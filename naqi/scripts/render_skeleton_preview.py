import argparse
import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--fps", type=float, default=24.0)
    parser.add_argument("--resolution", type=int, default=480)
    parser.add_argument("--color", default="0.18,0.72,1.0")
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])


def reset_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for action in list(bpy.data.actions):
        bpy.data.actions.remove(action)


def look_at(obj, target):
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()


def material(name, color):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*color, 1.0)
    mat.use_nodes = True
    principled = mat.node_tree.nodes.get("Principled BSDF")
    principled.inputs["Base Color"].default_value = (*color, 1.0)
    principled.inputs["Roughness"].default_value = 0.52
    return mat


def parse_color(value):
    values = [float(part.strip()) for part in value.split(",")]
    if len(values) != 3:
        raise ValueError("--color must contain three comma-separated numbers")
    return tuple(values)


def make_cylinder(name, start, end, radius, mat):
    direction = end - start
    length = max(direction.length, 1e-4)
    bpy.ops.mesh.primitive_cylinder_add(vertices=8, radius=radius, depth=1.0, location=(start + end) / 2)
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(mat)
    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = Vector((0.0, 0.0, 1.0)).rotation_difference(direction.normalized())
    obj.scale = (1.0, 1.0, length)
    return obj


def make_joint(name, position, radius, mat):
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=1, radius=radius, location=position)
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(mat)
    return obj


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


def main():
    args = parse_args()
    input_path = Path(args.input).resolve()
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    reset_scene()
    bpy.ops.import_scene.gltf(filepath=str(input_path))
    armatures = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if len(armatures) != 1:
        raise RuntimeError(f"Expected one armature, got {len(armatures)}")
    armature = armatures[0]
    for mesh in meshes:
        mesh.hide_render = True
        mesh.hide_viewport = True

    bone_names = set(armature.pose.bones.keys())
    if all(f"bone_{index}" in bone_names for index in range(22)):
        draw_names = [f"bone_{index}" for index in range(22)]
        root_name = "bone_0"
    else:
        draw_names = [
            "mixamorig:Hips", "mixamorig:Spine", "mixamorig:Spine1", "mixamorig:Spine2",
            "mixamorig:Neck", "mixamorig:Head", "mixamorig:LeftShoulder", "mixamorig:LeftArm",
            "mixamorig:LeftForeArm", "mixamorig:LeftHand", "mixamorig:RightShoulder",
            "mixamorig:RightArm", "mixamorig:RightForeArm", "mixamorig:RightHand",
            "mixamorig:LeftUpLeg", "mixamorig:LeftLeg", "mixamorig:LeftFoot",
            "mixamorig:LeftToeBase", "mixamorig:RightUpLeg", "mixamorig:RightLeg",
            "mixamorig:RightFoot", "mixamorig:RightToeBase",
        ]
        root_name = "mixamorig:Hips"
    draw_names = [name for name in draw_names if name in bone_names]

    action = armature.animation_data.action if armature.animation_data else None
    if action is None:
        raise RuntimeError("Input GLB does not contain an animation action")
    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = max(1, int(round(action.frame_range[1])))
    scene.render.fps = round(args.fps)
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 1
    scene.cycles.use_denoising = False
    cycles_device = configure_cycles_gpu(scene)
    scene.render.resolution_x = args.resolution
    scene.render.resolution_y = args.resolution
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "FFMPEG"
    scene.render.ffmpeg.format = "MPEG4"
    scene.render.ffmpeg.codec = "H264"
    scene.render.ffmpeg.constant_rate_factor = "MEDIUM"
    scene.render.ffmpeg.audio_codec = "NONE"
    scene.render.filepath = str(output_path)
    scene.world.color = (0.015, 0.02, 0.035)

    frame_points = []
    root_positions = []
    for frame in range(scene.frame_start, scene.frame_end + 1):
        scene.frame_set(frame)
        per_bone = {}
        for name in draw_names:
            pose_bone = armature.pose.bones[name]
            per_bone[name] = (
                armature.matrix_world @ pose_bone.head.copy(),
                armature.matrix_world @ pose_bone.tail.copy(),
            )
        frame_points.append(per_bone)
        root_positions.append(armature.matrix_world @ armature.pose.bones[root_name].head.copy())

    all_points = [point for per_bone in frame_points for endpoints in per_bone.values() for point in endpoints]
    root_origin = root_positions[0]
    local_points = [point - root for per_bone, root in zip(frame_points, root_positions) for endpoints in per_bone.values() for point in endpoints]
    mins = Vector((min(point.x for point in local_points), min(point.y for point in local_points), min(point.z for point in local_points)))
    maxs = Vector((max(point.x for point in local_points), max(point.y for point in local_points), max(point.z for point in local_points)))
    body_center = root_origin + (mins + maxs) / 2
    body_extent = max(maxs - mins)
    radius = max(body_extent * 0.018, 0.003)
    color = parse_color(args.color)
    bone_mat = material("RetargetedBone", color)
    joint_mat = material("RetargetedJoint", tuple(min(1.0, value * 1.35) for value in color))

    bone_objects = {}
    for name in draw_names:
        start, end = frame_points[0][name]
        bone_objects[name] = make_cylinder(name, start, end, radius, bone_mat)
    joint_names = sorted({name for name in draw_names} | {armature.pose.bones[name].parent.name for name in draw_names if armature.pose.bones[name].parent and armature.pose.bones[name].parent.name in draw_names})
    joint_objects = {}
    for name in joint_names:
        joint_objects[name] = make_joint(f"joint_{name}", frame_points[0][name][0], radius * 1.55, joint_mat)

    camera_data = bpy.data.cameras.new("SkeletonCamera")
    camera = bpy.data.objects.new("SkeletonCamera", camera_data)
    bpy.context.collection.objects.link(camera)
    camera.data.lens = 52
    scene.camera = camera
    base_camera_location = body_center + Vector((body_extent * 2.3, -body_extent * 3.0, body_extent * 0.55))
    camera.location = base_camera_location
    look_at(camera, body_center)

    lights = []
    for name, energy, offset in (
        ("SkeletonKey", 900, Vector((body_extent * 2, -body_extent * 3, body_extent * 3))),
        ("SkeletonFill", 450, Vector((-body_extent * 2, -body_extent, body_extent))),
        ("SkeletonRim", 650, Vector((body_extent, body_extent * 2, body_extent * 2))),
    ):
        data = bpy.data.lights.new(name, "AREA")
        data.energy = energy
        data.size = body_extent * 1.5
        light = bpy.data.objects.new(name, data)
        bpy.context.collection.objects.link(light)
        light.location = body_center + offset
        look_at(light, body_center)
        lights.append((light, light.location.copy()))

    def update_skeleton(scene_arg):
        index = max(0, min(scene_arg.frame_current - scene_arg.frame_start, len(frame_points) - 1))
        delta = root_positions[index] - root_origin
        for name, obj in bone_objects.items():
            start, end = frame_points[index][name]
            direction = end - start
            obj.location = (start + end) / 2
            obj.rotation_quaternion = Vector((0.0, 0.0, 1.0)).rotation_difference(direction.normalized())
            obj.scale = (1.0, 1.0, max(direction.length, 1e-4))
        for name, obj in joint_objects.items():
            obj.location = frame_points[index][name][0]
        target = body_center + delta
        camera.location = base_camera_location + delta
        look_at(camera, target)
        for light, base_location in lights:
            light.location = base_location + delta
            look_at(light, target)

    bpy.app.handlers.frame_change_pre.append(update_skeleton)
    try:
        scene.frame_set(scene.frame_start)
        bpy.ops.render.render(animation=True)
    finally:
        if update_skeleton in bpy.app.handlers.frame_change_pre:
            bpy.app.handlers.frame_change_pre.remove(update_skeleton)

    print(json.dumps({
        "input": str(input_path),
        "output": str(output_path),
        "frames": len(frame_points),
        "fps": scene.render.fps,
        "bones": draw_names,
        "render": "retargeted_skeleton_only",
        "cycles_device": cycles_device,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
