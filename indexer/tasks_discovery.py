import os
import mimetypes

from celery import shared_task
from django.db import close_old_connections
from django.utils import timezone

from indexer.models import Image, AccessRoot


SUPPORTED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff",
    ".pdf", ".svg", ".eps", ".ai", ".psd", ".indd",
}

BATCH_SIZE = 1000


def _build_image(path, root, now):
    filename = os.path.basename(path)
    ext = os.path.splitext(filename)[1].lower()
    mime_type = mimetypes.guess_type(path)[0] or ""

    return Image(
        filename=filename,
        path=path,
        root=root,
        file_ext=ext,
        mime_type=mime_type,
        created_at=now,
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
    root_path = root.path
    batch = []
    queued = 0

    for dirpath, _, filenames in os.walk(root_path):
        for name in filenames:
            ext = os.path.splitext(name)[1].lower()

            if ext and ext not in SUPPORTED_EXTENSIONS:
                continue

            path = os.path.join(dirpath, name)
            batch.append(_build_image(path, root, now))

            if len(batch) >= BATCH_SIZE:
                queued += _flush_batch(batch)

    queued += _flush_batch(batch)
    return queued