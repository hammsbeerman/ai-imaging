from celery import shared_task
from django.db.models import Q
from django.utils import timezone

from indexer.models import Image
from indexer.duplicate_utils import file_sha256, compute_phash
from indexer.previews import abs_preview_path


def _dedupe_one(img: Image) -> None:
    changed = []

    if hasattr(img, "sha256") and not img.sha256:
        img.sha256 = file_sha256(img.path)
        changed.append("sha256")

    if hasattr(img, "phash") and not img.phash:
        try:
            source_path = (
                abs_preview_path(img.preview_path)
                or abs_preview_path(img.thumb_path)
                or img.path
            )
            img.phash = compute_phash(source_path)
            changed.append("phash")
        except Exception:
            pass

    if hasattr(img, "duplicate_group"):
        new_group = getattr(img, "sha256", "") or ""
        if img.duplicate_group != new_group:
            img.duplicate_group = new_group
            changed.append("duplicate_group")

    if hasattr(img, "duplicate_checked_at"):
        img.duplicate_checked_at = timezone.now()
        changed.append("duplicate_checked_at")

    if changed:
        seen = set()
        changed = [f for f in changed if not (f in seen or seen.add(f))]
        img.save(update_fields=changed)


@shared_task
def dedupe_image_task(image_id: str):
    img = Image.objects.get(id=image_id)
    _dedupe_one(img)
    return {"ok": True, "id": image_id}


@shared_task
def queue_missing_dedupe_task(limit: int = 500):
    qs = Image.objects.filter(skip_index=False)

    if not hasattr(Image, "sha256"):
        return {"queued": 0, "reason": "sha256 field missing"}

    filters = Q(sha256="")

    if hasattr(Image, "phash"):
        filters |= Q(phash="")

    if hasattr(Image, "duplicate_group"):
        filters |= Q(duplicate_group="")

    if hasattr(Image, "duplicate_checked_at"):
        filters |= Q(duplicate_checked_at__isnull=True)

    ids = list(
        qs.filter(filters)
        .values_list("id", flat=True)[:limit]
    )

    for image_id in ids:
        dedupe_image_task.delay(str(image_id))

    return {"queued": len(ids)}