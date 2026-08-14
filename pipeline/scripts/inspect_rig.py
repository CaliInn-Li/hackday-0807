import argparse
import json
from collections import Counter
from pathlib import Path

import bpy


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(
        __import__("sys").argv[__import__("sys").argv.index("--") + 1 :]
    )
    return args


def reset_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)


def inspect_armature(obj):
    bones = []
    for bone in obj.data.bones:
        bones.append(
            {
                "name": bone.name,
                "parent": bone.parent.name if bone.parent else None,
                "head_local": [round(v, 7) for v in bone.head_local],
                "tail_local": [round(v, 7) for v in bone.tail_local],
                "length": round(bone.length, 7),
                "use_deform": bool(bone.use_deform),
            }
        )
    return {
        "name": obj.name,
        "matrix_world": [[round(v, 7) for v in row] for row in obj.matrix_world],
        "bone_count": len(bones),
        "root_bones": [bone["name"] for bone in bones if bone["parent"] is None],
        "bones": bones,
    }


def inspect_mesh(obj):
    group_names = {group.index: group.name for group in obj.vertex_groups}
    influenced_vertices = 0
    influences_per_vertex = Counter()
    group_weight_sum = Counter()
    group_vertex_count = Counter()
    unweighted = []

    for vertex in obj.data.vertices:
        positive = [(g.group, g.weight) for g in vertex.groups if g.weight > 1e-8]
        influences_per_vertex[len(positive)] += 1
        if positive:
            influenced_vertices += 1
        elif len(unweighted) < 20:
            unweighted.append(vertex.index)
        for group_index, weight in positive:
            name = group_names.get(group_index, f"<group:{group_index}>")
            group_weight_sum[name] += weight
            group_vertex_count[name] += 1

    modifiers = [
        {
            "name": modifier.name,
            "type": modifier.type,
            "object": getattr(getattr(modifier, "object", None), "name", None),
        }
        for modifier in obj.modifiers
    ]
    return {
        "name": obj.name,
        "vertex_count": len(obj.data.vertices),
        "polygon_count": len(obj.data.polygons),
        "vertex_group_count": len(obj.vertex_groups),
        "armature_parent": obj.parent.name if obj.parent and obj.parent.type == "ARMATURE" else None,
        "modifiers": modifiers,
        "influenced_vertices": influenced_vertices,
        "unweighted_vertex_count": len(obj.data.vertices) - influenced_vertices,
        "unweighted_vertex_examples": unweighted,
        "influences_per_vertex": dict(sorted(influences_per_vertex.items())),
        "groups": [
            {
                "name": name,
                "vertex_count": group_vertex_count[name],
                "weight_sum": round(group_weight_sum[name], 6),
            }
            for name in sorted(group_weight_sum)
        ],
    }


def main():
    args = parse_args()
    reset_scene()
    bpy.ops.import_scene.gltf(filepath=str(Path(args.input).resolve()))

    armatures = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    summary = {
        "input": str(Path(args.input).resolve()),
        "armature_count": len(armatures),
        "mesh_count": len(meshes),
        "armatures": [inspect_armature(obj) for obj in armatures],
        "meshes": [inspect_mesh(obj) for obj in meshes],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
