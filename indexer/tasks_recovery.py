from datetime import timedelta

from celery import shared_task
from django.db import close_old_connections, transaction
from django.utils import timezone

from indexer.models import Image, PreviewStatus, ProcessingStatus
from indexer.tasks_metrics import record_task_metric


def _claim_stale_ids(qs, updated_field: str, minutes: int, batch_size: int) -> list[str]:
    cutoff = timezone.now() - timedelta(minutes=minutes)

    return list(
        qs.filter(**{f"{updated_field}__lt": cutoff})
        .order_by(updated_field)
        .values_list("id", flat=True)[:batch_size]
    )


def _batched_reset(
    *,
    qs,
    status_field: str,
    pending_value: str,
    error_field: str,
    error_message: str,
    updated_field: str,
    stale_minutes: int,
    batch_size: int,
) -> int:
    ids = _claim_stale_ids(
        qs=qs,
        updated_field=updated_field,
        minutes=stale_minutes,
        batch_size=batch_size,
    )
    if not ids:
        return 0

    update_kwargs = {
        status_field: pending_value,
        error_field: error_message,
    }

    with transaction.atomic():
        return qs.model.objects.filter(id__in=ids).update(**update_kwargs)


@shared_task
def reset_stale_preview_processing_task(stale_minutes: int = 45, batch_size: int = 250):
    close_old_connections()
    started_at = timezone.now()

    reset_count = _batched_reset(
        qs=Image.objects.filter(preview_status=PreviewStatus.PROCESSING),
        status_field="preview_status",
        pending_value=PreviewStatus.PENDING,
        error_field="preview_error",
        error_message="Reset stale preview processing task",
        updated_field="updated_at",
        stale_minutes=stale_minutes,
        batch_size=batch_size,
    )

    details = {
        "stale_minutes": stale_minutes,
        "batch_size": batch_size,
        "preview_reset": reset_count,
    }
    record_task_metric("reset_stale_preview_processing_task", started_at, details=details)

    return {
        "ok": True,
        **details,
    }


@shared_task
def reset_stale_processing_task(stale_minutes: int = 45, batch_size: int = 500):
    close_old_connections()
    started_at = timezone.now()

    text_reset = _batched_reset(
        qs=Image.objects.filter(text_status=ProcessingStatus.PROCESSING),
        status_field="text_status",
        pending_value=ProcessingStatus.PENDING,
        error_field="text_error",
        error_message="Reset stale text processing task",
        updated_field="updated_at",
        stale_minutes=stale_minutes,
        batch_size=batch_size,
    )

    metadata_reset = _batched_reset(
        qs=Image.objects.filter(metadata_status=ProcessingStatus.PROCESSING),
        status_field="metadata_status",
        pending_value=ProcessingStatus.PENDING,
        error_field="metadata_error",
        error_message="Reset stale metadata processing task",
        updated_field="updated_at",
        stale_minutes=stale_minutes,
        batch_size=batch_size,
    )

    embedding_reset = _batched_reset(
        qs=Image.objects.filter(embedding_status=ProcessingStatus.PROCESSING),
        status_field="embedding_status",
        pending_value=ProcessingStatus.PENDING,
        error_field="embedding_error",
        error_message="Reset stale embedding processing task",
        updated_field="updated_at",
        stale_minutes=stale_minutes,
        batch_size=batch_size,
    )

    details = {
        "stale_minutes": stale_minutes,
        "batch_size": batch_size,
        "text_reset": text_reset,
        "metadata_reset": metadata_reset,
        "embedding_reset": embedding_reset,
    }
    record_task_metric("reset_stale_processing_task", started_at, details=details)

    return {
        "ok": True,
        **details,
    }