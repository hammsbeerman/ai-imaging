from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import HttpRequest, HttpResponseBadRequest, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .ops_actions import ALLOWED_ACTIONS, collect_ops_status, get_action_spec, run_ops_action

from .tasks_documents import queue_missing_document_sync_task
from .tasks_embedding import queue_missing_embeddings_task
from .tasks_folder_health import rebuild_folder_health_snapshot_task
from .tasks_metadata import queue_missing_metadata_task
from .tasks_preview import queue_missing_previews_task
from .tasks_queue_health import rebuild_queue_health_snapshot_task
from .tasks_recovery import (
    reset_stale_embedding_task,
    reset_stale_metadata_task,
    reset_stale_pipeline_processing_task,
    reset_stale_preview_task,
    reset_stale_text_task,
)
from .tasks_stats import rebuild_archive_stats_task
from .tasks_text import queue_missing_text_task

logger = logging.getLogger(__name__)

try:
    from .models import TaskLog
except Exception:  # pragma: no cover
    TaskLog = None


def _is_ops_user(user) -> bool:
    return bool(user.is_authenticated and (user.is_staff or user.is_superuser))


DIRECT_TASK_ACTIONS = {
    "rebuild_snapshot": {
        "label": "Rebuild queue snapshot",
        "runner": lambda: rebuild_queue_health_snapshot_task.delay(45),
    },
    "rebuild_archive_stats": {
        "label": "Rebuild archive stats",
        "runner": lambda: rebuild_archive_stats_task.delay(),
    },
    "rebuild_folder_health": {
        "label": "Rebuild folder health snapshot",
        "runner": lambda: rebuild_folder_health_snapshot_task.delay(),
    },
    "reset_stale_preview": {
        "label": "Reset stale preview rows",
        "runner": lambda: reset_stale_preview_task.delay(),
    },
    "reset_stale_text": {
        "label": "Reset stale text rows",
        "runner": lambda: reset_stale_text_task.delay(),
    },
    "reset_stale_metadata": {
        "label": "Reset stale metadata rows",
        "runner": lambda: reset_stale_metadata_task.delay(),
    },
    "reset_stale_embedding": {
        "label": "Reset stale embedding rows",
        "runner": lambda: reset_stale_embedding_task.delay(),
    },
    "reset_stale_all": {
        "label": "Reset all stale pipeline rows",
        "runner": lambda: reset_stale_pipeline_processing_task.delay(),
    },
    "queue_preview_work": {
        "label": "Queue missing previews",
        "runner": lambda: queue_missing_previews_task.delay(64, 8),
    },
    "queue_text_work": {
        "label": "Queue missing text work",
        "runner": lambda: queue_missing_text_task.delay(200, 10),
    },
    "queue_metadata_work": {
        "label": "Queue missing metadata work",
        "runner": lambda: queue_missing_metadata_task.delay(256, 16),
    },
    "queue_embedding_work": {
        "label": "Queue missing embedding work",
        "runner": lambda: queue_missing_embeddings_task.delay(256, 16),
    },
    "queue_document_sync": {
        "label": "Queue missing document sync work",
        "runner": lambda: queue_missing_document_sync_task.delay(200, 25),
    },
}


def _log_ops_result(request: HttpRequest, action: str, target: str, result) -> None:
    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    msg = (
        f"ops_ui action={action} target={target} rc={result.returncode}\n"
        f"stdout:\n{stdout}\n\nstderr:\n{stderr}"
    )

    if TaskLog is not None:
        try:
            TaskLog.objects.create(
                source="ops_ui",
                level="info" if result.returncode == 0 else "error",
                message=msg,
            )
            return
        except Exception:
            logger.exception("Failed writing TaskLog for ops action")

    if result.returncode == 0:
        logger.info(msg)
    else:
        logger.error(msg)


@login_required
@user_passes_test(_is_ops_user)
@require_POST
def run_dashboard_ops_action(request: HttpRequest):
    action = (request.POST.get("action") or "").strip().lower()
    target = (request.POST.get("target") or "").strip().lower()
    next_url = reverse("ui_home")

    direct_spec = DIRECT_TASK_ACTIONS.get(action)
    if direct_spec is not None:
        try:
            async_result = direct_spec["runner"]()
            messages.success(
                request,
                f"{direct_spec['label']} queued."
                + (f" Task id: {async_result.id}" if getattr(async_result, "id", None) else ""),
            )
        except Exception as exc:
            logger.exception("Direct task action failed before completion")
            messages.error(request, f"{direct_spec['label']} failed: {exc}")
        return HttpResponseRedirect(next_url)

    spec = get_action_spec(action, target)
    if spec is None:
        return HttpResponseBadRequest("Invalid ops action")

    try:
        result = run_ops_action(action, target, timeout=120)
    except Exception as exc:
        logger.exception("Ops action failed before completion")
        messages.error(request, f"{action} {target} failed: {exc}")
        return HttpResponseRedirect(next_url)

    _log_ops_result(request, action, target, result)

    if result.returncode == 0:
        messages.success(request, f"{spec.label} completed.")
    else:
        err = (result.stderr or result.stdout or "unknown error").strip().splitlines()
        short_err = err[-1] if err else "unknown error"
        messages.error(request, f"{spec.label} failed: {short_err}")

    return HttpResponseRedirect(next_url)


@login_required
@user_passes_test(_is_ops_user)
@require_GET
def ops_status_partial(request: HttpRequest):
    context = {
        "ops_status": collect_ops_status(),
        "ops_status_updated_at": timezone.localtime(),
    }
    return render(request, "indexer/partials/ops_controls.html", context)


def ops_action_specs_for_template():
    return sorted(ALLOWED_ACTIONS.values(), key=lambda x: (x.target, x.action))