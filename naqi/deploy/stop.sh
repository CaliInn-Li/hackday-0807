#!/usr/bin/env bash
set -Eeuo pipefail

DEPLOY_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
STATE_DIR=${NAQI_SERVICE_STATE_DIR:-"$DEPLOY_DIR/.runtime"}

for service in gateway backend; do
  pid_file="$STATE_DIR/$service.pid"
  if [[ ! -f "$pid_file" ]]; then
    printf '%s has no pid file\n' "$service"
    continue
  fi
  pid=$(cat "$pid_file")
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid"
    for _ in $(seq 1 20); do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.25
    done
  fi
  rm -f -- "$pid_file"
  printf '%s stopped\n' "$service"
done
