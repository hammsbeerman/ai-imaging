from celery import shared_task
from django.db import close_old_connections, transaction
from django.db.models import Count, Q

from indexer.models import FolderHealthSnapshot, Image, PreviewStatus, ProcessingStatus
from indexer.tasks_metrics import record_task_metric
from django.utils import timezone


@shared_task
def rebuild_folder_health_snapshot_task(limit: int = 25):
    close_old_connections()
    started_at = timezone.now()

    rows = list(
        Image.objects.exclude(folder_id__isnull=True)
        .values("folder__root_id", "folder__rel_path")
        .annotate(
            file_count=Count("id"),
            preview_failed=Count("id", filter=Q(preview_status=PreviewStatus.FAILED)),
            text_failed=Count("id", filter=Q(text_status=ProcessingStatus.FAILED)),
            metadata_failed=Count("id", filter=Q(metadata_status=ProcessingStatus.FAILED)),
            missing_preview=Count("id", filter=Q(preview_status=PreviewStatus.PENDING)),
            duplicate_count=Count("id", filter=~Q(duplicate_group="")),
        )
    )

    scored = []
    for row in rows:
        health_score = (
            (row["preview_failed"] * 3)
            + (row["text_failed"] * 2)
            + (row["metadata_failed"] * 3)
            + (row["missing_preview"] * 2)
            + row["duplicate_count"]
        )
        if health_score <= 0:
            continue
        row["health_score"] = float(health_score)
        scored.append(row)

    scored.sort(
        key=lambda r: (
            -r["health_score"],
            -r["preview_failed"],
            -r["metadata_failed"],
            r.get("folder__rel_path") or "",
        )
    )

    inserts = []
    for rank, row in enumerate(scored[:limit]):
        inserts.append(
            FolderHealthSnapshot(
                scope="global",
                root_id=row["folder__root_id"] or 0,
                folder=row.get("folder__rel_path") or "",
                file_count=row["file_count"],
                preview_failed=row["preview_failed"],
                text_failed=row["text_failed"],
                metadata_failed=row["metadata_failed"],
                missing_preview=row["missing_preview"],
                duplicate_count=row["duplicate_count"],
                health_score=row["health_score"],
                rank=rank,
            )
        )

    with transaction.atomic():
        FolderHealthSnapshot.objects.filter(scope="global").delete()
        FolderHealthSnapshot.objects.bulk_create(inserts, batch_size=100)

    details = {"scope": "global", "rows": len(inserts)}
    record_task_metric("rebuild_folder_health_snapshot_task", started_at, details=details)
    return {"ok": True, **details}
