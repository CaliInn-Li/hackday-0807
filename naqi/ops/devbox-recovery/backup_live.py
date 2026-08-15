#!/usr/bin/env python3
"""Create a consistent live backup of NAQI service state.

The service stays online. The script refuses to copy mutable asset files while
an asset job is queued or running unless --allow-active is explicitly used.
SQLite is copied through its online backup API, never by copying WAL files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_HOME = Path("/home/naqi")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command: list[str], *, cwd: Path | None = None) -> str:
    return subprocess.run(
        command,
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    ).stdout.strip()


def run_optional(command: list[str], *, cwd: Path | None = None) -> str | None:
    try:
        return run(command, cwd=cwd)
    except (OSError, subprocess.CalledProcessError):
        return None


def active_jobs(database: Path) -> list[dict[str, str]]:
    if not database.is_file():
        raise FileNotFoundError(database)
    found: list[dict[str, str]] = []
    with sqlite3.connect(database) as connection:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if "asset_jobs" in tables:
            for row in connection.execute(
                "SELECT id, job_type, status FROM asset_jobs "
                "WHERE status IN ('queued', 'running')"
            ):
                found.append({"id": row[0], "type": row[1], "status": row[2]})
        if "jobs" in tables:
            for row in connection.execute(
                "SELECT id, status FROM jobs WHERE status IN ('queued', 'running')"
            ):
                found.append({"id": row[0], "type": "full", "status": row[1]})
    return found


def sqlite_online_backup(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source) as source_connection:
        with sqlite3.connect(destination) as destination_connection:
            source_connection.backup(destination_connection)
            result = destination_connection.execute("PRAGMA integrity_check").fetchone()
            destination_connection.execute("PRAGMA journal_mode=DELETE")
            destination_connection.commit()
    if result is None or result[0] != "ok":
        raise RuntimeError(f"SQLite integrity_check failed: {result}")


def copy_data_root(source: Path, destination: Path, database_name: str) -> None:
    ignored_names = {database_name, f"{database_name}-wal", f"{database_name}-shm"}

    def ignore(_directory: str, names: list[str]) -> set[str]:
        return {name for name in names if name in ignored_names or name == ".uploads"}

    shutil.copytree(source, destination, dirs_exist_ok=True, ignore=ignore)


def package_inventory(python: Path) -> dict[str, Any]:
    snippet = (
        "import importlib.metadata as m,json,platform,sys;"
        "items=sorted(({\"name\":d.metadata.get(\"Name\",d.metadata.get(\"Summary\",\"unknown\")),"
        "\"version\":d.version} for d in m.distributions()),key=lambda x:x[\"name\"].lower());"
        "print(json.dumps({\"python\":sys.version,\"executable\":sys.executable,"
        "\"platform\":platform.platform(),\"packages\":items}))"
    )
    return json.loads(run([str(python), "-c", snippet]))


def file_inventory(roots: list[Path], include_hashes: bool) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for root in roots:
        if not root.exists():
            records.append({"path": str(root), "missing": True})
            continue
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            record: dict[str, Any] = {
                "path": str(path),
                "size_bytes": path.stat().st_size,
            }
            if include_hashes:
                record["sha256"] = sha256(path)
            records.append(record)
    return records


def backup_manifest(root: Path) -> list[dict[str, Any]]:
    records = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.name in {"backup-manifest.json", ".backup-in-progress"} or path.name.endswith(
            ("-wal", "-shm")
        ):
            continue
        try:
            size_bytes = path.stat().st_size
            checksum = sha256(path)
        except FileNotFoundError:
            continue
        records.append(
            {
                "path": str(path.relative_to(root)),
                "size_bytes": size_bytes,
                "sha256": checksum,
            }
        )
    return records


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=DEFAULT_HOME)
    parser.add_argument("--service-root", type=Path)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--backup-root", type=Path)
    parser.add_argument("--hash-models", action="store_true")
    parser.add_argument("--allow-active", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    home = args.home.expanduser().resolve()
    service_root = (
        args.service_root
        or home / "demo-services" / "naqi-backend-25f55c9"
    ).resolve()
    repo = service_root / "repo"
    backend = repo / "naqi" / "backend"
    data_root = (args.data_root or home / "demo-data" / "naqi-backend").resolve()
    database = Path(os.environ.get("NAQI_DATABASE_PATH", data_root / "naqi.sqlite3"))
    backup_root = (args.backup_root or home / "backups").resolve()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = backup_root / f"naqi-live-{timestamp}"
    destination.mkdir(parents=True, mode=0o700)
    in_progress = destination / ".backup-in-progress"
    in_progress.write_text(timestamp + "\n", encoding="utf-8")

    jobs = active_jobs(database)
    if jobs and not args.allow_active:
        shutil.rmtree(destination)
        raise SystemExit(
            "Refusing live file copy while jobs are active: " + json.dumps(jobs)
        )

    data_destination = destination / "data"
    copy_data_root(data_root, data_destination, database.name)
    sqlite_online_backup(database, data_destination / database.name)

    config_dir = destination / "config"
    config_dir.mkdir()
    backend_env = backend / ".env"
    if backend_env.is_file():
        copied_env = config_dir / "backend.env"
        shutil.copy2(backend_env, copied_env)
        copied_env.chmod(0o600)
    shutil.copy2(backend / ".env.example", config_dir / "backend.env.example")

    code_dir = destination / "code"
    code_dir.mkdir()
    run(["git", "bundle", "create", str(code_dir / "hackday.bundle"), "--all"], cwd=repo)
    git_state = {
        "head": run(["git", "rev-parse", "HEAD"], cwd=repo),
        "status_porcelain": run(["git", "status", "--porcelain"], cwd=repo),
    }
    (code_dir / "git-state.json").write_text(
        json.dumps(git_state, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    ml_git_state: dict[str, Any] = {}
    for project_name in ("GVHMR", "SkinTokens"):
        project = home / project_name
        if not (project / ".git").is_dir():
            continue
        run(
            ["git", "bundle", "create", str(code_dir / f"{project_name}.bundle"), "--all"],
            cwd=project,
        )
        ml_git_state[project_name] = {
            "head": run(["git", "rev-parse", "HEAD"], cwd=project),
            "status_porcelain": run(["git", "status", "--porcelain"], cwd=project),
        }
    (code_dir / "ml-git-state.json").write_text(
        json.dumps(ml_git_state, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    environment_dir = destination / "environments"
    environment_dir.mkdir()
    environments = {
        "gvhmr": home / "GVHMR" / ".venv310" / "bin" / "python",
        "skintokens": home / "SkinTokens" / ".venv" / "bin" / "python",
        "backend": backend / ".venv" / "bin" / "python",
    }
    for name, python in environments.items():
        inventory = package_inventory(python)
        (environment_dir / f"{name}-packages.json").write_text(
            json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        package_lines = [
            f"{item['name']}=={item['version']}" for item in inventory["packages"]
        ]
        (environment_dir / f"{name}-freeze.txt").write_text(
            "\n".join(package_lines) + "\n", encoding="utf-8"
        )
        pyvenv = python.parents[1] / "pyvenv.cfg"
        if pyvenv.is_file():
            shutil.copy2(pyvenv, environment_dir / f"{name}-pyvenv.cfg")

    model_roots = [
        home / "GVHMR" / "inputs" / "checkpoints",
        home / "SkinTokens" / "experiments",
        home / "SkinTokens" / "models" / "Qwen3-0.6B",
    ]
    model_records = file_inventory(model_roots, args.hash_models)
    (destination / "model-files.json").write_text(
        json.dumps(model_records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    wheel_records = file_inventory(
        [home / "GVHMR" / "wheelhouse", home / "SkinTokens" / "wheelhouse"],
        include_hashes=False,
    )
    (destination / "offline-wheel-files.json").write_text(
        json.dumps(wheel_records, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    system = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "hostname": platform.node(),
        "platform": platform.platform(),
        "home": str(home),
        "service_root": str(service_root),
        "data_root": str(data_root),
        "active_jobs": jobs,
        "persistent_python_runtimes": [
            str((home / "GVHMR/bootstrap/runtime310/python").resolve()),
            str((home / "SkinTokens/bootstrap/runtime311").resolve()),
        ],
        "persistent_wheelhouses": [
            str(home / "GVHMR/wheelhouse"),
            str(home / "SkinTokens/wheelhouse"),
        ],
        "persistent_toolchains": str(home / "toolchains"),
        "nvidia_smi": run_optional(
            [
                "nvidia-smi",
                "--query-gpu=name,driver_version,memory.total,compute_cap",
                "--format=csv,noheader",
            ]
        ),
        "nvcc": run_optional(["nvcc", "--version"]),
        "mise": run_optional([str(home / "toolchains/mise/mise"), "--version"]),
        "node22": run_optional(
            [str(home / "toolchains/mise/mise"), "exec", "node@22", "--", "node", "--version"]
        ),
        "blender_archive": str(home / "toolchains/blender-4.5.12-linux-x64.tar.gz"),
    }
    (destination / "system.json").write_text(
        json.dumps(system, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    manifest = {
        "format_version": 1,
        "created_at": system["created_at"],
        "files": backup_manifest(destination),
    }
    (destination / "backup-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    in_progress.unlink()
    print(destination)


if __name__ == "__main__":
    main()
