from datetime import timedelta

from celery import shared_task
from django.db import close_old_connections
from django.utils import timezone

from indexer.models import Image, PreviewStatus, ProcessingStatus
from indexer.tasks_metrics import record_task_metric


def _reset_rows(qs, *, status_field: str, error_field: str, run_at_field: str | None, to_pending: str, reason: str) -> int:
    update_kwargs = {status_field: to_pending, error_field: reason}
    if run_at_field:
        update_kwargs[run_at_field] = None
    return qs.update(**update_kwargs)


@shared_task
def reset_stale_preview_processing_task(timeout_minutes: int = 45):
    close_old_connections()
    started_at = timezone.now()
    cutoff = started_at - timedelta(minutes=timeout_minutes)

    qs = Image.objects.filter(
        preview_status=PreviewStatus.PROCESSING,
        preview_created_at__lt=cutoff,
    )
    reset = qs.update(
        preview_status=PreviewStatus.PENDING,
        preview_error=f"reset stale preview claim older than {timeout_minutes} minutes",
    )

    record_task_metric(
        "reset_stale_preview_processing_task",
        started_at,
        details={"timeout_minutes": timeout_minutes, "reset": reset},
    )
    return {"reset": reset, "timeout_minutes": timeout_minutes}


@shared_task
def reset_stale_processing_task(timeout_minutes: int = 45):
    close_old_connections()
    started_at = timezone.now()
    cutoff = started_at - timedelta(minutes=timeout_minutes)

    text_reset = _reset_rows(
        Image.objects.filter(text_status=ProcessingStatus.PROCESSING, text_run_at__lt=cutoff),
        status_field="text_status",
        error_field="text_error",
        run_at_field="text_run_at",
        to_pending=ProcessingStatus.PENDING,
        reason=f"reset stale text claim older than {timeout_minutes} minutes",
    )
    metadata_reset = _reset_rows(
        Image.objects.filter(metadata_status=ProcessingStatus.PROCESSING, metadata_run_at__lt=cutoff),
        status_field="metadata_status",
        error_field="metadata_error",
        run_at_field="metadata_run_at",
        to_pending=ProcessingStatus.PENDING,
        reason=f"reset stale metadata claim older than {timeout_minutes} minutes",
    )
    embedding_reset = _reset_rows(
        Image.objects.filter(embedding_status=ProcessingStatus.PROCESSING, embedding_run_at__lt=cutoff),
        status_field="embedding_status",
        error_field="embedding_error",
        run_at_field="embedding_run_at",
        to_pending=ProcessingStatus.PENDING,
        reason=f"reset stale embedding claim older than {timeout_minutes} minutes",
    )

    details = {
        "timeout_minutes": timeout_minutes,
        "text_reset": text_reset,
        "metadata_reset": metadata_reset,
        "embedding_reset": embedding_reset,
    }
    record_task_metric("reset_stale_processing_task", started_at, details=details)
    return details
