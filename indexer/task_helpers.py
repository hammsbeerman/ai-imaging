import uuid

from django.core.cache import cache
from django.utils import timezone

from indexer.models import TaskLog


def log(task: str, message: str, level: str = "INFO"):
    TaskLog.objects.create(
        task=task,
        level=level,
        message=message,
    )


def trim(limit: int = 2000):
    ids = list(
        TaskLog.objects.order_by("-created").values_list("id", flat=True)[:limit]
    )
    if ids:
        TaskLog.objects.exclude(id__in=ids).delete()


def acquire_lock(key: str, ttl: int = 300):
    token = str(uuid.uuid4())
    added = cache.add(key, token, timeout=ttl)
    return token if added else None


def refresh_lock(key: str, token: str, ttl: int = 300) -> bool:
    current = cache.get(key)
    if current != token:
        return False
    cache.set(key, token, timeout=ttl)
    return True


def release_lock(key: str, token: str):
    current = cache.get(key)
    if current == token:
        cache.delete(key)