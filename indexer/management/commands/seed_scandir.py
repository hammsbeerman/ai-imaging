from django.core.management.base import BaseCommand
from indexer.models import ScanDir, IndexerSettings


class Command(BaseCommand):
    help = "Seed ScanDir queue with IndexerSettings.scan_path"

    def handle(self, *args, **options):
        s = IndexerSettings.load()
        obj, created = ScanDir.objects.get_or_create(path=s.scan_path)
        self.stdout.write(self.style.SUCCESS(f"Seeded {obj.path} (created={created})"))