#!/usr/bin/env bash
set -euo pipefail

APP_BASE="/opt/media-index-prod"
APP_ROOT="$APP_BASE/media_index"
VENV="$APP_BASE/venv"
OPS_SCRIPT="$APP_BASE/bin/media-index-ops"
OPS_LINK="/usr/local/bin/media-index-ops"

SUDOERS_SRC="$APP_BASE/deploy/sudoers/media-index-ops"
SUDOERS_DST="/etc/sudoers.d/media-index-ops"
SUDOERS_TMP="/tmp/media-index-ops.sudoers.$$"

ROLE="${ROLE:-all}"

service_exists() {
  local svc="$1"
  systemctl list-unit-files "${svc}.service" --no-legend 2>/dev/null | grep -q "^${svc}\.service"
}

install_ops_sudoers() {
  if [[ ! -f "$SUDOERS_SRC" ]]; then
    echo "==> No sudoers template found at $SUDOERS_SRC, skipping"
    return 0
  fi

  echo "==> Installing sudoers rule for media-index-ops"

  cp "$SUDOERS_SRC" "$SUDOERS_TMP"
  chmod 440 "$SUDOERS_TMP"

  if sudo visudo -cf "$SUDOERS_TMP"; then
    if ! sudo cmp -s "$SUDOERS_TMP" "$SUDOERS_DST" 2>/dev/null; then
      sudo cp "$SUDOERS_TMP" "$SUDOERS_DST"
      sudo chmod 440 "$SUDOERS_DST"
      echo "    updated $SUDOERS_DST"
    else
      echo "    sudoers unchanged"
    fi
  else
    echo "    ERROR: sudoers validation failed for $SUDOERS_SRC"
    rm -f "$SUDOERS_TMP"
    exit 1
  fi

  rm -f "$SUDOERS_TMP"
}

force_stop_service() {
  local svc="$1"
  local stop_timeout="${2:-3}"

  if ! service_exists "$svc"; then
    echo "==> Skipping ${svc} (service does not exist)"
    return 0
  fi

  if ! systemctl is-active --quiet "$svc"; then
    echo "==> ${svc} already stopped"
    return 0
  fi

  echo "==> Stopping ${svc} (timeout: ${stop_timeout}s)"

  if sudo timeout "${stop_timeout}" systemctl stop "$svc"; then
    echo "    ${svc} stopped cleanly"
  else
    echo "    ${svc} did not stop in time, force killing"
    sudo systemctl kill --signal=SIGKILL --kill-who=all "$svc" || true
    sleep 1
    sudo systemctl reset-failed "$svc" || true
  fi
}

start_service() {
  local svc="$1"

  if ! service_exists "$svc"; then
    echo "==> Skipping ${svc} (service does not exist)"
    return 0
  fi

  echo "==> Starting ${svc}"
  sudo systemctl start "$svc"

  if systemctl is-active --quiet "$svc"; then
    echo "    ${svc} is running"
  else
    echo "    ERROR: ${svc} failed to start"
    sudo systemctl status "$svc" --no-pager || true
    exit 1
  fi
}

restart_service_hard() {
  local svc="$1"

  if ! service_exists "$svc"; then
    echo "==> Skipping ${svc} (service does not exist)"
    return 0
  fi

  force_stop_service "$svc" 2
  start_service "$svc"
}

get_requirements_for_role() {
  case "$ROLE" in
    web)
      cat <<EOF
$APP_BASE/requirements/base.txt
EOF
      ;;
    preview)
      cat <<EOF
$APP_BASE/requirements/base.txt
$APP_BASE/requirements/imaging.txt
EOF
      ;;
    embedding)
      cat <<EOF
$APP_BASE/requirements/base.txt
$APP_BASE/requirements/imaging.txt
$APP_BASE/requirements/gpu.txt
EOF
      ;;
    scan)
      cat <<EOF
$APP_BASE/requirements/base.txt
$APP_BASE/requirements/imaging.txt
EOF
      ;;
    worker)
      cat <<EOF
$APP_BASE/requirements/base.txt
$APP_BASE/requirements/imaging.txt
EOF
      ;;
    all)
      cat <<EOF
$APP_BASE/requirements.txt
$APP_BASE/requirements/base.txt
$APP_BASE/requirements/imaging.txt
$APP_BASE/requirements/gpu.txt
EOF
      ;;
    *)
      echo "ERROR: Unknown ROLE='$ROLE'" >&2
      exit 1
      ;;
  esac
}

get_services_for_role() {
  case "$ROLE" in
    web)
      cat <<EOF
media-index-gunicorn
media-index-celery-beat
EOF
      ;;
    preview)
      cat <<EOF
media-index-celery-worker-preview
EOF
      ;;
    embedding)
      cat <<EOF
media-index-celery-worker-embedding
EOF
      ;;
    scan)
      cat <<EOF
media-index-celery-worker-scan
EOF
      ;;
    worker)
      cat <<EOF
media-index-celery-worker
media-index-celery-worker-ops
media-index-celery-worker-ocr
media-index-celery-worker-mail
media-index-celery-worker-control
media-index-celery-worker-text
media-index-celery-worker-metadata
EOF
      ;;
    all)
      cat <<EOF
media-index-gunicorn
media-index-celery-beat
media-index-celery-worker
media-index-celery-worker-ops
media-index-celery-worker-scan
media-index-celery-worker-preview
media-index-celery-worker-ocr
media-index-celery-worker-mail
media-index-celery-worker-control
media-index-celery-worker-text
media-index-celery-worker-metadata
media-index-celery-worker-embedding
EOF
      ;;
    *)
      echo "ERROR: Unknown ROLE='$ROLE'" >&2
      exit 1
      ;;
  esac
}

build_role_hash() {
  local hash_file_input=()
  while IFS= read -r req; do
    [[ -n "$req" ]] || continue
    if [[ -f "$req" ]]; then
      hash_file_input+=("$req")
    fi
  done < <(get_requirements_for_role)

  if [[ ${#hash_file_input[@]} -eq 0 ]]; then
    echo ""
    return 0
  fi

  sha256sum "${hash_file_input[@]}" | sha256sum | awk '{print $1}'
}

install_requirements_for_role() {
  echo "==> Installing requirements for role: $ROLE"

  case "$ROLE" in
    web)
      pip install -r "$APP_BASE/requirements/base.txt"
      ;;
    preview|scan|worker)
      pip install -r "$APP_BASE/requirements/base.txt"
      pip install -r "$APP_BASE/requirements/imaging.txt"
      ;;
    embedding)
      pip install -r "$APP_BASE/requirements/base.txt"
      pip install -r "$APP_BASE/requirements/imaging.txt"
      pip install -r "$APP_BASE/requirements/gpu.txt"
      ;;
    all)
      pip install -r "$APP_BASE/requirements.txt"
      ;;
    *)
      echo "ERROR: Unknown ROLE='$ROLE'" >&2
      exit 1
      ;;
  esac
}

ROLE_HASH_FILE="$APP_BASE/.last_requirements_sha256_${ROLE}"

cd "$APP_ROOT"

echo "==> Pulling latest code"
git checkout main
git pull origin main

echo "==> Deploy role: $ROLE"

echo "==> Linking ops script"
if [ -f "$OPS_SCRIPT" ]; then
  sudo ln -sf "$OPS_SCRIPT" "$OPS_LINK"
  sudo chmod +x "$OPS_SCRIPT"
  echo "    linked $OPS_LINK -> $OPS_SCRIPT"
else
  echo "    WARNING: ops script not found at $OPS_SCRIPT, skipping link"
fi

install_ops_sudoers

echo "==> Activating venv"
source "$VENV/bin/activate"

NEW_HASH="$(build_role_hash)"
OLD_HASH="$(cat "$ROLE_HASH_FILE" 2>/dev/null || true)"

if [[ -n "$NEW_HASH" ]]; then
  if [[ "$NEW_HASH" != "$OLD_HASH" ]]; then
    install_requirements_for_role
    echo "$NEW_HASH" > "$ROLE_HASH_FILE"
  else
    echo "==> Requirements unchanged for role '$ROLE', skipping pip install"
  fi
else
  echo "==> No requirements files found for role '$ROLE', skipping pip install"
fi

if [[ "$ROLE" == "web" || "$ROLE" == "all" ]]; then
  echo "==> Running migrations (role: $ROLE)"

  python manage.py shell -c "
from django.db import connection
from django.core.management import call_command
with connection.cursor() as cursor:
    cursor.execute('SELECT pg_try_advisory_lock(918273645);')
    locked = cursor.fetchone()[0]
if not locked:
    raise SystemExit('Another migration process is already running.')
call_command('migrate')
"
else
  echo "==> Skipping migrations (role: $ROLE)"
fi

if [[ "$ROLE" == "web" || "$ROLE" == "all" ]]; then
  echo "==> Running Django check (role: $ROLE)"
  python manage.py check
else
  echo "==> Skipping Django check (role: $ROLE)"
fi

echo "==> Hard restarting services for role: $ROLE"
while IFS= read -r svc; do
  [[ -n "$svc" ]] || continue
  restart_service_hard "$svc"
done < <(get_services_for_role)

echo "==> Deploy complete on $(hostname) for role '$ROLE'"