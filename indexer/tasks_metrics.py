from django.utils import timezone

from indexer.models import TaskRunMetric


def record_task_metric(task_name: str, started_at, *, status: str = "ok", scope: str = "global", details: dict | None = None):
    finished_at = timezone.now()
    duration_ms = int((finished_at - started_at).total_seconds() * 1000)
    return TaskRunMetric.objects.create(
        task_name=task_name,
        scope=scope,
        started_at=started_at,
        finished_at=finished_at,
        duration_ms=duration_ms,
        status=status,
        details_json=details or {},
    )
