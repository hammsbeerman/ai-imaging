from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import HttpRequest, HttpResponseBadRequest, HttpResponseRedirect
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from .ops_actions import ALLOWED_ACTIONS, get_action_spec, run_ops_action

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
            # Adjust field names here if your TaskLog differs.
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
    next_url = (request.POST.get("next") or request.META.get("HTTP_REFERER") or "/ui/").strip()

    spec = get_action_spec(action, target)
    if spec is None:
        return HttpResponseBadRequest("Invalid ops action")

    try:
        result = run_ops_action(action, target, timeout=120)
    except Exception as exc:
        logger.exception("Ops action failed before completion")
        messages.error(request, f"{action} {target} failed: {exc}")
        return redirect(next_url)

    _log_ops_result(request, action, target, result)

    if result.returncode == 0:
        messages.success(request, f"{spec.label} completed.")
    else:
        err = (result.stderr or result.stdout or "unknown error").strip().splitlines()
        short_err = err[-1] if err else "unknown error"
        messages.error(request, f"{spec.label} failed: {short_err}")

    return HttpResponseRedirect(next_url)


def ops_action_specs_for_template():
    """
    Handy if you want to pass these from a view later.
    """
    return sorted(ALLOWED_ACTIONS.values(), key=lambda x: (x.target, x.action))