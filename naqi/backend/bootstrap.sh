#!/usr/bin/env bash
set -Eeuo pipefail

BACKEND_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PYTHON_BIN=${PYTHON_BIN:-python3.11}
VENV_DIR=${NAQI_VENV_DIR:-"$BACKEND_DIR/.venv"}

"$PYTHON_BIN" -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r "$BACKEND_DIR/requirements.txt"
echo "NAQI backend environment ready: $VENV_DIR"
