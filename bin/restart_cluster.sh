#!/bin/bash
set -euo pipefail

REMOTE_HOST="ubuntu@192.168.0.66"

echo "==> Restarting local beat..."
sudo systemctl restart media-index-celery-beat

echo "==> Restarting local gunicorn..."
sudo systemctl restart media-index-gunicorn

echo "==> Fast-restarting workers on ${REMOTE_HOST}..."
ssh -o BatchMode=yes "${REMOTE_HOST}" 'bash -s' <<'EOF'
set -euo pipefail

sudo -n true

fast_restart() {
    local svc="$1"
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
fast_restart media-index-celery-worker-preview
fast_restart media-index-celery-worker-embedding
fast_restart media-index-celery-worker-scan

echo "==> Remote worker restart complete"
EOF

echo "==> Local service status"
sudo systemctl --no-pager --full status media-index-celery-beat media-index-gunicorn | sed -n '1,40p'

echo "==> Done"
