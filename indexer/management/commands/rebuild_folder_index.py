from django.core.cache import cache
from django.core.management.base import BaseCommand

from indexer.models import Folder, Image


def normalize_rel_dir(path: str) -> str:
    return (path or "").replace("\\", "/").strip("/")


def split_parts(rel_dir: str) -> list[str]:
    rel_dir = normalize_rel_dir(rel_dir)
    if not rel_dir:
        return []
    return [p for p in rel_dir.split("/") if p]


class Command(BaseCommand):
    help = "Rebuild Folder rows and Image.folder links from Image.relative_dir"

    def handle(self, *args, **options):
        self.stdout.write("Rebuilding folder index...")

        # Clear existing links first so deleting folders is clean
        Image.objects.exclude(folder__isnull=True).update(folder=None)
        Folder.objects.all().delete()

        folder_cache = {}
        processed = 0

        # Materialize rows first so SQLite does not keep a read cursor open
        # while we do writes in the same loop.
        images = list(
            Image.objects.exclude(root__isnull=True)
            .values(
                "id",
                "root_id",
                "relative_dir",
                "customer_name",
                "probable_job_number",
                "preview_status",
            )
            .order_by("id")
        )

        for img in images:
            rel_dir = normalize_rel_dir(img["relative_dir"] or "")
            parts = split_parts(rel_dir)

            parent = None
            built = []

            for depth, part in enumerate(parts, start=1):
                built.append(part)
                rel_path = "/".join(built)
                key = (img["root_id"], rel_path)

                folder = folder_cache.get(key)
                if folder is None:
                    folder, _ = Folder.objects.get_or_create(
                        root_id=img["root_id"],
                        path=rel_path,
                        defaults={
                            "rel_path": rel_path,
                            "name": part,
                            "depth": depth,
                            "parent": parent,
                            "has_children": False,
                            "customer_name": "",
                            "probable_job_number": "",
                        },
                    )
                    folder_cache[key] = folder

                if parent and not parent.has_children:
                    parent.has_children = True
                    parent.save(update_fields=["has_children"])

                parent = folder

            leaf = parent
            if leaf:
                Image.objects.filter(id=img["id"]).update(folder=leaf)

                updates = []

                leaf.image_count += 1
                leaf.file_count += 1
                updates.extend(["image_count", "file_count"])

                if not leaf.customer_name and img["customer_name"]:
                    leaf.customer_name = img["customer_name"]
                    updates.append("customer_name")

                if not leaf.probable_job_number and img["probable_job_number"]:
                    leaf.probable_job_number = img["probable_job_number"]
                    updates.append("probable_job_number")

                if leaf.preview_image_id is None and img["preview_status"] == "ok":
                    leaf.preview_image_id = img["id"]
                    updates.append("preview_image")

                if updates:
                    leaf.save(update_fields=updates)

            processed += 1
            if processed % 1000 == 0:
                self.stdout.write(f"Processed {processed} images...")

        cache.clear()
        self.stdout.write(self.style.SUCCESS(f"Done. Processed {processed} images."))