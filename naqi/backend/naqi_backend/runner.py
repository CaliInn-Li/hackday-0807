from __future__ import annotations

import os
import signal
import subprocess
import threading
from pathlib import Path
from typing import Protocol

from .config import Settings
from .db import Job


class JobRunner(Protocol):
    def run(self, job: Job, cancel_event: threading.Event) -> int:
        ...

    def cancel(self, job_id: str) -> None:
        ...


class PipelineRunner:
    """Runs only the existing shell script through argv, never through a shell."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._processes: dict[str, subprocess.Popen[bytes]] = {}
        self._lock = threading.RLock()

    def run(self, job: Job, cancel_event: threading.Event) -> int:
        if self.settings.pipeline_script is None:
            raise RuntimeError("NAQI_PIPELINE_SCRIPT is not configured")
        logs_dir = job.job_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = logs_dir / "stdout.log"
        stderr_path = logs_dir / "stderr.log"
        env = os.environ.copy()
        if job.mapping_side != "auto":
            env["NAQI_MAPPING_SIDE"] = job.mapping_side
        else:
            env.pop("NAQI_MAPPING_SIDE", None)
        if job.fps is not None:
            env["NAQI_FPS"] = str(job.fps)
        else:
            env.pop("NAQI_FPS", None)
        env["NAQI_RENDER_KEYFRAMES"] = "1" if job.render_keyframes else "0"
        argv = [
            self.settings.bash_binary,
            str(self.settings.pipeline_script),
            str(job.video_path),
            str(job.character_path),
            str(job.job_dir),
            job.camera_mode,
        ]
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        popen_kwargs: dict[str, object] = {
            "args": argv,
            "cwd": str(self.settings.pipeline_script.parent),
            "env": env,
            "stdin": subprocess.DEVNULL,
            "stdout": stdout_path.open("ab"),
            "stderr": stderr_path.open("ab"),
            "shell": False,
            "creationflags": creationflags,
        }
        if os.name != "nt":
            popen_kwargs["start_new_session"] = True
        try:
            process = subprocess.Popen(**popen_kwargs)  # type: ignore[arg-type]
        except Exception:
            for stream_name in ("stdout", "stderr"):
                stream = popen_kwargs[stream_name]
                if hasattr(stream, "close"):
                    stream.close()  # type: ignore[union-attr]
            raise
        with self._lock:
            self._processes[job.id] = process
        try:
            while True:
                result = process.poll()
                if result is not None:
                    return int(result)
                if cancel_event.wait(0.25):
                    self._terminate_process(job.id, process)
                    return int(process.wait())
        finally:
            with self._lock:
                self._processes.pop(job.id, None)
            for stream_name in ("stdout", "stderr"):
                stream = popen_kwargs[stream_name]
                if hasattr(stream, "close"):
                    stream.close()  # type: ignore[union-attr]

    def cancel(self, job_id: str) -> None:
        with self._lock:
            process = self._processes.get(job_id)
        if process is not None:
            self._terminate_process(job_id, process)

    def _terminate_process(self, job_id: str, process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            return
        try:
            if os.name != "nt":
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
        except (ProcessLookupError, OSError):
            pass
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                if os.name != "nt":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
            except (ProcessLookupError, OSError):
                pass
        del job_id
