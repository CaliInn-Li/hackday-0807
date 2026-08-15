"""Embed the deterministic production SMPL-22 skeleton into a character GLB.

Placeholder weights keep all joints alive through glTF. SkinTokens replaces
them when invoked with ``--use-skeleton --use-transfer``.
"""

import argparse
import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from rig_contract import (
    CONTRACT_NAME,
    PREFERRED_TAIL_CHILD,
    SKINTOKENS_TRANSFER_ARMATURE_NAME,
    SMPL22_TARGET_PARENTS,
    validate_template_payload,
)
from skeleton_fit import (
    estimate_arm_section_center,
    estimate_body_axis,
    estimate_foot_centers,
    estimate_head_center,
)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--template", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument(
        "--body-center-y",
        type=float,
        help="Override the fitted torso-axis Y in imported Blender coordinates.",
    )
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])


def reset_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for collection in (bpy.data.armatures, bpy.data.actions):
        for datablock in list(collection):
            collection.remove(datablock)


def load_template(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    problems = validate_template_payload(payload)
    if problems:
        raise RuntimeError("Invalid SMPL-22 template:\n  - " + "\n  - ".join(problems))
    joints = payload["joints"]
    return (
        [item["name"] for item in joints],
        {item["name"]: item.get("parent") for item in joints},
        {item["name"]: Vector(item["position"]) for item in joints},
        payload.get("fit", {}),
    )


def import_static_character(path):
    bpy.ops.import_scene.gltf(filepath=str(Path(path).resolve()))
    armatures = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
    meshes = [
        obj
        for obj in bpy.context.scene.objects
        if obj.type == "MESH" and not obj.name.lower().startswith("icosphere")
    ]
    if not meshes:
        raise RuntimeError("Input GLB does not contain a renderable mesh")

    # This stage owns the canonical rig. Remove stale skin state while keeping
    # the visible asset and its material/morph data.
    for mesh in meshes:
        world = mesh.matrix_world.copy()
        mesh.parent = None
        mesh.matrix_world = world
        for modifier in list(mesh.modifiers):
            if modifier.type == "ARMATURE":
                mesh.modifiers.remove(modifier)
        for group in list(mesh.vertex_groups):
            mesh.vertex_groups.remove(group)
    for armature in armatures:
        bpy.data.objects.remove(armature, do_unlink=True)

    # Bake all node transforms so fitted joints and exported POSITION accessors
    # share one bind coordinate system.
    for mesh in meshes:
        mesh.data.transform(mesh.matrix_world)
        mesh.matrix_world.identity()
    return sorted(meshes, key=lambda item: item.name)


def mesh_points(meshes):
    return [vertex.co.copy() for mesh in meshes for vertex in mesh.data.vertices]


def mesh_bounds(points):
    if not points:
        raise RuntimeError("Input meshes contain no vertices")
    minimum = Vector(tuple(min(point[i] for point in points) for i in range(3)))
    maximum = Vector(tuple(max(point[i] for point in points) for i in range(3)))
    return minimum, maximum


def fit_positions(
    template_positions,
    points,
    minimum,
    maximum,
    fit_settings,
    body_center_y_override=None,
):
    extent = maximum - minimum
    if min(extent) <= 1e-8:
        raise RuntimeError(f"Degenerate character bounds: min={minimum}, max={maximum}")
    body_axis = estimate_body_axis(
        points, minimum, maximum, fit_settings.get("body_axis", {})
    )
    if body_center_y_override is not None:
        body_axis["center_y"] = float(body_center_y_override)
        body_axis["sample_mode"] = "manual_override"

    height, width, depth = extent.z, extent.x, extent.y
    max_abs_x = max(abs(point.x) for point in template_positions.values())
    max_abs_y = max(abs(point.y) for point in template_positions.values())
    x_scale = min(height, width * 0.96 / (2 * max_abs_x))
    y_scale = min(height, depth * 0.80 / (2 * max_abs_y)) if max_abs_y else height
    positions = {
        name: Vector(
            (
                body_axis["center_x"] + normalized.x * x_scale,
                body_axis["center_y"] + normalized.y * y_scale,
                minimum.z + normalized.z * height,
            )
        )
        for name, normalized in template_positions.items()
    }

    landmark_settings = fit_settings.get("limb_landmarks", {})
    landmark_report = {"arms": {}, "feet": {}}
    for side in ("Left", "Right"):
        for joint in ("Arm", "ForeArm", "Hand"):
            name = f"mixamorig:{side}{joint}"
            section = estimate_arm_section_center(
                points, minimum, maximum, positions[name].x, landmark_settings
            )
            landmark_report["arms"][name] = section
            if section["accepted"]:
                positions[name].y = section["y"]
                positions[name].z = section["z"]

        shoulder_name = f"mixamorig:{side}Shoulder"
        arm_name = f"mixamorig:{side}Arm"
        if landmark_report["arms"][arm_name]["accepted"]:
            spine = positions["mixamorig:Spine2"]
            arm = positions[arm_name]
            positions[shoulder_name].y = spine.y * 0.75 + arm.y * 0.25
            positions[shoulder_name].z = spine.z * 0.75 + arm.z * 0.25

    feet = estimate_foot_centers(points, minimum, maximum, landmark_settings)
    landmark_report["feet"] = feet
    if feet["accepted"]:
        for side, label in (("Left", "left"), ("Right", "right")):
            hip_name = f"mixamorig:{side}UpLeg"
            knee_name = f"mixamorig:{side}Leg"
            foot_name = f"mixamorig:{side}Foot"
            toe_name = f"mixamorig:{side}ToeBase"
            foot_x = feet[label]["x"]
            hip_x = positions[hip_name].x
            positions[knee_name].x = hip_x * 0.45 + foot_x * 0.55
            positions[foot_name].x = foot_x
            positions[toe_name].x = foot_x
            positions[foot_name].y = (
                body_axis["center_y"] * 0.5 + feet[label]["y"] * 0.5
            )

    head = estimate_head_center(points, minimum, maximum, landmark_settings)
    landmark_report["head"] = head
    if head["accepted"]:
        spine2 = positions["mixamorig:Spine2"]
        accepted_arm_z = [
            section["z"]
            for name, section in landmark_report["arms"].items()
            if name in ("mixamorig:LeftArm", "mixamorig:RightArm")
            and section["accepted"]
        ]
        neck_z = spine2.z + float(
            landmark_settings.get("neck_above_spine2", 0.035)
        ) * height
        if accepted_arm_z:
            neck_z = max(
                neck_z,
                sum(accepted_arm_z) / len(accepted_arm_z)
                + float(
                    landmark_settings.get("neck_above_arm_center", 0.055)
                )
                * height,
            )
        minimum_head_gap = float(
            landmark_settings.get("head_min_above_neck", 0.060)
        ) * height
        if head["z"] > neck_z + minimum_head_gap:
            positions["mixamorig:Neck"] = Vector(
                (
                    body_axis["center_x"],
                    spine2.y * 0.5 + head["y"] * 0.5,
                    neck_z,
                )
            )
            positions["mixamorig:Head"] = Vector(
                (head["x"], head["y"], head["z"])
            )
            head["neck_accepted"] = True
            head["neck_z"] = float(neck_z)
        else:
            head["neck_accepted"] = False
            head["neck_reason"] = "fitted head does not leave the minimum neck gap"
    bounds_center_y = (minimum.y + maximum.y) * 0.5
    body_axis.update(
        {
            "bounds_center_y": float(bounds_center_y),
            "offset_from_bounds_center_y": float(body_axis["center_y"] - bounds_center_y),
            "x_scale": float(x_scale),
            "y_scale": float(y_scale),
            "height": float(height),
        }
    )
    return positions, body_axis, landmark_report


def create_armature(names, parents, positions, minimum, maximum):
    # SkinTokens' current transfer implementation recreates a literal
    # ``Armature`` and looks it up by the imported asset name.
    data = bpy.data.armatures.new(SKINTOKENS_TRANSFER_ARMATURE_NAME)
    armature = bpy.data.objects.new(SKINTOKENS_TRANSFER_ARMATURE_NAME, data)
    bpy.context.collection.objects.link(armature)
    armature.show_in_front = True
    armature["skeleton_contract"] = CONTRACT_NAME
    armature["skeleton_joint_count"] = 22

    bpy.context.view_layer.objects.active = armature
    armature.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    edit_bones = {}
    height = maximum.z - minimum.z
    terminal_directions = {
        "mixamorig:Head": Vector((0, 0, 1)),
        "mixamorig:LeftHand": Vector((1, 0, 0)),
        "mixamorig:RightHand": Vector((-1, 0, 0)),
        "mixamorig:LeftToeBase": Vector((0, -1, 0)),
        "mixamorig:RightToeBase": Vector((0, -1, 0)),
    }
    for name in names:
        bone = data.edit_bones.new(name)
        bone.head = positions[name]
        child = PREFERRED_TAIL_CHILD.get(name)
        if child:
            bone.tail = positions[child]
        elif name in terminal_directions:
            tail = positions[name] + terminal_directions[name] * max(height * 0.02, 1e-5)
            bone.tail = Vector(
                tuple(
                    min(max(float(tail[axis]), float(minimum[axis])), float(maximum[axis]))
                    for axis in range(3)
                )
            )
        elif parents[name]:
            direction = positions[name] - positions[parents[name]]
            if direction.length < height * 1e-4:
                direction = Vector((0, 0, 1))
            bone.tail = positions[name] + direction.normalized() * max(height * 0.035, 1e-5)
        else:
            bone.tail = positions[name] + Vector((0, 0, max(height * 0.035, 1e-5)))
        bone.roll = 0.0
        bone.use_deform = True
        edit_bones[name] = bone
    for name, parent in parents.items():
        if parent:
            edit_bones[name].parent = edit_bones[parent]
            edit_bones[name].use_connect = False
    bpy.ops.object.mode_set(mode="OBJECT")
    armature.select_set(False)
    return armature


def add_placeholder_weights(meshes, armature, names, positions):
    """Keep all joints and vertices valid until SkinTokens replaces weights."""
    all_vertices = [(mesh, vertex) for mesh in meshes for vertex in mesh.data.vertices]
    if len(all_vertices) < len(names):
        raise RuntimeError("Character needs at least 22 vertices to preserve SMPL-22")
    reserved = set()
    forced = {}
    for name in names:
        mesh, vertex = min(
            (
                item
                for item in all_vertices
                if (item[0].name, item[1].index) not in reserved
            ),
            key=lambda item: (item[1].co - positions[name]).length_squared,
        )
        key = (mesh.name, vertex.index)
        reserved.add(key)
        forced[key] = name

    for mesh in meshes:
        groups = {name: mesh.vertex_groups.new(name=name) for name in names}
        for vertex in mesh.data.vertices:
            name = forced.get((mesh.name, vertex.index))
            if name is None:
                name = min(
                    names,
                    key=lambda candidate: (vertex.co - positions[candidate]).length_squared,
                )
            groups[name].add([vertex.index], 1.0, "REPLACE")
        modifier = mesh.modifiers.new("SMPL22Rig", "ARMATURE")
        modifier.object = armature
        mesh.parent = armature
        mesh.matrix_parent_inverse = armature.matrix_world.inverted()


def validate_placeholder(meshes, names):
    expected = set(names)
    influenced = set()
    for mesh in meshes:
        groups = {group.index: group.name for group in mesh.vertex_groups}
        if set(groups.values()) != expected:
            raise RuntimeError(f"Placeholder vertex groups are incomplete on {mesh.name}")
        for vertex in mesh.data.vertices:
            positive = [entry for entry in vertex.groups if entry.weight > 1e-8]
            if len(positive) != 1:
                raise RuntimeError(
                    f"Placeholder {mesh.name}[{vertex.index}] must have one weight"
                )
            influenced.add(groups[positive[0].group])
    if influenced != expected:
        raise RuntimeError(f"Placeholder did not preserve: {sorted(expected - influenced)}")


def export_glb(path, armature, meshes):
    output = Path(path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    armature.select_set(True)
    for mesh in meshes:
        mesh.select_set(True)
    bpy.context.view_layer.objects.active = armature
    bpy.ops.export_scene.gltf(
        filepath=str(output),
        export_format="GLB",
        use_selection=True,
        export_skins=True,
        export_animations=False,
        export_morph=True,
        export_yup=True,
    )


def main():
    args = parse_args()
    reset_scene()
    names, parents, template_positions, fit_settings = load_template(args.template)
    meshes = import_static_character(args.input)
    points = mesh_points(meshes)
    minimum, maximum = mesh_bounds(points)
    positions, body_axis, landmark_fit = fit_positions(
        template_positions,
        points,
        minimum,
        maximum,
        fit_settings,
        args.body_center_y,
    )
    armature = create_armature(names, parents, positions, minimum, maximum)
    add_placeholder_weights(meshes, armature, names, positions)
    validate_placeholder(meshes, names)
    export_glb(args.output, armature, meshes)

    report = {
        "input": str(Path(args.input).resolve()),
        "output": str(Path(args.output).resolve()),
        "contract": CONTRACT_NAME,
        "armature_name": armature.name,
        "bone_count": len(names),
        "mesh_count": len(meshes),
        "body_axis": body_axis,
        "landmark_fit": landmark_fit,
        "bounds": {
            "min": [float(value) for value in minimum],
            "max": [float(value) for value in maximum],
        },
        "joints": {
            name: [round(float(value), 7) for value in positions[name]] for name in names
        },
    }
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
