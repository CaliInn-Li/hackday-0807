#!/usr/bin/env bash
set -Eeuo pipefail

DEPLOY_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
NAQI_ROOT=$(cd -- "$DEPLOY_DIR/.." && pwd)
BACKEND_DIR=${NAQI_BACKEND_DIR:-"$NAQI_ROOT/backend"}
STATE_DIR=${NAQI_SERVICE_STATE_DIR:-"$DEPLOY_DIR/.runtime"}
GATEWAY_PORT=${NAQI_GATEWAY_PORT:-18000}
if [[ -f "$BACKEND_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$BACKEND_DIR/.env"
  set +a
fi
ADMIN_PORT=${NAQI_ADMIN_PORT:-18081}

for service in backend gateway; do
  pid_file="$STATE_DIR/$service.pid"
  if [[ -f "$pid_file" ]] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
    printf '%s=running pid=%s\n' "$service" "$(cat "$pid_file")"
  else
    printf '%s=stopped\n' "$service"
  fi
done

printf 'public_live='
curl -fsS "http://127.0.0.1:$GATEWAY_PORT/api/health/live"
printf '\nadmin_ready='
curl -sS -w ' http_status=%{http_code}' "http://127.0.0.1:$ADMIN_PORT/health/ready"
printf '\n'
