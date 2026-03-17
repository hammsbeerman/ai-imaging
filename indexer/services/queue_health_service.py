from datetime import timedelta

from django.db.models import Count
from django.utils import timezone

from indexer.models import Image, PreviewStatus, ProcessingStatus, QueueHealthSnapshot, ScanDir, TaskLog, TaskRunMetric


def _snapshot():
    return QueueHealthSnapshot.objects.filter(scope="global").first()


def get_scan_queue_counts() -> dict:
    snap = _snapshot()
    if snap:
        return {
            "pending_dirs": snap.scan_pending_dirs,
            "retrying_dirs": snap.scan_retrying_dirs,
            "done_dirs": snap.scan_done_dirs,
        }
    return {
        "pending_dirs": ScanDir.objects.filter(done=False).count(),
        "retrying_dirs": (
            ScanDir.objects.filter(done=False)
            .exclude(last_error__isnull=True)
            .exclude(last_error="")
            .count()
        ),
        "done_dirs": ScanDir.objects.filter(done=True).count(),
    }


def get_preview_queue_counts() -> dict:
    snap = _snapshot()
    if snap:
        return {
            "pending": snap.preview_pending,
            "processing": snap.preview_processing,
            "ok": snap.preview_ok,
            "failed": snap.preview_failed,
            "unsupported": snap.preview_unsupported,
            "oldest_pending_at": snap.oldest_preview_pending_at,
            "oldest_processing_at": snap.oldest_preview_processing_at,
        }
    return {
        "pending": Image.objects.filter(preview_status=PreviewStatus.PENDING).count(),
        "processing": Image.objects.filter(preview_status=PreviewStatus.PROCESSING).count(),
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
    snap = _snapshot()
    if snap:
        return {
            "pending": snap.text_pending,
            "processing": snap.text_processing,
            "ok": snap.text_ok,
            "failed": snap.text_failed,
            "skipped": snap.text_skipped,
            "unsupported": snap.text_unsupported,
            "oldest_pending_at": snap.oldest_text_pending_at,
            "oldest_processing_at": snap.oldest_text_processing_at,
        }
    return _count_processing_status("text_status")


def get_metadata_queue_counts() -> dict:
    snap = _snapshot()
    if snap:
        return {
            "pending": snap.metadata_pending,
            "processing": snap.metadata_processing,
            "ok": snap.metadata_ok,
            "failed": snap.metadata_failed,
            "skipped": snap.metadata_skipped,
            "unsupported": snap.metadata_unsupported,
            "oldest_pending_at": snap.oldest_metadata_pending_at,
            "oldest_processing_at": snap.oldest_metadata_processing_at,
        }
    return _count_processing_status("metadata_status")


def get_embedding_queue_counts() -> dict:
    snap = _snapshot()
    if snap:
        return {
            "pending": snap.embedding_pending,
            "processing": snap.embedding_processing,
            "ok": snap.embedding_ok,
            "failed": snap.embedding_failed,
            "skipped": snap.embedding_skipped,
            "unsupported": snap.embedding_unsupported,
            "indexed": snap.embedding_indexed,
            "oldest_pending_at": snap.oldest_embedding_pending_at,
            "oldest_processing_at": snap.oldest_embedding_processing_at,
        }
    data = _count_processing_status("embedding_status")
    data["indexed"] = Image.objects.filter(indexed=True).count()
    return data


def get_recent_tasklog_rows(task_names: list[str], limit: int = 20):
    return list(TaskLog.objects.filter(task__in=task_names).order_by("-created")[:limit])


def get_stuck_processing_counts(timeout_minutes=30):
    snap = _snapshot()
    if snap:
        return {
            "preview": snap.stuck_preview,
            "text": snap.stuck_text,
            "metadata": snap.stuck_metadata,
            "embedding": snap.stuck_embedding,
        }

    cutoff = timezone.now() - timedelta(minutes=timeout_minutes)
    return {
        "preview": Image.objects.filter(preview_status=PreviewStatus.PROCESSING, preview_created_at__lt=cutoff).count(),
        "text": Image.objects.filter(text_status=ProcessingStatus.PROCESSING, text_run_at__lt=cutoff).count(),
        "metadata": Image.objects.filter(metadata_status=ProcessingStatus.PROCESSING, metadata_run_at__lt=cutoff).count(),
        "embedding": Image.objects.filter(embedding_status=ProcessingStatus.PROCESSING, embedding_run_at__lt=cutoff).count(),
    }


def get_top_pipeline_errors(limit=10):
    errors = []
    for field in ["preview_error", "text_error", "metadata_error", "embedding_error"]:
        qs = (
            Image.objects.exclude(**{field: ""})
            .exclude(**{field: None})
            .values(field)
            .annotate(count=Count("id"))
            .order_by("-count")[:limit]
        )
        for row in qs:
            errors.append({"stage": field.replace("_error", ""), "error": row[field], "count": row["count"]})

    errors.sort(key=lambda x: x["count"], reverse=True)
    return errors[:limit]


def get_recent_task_metrics(task_names: list[str], limit: int = 20):
    return list(
        TaskRunMetric.objects.filter(task_name__in=task_names)
        .order_by("-finished_at")[:limit]
    )
