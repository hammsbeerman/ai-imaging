from celery import shared_task
from django.core.cache import cache
from django.core.management import call_command
from django.utils import timezone


REBUILD_FOLDER_INDEX_STATUS_KEY = "rebuild_folder_index_status"


@shared_task
def rebuild_folder_index_task():
    cache.set(
        REBUILD_FOLDER_INDEX_STATUS_KEY,
        {
            "state": "running",
            "started_at": timezone.now().isoformat(),
            "finished_at": None,
            "message": "Folder index rebuild is running.",
        },
        timeout=60 * 60 * 6,
    )

    try:
        call_command("rebuild_folder_index")
        cache.set(
            REBUILD_FOLDER_INDEX_STATUS_KEY,
            {
                "state": "idle",
                "started_at": None,
                "finished_at": timezone.localtime().strftime("%Y-%m-%d %I:%M:%S %p"),
                "message": "Folder index rebuild completed.",
            },
            timeout=60 * 60 * 6,
        )
    except Exception as e:
        cache.set(
            REBUILD_FOLDER_INDEX_STATUS_KEY,
            {
                "state": "failed",
                "started_at": None,
                "finished_at": timezone.localtime().strftime("%Y-%m-%d %I:%M:%S %p"),
                "message": f"Folder index rebuild failed: {e}",
            },
            timeout=60 * 60 * 6,
        )
        raise