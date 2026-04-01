from datetime import timedelta
from urllib.parse import urlparse

import redis
from celery import shared_task
from django.conf import settings
from django.db import close_old_connections
from django.db.models import Count, Min, Q
from django.utils import timezone

from indexer.models import Image, ProcessingStatus, PreviewStatus, QueueHealthSnapshot, ScanDir
from indexer.tasks_metrics import record_task_metric


QUEUE_MAP = {
    "ops_queue_depth": "ops",
    "preview_queue_depth": "preview",
    "scan_queue_depth": "scan",
    "ocr_queue_depth": "ocr",
    "mail_queue_depth": "mail",
    "control_queue_depth": "control",
    "embedding_queue_depth": "embedding",
    "metadata_queue_depth": "metadata",
    "text_queue_depth": "text",
}


def _status_counts(field_name: str) -> dict:
    return Image.objects.aggregate(
        pending=Count("id", filter=Q(**{field_name: ProcessingStatus.PENDING})),
        processing=Count("id", filter=Q(**{field_name: ProcessingStatus.PROCESSING})),
        ok=Count("id", filter=Q(**{field_name: ProcessingStatus.OK})),
        failed=Count("id", filter=Q(**{field_name: ProcessingStatus.FAILED})),
        skipped=Count("id", filter=Q(**{field_name: ProcessingStatus.SKIPPED})),
        unsupported=Count("id", filter=Q(**{field_name: ProcessingStatus.UNSUPPORTED})),
    )


def _redis_client() -> redis.Redis:
    broker_url = getattr(settings, "CELERY_BROKER_URL", None)
    if not broker_url:
        raise RuntimeError("CELERY_BROKER_URL not set")

    parsed = urlparse(broker_url)
    if parsed.scheme not in {"redis", "rediss"}:
        raise RuntimeError(f"Unsupported broker scheme: {parsed.scheme!r}")

    db = 0
    path = (parsed.path or "").strip("/")
    if path:
        try:
            db = int(path)
        except ValueError as exc:
            raise RuntimeError(f"Invalid Redis DB in broker URL: {parsed.path!r}") from exc

    return redis.Redis(
        host=parsed.hostname or "127.0.0.1",
        port=parsed.port or 6379,
        password=parsed.password,
        db=db,
        ssl=(parsed.scheme == "rediss"),
        decode_responses=False,
        socket_timeout=5,
        socket_connect_timeout=5,
    )


def _queue_depths() -> tuple[dict, str]:
    values: dict[str, int] = {}
    errors: list[str] = []

    try:
        client = _redis_client()

        for field_name, queue_name in QUEUE_MAP.items():
            try:
                # Missing Redis key should just read as 0.
                values[field_name] = int(client.llen(queue_name) or 0)
            except redis.RedisError as exc:
                values[field_name] = 0
                errors.append(f"{queue_name}: {exc}")

    except Exception as exc:
        for field_name in QUEUE_MAP:
            values[field_name] = 0
        errors.append(str(exc))

    return values, " | ".join(errors)


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
    text["oldest_pending_at"] = Image.objects.filter(
        text_status=ProcessingStatus.PENDING
    ).aggregate(v=Min("created"))["v"]
    text["oldest_processing_at"] = Image.objects.filter(
        text_status=ProcessingStatus.PROCESSING
    ).aggregate(v=Min("text_run_at"))["v"]

    metadata = _status_counts("metadata_status")
    metadata["oldest_pending_at"] = Image.objects.filter(
        metadata_status=ProcessingStatus.PENDING
    ).aggregate(v=Min("created"))["v"]
    metadata["oldest_processing_at"] = Image.objects.filter(
        metadata_status=ProcessingStatus.PROCESSING
    ).aggregate(v=Min("metadata_run_at"))["v"]

    embedding = _status_counts("embedding_status")
    embedding["oldest_pending_at"] = Image.objects.filter(
        embedding_status=ProcessingStatus.PENDING
    ).aggregate(v=Min("created"))["v"]
    embedding["oldest_processing_at"] = Image.objects.filter(
        embedding_status=ProcessingStatus.PROCESSING
    ).aggregate(v=Min("embedding_run_at"))["v"]
    embedding["indexed"] = Image.objects.filter(indexed=True).count()

    # stage-specific stale cutoffs (must match recovery task)
    preview_cutoff = started_at - timedelta(minutes=45)
    metadata_cutoff = started_at - timedelta(minutes=45)
    embedding_cutoff = started_at - timedelta(minutes=120)

    stuck = {
        "stuck_preview": Image.objects.filter(
            preview_status=PreviewStatus.PROCESSING,
            updated_at__lt=preview_cutoff,
        ).count(),

        "stuck_text": Image.objects.filter(
            text_status=ProcessingStatus.PROCESSING,
            updated_at__lt=preview_cutoff,  # text follows preview timing
        ).count(),

        "stuck_metadata": Image.objects.filter(
            metadata_status=ProcessingStatus.PROCESSING,
            updated_at__lt=metadata_cutoff,
        ).count(),

        "stuck_embedding": Image.objects.filter(
            embedding_status=ProcessingStatus.PROCESSING,
            updated_at__lt=embedding_cutoff,
        ).count(),
    }

    queue_depths, queue_error = _queue_depths()

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

    for key, value in queue_depths.items():
        setattr(obj, key, value or 0)

    obj.queue_snapshot_error = queue_error
    obj.save()

    details = {"scope": obj.scope, "timeout_minutes": timeout_minutes}
    record_task_metric("rebuild_queue_health_snapshot_task", started_at, details=details)
    return {"ok": True, **details}