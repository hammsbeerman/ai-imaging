from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import HttpRequest, HttpResponseBadRequest, HttpResponseRedirect
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from urllib.parse import urlsplit

from .ops_actions import ALLOWED_ACTIONS, collect_ops_status, get_action_spec, run_ops_action

logger = logging.getLogger(__name__)

try:
    from .models import TaskLog
except Exception:  # pragma: no cover
    TaskLog = None


def _is_ops_user(user) -> bool:
    return bool(user.is_authenticated and (user.is_staff or user.is_superuser))


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


from urllib.parse import urlsplit

@login_required
@user_passes_test(_is_ops_user)
@require_POST
def run_dashboard_ops_action(request: HttpRequest):
    action = (request.POST.get("action") or "").strip().lower()
    target = (request.POST.get("target") or "").strip().lower()

    raw_next = (request.POST.get("next") or "/ai/ui/").strip()

    parts = urlsplit(raw_next)
    next_path = parts.path or "/ai/ui/"

    while next_path.startswith("/ai/ai/"):
        next_path = next_path.replace("/ai/ai/", "/ai/", 1)

    if not next_path.startswith("/"):
        next_path = "/" + next_path

    spec = get_action_spec(action, target)
    if spec is None:
        return HttpResponseBadRequest("Invalid ops action")

    try:
        result = run_ops_action(action, target, timeout=120)
    except Exception as exc:
        logger.exception("Ops action failed before completion")
        messages.error(request, f"{action} {target} failed: {exc}")
        return HttpResponseRedirect(next_path)

    _log_ops_result(request, action, target, result)

    if result.returncode == 0:
        messages.success(request, f"{spec.label} completed.")
    else:
        err = (result.stderr or result.stdout or "unknown error").strip().splitlines()
        short_err = err[-1] if err else "unknown error"
        messages.error(request, f"{spec.label} failed: {short_err}")

    return HttpResponseRedirect(next_path)


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