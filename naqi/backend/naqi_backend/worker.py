from __future__ import annotations

import queue
import threading

from .assets import AssetDatabase
from .db import JobDatabase
from .runner import JobRunner
from .stage_runner import AssetStageRunner


# A single process-wide lock makes the GPU exclusivity explicit even if a
# future caller accidentally creates more than one BackendRuntime.
GPU_EXECUTION_LOCK = threading.Lock()
WorkItem = tuple[str, str]


class JobWorker:
    """One queue for legacy full jobs and typed asset stages."""

    def __init__(
        self,
        database: JobDatabase,
        runner: JobRunner,
        asset_database: AssetDatabase | None = None,
        stage_runner: AssetStageRunner | None = None,
    ) -> None:
        self.database = database
        self.runner = runner
        self.asset_database = asset_database
        self.stage_runner = stage_runner
        self._queue: queue.Queue[WorkItem | None] = queue.Queue()
        self._cancel_events: dict[str, threading.Event] = {}
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self, queued_ids: list[str], asset_queued_ids: list[str] | None = None) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._loop,
                name="naqi-gpu-worker",
                daemon=True,
            )
            self._thread.start()
            for job_id in queued_ids:
                self._queue.put(("full", job_id))
            for job_id in asset_queued_ids or []:
                self._queue.put(("asset", job_id))

    def stop(self, timeout: float = 15.0) -> None:
        self._stop.set()
        with self._lock:
            running = list(self._cancel_events)
            for event in self._cancel_events.values():
                event.set()
        for key in running:
            kind, job_id = key.split(":", 1)
            if kind == "asset" and self.stage_runner is not None:
                self.stage_runner.cancel(job_id)
            elif kind == "full":
                self.runner.cancel(job_id)
        self._queue.put(None)
        thread = self._thread
        if thread:
            thread.join(timeout=timeout)

    def enqueue(self, job_id: str) -> None:
        self._enqueue("full", job_id)

    def enqueue_asset(self, job_id: str) -> None:
        if self.asset_database is None or self.stage_runner is None:
            raise RuntimeError("typed asset worker is not configured")
        self._enqueue("asset", job_id)

    def _enqueue(self, kind: str, job_id: str) -> None:
        with self._lock:
            self._cancel_events.setdefault(f"{kind}:{job_id}", threading.Event())
        self._queue.put((kind, job_id))

    def cancel(self, job_id: str) -> bool:
        job = self.database.get(job_id)
        if job is None or job.status in {"succeeded", "failed", "cancelled"}:
            return False
        self._mark_cancelled("full", job_id)
        if job.status == "running":
            self.runner.cancel(job_id)
        return True

    def cancel_asset(self, job_id: str) -> bool:
        if self.asset_database is None or self.stage_runner is None:
            return False
        job = self.asset_database.get_job(job_id)
        if job is None or job.status in {"ready", "failed", "cancelled"}:
            return False
        self._mark_cancelled("asset", job_id)
        if job.status == "running":
            self.stage_runner.cancel(job_id)
        return True

    def _mark_cancelled(self, kind: str, job_id: str) -> None:
        with self._lock:
            self._cancel_events.setdefault(f"{kind}:{job_id}", threading.Event()).set()
        if kind == "asset" and self.asset_database is not None:
            self.asset_database.update_job_status(job_id, "cancelled", "cancelled by client")
        else:
            self.database.update_status(job_id, "cancelled", "cancelled by client")

    def _loop(self) -> None:
        while not self._stop.is_set():
            item = self._queue.get()
            if item is None:
                return
            kind, job_id = item
            if kind == "asset":
                self._run_asset(job_id)
            else:
                self._run_full(job_id)

    def _run_full(self, job_id: str) -> None:
        job = self.database.get(job_id)
        if job is None or job.status != "queued":
            return
        key = f"full:{job_id}"
        with self._lock:
            event = self._cancel_events.setdefault(key, threading.Event())
        if event.is_set():
            self.database.update_status(job_id, "cancelled", "cancelled before execution")
            return
        self.database.update_status(job_id, "running")
        try:
            with GPU_EXECUTION_LOCK:
                exit_code = self.runner.run(job, event)
            current = self.database.get(job_id)
            if event.is_set() or (current and current.status == "cancelled"):
                self.database.update_status(job_id, "cancelled", "cancelled by client")
            elif exit_code == 0:
                self.database.update_status(job_id, "succeeded")
            else:
                self.database.update_status(job_id, "failed", f"pipeline exited with code {exit_code}")
        except Exception as exc:  # noqa: BLE001 - persist worker failures for operators
            current = self.database.get(job_id)
            if current and current.status == "cancelled":
                self.database.update_status(job_id, "cancelled", "cancelled by client")
            else:
                self.database.update_status(job_id, "failed", f"runner error: {type(exc).__name__}: {exc}")
        finally:
            with self._lock:
                self._cancel_events.pop(key, None)

    def _run_asset(self, job_id: str) -> None:
        if self.asset_database is None or self.stage_runner is None:
            return
        job = self.asset_database.get_job(job_id)
        if job is None or job.status != "queued":
            return
        key = f"asset:{job_id}"
        with self._lock:
            event = self._cancel_events.setdefault(key, threading.Event())
        if event.is_set():
            self.asset_database.update_job_status(job_id, "cancelled", "cancelled before execution")
            return
        self.asset_database.update_job_status(job_id, "running")
        try:
            with GPU_EXECUTION_LOCK:
                exit_code = self.stage_runner.run(job, self.asset_database, event)
            current = self.asset_database.get_job(job_id)
            if event.is_set() or (current and current.status == "cancelled"):
                self.asset_database.update_job_status(job_id, "cancelled", "cancelled by client")
            elif exit_code == 0:
                self.asset_database.update_job_status(job_id, "ready")
            else:
                self.asset_database.update_job_status(
                    job_id, "failed", f"stage exited with code {exit_code}"
                )
        except Exception as exc:  # noqa: BLE001 - persist worker failures for operators
            current = self.asset_database.get_job(job_id)
            if current and current.status == "cancelled":
                self.asset_database.update_job_status(job_id, "cancelled", "cancelled by client")
            else:
                self.asset_database.update_job_status(
                    job_id, "failed", f"stage error: {type(exc).__name__}: {exc}"
                )
        finally:
            with self._lock:
                self._cancel_events.pop(key, None)
