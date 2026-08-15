"""Render a few keyframes of an animated GLB for deformation QA.

This intentionally renders PNG keyframes only. It is not a replacement for
the GLB animation itself and does not encode a video.
"""

import argparse
import sys
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_gvhmr_motion import glb_visual_height, look_at, mesh_points  # noqa: E402


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--frames", default="1,80,160")
    parser.add_argument("--resolution", type=int, default=480)
    parser.add_argument("--samples", type=int, default=2)
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])


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
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    bpy.ops.import_scene.gltf(filepath=str(input_path))

    armatures = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if len(armatures) != 1 or not meshes:
        raise RuntimeError(f"Expected one armature and at least one mesh, got {len(armatures)} and {len(meshes)}")
    armature = armatures[0]
    root_name = "bone_0" if "bone_0" in armature.pose.bones else "mixamorig:Hips"
    action = armature.animation_data.action if armature.animation_data else None
    if action is None:
        raise RuntimeError("Input GLB does not contain an animation action")

    scene = bpy.context.scene
    scene.frame_start = 1
    scene.frame_end = max(1, int(round(action.frame_range[1])))
    scene.render.engine = "CYCLES"
    scene.cycles.samples = max(1, args.samples)
    scene.cycles.use_denoising = False
    cycles_device = configure_cycles_gpu(scene)
    scene.render.resolution_x = args.resolution
    scene.render.resolution_y = args.resolution
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.world.color = (0.035, 0.035, 0.045)

    visual_height = glb_visual_height(input_path)
    points = mesh_points(meshes, visual_height)
    mins = Vector((min(p.x for p in points), min(p.y for p in points), min(p.z for p in points)))
    maxs = Vector((max(p.x for p in points), max(p.y for p in points), max(p.z for p in points)))
    center = (mins + maxs) / 2
    radius = max(maxs - mins) * 0.75

    root_positions = []
    for frame in range(scene.frame_start, scene.frame_end + 1):
        scene.frame_set(frame)
        root_positions.append(armature.matrix_world @ armature.pose.bones[root_name].head)
    root_origin = root_positions[0]

    camera_data = bpy.data.cameras.new("TopologyQA_Camera")
    camera = bpy.data.objects.new("TopologyQA_Camera", camera_data)
    bpy.context.collection.objects.link(camera)
    camera.data.lens = 52
    scene.camera = camera
    camera.location = center + Vector((radius * 2.8, -radius * 3.1, radius * 0.3))
    look_at(camera, center)
    base_camera_location = camera.location.copy()

    lights = []
    for name, energy, offset in (
        ("TopologyQA_Key", 80, Vector((radius * 2, -radius * 3, radius * 3))),
        ("TopologyQA_Fill", 35, Vector((-radius * 2, -radius, radius))),
        ("TopologyQA_Rim", 55, Vector((radius, radius * 2, radius * 2))),
    ):
        data = bpy.data.lights.new(name, "AREA")
        data.energy = energy
        data.size = radius * 2
        light = bpy.data.objects.new(name, data)
        bpy.context.collection.objects.link(light)
        light.location = center + offset
        look_at(light, center)
        lights.append((light, light.location.copy()))

    def position_camera(frame):
        index = max(0, min(frame - scene.frame_start, len(root_positions) - 1))
        delta = root_positions[index] - root_origin
        target = center + delta
        camera.location = base_camera_location + delta
        look_at(camera, target)
        for light, base_location in lights:
            light.location = base_location + delta
            look_at(light, target)

    requested = [int(value.strip()) for value in args.frames.split(",") if value.strip()]
    frames = sorted({max(scene.frame_start, min(scene.frame_end, frame)) for frame in requested})
    for frame in frames:
        scene.frame_set(frame)
        position_camera(frame)
        scene.render.filepath = str(output_dir / f"frame_{frame:04d}.png")
        bpy.ops.render.render(write_still=True)

    print({
        "input": str(input_path),
        "output_dir": str(output_dir),
        "frames": frames,
        "cycles_device": cycles_device,
    })


if __name__ == "__main__":
    main()
