from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from fractions import Fraction
from pathlib import Path
from typing import Mapping, Sequence


class StageAdapterError(RuntimeError):
    """Raised when an external stage dependency or output is unavailable."""


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise StageAdapterError(f"{name} is not configured")
    return value


def _tools_dir() -> Path:
    path = Path(_required_env("NAQI_PIPELINE_TOOLS_DIR")).expanduser().resolve()
    if not path.is_dir():
        raise StageAdapterError(f"NAQI_PIPELINE_TOOLS_DIR is not a directory: {path}")
    return path


def _tool(name: str) -> Path:
    path = _tools_dir() / name
    if not path.is_file():
        raise StageAdapterError(f"pipeline tool is missing: {path}")
    return path


def _home_python(home_name: str, relative: str) -> Path:
    home = Path(_required_env(home_name)).expanduser().resolve()
    path = home / relative
    if not path.is_file():
        raise StageAdapterError(f"Python runtime is missing: {path}")
    return path


def _blender() -> str:
    value = os.getenv("BLENDER_BIN", "blender")
    if "/" in value or "\\" in value:
        if not Path(value).expanduser().is_file():
            raise StageAdapterError(f"BLENDER_BIN is not a file: {value}")
    elif shutil.which(value) is None:
        raise StageAdapterError(f"BLENDER_BIN is not available: {value}")
    return value


def _gvhmr_env(home: Path) -> dict[str, str]:
    """Match the environment used by the prototype GVHMR shell contract."""
    env = os.environ.copy()
    current_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(home)
        if not current_pythonpath
        else str(home) + os.pathsep + current_pythonpath
    )
    env["TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD"] = "1"
    return env


def _env_enabled(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _run(
    argv: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> None:
    subprocess.run(
        list(argv),
        cwd=str(cwd) if cwd else None,
        env=dict(env) if env is not None else os.environ.copy(),
        shell=False,
        check=True,
    )


def _run_capture(
    argv: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    try:
        completed = subprocess.run(
            list(argv),
            cwd=str(cwd) if cwd else None,
            env=dict(env) if env is not None else os.environ.copy(),
            shell=False,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        if isinstance(exc.stdout, str) and exc.stdout:
            print(exc.stdout, end="", file=sys.stderr)
        raise
    return completed.stdout


def _ensure(path: Path, label: str) -> Path:
    if not path.is_file():
        raise StageAdapterError(f"stage did not produce {label}: {path}")
    return path


def _detect_fps(source: Path) -> str:
    """Honor an explicit override, otherwise preserve the uploaded video's rate."""
    configured = os.getenv("NAQI_FPS", "").strip()
    if configured:
        return configured
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        return "24"
    try:
        value = _run_capture(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=avg_frame_rate",
                "-of",
                "default=nw=1:nk=1",
                str(source.resolve()),
            ]
        ).strip()
        rate = float(Fraction(value))
        if rate > 0:
            return f"{rate:.8f}".rstrip("0").rstrip(".")
    except (OSError, ValueError, ZeroDivisionError, subprocess.CalledProcessError):
        pass
    return "24"


def run_rig(source: Path, output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    skin_python = _home_python("SKINTOKENS_HOME", ".venv/bin/python")
    gvhmr_python = _home_python("GVHMR_HOME", ".venv310/bin/python")
    rigged = output_dir / "rigged.glb"
    topology = output_dir / "topology.json"
    mapping = output_dir / "mapping.json"
    _run(
        [
            str(skin_python),
            str(_tool("run_skintokens_offline.py")),
            "--skintokens-home",
            _required_env("SKINTOKENS_HOME"),
            "--input",
            str(source.resolve()),
            "--output",
            str(rigged),
            "--server-timeout",
            os.getenv("NAQI_SKINTOKENS_SERVER_TIMEOUT", "600"),
            "--use-transfer",
        ],
        cwd=Path(_required_env("SKINTOKENS_HOME")).expanduser().resolve(),
    )
    _run(
        [
            str(gvhmr_python),
            str(_tool("inspect_skin_tokens_topology.py")),
            "--input",
            str(_ensure(rigged, "rigged GLB")),
            "--output",
            str(topology),
        ]
    )
    side = os.getenv("NAQI_MAPPING_SIDE", "left")
    if side not in {"left", "right"}:
        raise StageAdapterError("NAQI_MAPPING_SIDE must be left or right")
    side_flag = "--x-positive-is-right" if side == "right" else "--x-positive-is-left"
    _run(
        [
            str(gvhmr_python),
            str(_tool("build_topology_mapping.py")),
            "--topology-report",
            str(_ensure(topology, "topology report")),
            "--output",
            str(mapping),
            side_flag,
        ]
    )
    return {
        "rigged_glb": _ensure(rigged, "rigged GLB"),
        "topology_report": _ensure(topology, "topology report"),
        "mapping": _ensure(mapping, "mapping report"),
    }


def run_motion(source: Path, output_dir: Path, work_dir: Path, camera_mode: str) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    gvhmr_home = Path(_required_env("GVHMR_HOME")).expanduser().resolve()
    gvhmr_python = _home_python("GVHMR_HOME", ".venv310/bin/python")
    gvhmr_env = _gvhmr_env(gvhmr_home)
    official_demo = gvhmr_home / "tools" / "demo" / "demo.py"
    if not official_demo.is_file():
        raise StageAdapterError(f"GVHMR demo is missing: {official_demo}")
    demo = (
        official_demo
        if _env_enabled("NAQI_GVHMR_RENDER_PREVIEW")
        else Path(__file__).with_name("gvhmr_infer_only.py")
    )
    gvhmr_root = work_dir / "gvhmr"
    argv = [
        str(gvhmr_python),
        str(demo),
        "--video",
        str(source.resolve()),
        "--output_root",
        str(gvhmr_root),
    ]
    if camera_mode == "static":
        argv.append("--static_cam")
    demo_result = subprocess.run(
        argv,
        cwd=str(gvhmr_home),
        env=gvhmr_env,
        shell=False,
        check=False,
    )
    results = sorted(gvhmr_root.rglob("hmr4d_results.pt")) if gvhmr_root.exists() else []
    if not results:
        raise StageAdapterError(
            "GVHMR did not produce hmr4d_results.pt under "
            f"{gvhmr_root} (exit {demo_result.returncode})"
        )
    motion = output_dir / "motion.npz"
    manifest = output_dir / "manifest.json"
    _run(
        [
            str(gvhmr_python),
            str(_tool("extract_gvhmr_motion.py")),
            "--input",
            str(results[0]),
            "--output",
            str(motion),
            "--manifest",
            str(manifest),
            "--fps",
            _detect_fps(source),
        ],
        cwd=gvhmr_home,
        env=gvhmr_env,
    )
    return {
        "motion_npz": _ensure(motion, "motion NPZ"),
        "manifest": _ensure(manifest, "motion manifest"),
    }


def run_retarget(
    character: Path,
    motion: Path,
    mapping: Path,
    output_dir: Path,
    render_keyframes: bool,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    gvhmr_home = Path(_required_env("GVHMR_HOME")).expanduser().resolve()
    gvhmr_python = _home_python("GVHMR_HOME", ".venv310/bin/python")
    gvhmr_env = _gvhmr_env(gvhmr_home)
    blender = _blender()
    animated = output_dir / "animated.glb"
    retarget = output_dir / "retarget.json"
    apply_args: list[str] = [
        blender,
        "--background",
        "--python",
        str(_tool("apply_gvhmr_motion.py")),
        "--",
        "--character",
        str(character.resolve()),
        "--motion",
        str(motion.resolve()),
        "--mapping-json",
        str(mapping.resolve()),
        "--output",
        str(animated),
        "--report",
        str(retarget),
    ]
    _run(apply_args, cwd=output_dir)
    _ensure(animated, "animated GLB")
    _ensure(retarget, "retarget report")
    qa = output_dir / "qa.json"
    qa_text = _run_capture(
        [
            str(gvhmr_python),
            str(_tool("inspect_glb_animation.py")),
            str(animated),
        ],
        cwd=gvhmr_home,
        env=gvhmr_env,
    )
    qa.write_text(qa_text, encoding="utf-8")
    print(qa_text, end="")
    if render_keyframes:
        _run(
            [
                blender,
                "--background",
                "--python",
                str(_tool("render_glb_keyframes.py")),
                "--",
                "--input",
                str(animated),
                "--output-dir",
                str(output_dir / "keyframes"),
                "--frames",
                "1,80,160",
            ],
            cwd=output_dir,
        )
    return {
        "animated_glb": animated,
        "retarget_report": retarget,
        "qa_report": _ensure(qa, "animation QA report"),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one lightweight NAQI typed stage")
    parser.add_argument("stage", choices=("rig", "motion", "retarget"))
    parser.add_argument("--source")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--camera-mode", choices=("static", "moving"), default="static")
    parser.add_argument("--character", type=Path)
    parser.add_argument("--motion", type=Path)
    parser.add_argument("--mapping", type=Path)
    parser.add_argument("--render-keyframes", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.stage == "rig":
        if not args.source:
            raise StageAdapterError("rig requires --source")
        run_rig(Path(args.source), args.output_dir)
    elif args.stage == "motion":
        if not args.source:
            raise StageAdapterError("motion requires --source")
        run_motion(Path(args.source), args.output_dir, args.work_dir, args.camera_mode)
    else:
        if not args.character or not args.motion or not args.mapping:
            raise StageAdapterError("retarget requires --character, --motion, and --mapping")
        run_retarget(
            args.character,
            args.motion,
            args.mapping,
            args.output_dir,
            args.render_keyframes,
        )


if __name__ == "__main__":
    main()
