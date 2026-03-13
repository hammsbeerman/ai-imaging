import os

from celery import shared_task
from django.db import close_old_connections
from django.utils import timezone

from indexer.models import Image, ProcessingStatus, PreviewStatus
from indexer.clip_embedder import embed_image
from indexer.qdrant import upsert_vector
from indexer.previews import abs_preview_path
from indexer.locks import acquire_lock, release_lock
from indexer.tasklog import log
from indexer.services.pipeline_logging import (
    log_stage_start,
    log_stage_ok,
    log_stage_skip,
    log_stage_error,
)


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"}


@shared_task
def queue_missing_embeddings_task(batch_size=500, chunk_size=25):
    close_old_connections()

    lock_key = "lock:queue_missing_embeddings_task"
    token = acquire_lock(lock_key, ttl=120)
    if not token:
        log("embedding", "queue skipped (lock held)")
        return

    try:
        ids = list(
            Image.objects
            .filter(
                embedding_status=ProcessingStatus.PENDING,
                skip_index=False,
                preview_status=PreviewStatus.OK,
            )
            .exclude(preview_path="")
            .values_list("id", flat=True)[:batch_size]
        )

        log("embedding", f"queue selected={len(ids)}")

        total_ok = 0
        total_failed = 0
        total_skipped = 0

        for i in range(0, len(ids), chunk_size):
            chunk = [str(x) for x in ids[i:i + chunk_size]]

            log("embedding", f"batch start selected={len(chunk)}")

            ok = 0
            failed = 0
            skipped = 0

            for image_id in chunk:
                try:
                    result = _embed_one(image_id)
                    if result == "ok":
                        ok += 1
                    elif result == "skipped":
                        skipped += 1
                    else:
                        failed += 1
                except Exception as e:
                    failed += 1
                    try:
                        img = Image.objects.get(id=image_id)
                        img.embedding_status = ProcessingStatus.FAILED
                        img.embedding_error = str(e)[:2000]
                        img.save(update_fields=["embedding_status", "embedding_error"])
                        log_stage_error("embedding", img, e)
                    except Exception:
                        log("embedding", f"FAILED image_id={image_id} error={str(e)[:500]}", "ERROR")
                    continue

            total_ok += ok
            total_failed += failed
            total_skipped += skipped

            log("embedding", f"batch done selected={len(chunk)} ok={ok} skipped={skipped} failed={failed}")

        return {
            "selected": len(ids),
            "ok": total_ok,
            "skipped": total_skipped,
            "failed": total_failed,
        }

    finally:
        release_lock(lock_key, token)


@shared_task
def process_embedding_batch_task(image_ids):
    close_old_connections()

    log("embedding", f"batch start selected={len(image_ids)}")

    ok = 0
    failed = 0
    skipped = 0

    for image_id in image_ids:
        try:
            result = _embed_one(str(image_id))
            if result == "ok":
                ok += 1
            elif result == "skipped":
                skipped += 1
            else:
                failed += 1
        except Exception as e:
            failed += 1
            try:
                img = Image.objects.get(id=image_id)
                img.embedding_status = ProcessingStatus.FAILED
                img.embedding_error = str(e)[:2000]
                img.save(update_fields=["embedding_status", "embedding_error"])
                log_stage_error("embedding", img, e)
            except Exception:
                log("embedding", f"FAILED image_id={image_id} error={str(e)[:500]}", "ERROR")
            continue

    log("embedding", f"batch done selected={len(image_ids)} ok={ok} skipped={skipped} failed={failed}")

    return {
        "selected": len(image_ids),
        "ok": ok,
        "skipped": skipped,
        "failed": failed,
    }


@shared_task
def embed_image_task(image_id):
    close_old_connections()
    try:
        result = _embed_one(str(image_id))
        return {"status": result, "image_id": str(image_id)}
    except Exception as e:
        img = Image.objects.get(id=image_id)

        img.embedding_status = ProcessingStatus.FAILED
        img.embedding_error = str(e)[:2000]

        img.save(update_fields=[
            "embedding_status",
            "embedding_error",
        ])

        log_stage_error("embedding", img, e)

        return {"ok": False, "id": image_id, "error": str(e)}


def _embed_one(image_id):
    img = Image.objects.get(id=image_id)

    img.embedding_status = ProcessingStatus.PROCESSING
    img.embedding_error = ""
    update_fields = ["embedding_status", "embedding_error"]
    if hasattr(img, "embedding_run_at"):
        img.embedding_run_at = timezone.now()
        update_fields.append("embedding_run_at")
    img.save(update_fields=update_fields)

    ext = (img.file_ext or img.ext or os.path.splitext(img.filename)[1]).lower()

    source_path = None
    preview_path = abs_preview_path(img.preview_path)

    if preview_path and os.path.exists(preview_path):
        source_path = preview_path
    elif ext in IMAGE_EXTENSIONS and os.path.exists(img.path):
        source_path = img.path

    if not source_path:
        img.embedding_status = ProcessingStatus.SKIPPED
        img.embedding_error = "no usable raster source for embedding"
        update_fields = ["embedding_status", "embedding_error"]
        if hasattr(img, "embedding_run_at"):
            img.embedding_run_at = timezone.now()
            update_fields.append("embedding_run_at")
        img.save(update_fields=update_fields)

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
        },
    )

    img.embedding_status = ProcessingStatus.OK
    img.embedding_error = ""
    img.indexed = True
    update_fields = ["embedding_status", "embedding_error", "indexed"]
    if hasattr(img, "embedding_run_at"):
        img.embedding_run_at = timezone.now()
        update_fields.append("embedding_run_at")
    img.save(update_fields=update_fields)

    log_stage_ok("embedding", img)
    return "ok"