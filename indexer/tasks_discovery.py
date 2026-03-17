import mimetypes
import os
from pathlib import Path

from celery import shared_task
from django.db import close_old_connections
from django.utils import timezone

from indexer.models import AccessRoot, Image, PreviewStatus, ProcessingStatus
from indexer.metadata_utils import clean_customer_name


SUPPORTED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff",
    ".pdf", ".svg", ".eps", ".ai", ".psd", ".indd",
}

BATCH_SIZE = 1000


def _derive_customer_name(path: str) -> str:
    parts = path.replace("\\", "/").split("/")

    for i, part in enumerate(parts):
        if part.lower() == "customers" and i + 1 < len(parts):
            return clean_customer_name(parts[i + 1])

    if len(parts) >= 2:
        return clean_customer_name(parts[-2])

    return ""


def _build_image(path: str, root, now):
    filename = os.path.basename(path)
    ext = Path(filename).suffix.lower()
    mime_type = mimetypes.guess_type(path)[0] or ""

    return Image(
        filename=filename,
        path=path,
        root=root,
        file_ext=ext,
        ext=ext,
        mime_type=mime_type,
        indexed=False,
        skip_index=False,
        preview_status=PreviewStatus.PENDING,
        text_status=ProcessingStatus.PENDING,
        embedding_status=ProcessingStatus.PENDING,
        metadata_status=ProcessingStatus.PENDING,
        file_size=None,
        file_mtime=now,
        customer_name=_derive_customer_name(path),
    )


def _flush_batch(batch):
    if not batch:
        return 0

    before = len(batch)
    Image.objects.bulk_create(
        batch,
        batch_size=BATCH_SIZE,
        ignore_conflicts=True,
    )
    batch.clear()
    return before


def _existing_paths_for_chunk(paths: list[str]) -> set[str]:
    if not paths:
        return set()

    return set(
        Image.objects.filter(path__in=paths).values_list("path", flat=True)
    )


def _iter_files(root_path: str):
    for dirpath, _, filenames in os.walk(root_path):
        for name in filenames:
            ext = Path(name).suffix.lower()
            if ext and ext not in SUPPORTED_EXTENSIONS:
                continue
            yield os.path.join(dirpath, name)


@shared_task
def scan_root_task(root_id=None):
    close_old_connections()

    if root_id:
        roots = AccessRoot.objects.filter(id=root_id)
    else:
        roots = AccessRoot.objects.all()

    created_total = 0

    for root in roots:
        created_total += scan_directory(root)

    return {"created": created_total}


def scan_directory(root):
    now = timezone.now()
    root_path = root.scan_path_root
    batch = []
    path_chunk = []
    created = 0

    if not root_path or not os.path.isdir(root_path):
        return 0

    for path in _iter_files(root_path):
        path_chunk.append(path)

        if len(path_chunk) >= BATCH_SIZE:
            existing = _existing_paths_for_chunk(path_chunk)

            for candidate_path in path_chunk:
                if candidate_path in existing:
                    continue
                batch.append(_build_image(candidate_path, root, now))

            created += _flush_batch(batch)
            path_chunk.clear()

    if path_chunk:
        existing = _existing_paths_for_chunk(path_chunk)

        for candidate_path in path_chunk:
            if candidate_path in existing:
                continue
            batch.append(_build_image(candidate_path, root, now))

        created += _flush_batch(batch)

    return created