from celery import shared_task
from django.db import close_old_connections

from indexer.models import Image
from indexer.preview_health import preview_files_exist
from indexer.tasks_preview import repair_missing_previews_task as active_repair_missing_previews_task


@shared_task
def repair_missing_previews_task(limit: int = 500):
    close_old_connections()
    return active_repair_missing_previews_task(limit)