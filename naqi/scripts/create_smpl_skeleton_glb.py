import argparse
import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--template", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])


def reset_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for armature in list(bpy.data.armatures):
        bpy.data.armatures.remove(armature)


def load_template(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    names = payload["names"]
    joints = [Vector((float(p[0]), float(p[1]), float(p[2]))) for p in payload["joints"]]
    parents = [int(p) for p in payload["parents"]]
    if len(names) != 24 or len(joints) != 24 or len(parents) != 24:
        raise RuntimeError("The SMPL template must contain exactly 24 joints")
    # SMPL is X-right, Y-up, Z-forward. Blender is X-right, Y-back, Z-up.
    blender_joints = [Vector((point.x, -point.z, point.y)) for point in joints]
    return names, blender_joints, parents


def mesh_world_points(meshes):
    points = []
    for mesh in meshes:
        points.extend(mesh.matrix_world @ vertex.co for vertex in mesh.data.vertices)
    return points


def bake_mesh_transforms(meshes):
    for mesh in meshes:
        world = mesh.matrix_world.copy()
        mesh.data.transform(world)
        mesh.matrix_world.identity()


def create_armature(names, joints, parents, target_min, target_max):
    source_min = min(point.z for point in joints)
    source_max = max(point.z for point in joints)
    source_height = source_max - source_min
    target_height = target_max.z - target_min.z
    if source_height <= 0 or target_height <= 0:
        raise RuntimeError("Unable to determine SMPL or mesh height")
    scale = target_height / source_height
    root = joints[0]
    target_center = Vector(((target_min.x + target_max.x) / 2, (target_min.y + target_max.y) / 2, target_min.z - source_min * scale))
    points = [target_center + (point - root) * scale for point in joints]

    children = [[] for _ in points]
    for index, parent in enumerate(parents):
        if parent >= 0:
            children[parent].append(index)

    armature_data = bpy.data.armatures.new("SMPL_Armature")
    armature = bpy.data.objects.new("SMPL_Armature", armature_data)
    bpy.context.collection.objects.link(armature)
    armature.show_in_front = True
    armature["skeleton_format"] = "SMPL"
    armature["skeleton_joint_count"] = 24
    armature["skeleton_joint_order"] = json.dumps(names)

    bpy.context.view_layer.objects.active = armature
    armature.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    edit_bones = []
    for index, name in enumerate(names):
        bone = armature_data.edit_bones.new(name)
        bone.head = points[index]
        if children[index]:
            child_center = sum((points[child] for child in children[index]), Vector()) / len(children[index])
            direction = child_center - points[index]
        elif parents[index] >= 0:
            direction = points[index] - points[parents[index]]
        else:
            direction = Vector((0, 0, 1))
        if direction.length < target_height * 1e-4:
            direction = Vector((0, 0, max(target_height * 0.02, 1e-4)))
        else:
            direction.normalize()
            direction *= max(target_height * 0.025, target_height * 0.18 / max(len(points), 1))
        bone.tail = bone.head + direction
        bone.use_deform = True
        edit_bones.append(bone)
    for index, parent in enumerate(parents):
        if parent >= 0:
            edit_bones[index].parent = edit_bones[parent]
            edit_bones[index].use_connect = False
    bpy.ops.object.mode_set(mode="OBJECT")
    armature.select_set(False)
    return armature, points, scale


def main():
    args = parse_args()
    input_path = Path(args.input).resolve()
    template_path = Path(args.template).resolve()
    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    reset_scene()
    bpy.ops.import_scene.gltf(filepath=str(input_path))
    # The source snow-girl GLB contains a small helper Icosphere in addition
    # to the character.  It is not part of the character surface and should
    # not be presented to SkinTokens as a second mesh to skin.
    for helper in list(bpy.context.scene.objects):
        if helper.type == "MESH" and helper.name.lower().startswith("icosphere"):
            bpy.data.objects.remove(helper, do_unlink=True)
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    old_armatures = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
    if not meshes:
        raise RuntimeError("Input GLB does not contain a mesh")
    for armature in old_armatures:
        bpy.data.objects.remove(armature, do_unlink=True)

    bake_mesh_transforms(meshes)
    points = mesh_world_points(meshes)
    target_min = Vector((min(point.x for point in points), min(point.y for point in points), min(point.z for point in points)))
    target_max = Vector((max(point.x for point in points), max(point.y for point in points), max(point.z for point in points)))
    names, joints, parents = load_template(template_path)
    armature, skeleton_points, scale = create_armature(names, joints, parents, target_min, target_max)

    for mesh in meshes:
        mesh.parent = armature
        mesh.parent_type = "OBJECT"
        # glTF stores at most four joint influences per vertex.  A tiny weight
        # on every group would therefore export only the first four joints and
        # SkinTokens' trim_skeleton step would discard the rest.  Use a
        # nearest-joint placeholder assignment instead, guaranteeing that all
        # 24 canonical joints occur in the exported JOINTS_0 data.  SkinTokens
        # will replace these placeholder weights in --use_skeleton mode.
        for group in list(mesh.vertex_groups):
            mesh.vertex_groups.remove(group)
        groups = [mesh.vertex_groups.new(name=name) for name in names]
        assignments = [None] * len(mesh.data.vertices)
        reserved = set()
        # Reserve distinct vertices first so a very small hand/elbow region
        # cannot overwrite the only placeholder vertex of another joint.
        for joint_index in range(len(names)):
            vertex_index = min(
                (index for index in range(len(mesh.data.vertices)) if index not in reserved),
                key=lambda index: (
                    (mesh.matrix_world @ mesh.data.vertices[index].co - skeleton_points[joint_index]).length_squared
                ),
            )
            assignments[vertex_index] = joint_index
            reserved.add(vertex_index)
        for vertex in mesh.data.vertices:
            if assignments[vertex.index] is not None:
                continue
            point = mesh.matrix_world @ vertex.co
            assignments[vertex.index] = min(
                range(len(skeleton_points)),
                key=lambda index: (point - skeleton_points[index]).length_squared,
            )
        for joint_index, group in enumerate(groups):
            indices = [index for index, assignment in enumerate(assignments) if assignment == joint_index]
            if indices:
                group.add(indices, 1.0, "REPLACE")
        modifier = mesh.modifiers.new("SMPL_Armature", "ARMATURE")
        modifier.object = armature

    bpy.ops.object.select_all(action="DESELECT")
    armature.select_set(True)
    for mesh in meshes:
        mesh.select_set(True)
    bpy.context.view_layer.objects.active = armature
    bpy.ops.export_scene.gltf(
        filepath=str(output_path),
        export_format="GLB",
        use_selection=True,
        export_skins=True,
        export_animations=False,
        export_yup=True,
    )
    print(json.dumps({
        "input": str(input_path),
        "output": str(output_path),
        "skeleton_format": "SMPL",
        "joints": names,
        "joint_count": len(names),
        "parents": parents,
        "mesh_height": round(target_max.z - target_min.z, 7),
        "skeleton_scale": round(scale, 7),
        "skeleton_points": [[round(value, 7) for value in point] for point in skeleton_points],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
