#!/usr/bin/env bash
set -Eeuo pipefail

BACKEND_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
VENV_DIR=${NAQI_VENV_DIR:-"$BACKEND_DIR/.venv"}
ENV_FILE=${NAQI_ENV_FILE:-"$BACKEND_DIR/.env"}

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  echo "Missing backend venv at $VENV_DIR; run ./bootstrap.sh first." >&2
  exit 1
fi

export PYTHONPATH="$BACKEND_DIR${PYTHONPATH:+:$PYTHONPATH}"
exec "$VENV_DIR/bin/python" -m naqi_backend.main "$@"
