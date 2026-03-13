from django.core.management.base import BaseCommand
from indexer.scanner import scan_directory


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument("path")

    def handle(self, *args, **kwargs):
        n = scan_directory(kwargs["path"])
        self.stdout.write(self.style.SUCCESS(f"Scan complete. New items: {n}"))