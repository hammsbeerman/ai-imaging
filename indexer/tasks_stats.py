from django.db import close_old_connections
from django.db.models import Count, Q
from django.utils import timezone
from celery import shared_task

from indexer.models import ArchiveStats, Image, PreviewStatus, ProcessingStatus
from indexer.tasks_metrics import record_task_metric


@shared_task
def rebuild_archive_stats_task():
    close_old_connections()
    started_at = timezone.now()

    stats, _ = ArchiveStats.objects.get_or_create(scope="global")

    agg = Image.objects.aggregate(
        total_files=Count("id"),
        indexed_files=Count("id", filter=Q(indexed=True)),

        preview_ok=Count("id", filter=Q(preview_status=PreviewStatus.OK)),
        preview_pending=Count("id", filter=Q(preview_status=PreviewStatus.PENDING)),
        preview_processing=Count("id", filter=Q(preview_status=PreviewStatus.PROCESSING)),
        preview_failed=Count("id", filter=Q(preview_status=PreviewStatus.FAILED)),
        preview_unsupported=Count("id", filter=Q(preview_status=PreviewStatus.UNSUPPORTED)),

        text_ok=Count("id", filter=Q(text_status=ProcessingStatus.OK)),
        text_pending=Count("id", filter=Q(text_status=ProcessingStatus.PENDING)),
        text_processing=Count("id", filter=Q(text_status=ProcessingStatus.PROCESSING)),
        text_failed=Count("id", filter=Q(text_status=ProcessingStatus.FAILED)),
        text_skipped=Count("id", filter=Q(text_status=ProcessingStatus.SKIPPED)),

        metadata_ok=Count("id", filter=Q(metadata_status=ProcessingStatus.OK)),
        metadata_pending=Count("id", filter=Q(metadata_status=ProcessingStatus.PENDING)),
        metadata_processing=Count("id", filter=Q(metadata_status=ProcessingStatus.PROCESSING)),
        metadata_failed=Count("id", filter=Q(metadata_status=ProcessingStatus.FAILED)),
        metadata_skipped=Count("id", filter=Q(metadata_status=ProcessingStatus.SKIPPED)),

        embedding_ok=Count("id", filter=Q(embedding_status=ProcessingStatus.OK)),
        embedding_pending=Count("id", filter=Q(embedding_status=ProcessingStatus.PENDING)),
        embedding_processing=Count("id", filter=Q(embedding_status=ProcessingStatus.PROCESSING)),
        embedding_failed=Count("id", filter=Q(embedding_status=ProcessingStatus.FAILED)),
        embedding_skipped=Count("id", filter=Q(embedding_status=ProcessingStatus.SKIPPED)),

        duplicate_groups=Count("duplicate_group", filter=~Q(duplicate_group=""), distinct=True),
        duplicate_items=Count("id", filter=~Q(duplicate_group="")),

        text_native_pdf=Count("id", filter=Q(text_status=ProcessingStatus.OK, text_source="pdf_text")),
        text_ocr_image=Count("id", filter=Q(text_status=ProcessingStatus.OK, text_source="ocr_image")),
        text_high_conf=Count("id", filter=Q(text_status=ProcessingStatus.OK, text_confidence__gte=85)),
        text_mid_conf=Count("id", filter=Q(text_status=ProcessingStatus.OK, text_confidence__gte=60, text_confidence__lt=85)),
        text_low_conf=Count("id", filter=Q(text_status=ProcessingStatus.OK, text_confidence__lt=60)),
    )

    for field, value in agg.items():
        setattr(stats, field, value or 0)

    stats.save()

    details = {"scope": stats.scope, "total_files": stats.total_files}
    record_task_metric("rebuild_archive_stats_task", started_at, details=details)

    return {"ok": True, **details}
