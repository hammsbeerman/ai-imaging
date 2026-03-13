import os

from celery import shared_task
from django.db import close_old_connections
from django.utils import timezone

from indexer.folders import attach_image_to_folder
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
from indexer.services.pipeline_logging import (
    log_stage_start,
    log_stage_ok,
    log_stage_skip,
    log_stage_error,
)


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp", ".gif"}


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
    cleaned = {}
    for key, value in (md or {}).items():
        cleaned[key] = _clean_text_value(value)
    return cleaned


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

    _clean_model_text_fields(
        img,
        [
            "file_ext",
            "ext",
            "mime_type",
            "folder_tokens",
            "customer_name",
            "job_type",
            "camera_make",
            "camera_model",
            "sha256",
            "probable_job_number",
            "relative_dir",
            "orientation",
            "color_mode",
            "metadata_error",
        ],
    )

    update_fields = [
        "file_ext",
        "ext",
        "mime_type",
        "size",
        "mtime",
        "folder_tokens",
        "customer_name",
        "job_type",
        "width",
        "height",
        "image_width",
        "image_height",
        "dpi_x",
        "dpi_y",
        "camera_make",
        "camera_model",
        "gps_lat",
        "gps_lon",
        "captured_at",
        "metadata_status",
        "metadata_error",
        "metadata_version",
    ]

    optional_fields = [
        "file_size",
        "file_mtime",
        "file_ctime",
        "sha256",
        "probable_job_number",
        "relative_dir",
        "folder_depth",
        "aspect_ratio",
        "orientation",
        "color_mode",
        "bit_depth",
        "page_count",
        "exif_date_taken",
        "metadata_run_at",
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

    img = Image.objects.select_related("root", "folder").get(id=image_id)

    img.metadata_status = ProcessingStatus.PROCESSING
    img.metadata_error = ""
    update_fields = ["metadata_status", "metadata_error"]
    if hasattr(img, "metadata_run_at"):
        img.metadata_run_at = timezone.now()
        update_fields.append("metadata_run_at")
    img.save(update_fields=update_fields)

    try:
        _metadata_one(img)
        return {"ok": True, "id": image_id}
    except Exception as e:
        img.metadata_status = ProcessingStatus.FAILED
        img.metadata_error = _clean_text_value(str(e))[:2000]

        update_fields = ["metadata_status", "metadata_error"]
        if hasattr(img, "metadata_run_at"):
            img.metadata_run_at = timezone.now()
            update_fields.append("metadata_run_at")

        img.save(update_fields=update_fields)
        log_stage_error("metadata", img, e)
        return {"ok": False, "id": image_id, "error": str(e)}


@shared_task
def queue_missing_metadata_task(limit: int = 2000):
    close_old_connections()

    ids = list(
        Image.objects.filter(
            skip_index=False,
            metadata_status=ProcessingStatus.PENDING,
        ).values_list("id", flat=True)[:limit]
    )
    for image_id in ids:
        extract_metadata_task.delay(str(image_id))
    return {"queued": len(ids)}