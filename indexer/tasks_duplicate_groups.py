from celery import shared_task
from django.db.models import Count

from indexer.models import Image


@shared_task
def rebuild_duplicate_groups_task():
    Image.objects.update(is_primary_duplicate=False)

    groups = list(
        Image.objects.exclude(duplicate_group="")
        .values("duplicate_group")
        .annotate(c=Count("id"))
        .filter(c__gt=1)
    )

    for g in groups:
        qs = (
            Image.objects.filter(duplicate_group=g["duplicate_group"])
            .order_by("path", "created")
        )
        first = qs.first()
        if not first:
            continue

        qs.update(is_primary_duplicate=False)
        first.is_primary_duplicate = True
        first.save(update_fields=["is_primary_duplicate"])

    return {"groups": len(groups)}