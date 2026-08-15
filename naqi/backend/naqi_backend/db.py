from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STATUSES = {"queued", "running", "succeeded", "failed", "cancelled"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Job:
    id: str
    status: str
    camera_mode: str
    mapping_side: str
    fps: float | None
    render_keyframes: bool
    job_dir: Path
    video_path: Path
    character_path: Path
    original_video_name: str
    original_character_name: str
    created_at: str
    updated_at: str
    started_at: str | None = None
    finished_at: str | None = None
    video_sha256: str | None = None
    character_sha256: str | None = None
    error: str | None = None


class JobDatabase:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    camera_mode TEXT NOT NULL,
                    mapping_side TEXT NOT NULL,
                    fps REAL,
                    render_keyframes INTEGER NOT NULL,
                    job_dir TEXT NOT NULL,
                    video_path TEXT NOT NULL,
                    character_path TEXT NOT NULL,
                    original_video_name TEXT NOT NULL,
                    original_character_name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    video_sha256 TEXT,
                    character_sha256 TEXT,
                    error TEXT
                )
                """
            )
            columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(jobs)").fetchall()
            }
            for name in ("started_at", "finished_at", "video_sha256", "character_sha256"):
                if name not in columns:
                    connection.execute(f"ALTER TABLE jobs ADD COLUMN {name} TEXT")
            connection.commit()

    def check(self) -> bool:
        with self._lock, self._connect() as connection:
            connection.execute("SELECT 1").fetchone()
        return True

    def _row_to_job(self, row: sqlite3.Row) -> Job:
        return Job(
            id=row["id"],
            status=row["status"],
            camera_mode=row["camera_mode"],
            mapping_side=row["mapping_side"],
            fps=row["fps"],
            render_keyframes=bool(row["render_keyframes"]),
            job_dir=Path(row["job_dir"]),
            video_path=Path(row["video_path"]),
            character_path=Path(row["character_path"]),
            original_video_name=row["original_video_name"],
            original_character_name=row["original_character_name"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            video_sha256=row["video_sha256"],
            character_sha256=row["character_sha256"],
            error=row["error"],
        )

    def create(self, job: Job) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO jobs (
                    id, status, camera_mode, mapping_side, fps, render_keyframes,
                    job_dir, video_path, character_path, original_video_name,
                    original_character_name, created_at, updated_at, started_at,
                    finished_at, video_sha256, character_sha256, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.id,
                    job.status,
                    job.camera_mode,
                    job.mapping_side,
                    job.fps,
                    int(job.render_keyframes),
                    str(job.job_dir),
                    str(job.video_path),
                    str(job.character_path),
                    job.original_video_name,
                    job.original_character_name,
                    job.created_at,
                    job.updated_at,
                    job.started_at,
                    job.finished_at,
                    job.video_sha256,
                    job.character_sha256,
                    job.error,
                ),
            )
            connection.commit()

    def get(self, job_id: str) -> Job | None:
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._row_to_job(row) if row else None

    def list_jobs(self) -> list[Job]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC"
            ).fetchall()
        return [self._row_to_job(row) for row in rows]

    def update_status(self, job_id: str, status: str, error: str | None = None) -> None:
        if status not in STATUSES:
            raise ValueError(f"unsupported job status: {status}")
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE jobs
                SET status = ?, error = ?, updated_at = ?,
                    started_at = CASE
                        WHEN ? = 'running' AND started_at IS NULL THEN ?
                        ELSE started_at
                    END,
                    finished_at = CASE
                        WHEN ? IN ('succeeded', 'failed', 'cancelled') THEN COALESCE(finished_at, ?)
                        ELSE finished_at
                    END
                WHERE id = ?
                """,
                (status, error, utc_now(), status, utc_now(), status, utc_now(), job_id),
            )
            connection.commit()

    def update_hashes(self, job_id: str, video_sha256: str, character_sha256: str) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE jobs
                SET video_sha256 = ?, character_sha256 = ?, updated_at = ?
                WHERE id = ?
                """,
                (video_sha256, character_sha256, utc_now(), job_id),
            )
            connection.commit()

    def mark_running_interrupted(self) -> int:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE jobs
                SET status = 'failed', error = 'interrupted by service restart',
                    updated_at = ?, finished_at = COALESCE(finished_at, ?)
                WHERE status = 'running'
                """,
                (utc_now(), utc_now()),
            )
            connection.commit()
            return cursor.rowcount

    def queued_ids(self) -> list[str]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT id FROM jobs WHERE status = 'queued' ORDER BY created_at"
            ).fetchall()
        return [str(row["id"]) for row in rows]

    def as_dict(self, job: Job) -> dict[str, Any]:
        return {
            "id": job.id,
            "job_family": "full",
            "job_type": "full",
            "status": job.status,
            "camera_mode": job.camera_mode,
            "mapping_side": job.mapping_side,
            "fps": job.fps,
            "render_keyframes": job.render_keyframes,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
            "started_at": job.started_at,
            "finished_at": job.finished_at,
            "duration_seconds": duration_seconds(job),
            "video_sha256": job.video_sha256,
            "character_sha256": job.character_sha256,
            "error": job.error,
        }

    @staticmethod
    def options_json(job: Job) -> str:
        return json.dumps(
            {
                "camera_mode": job.camera_mode,
                "mapping_side": job.mapping_side,
                "fps": job.fps,
                "render_keyframes": job.render_keyframes,
            },
            sort_keys=True,
        )


def duration_seconds(job: Job) -> float | None:
    if not job.started_at or not job.finished_at:
        return None
    try:
        started = datetime.fromisoformat(job.started_at)
        finished = datetime.fromisoformat(job.finished_at)
    except ValueError:
        return None
    return max(0.0, (finished - started).total_seconds())
