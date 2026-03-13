import redis
import time
import uuid
from django.core.cache import cache
from django.conf import settings

def _client():
    # uses the same redis as broker by default; adjust if yours differs
    url = getattr(settings, "CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")
    return redis.Redis.from_url(url)

def acquire_lock(key: str, ttl: int = 900) -> str | None:
    """
    Returns a lock token if acquired, else None.
    Uses cache.add so it is atomic.
    """
    token = uuid.uuid4().hex
    payload = {"token": token, "ts": time.time(), "ttl": int(ttl)}
    ok = cache.add(key, payload, timeout=int(ttl))
    return token if ok else None

def refresh_lock(key: str, token: str, ttl: int = 900) -> bool:
    payload = cache.get(key)
    if not payload or payload.get("token") != token:
        return False
    payload["ts"] = time.time()
    payload["ttl"] = int(ttl)
    cache.set(key, payload, timeout=int(ttl))
    return True

def release_lock(key: str, token: str) -> bool:
    payload = cache.get(key)
    if not payload:
        return True
    if payload.get("token") != token:
        # Don't let a different worker delete someone else's lock
        return False
    cache.delete(key)
    return True

def break_stale_lock(key: str, max_age_seconds: int = 1800) -> bool:
    """
    If a lock is older than max_age_seconds, delete it.
    Use only for admin/repair.
    """
    payload = cache.get(key)
    if not payload:
        return False
    ts = payload.get("ts") or 0
    if (time.time() - ts) > max_age_seconds:
        cache.delete(key)
        return True
    return False