#!/usr/bin/env bash
set -Eeuo pipefail

DEPLOY_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
NAQI_ROOT=$(cd -- "$DEPLOY_DIR/.." && pwd)

if [[ ! -f "$NAQI_ROOT/backend/.env" ]]; then
  echo "Create $NAQI_ROOT/backend/.env from .env.example before running this script." >&2
  exit 1
fi

if [[ ! -x "$NAQI_ROOT/backend/.venv/bin/python" ]]; then
  "$NAQI_ROOT/backend/bootstrap.sh"
fi

cd "$NAQI_ROOT/frontend"
npm ci
VITE_NAQI_API_BASE=/api npm run build

exec "$DEPLOY_DIR/start.sh"
