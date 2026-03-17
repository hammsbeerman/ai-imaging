from celery import shared_task
from django.db import close_old_connections
from django.db.models import Count, Q

from indexer.models import (
    ArchiveStats,
    Image,
    PreviewStatus,
    ProcessingStatus,
)


@shared_task
def rebuild_archive_stats_task():
    """
    Rebuild global archive stats used by ui_home dashboard.
    Runs periodically via Celery Beat.

    This replaces expensive dashboard COUNT queries on millions of rows.
    """

    close_old_connections()

    stats, _ = ArchiveStats.objects.get_or_create(scope="global")

    agg = Image.objects.aggregate(
        total_files=Count("id"),
        indexed_files=Count("id", filter=Q(indexed=True)),

        preview_ok=Count("id", filter=Q(preview_status=PreviewStatus.OK)),
        preview_pending=Count("id", filter=Q(preview_status=PreviewStatus.PENDING)),
        preview_failed=Count("id", filter=Q(preview_status=PreviewStatus.FAILED)),
        preview_unsupported=Count("id", filter=Q(preview_status=PreviewStatus.UNSUPPORTED)),

        text_ok=Count("id", filter=Q(text_status=ProcessingStatus.OK)),
        text_pending=Count("id", filter=Q(text_status=ProcessingStatus.PENDING)),
        text_failed=Count("id", filter=Q(text_status=ProcessingStatus.FAILED)),
        text_skipped=Count("id", filter=Q(text_status=ProcessingStatus.SKIPPED)),

        metadata_ok=Count("id", filter=Q(metadata_status=ProcessingStatus.OK)),
        metadata_pending=Count("id", filter=Q(metadata_status=ProcessingStatus.PENDING)),
        metadata_failed=Count("id", filter=Q(metadata_status=ProcessingStatus.FAILED)),
        metadata_skipped=Count("id", filter=Q(metadata_status=ProcessingStatus.SKIPPED)),

        embedding_ok=Count("id", filter=Q(embedding_status=ProcessingStatus.OK)),
        embedding_pending=Count("id", filter=Q(embedding_status=ProcessingStatus.PENDING)),
        embedding_failed=Count("id", filter=Q(embedding_status=ProcessingStatus.FAILED)),
        embedding_skipped=Count("id", filter=Q(embedding_status=ProcessingStatus.SKIPPED)),
    )

    for field, value in agg.items():
        setattr(stats, field, value or 0)

    stats.save()

    return {
        "ok": True,
        "scope": stats.scope,
        "total_files": stats.total_files,
    }