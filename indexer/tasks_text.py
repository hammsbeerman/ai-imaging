import io
import os
import tempfile

from PIL import Image as PILImage
from celery import shared_task
from django.db import close_old_connections, transaction
from django.utils import timezone

from indexer.models import Image, ProcessingStatus, PreviewStatus
from indexer.ocr_utils import ocr_image, looks_like_useful_text, clean_ocr_text
from indexer.locks import acquire_lock, release_lock
from indexer.tasklog import log
from indexer.tasks_metrics import record_task_metric
from indexer.services.pipeline_logging import (
    log_stage_start,
    log_stage_ok,
    log_stage_skip,
    log_stage_error,
)

try:
    import fitz  # pymupdf
except Exception:
    fitz = None


IMAGE_TEXT_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}


def _extract_pdf_text_if_present(path: str) -> str:
    try:
        from indexer.text_extract import extract_pdf_text
        return extract_pdf_text(path) or ""
    except Exception:
        return ""


def _extract_pdf_ocr_text(path: str, max_pages: int = 3) -> str:
    if not fitz:
        return ""

    parts = []

    doc = fitz.open(path)
    try:
        page_count = min(len(doc), max_pages)

        for page_num in range(page_count):
            page = doc.load_page(page_num)
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)

            img = PILImage.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")

            with tempfile.NamedTemporaryFile(suffix=".png", delete=True) as tmp:
                img.save(tmp.name, format="PNG")
                result = ocr_image(tmp.name, language="eng")

            text_clean = result.get("text_clean", "") or ""
            text_raw = result.get("text_raw", "") or ""

            if looks_like_useful_text(text_clean):
                parts.append(text_raw)

        return "\n\n".join(parts).strip()
    finally:
        doc.close()


def _save_text_success(
    img: Image,
    *,
    raw_text: str,
    clean_text: str,
    source: str,
    engine: str,
    confidence,
    language: str = "eng",
) -> None:
    img.text = raw_text
    img.extracted_text = raw_text

    if hasattr(img, "extracted_text_clean"):
        img.extracted_text_clean = clean_text
    if hasattr(img, "text_source"):
        img.text_source = source
    if hasattr(img, "text_engine"):
        img.text_engine = engine
    if hasattr(img, "text_confidence"):
        img.text_confidence = confidence
    if hasattr(img, "text_language"):
        img.text_language = language
    if hasattr(img, "text_length"):
        img.text_length = len(clean_text)
    if hasattr(img, "text_run_at"):
        img.text_run_at = timezone.now()

    img.text_status = ProcessingStatus.OK
    img.text_error = ""
    img.text_version = (img.text_version or 0) + 1 if isinstance(img.text_version, int) else 2

    update_fields = [
        "text",
        "extracted_text",
        "text_status",
        "text_error",
        "text_version",
    ]

    optional_fields = [
        "extracted_text_clean",
        "text_source",
        "text_engine",
        "text_confidence",
        "text_language",
        "text_length",
        "text_run_at",
    ]
    for field in optional_fields:
        if hasattr(img, field):
            update_fields.append(field)

    img.save(update_fields=update_fields)


def _save_text_skipped(img: Image, reason: str) -> None:
    img.text_status = ProcessingStatus.SKIPPED
    img.text_error = reason

    if hasattr(img, "text_run_at"):
        img.text_run_at = timezone.now()

    img.text_version = (img.text_version or 0) + 1 if isinstance(img.text_version, int) else 2

    update_fields = ["text_status", "text_error", "text_version"]
    if hasattr(img, "text_run_at"):
        update_fields.append("text_run_at")

    img.save(update_fields=update_fields)


def _text_one(img: Image) -> None:
    ext = (img.file_ext or img.ext or os.path.splitext(img.path)[1]).lower()

    log_stage_start("text", img)

    if ext == ".pdf":
        pdf_text = _extract_pdf_text_if_present(img.path)
        pdf_text_clean = clean_ocr_text(pdf_text)

        if looks_like_useful_text(pdf_text_clean):
            _save_text_success(
                img,
                raw_text=pdf_text,
                clean_text=pdf_text_clean,
                source="pdf_text",
                engine="native_pdf",
                confidence=100.0,
            )
            log_stage_ok("text", img, "source=pdf_text")
            return

        pdf_ocr_text = _extract_pdf_ocr_text(img.path, max_pages=3)
        pdf_ocr_text_clean = clean_ocr_text(pdf_ocr_text)

        if looks_like_useful_text(pdf_ocr_text_clean):
            _save_text_success(
                img,
                raw_text=pdf_ocr_text,
                clean_text=pdf_ocr_text_clean,
                source="pdf_ocr",
                engine="tesseract_pdf_render",
                confidence=None,
            )
            log_stage_ok("text", img, "source=pdf_ocr")
            return

        _save_text_skipped(img, "PDF has no useful embedded text or OCR text")
        log_stage_skip("text", img, "pdf has no useful embedded text or OCR text")
        return

    if ext in IMAGE_TEXT_EXTS:
        result = ocr_image(img.path, language="eng")

        text_clean = result.get("text_clean", "") or ""
        text_raw = result.get("text_raw", "") or ""

        if looks_like_useful_text(text_clean):
            _save_text_success(
                img,
                raw_text=text_raw,
                clean_text=text_clean,
                source=result.get("source", "ocr_image"),
                engine=result.get("engine", "tesseract"),
                confidence=result.get("confidence"),
                language=result.get("language", "eng"),
            )
            log_stage_ok("text", img, f"source={getattr(img, 'text_source', 'ocr_image')}")
            return

        _save_text_skipped(img, "No useful text detected")
        log_stage_skip("text", img, "no useful text detected")
        return

    _save_text_skipped(img, f"Unsupported text extraction type: {ext or 'unknown'}")
    log_stage_skip("text", img, f"unsupported type {ext or 'unknown'}")


def _process_one_text_id(image_id: str) -> str:
    img = Image.objects.get(id=image_id)

    if img.text_status != ProcessingStatus.PROCESSING:
        img.text_status = ProcessingStatus.PROCESSING
    img.text_error = ""
    update_fields = ["text_status", "text_error"]
    if hasattr(img, "text_run_at"):
        img.text_run_at = timezone.now()
        update_fields.append("text_run_at")
    img.save(update_fields=update_fields)

    try:
        _text_one(img)
        return "ok"
    except Exception as e:
        img.text_status = ProcessingStatus.FAILED
        img.text_error = str(e)[:2000]

        update_fields = ["text_status", "text_error"]
        if hasattr(img, "text_run_at"):
            img.text_run_at = timezone.now()
            update_fields.append("text_run_at")

        img.save(update_fields=update_fields)
        log_stage_error("text", img, e)
        return "failed"


@shared_task
def extract_text_task(image_id: str):
    close_old_connections()
    result = _process_one_text_id(str(image_id))
    return {"status": result, "id": str(image_id)}


@shared_task
def process_text_batch_task(image_ids):
    close_old_connections()

    ok = 0
    failed = 0

    for image_id in image_ids:
        result = _process_one_text_id(str(image_id))
        if result == "ok":
            ok += 1
        else:
            failed += 1

    return {
        "selected": len(image_ids),
        "ok": ok,
        "failed": failed,
    }


@shared_task
def queue_missing_text_task(batch_size: int = 500, chunk_size: int = 25):
    close_old_connections()

    lock_key = "lock:queue_missing_text_task"
    token = acquire_lock(lock_key, ttl=120)
    if not token:
        log("text", "queue skipped (lock held)")
        return

    try:
        ids = list(
            Image.objects.filter(
                skip_index=False,
                text_status=ProcessingStatus.PENDING,
                preview_status=PreviewStatus.OK,
            ).values_list("id", flat=True)[:batch_size]
        )

        log("text", f"queue selected={len(ids)}")

        total_ok = 0
        total_failed = 0

        for i in range(0, len(ids), chunk_size):
            chunk = [str(x) for x in ids[i:i + chunk_size]]

            ok = 0
            failed = 0

            for image_id in chunk:
                result = _process_one_text_id(image_id)
                if result == "ok":
                    ok += 1
                else:
                    failed += 1

            total_ok += ok
            total_failed += failed

            log("text", f"batch done selected={len(chunk)} ok={ok} failed={failed}")

        return {
            "selected": len(ids),
            "ok": total_ok,
            "failed": total_failed,
        }
    finally:
        release_lock(lock_key, token)