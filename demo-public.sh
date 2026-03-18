#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="$ROOT_DIR/infra/docker-compose.yml"
BACKEND_SERVICE_SRC="$ROOT_DIR/infra/systemd/places-backend.service"
NGINX_SITE_SRC="$ROOT_DIR/infra/nginx/places-demo.conf"
NGINX_SITE_DST="/etc/nginx/sites-available/places-demo"
NGINX_SITE_LINK="/etc/nginx/sites-enabled/places-demo"
NGINX_DEFAULT_LINK="/etc/nginx/sites-enabled/default"
WEB_ROOT="/var/www/places"

STATE_FILE="/tmp/places-demo-public.state"
LOCK_DIR="/tmp/places-demo-public.lock"
LOCK_PID_FILE="$LOCK_DIR/pid"

IN_UP_MODE=0
CLEANED_UP=0

log() {
  echo "[demo-public] $*"
}

warn() {
  echo "[demo-public] WARNING: $*" >&2
}

fail() {
  echo "[demo-public] ERROR: $*" >&2
  exit 1
}

require_cmd() {
  local cmd="$1"
  command -v "$cmd" >/dev/null 2>&1 || fail "Missing required command: $cmd"
}

write_state() {
  {
    echo "pid=$$"
    echo "started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  } >"$STATE_FILE"
}

is_http_open() {
  sudo ufw status | awk '
    BEGIN { found = 0 }
    $0 ~ /80\/tcp/ && $0 ~ /ALLOW IN/ { found = 1 }
    END { exit(found ? 0 : 1) }
  '
}

remove_all_http_allow_rules() {
  local removed=0
  local rule_num=""
  local rule_nums=""

  rule_nums="$(
    sudo ufw status numbered | awk '
      /^\[[[:space:]]*[0-9]+\]/ {
        line = $0
        sub(/^\[[[:space:]]*/, "", line)
        sub(/\].*$/, "", line)
        if ($0 ~ /80\/tcp/ && $0 ~ /ALLOW IN/) {
          rule_num = line
          print rule_num
        }
      }
    ' | sort -rn
  )"

  if [[ -z "$rule_nums" ]]; then
    log "No UFW 80/tcp ALLOW IN rules found."
    return 0
  fi

  while IFS= read -r rule_num; do
    [[ -z "$rule_num" ]] && continue
    printf 'y\n' | sudo ufw delete "$rule_num" >/dev/null
    removed=$((removed + 1))
  done <<<"$rule_nums"

  log "Closed public HTTP access (removed $removed UFW rule(s) for 80/tcp)."
}

cleanup_temp_state() {
  rm -f "$STATE_FILE"
  rm -f "$LOCK_PID_FILE"
  rmdir "$LOCK_DIR" 2>/dev/null || true
}

cleanup_up() {
  if [[ "$IN_UP_MODE" -ne 1 ]]; then
    return
  fi
  if [[ "$CLEANED_UP" -eq 1 ]]; then
    return
  fi
  CLEANED_UP=1

  log "Shutting down public demo access..."
  remove_all_http_allow_rules

  cleanup_temp_state
  log "Cleanup complete."
}

trap_handler() {
  cleanup_up
}

acquire_lock() {
  if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    local existing_pid=""
    if [[ -f "$LOCK_PID_FILE" ]]; then
      existing_pid="$(cat "$LOCK_PID_FILE" 2>/dev/null || true)"
    fi
    fail "Another demo-public session appears to be running${existing_pid:+ (pid: $existing_pid)}. Use './demo-public.sh down' to clean stale state."
  fi
  echo "$$" >"$LOCK_PID_FILE"
}

print_status() {
  local backend_status
  local nginx_status
  local http_status

  backend_status="$(sudo systemctl is-active places-backend 2>/dev/null || true)"
  nginx_status="$(sudo systemctl is-active nginx 2>/dev/null || true)"
  if is_http_open; then
    http_status="open"
  else
    http_status="closed"
  fi

  echo "places-backend: ${backend_status:-unknown}"
  echo "nginx: ${nginx_status:-unknown}"
  echo "public-http-80: $http_status"
  if [[ -f "$STATE_FILE" ]]; then
    echo "state-file: present ($STATE_FILE)"
  else
    echo "state-file: absent"
  fi
  if [[ -d "$LOCK_DIR" ]]; then
    echo "lock: present ($LOCK_DIR)"
  else
    echo "lock: absent"
  fi
}

preflight_up() {
  require_cmd docker
  require_cmd npm
  require_cmd rsync
  require_cmd ufw
  require_cmd systemctl
  require_cmd nginx
  require_cmd sudo

  docker compose version >/dev/null 2>&1 || fail "Docker Compose plugin is required (docker compose)."
  [[ -f "$COMPOSE_FILE" ]] || fail "Missing compose file: $COMPOSE_FILE"
  [[ -f "$BACKEND_SERVICE_SRC" ]] || fail "Missing backend systemd unit: $BACKEND_SERVICE_SRC"
  [[ -f "$NGINX_SITE_SRC" ]] || fail "Missing nginx site config: $NGINX_SITE_SRC"
}

preflight_down() {
  require_cmd ufw
  require_cmd sudo
}

preflight_status() {
  require_cmd ufw
  require_cmd systemctl
  require_cmd sudo
}

up_mode() {
  IN_UP_MODE=1
  trap trap_handler INT TERM EXIT

  preflight_up
  acquire_lock

  log "Refreshing sudo credentials..."
  sudo -v

  log "Starting database..."
  docker compose -f "$COMPOSE_FILE" up -d

  log "Building frontend..."
  (
    cd "$ROOT_DIR/frontend"
    npm install
    npm run build
  )

  log "Publishing frontend build to $WEB_ROOT..."
  sudo mkdir -p "$WEB_ROOT"
  sudo rsync -a --delete "$ROOT_DIR/frontend/dist/" "$WEB_ROOT/"

  log "Installing backend service..."
  sudo cp "$BACKEND_SERVICE_SRC" /etc/systemd/system/places-backend.service
  sudo systemctl daemon-reload
  sudo systemctl enable --now places-backend
  sudo systemctl restart places-backend

  log "Installing nginx site config..."
  sudo cp "$NGINX_SITE_SRC" "$NGINX_SITE_DST"
  sudo ln -sfn "$NGINX_SITE_DST" "$NGINX_SITE_LINK"
  sudo rm -f "$NGINX_DEFAULT_LINK"
  sudo nginx -t
  sudo systemctl reload nginx

  if is_http_open; then
    log "UFW already allows 80/tcp; leaving existing rule in place."
  else
    log "Opening public HTTP access (UFW allow 80/tcp)..."
    sudo ufw allow 80/tcp >/dev/null
  fi

  write_state

  local host_ip
  host_ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
  if [[ -z "$host_ip" ]]; then
    host_ip="<server-ip>"
  fi

  echo
  log "Demo is publicly available while this script is running."
  echo "  Frontend: http://$host_ip/"
  echo "  API:      http://$host_ip/api/health"
  echo
  log "Press Ctrl+C to close public access and exit."

  while true; do
    sleep 3600
  done
}

down_mode() {
  preflight_down
  log "Refreshing sudo credentials..."
  sudo -v

  remove_all_http_allow_rules

  cleanup_temp_state
  log "Demo down cleanup complete."
}

status_mode() {
  preflight_status
  log "Refreshing sudo credentials..."
  sudo -v
  print_status
}

usage() {
  cat <<'EOF'
Usage:
  ./demo-public.sh [up|down|status]

Modes:
  up      Build and publish frontend, refresh services, open UFW 80/tcp, and hold until Ctrl+C.
  down    Remove all UFW ALLOW IN rules for 80/tcp, then clear state/lock files.
  status  Print places-backend, nginx, and public HTTP firewall status.
EOF
}

main() {
  local mode="${1:-up}"

  case "$mode" in
  up)
    up_mode
    ;;
  down)
    down_mode
    ;;
  status)
    status_mode
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    usage
    fail "Unknown mode: $mode"
    ;;
  esac
}

main "$@"
