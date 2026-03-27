from __future__ import annotations

from urllib.parse import urlparse

import redis
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


ALLOWED_QUEUES = {
    "ops",
    "preview",
    "scan",
    "ocr",
    "mail",
    "control",
    "embedding",
    "metadata",
    "text",
}


def _redis_client() -> redis.Redis:
    broker_url = getattr(settings, "CELERY_BROKER_URL", None)
    if not broker_url:
        raise CommandError("CELERY_BROKER_URL is not configured")

    parsed = urlparse(broker_url)
    if parsed.scheme not in {"redis", "rediss"}:
        raise CommandError(f"Unsupported broker scheme for ops_queue: {parsed.scheme!r}")

    db = 0
    path = (parsed.path or "").strip("/")
    if path:
        try:
            db = int(path)
        except ValueError as exc:
            raise CommandError(f"Invalid Redis DB in CELERY_BROKER_URL: {parsed.path!r}") from exc

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


class Command(BaseCommand):
    help = "Safe Redis queue count/purge helper for ops UI"

    def add_arguments(self, parser):
        parser.add_argument("verb", choices=["count", "purge"])
        parser.add_argument("queue")

    def handle(self, *args, **options):
        verb = options["verb"]
        queue_name = options["queue"]

        if queue_name not in ALLOWED_QUEUES:
            raise CommandError(f"Queue {queue_name!r} is not allowlisted")

        client = _redis_client()

        try:
            if verb == "count":
                # Missing Redis list key should be treated as empty queue.
                count = int(client.llen(queue_name) or 0)
                self.stdout.write(str(count))
                return

            if verb == "purge":
                # Return the number of queued items before deletion.
                purged_count = int(client.llen(queue_name) or 0)
                client.delete(queue_name)
                self.stdout.write(str(purged_count))
                return

        except redis.RedisError as exc:
            raise CommandError(f"Redis error for queue {queue_name!r}: {exc}") from exc

        raise CommandError(f"Unsupported verb: {verb}")