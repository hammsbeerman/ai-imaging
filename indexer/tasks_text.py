import io
import os
import tempfile

from PIL import Image as PILImage
from celery import shared_task
from django.db import close_old_connections
from django.utils import timezone

from indexer.models import Image, ProcessingStatus, PreviewStatus
from indexer.ocr_utils import ocr_image, looks_like_useful_text, clean_ocr_text
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


@shared_task
def extract_text_task(image_id: str):
    close_old_connections()

    img = Image.objects.get(id=image_id)

    img.text_status = ProcessingStatus.PROCESSING
    img.text_error = ""
    update_fields = ["text_status", "text_error"]
    if hasattr(img, "text_run_at"):
        img.text_run_at = timezone.now()
        update_fields.append("text_run_at")
    img.save(update_fields=update_fields)

    try:
        _text_one(img)
        return {"ok": True, "id": image_id}
    except Exception as e:
        img.text_status = ProcessingStatus.FAILED
        img.text_error = str(e)[:2000]

        update_fields = ["text_status", "text_error"]
        if hasattr(img, "text_run_at"):
            img.text_run_at = timezone.now()
            update_fields.append("text_run_at")

        img.save(update_fields=update_fields)
        log_stage_error("text", img, e)
        return {"ok": False, "id": image_id, "error": str(e)}


@shared_task
def queue_missing_text_task(limit: int = 1000):
    close_old_connections()

    ids = list(
        Image.objects.filter(
            skip_index=False,
            text_status=ProcessingStatus.PENDING,
            preview_status=PreviewStatus.OK,
        ).values_list("id", flat=True)[:limit]
    )

    for image_id in ids:
        extract_text_task.delay(str(image_id))

    return {"queued": len(ids)}