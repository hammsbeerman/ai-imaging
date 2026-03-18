# Ensure Celery registers split task modules for the indexer app.

from . import tasks  # noqa: F401
from . import tasks_preview  # noqa: F401
from . import tasks_preview_repair  # noqa: F401
from . import tasks_text  # noqa: F401
from . import tasks_metadata  # noqa: F401
from . import tasks_embedding  # noqa: F401
from . import tasks_dedupe  # noqa: F401
from . import tasks_queue_health  # noqa: F401
from . import tasks_stats  # noqa: F401
from . import tasks_folder_health  # noqa: F401
from . import tasks_recovery  # noqa: F401