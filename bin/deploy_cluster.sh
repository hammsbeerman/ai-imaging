#!/usr/bin/env bash
set -euo pipefail

###############################################################################
# Cluster deploy script
#
# - Runs local deploy first
# - Runs deploy on any number of remote nodes
# - Tracks success/failure per node
# - Can pass ROLE to remote deploys later
# - Continues through remote failures and prints summary at end
###############################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_DEPLOY_SCRIPT="$SCRIPT_DIR/deploy.sh"
SSH_BIN="/usr/bin/ssh"

SSH_OPTS=(
  -o BatchMode=yes
  -o ConnectTimeout=10
  -o StrictHostKeyChecking=yes
)

# Format per line:
#   name|host|remote_deploy_script|role
NODES=(
  "worker-1|192.168.0.66|/opt/media-index-prod/media_index/bin/deploy.sh|worker"
)

SUCCESSES=()
FAILURES=()

resolve_script() {
  local path="$1"
  if [[ -e "$path" ]]; then
    readlink -f "$path" || realpath "$path" || echo "$path"
  else
    echo "$path"
  fi
}

log_block() {
  echo
  echo "=================================================="
  echo "==> $1"
  echo "=================================================="
}

run_local() {
  log_block "Running local deploy on $(hostname)"

  if [[ ! -f "$LOCAL_DEPLOY_SCRIPT" ]]; then
    echo "ERROR: local deploy script not found: $LOCAL_DEPLOY_SCRIPT"
    exit 1
  fi

  echo "Using local deploy script: $(resolve_script "$LOCAL_DEPLOY_SCRIPT")"
  ROLE="web" bash "$LOCAL_DEPLOY_SCRIPT"
  SUCCESSES+=("local:$(hostname)")
}

run_remote_node() {
  local name="$1"
  local host="$2"
  local remote_script="$3"
  local role="${4:-worker}"

  log_block "Running remote deploy on ${name} (${host}) role=${role}"

  if "$SSH_BIN" "${SSH_OPTS[@]}" "$host" "test -f '$remote_script'"; then
    echo "Using remote deploy script on ${host}: $("$SSH_BIN" "${SSH_OPTS[@]}" "$host" "readlink -f '$remote_script' || realpath '$remote_script' || echo '$remote_script'")"
    if "$SSH_BIN" "${SSH_OPTS[@]}" "$host" "ROLE='$role' bash '$remote_script'"; then
      SUCCESSES+=("${name}:${host}")
    else
      echo "ERROR: remote deploy failed on ${name} (${host})"
      FAILURES+=("${name}:${host}")
    fi
  else
    echo "ERROR: cannot access remote deploy script on ${name} (${host}): $remote_script"
    FAILURES+=("${name}:${host}")
  fi
}

print_summary() {
  log_block "Cluster deploy summary"

  echo "Successful nodes:"
  if [[ ${#SUCCESSES[@]} -eq 0 ]]; then
    echo "  none"
  else
    for item in "${SUCCESSES[@]}"; do
      echo "  - $item"
    done
  fi

  echo
  echo "Failed nodes:"
  if [[ ${#FAILURES[@]} -eq 0 ]]; then
    echo "  none"
  else
    for item in "${FAILURES[@]}"; do
      echo "  - $item"
    done
  fi

  echo
  if [[ ${#FAILURES[@]} -gt 0 ]]; then
    echo "Cluster deploy completed with failures."
    exit 1
  fi

  echo "Cluster deploy complete."
}

main() {
  run_local

  for node in "${NODES[@]}"; do
    IFS='|' read -r name host remote_script role <<< "$node"
    run_remote_node "$name" "$host" "$remote_script" "$role"
  done

  print_summary
}

main "$@"