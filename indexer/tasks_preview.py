import os

from celery import shared_task
from django.db import close_old_connections
from django.db.models import Q
from django.utils import timezone

from indexer.models import Image, PreviewStatus
from indexer.previews import generate_preview, abs_preview_path
from indexer.tasklog import log
from indexer.task_helpers import acquire_lock, release_lock
from indexer.preview_health import preview_files_exist


PREVIEWABLE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff",
    ".pdf", ".svg", ".eps", ".ai", ".psd", ".indd",
}

UNSUPPORTED_PREVIEW_EXTS = {".ai", ".eps", ".indd", ".svgz"}


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
    img.save(
        update_fields=[
            "preview_status",
            "preview_path",
            "thumb_path",
            "preview_error",
            "preview_source",
            "preview_created_at",
        ]
    )


@shared_task
def queue_missing_previews_task(batch_size=50, chunk_size=5):
    lock_key = "lock:queue_missing_previews_task"
    token = acquire_lock(lock_key, ttl=120)
    if not token:
        log("preview", "queue skipped (lock held)")
        return

    try:
        ids = list(
            Image.objects
            .filter(
                skip_index=False,
                preview_status=PreviewStatus.PENDING,
            )
            .values_list("id", flat=True)[:batch_size]
        )

        ids = [str(x) for x in ids]

        log("preview", f"queue selected={len(ids)}")

        total_ok = 0
        total_failed = 0
        total_unsupported = 0
        total_skipped = 0

        for i in range(0, len(ids), chunk_size):
            chunk = ids[i:i + chunk_size]
            log("preview", f"batch start selected={len(chunk)}")

            ok = 0
            failed = 0
            unsupported = 0
            skipped = 0

            for image_id in chunk:
                try:
                    result = _preview_one(image_id)
                    if result == "ok":
                        ok += 1
                    elif result == "unsupported":
                        unsupported += 1
                    elif result == "skipped":
                        skipped += 1
                    else:
                        failed += 1
                except Exception as e:
                    failed += 1
                    log("preview", f"FAILED image_id={image_id} error={str(e)[:500]}", "ERROR")

            total_ok += ok
            total_failed += failed
            total_unsupported += unsupported
            total_skipped += skipped

            log(
                "preview",
                f"batch done selected={len(chunk)} ok={ok} unsupported={unsupported} failed={failed} skipped={skipped}",
            )

        return {
            "selected": len(ids),
            "ok": total_ok,
            "unsupported": total_unsupported,
            "failed": total_failed,
            "skipped": total_skipped,
        }

    finally:
        release_lock(lock_key, token)


@shared_task
def process_preview_task(image_id, force=False):
    """
    Compatibility wrapper for manual retries / existing imports.
    """
    close_old_connections()
    return {
        "status": _preview_one(str(image_id), force=force),
        "image_id": str(image_id),
    }


def _preview_one(image_id, force=False):
    img = Image.objects.get(id=image_id)
    ext = (img.file_ext or img.ext or os.path.splitext(img.filename)[1]).lower()

    if not force and img.preview_status == PreviewStatus.OK:
        if preview_files_exist(img):
            log("preview", f"skip existing image_id={img.id} file={img.filename}")
            return "skipped"

        log("preview", f"missing files reset image_id={img.id} file={img.filename}")
        _reset_missing_preview(img)

    if ext not in PREVIEWABLE_EXTENSIONS:
        img.preview_status = PreviewStatus.UNSUPPORTED
        img.preview_error = f"preview unsupported for {ext or 'unknown type'}"
        img.preview_source = "unsupported"
        img.save(update_fields=["preview_status", "preview_error", "preview_source"])
        log("preview", f"unsupported image_id={img.id} file={img.filename} ext={ext}")
        return "unsupported"

    try:
        if force:
            log("preview", f"force rebuild image_id={img.id} file={img.filename}")
        else:
            log("preview", f"start image_id={img.id} file={img.filename}")

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

            # Keep existing preview/thumb fields on failure.
            # Do not wipe usable current output if regeneration fails.

            img.save(update_fields=[
                "preview_status",
                "preview_error",
                "preview_source",
            ])

            level = "INFO" if preview_result == "unsupported" else "ERROR"
            log(
                "preview",
                f"{preview_result.upper()} image_id={img.id} file={img.filename} error={msg[:500]}",
                level,
            )
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

        log("preview", f"ok image_id={img.id} file={img.filename}")
        return "ok"

    except Exception as e:
        msg = str(e)[:2000]

        if _is_expected_unsupported_preview_error(msg):
            img.preview_status = PreviewStatus.UNSUPPORTED
            img.preview_error = msg
            img.preview_source = "unsupported"

            # Keep existing preview/thumb data on unsupported failure too.

            img.save(update_fields=[
                "preview_status",
                "preview_error",
                "preview_source",
            ])
            log("preview", f"UNSUPPORTED image_id={img.id} file={img.filename} error={msg[:500]}", "INFO")
            return "unsupported"

        img.preview_status = PreviewStatus.FAILED
        img.preview_error = msg
        img.save(update_fields=["preview_status", "preview_error"])
        log("preview", f"FAILED image_id={img.id} file={img.filename} error={msg[:500]}", "ERROR")
        return "failed"

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