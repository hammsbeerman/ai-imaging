import os
import re
from datetime import datetime

from PIL import Image as PILImage, ExifTags

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}

def _gps_to_degrees(value):
    if not value:
        return None

    def frac_to_float(v):
        try:
            return float(v[0]) / float(v[1])
        except Exception:
            return float(v)

    d = frac_to_float(value[0])
    m = frac_to_float(value[1])
    s = frac_to_float(value[2])
    return d + (m / 60.0) + (s / 3600.0)


def extract_image_metadata(path: str) -> dict:
    ext = os.path.splitext(path)[1].lower()
    if ext not in IMAGE_EXTENSIONS:
        return {}

    out = {
        "image_width": None,
        "image_height": None,
        "captured_at": None,
        "camera_make": "",
        "camera_model": "",
        "gps_lat": None,
        "gps_lon": None,
        "dpi_x": None,
        "dpi_y": None,
    }

    try:
        with PILImage.open(path) as im:
            out["image_width"] = im.width
            out["image_height"] = im.height

            dpi = im.info.get("dpi")
            if dpi and isinstance(dpi, tuple) and len(dpi) >= 2:
                out["dpi_x"] = float(dpi[0])
                out["dpi_y"] = float(dpi[1])

            exif_raw = None
            try:
                exif_raw = im.getexif()
            except Exception:
                exif_raw = None

            if not exif_raw:
                return out

            exif = {}
            for tag_id, value in exif_raw.items():
                tag = ExifTags.TAGS.get(tag_id, tag_id)
                exif[tag] = value

            out["camera_make"] = str(exif.get("Make", "") or "").strip()
            out["camera_model"] = str(exif.get("Model", "") or "").strip()

            dt = exif.get("DateTimeOriginal") or exif.get("DateTime")
            if dt:
                try:
                    out["captured_at"] = datetime.strptime(str(dt), "%Y:%m:%d %H:%M:%S")
                except Exception:
                    pass

            gps_info = exif.get("GPSInfo")
            if gps_info:
                gps = {}
                for key, value in gps_info.items():
                    gps_name = ExifTags.GPSTAGS.get(key, key)
                    gps[gps_name] = value

                lat = _gps_to_degrees(gps.get("GPSLatitude"))
                lon = _gps_to_degrees(gps.get("GPSLongitude"))
                lat_ref = gps.get("GPSLatitudeRef")
                lon_ref = gps.get("GPSLongitudeRef")

                if lat is not None and lat_ref == "S":
                    lat = -lat
                if lon is not None and lon_ref == "W":
                    lon = -lon

                out["gps_lat"] = lat
                out["gps_lon"] = lon

    except Exception:
        return out

    return out


def extract_folder_tokens(path: str) -> str:
    parts = [p for p in path.replace("\\", "/").split("/") if p]
    tokens = []

    for part in parts:
        normalized = part.lower().replace("-", " ").replace("_", " ")
        bits = re.split(r"\s+", normalized)
        tokens.extend([b for b in bits if len(b) > 2])

    return " ".join(sorted(set(tokens)))


def extract_customer_name(path: str) -> str:
    parts = [p for p in path.replace("\\", "/").split("/") if p]
    lowered = [p.lower() for p in parts]

    if "customers" in lowered:
        idx = lowered.index("customers")
        if idx + 1 < len(parts):
            return parts[idx + 1]

    for part in parts:
        m = re.match(r"^\d{6,8}[_-](.+)$", part)
        if m:
            name = m.group(1).replace("+", " ").replace("_", " ").strip()
            if name:
                return name

    return ""


def infer_job_type(image) -> str:
    filename = (getattr(image, "filename", "") or "").lower()
    path = (getattr(image, "path", "") or "").lower()
    ext = (getattr(image, "file_ext", "") or os.path.splitext(filename)[1]).lower()

    haystack = f"{filename} {path}"

    if "brochure" in haystack:
        return "brochure"
    if "wrap" in haystack:
        return "wrap"
    if "banner" in haystack:
        return "banner"
    if "invoice" in haystack:
        return "invoice"
    if ext == ".pdf":
        return "pdf"
    if ext in {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}:
        return "image"

    return ""