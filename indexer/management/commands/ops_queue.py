from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from kombu import Connection


ALLOWED_QUEUES = {"ops", "preview", "docs"}


class Command(BaseCommand):
    help = "Ops helper for celery queues (currently supports purge/count)."

    def add_arguments(self, parser):
        parser.add_argument("verb", choices=["purge", "count"])
        parser.add_argument("queue")

    def handle(self, *args, **options):
        verb = options["verb"]
        queue_name = options["queue"]

        if queue_name not in ALLOWED_QUEUES:
            raise CommandError(f"Queue {queue_name!r} is not allowed")

        broker_url = getattr(settings, "CELERY_BROKER_URL", None)
        if not broker_url:
            raise CommandError("CELERY_BROKER_URL is not configured")

        with Connection(broker_url) as conn:
            channel = conn.channel()

            if verb == "count":
                result = channel.queue_declare(queue=queue_name, passive=True)
                count = getattr(result, "message_count", None)
                if count is None and isinstance(result, (tuple, list)) and len(result) >= 2:
                    count = result[1]
                count = count or 0
                self.stdout.write(str(count))
                return

            if verb == "purge":
                purged = channel.queue_purge(queue=queue_name)
                purged_count = getattr(purged, "message_count", purged)
                self.stdout.write(f"Purged {purged_count} message(s) from queue '{queue_name}'")
                return

        raise CommandError(f"Unsupported verb: {verb}")