import hashlib
import os
from datetime import datetime
from email.header import decode_header
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from indexer.models import Image, ProcessingStatus, PreviewStatus
from indexer.models_mail import InboundEmailAttachment

SUPPORTED_EXTS = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}


def decode_filename(value: str) -> str:
    if not value:
        return ""
    out = []
    for part, encoding in decode_header(value):
        if isinstance(part, bytes):
            out.append(part.decode(encoding or "utf-8", errors="replace"))
        else:
            out.append(part)
    return "".join(out).strip()


def _safe_filename(name: str) -> str:
    name = (name or "attachment").strip().replace("/", "_").replace("\\", "_")
    return name[:240] or "attachment"


def _write_attachment(payload: bytes, filename: str) -> str:
    now = timezone.now()
    rel_dir = Path("email_ingest") / now.strftime("%Y") / now.strftime("%m") / now.strftime("%d")
    full_dir = Path(settings.MEDIA_ROOT) / rel_dir
    full_dir.mkdir(parents=True, exist_ok=True)
    safe_name = _safe_filename(filename)
    full_path = full_dir / safe_name

    counter = 1
    stem = full_path.stem
    suffix = full_path.suffix
    while full_path.exists():
        full_path = full_dir / f"{stem}_{counter}{suffix}"
        counter += 1

    full_path.write_bytes(payload)
    return str(full_path)


def _build_image_for_attachment(path: str, filename: str, content_type: str, payload: bytes) -> Image:
    ext = Path(filename).suffix.lower()
    stat = os.stat(path)
    now = datetime.fromtimestamp(stat.st_mtime, tz=timezone.get_current_timezone())
    sha256 = hashlib.sha256(payload).hexdigest()

    image = Image.objects.create(
        path=path,
        filename=filename,
        size=stat.st_size,
        ext=ext,
        mtime=now,
        indexed=False,
        skip_index=False,
        file_ext=ext,
        mime_type=content_type or "",
        preview_status=PreviewStatus.PENDING,
        text_status=ProcessingStatus.PENDING,
        embedding_status=ProcessingStatus.PENDING,
        metadata_status=ProcessingStatus.PENDING,
        file_size=stat.st_size,
        file_mtime=now,
        file_ctime=now,
        sha256=sha256,
        relative_dir="email_ingest",
        folder_depth=1,
    )
    return image


def ingest_message_attachments(email_obj, msg):
    created = []
    for part in msg.walk():
        disposition = str(part.get("Content-Disposition") or "")
        if "attachment" not in disposition.lower():
            continue

        filename = decode_filename(part.get_filename() or "")
        if not filename:
            continue

        ext = Path(filename).suffix.lower()
        if ext not in SUPPORTED_EXTS:
            continue

        payload = part.get_payload(decode=True)
        if not payload:
            continue

        content_type = part.get_content_type() or ""
        file_path = _write_attachment(payload, filename)
        image = _build_image_for_attachment(file_path, filename, content_type, payload)

        attachment = InboundEmailAttachment.objects.create(
            email=email_obj,
            filename=filename,
            content_type=content_type,
            file_size=len(payload),
            image=image,
        )
        created.append(attachment)
    return created
