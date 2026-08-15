import argparse
import json
import pickle
from pathlib import Path

import numpy as np


SMPL_NAMES = [
    "Pelvis", "L_Hip", "R_Hip", "Spine1", "L_Knee", "R_Knee", "Spine2",
    "L_Ankle", "R_Ankle", "Spine3", "L_Foot", "R_Foot", "Neck",
    "L_Collar", "R_Collar", "Head", "L_Shoulder", "R_Shoulder",
    "L_Elbow", "R_Elbow", "L_Wrist", "R_Wrist", "L_Hand", "R_Hand",
]


def numeric(value):
    if hasattr(value, "r"):
        value = value.r
    if hasattr(value, "get_value"):
        value = value.get_value()
    return np.asarray(value, dtype=float)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    with open(args.input, "rb") as handle:
        model = pickle.load(handle, encoding="latin1")
    joints = numeric(model["J"])
    kintree = numeric(model["kintree_table"]).astype(int)
    if joints.shape[0] < 24 or kintree.shape[1] < 24:
        raise RuntimeError(f"Expected at least 24 SMPL joints, got J={joints.shape}, kintree={kintree.shape}")

    parents = kintree[0, :24].tolist()
    root = int(kintree[1, 0])
    parents[0] = -1
    for index, parent in enumerate(parents):
        if index and parent == root:
            parents[index] = 0

    payload = {
        "names": SMPL_NAMES,
        "joints": joints[:24].tolist(),
        "parents": parents,
        "source": str(Path(args.input).resolve()),
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output), "joint_count": 24, "parents": parents}))


if __name__ == "__main__":
    main()
