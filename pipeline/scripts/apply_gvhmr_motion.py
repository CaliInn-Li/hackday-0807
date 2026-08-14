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


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--character", required=True)
    parser.add_argument("--motion", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report", required=True)
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


def load_character(path):
    bpy.ops.import_scene.gltf(filepath=str(Path(path).resolve()))
    armatures = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if len(armatures) != 1 or not meshes:
        raise RuntimeError(f"Expected 1 armature and >=1 mesh, got {len(armatures)} and {len(meshes)}")
    armature = armatures[0]
    missing = sorted(set(TARGET_TO_SMPL22) - set(armature.pose.bones.keys()))
    if missing:
        raise RuntimeError(f"Character is missing mapped bones: {missing}")
    return armature, meshes, glb_visual_height(path)


def local_rest_rotation(bone):
    if bone.parent:
        local = bone.parent.matrix_local.inverted() @ bone.matrix_local
    else:
        local = bone.matrix_local
    return local.to_3x3().normalized()


def mesh_points(meshes, visual_height):
    # For a glTF skinned mesh, node transforms are intentionally ignored by the
    # skinning equation. Blender may attach an import-only object scale while the
    # renderable POSITION data remains in the mesh-local bind space. Using raw
    # local positions therefore matches what glTF runtimes actually display.
    points = [vertex.co.copy() for mesh in meshes for vertex in mesh.data.vertices]
    raw_height = max(point.z for point in points) - min(point.z for point in points)
    scale = visual_height / raw_height
    return [point * scale for point in points]


def key_motion(armature, meshes, visual_height, motion, step):
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
    rest_rotations = {
        name: local_rest_rotation(armature.data.bones[name]) for name in TARGET_TO_SMPL22
    }

    root = armature.pose.bones["mixamorig:Hips"]
    root_rest = armature.data.bones["mixamorig:Hips"].matrix_local.to_3x3().normalized()
    translation_zero = translations[0].copy()

    for frame_index, (frame_rotations, translation) in enumerate(zip(rotations, translations), start=1):
        for target_name, source_index in TARGET_TO_SMPL22.items():
            source_rotation = frame_rotations[source_index]
            blender_rotation = coordinate @ source_rotation @ coordinate_inv
            rest = rest_rotations[target_name]
            basis = rest.inverted() @ Matrix(blender_rotation.tolist()) @ rest
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
        "mapped_bones": len(TARGET_TO_SMPL22),
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


def render_previews(preview_dir, meshes, visual_height, frames):
    preview_dir = Path(preview_dir)
    preview_dir.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
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

    camera_data = bpy.data.cameras.new("MotionPreviewCamera")
    camera = bpy.data.objects.new("MotionPreviewCamera", camera_data)
    bpy.context.collection.objects.link(camera)
    camera.data.lens = 52
    scene.camera = camera
    camera.location = center + Vector((radius * 2.8, -radius * 3.1, radius * 0.3))
    look_at(camera, center)

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

    for frame in frames:
        scene.frame_set(frame)
        scene.render.filepath = str((preview_dir / f"gvhmr_frame_{frame:04d}.png").resolve())
        bpy.ops.render.render(write_still=True)


def main():
    args = parse_args()
    reset_scene()
    armature, meshes, visual_height = load_character(args.character)
    motion = np.load(args.motion)
    report = key_motion(armature, meshes, visual_height, motion, max(1, args.step))
    export_glb(args.output, armature, meshes)
    if args.preview_dir:
        frames = sorted({1, max(1, report["frames"] // 3), max(1, 2 * report["frames"] // 3)})
        render_previews(args.preview_dir, meshes, visual_height, frames)
        report["preview_frames"] = frames
    report.update(
        {
            "character": str(Path(args.character).resolve()),
            "motion": str(Path(args.motion).resolve()),
            "output": str(Path(args.output).resolve()),
        }
    )
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
