import json
import sys

from src.rig_package.parser.bpy import BpyParser


asset = BpyParser.load(sys.argv[1])
before = {
    "joint_count": asset.J,
    "joint_names": list(asset.joint_names) if asset.joint_names is not None else None,
    "skin_sums": asset.skin.sum(axis=0).round(6).tolist() if asset.skin is not None else None,
}
asset.trim_skeleton()
print(json.dumps({
    "before_trim": before,
    "after_trim_joint_count": asset.J,
    "after_trim_joint_names": list(asset.joint_names) if asset.joint_names is not None else None,
    "joint_names": list(asset.joint_names) if asset.joint_names is not None else None,
    "parents": asset.parents.tolist() if asset.parents is not None else None,
    "matrix_local_shape": list(asset.matrix_local.shape) if asset.matrix_local is not None else None,
    "matrix_basis_shape": list(asset.matrix_basis.shape) if asset.matrix_basis is not None else None,
    "mesh_names": list(asset.mesh_names) if asset.mesh_names is not None else None,
    "vertices_shape": list(asset.vertices.shape) if asset.vertices is not None else None,
    "skin_shape": list(asset.skin.shape) if asset.skin is not None else None,
}, ensure_ascii=False))
