import re

import pytesseract
pytesseract.pytesseract.tesseract_cmd = "/usr/bin/tesseract"
from PIL import Image as PILImage, ImageOps, ImageFilter
from PIL.Image import DecompressionBombError
import indexer.pillow_limits


def clean_ocr_text(text):
    text = text.replace("\x0c", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def preprocess_for_ocr(img):
    if img.mode not in ("L", "1"):
        img = ImageOps.grayscale(img)

    img = ImageOps.autocontrast(img)
    img = img.filter(ImageFilter.MedianFilter(size=3))

    w, h = img.size
    if w < 1600:
        ratio = 1600 / max(w, 1)
        img = img.resize((int(w * ratio), int(h * ratio)))

    img = img.point(lambda p: 255 if p > 180 else 0)
    return img


def looks_like_useful_text(text):
    if not text:
        return False
    stripped = re.sub(r"\s+", "", text)
    alpha = re.sub(r"[^A-Za-z]", "", text)
    return len(stripped) >= 20 and len(alpha) >= 10


def _mean_confidence(data):
    vals = []
    for v in data.get("conf", []):
        try:
            n = float(v)
            if n >= 0:
                vals.append(n)
        except Exception:
            continue
    if not vals:
        return None
    return round(sum(vals) / len(vals), 2)


def ocr_image(path, language="eng"):
    try:
        with PILImage.open(path) as img:
            img = preprocess_for_ocr(img)
            data = pytesseract.image_to_data(img, lang=language, output_type=pytesseract.Output.DICT)
            text = pytesseract.image_to_string(img, lang=language)
    except DecompressionBombError as e:
        raise RuntimeError(f"OCR blocked oversized image: {e}")

    return {
        "text_raw": text or "",
        "text_clean": clean_ocr_text(text or ""),
        "confidence": _mean_confidence(data),
        "engine": "tesseract",
        "source": "ocr_image",
        "language": language,
    }