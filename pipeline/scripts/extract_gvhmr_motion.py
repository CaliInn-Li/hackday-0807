import argparse
import json
from pathlib import Path

import numpy as np
import torch
from pytorch3d.transforms import axis_angle_to_matrix, quaternion_to_matrix

from hmr4d.utils.smplx_utils import make_smplx
from hmr4d.utils.net_utils import to_cuda


SMPL22_NAMES = [
    "pelvis",
    "left_hip",
    "right_hip",
    "spine1",
    "left_knee",
    "right_knee",
    "spine2",
    "left_ankle",
    "right_ankle",
    "spine3",
    "left_foot",
    "right_foot",
    "neck",
    "left_collar",
    "right_collar",
    "head",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
]


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="GVHMR hmr4d_results.pt")
    parser.add_argument("--output", required=True, help="Portable NPZ output")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--fps", type=float, default=30.0)
    return parser.parse_args()


def as_rotation_matrix(value):
    value = torch.as_tensor(value).float()
    if value.shape[-2:] == (3, 3):
        return value
    if value.ndim == 2 and value.shape[-1] > 3 and value.shape[-1] % 3 == 0:
        value = value.reshape(value.shape[0], -1, 3)
    if value.shape[-1] == 3:
        return axis_angle_to_matrix(value)
    if value.shape[-1] == 4:
        return quaternion_to_matrix(value)
    raise ValueError(f"Unsupported rotation shape: {tuple(value.shape)}")


def normalized_rotations(params):
    root = as_rotation_matrix(params["global_orient"])
    body = as_rotation_matrix(params["body_pose"])
    if root.ndim == 3:
        root = root[:, None]
    if body.ndim == 3:
        body = body.reshape(body.shape[0], -1, 3, 3)
    rotations = torch.cat((root, body), dim=1)
    if rotations.shape[1] < 22:
        raise ValueError(f"Expected at least 22 joints, got {rotations.shape[1]}")
    return rotations[:, :22]


@torch.no_grad()
def source_height(params):
    model = make_smplx("supermotion").cuda()
    output = model(**to_cuda(params))
    vertices = output.vertices[0]
    # GVHMR/SMPL-X is Y-up.
    return float((vertices[:, 1].max() - vertices[:, 1].min()).item())


def tensor_shapes(value):
    if isinstance(value, torch.Tensor):
        return list(value.shape)
    if isinstance(value, dict):
        return {key: tensor_shapes(item) for key, item in value.items()}
    return type(value).__name__


def main():
    args = parse_args()

    if not args.input or not args.input.strip():
        raise SystemExit(
            "ERROR: --input is empty. The $GVHMR_RESULT (and $VIDEO_STEM) shell "
            "variables were probably not defined. Make sure VIDEO_STEM and "
            "GVHMR_RESULT are set before invoking this script."
        )

    input_path = Path(args.input)
    if not input_path.is_file():
        raise SystemExit(
            f"ERROR: --input is not a file: {input_path} "
            "(is $GVHMR_RESULT pointing at hmr4d_results.pt?)"
        )
    pred = torch.load(input_path, map_location="cpu", weights_only=False)
    params = pred["smpl_params_global"]
    rotations = normalized_rotations(params).cpu().numpy().astype(np.float32)
    translations = torch.as_tensor(params["transl"]).cpu().numpy().astype(np.float32)
    if translations.ndim == 3 and translations.shape[1] == 1:
        translations = translations[:, 0]
    if translations.shape != (rotations.shape[0], 3):
        raise ValueError(f"Unexpected translation shape: {translations.shape}")

    height = source_height(params)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output_path,
        rotations=rotations,
        translations=translations,
        source_height=np.float32(height),
        fps=np.float32(args.fps),
        joint_names=np.asarray(SMPL22_NAMES),
    )

    manifest = {
        "input": str(input_path.resolve()),
        "output": str(output_path.resolve()),
        "frames": int(rotations.shape[0]),
        "fps": args.fps,
        "duration_seconds": round(rotations.shape[0] / args.fps, 3),
        "source_height_m": round(height, 6),
        "rotation_shape": list(rotations.shape),
        "translation_shape": list(translations.shape),
        "translation_range": {
            "min": translations.min(axis=0).round(6).tolist(),
            "max": translations.max(axis=0).round(6).tolist(),
        },
        "source_keys": tensor_shapes(pred),
    }
    manifest_path = Path(args.manifest)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
