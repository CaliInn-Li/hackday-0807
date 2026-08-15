#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 /home/naqi/backups/naqi-live-YYYYmmddTHHMMSSZ" >&2
  exit 2
fi

BACKUP=$(cd -- "$1" && pwd)
NAQI_HOME=${NAQI_HOME:-/home/naqi}
SERVICE_ROOT=${NAQI_SERVICE_ROOT:-"$NAQI_HOME/demo-services/naqi-backend-25f55c9"}
REPO="$SERVICE_ROOT/repo"
DATA_ROOT=${NAQI_DATA_ROOT:-"$NAQI_HOME/demo-data/naqi-backend"}
MISE="$NAQI_HOME/toolchains/mise/mise"
SYSTEM_PACKAGES=(
  ffmpeg
  libxrender1
  libxfixes3
  libxi6
  libxkbcommon0
  libsm6
  libice6
  libgl1
)

if curl -fsS http://127.0.0.1:18080/health/live >/dev/null 2>&1; then
  echo "Refusing restore while the service is running. This script is for a recreated DevBox." >&2
  exit 1
fi
[[ -f "$BACKUP/backup-manifest.json" ]] || { echo "Invalid backup directory" >&2; exit 1; }
"$(dirname -- "${BASH_SOURCE[0]}")/verify_backup.py" "$BACKUP"

if [[ ! -x "$MISE" ]]; then
  echo "Persistent mise binary is missing: $MISE" >&2
  exit 1
fi
if ! "$MISE" exec node@22 -- node --version >/dev/null 2>&1; then
  "$MISE" use --global node@22
fi

missing_system_packages=()
for package in "${SYSTEM_PACKAGES[@]}"; do
  dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q 'install ok installed' || \
    missing_system_packages+=("$package")
done
if ((${#missing_system_packages[@]})); then
  sudo apt-get update
  sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y "${missing_system_packages[@]}"
fi

if [[ ! -x /opt/blender-4.5.12/blender ]]; then
  [[ -f "$NAQI_HOME/toolchains/blender-4.5.12-linux-x64.tar.gz" ]] || {
    echo "Persistent Blender archive is missing" >&2
    exit 1
  }
  sudo tar -C /opt -xzf "$NAQI_HOME/toolchains/blender-4.5.12-linux-x64.tar.gz"
fi
sudo ln -sfn /opt/blender-4.5.12/blender /usr/local/bin/blender
/usr/local/bin/blender --version >/dev/null
ffmpeg -version >/dev/null

if [[ ! -d "$REPO/.git" ]]; then
  mkdir -p "$SERVICE_ROOT"
  git clone "$BACKUP/code/hackday.bundle" "$REPO"
fi

if [[ -f "$DATA_ROOT/naqi.sqlite3" ]]; then
  echo "Reusing persistent data already present at $DATA_ROOT"
else
  mkdir -p "$DATA_ROOT"
  cp -a "$BACKUP/data/." "$DATA_ROOT/"
fi
mkdir -p "$REPO/naqi/backend"
if [[ ! -f "$REPO/naqi/backend/.env" ]]; then
  cp -a "$BACKUP/config/backend.env" "$REPO/naqi/backend/.env"
fi
chmod 600 "$REPO/naqi/backend/.env"
sed -i "s|^BLENDER_BIN=.*|BLENDER_BIN=/opt/blender-4.5.12/blender|" "$REPO/naqi/backend/.env"

for required in \
  "$NAQI_HOME/GVHMR/.venv310/bin/python" \
  "$NAQI_HOME/SkinTokens/.venv/bin/python"; do
  [[ -x "$required" ]] || {
    echo "Persistent ML environment is missing: $required" >&2
    echo "Restore the off-host GVHMR/SkinTokens archive before continuing." >&2
    exit 1
  }
done

cd "$REPO/naqi/backend"
[[ -x .venv/bin/python ]] || ./bootstrap.sh
cd "$REPO/naqi/frontend"
"$MISE" exec node@22 -- npm ci
VITE_NAQI_API_BASE=/api "$MISE" exec node@22 -- npm run build

cd "$REPO/naqi/deploy"
PATH="$NAQI_HOME/.local/share/mise/shims:$PATH" ./start.sh
echo "Restore complete. Run ../ops/devbox-recovery/verify_devbox.sh next."
