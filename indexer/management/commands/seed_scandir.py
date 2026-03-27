from django.core.management.base import BaseCommand
from django.utils import timezone
from indexer.models import ScanDir, IndexerSettings


class Command(BaseCommand):
    help = "Seed ScanDir queue with IndexerSettings.scan_path"

    def handle(self, *args, **options):
        s = IndexerSettings.load()
        obj, created = ScanDir.objects.update_or_create(
            path=s.scan_path,
            defaults={
                "done": False,
                "retry_at": timezone.now(),
                "last_error": None,
            },
        )
        self.stdout.write(self.style.SUCCESS(f"Seeded {obj.path} (created={created})"))