from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass(frozen=True)
class OpsActionSpec:
    action: str
    target: str
    command: Tuple[str, ...]
    confirm: bool = False
    label: str = ""


SYSTEMD_SERVICES: Dict[str, str] = {
    "web": "media-index-gunicorn",
    "beat": "media-index-celery-beat",
    "ops": "media-index-celery-worker-ops",
    "preview": "media-index-celery-worker-preview",
    "text": "media-index-celery-worker-text",
    "embedding": "media-index-celery-worker-embedding",
    "mail": "media-index-celery-worker-mail",
    "metadata": "media-index-celery-worker-metadata",
    "ocr": "media-index-celery-worker-ocr",
    "ocr_dispatch": "media-index-celery-worker-ocr-dispatch",
    "document_sync": "media-index-celery-worker-document-sync",
    "scan": "media-index-celery-worker-scan",
    "control": "media-index-celery-worker-control",
}

CELERY_QUEUES: Dict[str, str] = {
    "ops": "ops",
    "preview": "preview",
    "scan": "scan",
    "ocr": "ocr",
    "mail": "mail",
    "control": "control",
    "embedding": "embedding",
    "metadata": "metadata",
    "text": "text",
    "ocr_dispatch": "ocr_dispatch",
    "document_sync": "document_sync",
    "celery": "celery",
}


def _wrapper_cmd(*parts: str) -> Tuple[str, ...]:
    return ("/usr/bin/sudo", "/usr/local/bin/media-index-ops", *parts)


def build_allowed_actions() -> Dict[Tuple[str, str], OpsActionSpec]:
    actions: Dict[Tuple[str, str], OpsActionSpec] = {}

    for target, service_name in SYSTEMD_SERVICES.items():
        pretty = target.replace("_", " ").title()

        actions[("start", target)] = OpsActionSpec(
            action="start",
            target=target,
            command=_wrapper_cmd("service", "start", service_name),
            label=f"Start {pretty}",
        )
        actions[("stop", target)] = OpsActionSpec(
            action="stop",
            target=target,
            command=_wrapper_cmd("service", "stop", service_name),
            confirm=True,
            label=f"Stop {pretty}",
        )
        actions[("restart", target)] = OpsActionSpec(
            action="restart",
            target=target,
            command=_wrapper_cmd("service", "restart", service_name),
            confirm=True,
            label=f"Restart {pretty}",
        )

    for target, queue_name in CELERY_QUEUES.items():
        pretty = target.replace("_", " ").title()
        actions[("purge", target)] = OpsActionSpec(
            action="purge",
            target=target,
            command=_wrapper_cmd("queue", "purge", queue_name),
            confirm=True,
            label=f"Purge {pretty} Queue",
        )

    return actions


ALLOWED_ACTIONS = build_allowed_actions()


def get_action_spec(action: str, target: str) -> OpsActionSpec | None:
    return ALLOWED_ACTIONS.get((action, target))


def run_ops_action(action: str, target: str, timeout: int = 120) -> subprocess.CompletedProcess:
    spec = get_action_spec(action, target)
    if not spec:
        raise ValueError(f"Unsupported ops action: action={action!r} target={target!r}")

    return subprocess.run(
        spec.command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def describe_command(action: str, target: str) -> str:
    spec = get_action_spec(action, target)
    if not spec:
        return ""
    return shlex.join(spec.command)


def get_queue_count(target: str, timeout: int = 30) -> int | None:
    queue_name = CELERY_QUEUES.get(target)
    if not queue_name:
        return None

    result = subprocess.run(
        _wrapper_cmd("queue", "count", queue_name),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        return None

    raw = (result.stdout or "").strip()
    try:
        return int(raw)
    except Exception:
        return None


def get_service_status(target: str, timeout: int = 30) -> str:
    service_name = SYSTEMD_SERVICES.get(target)
    if not service_name:
        return "unknown"

    result = subprocess.run(
        _wrapper_cmd("service", "status", service_name),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )

    raw = ((result.stdout or "") + "\n" + (result.stderr or "")).strip().lower()

    for known in ("active", "inactive", "failed", "activating", "deactivating"):
        if raw == known or f"\n{known}\n" in f"\n{raw}\n" or raw.startswith(known):
            return known

    return "unknown"


def collect_ops_status() -> dict:
    return {
        "services": {
            key: {
                "name": SYSTEMD_SERVICES[key],
                "status": get_service_status(key),
            }
            for key in SYSTEMD_SERVICES.keys()
        },
        "queues": {
            key: {
                "name": CELERY_QUEUES[key],
                "count": get_queue_count(key),
            }
            for key in CELERY_QUEUES.keys()
        },
    }