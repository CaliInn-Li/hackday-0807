"""Register the checked-in demo outputs without rerunning GPU inference.

Run this with backend/.venv/bin/python after setting NAQI_DATA_ROOT. The script
is idempotent: deterministic IDs and upserted file records make reruns safe.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
from pathlib import Path


NAQI_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = NAQI_ROOT / "backend"
DATA_ROOT = Path(
    os.environ.get("NAQI_DATA_ROOT", str(BACKEND_ROOT / "data"))
).expanduser().resolve()
DATABASE_PATH = Path(
    os.environ.get("NAQI_DATABASE_PATH", str(DATA_ROOT / "naqi.sqlite3"))
).expanduser().resolve()
sys.path.insert(0, str(BACKEND_ROOT))

from naqi_backend.assets import ASSET_MIME_TYPES, AssetDatabase  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


database = AssetDatabase(DATABASE_PATH, DATA_ROOT)
database.initialize()


def register(
    *,
    asset_id: str,
    kind: str,
    name: str,
    files: dict[str, Path],
    source_character_id: str | None = None,
    source_motion_id: str | None = None,
) -> None:
    missing = [str(path) for path in files.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"demo source files are missing: {missing}")

    root = DATA_ROOT / "assets" / kind / asset_id
    root.mkdir(parents=True, exist_ok=True)
    first_source = next(iter(files.values()))
    asset = database.get_asset(asset_id)
    if asset is None:
        asset = database.create_asset(
            asset_id=asset_id,
            kind=kind,
            name=name,
            root_dir=root,
            source_sha256=sha256(first_source),
            cache_key=f"demo-seed:{asset_id}",
            source_character_id=source_character_id,
            source_motion_id=source_motion_id,
            status="ready",
        )

    for file_kind, source in files.items():
        destination = root / source.name
        source_hash = sha256(source)
        if not destination.exists() or sha256(destination) != source_hash:
            shutil.copy2(source, destination)
        database.add_file(
            asset_id=asset.id,
            file_kind=file_kind,
            path=destination,
            size_bytes=destination.stat().st_size,
            sha256=source_hash,
            mime_type=ASSET_MIME_TYPES[file_kind],
        )
    database.set_asset_status(asset.id, "ready")
    print(f"registered {kind}: {name} ({asset.id})")


register(
    asset_id="character-snow-girl-demo",
    kind="character",
    name="雪帽少女",
    files={
        "source_glb": NAQI_ROOT / "input" / "雪帽少女.glb",
        "rigged_glb": NAQI_ROOT / "output" / "rigged" / "雪帽少女_rigged.glb",
        "topology_report": NAQI_ROOT / "output" / "reports" / "topology" / "snow_girl_rigged_topology.json",
        "mapping": NAQI_ROOT / "config" / "snow_girl_topology_mapping.json",
    },
)
register(
    asset_id="character-ice-archer-demo",
    kind="character",
    name="冰雪射手",
    files={
        "source_glb": NAQI_ROOT / "input" / "冰雪射手.glb",
        "rigged_glb": NAQI_ROOT / "output" / "rigged" / "冰雪射手_rigged.glb",
        "topology_report": NAQI_ROOT / "output" / "reports" / "topology" / "ice_archer_rigged_topology.json",
        "mapping": NAQI_ROOT / "config" / "ice_archer_topology_mapping.json",
    },
)

for key, label in (("video1", "Video 1"), ("video2", "Video 2")):
    register(
        asset_id=f"motion-{key}-demo",
        kind="motion",
        name=f"{label} 动作",
        files={
            "motion_npz": NAQI_ROOT / "motion" / f"{key}_smpl22.npz",
            "manifest": NAQI_ROOT / "motion" / f"{key}_motion_manifest.json",
        },
    )
register(
    asset_id="motion-action-trim-demo",
    kind="motion",
    name="Action Trim 动作",
    files={
        "source_mp4": NAQI_ROOT / "input" / "videos" / "action_trim.mp4",
        "motion_npz": NAQI_ROOT / "motion" / "action_trim_smpl22.npz",
        "manifest": NAQI_ROOT / "motion" / "action_trim_motion_manifest.json",
    },
)

animations = (
    ("snow-girl-video1", "雪帽少女 + Video 1", "snow-girl", "video1", "雪帽少女_video1"),
    ("ice-archer-video1", "冰雪射手 + Video 1", "ice-archer", "video1", "冰雪射手_video1"),
    ("snow-girl-video2", "雪帽少女 + Video 2", "snow-girl", "video2", "雪帽少女_video2"),
    ("ice-archer-video2", "冰雪射手 + Video 2", "ice-archer", "video2", "冰雪射手_video2"),
    ("snow-girl-action-trim", "雪帽少女 + Action Trim", "snow-girl", "action-trim", "雪帽少女_action_trim"),
)
for key, name, character_key, motion_key, filename_root in animations:
    files = {
        "animated_glb": NAQI_ROOT / "output" / "animated" / f"{filename_root}_animated.glb",
        "retarget_report": NAQI_ROOT / "output" / "reports" / "retarget" / f"{filename_root}_retarget.json",
    }
    qa_report = NAQI_ROOT / "output" / "reports" / "animation" / f"{filename_root}_animation.json"
    if qa_report.is_file():
        files["qa_report"] = qa_report
    register(
        asset_id=f"animation-{key}-demo",
        kind="animation",
        name=name,
        source_character_id=f"character-{character_key}-demo",
        source_motion_id=f"motion-{motion_key}-demo",
        files=files,
    )
