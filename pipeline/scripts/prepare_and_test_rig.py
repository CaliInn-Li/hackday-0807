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
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])


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


def setup_render(meshes):
    scene = bpy.context.scene
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
