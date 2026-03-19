import os

from celery import shared_task
from django.db import close_old_connections, transaction
from django.utils import timezone

from indexer.folders import attach_image_to_folder
from indexer.locks import acquire_lock, release_lock
from indexer.metadata_utils import (
    build_folder_tokens,
    clean_customer_name,
    extract_image_metadata,
    extract_probable_job_number,
    file_sha256,
    guess_mime_type,
    normalized_ext,
    relative_dir,
    folder_depth,
    safe_stat,
)
from indexer.models import Image, ProcessingStatus
from indexer.services.pipeline_logging import log_stage_start, log_stage_ok, log_stage_error
from indexer.tasklog import log
from indexer.tasks_metrics import record_task_metric


QUEUE_PICK_LIMIT = 512
WORKER_BATCH_SIZE = 32
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp", ".gif"}

METADATA_PROCESSING_CAP = 5000


def _chunked(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def _clean_text_value(value):
    if value is None:
        return value
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="ignore")
    if isinstance(value, str):
        return value.replace("\x00", "").strip()
    return value


def _clean_model_text_fields(img: Image, field_names: list[str]) -> None:
    for field in field_names:
        if hasattr(img, field):
            setattr(img, field, _clean_text_value(getattr(img, field, None)))


def _clean_metadata_dict(md: dict) -> dict:
    return {key: _clean_text_value(value) for key, value in (md or {}).items()}


def _derive_customer_name(path: str) -> str:
    parts = path.replace("\\", "/").split("/")
    for i, part in enumerate(parts):
        if part.lower() == "customers" and i + 1 < len(parts):
            return clean_customer_name(parts[i + 1])
    if len(parts) >= 2:
        return clean_customer_name(parts[-2])
    return ""


def _derive_job_type(path: str, ext: str) -> str:
    ext = (ext or "").lower()
    parts = path.lower()
    if ext in {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".gif", ".webp"}:
        return "image"
    if ext == ".pdf":
        return "pdf"
    if ext in {".ai", ".eps", ".svg"}:
        return "vector"
    if "wedding" in parts:
        return "wedding"
    if "school" in parts:
        return "school"
    return "file"


def _root_base_for_image(img: Image) -> str:
    if getattr(img, "root_id", None) and getattr(img, "root", None) and img.root.scan_path_root:
        return img.root.scan_path_root
    return "/mnt/archive"


def _metadata_one(img: Image) -> None:
    path = img.path
    log_stage_start("metadata", img)

    ext = normalized_ext(path)
    img.file_ext = _clean_text_value(ext)
    if not img.ext:
        img.ext = _clean_text_value(ext)

    img.mime_type = _clean_text_value(guess_mime_type(path))

    st = safe_stat(path)
    img.size = st["file_size"]
    img.mtime = st["file_mtime"]

    if hasattr(img, "file_size"):
        img.file_size = st["file_size"]
    if hasattr(img, "file_mtime"):
        img.file_mtime = st["file_mtime"]
    if hasattr(img, "file_ctime"):
        img.file_ctime = st["file_ctime"]
    if hasattr(img, "sha256") and not img.sha256:
        img.sha256 = _clean_text_value(file_sha256(path))

    img.folder_tokens = _clean_text_value(build_folder_tokens(path))
    img.customer_name = _clean_text_value(_derive_customer_name(path))
    img.job_type = _clean_text_value(_derive_job_type(path, ext))

    root_base = _root_base_for_image(img)
    if hasattr(img, "probable_job_number"):
        img.probable_job_number = _clean_text_value(extract_probable_job_number(path))
    if hasattr(img, "relative_dir"):
        img.relative_dir = _clean_text_value(relative_dir(path, root=root_base))
        if img.relative_dir in (".",):
            img.relative_dir = ""
    if hasattr(img, "folder_depth"):
        img.folder_depth = folder_depth(path, root=root_base)

    if ext in IMAGE_EXTS:
        md = _clean_metadata_dict(extract_image_metadata(path))
        img.width = md.get("width")
        img.height = md.get("height")
        if hasattr(img, "image_width"):
            img.image_width = md.get("width")
        if hasattr(img, "image_height"):
            img.image_height = md.get("height")

        img.dpi_x = md.get("dpi_x")
        img.dpi_y = md.get("dpi_y")
        img.camera_make = md.get("camera_make", "")
        img.camera_model = md.get("camera_model", "")
        img.gps_lat = md.get("gps_lat")
        img.gps_lon = md.get("gps_lon")

        if md.get("exif_date_taken"):
            img.captured_at = md.get("exif_date_taken")

        if hasattr(img, "aspect_ratio"):
            img.aspect_ratio = md.get("aspect_ratio")
        if hasattr(img, "orientation"):
            img.orientation = md.get("orientation", "")
        if hasattr(img, "color_mode"):
            img.color_mode = md.get("color_mode", "")
        if hasattr(img, "bit_depth"):
            img.bit_depth = md.get("bit_depth")
        if hasattr(img, "page_count"):
            img.page_count = md.get("page_count")
        if hasattr(img, "exif_date_taken"):
            img.exif_date_taken = md.get("exif_date_taken")

    img.metadata_status = ProcessingStatus.OK
    img.metadata_error = ""
    if hasattr(img, "metadata_run_at"):
        img.metadata_run_at = timezone.now()

    img.metadata_version = (img.metadata_version or 0) + 1 if isinstance(img.metadata_version, int) else 2

    _clean_model_text_fields(img, [
        "file_ext", "ext", "mime_type", "folder_tokens", "customer_name", "job_type",
        "camera_make", "camera_model", "sha256", "probable_job_number", "relative_dir",
        "orientation", "color_mode", "metadata_error",
    ])

    update_fields = [
        "file_ext", "ext", "mime_type", "size", "mtime", "folder_tokens", "customer_name",
        "job_type", "width", "height", "image_width", "image_height", "dpi_x", "dpi_y",
        "camera_make", "camera_model", "gps_lat", "gps_lon", "captured_at", "metadata_status",
        "metadata_error", "metadata_version",
    ]
    optional_fields = [
        "file_size", "file_mtime", "file_ctime", "sha256", "probable_job_number", "relative_dir",
        "folder_depth", "aspect_ratio", "orientation", "color_mode", "bit_depth", "page_count",
        "exif_date_taken", "metadata_run_at",
    ]
    for field in optional_fields:
        if hasattr(img, field):
            update_fields.append(field)

    seen = set()
    update_fields = [f for f in update_fields if not (f in seen or seen.add(f))]

    img.save(update_fields=update_fields)
    attach_image_to_folder(img)
    log_stage_ok("metadata", img, f"ext={ext}")


@shared_task
def extract_metadata_task(image_id: str):
    close_old_connections()
    try:
        img = Image.objects.select_related("root", "folder").get(id=image_id)
    except Image.DoesNotExist:
        return {"ok": False, "id": image_id, "error": "missing"}

    if img.metadata_status == ProcessingStatus.PENDING:
        img.metadata_status = ProcessingStatus.PROCESSING
        img.metadata_error = ""
        img.metadata_run_at = timezone.now()
        img.save(update_fields=["metadata_status", "metadata_error", "metadata_run_at"])

    try:
        _metadata_one(img)
        return {"ok": True, "id": image_id}
    except Exception as e:
        img.metadata_status = ProcessingStatus.FAILED
        img.metadata_error = _clean_text_value(str(e))[:2000]
        img.metadata_run_at = timezone.now()
        img.save(update_fields=["metadata_status", "metadata_error", "metadata_run_at"])
        log_stage_error("metadata", img, e)
        return {"ok": False, "id": image_id, "error": str(e)}


@shared_task
def process_metadata_batch_task(image_ids):
    close_old_connections()
    rows = Image.objects.filter(id__in=image_ids).select_related("root", "folder")
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
        if img.metadata_status not in (ProcessingStatus.PROCESSING, ProcessingStatus.FAILED):
            skipped += 1
            continue

        try:
            _metadata_one(img)
            ok += 1
        except Exception as e:
            failed += 1
            img.metadata_status = ProcessingStatus.FAILED
            img.metadata_error = _clean_text_value(str(e))[:2000]
            img.metadata_run_at = timezone.now()
            img.save(update_fields=["metadata_status", "metadata_error", "metadata_run_at"])
            log_stage_error("metadata", img, e)

    return {"selected": len(image_ids), "ok": ok, "failed": failed, "skipped": skipped, "missing": missing}


@shared_task
def queue_missing_metadata_task(limit: int = QUEUE_PICK_LIMIT, chunk_size: int = WORKER_BATCH_SIZE):
    close_old_connections()
    started_at = timezone.now()
    lock_key = "lock:queue_missing_metadata_task"
    token = acquire_lock(lock_key, ttl=120)
    if not token:
        log("metadata", "queue skipped (lock held)")
        return {
            "picked": 0,
            "claimed": 0,
            "submitted_batches": 0,
            "reason": "lock held",
        }

    try:
        current_processing = Image.objects.filter(
            skip_index=False,
            metadata_status=ProcessingStatus.PROCESSING,
        ).count()

        if current_processing >= METADATA_PROCESSING_CAP:
            details = {
                "picked": 0,
                "claimed": 0,
                "submitted_batches": 0,
                "reason": "processing cap reached",
                "processing_cap": METADATA_PROCESSING_CAP,
                "current_processing": current_processing,
            }
            log(
                "metadata",
                f"queue skipped processing_cap current_processing={current_processing} cap={METADATA_PROCESSING_CAP}",
            )
            record_task_metric("queue_missing_metadata_task", started_at, details=details)
            return details

        allowed_to_claim = max(METADATA_PROCESSING_CAP - current_processing, 0)
        effective_limit = min(limit, allowed_to_claim)

        if effective_limit <= 0:
            details = {
                "picked": 0,
                "claimed": 0,
                "submitted_batches": 0,
                "reason": "no claim room",
                "processing_cap": METADATA_PROCESSING_CAP,
                "current_processing": current_processing,
            }
            record_task_metric("queue_missing_metadata_task", started_at, details=details)
            return details

        with transaction.atomic():
            candidate_ids = list(
                Image.objects.filter(
                    skip_index=False,
                    metadata_status=ProcessingStatus.PENDING,
                )
                .order_by("id")
                .values_list("id", flat=True)[:effective_limit]
            )

            if not candidate_ids:
                details = {
                    "picked": 0,
                    "claimed": 0,
                    "submitted_batches": 0,
                    "processing_cap": METADATA_PROCESSING_CAP,
                    "current_processing": current_processing,
                }
                record_task_metric("queue_missing_metadata_task", started_at, details=details)
                return details

            claim_qs = Image.objects.filter(
                id__in=candidate_ids,
                skip_index=False,
                metadata_status=ProcessingStatus.PENDING,
            )
            claimed_ids = list(claim_qs.values_list("id", flat=True))

            if not claimed_ids:
                details = {
                    "picked": len(candidate_ids),
                    "claimed": 0,
                    "submitted_batches": 0,
                    "processing_cap": METADATA_PROCESSING_CAP,
                    "current_processing": current_processing,
                }
                record_task_metric("queue_missing_metadata_task", started_at, details=details)
                return details

            claimed = claim_qs.update(
                metadata_status=ProcessingStatus.PROCESSING,
                metadata_error="",
                metadata_run_at=timezone.now(),
            )

        submitted = 0
        claimed_ids = [str(x) for x in claimed_ids[:claimed]]
        for batch_ids in _chunked(claimed_ids, chunk_size):
            process_metadata_batch_task.delay(batch_ids)
            submitted += 1

        log(
            "metadata",
            f"queue picked={len(candidate_ids)} claimed={len(claimed_ids)} submitted_batches={submitted} "
            f"current_processing={current_processing} cap={METADATA_PROCESSING_CAP}",
        )
        details = {
            "picked": len(candidate_ids),
            "claimed": len(claimed_ids),
            "submitted_batches": submitted,
            "processing_cap": METADATA_PROCESSING_CAP,
            "current_processing": current_processing,
        }
        record_task_metric("queue_missing_metadata_task", started_at, details=details)
        return details

    finally:
        release_lock(lock_key, token)