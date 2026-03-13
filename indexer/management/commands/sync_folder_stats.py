from django.core.management.base import BaseCommand
from django.core.cache import cache
from django.db.models import Count, Q

from indexer.models import Folder, Image, PreviewStatus


class Command(BaseCommand):
    help = "Recalculate folder stats (image_count, preview_image, has_children)"

    def handle(self, *args, **options):
        self.stdout.write("Syncing folder stats...")

        folders = Folder.objects.all()

        updated = 0

        for folder in folders:

            images = Image.objects.filter(folder_id=folder.id)

            image_count = images.count()

            preview_image = (
                images
                .filter(preview_status=PreviewStatus.OK)
                .order_by("-width", "-height", "-mtime")
                .only("id")
                .first()
            )

            preview_image_id = preview_image.id if preview_image else None

            has_children = Folder.objects.filter(parent_id=folder.id).exists()

            dirty = False

            if folder.image_count != image_count:
                folder.image_count = image_count
                dirty = True

            if folder.file_count != image_count:
                folder.file_count = image_count
                dirty = True

            if folder.preview_image_id != preview_image_id:
                folder.preview_image_id = preview_image_id
                dirty = True

            if folder.has_children != has_children:
                folder.has_children = has_children
                dirty = True

            if dirty:
                folder.save(
                    update_fields=[
                        "image_count",
                        "file_count",
                        "preview_image",
                        "has_children",
                    ]
                )
                updated += 1
        cache.clear()

        self.stdout.write(self.style.SUCCESS(f"Updated {updated} folders"))