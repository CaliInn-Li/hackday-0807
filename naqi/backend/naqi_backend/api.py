from __future__ import annotations

import hashlib
import hmac
import os
import re
import shutil
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Callable

from fastapi import Body, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from .assets import (
    ASSET_FILE_KINDS,
    ASSET_KINDS,
    Asset,
    AssetDatabase,
    AssetJob,
)
from .config import Settings
from .db import Job, JobDatabase, utc_now
from .runner import JobRunner, PipelineRunner
from .stage_runner import AssetStageRunner, StageRunner
from .worker import JobWorker


class BackendRuntime:
    def __init__(
        self,
        settings: Settings,
        runner: JobRunner | None = None,
        stage_runner: AssetStageRunner | None = None,
    ) -> None:
        self.settings = settings
        self.database = JobDatabase(settings.database_path)
        self.asset_database = AssetDatabase(settings.database_path, settings.data_root)
        self.runner = runner or PipelineRunner(settings)
        self.stage_runner = stage_runner or StageRunner(settings)
        self.worker = JobWorker(
            self.database,
            self.runner,
            self.asset_database,
            self.stage_runner,
        )
        self._started = False
        self._lock = threading.RLock()

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self.settings.data_root.mkdir(parents=True, exist_ok=True)
            self.settings.runs_dir.mkdir(parents=True, exist_ok=True)
            self.database.initialize()
            self.asset_database.initialize()
            self.database.mark_running_interrupted()
            self.asset_database.mark_running_interrupted()
            self.worker.start(
                self.database.queued_ids(),
                self.asset_database.queued_job_ids(),
            )
            self._started = True

    def stop(self) -> None:
        with self._lock:
            if not self._started:
                return
            self.worker.stop()
            self._started = False

    async def save_upload(
        self,
        upload: UploadFile,
        destination: Path,
        expected_suffix: str,
    ) -> tuple[str, str]:
        filename = upload.filename or "upload"
        safe_name = safe_filename(filename, expected_suffix)
        digest = hashlib.sha256()
        size = 0
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with destination.open("wb") as output:
                while True:
                    chunk = await upload.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > self.settings.max_upload_bytes:
                        raise HTTPException(status_code=413, detail="uploaded file is too large")
                    digest.update(chunk)
                    output.write(chunk)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        return safe_name, digest.hexdigest()

    async def save_asset_upload(
        self,
        upload: UploadFile,
        destination: Path,
        expected_suffix: str,
    ) -> tuple[str, str, int]:
        filename = upload.filename or "upload"
        safe_name = safe_filename(filename, expected_suffix)
        digest = hashlib.sha256()
        size = 0
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with destination.open("wb") as output:
                while True:
                    chunk = await upload.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > self.settings.max_upload_bytes:
                        raise HTTPException(status_code=413, detail="uploaded file is too large")
                    digest.update(chunk)
                    output.write(chunk)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        return safe_name, digest.hexdigest(), size

    def _asset_root(self, kind: str, asset_id: str) -> Path:
        return (self.settings.data_root / "assets" / kind / asset_id).resolve()

    def _asset_work_dir(self, job_id: str) -> Path:
        return (self.settings.data_root / "asset_jobs" / job_id).resolve()

    async def create_character_asset(self, upload: UploadFile, name: str) -> tuple[Asset, bool, AssetJob | None]:
        temporary = self.settings.data_root / ".uploads" / f"{uuid.uuid4()}.glb"
        _, digest, size = await self.save_asset_upload(upload, temporary, ".glb")
        mapping_side = os.getenv("NAQI_MAPPING_SIDE", "left")
        # The prototype contract accepts only left/right.  Treat an inherited
        # legacy "auto" value as the script's default instead of poisoning the
        # typed-stage cache key or passing an invalid value downstream.
        if mapping_side == "auto":
            mapping_side = "left"
        cache_key = hashlib.sha256(
            f"rig-v1|{digest}|{mapping_side}".encode("utf-8")
        ).hexdigest()
        existing = self.asset_database.find_by_cache("character", cache_key)
        if existing is not None:
            temporary.unlink(missing_ok=True)
            existing_job = (
                self.asset_database.get_job(existing.latest_job_id)
                if existing.latest_job_id
                else None
            )
            if existing.status == "ready":
                return existing, True, None
            if existing.status in {"pending", "queued", "running"}:
                return existing, False, existing_job
            if self.asset_database.get_file(existing.id, "source_glb") is not None:
                retry = self.asset_database.create_job(
                    job_type="rig",
                    asset_id=existing.id,
                    work_dir=self._asset_work_dir(str(uuid.uuid4())),
                )
                self.worker.enqueue_asset(retry.id)
                return existing, False, retry
            self.asset_database.delete_asset(existing.id)
        asset_id = str(uuid.uuid4())
        root = self._asset_root("character", asset_id)
        try:
            asset = self.asset_database.create_asset(
                kind="character",
                name=name,
                root_dir=root,
                source_sha256=digest,
                cache_key=cache_key,
                asset_id=asset_id,
            )
            root.mkdir(parents=True, exist_ok=True)
            source = root / "source.glb"
            temporary.replace(source)
            self.asset_database.add_file(
                asset_id=asset.id,
                file_kind="source_glb",
                path=source,
                size_bytes=size,
                sha256=digest,
            )
            job = self.asset_database.create_job(
                job_type="rig",
                asset_id=asset.id,
                work_dir=self._asset_work_dir(str(uuid.uuid4())),
            )
            self.worker.enqueue_asset(job.id)
            return asset, False, job
        except Exception:
            temporary.unlink(missing_ok=True)
            shutil.rmtree(root, ignore_errors=True)
            self.asset_database.delete_asset(asset_id)
            raise

    async def create_motion_asset(
        self,
        upload: UploadFile,
        name: str,
        camera_mode: str,
    ) -> tuple[Asset, bool, AssetJob | None]:
        temporary = self.settings.data_root / ".uploads" / f"{uuid.uuid4()}.mp4"
        _, digest, size = await self.save_asset_upload(upload, temporary, ".mp4")
        cache_key = hashlib.sha256(
            f"motion-v1|{digest}|{camera_mode}".encode("utf-8")
        ).hexdigest()
        existing = self.asset_database.find_by_cache("motion", cache_key)
        if existing is not None:
            temporary.unlink(missing_ok=True)
            existing_job = (
                self.asset_database.get_job(existing.latest_job_id)
                if existing.latest_job_id
                else None
            )
            if existing.status == "ready":
                return existing, True, None
            if existing.status in {"pending", "queued", "running"}:
                return existing, False, existing_job
            if self.asset_database.get_file(existing.id, "source_mp4") is not None:
                retry = self.asset_database.create_job(
                    job_type="motion",
                    asset_id=existing.id,
                    work_dir=self._asset_work_dir(str(uuid.uuid4())),
                    params={"camera_mode": camera_mode},
                )
                self.worker.enqueue_asset(retry.id)
                return existing, False, retry
            self.asset_database.delete_asset(existing.id)
        asset_id = str(uuid.uuid4())
        root = self._asset_root("motion", asset_id)
        try:
            asset = self.asset_database.create_asset(
                kind="motion",
                name=name,
                root_dir=root,
                source_sha256=digest,
                cache_key=cache_key,
                asset_id=asset_id,
            )
            root.mkdir(parents=True, exist_ok=True)
            source = root / "source.mp4"
            temporary.replace(source)
            self.asset_database.add_file(
                asset_id=asset.id,
                file_kind="source_mp4",
                path=source,
                size_bytes=size,
                sha256=digest,
            )
            job = self.asset_database.create_job(
                job_type="motion",
                asset_id=asset.id,
                work_dir=self._asset_work_dir(str(uuid.uuid4())),
                params={"camera_mode": camera_mode},
            )
            self.worker.enqueue_asset(job.id)
            return asset, False, job
        except Exception:
            temporary.unlink(missing_ok=True)
            shutil.rmtree(root, ignore_errors=True)
            self.asset_database.delete_asset(asset_id)
            raise

    def create_animation_asset(
        self,
        character_id: str,
        motion_id: str,
        render_keyframes: bool,
    ) -> tuple[Asset, bool, AssetJob | None]:
        character = self.asset_database.get_asset(character_id)
        motion = self.asset_database.get_asset(motion_id)
        if character is None or character.kind != "character" or character.status != "ready":
            raise HTTPException(status_code=409, detail="character must be a ready asset")
        if motion is None or motion.kind != "motion" or motion.status != "ready":
            raise HTTPException(status_code=409, detail="motion must be a ready asset")
        rigged = self.asset_database.get_file(character_id, "rigged_glb")
        motion_npz = self.asset_database.get_file(motion_id, "motion_npz")
        mapping = self.asset_database.get_file(character_id, "mapping")
        if rigged is None or motion_npz is None or mapping is None:
            raise HTTPException(status_code=409, detail="ready source assets are missing required files")
        source_sha256 = hashlib.sha256(
            f"retarget-source-v1|{rigged.sha256}|{motion_npz.sha256}".encode("utf-8")
        ).hexdigest()
        cache_key = hashlib.sha256(
            f"retarget-v1|{rigged.sha256}|{motion_npz.sha256}|{int(render_keyframes)}".encode("utf-8")
        ).hexdigest()
        existing = self.asset_database.find_by_cache("animation", cache_key)
        if existing is not None:
            existing_job = (
                self.asset_database.get_job(existing.latest_job_id)
                if existing.latest_job_id
                else None
            )
            if existing.status == "ready":
                return existing, True, None
            if existing.status in {"pending", "queued", "running"}:
                return existing, False, existing_job
            retry = self.asset_database.create_job(
                job_type="retarget",
                asset_id=existing.id,
                work_dir=self._asset_work_dir(str(uuid.uuid4())),
                character_id=character_id,
                motion_id=motion_id,
                params={"render_keyframes": render_keyframes},
            )
            self.worker.enqueue_asset(retry.id)
            return existing, False, retry
        asset_id = str(uuid.uuid4())
        root = self._asset_root("animation", asset_id)
        asset = self.asset_database.create_asset(
            kind="animation",
            name=f"{character.name} + {motion.name}",
            root_dir=root,
            source_sha256=source_sha256,
            cache_key=cache_key,
            source_character_id=character_id,
            source_motion_id=motion_id,
            render_keyframes=render_keyframes,
            asset_id=asset_id,
        )
        root.mkdir(parents=True, exist_ok=True)
        job = self.asset_database.create_job(
            job_type="retarget",
            asset_id=asset.id,
            work_dir=self._asset_work_dir(str(uuid.uuid4())),
            character_id=character_id,
            motion_id=motion_id,
            params={"render_keyframes": render_keyframes},
        )
        self.worker.enqueue_asset(job.id)
        return asset, False, job

    async def create_job(
        self,
        video: UploadFile,
        character: UploadFile,
        camera_mode: str,
        mapping_side: str,
        fps: float | None,
        render_keyframes: bool,
    ) -> Job:
        job_id = str(uuid.uuid4())
        job_dir = (self.settings.runs_dir / job_id).resolve()
        input_dir = job_dir / "inputs"
        input_dir.mkdir(parents=True, exist_ok=False)
        video_path = input_dir / "video.mp4"
        character_path = input_dir / "character.glb"
        try:
            video_name, video_hash = await self.save_upload(video, video_path, ".mp4")
            character_name, character_hash = await self.save_upload(
                character, character_path, ".glb"
            )
            now = utc_now()
            job = Job(
                id=job_id,
                status="queued",
                camera_mode=camera_mode,
                mapping_side=mapping_side,
                fps=fps,
                render_keyframes=render_keyframes,
                job_dir=job_dir,
                video_path=video_path,
                character_path=character_path,
                original_video_name=video_name,
                original_character_name=character_name,
                created_at=now,
                updated_at=now,
                video_sha256=video_hash,
                character_sha256=character_hash,
            )
            self.database.create(job)
            self.worker.enqueue(job_id)
            return job
        except Exception:
            shutil.rmtree(job_dir, ignore_errors=True)
            raise


def safe_filename(filename: str, expected_suffix: str) -> str:
    basename = Path(filename.replace("\\", "/")).name
    if Path(basename).suffix.lower() != expected_suffix:
        raise HTTPException(
            status_code=415,
            detail=f"only {expected_suffix} uploads are accepted",
        )
    stem = Path(basename).stem
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._") or "upload"
    return f"{stem}{expected_suffix}"


def _auth_guard(settings: Settings, admin: bool) -> Callable[..., Any]:
    expected = settings.admin_api_key if admin else settings.api_key

    async def guard(request: Request) -> None:
        if expected is None and settings.dev_mode:
            return
        supplied = request.headers.get("authorization", "")
        scheme, _, token = supplied.partition(" ")
        if scheme.lower() != "bearer" or not token or expected is None:
            raise HTTPException(
                status_code=401,
                detail="missing or invalid bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if not hmac.compare_digest(token.encode("utf-8"), expected.encode("utf-8")):
            raise HTTPException(
                status_code=401,
                detail="missing or invalid bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    return guard


def _job_or_404(runtime: BackendRuntime, job_id: str) -> Job:
    try:
        uuid.UUID(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="job not found") from exc
    job = runtime.database.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job


def _job_response(runtime: BackendRuntime, job: Job) -> dict[str, Any]:
    return runtime.database.as_dict(job)


def _asset_response(
    runtime: BackendRuntime,
    asset: Asset,
    *,
    cache_hit: bool = False,
    job: AssetJob | None = None,
) -> dict[str, Any]:
    current = runtime.asset_database.get_asset(asset.id) or asset
    body = runtime.asset_database.asset_dict(current)
    body["cache_hit"] = cache_hit
    current_job = runtime.asset_database.get_job(job.id) if job else None
    body["job"] = runtime.asset_database.job_dict(current_job or job) if (current_job or job) else None
    return body


def _asset_job_or_404(runtime: BackendRuntime, job_id: str) -> AssetJob:
    job = runtime.asset_database.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job


def _unified_job_response(runtime: BackendRuntime, job_id: str) -> dict[str, Any]:
    old_job = runtime.database.get(job_id)
    if old_job is not None:
        return runtime.database.as_dict(old_job)
    asset_job = runtime.asset_database.get_job(job_id)
    if asset_job is not None:
        return runtime.asset_database.job_dict(asset_job)
    raise HTTPException(status_code=404, detail="job not found")


def _unified_job_list(runtime: BackendRuntime) -> list[dict[str, Any]]:
    items = [runtime.database.as_dict(job) for job in runtime.database.list_jobs()]
    items.extend(runtime.asset_database.job_dict(job) for job in runtime.asset_database.list_jobs())
    return sorted(items, key=lambda item: str(item.get("created_at", "")), reverse=True)


def _safe_asset_file(runtime: BackendRuntime, asset_id: str, file_kind: str) -> tuple[Asset, Path, str]:
    asset = runtime.asset_database.get_asset(asset_id)
    if asset is None or file_kind not in ASSET_FILE_KINDS.get(asset.kind, set()):
        raise HTTPException(status_code=404, detail="asset file not found")
    record = runtime.asset_database.get_file(asset_id, file_kind)
    if record is None:
        raise HTTPException(status_code=404, detail="asset file not found")
    root = runtime.settings.data_root.resolve()
    path = record.path.resolve()
    try:
        path.relative_to(root)
        path.relative_to(asset.root_dir.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="asset file not found") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="asset file not found")
    return asset, path, record.mime_type


def _configure_cors(app: FastAPI, settings: Settings) -> None:
    if not settings.cors_origins:
        return
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        expose_headers=["Content-Disposition"],
    )


def _artifact_root(job: Job) -> Path:
    return job.job_dir.resolve()


def _safe_artifact_file(job: Job, artifact_path: str) -> Path:
    root = _artifact_root(job)
    requested = Path(artifact_path)
    if requested.is_absolute() or ".." in requested.parts:
        raise HTTPException(status_code=404, detail="artifact not found")
    candidate = (root / requested).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="artifact not found") from exc
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="artifact not found")
    return candidate


def _list_artifacts(runtime: BackendRuntime, job: Job) -> dict[str, Any]:
    root = _artifact_root(job)
    artifacts: list[dict[str, Any]] = []
    checksums = {
        f"inputs/{job.video_path.name}": job.video_sha256,
        f"inputs/{job.character_path.name}": job.character_sha256,
    }
    if root.exists():
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            try:
                resolved = path.resolve()
                relative = resolved.relative_to(root).as_posix()
            except ValueError:
                continue
            item: dict[str, Any] = {"path": relative, "size": path.stat().st_size}
            if checksums.get(relative):
                item["sha256"] = checksums[relative]
            artifacts.append(item)
    return {
        "job_id": job.id,
        "status": job.status,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "duration_seconds": runtime.database.as_dict(job)["duration_seconds"],
        "video_sha256": job.video_sha256,
        "character_sha256": job.character_sha256,
        "artifacts": artifacts,
    }


def _attach_runtime(app: FastAPI, runtime: BackendRuntime, manage_lifecycle: bool) -> FastAPI:
    app.state.runtime = runtime
    if manage_lifecycle:
        @asynccontextmanager
        async def lifespan(_: FastAPI) -> AsyncIterator[None]:
            runtime.start()
            try:
                yield
            finally:
                runtime.stop()

        app.router.lifespan_context = lifespan
    return app


def create_public_app(
    settings: Settings | None = None,
    runner: JobRunner | None = None,
    manage_lifecycle: bool = True,
    runtime: BackendRuntime | None = None,
) -> FastAPI:
    actual_settings = settings or Settings.from_env()
    actual_settings.validate()
    backend_runtime = runtime or BackendRuntime(actual_settings, runner)
    auth = _auth_guard(actual_settings, admin=False)
    app = FastAPI(title="NAQI Job Service", version="0.1.0")
    _configure_cors(app, actual_settings)
    _attach_runtime(app, backend_runtime, manage_lifecycle)

    @app.get("/health/live")
    async def health_live_public() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/jobs", status_code=202, dependencies=[Depends(auth)])
    async def submit_job(
        video: UploadFile = File(...),
        character: UploadFile = File(...),
        camera_mode: str = Form("static"),
        mapping_side: str = Form("auto"),
        fps: float | None = Form(None),
        render_keyframes: bool = Form(False),
    ) -> JSONResponse:
        if camera_mode not in {"static", "moving"}:
            raise HTTPException(status_code=422, detail="camera_mode must be static or moving")
        if mapping_side not in {"auto", "left", "right"}:
            raise HTTPException(status_code=422, detail="mapping_side must be auto, left, or right")
        if fps is not None and not actual_settings.fps_min <= fps <= actual_settings.fps_max:
            raise HTTPException(
                status_code=422,
                detail=f"fps must be between {actual_settings.fps_min:g} and {actual_settings.fps_max:g}",
            )
        if Path(video.filename or "").suffix.lower() != ".mp4":
            raise HTTPException(status_code=415, detail="video must have an .mp4 extension")
        if Path(character.filename or "").suffix.lower() != ".glb":
            raise HTTPException(status_code=415, detail="character must have a .glb extension")
        job = await actual_runtime(app).create_job(
            video, character, camera_mode, mapping_side, fps, render_keyframes
        )
        return JSONResponse(_job_response(actual_runtime(app), job), status_code=202)

    @app.get("/v1/jobs", dependencies=[Depends(auth)])
    async def list_jobs(limit: int = 100, offset: int = 0) -> dict[str, Any]:
        if limit < 1 or limit > 500 or offset < 0:
            raise HTTPException(status_code=422, detail="limit must be 1..500 and offset non-negative")
        items = _unified_job_list(actual_runtime(app))
        return {"items": items[offset : offset + limit], "total": len(items)}

    @app.get("/v1/assets/characters", dependencies=[Depends(auth)])
    async def list_characters() -> dict[str, Any]:
        runtime = actual_runtime(app)
        items = [
            runtime.asset_database.asset_dict(asset)
            for asset in runtime.asset_database.list_assets("character")
        ]
        return {"items": items, "total": len(items)}

    @app.post("/v1/assets/characters", status_code=202, dependencies=[Depends(auth)])
    async def upload_character(
        file: UploadFile = File(...),
        name: str | None = Form(None),
    ) -> JSONResponse:
        if Path(file.filename or "").suffix.lower() != ".glb":
            raise HTTPException(status_code=415, detail="character must have an .glb extension")
        display_name = (name or "").strip() or Path(file.filename or "character.glb").stem
        asset, cache_hit, job = await actual_runtime(app).create_character_asset(
            file, display_name
        )
        body = _asset_response(actual_runtime(app), asset, cache_hit=cache_hit, job=job)
        return JSONResponse(body, status_code=200 if cache_hit else 202)

    @app.get("/v1/assets/motions", dependencies=[Depends(auth)])
    async def list_motions() -> dict[str, Any]:
        runtime = actual_runtime(app)
        items = [
            runtime.asset_database.asset_dict(asset)
            for asset in runtime.asset_database.list_assets("motion")
        ]
        return {"items": items, "total": len(items)}

    @app.post("/v1/assets/motions", status_code=202, dependencies=[Depends(auth)])
    async def upload_motion(
        file: UploadFile = File(...),
        camera_mode: str = Form("static"),
        name: str | None = Form(None),
    ) -> JSONResponse:
        if Path(file.filename or "").suffix.lower() != ".mp4":
            raise HTTPException(status_code=415, detail="motion must have an .mp4 extension")
        if camera_mode not in {"static", "moving"}:
            raise HTTPException(status_code=422, detail="camera_mode must be static or moving")
        display_name = (name or "").strip() or Path(file.filename or "motion.mp4").stem
        asset, cache_hit, job = await actual_runtime(app).create_motion_asset(
            file, display_name, camera_mode
        )
        body = _asset_response(actual_runtime(app), asset, cache_hit=cache_hit, job=job)
        return JSONResponse(body, status_code=200 if cache_hit else 202)

    @app.get("/v1/assets/animations", dependencies=[Depends(auth)])
    async def list_animations() -> dict[str, Any]:
        runtime = actual_runtime(app)
        items = [
            runtime.asset_database.asset_dict(asset)
            for asset in runtime.asset_database.list_assets("animation")
        ]
        return {"items": items, "total": len(items)}

    @app.post("/v1/animations", status_code=202, dependencies=[Depends(auth)])
    async def create_animation(payload: dict[str, Any] = Body(...)) -> JSONResponse:
        character_id = payload.get("character_id")
        motion_id = payload.get("motion_id")
        render_keyframes = payload.get("render_keyframes", False)
        if not isinstance(character_id, str) or not isinstance(motion_id, str):
            raise HTTPException(status_code=422, detail="character_id and motion_id are required")
        if not isinstance(render_keyframes, bool):
            raise HTTPException(status_code=422, detail="render_keyframes must be a boolean")
        asset, cache_hit, job = actual_runtime(app).create_animation_asset(
            character_id, motion_id, render_keyframes
        )
        body = _asset_response(actual_runtime(app), asset, cache_hit=cache_hit, job=job)
        return JSONResponse(body, status_code=200 if cache_hit else 202)

    @app.get(
        "/v1/assets/{kind}/{asset_id}/files/{file_kind}",
        dependencies=[Depends(auth)],
    )
    async def download_asset_file(
        kind: str,
        asset_id: str,
        file_kind: str,
        download: bool = False,
    ) -> FileResponse:
        runtime = actual_runtime(app)
        asset, path, mime_type = _safe_asset_file(runtime, asset_id, file_kind)
        normalized_kind = {
            "character": "character",
            "characters": "character",
            "motion": "motion",
            "motions": "motion",
            "animation": "animation",
            "animations": "animation",
        }.get(kind)
        if normalized_kind is None or asset.kind != normalized_kind:
            raise HTTPException(status_code=404, detail="asset file not found")
        return FileResponse(
            path,
            media_type=mime_type,
            filename=path.name,
            content_disposition_type="attachment" if download else "inline",
        )

    @app.get("/v1/jobs/{job_id}", dependencies=[Depends(auth)])
    async def get_job(job_id: str) -> dict[str, Any]:
        return _unified_job_response(actual_runtime(app), job_id)

    @app.get("/v1/jobs/{job_id}/artifacts", dependencies=[Depends(auth)])
    async def get_artifacts(job_id: str) -> dict[str, Any]:
        runtime = actual_runtime(app)
        return _list_artifacts(runtime, _job_or_404(runtime, job_id))

    @app.get("/v1/jobs/{job_id}/artifacts/{artifact_path:path}", dependencies=[Depends(auth)])
    async def download_artifact(
        job_id: str,
        artifact_path: str,
        download: bool = False,
    ) -> FileResponse:
        runtime = actual_runtime(app)
        job = _job_or_404(runtime, job_id)
        path = _safe_artifact_file(job, artifact_path)
        return FileResponse(
            path,
            media_type=_artifact_media_type(path),
            filename=path.name,
            content_disposition_type="attachment" if download else "inline",
        )

    @app.post("/v1/jobs/{job_id}/cancel", dependencies=[Depends(auth)])
    async def cancel_job(job_id: str) -> dict[str, Any]:
        runtime = actual_runtime(app)
        old_job = runtime.database.get(job_id)
        if old_job is not None:
            if old_job.status in {"succeeded", "failed", "cancelled"}:
                return _job_response(runtime, old_job)
            runtime.worker.cancel(job_id)
            updated = runtime.database.get(job_id)
            return _job_response(runtime, updated or old_job)
        asset_job = _asset_job_or_404(runtime, job_id)
        if asset_job.status in {"ready", "failed", "cancelled"}:
            return runtime.asset_database.job_dict(asset_job)
        runtime.worker.cancel_asset(job_id)
        updated_asset_job = runtime.asset_database.get_job(job_id)
        return runtime.asset_database.job_dict(updated_asset_job or asset_job)

    return app


def create_admin_app(
    settings: Settings | None = None,
    runtime: BackendRuntime | None = None,
    manage_lifecycle: bool = True,
) -> FastAPI:
    actual_settings = settings or Settings.from_env()
    actual_settings.validate()
    backend_runtime = runtime or BackendRuntime(actual_settings)
    auth = _auth_guard(actual_settings, admin=True)
    app = FastAPI(title="NAQI Admin API", version="0.1.0")
    _attach_runtime(app, backend_runtime, manage_lifecycle)

    @app.get("/health/live", dependencies=[Depends(auth)])
    async def health_live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", dependencies=[Depends(auth)])
    async def health_ready() -> JSONResponse:
        runtime = actual_runtime(app)
        pipeline = actual_settings.pipeline_script
        checks = {
            "database": False,
            "asset_database": False,
            "runs_dir": actual_settings.runs_dir.is_dir() and _is_writable(actual_settings.runs_dir),
            "pipeline_script": pipeline is not None
            and pipeline.is_file()
            and _is_readable(pipeline),
        }
        stage_checks = actual_settings.stage_checks()
        checks.update(stage_checks)
        try:
            checks["database"] = runtime.database.check()
            checks["asset_database"] = runtime.asset_database.check()
        except Exception:  # noqa: BLE001 - health endpoint reports not ready
            checks["database"] = False
            checks["asset_database"] = False
        checks["execution_backend"] = checks["pipeline_script"] or all(stage_checks.values())
        checks["legacy_execution_backend"] = checks["pipeline_script"]
        checks["asset_execution_backend"] = all(stage_checks.values())
        ready = (
            checks["database"]
            and checks["asset_database"]
            and checks["runs_dir"]
            and checks["execution_backend"]
        )
        return JSONResponse(
            {"status": "ready" if ready else "not_ready", "checks": checks},
            status_code=200 if ready else 503,
        )

    @app.get("/v1/admin/status", dependencies=[Depends(auth)])
    async def admin_status() -> dict[str, Any]:
        runtime = actual_runtime(app)
        queued = len(runtime.database.queued_ids())
        queued_assets = len(runtime.asset_database.queued_job_ids())
        return {
            "worker_count": actual_settings.worker_count,
            "queued_jobs": queued,
            "queued_asset_jobs": queued_assets,
            "runs_dir": str(actual_settings.runs_dir),
            "database_path": str(actual_settings.database_path),
            "pipeline_script": str(actual_settings.pipeline_script),
            "pipeline_tools_configured": actual_settings.pipeline_tools_dir is not None,
        }

    return app


def actual_runtime(app: FastAPI) -> BackendRuntime:
    return app.state.runtime


def _is_writable(path: Path) -> bool:
    try:
        probe = path / ".naqi-write-check"
        probe.touch(exist_ok=False)
        probe.unlink()
        return True
    except OSError:
        return False


def _is_readable(path: Path) -> bool:
    try:
        with path.open("rb"):
            return True
    except OSError:
        return False


def _artifact_media_type(path: Path) -> str:
    return {
        ".glb": "model/gltf-binary",
        ".npz": "application/octet-stream",
        ".mp4": "video/mp4",
    }.get(path.suffix.lower(), "application/octet-stream")


def build_app_pair(
    settings: Settings | None = None,
    runner: JobRunner | None = None,
) -> tuple[FastAPI, FastAPI, BackendRuntime]:
    actual_settings = settings or Settings.from_env()
    actual_settings.validate()
    runtime = BackendRuntime(actual_settings, runner)
    public = create_public_app(
        actual_settings,
        runtime.runner,
        manage_lifecycle=False,
        runtime=runtime,
    )
    admin = create_admin_app(actual_settings, runtime, manage_lifecycle=False)
    public.state.runtime = runtime
    return public, admin, runtime
