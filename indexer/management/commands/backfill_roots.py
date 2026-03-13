from django.core.management.base import BaseCommand

from indexer.models import Image, AccessRoot
from indexer.scanner import _pick_root


class Command(BaseCommand):
    help = "Backfill Image.root using AccessRoot longest-prefix match"

    def handle(self, *args, **options):
        roots = list(AccessRoot.objects.all())

        if not roots:
            self.stdout.write(self.style.WARNING("No AccessRoot rows exist. Nothing to do."))
            return

        qs = Image.objects.filter(root__isnull=True)
        total = qs.count()

        self.stdout.write(f"Scanning {total} images for root matches...")

        updated = 0

        for img in qs.iterator(chunk_size=500):
            root_obj = _pick_root(img.path, roots)

            if root_obj:
                img.root = root_obj
                img.save(update_fields=["root"])
                updated += 1

        self.stdout.write(self.style.SUCCESS(f"Done. Updated {updated} images."))