from datetime import timedelta

from celery import shared_task
from django.db import close_old_connections
from django.utils import timezone

from indexer.models import Image, ProcessingStatus
from indexer.tasklog import log


@shared_task
def reset_stuck_processing_task(timeout_minutes: int = 30):
    close_old_connections()

    cutoff = timezone.now() - timedelta(minutes=timeout_minutes)

    text_count = (
        Image.objects
        .filter(
            text_status=ProcessingStatus.PROCESSING,
            text_run_at__lt=cutoff,
        )
        .update(
            text_status=ProcessingStatus.PENDING,
            text_error="reset from stuck processing",
        )
    )

    metadata_count = (
        Image.objects
        .filter(
            metadata_status=ProcessingStatus.PROCESSING,
            metadata_run_at__lt=cutoff,
        )
        .update(
            metadata_status=ProcessingStatus.PENDING,
            metadata_error="reset from stuck processing",
        )
    )

    embedding_count = (
        Image.objects
        .filter(
            embedding_status=ProcessingStatus.PROCESSING,
            embedding_run_at__lt=cutoff,
        )
        .update(
            embedding_status=ProcessingStatus.PENDING,
            embedding_error="reset from stuck processing",
        )
    )

    total = text_count + metadata_count + embedding_count

    log(
        "maintenance",
        (
            f"reset_stuck_processing timeout_minutes={timeout_minutes} "
            f"text={text_count} metadata={metadata_count} embedding={embedding_count} total={total}"
        ),
        "WARNING" if total else "INFO",
    )

    return {
        "timeout_minutes": timeout_minutes,
        "text_reset": text_count,
        "metadata_reset": metadata_count,
        "embedding_reset": embedding_count,
        "total_reset": total,
    }