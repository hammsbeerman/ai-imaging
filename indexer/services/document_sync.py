import hashlib

from django.utils import timezone

from indexer.models import Image
from indexer.models_documents import Document
from indexer.services.document_pages import refresh_document_pages
from indexer.services.document_text import (
    build_summary,
    classify_document,
    compute_confidence_score,
    extract_entities,
    extract_invoice_data,
    make_search_text,
    normalize_clean_text,
    parse_document_date,
)
from indexer.services.document_vendor import guess_vendor_from_email

SUPPORTED_DOCUMENT_EXTS = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}


def is_supported_document_image(image: Image) -> bool:
    ext = (image.file_ext or image.ext or "").lower()
    return ext in SUPPORTED_DOCUMENT_EXTS


def _make_duplicate_group(sha256_value: str) -> str:
    if not sha256_value:
        return ""
    return hashlib.sha1(sha256_value.encode("utf-8")).hexdigest()[:24]


def sync_document_from_image(image: Image) -> Document:
    doc, _ = Document.objects.get_or_create(image=image)
    doc.sync_status = Document.SYNC_PROCESSING
    doc.processing_error = ""
    doc.save(update_fields=["sync_status", "processing_error", "updated_at"])

    clean_text = normalize_clean_text(
        image.extracted_text_clean or image.extracted_text or image.text or ""
    )
    search_text = make_search_text(clean_text)
    summary = build_summary(clean_text)
    entities = extract_entities(clean_text)
    document_type = classify_document(clean_text, filename=image.filename or "")
    invoice_data = extract_invoice_data(clean_text)

    email_attachment = image.email_attachments.select_related("email").order_by("id").first()
    email_obj = email_attachment.email if email_attachment else None
    email_vendor = guess_vendor_from_email(email_obj.from_email) if email_obj else ""

    confidence_score = compute_confidence_score(
        text_source=image.text_source or "",
        text_length=len(clean_text),
        text_confidence=image.text_confidence,
        document_type=document_type,
        entities=entities,
        invoice_data=invoice_data,
        page_count=image.page_count,
    )

    doc.original_filename = image.filename or ""
    doc.source_path = image.path or ""
    doc.file_ext = image.file_ext or image.ext or ""
    doc.mime_type = image.mime_type or ""
    doc.sha256 = image.sha256 or ""
    doc.file_size = image.file_size or image.size
    doc.page_count = image.page_count

    if not doc.title:
        doc.title = image.filename or ""

    doc.ocr_text = image.extracted_text or image.text or ""
    doc.ocr_text_preview = clean_text[:1000]
    doc.extracted_text_clean = clean_text
    doc.extracted_text_search = search_text
    doc.extracted_text_summary = summary

    doc.text_source = image.text_source or ""
    doc.text_engine = image.text_engine or ""
    doc.text_confidence = image.text_confidence
    doc.text_length = len(clean_text)
    doc.text_language = image.text_language or ""

    doc.document_type = document_type
    doc.detected_emails = entities["emails"]
    doc.detected_phones = entities["phones"]
    doc.detected_dates = entities["dates"]
    doc.detected_money = entities["money"]
    doc.detected_keywords = entities["keywords"]

    doc.invoice_number = invoice_data["invoice_number"]
    doc.invoice_total = invoice_data["invoice_total"]
    doc.invoice_due_date = invoice_data["invoice_due_date"]
    if not doc.invoice_vendor:
        doc.invoice_vendor = email_vendor or invoice_data["invoice_vendor"]

    doc.document_date = parse_document_date(doc.invoice_due_date)

    dup_group = _make_duplicate_group(doc.sha256)
    doc.duplicate_group = dup_group
    if doc.sha256:
        doc.is_duplicate = Document.objects.filter(sha256=doc.sha256).exclude(pk=doc.pk).exists()
    else:
        doc.is_duplicate = False

    if image.text_status == "failed":
        doc.sync_status = Document.SYNC_ERROR
        doc.processing_error = image.text_error or "Image text extraction failed"
    else:
        doc.sync_status = Document.SYNC_OK
        doc.processing_error = ""

    doc.confidence_score = confidence_score
    doc.synced_at = timezone.now()
    doc.save()

    page_count = refresh_document_pages(doc)
    if page_count and doc.page_count != page_count:
        doc.page_count = page_count
        doc.save(update_fields=["page_count", "updated_at"])

    if email_attachment and email_attachment.document_id != doc.id:
        email_attachment.document = doc
        email_attachment.save(update_fields=["document"])

    return doc
