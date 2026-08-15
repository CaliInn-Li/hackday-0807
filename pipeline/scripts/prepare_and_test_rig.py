import argparse
import json
import math
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
    SMPL22_TARGET_PARENTS,
    match_to_reference,
)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument(
        "--reference-skeleton",
        required=True,
        help="Stage-1A semantic SMPL-22 skeleton used to identify generated joint names.",
    )
    parser.add_argument("--clean-output", required=True)
    parser.add_argument("--animated-output", required=True)
    parser.add_argument("--render-dir", required=True)
    parser.add_argument("--diagnostic", required=False, default=None,
                        help="Optional JSON path for the skeleton topology diagnostic.")
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])


# ---------------------------------------------------------------------------
# Skeleton topology gate
# ---------------------------------------------------------------------------
#
# Stage 1 supplies a fixed SMPL-22 skeleton and asks SkinTokens to generate
# weights only. This stage proves that SkinTokens preserved the exact graph and
# joint geometry before any semantic rename or animation is allowed.
#
# Coordinate convention observed in SkinTokens output: Z up, X left/right,
# Y depth (tail of a directional chain descends in +Y for legs).

# Expected Mixamo-22 semantics, in order of the config mapping keys.
EXPECTED_CHAIN = {
    # (semantic name, expected parent, approximate straight-line direction)
    "mixamorig:Hips":         (None,   (0, 0, 1)),
    "mixamorig:Spine":        ("mixamorig:Hips",         (0, 0, 1)),
    "mixamorig:Spine1":       ("mixamorig:Spine",        (0, 0, 1)),
    "mixamorig:Spine2":       ("mixamorig:Spine1",       (0, 0, 1)),
    "mixamorig:Neck":         ("mixamorig:Spine2",       (0, 0, 1)),
    "mixamorig:Head":         ("mixamorig:Neck",         (0, 0, 1)),
    "mixamorig:LeftShoulder": ("mixamorig:Spine2",      (-1, 0, 0)),
    "mixamorig:LeftArm":      ("mixamorig:LeftShoulder", (-1, 0, 0)),
    "mixamorig:LeftForeArm":  ("mixamorig:LeftArm",      (-1, 0, 0)),
    "mixamorig:LeftHand":     ("mixamorig:LeftForeArm",  (-1, 0, 0)),
    "mixamorig:RightShoulder": ("mixamorig:Spine2",      (1, 0, 0)),
    "mixamorig:RightArm":     ("mixamorig:RightShoulder", (1, 0, 0)),
    "mixamorig:RightForeArm": ("mixamorig:RightArm",      (1, 0, 0)),
    "mixamorig:RightHand":    ("mixamorig:RightForeArm",  (1, 0, 0)),
    "mixamorig:LeftUpLeg":    ("mixamorig:Hips",         (0, 1, -1)),
    "mixamorig:LeftLeg":      ("mixamorig:LeftUpLeg",    (0, 1, -1)),
    "mixamorig:LeftFoot":     ("mixamorig:LeftLeg",      (0, 1, 0)),
    "mixamorig:LeftToeBase":  ("mixamorig:LeftFoot",     (0, 1, 0)),
    "mixamorig:RightUpLeg":   ("mixamorig:Hips",         (0, 1, -1)),
    "mixamorig:RightLeg":     ("mixamorig:RightUpLeg",   (0, 1, -1)),
    "mixamorig:RightFoot":    ("mixamorig:RightLeg",     (0, 1, 0)),
    "mixamorig:RightToeBase": ("mixamorig:RightFoot",    (0, 1, 0)),
}


def bone_direction(bone):
    """Unit vector from head to tail in the armature's rest space."""
    direction = Vector(bone.tail_local) - Vector(bone.head_local)
    if direction.length < 1e-8:
        return Vector((0, 0, 0))
    return direction.normalized()


def child_chains(bone, bones_by_parent):
    """Return list of chains (each a list of bone names) rooted at this bone's
    children, following the single-child path until a leaf or a fork."""
    chains = []
    for child_name in bones_by_parent.get(bone.name, []):
        chain = [child_name]
        current = child_name
        while True:
            children = bones_by_parent.get(current, [])
            if len(children) != 1:
                break
            nxt = children[0]
            chain.append(nxt)
            current = nxt
        chains.append(chain)
    return chains


def describe_topology(armature):
    """Return a dict describing the inferred geometric topology."""
    bones = {b.name: b for b in armature.data.bones}
    bones_by_parent = {}
    for b in armature.data.bones:
        bones_by_parent.setdefault(b.parent.name if b.parent else None, []).append(b.name)

    roots = [b.name for b in armature.data.bones if b.parent is None]

    report = {
        "bone_count": len(bones),
        "root_count": len(roots),
        "roots": roots,
        "bones": [],
    }

    for b in armature.data.bones:
        direction = bone_direction(b)
        report["bones"].append({
            "name": b.name,
            "parent": b.parent.name if b.parent else None,
            "head": [round(v, 6) for v in b.head_local],
            "tail": [round(v, 6) for v in b.tail_local],
            "length": round(b.length, 6),
            "direction": [round(v, 4) for v in direction],
            "children": sorted(bones_by_parent.get(b.name, [])),
        })

    # Chain analysis: for each root, enumerate direct child chains.
    chains = []
    for root in roots:
        for chain in child_chains(bones[root], bones_by_parent):
            chains.append({"root": root, "chain": chain, "depth": len(chain)})
    report["root_chains"] = chains
    return report


def leaf_chains(bones, bones_by_parent):
    """Enumerate every root-to-leaf path, yielding (path, terminal_depth) where
    `path` is a list of bpy bone objects (root first, leaf last).

    `terminal_depth` counts segments *after* the last fork (a fork owns two or
    more children), which isolates the length of the limb (arm/leg/fingers)
    from the shared torso chain above it. This avoids flagging a legitimate
    humanoid whose root-to-leaf path necessarily includes the pelvis + spine.
    `bones_by_parent` maps a parent bone *name* to a list of child bone *names*.
    """
    roots = [b for b in bones.values() if b.parent is None]
    results = []
    for root in roots:
        def walk(bone, path, post_fork_depth):
            children = [bones[n] for n in bones_by_parent.get(bone.name, [])]
            if not children:
                results.append((path, post_fork_depth))
                return
            # A fork means the shared chain ends; reset the limb counter.
            next_depth = 1 if len(children) > 1 else post_fork_depth + 1
            for child in children:
                walk(child, path + [child], next_depth)
        walk(root, [root], 0)
    return results


def _classify_path(path):
    head = Vector(path[0].head_local)
    tip = Vector(path[-1].tail_local)
    delta = tip - head
    length = delta.length
    if length < 1e-8:
        return ("degenerate", 0.0)
    z_component = delta.z / length
    x_component = delta.x / length
    y_component = delta.y / length
    if z_component > 0.6:
        kind = "torso"
    elif x_component > 0.5 or x_component < -0.5:
        kind = "arm"
    elif z_component < -0.3 and abs(y_component) > 0.3:
        kind = "leg"
    else:
        kind = "other"
    return (kind, length)


def classify_chains(armature):
    """Classify all root-to-leaf chains and flag structural anomalies."""
    bones = {b.name: b for b in armature.data.bones}
    bones_by_parent = {}
    for b in armature.data.bones:
        bones_by_parent.setdefault(b.parent.name if b.parent else None, []).append(b.name)

    roots = [b.name for b in armature.data.bones if b.parent is None]
    problems = []

    if len(roots) != 1:
        problems.append(f"expected exactly 1 root bone, found {len(roots)}: {roots}")
    if len(bones) != 22:
        problems.append(f"expected 22 bones (standard Mixamo humanoid), found {len(bones)}")
    if roots:
        paths = leaf_chains(bones, bones_by_parent)
        report_chains = []
        for path, terminal_depth in paths:
            kind, length = _classify_path(path)
            report_chains.append({
                "chain": [b.name for b in path],
                "depth": len(path),
                "terminal_depth": terminal_depth,
                "kind": kind,
                "length": round(length, 4),
            })
            # The shared torso chain is ignored for limb-depth checks; only the
            # terminal limb segment (after the last fork) is measured.
            if kind == "leg" and terminal_depth > 4:
                problems.append(
                    f"leg limb {'/'.join(b.name for b in path[-terminal_depth:])} has "
                    f"{terminal_depth} segments (humanoid leg should be <=4: "
                    "UpLeg->Leg->Foot->ToeBase)."
                )
            if kind == "arm" and terminal_depth > 4:
                problems.append(
                    f"arm limb {'/'.join(b.name for b in path[-terminal_depth:])} has "
                    f"{terminal_depth} segments (humanoid arm should be <=4: "
                    "Shoulder->Arm->ForeArm->Hand)."
                )
        return {"root": roots[0], "chains": report_chains, "problems": problems}, problems

    return {"bone_count": len(bones), "problems": problems}, problems


def validate_semantic_geometry(armature, raw_to_semantic):
    semantic_to_actual = {semantic: actual for actual, semantic in raw_to_semantic.items()}
    bones = {
        semantic: armature.data.bones[actual]
        for semantic, actual in semantic_to_actual.items()
    }
    hips = bones["mixamorig:Hips"].head_local
    head = bones["mixamorig:Head"].head_local
    height = max(abs(head.z - hips.z), 1e-6)
    tolerance = height * 0.01
    problems = []
    if head.z <= hips.z + tolerance:
        problems.append("Head must be above Hips in Blender Z-up coordinates")
    for suffix in ("Shoulder", "Arm", "ForeArm", "Hand", "UpLeg", "Leg", "Foot", "ToeBase"):
        left = bones[f"mixamorig:Left{suffix}"].head_local
        right = bones[f"mixamorig:Right{suffix}"].head_local
        if left.x <= hips.x + tolerance:
            problems.append(f"Left{suffix} must lie on the +X side of Hips")
        if right.x >= hips.x - tolerance:
            problems.append(f"Right{suffix} must lie on the -X side of Hips")
    for side in ("Left", "Right"):
        if bones[f"mixamorig:{side}Foot"].head_local.z >= hips.z:
            problems.append(f"{side}Foot must be below Hips")
    return problems


def validate_humanoid(armature, reference_positions, diagnostic_path=None):
    """Prove the generated armature still satisfies the fixed SMPL-22 contract."""
    report = describe_topology(armature)
    chain_report, chain_problems = classify_chains(armature)
    bone_names = [bone.name for bone in armature.data.bones]
    parent_by_name = {
        bone.name: bone.parent.name if bone.parent else None
        for bone in armature.data.bones
    }
    effective_mapping, metrics, contract_problems = match_to_reference(
        bone_names,
        parent_by_name,
        {bone.name: list(map(float, bone.head_local)) for bone in armature.data.bones},
        reference_positions,
    )
    problems = list(chain_problems) + list(contract_problems)
    if effective_mapping and set(effective_mapping) == set(bone_names):
        problems.extend(validate_semantic_geometry(armature, effective_mapping))
    if report["bone_count"] != 22:
        problems.append(
            f"bone count {report['bone_count']} != 22; SkinTokens did not preserve "
            "the fixed --use-skeleton input"
        )
    if report["root_count"] != 1:
        problems.append(f"root count {report['root_count']} != 1")

    semantic_parents = {}
    if effective_mapping:
        for name, semantic in effective_mapping.items():
            parent = parent_by_name[name]
            semantic_parents[semantic] = None if parent is None else effective_mapping[parent]
        for semantic, expected_parent in SMPL22_TARGET_PARENTS.items():
            if semantic_parents.get(semantic) != expected_parent:
                problems.append(
                    f"{semantic} parent must be {expected_parent!r}, "
                    f"found {semantic_parents.get(semantic)!r}"
                )

    diagnostic = {
        "armature": armature.name,
        "contract": CONTRACT_NAME,
        "generated_to_semantic": effective_mapping,
        "reference_match": metrics,
        "semantic_parents": semantic_parents,
        "topology": report,
        "chain_analysis": chain_report,
        "problems": sorted(set(problems)),
        "is_valid_humanoid": not problems,
    }
    if diagnostic_path:
        path = Path(diagnostic_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(diagnostic, ensure_ascii=False, indent=2), encoding="utf-8")
    if problems:
        summary = "\n".join(f"  - {problem}" for problem in sorted(set(problems)))
        raise RuntimeError(
            f"Skeleton violates fixed {CONTRACT_NAME}; refusing to continue:\n{summary}"
        )
    return diagnostic, effective_mapping


def reset_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for datablocks in (bpy.data.actions, bpy.data.cameras, bpy.data.lights):
        for datablock in list(datablocks):
            datablocks.remove(datablock)


def load_reference_skeleton(path):
    reset_scene()
    bpy.ops.import_scene.gltf(filepath=str(Path(path).resolve()))
    armatures = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
    if len(armatures) != 1:
        raise RuntimeError(
            f"Reference SMPL-22 GLB must contain one armature, found {len(armatures)}"
        )
    armature = armatures[0]
    names = set(armature.data.bones.keys())
    if names != set(SMPL22_TARGET_PARENTS):
        raise RuntimeError("Reference GLB does not contain the semantic SMPL-22 target names")
    parents = {
        bone.name: bone.parent.name if bone.parent else None
        for bone in armature.data.bones
    }
    if parents != SMPL22_TARGET_PARENTS:
        raise RuntimeError("Reference GLB parent graph violates the SMPL-22 contract")
    return {
        bone.name: [float(value) for value in bone.head_local]
        for bone in armature.data.bones
    }


def import_character(path):
    bpy.ops.import_scene.gltf(filepath=str(Path(path).resolve()))
    armatures = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
    if len(armatures) != 1:
        raise RuntimeError(f"Expected one armature, got {len(armatures)}")
    armature = armatures[0]

    skinned_meshes = {
        obj
        for obj in bpy.context.scene.objects
        if obj.type == "MESH"
        and (
            obj.parent == armature
            or any(mod.type == "ARMATURE" and mod.object == armature for mod in obj.modifiers)
        )
    }
    if not skinned_meshes:
        raise RuntimeError("No skinned mesh found")

    for obj in list(bpy.context.scene.objects):
        if obj.type == "MESH" and obj not in skinned_meshes:
            bpy.data.objects.remove(obj, do_unlink=True)
    return armature, sorted(skinned_meshes, key=lambda obj: obj.name)


def rename_skeleton(armature, meshes, mapping):
    actual = set(armature.data.bones.keys())
    if actual == set(mapping.values()):
        pass
    elif actual != set(mapping):
        raise RuntimeError(
            "Armature names match neither the generated names nor semantic SMPL-22 names"
        )
    else:
        # Renaming deform bones also renames their matching vertex groups.
        for old_name, new_name in mapping.items():
            armature.data.bones[old_name].name = new_name

    expected = set(mapping.values())
    actual = set(armature.data.bones.keys())
    if not expected.issubset(actual):
        raise RuntimeError("Bone rename did not complete")
    for mesh in meshes:
        mesh.name = "CharacterMesh"
        mesh.data.name = "CharacterMesh"
    armature.name = "CharacterRig"
    armature.data.name = "CharacterRig"


def repair_bone_tails(armature):
    """Repair SkinTokens leaf tails and make target rest axes deterministic."""
    bpy.ops.object.select_all(action="DESELECT")
    armature.select_set(True)
    bpy.context.view_layer.objects.active = armature
    bpy.ops.object.mode_set(mode="EDIT")
    bones = armature.data.edit_bones
    body_height = max(
        bones["mixamorig:Head"].head.z - bones["mixamorig:Hips"].head.z,
        1e-5,
    )
    for name, parent in SMPL22_TARGET_PARENTS.items():
        bone = bones[name]
        child = PREFERRED_TAIL_CHILD.get(name)
        if child:
            bone.tail = bones[child].head
        elif parent:
            direction = bone.head - bones[parent].head
            if direction.length < body_height * 1e-4:
                direction = Vector((0, 0, 1))
            bone.tail = bone.head + direction.normalized() * max(body_height * 0.04, 1e-5)
        bone.roll = 0.0
    bpy.ops.object.mode_set(mode="OBJECT")


def validate_skin_weights(armature, meshes):
    expected = set(SMPL22_TARGET_PARENTS)
    influenced_bones = set()
    problems = []
    world_vertices = [
        (mesh, vertex, mesh.matrix_world @ vertex.co)
        for mesh in meshes
        for vertex in mesh.data.vertices
    ]
    minimum = Vector(tuple(min(item[2][axis] for item in world_vertices) for axis in range(3)))
    maximum = Vector(tuple(max(item[2][axis] for item in world_vertices) for axis in range(3)))
    height = max(maximum.z - minimum.z, 1e-6)
    weighted_sums = {name: Vector((0, 0, 0)) for name in expected}
    weight_totals = {name: 0.0 for name in expected}
    summary = {"meshes": [], "influenced_bones": [], "joint_weight_fit": {}}
    for mesh in meshes:
        group_names = {group.index: group.name for group in mesh.vertex_groups}
        unexpected = sorted(set(group_names.values()) - expected)
        if unexpected:
            problems.append(f"mesh {mesh.name} has unexpected vertex groups: {unexpected}")
        unweighted = 0
        max_influences = 0
        invalid_sum = 0
        for vertex in mesh.data.vertices:
            positive = [entry for entry in vertex.groups if entry.weight > 1e-8]
            total = sum(entry.weight for entry in positive)
            if not positive:
                unweighted += 1
                continue
            max_influences = max(max_influences, len(positive))
            if len(positive) > 4:
                problems.append(
                    f"mesh {mesh.name} vertex {vertex.index} has {len(positive)} influences; max is 4"
                )
                break
            if abs(total - 1.0) > 1e-3:
                invalid_sum += 1
            world_position = mesh.matrix_world @ vertex.co
            for entry in positive:
                name = group_names[entry.group]
                influenced_bones.add(name)
                if name in weighted_sums:
                    weighted_sums[name] += world_position * entry.weight
                    weight_totals[name] += entry.weight
        if unweighted:
            problems.append(f"mesh {mesh.name} has {unweighted} unweighted vertices")
        if invalid_sum:
            problems.append(f"mesh {mesh.name} has {invalid_sum} non-normalized vertices")
        summary["meshes"].append(
            {
                "name": mesh.name,
                "vertices": len(mesh.data.vertices),
                "unweighted_vertices": unweighted,
                "max_influences": max_influences,
                "invalid_weight_sums": invalid_sum,
            }
        )
    missing = sorted(expected - influenced_bones)
    if missing:
        problems.append(f"semantic bones with no positive skin influence: {missing}")
    summary["influenced_bones"] = sorted(influenced_bones)

    margin = height * 0.08
    centroids = {}
    for name in sorted(expected):
        if weight_totals[name] <= 1e-8:
            continue
        centroid = weighted_sums[name] / weight_totals[name]
        centroids[name] = centroid
        head = armature.matrix_world @ armature.data.bones[name].head_local
        normalized_distance = (centroid - head).length / height
        inside_expanded_bounds = all(
            minimum[axis] - margin <= head[axis] <= maximum[axis] + margin
            for axis in range(3)
        )
        summary["joint_weight_fit"][name] = {
            "bone_head": [round(float(value), 7) for value in head],
            "weighted_centroid": [round(float(value), 7) for value in centroid],
            "normalized_distance": round(float(normalized_distance), 6),
            "inside_expanded_mesh_bounds": inside_expanded_bounds,
        }
        if not inside_expanded_bounds:
            problems.append(f"{name} head lies outside the mesh bounds")
        if normalized_distance > 0.35:
            problems.append(
                f"{name} is too far from its weighted vertices: {normalized_distance:.3f} body heights"
            )

    hips_x = (armature.matrix_world @ armature.data.bones["mixamorig:Hips"].head_local).x
    side_tolerance = height * 0.01
    for suffix in ("Shoulder", "Arm", "ForeArm", "Hand", "UpLeg", "Leg", "Foot", "ToeBase"):
        left_name = f"mixamorig:Left{suffix}"
        right_name = f"mixamorig:Right{suffix}"
        if left_name in centroids and centroids[left_name].x <= hips_x - side_tolerance:
            problems.append(f"{left_name} weights are not on the +X character-left side")
        if right_name in centroids and centroids[right_name].x >= hips_x + side_tolerance:
            problems.append(f"{right_name} weights are not on the -X character-right side")
    if problems:
        raise RuntimeError("Skin weight contract failed:\n  - " + "\n  - ".join(problems))
    return summary


def detach_skinned_mesh_roots(meshes):
    # glTF skinning already references the armature through the modifier. Keeping
    # the mesh parented to the armature produces NODE_SKINNED_MESH_NON_ROOT and
    # makes parent transforms implementation-dependent in some runtimes.
    for mesh in meshes:
        world = mesh.matrix_world.copy()
        mesh.parent = None
        mesh.matrix_world = world


def select_character(armature, meshes):
    bpy.ops.object.select_all(action="DESELECT")
    armature.select_set(True)
    for mesh in meshes:
        mesh.select_set(True)
    bpy.context.view_layer.objects.active = armature


def export_glb(path, armature, meshes, animations):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    select_character(armature, meshes)
    bpy.ops.export_scene.gltf(
        filepath=str(path.resolve()),
        export_format="GLB",
        use_selection=True,
        export_skins=True,
        export_animations=animations,
        export_morph=False,
        export_yup=True,
    )


def key_rotation(pose_bone, frame, xyz_degrees):
    pose_bone.rotation_mode = "XYZ"
    pose_bone.rotation_euler = [math.radians(value) for value in xyz_degrees]
    pose_bone.keyframe_insert(data_path="rotation_euler", frame=frame)


def create_test_action(armature):
    scene = bpy.context.scene
    scene.render.fps = 30
    scene.frame_start = 1
    scene.frame_end = 90
    action = bpy.data.actions.new("RigStressTest")
    armature.animation_data_create()
    armature.animation_data.action = action

    controlled = {
        "mixamorig:LeftArm": [(1, (0, 0, 0)), (25, (0, 0, -30)), (50, (15, 0, 22)), (75, (0, 0, 0))],
        "mixamorig:LeftForeArm": [(1, (0, 0, 0)), (25, (40, 0, 0)), (50, (-25, 0, 0)), (75, (0, 0, 0))],
        "mixamorig:RightArm": [(1, (0, 0, 0)), (25, (0, 0, 30)), (50, (-15, 0, -22)), (75, (0, 0, 0))],
        "mixamorig:RightForeArm": [(1, (0, 0, 0)), (25, (-40, 0, 0)), (50, (25, 0, 0)), (75, (0, 0, 0))],
        "mixamorig:LeftUpLeg": [(1, (0, 0, 0)), (25, (-15, 0, 4)), (50, (10, 0, 0)), (75, (0, 0, 0))],
        "mixamorig:LeftLeg": [(1, (0, 0, 0)), (25, (28, 0, 0)), (50, (-12, 0, 0)), (75, (0, 0, 0))],
        "mixamorig:RightUpLeg": [(1, (0, 0, 0)), (25, (10, 0, -4)), (50, (-15, 0, 0)), (75, (0, 0, 0))],
        "mixamorig:RightLeg": [(1, (0, 0, 0)), (25, (-12, 0, 0)), (50, (28, 0, 0)), (75, (0, 0, 0))],
        "mixamorig:Spine2": [(1, (0, 0, 0)), (25, (0, 0, 8)), (50, (0, 0, -8)), (75, (0, 0, 0))],
    }
    for bone_name, keys in controlled.items():
        pose_bone = armature.pose.bones[bone_name]
        for frame, rotation in keys:
            key_rotation(pose_bone, frame, rotation)

    for curve in action.fcurves:
        for keyframe in curve.keyframe_points:
            keyframe.interpolation = "BEZIER"
    scene.frame_set(25)


def mesh_bounds(meshes):
    corners = [mesh.matrix_world @ Vector(corner) for mesh in meshes for corner in mesh.bound_box]
    mins = Vector((min(v.x for v in corners), min(v.y for v in corners), min(v.z for v in corners)))
    maxs = Vector((max(v.x for v in corners), max(v.y for v in corners), max(v.z for v in corners)))
    return (mins + maxs) / 2, maxs - mins


def look_at(obj, target):
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()


def enable_gpu_rendering():
    # NVIDIA OptiX (RTX 5090 / Blackwell needs Blender 4.3+).
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "OPTIX"
    prefs.get_devices()
    fallback = None
    for device in prefs.devices:
        if device.type == "OPTIX":
            device.use = True
            fallback = device
        elif device.type == "CUDA":
            fallback = fallback or device
    if not any(d.use and d.type == "OPTIX" for d in prefs.devices) and fallback is not None:
        fallback.use = True
    for scene_obj in bpy.data.scenes:
        scene_obj.cycles.device = "GPU"


def setup_render(meshes):
    scene = bpy.context.scene
    enable_gpu_rendering()
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 24
    scene.cycles.use_denoising = True
    scene.render.resolution_x = 640
    scene.render.resolution_y = 640
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    scene.world.color = (0.035, 0.035, 0.045)

    center, extent = mesh_bounds(meshes)
    radius = max(extent) * 0.75
    camera_data = bpy.data.cameras.new("PreviewCamera")
    camera = bpy.data.objects.new("PreviewCamera", camera_data)
    bpy.context.collection.objects.link(camera)
    camera.data.lens = 52
    scene.camera = camera

    for name, energy, size, offset in (
        ("Key", 80, radius * 2.5, Vector((radius * 2, -radius * 3, radius * 3))),
        ("Fill", 35, radius * 2.0, Vector((-radius * 2, -radius, radius))),
        ("Rim", 55, radius * 1.5, Vector((radius, radius * 2, radius * 2))),
    ):
        light_data = bpy.data.lights.new(name, "AREA")
        light_data.energy = energy
        light_data.shape = "DISK"
        light_data.size = max(size, 0.01)
        light = bpy.data.objects.new(name, light_data)
        bpy.context.collection.objects.link(light)
        light.location = center + offset
        look_at(light, center)
    return camera, center, max(radius, 0.05)


def render_views(render_dir, camera, center, radius):
    render_dir = Path(render_dir)
    render_dir.mkdir(parents=True, exist_ok=True)
    views = {
        "front": Vector((0, -radius * 4.2, radius * 0.25)),
        "back": Vector((0, radius * 4.2, radius * 0.25)),
        "left": Vector((-radius * 4.2, 0, radius * 0.25)),
        "three_quarter": Vector((radius * 2.8, -radius * 3.1, radius * 0.3)),
    }
    for name, offset in views.items():
        camera.location = center + offset
        look_at(camera, center)
        bpy.context.scene.render.filepath = str((render_dir / f"rig_test_{name}.png").resolve())
        bpy.ops.render.render(write_still=True)


def main():
    args = parse_args()
    reference_positions = load_reference_skeleton(args.reference_skeleton)
    reset_scene()
    armature, meshes = import_character(args.input)

    diagnostic, effective_mapping = validate_humanoid(
        armature,
        reference_positions=reference_positions,
        diagnostic_path=args.diagnostic,
    )
    rename_skeleton(armature, meshes, effective_mapping)
    repair_bone_tails(armature)
    weight_report = validate_skin_weights(armature, meshes)
    diagnostic["skin_weights"] = weight_report
    if args.diagnostic:
        Path(args.diagnostic).write_text(
            json.dumps(diagnostic, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    detach_skinned_mesh_roots(meshes)
    export_glb(args.clean_output, armature, meshes, animations=False)
    create_test_action(armature)
    export_glb(args.animated_output, armature, meshes, animations=True)
    camera, center, radius = setup_render(meshes)
    render_views(args.render_dir, camera, center, radius)
    print(
        json.dumps(
            {
                "contract": CONTRACT_NAME,
                "bones": len(armature.data.bones),
                "meshes": len(meshes),
                "skin_weights": weight_report,
                "clean_output": str(Path(args.clean_output).resolve()),
                "animated_output": str(Path(args.animated_output).resolve()),
                "render_dir": str(Path(args.render_dir).resolve()),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
