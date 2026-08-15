#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify a NAQI live backup")
    parser.add_argument("backup", type=Path)
    parser.add_argument("--skip-models", action="store_true")
    args = parser.parse_args()
    root = args.backup.expanduser().resolve()

    if (root / ".backup-in-progress").exists():
        raise SystemExit(f"backup is incomplete: {root}")

    manifest = json.loads((root / "backup-manifest.json").read_text(encoding="utf-8"))
    for record in manifest["files"]:
        path = root / record["path"]
        if not path.is_file() or path.stat().st_size != record["size_bytes"]:
            raise SystemExit(f"backup file missing or wrong size: {path}")
        if sha256(path) != record["sha256"]:
            raise SystemExit(f"backup checksum mismatch: {path}")

    databases = list((root / "data").glob("*.sqlite3"))
    if len(databases) != 1:
        raise SystemExit(f"expected one SQLite backup, found: {databases}")
    with sqlite3.connect(databases[0]) as connection:
        result = connection.execute("PRAGMA integrity_check").fetchone()
    if result is None or result[0] != "ok":
        raise SystemExit(f"SQLite integrity_check failed: {result}")

    if not args.skip_models:
        models = json.loads((root / "model-files.json").read_text(encoding="utf-8"))
        for record in models:
            if record.get("missing"):
                raise SystemExit(f"model root was missing during backup: {record['path']}")
            path = Path(record["path"])
            if not path.is_file() or path.stat().st_size != record["size_bytes"]:
                raise SystemExit(f"model file missing or wrong size: {path}")
            expected = record.get("sha256")
            if expected and sha256(path) != expected:
                raise SystemExit(f"model checksum mismatch: {path}")

    print(f"backup verified: {root}")


if __name__ == "__main__":
    main()
