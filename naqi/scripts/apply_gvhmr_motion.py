import argparse
import json
import math
import struct
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix, Vector


TARGET_TO_SMPL22 = {
    "mixamorig:Hips": 0,
    "mixamorig:Spine": 3,
    "mixamorig:Spine1": 6,
    "mixamorig:Spine2": 9,
    "mixamorig:Neck": 12,
    "mixamorig:Head": 15,
    "mixamorig:LeftShoulder": 13,
    "mixamorig:LeftArm": 16,
    "mixamorig:LeftForeArm": 18,
    "mixamorig:LeftHand": 20,
    "mixamorig:RightShoulder": 14,
    "mixamorig:RightArm": 17,
    "mixamorig:RightForeArm": 19,
    "mixamorig:RightHand": 21,
    "mixamorig:LeftUpLeg": 1,
    "mixamorig:LeftLeg": 4,
    "mixamorig:LeftFoot": 7,
    "mixamorig:LeftToeBase": 10,
    "mixamorig:RightUpLeg": 2,
    "mixamorig:RightLeg": 5,
    "mixamorig:RightFoot": 8,
    "mixamorig:RightToeBase": 11,
}

# Legacy SkinTokens rig output: anonymous bone order follows its Mixamo
# semantic order, not the SMPL22 joint order.
GENERIC_TO_SMPL22 = {
    "bone_0": 0,   # Hips
    "bone_1": 3,   # Spine
    "bone_2": 6,   # Spine1
    "bone_3": 9,   # Spine2
    "bone_4": 12,  # Neck
    "bone_5": 15,  # Head
    "bone_6": 13,  # LeftShoulder
    "bone_7": 16,  # LeftArm
    "bone_8": 18,  # LeftForeArm
    "bone_9": 20,  # LeftHand
    "bone_10": 14, # RightShoulder
    "bone_11": 17, # RightArm
    "bone_12": 19, # RightForeArm
    "bone_13": 21, # RightHand
    "bone_14": 1,  # LeftUpLeg
    "bone_15": 4,  # LeftLeg
    "bone_16": 7,  # LeftFoot
    "bone_17": 10, # LeftToeBase
    "bone_18": 2,  # RightUpLeg
    "bone_19": 5,  # RightLeg
    "bone_20": 8,  # RightFoot
    "bone_21": 11, # RightToeBase
}

# The canonical-SMPL test is exported by Blender in depth-first armature order
# rather than the SMPL index order. Its 24 bones are:
# pelvis, left leg chain, right leg chain, spine/head, left arm/hand,
# right arm/hand. The two hand bones have no separate rotations in the
# 22-joint GVHMR file and are intentionally left at their rest pose.
SMPL_DFS_TO_SMPL22 = {
    "bone_0": 0,   # Pelvis
    "bone_1": 1,   # L_Hip
    "bone_2": 4,   # L_Knee
    "bone_3": 7,   # L_Ankle
    "bone_4": 10,  # L_Foot
    "bone_5": 2,   # R_Hip
    "bone_6": 5,   # R_Knee
    "bone_7": 8,   # R_Ankle
    "bone_8": 11,  # R_Foot
    "bone_9": 3,   # Spine1
    "bone_10": 6,  # Spine2
    "bone_11": 9,  # Spine3
    "bone_12": 12, # Neck
    "bone_13": 15, # Head
    "bone_14": 13, # L_Collar
    "bone_15": 16, # L_Shoulder
    "bone_16": 18, # L_Elbow
    "bone_17": 20, # L_Wrist
    "bone_19": 14, # R_Collar
    "bone_20": 17, # R_Shoulder
    "bone_21": 19, # R_Elbow
    "bone_22": 21, # R_Wrist
}

# Parent indices for the 22 joints exported by extract_gvhmr_motion.py.
# GVHMR/SMPL body_pose values are local rotations.  They must be accumulated
# through this tree before they can be compared with a target bone's bind
# orientation.
SMPL22_PARENTS = [
    -1, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8,
    9, 9, 9, 12, 13, 14, 16, 17, 18, 19,
]


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--character", required=True)
    parser.add_argument("--motion", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument(
        "--mapping-json",
        help="Explicit topology-derived target-bone to SMPL-22 mapping JSON",
    )
    parser.add_argument("--preview-dir")
    parser.add_argument("--step", type=int, default=1, help="Keep every Nth motion frame")
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])


def reset_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for action in list(bpy.data.actions):
        bpy.data.actions.remove(action)


def glb_visual_height(path):
    data = Path(path).read_bytes()
    if data[:4] != b"glTF":
        raise ValueError("Character input must be a binary GLB")
    json_length, json_type = struct.unpack_from("<II", data, 12)
    if json_type != 0x4E4F534A:
        raise ValueError("First GLB chunk is not JSON")
    document = json.loads(data[20 : 20 + json_length].decode("utf-8").rstrip(" \x00"))
    y_min = math.inf
    y_max = -math.inf
    for mesh in document.get("meshes", []):
        for primitive in mesh.get("primitives", []):
            accessor_index = primitive.get("attributes", {}).get("POSITION")
            if accessor_index is None:
                continue
            accessor = document["accessors"][accessor_index]
            y_min = min(y_min, float(accessor["min"][1]))
            y_max = max(y_max, float(accessor["max"][1]))
    if not math.isfinite(y_min) or y_max <= y_min:
        raise ValueError("Unable to determine character height from GLB POSITION accessors")
    return y_max - y_min


def load_topology_mapping(path, armature):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    raw_mapping = payload.get("bone_to_smpl22")
    if not isinstance(raw_mapping, dict) or not raw_mapping:
        raise RuntimeError(f"Mapping JSON has no bone_to_smpl22 object: {path}")
    mapping = {}
    for bone_name, source_index in raw_mapping.items():
        if bone_name not in armature.pose.bones:
            raise RuntimeError(f"Mapping references missing target bone {bone_name!r}")
        source_index = int(source_index)
        if not 0 <= source_index < 22:
            raise RuntimeError(f"SMPL-22 index out of range for {bone_name!r}: {source_index}")
        mapping[bone_name] = source_index
    if len(set(mapping.values())) != len(mapping):
        raise RuntimeError(f"Mapping contains duplicate SMPL-22 indices: {path}")
    return mapping, payload


def load_character(path, mapping_path=None):
    bpy.ops.import_scene.gltf(filepath=str(Path(path).resolve()))
    armatures = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
    meshes = [
        obj
        for obj in bpy.context.scene.objects
        if obj.type == "MESH" and not obj.name.lower().startswith("icosphere")
    ]
    if len(armatures) != 1 or not meshes:
        raise RuntimeError(f"Expected 1 armature and >=1 mesh, got {len(armatures)} and {len(meshes)}")
    armature = armatures[0]
    if mapping_path:
        target_mapping, mapping_payload = load_topology_mapping(mapping_path, armature)
        return armature, meshes, glb_visual_height(path), target_mapping, mapping_payload
    bone_names = set(armature.pose.bones.keys())
    if set(TARGET_TO_SMPL22).issubset(bone_names):
        target_mapping = TARGET_TO_SMPL22
    elif (
        all(f"bone_{index}" in bone_names for index in range(24))
        and armature.data.bones["bone_5"].parent is not None
        and armature.data.bones["bone_5"].parent.name == "bone_0"
    ):
        target_mapping = SMPL_DFS_TO_SMPL22
    elif set(GENERIC_TO_SMPL22).issubset(bone_names):
        target_mapping = GENERIC_TO_SMPL22
    else:
        missing_mixamo = sorted(set(TARGET_TO_SMPL22) - bone_names)
        missing_generic = sorted(set(GENERIC_TO_SMPL22) - bone_names)
        raise RuntimeError(
            "Character is missing mapped bones; "
            f"missing mixamo={missing_mixamo}, missing generic={missing_generic}"
        )
    return armature, meshes, glb_visual_height(path), target_mapping, None


def local_rest_rotation(bone):
    if bone.parent:
        local = bone.parent.matrix_local.inverted() @ bone.matrix_local
    else:
        local = bone.matrix_local
    return local.to_3x3().normalized()


def global_rest_rotation(armature, bone):
    return armature.matrix_world.to_3x3() @ bone.matrix_local.to_3x3().normalized()


def mesh_points(meshes, visual_height):
    # For a glTF skinned mesh, node transforms are intentionally ignored by the
    # skinning equation. Blender may attach an import-only object scale while the
    # renderable POSITION data remains in the mesh-local bind space. Using raw
    # local positions therefore matches what glTF runtimes actually display.
    points = [vertex.co.copy() for mesh in meshes for vertex in mesh.data.vertices]
    raw_height = max(point.z for point in points) - min(point.z for point in points)
    scale = visual_height / raw_height
    return [point * scale for point in points]


def key_motion(armature, meshes, visual_height, motion, step, target_mapping):
    rotations = motion["rotations"][::step]
    translations = motion["translations"][::step]
    source_height = float(motion["source_height"])
    source_fps = float(motion["fps"])
    scale = visual_height / source_height

    scene = bpy.context.scene
    scene.render.fps = round(source_fps / step)
    scene.frame_start = 1
    scene.frame_end = len(rotations)
    action = bpy.data.actions.new("GVHMR_Action")
    armature.animation_data_create()
    armature.animation_data.action = action
    armature["motion_source"] = "GVHMR"
    armature["source_fps"] = source_fps
    armature["translation_scale"] = scale

    # GVHMR/SMPL-X: X right, Y up, Z forward. Blender: X right, Y back, Z up.
    coordinate = np.asarray(((1.0, 0.0, 0.0), (0.0, 0.0, -1.0), (0.0, 1.0, 0.0)))
    coordinate_inv = coordinate.T
    if rotations.shape[1] != len(SMPL22_PARENTS):
        raise RuntimeError(
            f"Expected {len(SMPL22_PARENTS)} SMPL-22 rotations, got {rotations.shape[1]}"
        )

    # Convert SMPL local rotations into global rotations before retargeting.
    # Treating body_pose[j] as a world rotation is the reason the earlier
    # implementation could leave a walking character with arms held sideways.
    source_global_rotations = np.empty_like(rotations)
    for source_index, parent_index in enumerate(SMPL22_PARENTS):
        if parent_index < 0:
            source_global_rotations[:, source_index] = rotations[:, source_index]
        else:
            source_global_rotations[:, source_index] = (
                source_global_rotations[:, parent_index] @ rotations[:, source_index]
            )

    target_bones = {name: armature.data.bones[name] for name in target_mapping}
    rest_globals = {
        name: global_rest_rotation(armature, bone) for name, bone in target_bones.items()
    }
    rest_locals = {}
    for name, bone in target_bones.items():
        parent_name = bone.parent.name if bone.parent else None
        parent_rest = rest_globals[parent_name] if parent_name in rest_globals else Matrix.Identity(3)
        rest_locals[name] = parent_rest.inverted() @ rest_globals[name]

    root_name = next(name for name, source_index in target_mapping.items() if source_index == 0)
    root = armature.pose.bones[root_name]
    root_rest = rest_globals[root_name]
    translation_zero = translations[0].copy()

    for frame_index, (frame_rotations, translation) in enumerate(zip(rotations, translations), start=1):
        frame_source_global = source_global_rotations[frame_index - 1]
        desired_globals = {}
        for target_name, source_index in target_mapping.items():
            source_global = coordinate @ frame_source_global[source_index] @ coordinate_inv
            desired_globals[target_name] = Matrix(source_global.tolist()) @ rest_globals[target_name]

        for target_name, source_index in target_mapping.items():
            target_bone = target_bones[target_name]
            parent_name = target_bone.parent.name if target_bone.parent else None
            parent_desired = (
                desired_globals[parent_name]
                if parent_name in desired_globals
                else Matrix.Identity(3)
            )
            desired_local = parent_desired.inverted() @ desired_globals[target_name]
            basis = rest_locals[target_name].inverted() @ desired_local
            pose_bone = armature.pose.bones[target_name]
            pose_bone.rotation_mode = "QUATERNION"
            pose_bone.rotation_quaternion = basis.to_quaternion().normalized()
            pose_bone.keyframe_insert(data_path="rotation_quaternion", frame=frame_index)

        displacement = coordinate @ (translation - translation_zero)
        # PoseBone.location is expressed in the root bone's rest coordinate frame.
        root.location = root_rest.inverted() @ Vector((displacement * scale).tolist())
        root.keyframe_insert(data_path="location", frame=frame_index)

    scene.frame_set(1)
    return {
        "frames": len(rotations),
        "fps": scene.render.fps,
        "duration_seconds": round(len(rotations) / scene.render.fps, 3),
        "target_height": round(visual_height, 7),
        "source_height": round(source_height, 7),
        "translation_scale": round(scale, 7),
        "mapped_bones": len(target_mapping),
        "target_bone_names": list(target_mapping),
        "rotation_transfer": "SMPL-22 local rotations -> SMPL global rotations -> target bind-relative local rotations",
    }


def export_glb(path, armature, meshes):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    for mesh in meshes:
        world = mesh.matrix_world.copy()
        mesh.parent = None
        mesh.matrix_world = world
    bpy.ops.object.select_all(action="DESELECT")
    armature.select_set(True)
    for mesh in meshes:
        mesh.select_set(True)
    bpy.context.view_layer.objects.active = armature
    bpy.ops.export_scene.gltf(
        filepath=str(path.resolve()),
        export_format="GLB",
        use_selection=True,
        export_skins=True,
        export_animations=True,
        export_morph=False,
        export_yup=True,
    )


def look_at(obj, target):
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()


def configure_cycles_gpu(scene):
    preferences = bpy.context.preferences.addons["cycles"].preferences
    for device_type in ("CUDA", "OPTIX"):
        try:
            preferences.compute_device_type = device_type
            preferences.get_devices()
            enabled = []
            for device in preferences.devices:
                device.use = device.type != "CPU"
                if device.use:
                    enabled.append(device.name)
            if enabled:
                scene.cycles.device = "GPU"
                return {"backend": device_type, "devices": enabled}
        except Exception:
            continue
    scene.cycles.device = "CPU"
    return {"backend": "CPU", "devices": []}


def render_previews(preview_dir, armature, meshes, visual_height, frames, root_name):
    preview_dir = Path(preview_dir)
    preview_dir.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    cycles_device = configure_cycles_gpu(scene)
    scene.cycles.samples = 20
    scene.cycles.use_denoising = True
    scene.render.resolution_x = 640
    scene.render.resolution_y = 640
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.world.color = (0.035, 0.035, 0.045)

    points = mesh_points(meshes, visual_height)
    mins = Vector((min(p.x for p in points), min(p.y for p in points), min(p.z for p in points)))
    maxs = Vector((max(p.x for p in points), max(p.y for p in points), max(p.z for p in points)))
    center = (mins + maxs) / 2
    radius = max(maxs - mins) * 0.75

    current_frame = scene.frame_current
    root_positions = []
    for frame in range(scene.frame_start, scene.frame_end + 1):
        scene.frame_set(frame)
        root_positions.append(armature.matrix_world @ armature.pose.bones[root_name].head)
    scene.frame_set(current_frame)
    root_origin = root_positions[0]

    camera_data = bpy.data.cameras.new("MotionPreviewCamera")
    camera = bpy.data.objects.new("MotionPreviewCamera", camera_data)
    bpy.context.collection.objects.link(camera)
    camera.data.lens = 52
    scene.camera = camera
    camera.location = center + Vector((radius * 2.8, -radius * 3.1, radius * 0.3))
    look_at(camera, center)
    base_camera_location = camera.location.copy()

    lights = []
    for name, energy, offset in (
        ("MotionKey", 80, Vector((radius * 2, -radius * 3, radius * 3))),
        ("MotionFill", 35, Vector((-radius * 2, -radius, radius))),
        ("MotionRim", 55, Vector((radius, radius * 2, radius * 2))),
    ):
        data = bpy.data.lights.new(name, "AREA")
        data.energy = energy
        data.size = radius * 2
        light = bpy.data.objects.new(name, data)
        bpy.context.collection.objects.link(light)
        light.location = center + offset
        look_at(light, center)
        lights.append((light, light.location.copy()))

    for frame in frames:
        scene.frame_set(frame)
        root_delta = root_positions[frame - scene.frame_start] - root_origin
        target = center + root_delta
        camera.location = base_camera_location + root_delta
        look_at(camera, target)
        for light, base_location in lights:
            light.location = base_location + root_delta
            look_at(light, target)
        scene.render.filepath = str((preview_dir / f"gvhmr_frame_{frame:04d}.png").resolve())
        bpy.ops.render.render(write_still=True)
    return cycles_device


def main():
    args = parse_args()
    reset_scene()
    armature, meshes, visual_height, target_mapping, mapping_payload = load_character(
        args.character, args.mapping_json
    )
    motion = np.load(args.motion)
    report = key_motion(
        armature,
        meshes,
        visual_height,
        motion,
        max(1, args.step),
        target_mapping,
    )
    export_glb(args.output, armature, meshes)
    if args.preview_dir:
        frames = sorted({1, max(1, report["frames"] // 3), max(1, 2 * report["frames"] // 3)})
        root_name = next(name for name, source_index in target_mapping.items() if source_index == 0)
        report["preview_cycles"] = render_previews(
            args.preview_dir, armature, meshes, visual_height, frames, root_name
        )
        report["preview_frames"] = frames
        report["preview_camera"] = "follow_root"
    report.update(
        {
            "character": str(Path(args.character).resolve()),
            "motion": str(Path(args.motion).resolve()),
            "output": str(Path(args.output).resolve()),
        }
    )
    if args.mapping_json:
        report["mapping_json"] = str(Path(args.mapping_json).resolve())
        report["mapping_coordinate_note"] = mapping_payload.get("coordinate_note")
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
