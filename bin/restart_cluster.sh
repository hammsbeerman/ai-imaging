#!/usr/bin/env bash
set -euo pipefail

REMOTE_HOST="ubuntu@192.168.0.66"

restart_local() {
    local svc="$1"
    echo "==> Restarting local ${svc}..."
    sudo systemctl restart "${svc}"
}

echo "==> Restarting local services..."
restart_local media-index-celery-beat
restart_local media-index-gunicorn

echo "==> Fast-restarting workers on ${REMOTE_HOST}..."
ssh -o BatchMode=yes "${REMOTE_HOST}" 'bash -s' <<'EOF'
set -euo pipefail

sudo -n true

service_exists() {
    local svc="$1"
    systemctl list-unit-files "${svc}.service" --no-legend 2>/dev/null | grep -q "^${svc}\.service"
}

fast_restart() {
    local svc="$1"

    if ! service_exists "${svc}"; then
        echo "--> skipping ${svc} (service does not exist)"
        return 0
    fi

    echo "--> restarting ${svc}"

    if systemctl is-active --quiet "${svc}"; then
        echo "    sending SIGTERM to ${svc}"
        sudo -n systemctl kill -s SIGTERM "${svc}" || true
        sleep 5
    fi

    if systemctl is-active --quiet "${svc}"; then
        echo "    still active, sending SIGKILL to ${svc}"
        sudo -n systemctl kill -s SIGKILL "${svc}" || true
        sleep 2
    fi

    echo "    resetting failed state for ${svc}"
    sudo -n systemctl reset-failed "${svc}" || true

    echo "    starting ${svc}"
    sudo -n systemctl start "${svc}"
    sleep 2

    if systemctl is-active --quiet "${svc}"; then
        echo "    OK: ${svc} is running"
    else
        echo "    ERROR: ${svc} did not come back up"
        sudo systemctl --no-pager --full status "${svc}" || true
        exit 1
    fi
}

fast_restart media-index-celery-worker
fast_restart media-index-celery-worker-ops
fast_restart media-index-celery-worker-control
fast_restart media-index-celery-worker-document-sync
fast_restart media-index-celery-worker-embedding
fast_restart media-index-celery-worker-mail
fast_restart media-index-celery-worker-metadata
fast_restart media-index-celery-worker-ocr
fast_restart media-index-celery-worker-ocr-dispatch
fast_restart media-index-celery-worker-preview
fast_restart media-index-celery-worker-scan
fast_restart media-index-celery-worker-text

echo "==> Remote worker restart complete"
EOF

echo "==> Local service status"
sudo systemctl --no-pager --full status media-index-celery-beat media-index-gunicorn | sed -n '1,40p'

echo "==> Done"