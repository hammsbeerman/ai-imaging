from celery import shared_task
from django.db import close_old_connections
from django.db.models import Q
from django.utils import timezone

from indexer.duplicate_utils import compute_phash, file_sha256
from indexer.models import Image
from indexer.previews import abs_preview_path


QUEUE_PICK_LIMIT = 500
WORKER_BATCH_SIZE = 50


def _chunked(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def _dedupe_one(img: Image) -> None:
    changed = []

    if hasattr(img, "sha256") and not img.sha256:
        img.sha256 = file_sha256(img.path)
        changed.append("sha256")

    if hasattr(img, "phash") and not img.phash:
        try:
            source_path = abs_preview_path(img.preview_path) or abs_preview_path(img.thumb_path) or img.path
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
def dedupe_batch_task(image_ids):
    close_old_connections()
    rows = Image.objects.filter(id__in=image_ids).only(
        "id", "path", "preview_path", "thumb_path", "sha256", "phash",
        "duplicate_group", "duplicate_checked_at",
    )
    by_id = {str(img.id): img for img in rows}

    ok = 0
    missing = 0
    for image_id in image_ids:
        img = by_id.get(str(image_id))
        if not img:
            missing += 1
            continue
        _dedupe_one(img)
        ok += 1

    return {"selected": len(image_ids), "ok": ok, "missing": missing}


@shared_task
def queue_missing_dedupe_task(limit: int = QUEUE_PICK_LIMIT, chunk_size: int = WORKER_BATCH_SIZE):
    close_old_connections()
    qs = Image.objects.filter(skip_index=False)

    filters = Q(sha256="")
    if hasattr(Image, "phash"):
        filters |= Q(phash="")
    if hasattr(Image, "duplicate_group"):
        filters |= Q(duplicate_group="")
    if hasattr(Image, "duplicate_checked_at"):
        filters |= Q(duplicate_checked_at__isnull=True)

    ids = list(qs.filter(filters).order_by("id").values_list("id", flat=True)[:limit])
    submitted = 0
    for batch_ids in _chunked([str(x) for x in ids], chunk_size):
        dedupe_batch_task.delay(batch_ids)
        submitted += 1

    return {"queued": len(ids), "submitted_batches": submitted}
