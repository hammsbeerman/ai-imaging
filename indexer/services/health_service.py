from django.db.models import Count

from indexer.models import Image, PreviewStatus, ProcessingStatus


def _stage_counts(field_name: str) -> dict:
    rows = (
        Image.objects
        .values(field_name)
        .annotate(count=Count("id"))
        .order_by()
    )

    out = {
        "ok": 0,
        "pending": 0,
        "failed": 0,
        "skipped": 0,
        "unsupported": 0,
    }

    for row in rows:
        key = row[field_name] or "pending"
        out[key] = row["count"]

    return out


def get_health_summary():
    preview = _stage_counts("preview_status")
    text = _stage_counts("text_status")
    embedding = _stage_counts("embedding_status")
    metadata = _stage_counts("metadata_status")

    preview["ready_now"] = Image.objects.filter(
        skip_index=False,
        preview_status=PreviewStatus.PENDING,
    ).count()

    text["ready_now"] = Image.objects.filter(
        skip_index=False,
        text_status=ProcessingStatus.PENDING,
        preview_status=PreviewStatus.OK,
    ).count()

    metadata["ready_now"] = Image.objects.filter(
        skip_index=False,
        metadata_status=ProcessingStatus.PENDING,
    ).count()

    embedding["ready_now"] = (
        Image.objects.filter(
            skip_index=False,
            embedding_status=ProcessingStatus.PENDING,
            preview_status=PreviewStatus.OK,
        )
        .exclude(preview_path__isnull=True)
        .exclude(preview_path="")
        .count()
    )

    return {
        "total_images": Image.objects.count(),
        "preview": preview,
        "text": text,
        "embedding": embedding,
        "metadata": metadata,
    }


def get_recent_errors(limit=100):
    rows = []

    for img in Image.objects.exclude(preview_error="").exclude(preview_error__isnull=True)[:limit]:
        rows.append({
            "stage": "preview",
            "id": str(img.id),
            "filename": img.filename,
            "path": img.path,
            "file_ext": img.file_ext or img.ext or "",
            "error": img.preview_error,
        })

    for img in Image.objects.exclude(text_error="").exclude(text_error__isnull=True)[:limit]:
        rows.append({
            "stage": "text",
            "id": str(img.id),
            "filename": img.filename,
            "path": img.path,
            "file_ext": img.file_ext or img.ext or "",
            "error": img.text_error,
        })

    for img in Image.objects.exclude(embedding_error="").exclude(embedding_error__isnull=True)[:limit]:
        rows.append({
            "stage": "embedding",
            "id": str(img.id),
            "filename": img.filename,
            "path": img.path,
            "file_ext": img.file_ext or img.ext or "",
            "error": img.embedding_error,
        })

    for img in Image.objects.exclude(metadata_error="").exclude(metadata_error__isnull=True)[:limit]:
        rows.append({
            "stage": "metadata",
            "id": str(img.id),
            "filename": img.filename,
            "path": img.path,
            "file_ext": img.file_ext or img.ext or "",
            "error": img.metadata_error,
        })

    return rows[:limit]


def get_top_error_reasons(limit=20):
    counts = {}

    def add_error(value):
        key = (value or "").strip()
        if key:
            counts[key] = counts.get(key, 0) + 1

    for img in Image.objects.only("preview_error", "text_error", "embedding_error", "metadata_error"):
        add_error(img.preview_error)
        add_error(img.text_error)
        add_error(img.embedding_error)
        add_error(img.metadata_error)

    return [
        {"error": error, "count": count}
        for error, count in sorted(counts.items(), key=lambda x: x[1], reverse=True)[:limit]
    ]
  