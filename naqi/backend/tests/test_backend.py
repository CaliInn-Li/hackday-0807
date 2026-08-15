from __future__ import annotations

import hashlib
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from naqi_backend.api import BackendRuntime, create_admin_app, create_public_app
from naqi_backend.assets import ASSET_MIME_TYPES, AssetDatabase
from naqi_backend.config import Settings
from naqi_backend.db import Job, JobDatabase, utc_now


class FakeRunner:
    def __init__(self, exit_code: int = 0, wait_for_cancel: bool = False) -> None:
        self.exit_code = exit_code
        self.wait_for_cancel = wait_for_cancel
        self.started = threading.Event()
        self.cancelled = threading.Event()
        self.calls: list[Job] = []

    def run(self, job: Job, cancel_event: threading.Event) -> int:
        self.calls.append(job)
        self.started.set()
        (job.job_dir / "outputs").mkdir(exist_ok=True)
        (job.job_dir / "outputs" / "result.glb").write_bytes(b"result")
        if self.wait_for_cancel:
            while not cancel_event.wait(0.02):
                pass
            return -15
        return self.exit_code

    def cancel(self, job_id: str) -> None:
        del job_id
        self.cancelled.set()


class FakeStageRunner:
    def __init__(self, exit_code: int = 0, wait_for_cancel: bool = False) -> None:
        self.exit_code = exit_code
        self.wait_for_cancel = wait_for_cancel
        self.started = threading.Event()
        self.cancelled = threading.Event()

    def run(self, job, database: AssetDatabase, cancel_event: threading.Event) -> int:
        self.started.set()
        if self.wait_for_cancel:
            while not cancel_event.wait(0.02):
                pass
            return -15
        if self.exit_code != 0:
            return self.exit_code
        asset = database.get_asset(job.asset_id)
        assert asset is not None
        outputs = {
            "rig": {
                "rigged_glb": ("rigged.glb", b"rigged"),
                "topology_report": ("topology.json", b"{}"),
                "mapping": ("mapping.json", b"{}"),
            },
            "motion": {
                "motion_npz": ("motion.npz", b"npz"),
                "manifest": ("manifest.json", b"{}"),
            },
            "retarget": {
                "animated_glb": ("animated.glb", b"animated"),
                "retarget_report": ("retarget.json", b"{}"),
                "qa_report": ("qa.json", b"{}"),
            },
        }[job.job_type]
        for file_kind, (filename, content) in outputs.items():
            path = asset.root_dir / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            database.add_file(
                asset_id=asset.id,
                file_kind=file_kind,
                path=path,
                size_bytes=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
                mime_type=ASSET_MIME_TYPES[file_kind],
            )
        return 0

    def cancel(self, job_id: str) -> None:
        del job_id
        self.cancelled.set()


def settings(tmp_path: Path, max_upload_bytes: int = 100) -> Settings:
    tmp_path.mkdir(parents=True, exist_ok=True)
    pipeline = tmp_path / "run_naqi_pipeline.sh"
    pipeline.write_text("#!/bin/sh\n", encoding="utf-8")
    tools = tmp_path / "pipeline-tools"
    tools.mkdir()
    for tool_name in (
        "run_skintokens_offline.py",
        "inspect_skin_tokens_topology.py",
        "build_topology_mapping.py",
        "extract_gvhmr_motion.py",
        "apply_gvhmr_motion.py",
        "inspect_glb_animation.py",
        "render_glb_keyframes.py",
    ):
        (tools / tool_name).write_text("# fake tool\n", encoding="utf-8")
    skintokens_home = tmp_path / "SkinTokens"
    (skintokens_home / ".venv" / "bin").mkdir(parents=True)
    (skintokens_home / ".venv" / "bin" / "python").write_text("fake python\n", encoding="utf-8")
    gvhmr_home = tmp_path / "GVHMR"
    (gvhmr_home / ".venv310" / "bin").mkdir(parents=True)
    (gvhmr_home / ".venv310" / "bin" / "python").write_text("fake python\n", encoding="utf-8")
    (gvhmr_home / "tools" / "demo").mkdir(parents=True)
    (gvhmr_home / "tools" / "demo" / "demo.py").write_text("# fake demo\n", encoding="utf-8")
    blender = tmp_path / "blender"
    blender.write_text("fake blender\n", encoding="utf-8")
    return Settings(
        api_key="public-secret",
        admin_api_key="admin-secret",
        dev_mode=False,
        public_host="127.0.0.1",
        public_port=18080,
        admin_host="127.0.0.1",
        admin_port=18081,
        data_root=tmp_path / "data",
        runs_dir=tmp_path / "runs",
        database_path=tmp_path / "jobs.sqlite3",
        pipeline_script=pipeline,
        max_upload_bytes=max_upload_bytes,
        fps_min=1,
        fps_max=120,
        worker_count=1,
        bash_binary="bash",
        pipeline_tools_dir=tools,
        skintokens_home=skintokens_home,
        gvhmr_home=gvhmr_home,
        blender_bin=str(blender),
    )


def auth(key: str = "public-secret") -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


def submit(client: TestClient, **data: object):
    form = {key: str(value).lower() if isinstance(value, bool) else str(value) for key, value in data.items()}
    return client.post(
        "/v1/jobs",
        headers=auth(),
        data=form,
        files={
            "video": ("clip.mp4", b"video-data", "video/mp4"),
            "character": ("../unsafe character.glb", b"glb-data", "model/gltf-binary"),
        },
    )


def wait_for_status(client: TestClient, job_id: str, expected: str) -> dict:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        response = client.get(f"/v1/jobs/{job_id}", headers=auth())
        body = response.json()
        if body["status"] == expected:
            return body
        time.sleep(0.02)
    pytest.fail(f"job did not reach {expected}: {body}")


def test_authentication_and_dev_mode(tmp_path: Path) -> None:
    runner = FakeRunner()
    with TestClient(create_public_app(settings(tmp_path), runner)) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/v1/jobs/nope").status_code == 401
        assert client.get("/v1/jobs/nope", headers=auth("wrong")).status_code == 401
    dev = settings(tmp_path / "dev")
    dev = Settings(**{**dev.__dict__, "api_key": None, "admin_api_key": None, "dev_mode": True})
    with TestClient(create_public_app(dev, FakeRunner())) as client:
        assert client.get("/v1/jobs/nope").status_code == 404


def test_upload_validation_limit_and_hashes(tmp_path: Path) -> None:
    with TestClient(create_public_app(settings(tmp_path, max_upload_bytes=5), FakeRunner())) as client:
        too_large = client.post(
            "/v1/jobs",
            headers=auth(),
            files={
                "video": ("clip.mp4", b"123456", "video/mp4"),
                "character": ("character.glb", b"g", "model/gltf-binary"),
            },
        )
        assert too_large.status_code == 413
        bad = client.post(
            "/v1/jobs",
            headers=auth(),
            files={
                "video": ("clip.mov", b"1", "video/quicktime"),
                "character": ("character.glb", b"1", "model/gltf-binary"),
            },
        )
        assert bad.status_code == 415

    runner = FakeRunner()
    with TestClient(create_public_app(settings(tmp_path / "hashes"), runner)) as client:
        response = submit(client, fps=24, render_keyframes=False)
        assert response.status_code == 202
        body = response.json()
        assert body["video_sha256"] == hashlib.sha256(b"video-data").hexdigest()
        assert body["character_sha256"] == hashlib.sha256(b"glb-data").hexdigest()
        assert body["started_at"] is None
        assert body["finished_at"] is None
        result = wait_for_status(client, body["id"], "succeeded")
        assert result["duration_seconds"] is not None
        artifacts = client.get(f"/v1/jobs/{body['id']}/artifacts", headers=auth()).json()
        assert artifacts["video_sha256"] == body["video_sha256"]
        assert any(item.get("sha256") == body["character_sha256"] for item in artifacts["artifacts"])


def test_queue_success_and_failure(tmp_path: Path) -> None:
    first = FakeRunner(wait_for_cancel=True)
    with TestClient(create_public_app(settings(tmp_path), first)) as client:
        one = submit(client).json()
        assert first.started.wait(2)
        two = submit(client).json()
        assert client.get(f"/v1/jobs/{two['id']}", headers=auth()).json()["status"] == "queued"
        cancel = client.post(f"/v1/jobs/{one['id']}/cancel", headers=auth())
        assert cancel.json()["status"] == "cancelled"

    failing = FakeRunner(exit_code=7)
    with TestClient(create_public_app(settings(tmp_path / "failure"), failing)) as client:
        body = submit(client).json()
        failed = wait_for_status(client, body["id"], "failed")
        assert "exited with code 7" in failed["error"]
        assert failed["started_at"] is not None
        assert failed["finished_at"] is not None


def test_cancel_running_and_artifact_path_traversal(tmp_path: Path) -> None:
    runner = FakeRunner(wait_for_cancel=True)
    with TestClient(create_public_app(settings(tmp_path), runner)) as client:
        body = submit(client).json()
        assert runner.started.wait(2)
        cancelled = client.post(f"/v1/jobs/{body['id']}/cancel", headers=auth())
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"
        assert runner.cancelled.is_set()
        assert client.get(
            f"/v1/jobs/{body['id']}/artifacts/%2e%2e/%2e%2e/jobs.sqlite3", headers=auth()
        ).status_code == 404


def test_artifact_download_mime_and_disposition(tmp_path: Path) -> None:
    runner = FakeRunner()
    with TestClient(create_public_app(settings(tmp_path), runner)) as client:
        body = submit(client).json()
        wait_for_status(client, body["id"], "succeeded")
        job_dir = tmp_path / "runs" / body["id"]
        (job_dir / "outputs" / "motion.npz").write_bytes(b"npz")
        (job_dir / "outputs" / "clip.mp4").write_bytes(b"mp4")
        glb = client.get(
            f"/v1/jobs/{body['id']}/artifacts/outputs/result.glb", headers=auth()
        )
        assert glb.status_code == 200
        assert glb.headers["content-type"].startswith("model/gltf-binary")
        assert glb.headers["content-disposition"].startswith("inline;")
        npz = client.get(
            f"/v1/jobs/{body['id']}/artifacts/outputs/motion.npz?download=true", headers=auth()
        )
        assert npz.headers["content-type"].startswith("application/octet-stream")
        assert npz.headers["content-disposition"].startswith("attachment;")
        mp4 = client.get(
            f"/v1/jobs/{body['id']}/artifacts/outputs/clip.mp4", headers=auth()
        )
        assert mp4.headers["content-type"].startswith("video/mp4")


def test_asset_upload_cache_composition_and_download(tmp_path: Path) -> None:
    config = settings(tmp_path)
    runtime = BackendRuntime(config, FakeRunner(), FakeStageRunner())
    with TestClient(create_public_app(config, runtime=runtime)) as client:
        character = client.post(
            "/v1/assets/characters",
            headers=auth(),
            files={"file": ("character.glb", b"character", "model/gltf-binary")},
        )
        assert character.status_code == 202
        character_body = character.json()
        assert character_body["cache_hit"] is False
        assert character_body["name"] == "character"
        character_job = character_body["job"]["id"]
        wait_for_status(client, character_job, "ready")
        character_id = character_body["id"]
        source = client.get(
            f"/v1/assets/characters/{character_id}/files/source_glb", headers=auth()
        )
        assert source.status_code == 200
        assert source.headers["content-type"].startswith("model/gltf-binary")
        assert source.headers["content-disposition"].startswith("inline;")

        cached_character = client.post(
            "/v1/assets/characters",
            headers=auth(),
            data={"name": "Same Source"},
            files={"file": ("other.glb", b"character", "model/gltf-binary")},
        )
        assert cached_character.status_code == 200
        assert cached_character.json()["cache_hit"] is True
        assert cached_character.json()["id"] == character_id

        motion = client.post(
            "/v1/assets/motions",
            headers=auth(),
            data={"camera_mode": "static"},
            files={"file": ("motion.mp4", b"motion", "video/mp4")},
        )
        assert motion.status_code == 202
        motion_body = motion.json()
        assert motion_body["name"] == "motion"
        wait_for_status(client, motion_body["job"]["id"], "ready")
        listed_motion = client.get("/v1/assets/motions", headers=auth()).json()["items"][0]
        assert listed_motion["camera_mode"] == "static"
        assert listed_motion["files"][0]["filename"]

        animation = client.post(
            "/v1/animations",
            headers=auth(),
            json={
                "character_id": character_id,
                "motion_id": motion_body["id"],
                "render_keyframes": False,
            },
        )
        assert animation.status_code == 202
        animation_body = animation.json()
        wait_for_status(client, animation_body["job"]["id"], "ready")
        animated = client.get(
            f"/v1/assets/animations/{animation_body['id']}/files/animated_glb?download=true",
            headers=auth(),
        )
        assert animated.status_code == 200
        assert animated.headers["content-type"].startswith("model/gltf-binary")
        assert animated.headers["content-disposition"].startswith("attachment;")
        assert client.get(
            f"/v1/assets/animations/{animation_body['id']}/files/motion_npz",
            headers=auth(),
        ).status_code == 404

        cached_animation = client.post(
            "/v1/animations",
            headers=auth(),
            json={
                "character_id": character_id,
                "motion_id": motion_body["id"],
                "render_keyframes": False,
            },
        )
        assert cached_animation.status_code == 200
        assert cached_animation.json()["cache_hit"] is True
        jobs = client.get("/v1/jobs", headers=auth()).json()
        assert jobs["total"] >= 3
        assert any(item["job_family"] == "asset" for item in jobs["items"])


def test_asset_failure_cancel_and_cors(tmp_path: Path) -> None:
    config = settings(tmp_path)
    config = Settings(**{**config.__dict__, "cors_origins": ("http://localhost:3000",)})
    stage = FakeStageRunner(wait_for_cancel=True)
    runtime = BackendRuntime(config, FakeRunner(), stage)
    with TestClient(create_public_app(config, runtime=runtime)) as client:
        preflight = client.options(
            "/v1/assets/characters",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
        assert preflight.status_code == 200
        assert preflight.headers["access-control-allow-origin"] == "http://localhost:3000"
        blocked = client.options(
            "/v1/assets/characters",
            headers={
                "Origin": "http://evil.example",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert "access-control-allow-origin" not in blocked.headers
        response = client.post(
            "/v1/assets/characters",
            headers=auth(),
            data={"name": "Cancel"},
            files={"file": ("cancel.glb", b"cancel", "model/gltf-binary")},
        )
        job_id = response.json()["job"]["id"]
        assert stage.started.wait(2)
        cancelled = client.post(f"/v1/jobs/{job_id}/cancel", headers=auth())
        assert cancelled.json()["status"] == "cancelled"
        assert stage.cancelled.is_set()

    failing_config = settings(tmp_path / "failure")
    failing = BackendRuntime(failing_config, FakeRunner(), FakeStageRunner(exit_code=7))
    with TestClient(create_public_app(failing_config, runtime=failing)) as client:
        response = client.post(
            "/v1/assets/characters",
            headers=auth(),
            data={"name": "Fail"},
            files={"file": ("fail.glb", b"fail", "model/gltf-binary")},
        )
        failed = wait_for_status(client, response.json()["job"]["id"], "failed")
        assert failed["error"].startswith("stage exited with code 7")
        retried = client.post(
            "/v1/assets/characters",
            headers=auth(),
            files={"file": ("fail.glb", b"fail", "model/gltf-binary")},
        )
        assert retried.status_code == 202
        assert retried.json()["id"] == response.json()["id"]
        assert retried.json()["job"]["id"] != response.json()["job"]["id"]


def test_restart_recovery_and_health(tmp_path: Path) -> None:
    config = settings(tmp_path)
    config.runs_dir.mkdir()
    db = JobDatabase(config.database_path)
    db.initialize()
    job_dir = config.runs_dir / "00000000-0000-0000-0000-000000000001"
    job_dir.mkdir()
    now = utc_now()
    db.create(
        Job(
            id=job_dir.name,
            status="running",
            camera_mode="static",
            mapping_side="auto",
            fps=None,
            render_keyframes=False,
            job_dir=job_dir,
            video_path=job_dir / "video.mp4",
            character_path=job_dir / "character.glb",
            original_video_name="video.mp4",
            original_character_name="character.glb",
            created_at=now,
            updated_at=now,
            started_at=now,
        )
    )
    runtime = BackendRuntime(config, FakeRunner())
    runtime.start()
    recovered = runtime.database.get(job_dir.name)
    assert recovered is not None
    assert recovered.status == "failed"
    assert recovered.finished_at is not None
    runtime.stop()

    with TestClient(create_admin_app(config)) as client:
        assert client.get("/health/live", headers=auth("admin-secret")).json() == {"status": "ok"}
        ready = client.get("/health/ready", headers=auth("admin-secret"))
        assert ready.status_code == 200
        checks = ready.json()["checks"]
        assert checks["database"] is True
        assert checks["asset_database"] is True
        assert checks["runs_dir"] is True
        assert checks["pipeline_script"] is True
        assert checks["pipeline_tools_dir"] is True
        assert checks["skintokens_home"] is True
        assert checks["gvhmr_home"] is True
        assert checks["blender_bin"] is True
        assert checks["execution_backend"] is True

    missing_pipeline = Settings(**{**config.__dict__, "pipeline_script": None})
    with TestClient(create_admin_app(missing_pipeline)) as client:
        ready = client.get("/health/ready", headers=auth("admin-secret"))
        assert ready.status_code == 200
        assert ready.json()["checks"]["pipeline_script"] is False
        assert ready.json()["checks"]["execution_backend"] is True

    missing_all_execution = Settings(
        **{
            **config.__dict__,
            "pipeline_script": None,
            "pipeline_tools_dir": None,
            "skintokens_home": None,
            "gvhmr_home": None,
            "blender_bin": "missing-blender-for-test",
        }
    )
    with TestClient(create_admin_app(missing_all_execution)) as client:
        ready = client.get("/health/ready", headers=auth("admin-secret"))
        assert ready.status_code == 503
        assert ready.json()["checks"]["execution_backend"] is False
