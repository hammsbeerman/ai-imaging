import os

from celery import shared_task
from django.db import close_old_connections, transaction
from django.utils import timezone

from indexer.clip_embedder import embed_image
from indexer.locks import acquire_lock, release_lock
from indexer.models import Image, PreviewStatus, ProcessingStatus
from indexer.previews import abs_preview_path
from indexer.qdrant import upsert_vector
from indexer.tasklog import log
from indexer.tasks_metrics import record_task_metric
from indexer.services.pipeline_logging import log_stage_error, log_stage_ok, log_stage_skip, log_stage_start


QUEUE_PICK_LIMIT = 256
WORKER_BATCH_SIZE = 16
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}


def _chunked(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def _embedding_source_path(img: Image) -> str | None:
    preview_path = abs_preview_path(img.preview_path)
    thumb_path = abs_preview_path(img.thumb_path)

    if preview_path and os.path.exists(preview_path):
        return preview_path
    if thumb_path and os.path.exists(thumb_path):
        return thumb_path

    ext = (img.file_ext or img.ext or os.path.splitext(img.filename)[1]).lower()
    if ext in IMAGE_EXTENSIONS and img.path and os.path.exists(img.path):
        return img.path
    return None


def _mark_failed(img: Image, error: Exception | str):
    img.embedding_status = ProcessingStatus.FAILED
    img.embedding_error = str(error)[:2000]
    update_fields = ["embedding_status", "embedding_error"]
    if hasattr(img, "embedding_run_at"):
        img.embedding_run_at = timezone.now()
        update_fields.append("embedding_run_at")
    img.save(update_fields=update_fields)


def _mark_skipped(img: Image, reason: str):
    img.embedding_status = ProcessingStatus.SKIPPED
    img.embedding_error = reason
    update_fields = ["embedding_status", "embedding_error"]
    if hasattr(img, "embedding_run_at"):
        img.embedding_run_at = timezone.now()
        update_fields.append("embedding_run_at")
    img.save(update_fields=update_fields)


def _mark_ok(img: Image):
    img.embedding_status = ProcessingStatus.OK
    img.embedding_error = ""
    img.indexed = True
    update_fields = ["embedding_status", "embedding_error", "indexed"]
    if hasattr(img, "embedding_run_at"):
        img.embedding_run_at = timezone.now()
        update_fields.append("embedding_run_at")
    img.save(update_fields=update_fields)


def _embed_one(img: Image):
    source_path = _embedding_source_path(img)
    if not source_path:
        _mark_skipped(img, "no usable raster source for embedding")
        log_stage_skip("embedding", img, "no usable raster source")
        return "skipped"

    log_stage_start("embedding", img)
    vec = embed_image(source_path)
    if hasattr(vec, "tolist"):
        vec = vec.tolist()

    upsert_vector(
        image_id=str(img.id),
        vector=vec,
        payload={
            "path": img.path,
            "filename": img.filename,
            "root_id": img.root_id,
            "file_ext": img.file_ext or img.ext or "",
            "customer_name": img.customer_name or "",
            "job_type": img.job_type or "",
            "relative_dir": getattr(img, "relative_dir", "") or "",
            "probable_job_number": getattr(img, "probable_job_number", "") or "",
            "folder_id": img.folder_id,
        },
    )

    _mark_ok(img)
    log_stage_ok("embedding", img, f"source={os.path.basename(source_path)}")
    return "ok"


@shared_task
def embed_image_task(image_id):
    close_old_connections()
    try:
        img = Image.objects.get(id=image_id)
    except Image.DoesNotExist:
        return {"status": "missing", "image_id": str(image_id)}

    try:
        if img.embedding_status == ProcessingStatus.PENDING:
            img.embedding_status = ProcessingStatus.PROCESSING
            img.embedding_error = ""
            img.embedding_run_at = timezone.now()
            img.save(update_fields=["embedding_status", "embedding_error", "embedding_run_at"])
        result = _embed_one(img)
        return {"status": result, "image_id": str(image_id)}
    except Exception as e:
        _mark_failed(img, e)
        log_stage_error("embedding", img, e)
        return {"status": "failed", "image_id": str(image_id), "error": str(e)[:500]}


@shared_task
def process_embedding_batch_task(image_ids):
    close_old_connections()
    rows = Image.objects.filter(id__in=image_ids).only(
        "id", "path", "filename", "root_id", "file_ext", "ext", "preview_path", "thumb_path",
        "customer_name", "job_type", "relative_dir", "probable_job_number", "folder_id",
        "skip_index", "embedding_status", "embedding_error", "embedding_run_at", "indexed",
    )
    by_id = {str(img.id): img for img in rows}

    ok = 0
    failed = 0
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
        if img.embedding_status not in (ProcessingStatus.PROCESSING, ProcessingStatus.FAILED):
            skipped += 1
            continue
        try:
            result = _embed_one(img)
            if result == "ok":
                ok += 1
            else:
                skipped += 1
        except Exception as e:
            failed += 1
            _mark_failed(img, e)
            log_stage_error("embedding", img, e)

    return {"selected": len(image_ids), "ok": ok, "failed": failed, "skipped": skipped, "missing": missing}


@shared_task
def queue_missing_embeddings_task(batch_size=QUEUE_PICK_LIMIT, chunk_size=WORKER_BATCH_SIZE):
    close_old_connections()
    started_at = timezone.now()

    lock_key = "lock:queue_missing_embeddings_task"
    token = acquire_lock(lock_key, ttl=120)
    if not token:
        log("embedding", "queue skipped (lock held)")
        return

    try:
        with transaction.atomic():
            candidate_ids = list(
                Image.objects.filter(
                    skip_index=False,
                    embedding_status=ProcessingStatus.PENDING,
                    preview_status=PreviewStatus.OK,
                )
                .order_by("id")
                .values_list("id", flat=True)[:batch_size]
            )

            if not candidate_ids:
                return {"picked": 0, "claimed": 0, "submitted_batches": 0}

            claim_qs = Image.objects.filter(
                id__in=candidate_ids,
                skip_index=False,
                embedding_status=ProcessingStatus.PENDING,
                preview_status=PreviewStatus.OK,
            )
            claimed_ids = list(claim_qs.values_list("id", flat=True))
            if not claimed_ids:
                return {"picked": len(candidate_ids), "claimed": 0, "submitted_batches": 0}

            claim_count = claim_qs.update(
                embedding_status=ProcessingStatus.PROCESSING,
                embedding_error="",
                embedding_run_at=timezone.now(),
            )

        submitted = 0
        claimed_ids = [str(x) for x in claimed_ids[:claim_count]]
        for batch_ids in _chunked(claimed_ids, chunk_size):
            process_embedding_batch_task.delay(batch_ids)
            submitted += 1

        log("embedding", f"queue picked={len(candidate_ids)} claimed={len(claimed_ids)} submitted_batches={submitted}")
        details = {"picked": len(candidate_ids), "claimed": len(claimed_ids), "submitted_batches": submitted}
        record_task_metric("queue_missing_embeddings_task", started_at, details=details)
        return details

    finally:
        release_lock(lock_key, token)
