try:
    import fitz  # pymupdf
except Exception:
    fitz = None

from indexer.models_documents import DocumentPage
from indexer.services.document_text import build_summary, make_search_text, normalize_clean_text


def refresh_document_pages(document):
    image = document.image
    path = image.path
    ext = (image.file_ext or image.ext or "").lower()

    if ext != ".pdf" or not fitz:
        DocumentPage.objects.filter(document=document).delete()
        clean = normalize_clean_text(document.extracted_text_clean or document.ocr_text or "")
        if clean:
            DocumentPage.objects.update_or_create(
                document=document,
                page_number=1,
                defaults={
                    "text_raw": document.ocr_text or clean,
                    "extracted_text_clean": clean,
                    "extracted_text_search": make_search_text(clean),
                    "text_summary": build_summary(clean),
                    "width": image.width,
                    "height": image.height,
                },
            )
        return 1 if clean else 0

    doc = fitz.open(path)
    count = 0
    seen = []
    try:
        for i, page in enumerate(doc, start=1):
            raw = page.get_text("text") or ""
            clean = normalize_clean_text(raw)
            DocumentPage.objects.update_or_create(
                document=document,
                page_number=i,
                defaults={
                    "text_raw": raw,
                    "extracted_text_clean": clean,
                    "extracted_text_search": make_search_text(clean),
                    "text_summary": build_summary(clean),
                    "width": int(page.rect.width),
                    "height": int(page.rect.height),
                },
            )
            seen.append(i)
            count = i
    finally:
        doc.close()

    if seen:
        DocumentPage.objects.filter(document=document).exclude(page_number__in=seen).delete()
    else:
        DocumentPage.objects.filter(document=document).delete()
    return count
