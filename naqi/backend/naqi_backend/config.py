from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path


class ConfigurationError(RuntimeError):
    """Raised when backend configuration is unsafe or invalid."""


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    api_key: str | None
    admin_api_key: str | None
    dev_mode: bool
    public_host: str
    public_port: int
    admin_host: str
    admin_port: int
    data_root: Path
    runs_dir: Path
    database_path: Path
    pipeline_script: Path | None
    max_upload_bytes: int
    fps_min: float
    fps_max: float
    worker_count: int
    bash_binary: str
    pipeline_tools_dir: Path | None = None
    skintokens_home: Path | None = None
    gvhmr_home: Path | None = None
    blender_bin: str = "blender"
    cors_origins: tuple[str, ...] = ()

    @classmethod
    def from_env(cls, backend_dir: Path | None = None) -> "Settings":
        backend_root = (backend_dir or Path(__file__).resolve().parents[1]).resolve()
        data_root = Path(
            os.getenv("NAQI_DATA_ROOT", str(backend_root / "data"))
        ).expanduser().resolve()
        runs_dir = Path(os.getenv("NAQI_RUNS_DIR", str(data_root / "runs"))).expanduser().resolve()
        database_path = Path(
            os.getenv("NAQI_DATABASE_PATH", str(data_root / "naqi.sqlite3"))
        ).expanduser().resolve()
        pipeline_value = os.getenv("NAQI_PIPELINE_SCRIPT")
        pipeline = Path(pipeline_value).expanduser().resolve() if pipeline_value else None
        tools_value = os.getenv("NAQI_PIPELINE_TOOLS_DIR")
        pipeline_tools = Path(tools_value).expanduser().resolve() if tools_value else None
        skintokens_value = os.getenv("SKINTOKENS_HOME")
        skintokens_home = (
            Path(skintokens_value).expanduser().resolve() if skintokens_value else None
        )
        gvhmr_value = os.getenv("GVHMR_HOME")
        gvhmr_home = Path(gvhmr_value).expanduser().resolve() if gvhmr_value else None
        cors_origins = tuple(
            origin.strip()
            for origin in os.getenv("NAQI_CORS_ORIGINS", "").split(",")
            if origin.strip()
        )
        return cls(
            api_key=os.getenv("NAQI_API_KEY") or None,
            admin_api_key=os.getenv("NAQI_ADMIN_API_KEY") or None,
            dev_mode=_env_bool("NAQI_DEV_MODE"),
            public_host=os.getenv("NAQI_PUBLIC_HOST", "0.0.0.0"),
            public_port=int(os.getenv("NAQI_PUBLIC_PORT", "18080")),
            admin_host=os.getenv("NAQI_ADMIN_HOST", "127.0.0.1"),
            admin_port=int(os.getenv("NAQI_ADMIN_PORT", "18081")),
            data_root=data_root,
            runs_dir=runs_dir,
            database_path=database_path,
            pipeline_script=pipeline,
            max_upload_bytes=int(os.getenv("NAQI_MAX_UPLOAD_BYTES", str(2 * 1024**3))),
            fps_min=float(os.getenv("NAQI_FPS_MIN", "1")),
            fps_max=float(os.getenv("NAQI_FPS_MAX", "120")),
            worker_count=int(os.getenv("NAQI_WORKERS", "1")),
            bash_binary=os.getenv("NAQI_BASH_BINARY", "bash"),
            pipeline_tools_dir=pipeline_tools,
            skintokens_home=skintokens_home,
            gvhmr_home=gvhmr_home,
            blender_bin=os.getenv("BLENDER_BIN", "blender"),
            cors_origins=cors_origins,
        )

    def validate(self) -> None:
        if not self.dev_mode and (not self.api_key or not self.admin_api_key):
            raise ConfigurationError(
                "NAQI_API_KEY and NAQI_ADMIN_API_KEY are required; "
                "set NAQI_DEV_MODE=1 only for an explicitly local development run"
            )
        if self.public_port < 1 or self.public_port > 65535:
            raise ConfigurationError("public port is outside 1..65535")
        if self.admin_port < 1 or self.admin_port > 65535:
            raise ConfigurationError("admin port is outside 1..65535")
        if self.max_upload_bytes <= 0:
            raise ConfigurationError("NAQI_MAX_UPLOAD_BYTES must be positive")
        if self.fps_min <= 0 or self.fps_max < self.fps_min:
            raise ConfigurationError("invalid FPS bounds")
        if self.worker_count != 1:
            raise ConfigurationError("only one GPU worker is supported")
        if "*" in self.cors_origins:
            raise ConfigurationError("NAQI_CORS_ORIGINS must not contain '*' when credentials are enabled")

    def stage_checks(self) -> dict[str, bool]:
        """Return non-sensitive readiness checks for typed stage execution."""
        tools = self.pipeline_tools_dir
        required_tools = (
            "run_skintokens_offline.py",
            "inspect_skin_tokens_topology.py",
            "build_topology_mapping.py",
            "extract_gvhmr_motion.py",
            "apply_gvhmr_motion.py",
            "inspect_glb_animation.py",
            "render_glb_keyframes.py",
        )
        tools_ready = tools is not None and tools.is_dir() and all(
            (tools / name).is_file() for name in required_tools
        )
        skintokens_ready = (
            self.skintokens_home is not None
            and self.skintokens_home.is_dir()
            and (self.skintokens_home / ".venv" / "bin" / "python").is_file()
        )
        gvhmr_ready = (
            self.gvhmr_home is not None
            and self.gvhmr_home.is_dir()
            and (self.gvhmr_home / ".venv310" / "bin" / "python").is_file()
            and (self.gvhmr_home / "tools" / "demo" / "demo.py").is_file()
        )
        blender_path = Path(self.blender_bin).expanduser()
        blender_ready = (
            blender_path.is_file() if blender_path.parent != Path(".") else shutil.which(self.blender_bin) is not None
        )
        return {
            "pipeline_tools_dir": tools_ready,
            "skintokens_home": skintokens_ready,
            "gvhmr_home": gvhmr_ready,
            "blender_bin": blender_ready,
        }
