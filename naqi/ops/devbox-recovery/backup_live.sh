#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
NAQI_HOME=${NAQI_HOME:-/home/naqi}
PYTHON=${NAQI_BACKUP_PYTHON:-"$NAQI_HOME/demo-services/naqi-backend-25f55c9/repo/naqi/backend/.venv/bin/python"}

if [[ ! -x "$PYTHON" ]]; then
  echo "Backup Python is missing: $PYTHON" >&2
  exit 1
fi

exec nice -n 19 ionice -c3 "$PYTHON" "$SCRIPT_DIR/backup_live.py" "$@"
