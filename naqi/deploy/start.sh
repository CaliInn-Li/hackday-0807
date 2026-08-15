#!/usr/bin/env bash
set -Eeuo pipefail

DEPLOY_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
NAQI_ROOT=$(cd -- "$DEPLOY_DIR/.." && pwd)
BACKEND_DIR=${NAQI_BACKEND_DIR:-"$NAQI_ROOT/backend"}
STATIC_ROOT=${NAQI_GATEWAY_STATIC_ROOT:-"$NAQI_ROOT/frontend/dist"}
STATE_DIR=${NAQI_SERVICE_STATE_DIR:-"$DEPLOY_DIR/.runtime"}
LOG_DIR=${NAQI_SERVICE_LOG_DIR:-"$STATE_DIR/logs"}
GATEWAY_PORT=${NAQI_GATEWAY_PORT:-18000}

mkdir -p "$STATE_DIR" "$LOG_DIR"

pid_is_running() {
  [[ -f "$1" ]] && kill -0 "$(cat "$1")" 2>/dev/null
}

if [[ ! -x "$BACKEND_DIR/.venv/bin/python" ]]; then
  echo "Backend venv missing. Run ./bootstrap_and_start.sh or ../backend/bootstrap.sh first." >&2
  exit 1
fi
if [[ ! -f "$BACKEND_DIR/.env" ]]; then
  echo "Backend .env missing. Copy ../backend/.env.example and configure real runtime paths." >&2
  exit 1
fi
set -a
# shellcheck disable=SC1090
source "$BACKEND_DIR/.env"
set +a
PUBLIC_PORT=${NAQI_PUBLIC_PORT:-18080}
ADMIN_HOST=${NAQI_ADMIN_HOST:-127.0.0.1}
case "$ADMIN_HOST" in
  127.0.0.1|localhost|::1) ;;
  *) echo "Refusing to start: NAQI_ADMIN_HOST must remain loopback-only." >&2; exit 1 ;;
esac
if [[ ! -f "$STATIC_ROOT/index.html" ]]; then
  echo "Frontend dist missing. Run ./bootstrap_and_start.sh or build ../frontend first." >&2
  exit 1
fi

if ! pid_is_running "$STATE_DIR/backend.pid"; then
  cd "$BACKEND_DIR"
  nohup ./start.sh > "$LOG_DIR/backend.log" 2>&1 </dev/null &
  echo $! > "$STATE_DIR/backend.pid"
fi

for _ in $(seq 1 60); do
  curl -fsS "http://127.0.0.1:$PUBLIC_PORT/health/live" >/dev/null && break
  sleep 1
done
curl -fsS "http://127.0.0.1:$PUBLIC_PORT/health/live" >/dev/null

if ! pid_is_running "$STATE_DIR/gateway.pid"; then
  cd "$DEPLOY_DIR"
  nohup env \
    NAQI_GATEWAY_STATIC_ROOT="$STATIC_ROOT" \
    NAQI_GATEWAY_PORT="$GATEWAY_PORT" \
    NAQI_GATEWAY_API_PORT="$PUBLIC_PORT" \
    node "$DEPLOY_DIR/http_gateway.mjs" > "$LOG_DIR/gateway.log" 2>&1 </dev/null &
  echo $! > "$STATE_DIR/gateway.pid"
fi

for _ in $(seq 1 30); do
  curl -fsS "http://127.0.0.1:$GATEWAY_PORT/api/health/live" >/dev/null && break
  sleep 1
done
curl -fsS "http://127.0.0.1:$GATEWAY_PORT/api/health/live"
printf '\nbackend_pid=%s gateway_pid=%s gateway_port=%s\n' \
  "$(cat "$STATE_DIR/backend.pid")" "$(cat "$STATE_DIR/gateway.pid")" "$GATEWAY_PORT"
