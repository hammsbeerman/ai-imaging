import io
import os
import re
import json
import shutil
import zipfile
import tempfile
import subprocess
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image as PILImage, ImageOps, ImageSequence
from PIL.Image import DecompressionBombError
import indexer.pillow_limits


try:
    import fitz  # pymupdf
except Exception:
    fitz = None

try:
    from psd_tools import PSDImage
except Exception:
    PSDImage = None

try:
    import cairosvg
except Exception:
    cairosvg = None

try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except Exception:
    pass

try:
    import rawpy
except Exception:
    rawpy = None


IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp", ".gif"
}

RAW_EXTENSIONS = {
    ".cr2", ".cr3", ".nef", ".arw", ".dng", ".orf", ".rw2", ".raf", ".srw"
}

PREVIEWABLE_EXTENSIONS = {
    *IMAGE_EXTENSIONS,
    ".pdf", ".psd", ".svg", ".ai", ".eps", ".heic", ".heif", ".indd",
    *RAW_EXTENSIONS,
}


@dataclass
class PreviewResult:
    ok: bool
    preview_path: Optional[str] = None
    thumb_path: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    preview_source: Optional[str] = None
    error: Optional[str] = None


def _safe_stem(path: str) -> str:
    name = Path(path).stem
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
    return name[:120]


def _preview_key(source_path: str) -> str:
    return hashlib.sha1(source_path.encode("utf-8", errors="ignore")).hexdigest()


def _ensure_dir(path: str) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)


def _flatten_to_rgb(img: PILImage.Image, background=(255, 255, 255)) -> PILImage.Image:
    if img.mode in ("RGBA", "LA"):
        base = PILImage.new("RGB", img.size, background)
        alpha = img.getchannel("A") if "A" in img.getbands() else None
        base.paste(img.convert("RGB"), mask=alpha)
        return base
    if img.mode == "P":
        img = img.convert("RGBA")
        return _flatten_to_rgb(img, background=background)
    if img.mode != "RGB":
        img = img.convert("RGB")
    return img


def _save_preview_and_thumb(
    img: PILImage.Image,
    source_path: str,
    preview_dir: str,
    thumb_dir: str,
    max_preview_px: int = 1600,
    thumb_px: int = 320,
    fmt: str = "JPEG",
    quality: int = 88,
) -> PreviewResult:
    img = ImageOps.exif_transpose(img)
    img = _flatten_to_rgb(img)

    key = _preview_key(source_path)

    _ensure_dir(preview_dir)
    _ensure_dir(thumb_dir)

    preview_path = os.path.join(preview_dir, f"{key}.jpg")
    thumb_path = os.path.join(thumb_dir, f"{key}.jpg")

    preview_tmp = preview_path + ".tmp"
    thumb_tmp = thumb_path + ".tmp"

    preview_img = img.copy()
    preview_img.thumbnail((max_preview_px, max_preview_px))
    preview_img.save(preview_tmp, format=fmt, quality=quality, optimize=True)

    thumb_img = img.copy()
    thumb_img.thumbnail((thumb_px, thumb_px))
    thumb_img.save(thumb_tmp, format=fmt, quality=82, optimize=True)

    os.replace(preview_tmp, preview_path)
    os.replace(thumb_tmp, thumb_path)

    return PreviewResult(
        ok=True,
        preview_path=preview_path,
        thumb_path=thumb_path,
        width=img.width,
        height=img.height,
    )


def render_standard_image(source_path: str, preview_dir: str, thumb_dir: str) -> PreviewResult:
    try:
        with PILImage.open(source_path) as im:
            if getattr(im, "is_animated", False):
                first = next(ImageSequence.Iterator(im))
                img = first.copy()
            else:
                img = im.copy()

        result = _save_preview_and_thumb(img, source_path, preview_dir, thumb_dir)
        result.preview_source = "image"
        return result
    except DecompressionBombError as e:
        return PreviewResult(ok=False, error=f"Pillow blocked oversized image: {e}")


def render_pdf(source_path: str, preview_dir: str, thumb_dir: str) -> PreviewResult:
    if fitz:
        doc = fitz.open(source_path)
        try:
            page = doc.load_page(0)
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            try:
                img = PILImage.open(io.BytesIO(pix.tobytes("png")))
                result = _save_preview_and_thumb(img, source_path, preview_dir, thumb_dir)
                result.preview_source = "pdf"
                return result
            except DecompressionBombError as e:
                return PreviewResult(ok=False, error=f"Pillow blocked oversized PDF render: {e}")
        finally:
            doc.close()

    pdftoppm = shutil.which("pdftoppm")
    if pdftoppm:
        with tempfile.TemporaryDirectory() as tmp:
            out_base = os.path.join(tmp, "page")
            cmd = [pdftoppm, "-png", "-f", "1", "-singlefile", source_path, out_base]
            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode == 0:
                png_path = f"{out_base}.png"
                try:
                    with PILImage.open(png_path) as img:
                        result = _save_preview_and_thumb(img.copy(), source_path, preview_dir, thumb_dir)
                        result.preview_source = "pdf"
                        return result
                except DecompressionBombError as e:
                    return PreviewResult(ok=False, error=f"Pillow blocked oversized PDF render: {e}")

    return PreviewResult(ok=False, error="Could not render PDF. Install pymupdf or pdftoppm.")


def render_psd(source_path: str, preview_dir: str, thumb_dir: str) -> PreviewResult:
    if not PSDImage:
        return PreviewResult(ok=False, error="psd-tools not installed")
    try:
        psd = PSDImage.open(source_path)
        composite = psd.composite()
        result = _save_preview_and_thumb(composite, source_path, preview_dir, thumb_dir)
        result.preview_source = "psd"
        return result
    except DecompressionBombError as e:
        return PreviewResult(ok=False, error=f"Pillow blocked oversized PSD render: {e}")


def render_svg(source_path: str, preview_dir: str, thumb_dir: str) -> PreviewResult:
    name = Path(source_path).name.lower()

    if "webfont" in name or "-font" in name or "glyph" in name:
        return PreviewResult(ok=False, error="Skipped font helper SVG")

    if not cairosvg:
        return PreviewResult(ok=False, error="cairosvg not installed")

    try:
        png_bytes = cairosvg.svg2png(url=source_path, output_width=1800)
    except Exception as e:
        msg = str(e)
        if "SVG size is undefined" not in msg:
            return PreviewResult(ok=False, error=f"SVG render failed: {e}")

        try:
            with open(source_path, "rb") as f:
                svg_bytes = f.read()

            png_bytes = cairosvg.svg2png(
                bytestring=svg_bytes,
                parent_width=1800,
                parent_height=1800,
                output_width=1800,
                output_height=1800,
            )
        except Exception as e2:
            return PreviewResult(ok=False, error=f"SVG render failed: {e2}")

    try:
        img = PILImage.open(io.BytesIO(png_bytes))
        result = _save_preview_and_thumb(img, source_path, preview_dir, thumb_dir)
        result.preview_source = "svg"
        return result
    except DecompressionBombError as e:
        return PreviewResult(ok=False, error=f"Pillow blocked oversized SVG render: {e}")
    except Exception as e:
        return PreviewResult(ok=False, error=f"SVG preview save failed: {e}")


def render_heic(source_path: str, preview_dir: str, thumb_dir: str) -> PreviewResult:
    try:
        with PILImage.open(source_path) as img:
            result = _save_preview_and_thumb(img.copy(), source_path, preview_dir, thumb_dir)
            result.preview_source = "heic"
            return result
    except DecompressionBombError as e:
        return PreviewResult(ok=False, error=f"Pillow blocked oversized HEIC image: {e}")


def render_raw(source_path: str, preview_dir: str, thumb_dir: str) -> PreviewResult:
    if not rawpy:
        return PreviewResult(ok=False, error="rawpy not installed")
    with rawpy.imread(source_path) as raw:
        rgb = raw.postprocess(use_camera_wb=True, half_size=False, no_auto_bright=False)
    try:
        img = PILImage.fromarray(rgb)
        result = _save_preview_and_thumb(img, source_path, preview_dir, thumb_dir)
        result.preview_source = "raw"
        return result
    except DecompressionBombError as e:
        return PreviewResult(ok=False, error=f"Pillow blocked oversized RAW render: {e}")


def render_ai_or_eps(source_path: str, preview_dir: str, thumb_dir: str) -> PreviewResult:
    gs = shutil.which("gs") or shutil.which("gswin64c") or shutil.which("gswin32c")
    if not gs:
        return PreviewResult(ok=False, error="Ghostscript not installed")

    with tempfile.TemporaryDirectory() as tmp:
        out_png = os.path.join(tmp, "render.png")
        cmd = [
            gs,
            "-dSAFER",
            "-dBATCH",
            "-dNOPAUSE",
            "-sDEVICE=pngalpha",
            "-r200",
            f"-sOutputFile={out_png}",
            source_path,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0 or not os.path.exists(out_png):
            return PreviewResult(ok=False, error=f"Ghostscript failed: {proc.stderr[-500:]}")
        try:
            with PILImage.open(out_png) as img:
                result = _save_preview_and_thumb(img.copy(), source_path, preview_dir, thumb_dir)
                result.preview_source = "ghostscript"
                return result
        except DecompressionBombError as e:
            return PreviewResult(ok=False, error=f"Pillow blocked oversized AI/EPS render: {e}")


def extract_indd_preview_with_exiftool(source_path: str, preview_dir: str, thumb_dir: str) -> PreviewResult:
    exiftool = shutil.which("exiftool")
    if not exiftool:
        return PreviewResult(ok=False, error="exiftool not installed")

    with tempfile.TemporaryDirectory() as tmp:
        out_preview = os.path.join(tmp, "preview.jpg")
        cmd = [exiftool, "-b", "-PreviewImage", source_path]
        proc = subprocess.run(cmd, capture_output=True)
        if proc.returncode == 0 and proc.stdout:
            with open(out_preview, "wb") as f:
                f.write(proc.stdout)
            try:
                with PILImage.open(out_preview) as img:
                    result = _save_preview_and_thumb(img.copy(), source_path, preview_dir, thumb_dir)
                    result.preview_source = "indd_embedded_preview"
                    return result
            except DecompressionBombError as e:
                return PreviewResult(ok=False, error=f"Pillow blocked oversized INDD preview: {e}")
            except Exception as e:
                return PreviewResult(ok=False, error=f"Embedded preview unreadable: {e}")

    return PreviewResult(ok=False, error="No embedded INDD preview found")


def render_indd(
    source_path: str,
    preview_dir: str,
    thumb_dir: str,
) -> PreviewResult:
    p = Path(source_path)

    sibling_candidates = [
        p.with_suffix(".pdf"),
        p.with_suffix(".jpg"),
        p.with_suffix(".jpeg"),
        p.with_suffix(".png"),
    ]

    for sibling in sibling_candidates:
        if sibling.exists():
            ext = sibling.suffix.lower()

            if ext == ".pdf":
                result = render_pdf(str(sibling), preview_dir, thumb_dir)
                if result.ok:
                    result.preview_source = "sibling_pdf"
                    return result

            elif ext in {".jpg", ".jpeg", ".png"}:
                result = render_standard_image(str(sibling), preview_dir, thumb_dir)
                if result.ok:
                    result.preview_source = f"sibling_{ext.lstrip('.')}"
                    return result

    result = extract_indd_preview_with_exiftool(source_path, preview_dir, thumb_dir)
    if result.ok:
        return result

    return PreviewResult(
        ok=False,
        error="INDD preview unsupported: no sibling PDF/JPG/PNG and no embedded preview found",
    )


def build_preview_for_file(source_path: str, preview_dir: str, thumb_dir: str) -> PreviewResult:
    ext = Path(source_path).suffix.lower()

    try:
        if ext in IMAGE_EXTENSIONS:
            return render_standard_image(source_path, preview_dir, thumb_dir)
        if ext == ".pdf":
            return render_pdf(source_path, preview_dir, thumb_dir)
        if ext == ".psd":
            return render_psd(source_path, preview_dir, thumb_dir)
        if ext == ".svg":
            return render_svg(source_path, preview_dir, thumb_dir)
        if ext in {".heic", ".heif"}:
            return render_heic(source_path, preview_dir, thumb_dir)
        if ext in RAW_EXTENSIONS:
            return render_raw(source_path, preview_dir, thumb_dir)
        if ext in {".ai", ".eps"}:
            return render_ai_or_eps(source_path, preview_dir, thumb_dir)
        if ext == ".indd":
            return render_indd(source_path, preview_dir, thumb_dir)

        return PreviewResult(ok=False, error=f"Unsupported extension: {ext}")
    except Exception as e:
        return PreviewResult(ok=False, error=str(e))