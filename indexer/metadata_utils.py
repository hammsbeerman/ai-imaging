import hashlib
import mimetypes
import os
import re
from datetime import datetime

from django.utils import timezone
from PIL import Image as PILImage, ExifTags
from PIL.Image import DecompressionBombError
import indexer.pillow_limits


def file_sha256(path, chunk_size=1024 * 1024):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_stat(path):
    st = os.stat(path)
    return {
        "file_size": st.st_size,
        "file_mtime": timezone.make_aware(datetime.fromtimestamp(st.st_mtime)),
        "file_ctime": timezone.make_aware(datetime.fromtimestamp(st.st_ctime)),
    }


def normalized_ext(path):
    return os.path.splitext(path)[1].lower()


def guess_mime_type(path):
    mime, _ = mimetypes.guess_type(path)
    return mime or ""


def clean_customer_name(raw):
    raw = os.path.basename(raw)
    raw = re.sub(r"^\d{6,8}[_\-\s]*", "", raw)
    raw = raw.replace("+", " ").replace("_", " ").replace("-", " ")
    raw = re.sub(r"\s+", " ", raw).strip()
    return " ".join(word.capitalize() for word in raw.split())


def extract_probable_job_number(path):
    m = re.search(r"\b(\d{5,10})\b", path)
    return m.group(1) if m else ""


def build_folder_tokens(path):
    tokens = re.split(r"[\\/._\-\+\s]+", path.lower())
    tokens = [t for t in tokens if t]
    return " ".join(sorted(set(tokens)))


def relative_dir(path, root="/mnt/archive"):
    try:
        return os.path.relpath(os.path.dirname(path), root)
    except Exception:
        return os.path.dirname(path)


def folder_depth(path, root="/mnt/archive"):
    rel = relative_dir(path, root=root)
    if rel in ("", "."):
        return 0
    return len(rel.split(os.sep))


def extract_image_metadata(path):
    out = {
        "width": None,
        "height": None,
        "aspect_ratio": None,
        "orientation": "",
        "dpi_x": None,
        "dpi_y": None,
        "color_mode": "",
        "bit_depth": None,
        "page_count": 1,
        "exif_date_taken": None,
        "camera_make": "",
        "camera_model": "",
        "gps_lat": None,
        "gps_lon": None,
    }
    try:
        with PILImage.open(path) as img:
            width, height = img.size
            out["width"] = width
            out["height"] = height
            out["aspect_ratio"] = round(width / height, 5) if height else None

            if width > height:
                out["orientation"] = "landscape"
            elif height > width:
                out["orientation"] = "portrait"
            else:
                out["orientation"] = "square"

            out["color_mode"] = img.mode or ""

            dpi = img.info.get("dpi")
            if isinstance(dpi, tuple) and len(dpi) >= 2:
                out["dpi_x"] = float(dpi[0])
                out["dpi_y"] = float(dpi[1])

            try:
                out["page_count"] = int(getattr(img, "n_frames", 1))
            except Exception:
                out["page_count"] = 1

            mode_to_depth = {
                "1": 1,
                "L": 8,
                "P": 8,
                "RGB": 24,
                "RGBA": 32,
                "CMYK": 32,
                "I;16": 16,
            }
            out["bit_depth"] = mode_to_depth.get(img.mode)

            exif = img.getexif()
            if exif:
                exif = {ExifTags.TAGS.get(k, k): v for k, v in exif.items()}
                out["camera_make"] = str(exif.get("Make", "")).strip()
                out["camera_model"] = str(exif.get("Model", "")).strip()

                dt = exif.get("DateTimeOriginal") or exif.get("DateTime")
                if dt:
                    try:
                        naive = datetime.strptime(str(dt), "%Y:%m:%d %H:%M:%S")
                        out["exif_date_taken"] = timezone.make_aware(naive)
                    except Exception:
                        pass
    except DecompressionBombError as e:
        raise RuntimeError(f"Metadata blocked oversized image: {e}")

    return out