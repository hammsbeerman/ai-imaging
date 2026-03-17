import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "media_index.settings")

app = Celery("media_index")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# Explicit imports help avoid stale autodiscovery issues in production.
app.conf.imports = (
    "indexer.tasks",
    "indexer.tasks_discovery",
    "indexer.tasks_metadata",
    "indexer.tasks_preview",
    "indexer.tasks_text",
    "indexer.tasks_embedding",
    "indexer.tasks_metrics",
    "indexer.tasks_recovery",
    "indexer.tasks_queue_health",
    "indexer.tasks_dedupe",
    "indexer.tasks_duplicate_groups",
    "indexer.tasks_preview_repair",
    "indexer.tasks_maintenance",
)
