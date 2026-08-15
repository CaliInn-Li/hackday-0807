"""Inspect a SkinTokens GLB skeleton without Blender.

The output is deliberately a topology report and mapping proposal, not an
automatic final retarget map.  SkinTokens bone numbers are not a stable
semantic contract, so the proposal uses parent/child structure, chain depth,
branching, and rest-pose positions.  Left/right still needs an explicit
coordinate convention check before it is used for animation.
"""

from __future__ import annotations

import argparse
import json
import math
import struct
from pathlib import Path
from typing import Any


Vec3 = tuple[float, float, float]
Mat4 = tuple[tuple[float, float, float, float], ...]


def read_glb_json(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    if data[:4] != b"glTF":
        raise ValueError(f"Not a GLB file: {path}")
    json_length, json_type = struct.unpack_from("<II", data, 12)
    if json_type != 0x4E4F534A:
        raise ValueError("The first GLB chunk is not JSON")
    text = data[20 : 20 + json_length].decode("utf-8").rstrip(" \x00")
    return json.loads(text)


def identity() -> Mat4:
    return (
        (1.0, 0.0, 0.0, 0.0),
        (0.0, 1.0, 0.0, 0.0),
        (0.0, 0.0, 1.0, 0.0),
        (0.0, 0.0, 0.0, 1.0),
    )


def matmul(a: Mat4, b: Mat4) -> Mat4:
    return tuple(
        tuple(sum(a[row][k] * b[k][col] for k in range(4)) for col in range(4))
        for row in range(4)
    )  # type: ignore[return-value]


def trs_matrix(node: dict[str, Any]) -> Mat4:
    if "matrix" in node:
        values = [float(value) for value in node["matrix"]]
        if len(values) != 16:
            raise ValueError("A glTF node matrix must contain 16 values")
        # glTF stores matrices column-major; this module uses row-major math.
        return tuple(
            tuple(values[col * 4 + row] for col in range(4))
            for row in range(4)
        )  # type: ignore[return-value]

    tx, ty, tz = (float(value) for value in node.get("translation", (0, 0, 0)))
    qx, qy, qz, qw = (float(value) for value in node.get("rotation", (0, 0, 0, 1)))
    sx, sy, sz = (float(value) for value in node.get("scale", (1, 1, 1)))

    xx, yy, zz = qx * qx, qy * qy, qz * qz
    xy, xz, yz = qx * qy, qx * qz, qy * qz
    wx, wy, wz = qw * qx, qw * qy, qw * qz
    rotation = (
        (1 - 2 * (yy + zz), 2 * (xy - wz), 2 * (xz + wy)),
        (2 * (xy + wz), 1 - 2 * (xx + zz), 2 * (yz - wx)),
        (2 * (xz - wy), 2 * (yz + wx), 1 - 2 * (xx + yy)),
    )
    return (
        (rotation[0][0] * sx, rotation[0][1] * sy, rotation[0][2] * sz, tx),
        (rotation[1][0] * sx, rotation[1][1] * sy, rotation[1][2] * sz, ty),
        (rotation[2][0] * sx, rotation[2][1] * sy, rotation[2][2] * sz, tz),
        (0.0, 0.0, 0.0, 1.0),
    )


def position(matrix: Mat4) -> Vec3:
    return (matrix[0][3], matrix[1][3], matrix[2][3])


def sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def length(value: Vec3) -> float:
    return math.sqrt(sum(component * component for component in value))


def average(points: list[Vec3]) -> Vec3:
    if not points:
        return (0.0, 0.0, 0.0)
    total = (0.0, 0.0, 0.0)
    for point in points:
        total = add(total, point)
    return tuple(component / len(points) for component in total)  # type: ignore[return-value]


def round_vec(value: Vec3) -> list[float]:
    return [round(component, 7) for component in value]


def nearest_joint_parent(node_index: int, node_parent: dict[int, int], node_to_joint: dict[int, int]) -> int:
    parent = node_parent.get(node_index)
    while parent is not None:
        if parent in node_to_joint:
            return node_to_joint[parent]
        parent = node_parent.get(parent)
    return -1


def descendants(joint_index: int, children: dict[int, list[int]]) -> list[int]:
    result: list[int] = []
    for child in children.get(joint_index, []):
        result.append(child)
        result.extend(descendants(child, children))
    return result


def child_path(start: int, children: dict[int, list[int]]) -> list[int]:
    """Follow a single-child chain and stop at a branch or a leaf."""
    path = [start]
    current = start
    while len(children.get(current, [])) == 1:
        current = children[current][0]
        path.append(current)
    return path


def best_upward_child(
    parent: int, children: dict[int, list[int]], world_positions: list[Vec3]
) -> int | None:
    candidates = children.get(parent, [])
    if not candidates:
        return None
    base = world_positions[parent]
    return max(
        candidates,
        key=lambda index: (world_positions[index][1] - base[1], -length(sub(world_positions[index], base))),
    )


def semantic_path_mapping(
    path: list[int], names: list[str], slots: list[str]
) -> dict[str, str]:
    if not path:
        return {}
    result: dict[str, str] = {}
    for slot, index in zip(slots, path):
        result[slot] = names[index]
    if len(path) > len(slots):
        result["extra_chain_joints"] = ",".join(names[index] for index in path[len(slots) :])
    return result


def analyze(path: Path) -> dict[str, Any]:
    document = read_glb_json(path)
    nodes = document.get("nodes", [])
    skins = document.get("skins", [])
    if not skins:
        raise ValueError("The GLB has no skin")

    joints = [int(index) for index in skins[0].get("joints", [])]
    if not joints:
        raise ValueError("The first skin has no joints")
    node_to_joint = {node_index: joint_index for joint_index, node_index in enumerate(joints)}

    node_parent: dict[int, int] = {}
    for parent_index, node in enumerate(nodes):
        for child_index in node.get("children", []):
            node_parent[int(child_index)] = parent_index

    local_matrices = [trs_matrix(node) for node in nodes]
    world_cache: dict[int, Mat4] = {}

    def world_matrix(node_index: int) -> Mat4:
        if node_index in world_cache:
            return world_cache[node_index]
        parent = node_parent.get(node_index)
        result = local_matrices[node_index] if parent is None else matmul(world_matrix(parent), local_matrices[node_index])
        world_cache[node_index] = result
        return result

    world_positions = [position(world_matrix(node_index)) for node_index in joints]
    parent_joint = {
        joint_index: nearest_joint_parent(node_index, node_parent, node_to_joint)
        for joint_index, node_index in enumerate(joints)
    }
    children: dict[int, list[int]] = {joint_index: [] for joint_index in range(len(joints))}
    for joint_index, parent in parent_joint.items():
        if parent >= 0:
            children[parent].append(joint_index)
    for values in children.values():
        values.sort()

    names = [str(nodes[node_index].get("name", f"joint_{joint_index}")) for joint_index, node_index in enumerate(joints)]
    roots = [index for index, parent in parent_joint.items() if parent < 0]
    root = max(roots, key=lambda index: len(descendants(index, children))) if roots else 0

    root_children = children.get(root, [])
    upward = best_upward_child(root, children, world_positions)
    leg_children = [index for index in root_children if index != upward]

    spine_path: list[int] = [root]
    if upward is not None:
        spine_path.extend(child_path(upward, children))
    branch = spine_path[-1]
    branch_children = children.get(branch, [])
    neck = best_upward_child(branch, children, world_positions)
    arm_children = [index for index in branch_children if index != neck]

    arm_paths = []
    for index in arm_children:
        path_indices = child_path(index, children)
        arm_paths.append(
            {
                "side_axis": "x_positive" if world_positions[index][0] >= world_positions[root][0] else "x_negative",
                "path": [names[item] for item in path_indices],
                "semantic_slots": semantic_path_mapping(
                    path_indices, names, ["Collar", "Shoulder", "Elbow", "Wrist"]
                ),
                "finger_or_extra_children": [names[item] for item in children.get(path_indices[-1], [])],
            }
        )

    leg_paths = []
    for index in leg_children:
        path_indices = child_path(index, children)
        leg_paths.append(
            {
                "side_axis": "x_positive" if world_positions[index][0] >= world_positions[root][0] else "x_negative",
                "path": [names[item] for item in path_indices],
                "semantic_slots": semantic_path_mapping(
                    path_indices, names, ["Hip", "Knee", "Ankle", "Foot"]
                ),
            }
        )

    neck_path = child_path(neck, children) if neck is not None else []
    body_mapping: dict[str, str] = {"Pelvis": names[root]}
    body_mapping.update(semantic_path_mapping(spine_path[1:], names, ["Spine1", "Spine2", "Spine3"]))
    body_mapping.update(semantic_path_mapping(neck_path, names, ["Neck", "Head"]))

    joint_rows = []
    for joint_index, node_index in enumerate(joints):
        child_indices = children.get(joint_index, [])
        descendants_indices = descendants(joint_index, children)
        joint_rows.append(
            {
                "joint_index": joint_index,
                "node_index": node_index,
                "name": names[joint_index],
                "parent": names[parent_joint[joint_index]] if parent_joint[joint_index] >= 0 else None,
                "children": [names[index] for index in child_indices],
                "direct_child_count": len(child_indices),
                "descendant_count": len(descendants_indices),
                "leaf_count": sum(not children.get(index) for index in descendants_indices + [joint_index]),
                "world_position": round_vec(world_positions[joint_index]),
            }
        )

    return {
        "input": str(path.resolve()),
        "skin_count": len(skins),
        "joint_count": len(joints),
        "coordinate_note": "Positions are reported in the GLB node coordinate system; left/right still needs an explicit front/orientation check.",
        "root_candidates": [names[index] for index in roots],
        "root_candidate": names[root],
        "root_children": [names[index] for index in root_children],
        "upward_spine_branch": names[upward] if upward is not None else None,
        "spine_path": [names[index] for index in spine_path],
        "first_upper_branch": names[branch],
        "neck_path": [names[index] for index in neck_path],
        "body_mapping": body_mapping,
        "arm_candidates": arm_paths,
        "leg_candidates": leg_paths,
        "joints": joint_rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = analyze(args.input.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "output": str(args.output.resolve()),
        "joint_count": report["joint_count"],
        "root": report["root_candidate"],
        "spine_path": report["spine_path"],
        "arm_candidates": report["arm_candidates"],
        "leg_candidates": report["leg_candidates"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
