import os
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "media_index.settings")

app = Celery("media_index")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks(
    [
        "indexer",
    ]
)

existing_imports = tuple(getattr(app.conf, "imports", ()) or ())
app.conf.imports = existing_imports + (
    "indexer.tasks",
    "indexer.tasks_preview",
    "indexer.tasks_metadata",
    "indexer.tasks_dedupe",
)