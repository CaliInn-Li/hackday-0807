import argparse
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--mapping", required=True)
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
# SkinTokens is an autoregressive rigging generator. Unlike Make-It-Animatable
# or Mixamo, its output topology is NOT guaranteed to be a standard 22-bone
# humanoid: bone count, chain depth, and left/right ordering all vary between
# samples. Blindly renaming bone_0..bone_21 to mixamorig:* therefore silently
# produces a broken rig (limbs mislabeled, 8-segment legs, duplicated arm
# chains, finger chains, left/right swapped).
#
# This analyzer derives the *geometric* topology from each bone's head/tail
# positions and parent links, then checks it against the expected humanoid
# structure. It rejects non-humanoid samples *before* any renaming, so a bad
# rig never propagates downstream into the GVHMR retarget stage.
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


def validate_humanoid(armature, diagnostic_path=None):
    """Run the topology gate. Return a diagnostic dict. Raise RuntimeError with
    a readable summary if the skeleton is not a standard 22-bone humanoid."""
    report = describe_topology(armature)
    _, problems = classify_chains(armature)

    # Structural checks independent of naming.
    if report["bone_count"] != 22:
        problems.append(
            f"bone count {report['bone_count']} != 22; "
            "SkinTokens produced a non-standard skeleton. Re-run the sampling "
            "(--use-transfer) until it yields a 22-bone humanoid, or fix the "
            "topology before semantic renaming."
        )
    if report["root_count"] != 1:
        problems.append(
            f"root count {report['root_count']} != 1; expected a single pelvis root."
        )

    diagnostic = {
        "armature": armature.name,
        "topology": report,
        "problems": sorted(set(problems)),
        "is_valid_humanoid": len(problems) == 0,
    }

    if diagnostic_path:
        path = Path(diagnostic_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(diagnostic, ensure_ascii=False, indent=2), encoding="utf-8")

    if problems:
        summary = "\n".join(f"  - {p}" for p in sorted(set(problems)))
        raise RuntimeError(
            "Skeleton is not a standard 22-bone humanoid; refusing to apply "
            "semantic mapping. Diagnostics:\n" + summary +
            ("\nFull report written to: " + str(diagnostic_path) if diagnostic_path else "")
        )

    return diagnostic


def reset_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for datablocks in (bpy.data.actions, bpy.data.cameras, bpy.data.lights):
        for datablock in list(datablocks):
            datablocks.remove(datablock)


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
    missing = sorted(set(mapping) - set(armature.data.bones.keys()))
    if missing:
        raise RuntimeError(f"Mapping references missing bones: {missing}")

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
    mapping = json.loads(Path(args.mapping).read_text(encoding="utf-8"))
    reset_scene()
    armature, meshes = import_character(args.input)

    # Topology gate: refuse to rename if the rig is not a standard 22-bone
    # humanoid. A bad SkinTokens sample would otherwise be silently mislabeled
    # and corrupt every downstream retarget stage.
    validate_humanoid(armature, diagnostic_path=args.diagnostic)

    rename_skeleton(armature, meshes, mapping)
    detach_skinned_mesh_roots(meshes)
    export_glb(args.clean_output, armature, meshes, animations=False)
    create_test_action(armature)
    export_glb(args.animated_output, armature, meshes, animations=True)
    camera, center, radius = setup_render(meshes)
    render_views(args.render_dir, camera, center, radius)
    print(
        json.dumps(
            {
                "bones": len(armature.data.bones),
                "meshes": len(meshes),
                "clean_output": str(Path(args.clean_output).resolve()),
                "animated_output": str(Path(args.animated_output).resolve()),
                "render_dir": str(Path(args.render_dir).resolve()),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
