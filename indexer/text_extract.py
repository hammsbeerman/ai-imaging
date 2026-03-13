from pathlib import Path

try:
    import fitz  # pymupdf
except Exception:
    fitz = None


def extract_pdf_text(path: str) -> str:
    if not fitz:
        return ""
    chunks = []
    doc = fitz.open(path)
    try:
        for page in doc:
            chunks.append(page.get_text("text"))
    finally:
        doc.close()
    text = "\n".join(chunks).strip()
    return text[:200000]


def extract_searchable_text(path: str) -> str:
    ext = Path(path).suffix.lower()

    if ext == ".pdf":
        return extract_pdf_text(path)

    # For now, other binary design formats just index filename/path.
    # You can extend later with OCR or metadata extraction.
    return ""