"""Build an SMPL-22 mapping from a SkinTokens topology report.

The mapping is based on the report's semantic paths, not on stable-looking
bone numbers.  The analyzer labels the two lateral branches as x_positive and
x_negative.  By default x_positive is treated as the character's left side;
pass --x-positive-is-right when the GLB uses the opposite convention.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


BODY_TO_SMPL22 = {
    "Pelvis": 0,
    "Spine1": 3,
    "Spine2": 6,
    "Spine3": 9,
    "Neck": 12,
    "Head": 15,
}

ARM_TO_SMPL22 = {
    "left": {"Collar": 13, "Shoulder": 16, "Elbow": 18, "Wrist": 20},
    "right": {"Collar": 14, "Shoulder": 17, "Elbow": 19, "Wrist": 21},
}

LEG_TO_SMPL22 = {
    "left": {"Hip": 1, "Knee": 4, "Ankle": 7, "Foot": 10},
    "right": {"Hip": 2, "Knee": 5, "Ankle": 8, "Foot": 11},
}


def required_mapping_value(mapping: dict[str, Any], name: str, context: str) -> str:
    value = mapping.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{context} is missing semantic slot {name!r}")
    return value


def pick_side_candidate(candidates: list[dict[str, Any]], side_axis: str, kind: str) -> dict[str, Any]:
    matches = [candidate for candidate in candidates if candidate.get("side_axis") == side_axis]
    if len(matches) != 1:
        raise ValueError(
            f"Expected exactly one {kind} candidate for {side_axis}, got {len(matches)}"
        )
    return matches[0]


def build_mapping(report: dict[str, Any], x_positive_is_left: bool) -> dict[str, Any]:
    body = report.get("body_mapping")
    if not isinstance(body, dict):
        raise ValueError("Topology report has no body_mapping object")

    bone_to_smpl22: dict[str, int] = {}
    semantic_to_bone: dict[str, str] = {}

    for semantic_name, source_index in BODY_TO_SMPL22.items():
        bone_name = required_mapping_value(body, semantic_name, "body_mapping")
        bone_to_smpl22[bone_name] = source_index
        semantic_to_bone[semantic_name] = bone_name

    positive_side = "left" if x_positive_is_left else "right"
    negative_side = "right" if x_positive_is_left else "left"
    side_axes = (("x_positive", positive_side), ("x_negative", negative_side))

    arms = report.get("arm_candidates")
    legs = report.get("leg_candidates")
    if not isinstance(arms, list) or not isinstance(legs, list):
        raise ValueError("Topology report must contain arm_candidates and leg_candidates arrays")

    for axis, side in side_axes:
        arm = pick_side_candidate(arms, axis, "arm")
        arm_slots = arm.get("semantic_slots")
        if not isinstance(arm_slots, dict):
            raise ValueError(f"Arm candidate {axis} has no semantic_slots object")
        for semantic_name, source_index in ARM_TO_SMPL22[side].items():
            bone_name = required_mapping_value(arm_slots, semantic_name, f"arm {axis}")
            bone_to_smpl22[bone_name] = source_index
            semantic_to_bone[f"{side}_{semantic_name}"] = bone_name

        leg = pick_side_candidate(legs, axis, "leg")
        leg_slots = leg.get("semantic_slots")
        if not isinstance(leg_slots, dict):
            raise ValueError(f"Leg candidate {axis} has no semantic_slots object")
        for semantic_name, source_index in LEG_TO_SMPL22[side].items():
            bone_name = required_mapping_value(leg_slots, semantic_name, f"leg {axis}")
            bone_to_smpl22[bone_name] = source_index
            semantic_to_bone[f"{side}_{semantic_name}"] = bone_name

    values = list(bone_to_smpl22.values())
    if sorted(values) != list(range(22)):
        raise ValueError(f"Generated mapping does not cover SMPL-22 exactly: {sorted(values)}")

    all_joints = {
        str(row["name"])
        for row in report.get("joints", [])
        if isinstance(row, dict) and row.get("name")
    }
    mapped_joints = set(bone_to_smpl22)
    return {
        "mapping_method": "SkinTokens topology report -> SMPL-22 semantic slots",
        "source_topology_report": str(report.get("input", "")),
        "source_joint_count": int(report.get("joint_count", len(all_joints))),
        "coordinate_note": (
            f"x_positive is treated as SMPL-{positive_side[0].upper()} and "
            f"x_negative as SMPL-{negative_side[0].upper()}; verify the character front view."
        ),
        "x_positive_is": positive_side,
        "semantic_to_bone": semantic_to_bone,
        "bone_to_smpl22": bone_to_smpl22,
        "extra_bones": sorted(all_joints - mapped_joints),
        "extra_bones_policy": (
            "Keep extra SkinTokens joints in the armature. Current GVHMR export is SMPL-22, "
            "so finger and prop joints are not keyed by this retarget pass."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topology-report", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    side = parser.add_mutually_exclusive_group()
    side.add_argument(
        "--x-positive-is-left",
        dest="x_positive_is_left",
        action="store_true",
        help="Treat the analyzer's x_positive branch as the character's left side (default).",
    )
    side.add_argument(
        "--x-positive-is-right",
        dest="x_positive_is_left",
        action="store_false",
        help="Treat the analyzer's x_positive branch as the character's right side.",
    )
    parser.set_defaults(x_positive_is_left=True)
    args = parser.parse_args()

    report = json.loads(args.topology_report.read_text(encoding="utf-8"))
    mapping = build_mapping(report, args.x_positive_is_left)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "output": str(args.output.resolve()),
        "source_joint_count": mapping["source_joint_count"],
        "mapped_bones": len(mapping["bone_to_smpl22"]),
        "extra_bones": len(mapping["extra_bones"]),
        "x_positive_is": mapping["x_positive_is"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
