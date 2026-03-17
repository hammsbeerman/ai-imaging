import os

from celery import shared_task
from django.db import close_old_connections, transaction
from django.utils import timezone

from indexer.locks import acquire_lock, release_lock
from indexer.models import Image, PreviewStatus
from indexer.preview_health import preview_files_exist
from indexer.previews import generate_preview
from indexer.tasklog import log
from indexer.tasks_metrics import record_task_metric


QUEUE_PICK_LIMIT = 128
WORKER_BATCH_SIZE = 16
PREVIEWABLE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff",
    ".pdf", ".svg", ".eps", ".ai", ".psd", ".indd",
}

UNSUPPORTED_PREVIEW_EXTS = {".ai", ".eps", ".indd", ".svgz"}


def _chunked(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def _is_expected_unsupported_preview_error(msg: str) -> bool:
    msg = msg or ""
    return (
        "Ghostscript not installed" in msg
        or "SVG size is undefined" in msg
        or "Skipped font helper SVG" in msg
        or "No sibling PDF and no embedded INDD preview found" in msg
        or "No embedded INDD preview found" in msg
        or "Unsupported extension:" in msg
    )


def _reset_missing_preview(img: Image, reason: str = "Preview file missing; regenerating") -> None:
    img.preview_status = PreviewStatus.PENDING
    img.preview_path = ""
    img.thumb_path = ""
    img.preview_error = reason
    img.preview_source = ""
    img.preview_created_at = None
    img.save(update_fields=[
        "preview_status",
        "preview_path",
        "thumb_path",
        "preview_error",
        "preview_source",
        "preview_created_at",
    ])


def _preview_one(img: Image, force: bool = False):
    ext = (img.file_ext or img.ext or os.path.splitext(img.filename)[1]).lower()

    if not force and img.preview_status == PreviewStatus.OK:
        if preview_files_exist(img):
            return "skipped"
        _reset_missing_preview(img)

    if ext not in PREVIEWABLE_EXTENSIONS:
        img.preview_status = PreviewStatus.UNSUPPORTED
        img.preview_error = f"preview unsupported for {ext or 'unknown type'}"
        img.preview_source = "unsupported"
        img.save(update_fields=["preview_status", "preview_error", "preview_source"])
        return "unsupported"

    try:
        result = generate_preview(img.path)

        if not result.ok:
            msg = (result.error or "unknown preview failure")[:2000]
            if _is_expected_unsupported_preview_error(msg):
                img.preview_status = PreviewStatus.UNSUPPORTED
                preview_result = "unsupported"
            else:
                img.preview_status = PreviewStatus.FAILED
                preview_result = "failed"

            img.preview_error = msg
            img.preview_source = "unsupported" if preview_result == "unsupported" else (img.preview_source or "")
            img.save(update_fields=["preview_status", "preview_error", "preview_source"])
            return preview_result

        img.preview_status = PreviewStatus.OK
        img.preview_source = result.preview_source or ""
        img.preview_path = result.preview_path or img.preview_path or ""
        img.thumb_path = result.thumb_path or img.thumb_path or ""
        img.width = result.width
        img.height = result.height
        img.preview_created_at = timezone.now()
        img.preview_error = ""
        img.save(update_fields=[
            "preview_status",
            "preview_source",
            "preview_path",
            "thumb_path",
            "width",
            "height",
            "preview_created_at",
            "preview_error",
        ])
        return "ok"

    except Exception as e:
        msg = str(e)[:2000]
        if _is_expected_unsupported_preview_error(msg):
            img.preview_status = PreviewStatus.UNSUPPORTED
            img.preview_error = msg
            img.preview_source = "unsupported"
            img.save(update_fields=["preview_status", "preview_error", "preview_source"])
            return "unsupported"

        img.preview_status = PreviewStatus.FAILED
        img.preview_error = msg
        img.save(update_fields=["preview_status", "preview_error"])
        return "failed"


@shared_task
def queue_missing_previews_task(batch_size=QUEUE_PICK_LIMIT, chunk_size=WORKER_BATCH_SIZE):
    close_old_connections()
    started_at = timezone.now()
    lock_key = "lock:queue_missing_previews_task"
    token = acquire_lock(lock_key, ttl=120)
    if not token:
        log("preview", "queue skipped (lock held)")
        return

    try:
        with transaction.atomic():
            candidate_ids = list(
                Image.objects.filter(
                    skip_index=False,
                    preview_status=PreviewStatus.PENDING,
                )
                .order_by("id")
                .values_list("id", flat=True)[:batch_size]
            )

            if not candidate_ids:
                return {"picked": 0, "claimed": 0, "submitted_batches": 0}

            claimed_qs = Image.objects.filter(
                id__in=candidate_ids,
                preview_status=PreviewStatus.PENDING,
                skip_index=False,
            )
            claimed_ids = list(claimed_qs.values_list("id", flat=True))
            if not claimed_ids:
                return {"picked": len(candidate_ids), "claimed": 0, "submitted_batches": 0}

            claimed = claimed_qs.update(
                preview_status=PreviewStatus.PROCESSING,
                preview_error="",
                preview_created_at=timezone.now(),
            )

        submitted = 0
        claimed_ids = [str(x) for x in claimed_ids[:claimed]]
        for batch_ids in _chunked(claimed_ids, chunk_size):
            process_preview_batch_task.delay(batch_ids)
            submitted += 1

        log("preview", f"queue picked={len(candidate_ids)} claimed={len(claimed_ids)} submitted_batches={submitted}")
        details = {"picked": len(candidate_ids), "claimed": len(claimed_ids), "submitted_batches": submitted}
        record_task_metric("queue_missing_previews_task", started_at, details=details)
        return details

    finally:
        release_lock(lock_key, token)


@shared_task
def process_preview_task(image_id, force=False):
    close_old_connections()
    try:
        img = Image.objects.get(id=image_id)
    except Image.DoesNotExist:
        return {"status": "missing", "image_id": str(image_id)}
    return {"status": _preview_one(img, force=force), "image_id": str(image_id)}


@shared_task
def process_preview_batch_task(image_ids):
    close_old_connections()

    rows = Image.objects.filter(id__in=image_ids).only(
        "id", "filename", "path", "file_ext", "ext", "skip_index",
        "preview_status", "preview_error", "preview_source",
        "preview_path", "thumb_path", "preview_created_at",
        "width", "height",
    )
    by_id = {str(img.id): img for img in rows}

    ok = 0
    failed = 0
    unsupported = 0
    skipped = 0
    missing = 0

    for image_id in image_ids:
        img = by_id.get(str(image_id))
        if not img:
            missing += 1
            continue
        if img.skip_index:
            skipped += 1
            continue
        if img.preview_status not in (PreviewStatus.PROCESSING, PreviewStatus.FAILED):
            skipped += 1
            continue

        result = _preview_one(img)
        if result == "ok":
            ok += 1
        elif result == "unsupported":
            unsupported += 1
        elif result == "failed":
            failed += 1
        else:
            skipped += 1

    return {
        "selected": len(image_ids),
        "ok": ok,
        "unsupported": unsupported,
        "failed": failed,
        "skipped": skipped,
        "missing": missing,
    }


@shared_task
def repair_missing_previews_task(batch_size=500):
    close_old_connections()

    qs = (
        Image.objects
        .filter(preview_status=PreviewStatus.OK)
        .exclude(preview_path__isnull=True)
        .exclude(preview_path="")
        .order_by("created")[:batch_size]
    )

    scanned = 0
    reset = 0

    for img in qs:
        scanned += 1
        if preview_files_exist(img):
            continue
        _reset_missing_preview(img, reason="Preview file missing; reset for regeneration")
        reset += 1

    log("preview_repair", f"finished scanned={scanned} reset={reset}")
    return {"scanned": scanned, "reset": reset}
