import os
from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "media_index.settings")

app = Celery("media_index")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()