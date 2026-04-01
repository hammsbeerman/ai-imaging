import logging
from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from .models import Image, PreviewStatus, ProcessingStatus

logger = logging.getLogger(__name__)


DEFAULT_PREVIEW_STALE_MINUTES = 45
DEFAULT_METADATA_STALE_MINUTES = 45
DEFAULT_EMBEDDING_STALE_MINUTES = 120
DEFAULT_BATCH_SIZE = 500


def _image_field_names():
    return {f.name for f in Image._meta.get_fields() if hasattr(f, "name")}


def _build_reset_kwargs(status_field, pending_value):
    """
    Build a safe update() payload that only touches fields that actually exist.
    This lets the reset task work across slightly different schema versions.
    """
    field_names = _image_field_names()

    reset_kwargs = {
        status_field: pending_value,
        "updated_at": timezone.now(),
    }

    optional_null_fields = [
        "locked_at",
        "claimed_at",
        "processing_started_at",
        "started_at",
        "finished_at",
        "worker_started_at",
        "task_started_at",
        "last_queued_at",
        "last_attempt_at",
        "next_retry_at",
    ]

    optional_blank_fields = [
        "lock_token",
        "claimed_by",
        "worker_name",
        "task_id",
        "celery_task_id",
        "error",
        "error_message",
        "last_error",
        "failure_reason",
        "status_detail",
    ]

    optional_zero_fields = [
        "retry_count",
        "attempt_count",
    ]

    for name in optional_null_fields:
        if name in field_names:
            reset_kwargs[name] = None

    for name in optional_blank_fields:
        if name in field_names:
            reset_kwargs[name] = ""

    for name in optional_zero_fields:
        if name in field_names:
            reset_kwargs[name] = 0

    return reset_kwargs


def _reset_stale_stage(*, stage_label, status_field, processing_value, pending_value, stale_minutes, batch_size):
    """
    Reset stale Image rows for a single stage in batches.

    A row is stale when:
      - stage status == PROCESSING
      - updated_at < cutoff
    """
    now = timezone.now()
    cutoff = now - timedelta(minutes=stale_minutes)

    base_qs = (
        Image.objects
        .filter(**{status_field: processing_value})
        .filter(updated_at__lt=cutoff)
        .order_by("updated_at", "id")
    )

    total_candidates = base_qs.count()
    if total_candidates == 0:
        logger.info(
            "[stale-reset] %s: no stale rows found (cutoff=%s, minutes=%s)",
            stage_label,
            cutoff.isoformat(),
            stale_minutes,
        )
        return 0

    reset_kwargs = _build_reset_kwargs(status_field, pending_value)
    total_reset = 0

    logger.warning(
        "[stale-reset] %s: found %s stale rows (cutoff=%s, minutes=%s, batch_size=%s)",
        stage_label,
        total_candidates,
        cutoff.isoformat(),
        stale_minutes,
        batch_size,
    )

    while True:
        stale_ids = list(base_qs.values_list("id", flat=True)[:batch_size])
        if not stale_ids:
            break

        with transaction.atomic():
            updated = (
                Image.objects
                .filter(id__in=stale_ids)
                .filter(**{status_field: processing_value})
                .update(**reset_kwargs)
            )

        total_reset += updated

        logger.warning(
            "[stale-reset] %s: reset batch of %s stale rows (running_total=%s)",
            stage_label,
            updated,
            total_reset,
        )

        if len(stale_ids) < batch_size:
            break

    logger.warning(
        "[stale-reset] %s: completed reset of %s stale rows",
        stage_label,
        total_reset,
    )
    return total_reset


@shared_task(name="indexer.reset_stale_preview_task")
def reset_stale_preview_task(stale_minutes=DEFAULT_PREVIEW_STALE_MINUTES, batch_size=DEFAULT_BATCH_SIZE):
    return _reset_stale_stage(
        stage_label="preview",
        status_field="preview_status",
        processing_value=PreviewStatus.PROCESSING,
        pending_value=PreviewStatus.PENDING,
        stale_minutes=stale_minutes,
        batch_size=batch_size,
    )


@shared_task(name="indexer.reset_stale_metadata_task")
def reset_stale_metadata_task(stale_minutes=DEFAULT_METADATA_STALE_MINUTES, batch_size=DEFAULT_BATCH_SIZE):
    return _reset_stale_stage(
        stage_label="metadata",
        status_field="metadata_status",
        processing_value=ProcessingStatus.PROCESSING,
        pending_value=ProcessingStatus.PENDING,
        stale_minutes=stale_minutes,
        batch_size=batch_size,
    )


@shared_task(name="indexer.reset_stale_embedding_task")
def reset_stale_embedding_task(stale_minutes=DEFAULT_EMBEDDING_STALE_MINUTES, batch_size=DEFAULT_BATCH_SIZE):
    return _reset_stale_stage(
        stage_label="embedding",
        status_field="embedding_status",
        processing_value=ProcessingStatus.PROCESSING,
        pending_value=ProcessingStatus.PENDING,
        stale_minutes=stale_minutes,
        batch_size=batch_size,
    )


@shared_task(name="indexer.reset_stale_pipeline_processing_task")
def reset_stale_pipeline_processing_task(
    preview_minutes=DEFAULT_PREVIEW_STALE_MINUTES,
    metadata_minutes=DEFAULT_METADATA_STALE_MINUTES,
    embedding_minutes=DEFAULT_EMBEDDING_STALE_MINUTES,
    batch_size=DEFAULT_BATCH_SIZE,
):
    """
    Master recovery task for stale processing rows.
    Run this on a schedule or manually from ops.
    """
    preview_reset = reset_stale_preview_task(
        stale_minutes=preview_minutes,
        batch_size=batch_size,
    )
    metadata_reset = reset_stale_metadata_task(
        stale_minutes=metadata_minutes,
        batch_size=batch_size,
    )
    embedding_reset = reset_stale_embedding_task(
        stale_minutes=embedding_minutes,
        batch_size=batch_size,
    )

    result = {
        "preview_reset": int(preview_reset or 0),
        "metadata_reset": int(metadata_reset or 0),
        "embedding_reset": int(embedding_reset or 0),
        "total_reset": int((preview_reset or 0) + (metadata_reset or 0) + (embedding_reset or 0)),
        "preview_minutes": preview_minutes,
        "metadata_minutes": metadata_minutes,
        "embedding_minutes": embedding_minutes,
        "batch_size": batch_size,
    }

    logger.warning("[stale-reset] pipeline summary: %s", result)
    return result