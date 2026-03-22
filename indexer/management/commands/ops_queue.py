from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from kombu import Connection


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


class Command(BaseCommand):
    help = "Safe queue count/purge helper for ops UI"

    def add_arguments(self, parser):
        parser.add_argument("verb", choices=["count", "purge"])
        parser.add_argument("queue")

    def handle(self, *args, **options):
        verb = options["verb"]
        queue_name = options["queue"]

        if queue_name not in ALLOWED_QUEUES:
            raise CommandError(f"Queue {queue_name!r} is not allowlisted")

        broker_url = getattr(settings, "CELERY_BROKER_URL", None)
        if not broker_url:
            raise CommandError("CELERY_BROKER_URL is not configured")

        with Connection(broker_url) as conn:
            channel = conn.channel()

            if verb == "count":
                try:
                    result = channel.queue_declare(queue=queue_name, passive=True)
                except Exception as exc:
                    raise CommandError(f"Could not read queue {queue_name!r}: {exc}") from exc

                count = getattr(result, "message_count", None)
                if count is None and isinstance(result, (tuple, list)) and len(result) >= 2:
                    count = result[1]
                self.stdout.write(str(count or 0))
                return

            if verb == "purge":
                try:
                    result = channel.queue_purge(queue=queue_name)
                except Exception as exc:
                    raise CommandError(f"Could not purge queue {queue_name!r}: {exc}") from exc

                purged_count = getattr(result, "message_count", result)
                self.stdout.write(str(purged_count or 0))
                return

        raise CommandError(f"Unsupported verb: {verb}")