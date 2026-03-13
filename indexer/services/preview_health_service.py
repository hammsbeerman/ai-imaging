import os

from django.conf import settings

from indexer.models import Image, PreviewStatus
from indexer.previews import abs_preview_path, preview_mount_check_path


def get_mount_health() -> dict:
    path = preview_mount_check_path()

    exists = os.path.exists(path)
    readable = os.access(path, os.R_OK) if exists else False
    writable = os.access(path, os.W_OK) if exists else False
    healthy = exists and readable and writable

    return {
        "path": path,
        "exists": exists,
        "readable": readable,
        "writable": writable,
        "healthy": healthy,
    }


def count_missing_ok_previews(limit: int | None = None) -> int:
    qs = (
        Image.objects
        .filter(preview_status=PreviewStatus.OK)
        .exclude(preview_path__isnull=True)
        .exclude(preview_path="")
        .only("id", "preview_path")
        .order_by("created")
    )

    if limit:
        qs = qs[:limit]

    missing = 0
    for img in qs.iterator(chunk_size=200):
        preview_abs = abs_preview_path(img.preview_path)
        if not preview_abs or not os.path.exists(preview_abs):
            missing += 1

    return missing


def get_preview_error_buckets(limit: int = 10) -> list[dict]:
    rows = (
        Image.objects
        .filter(preview_status=PreviewStatus.FAILED)
        .exclude(preview_error="")
        .values_list("preview_error", flat=True)
    )

    counts: dict[str, int] = {}

    for raw in rows.iterator(chunk_size=200):
        msg = (raw or "").strip()
        if not msg:
            continue

        key = msg.splitlines()[0][:120]
        counts[key] = counts.get(key, 0) + 1

    ordered = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    return [{"reason": reason, "count": count} for reason, count in ordered[:limit]]


def get_unsupported_ext_buckets(limit: int = 10) -> list[dict]:
    rows = (
        Image.objects
        .filter(preview_status=PreviewStatus.UNSUPPORTED)
        .values_list("file_ext", flat=True)
    )

    counts: dict[str, int] = {}

    for ext in rows.iterator(chunk_size=200):
        key = (ext or "(blank)").lower()
        counts[key] = counts.get(key, 0) + 1

    ordered = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    return [{"ext": ext, "count": count} for ext, count in ordered[:limit]]