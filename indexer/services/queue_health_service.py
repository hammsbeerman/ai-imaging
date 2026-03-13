from datetime import timedelta
from django.utils import timezone
from django.db.models import Count

from indexer.models import (
    Image,
    ScanDir,
    TaskLog,
    PreviewStatus,
    ProcessingStatus,
)


def get_scan_queue_counts() -> dict:
    return {
        "pending_dirs": ScanDir.objects.filter(done=False).count(),
        "retrying_dirs": (
            ScanDir.objects
            .filter(done=False)
            .exclude(last_error__isnull=True)
            .exclude(last_error="")
            .count()
        ),
        "done_dirs": ScanDir.objects.filter(done=True).count(),
    }


def get_preview_queue_counts() -> dict:
    return {
        "pending": Image.objects.filter(preview_status=PreviewStatus.PENDING).count(),
        "ok": Image.objects.filter(preview_status=PreviewStatus.OK).count(),
        "failed": Image.objects.filter(preview_status=PreviewStatus.FAILED).count(),
        "unsupported": Image.objects.filter(preview_status=PreviewStatus.UNSUPPORTED).count(),
    }


def _count_processing_status(field_name: str) -> dict:
    return {
        "pending": Image.objects.filter(**{field_name: ProcessingStatus.PENDING}).count(),
        "processing": Image.objects.filter(**{field_name: ProcessingStatus.PROCESSING}).count(),
        "ok": Image.objects.filter(**{field_name: ProcessingStatus.OK}).count(),
        "failed": Image.objects.filter(**{field_name: ProcessingStatus.FAILED}).count(),
        "skipped": Image.objects.filter(**{field_name: ProcessingStatus.SKIPPED}).count(),
        "unsupported": Image.objects.filter(**{field_name: ProcessingStatus.UNSUPPORTED}).count(),
    }


def get_text_queue_counts() -> dict:
    return _count_processing_status("text_status")


def get_metadata_queue_counts() -> dict:
    return _count_processing_status("metadata_status")


def get_embedding_queue_counts() -> dict:
    data = _count_processing_status("embedding_status")
    data["indexed"] = Image.objects.filter(indexed=True).count()
    return data


def get_recent_tasklog_rows(task_names: list[str], limit: int = 20):
    return list(
        TaskLog.objects
        .filter(task__in=task_names)
        .order_by("-created")[:limit]
    )

def get_stuck_processing_counts(timeout_minutes=30):
    cutoff = timezone.now() - timedelta(minutes=timeout_minutes)

    return {
        "text": Image.objects.filter(
            text_status=ProcessingStatus.PROCESSING,
            text_run_at__lt=cutoff,
        ).count(),

        "metadata": Image.objects.filter(
            metadata_status=ProcessingStatus.PROCESSING,
            metadata_run_at__lt=cutoff,
        ).count(),

        "embedding": Image.objects.filter(
            embedding_status=ProcessingStatus.PROCESSING,
            embedding_run_at__lt=cutoff,
        ).count(),
    }

def get_top_pipeline_errors(limit=10):
    errors = []

    for field in [
        "preview_error",
        "text_error",
        "metadata_error",
        "embedding_error",
    ]:
        qs = (
            Image.objects
            .exclude(**{field: ""})
            .exclude(**{field: None})
            .values(field)
            .annotate(count=Count("id"))
            .order_by("-count")[:limit]
        )

        for row in qs:
            errors.append({
                "stage": field.replace("_error", ""),
                "error": row[field],
                "count": row["count"],
            })

    errors.sort(key=lambda x: x["count"], reverse=True)
    return errors[:limit]