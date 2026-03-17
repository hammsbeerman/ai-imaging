from celery import shared_task
from django.db import close_old_connections
from django.db.models import Count

from indexer.models import Image


@shared_task
def rebuild_duplicate_groups_task(batch_size: int = 250):
    close_old_connections()
    Image.objects.update(is_primary_duplicate=False)

    groups = list(
        Image.objects.exclude(duplicate_group="")
        .values("duplicate_group")
        .annotate(c=Count("id"))
        .filter(c__gt=1)
        .order_by("duplicate_group")
    )

    for offset in range(0, len(groups), batch_size):
        group_values = [g["duplicate_group"] for g in groups[offset:offset + batch_size]]
        members = list(
            Image.objects.filter(duplicate_group__in=group_values)
            .order_by("duplicate_group", "path", "created")
            .only("id", "duplicate_group")
        )

        seen = set()
        primary_ids = []
        for img in members:
            if img.duplicate_group not in seen:
                seen.add(img.duplicate_group)
                primary_ids.append(img.id)

        if primary_ids:
            Image.objects.filter(id__in=primary_ids).update(is_primary_duplicate=True)

    return {"groups": len(groups)}
