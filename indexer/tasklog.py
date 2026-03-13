from django.utils import timezone
from indexer.models import TaskLog

MAX_ROWS = 5000


def log(task: str, message: str, level: str = "INFO"):
    TaskLog.objects.create(
        created=timezone.now(),
        task=task,
        level=level,
        message=str(message),
    )


def trim():
    ids = list(TaskLog.objects.order_by("-created").values_list("id", flat=True)[:MAX_ROWS])
    if ids:
        TaskLog.objects.exclude(id__in=ids).delete()