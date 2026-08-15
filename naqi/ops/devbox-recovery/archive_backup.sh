#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 /home/naqi/backups/naqi-live-YYYYmmddTHHMMSSZ" >&2
  exit 2
fi

BACKUP=$(cd -- "$1" && pwd)
PARENT=$(dirname -- "$BACKUP")
NAME=$(basename -- "$BACKUP")
ARCHIVE="$PARENT/$NAME.tar.gz"

[[ -f "$BACKUP/backup-manifest.json" ]] || { echo "Invalid backup directory" >&2; exit 1; }
nice -n 19 ionice -c3 tar -C "$PARENT" -czf "$ARCHIVE" "$NAME"
gzip -t "$ARCHIVE"
sha256sum "$ARCHIVE" | tee "$ARCHIVE.sha256"
ls -lh "$ARCHIVE" "$ARCHIVE.sha256"
