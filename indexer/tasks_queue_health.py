from datetime import timedelta

from celery import shared_task
from django.db import close_old_connections
from django.db.models import Count, Min, Q
from django.utils import timezone

from indexer.models import Image, ProcessingStatus, PreviewStatus, QueueHealthSnapshot, ScanDir
from indexer.tasks_metrics import record_task_metric


def _status_counts(field_name: str) -> dict:
    return Image.objects.aggregate(
        pending=Count("id", filter=Q(**{field_name: ProcessingStatus.PENDING})),
        processing=Count("id", filter=Q(**{field_name: ProcessingStatus.PROCESSING})),
        ok=Count("id", filter=Q(**{field_name: ProcessingStatus.OK})),
        failed=Count("id", filter=Q(**{field_name: ProcessingStatus.FAILED})),
        skipped=Count("id", filter=Q(**{field_name: ProcessingStatus.SKIPPED})),
        unsupported=Count("id", filter=Q(**{field_name: ProcessingStatus.UNSUPPORTED})),
    )


@shared_task
def rebuild_queue_health_snapshot_task(timeout_minutes: int = 45):
    close_old_connections()
    started_at = timezone.now()
    cutoff = started_at - timedelta(minutes=timeout_minutes)

    scan = {
        "scan_pending_dirs": ScanDir.objects.filter(done=False).count(),
        "scan_retrying_dirs": (
            ScanDir.objects.filter(done=False)
            .exclude(last_error__isnull=True)
            .exclude(last_error="")
            .count()
        ),
        "scan_done_dirs": ScanDir.objects.filter(done=True).count(),
    }

    preview = Image.objects.aggregate(
        pending=Count("id", filter=Q(preview_status=PreviewStatus.PENDING)),
        processing=Count("id", filter=Q(preview_status=PreviewStatus.PROCESSING)),
        ok=Count("id", filter=Q(preview_status=PreviewStatus.OK)),
        failed=Count("id", filter=Q(preview_status=PreviewStatus.FAILED)),
        unsupported=Count("id", filter=Q(preview_status=PreviewStatus.UNSUPPORTED)),
        oldest_pending_at=Min("created", filter=Q(preview_status=PreviewStatus.PENDING)),
        oldest_processing_at=Min("preview_created_at", filter=Q(preview_status=PreviewStatus.PROCESSING)),
    )

    text = _status_counts("text_status")
    text["oldest_pending_at"] = Image.objects.filter(text_status=ProcessingStatus.PENDING).aggregate(v=Min("created"))["v"]
    text["oldest_processing_at"] = Image.objects.filter(text_status=ProcessingStatus.PROCESSING).aggregate(v=Min("text_run_at"))["v"]

    metadata = _status_counts("metadata_status")
    metadata["oldest_pending_at"] = Image.objects.filter(metadata_status=ProcessingStatus.PENDING).aggregate(v=Min("created"))["v"]
    metadata["oldest_processing_at"] = Image.objects.filter(metadata_status=ProcessingStatus.PROCESSING).aggregate(v=Min("metadata_run_at"))["v"]

    embedding = _status_counts("embedding_status")
    embedding["oldest_pending_at"] = Image.objects.filter(embedding_status=ProcessingStatus.PENDING).aggregate(v=Min("created"))["v"]
    embedding["oldest_processing_at"] = Image.objects.filter(embedding_status=ProcessingStatus.PROCESSING).aggregate(v=Min("embedding_run_at"))["v"]
    embedding["indexed"] = Image.objects.filter(indexed=True).count()

    stuck = {
        "stuck_preview": Image.objects.filter(preview_status=PreviewStatus.PROCESSING, preview_created_at__lt=cutoff).count(),
        "stuck_text": Image.objects.filter(text_status=ProcessingStatus.PROCESSING, text_run_at__lt=cutoff).count(),
        "stuck_metadata": Image.objects.filter(metadata_status=ProcessingStatus.PROCESSING, metadata_run_at__lt=cutoff).count(),
        "stuck_embedding": Image.objects.filter(embedding_status=ProcessingStatus.PROCESSING, embedding_run_at__lt=cutoff).count(),
    }

    obj, _ = QueueHealthSnapshot.objects.get_or_create(scope="global")
    for key, value in scan.items():
        setattr(obj, key, value or 0)

    obj.preview_pending = preview["pending"] or 0
    obj.preview_processing = preview["processing"] or 0
    obj.preview_ok = preview["ok"] or 0
    obj.preview_failed = preview["failed"] or 0
    obj.preview_unsupported = preview["unsupported"] or 0
    obj.oldest_preview_pending_at = preview["oldest_pending_at"]
    obj.oldest_preview_processing_at = preview["oldest_processing_at"]

    obj.text_pending = text["pending"] or 0
    obj.text_processing = text["processing"] or 0
    obj.text_ok = text["ok"] or 0
    obj.text_failed = text["failed"] or 0
    obj.text_skipped = text["skipped"] or 0
    obj.text_unsupported = text["unsupported"] or 0
    obj.oldest_text_pending_at = text["oldest_pending_at"]
    obj.oldest_text_processing_at = text["oldest_processing_at"]

    obj.metadata_pending = metadata["pending"] or 0
    obj.metadata_processing = metadata["processing"] or 0
    obj.metadata_ok = metadata["ok"] or 0
    obj.metadata_failed = metadata["failed"] or 0
    obj.metadata_skipped = metadata["skipped"] or 0
    obj.metadata_unsupported = metadata["unsupported"] or 0
    obj.oldest_metadata_pending_at = metadata["oldest_pending_at"]
    obj.oldest_metadata_processing_at = metadata["oldest_processing_at"]

    obj.embedding_pending = embedding["pending"] or 0
    obj.embedding_processing = embedding["processing"] or 0
    obj.embedding_ok = embedding["ok"] or 0
    obj.embedding_failed = embedding["failed"] or 0
    obj.embedding_skipped = embedding["skipped"] or 0
    obj.embedding_unsupported = embedding["unsupported"] or 0
    obj.embedding_indexed = embedding["indexed"] or 0
    obj.oldest_embedding_pending_at = embedding["oldest_pending_at"]
    obj.oldest_embedding_processing_at = embedding["oldest_processing_at"]

    for key, value in stuck.items():
        setattr(obj, key, value or 0)

    obj.save()

    details = {"scope": obj.scope, "timeout_minutes": timeout_minutes}
    record_task_metric("rebuild_queue_health_snapshot_task", started_at, details=details)
    return {"ok": True, **details}
