from __future__ import annotations

import hashlib
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path
from typing import Protocol

from .assets import ASSET_MIME_TYPES, Asset, AssetDatabase, AssetJob
from .config import Settings


class AssetStageRunner(Protocol):
    def run(self, job: AssetJob, database: AssetDatabase, cancel_event: threading.Event) -> int:
        ...

    def cancel(self, job_id: str) -> None:
        ...


class StageRunner:
    """Launches the backend's dependency-light stage adapter.

    The adapter then invokes the configured SkinTokens/GVHMR/Blender tools.
    This layer never imports those runtimes and shares the single worker queue
    with the legacy full-pipeline runner.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._processes: dict[str, subprocess.Popen[bytes]] = {}
        self._lock = threading.RLock()

    def run(self, job: AssetJob, database: AssetDatabase, cancel_event: threading.Event) -> int:
        asset = database.get_asset(job.asset_id)
        if asset is None:
            raise RuntimeError(f"asset does not exist: {job.asset_id}")
        job.work_dir.mkdir(parents=True, exist_ok=True)
        asset.root_dir.mkdir(parents=True, exist_ok=True)
        argv = self._adapter_argv(job, asset, database)
        env = os.environ.copy()
        if self.settings.pipeline_tools_dir is not None:
            env["NAQI_PIPELINE_TOOLS_DIR"] = str(self.settings.pipeline_tools_dir)
        if self.settings.skintokens_home is not None:
            env["SKINTOKENS_HOME"] = str(self.settings.skintokens_home)
        if self.settings.gvhmr_home is not None:
            env["GVHMR_HOME"] = str(self.settings.gvhmr_home)
        env["BLENDER_BIN"] = self.settings.blender_bin
        if env.get("NAQI_MAPPING_SIDE") == "auto":
            # run_naqi_pipeline.sh intentionally implements auto by leaving
            # this variable unset; the typed adapter follows the same rule.
            env.pop("NAQI_MAPPING_SIDE", None)
        backend_root = str(Path(__file__).resolve().parents[1])
        env["PYTHONPATH"] = backend_root + os.pathsep + env.get("PYTHONPATH", "")
        stdout_path = job.work_dir / "stdout.log"
        stderr_path = job.work_dir / "stderr.log"
        popen_kwargs: dict[str, object] = {
            "args": argv,
            "cwd": backend_root,
            "env": env,
            "stdin": subprocess.DEVNULL,
            "stdout": stdout_path.open("ab"),
            "stderr": stderr_path.open("ab"),
            "shell": False,
            "creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        }
        if os.name != "nt":
            popen_kwargs["start_new_session"] = True
        try:
            process = subprocess.Popen(**popen_kwargs)  # type: ignore[arg-type]
        except Exception:
            self._close_streams(popen_kwargs)
            raise
        with self._lock:
            self._processes[job.id] = process
        try:
            while True:
                result = process.poll()
                if result is not None:
                    if int(result) == 0 and not cancel_event.is_set():
                        self._register_outputs(job, asset, database)
                    return int(result)
                if cancel_event.wait(0.25):
                    self._terminate_process(job.id, process)
                    return int(process.wait())
        finally:
            with self._lock:
                self._processes.pop(job.id, None)
            self._close_streams(popen_kwargs)

    def cancel(self, job_id: str) -> None:
        with self._lock:
            process = self._processes.get(job_id)
        if process is not None:
            self._terminate_process(job_id, process)

    def _adapter_argv(self, job: AssetJob, asset: Asset, database: AssetDatabase) -> list[str]:
        argv = [
            sys.executable,
            "-m",
            "naqi_backend.stage_adapter",
            job.job_type,
            "--output-dir",
            str(asset.root_dir),
            "--work-dir",
            str(job.work_dir),
        ]
        params = job.params
        if job.job_type == "rig":
            source = database.get_file(asset.id, "source_glb")
            if source is None:
                raise RuntimeError("character source_glb is missing")
            argv.extend(["--source", str(source.path)])
        elif job.job_type == "motion":
            source = database.get_file(asset.id, "source_mp4")
            if source is None:
                raise RuntimeError("motion source_mp4 is missing")
            argv.extend(["--source", str(source.path)])
            argv.extend(["--camera-mode", str(params.get("camera_mode", "static"))])
        else:
            if not job.character_id or not job.motion_id:
                raise RuntimeError("retarget job is missing source relations")
            character = database.get_file(job.character_id, "rigged_glb")
            mapping = database.get_file(job.character_id, "mapping")
            motion = database.get_file(job.motion_id, "motion_npz")
            if character is None or mapping is None or motion is None:
                raise RuntimeError("retarget source files are incomplete")
            argv.extend(
                [
                    "--character",
                    str(character.path),
                    "--mapping",
                    str(mapping.path),
                    "--motion",
                    str(motion.path),
                ]
            )
            if bool(params.get("render_keyframes", False)):
                argv.append("--render-keyframes")
        return argv

    def _register_outputs(self, job: AssetJob, asset: Asset, database: AssetDatabase) -> None:
        output_names: dict[str, str]
        if job.job_type == "rig":
            output_names = {
                "rigged_glb": "rigged.glb",
                "topology_report": "topology.json",
                "mapping": "mapping.json",
            }
        elif job.job_type == "motion":
            output_names = {"motion_npz": "motion.npz", "manifest": "manifest.json"}
        else:
            output_names = {
                "animated_glb": "animated.glb",
                "retarget_report": "retarget.json",
                "qa_report": "qa.json",
            }
        for file_kind, filename in output_names.items():
            path = (asset.root_dir / filename).resolve()
            if not path.is_file():
                raise RuntimeError(f"stage output is missing: {path}")
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            database.add_file(
                asset_id=asset.id,
                file_kind=file_kind,
                path=path,
                size_bytes=path.stat().st_size,
                sha256=digest.hexdigest(),
                mime_type=ASSET_MIME_TYPES[file_kind],
            )

    @staticmethod
    def _close_streams(popen_kwargs: dict[str, object]) -> None:
        for name in ("stdout", "stderr"):
            stream = popen_kwargs.get(name)
            if hasattr(stream, "close"):
                stream.close()  # type: ignore[union-attr]

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
