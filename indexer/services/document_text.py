import re
from collections import Counter
from datetime import datetime

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
PHONE_RE = re.compile(r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}\b")
MONEY_RE = re.compile(r"\$\s?\d[\d,]*(?:\.\d{2})?")
DATE_RE = re.compile(r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})\b")
INVOICE_RE = re.compile(r"(?:invoice\s*(?:no\.?|number|#)?\s*[:#-]*\s*)([A-Z0-9\-]+)", re.I)
TOTAL_RE = re.compile(r"(?:total(?:\s+due)?|amount\s+due)\s*[:$\s]*([\d,]+\.\d{2})", re.I)
DUE_RE = re.compile(r"(?:due\s*date|due)\s*[:\s]*([0-9][0-9/\-]{5,})", re.I)
WHITESPACE_RE = re.compile(r"[ \t]+")
NON_SEARCH_RE = re.compile(r"[^a-z0-9@\.\-$/\n ]+")

STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "your", "you",
    "are", "was", "were", "have", "has", "had", "not", "but", "all",
    "can", "our", "out", "into", "their", "they", "will", "invoice",
    "total", "date", "due", "page",
}


def normalize_clean_text(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x0c", " ")
    lines = [WHITESPACE_RE.sub(" ", line).strip() for line in text.split("\n")]
    lines = [line for line in lines if line]
    return "\n".join(lines).strip()


def make_search_text(text: str) -> str:
    text = (text or "").lower()
    text = NON_SEARCH_RE.sub(" ", text)
    text = WHITESPACE_RE.sub(" ", text)
    return text.strip()


def build_summary(text: str, max_len: int = 500) -> str:
    if not text:
        return ""
    first = text.split("\n\n", 1)[0].strip()
    return first[:max_len]


def extract_entities(text: str) -> dict:
    words = re.findall(r"\b[a-zA-Z]{4,}\b", text.lower())
    common = Counter(words)
    keywords = [
        word for word, count in common.most_common(40)
        if word not in STOPWORDS and count >= 2
    ][:20]
    return {
        "emails": sorted(set(EMAIL_RE.findall(text))),
        "phones": sorted(set(PHONE_RE.findall(text))),
        "dates": sorted(set(DATE_RE.findall(text))),
        "money": sorted(set(MONEY_RE.findall(text))),
        "keywords": keywords,
    }


def classify_document(text: str, filename: str = "") -> str:
    hay = f"{filename}\n{text}".lower()
    if "invoice" in hay or "amount due" in hay:
        return "invoice"
    if "estimate" in hay or "quote" in hay:
        return "estimate"
    if "receipt" in hay:
        return "receipt"
    if "proof" in hay:
        return "proof"
    if "statement" in hay:
        return "statement"
    return "unknown"


def extract_invoice_data(text: str) -> dict:
    out = {
        "invoice_number": "",
        "invoice_total": "",
        "invoice_due_date": "",
        "invoice_vendor": "",
    }
    if not text:
        return out

    m = INVOICE_RE.search(text)
    if m:
        out["invoice_number"] = (m.group(1) or "").strip()

    m = TOTAL_RE.search(text)
    if m:
        out["invoice_total"] = (m.group(1) or "").strip()

    m = DUE_RE.search(text)
    if m:
        out["invoice_due_date"] = (m.group(1) or "").strip()

    for line in text.split("\n"):
        line = line.strip()
        if line and len(line) > 2:
            out["invoice_vendor"] = line[:255]
            break

    return out


def parse_document_date(value: str):
    if not value:
        return None
    for fmt in ("%m/%d/%Y", "%m-%d-%Y", "%Y-%m-%d", "%m/%d/%y", "%m-%d-%y"):
        try:
            return datetime.strptime(value, fmt).date()
        except Exception:
            continue
    return None


def compute_confidence_score(*, text_source: str, text_length: int, text_confidence, document_type: str, entities: dict, invoice_data: dict, page_count=None) -> float:
    score = 0.0
    if text_source:
        score += 15
    if text_length >= 80:
        score += 20
    elif text_length >= 30:
        score += 10
    if text_confidence is not None:
        try:
            score += min(max(float(text_confidence), 0.0), 100.0) * 0.40
        except Exception:
            pass
    if page_count:
        score += 10
    if document_type and document_type != "unknown":
        score += 15
    if entities.get("money"):
        score += 15
    if invoice_data.get("invoice_total"):
        score += 20
    if invoice_data.get("invoice_number"):
        score += 15
    if score > 100:
        score = 100
    return round(score, 1)
