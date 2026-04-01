from django.utils import timezone
from datetime import timedelta

STALE_MINUTES = 10


def stage_health(
    *,
    queue_depth=0,
    last_success=None,
    last_attempt=None,
    last_failure=None,
    processed_last_5m=0,
):
    now = timezone.now()

    def minutes_ago(ts):
        if not ts:
            return None
        return (now - ts).total_seconds() / 60

    last_success_age = minutes_ago(last_success)
    last_attempt_age = minutes_ago(last_attempt)

    # ---- classification ----
    if queue_depth > 0:
        if last_success_age is None or last_success_age > STALE_MINUTES:
            status = "stalled"
        elif processed_last_5m == 0:
            status = "blocked"
        else:
            status = "running"
    else:
        if processed_last_5m > 0:
            status = "draining"
        else:
            status = "idle"

    if last_failure and (minutes_ago(last_failure) or 0) < 5:
        status = "failing"

    return {
        "status": status,
        "queue_depth": queue_depth,
        "last_success": last_success,
        "last_attempt": last_attempt,
        "last_failure": last_failure,
        "processed_last_5m": processed_last_5m,
    }