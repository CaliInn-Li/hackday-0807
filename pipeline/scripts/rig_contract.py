"""Pure-Python fixed SMPL-22 target contract used by the production pipeline."""

from collections.abc import Mapping, Sequence
from itertools import permutations
from math import dist, sqrt


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

SMPL22_TARGET_PARENTS = {
    "mixamorig:Hips": None,
    "mixamorig:Spine": "mixamorig:Hips",
    "mixamorig:Spine1": "mixamorig:Spine",
    "mixamorig:Spine2": "mixamorig:Spine1",
    "mixamorig:Neck": "mixamorig:Spine2",
    "mixamorig:Head": "mixamorig:Neck",
    "mixamorig:LeftShoulder": "mixamorig:Spine2",
    "mixamorig:LeftArm": "mixamorig:LeftShoulder",
    "mixamorig:LeftForeArm": "mixamorig:LeftArm",
    "mixamorig:LeftHand": "mixamorig:LeftForeArm",
    "mixamorig:RightShoulder": "mixamorig:Spine2",
    "mixamorig:RightArm": "mixamorig:RightShoulder",
    "mixamorig:RightForeArm": "mixamorig:RightArm",
    "mixamorig:RightHand": "mixamorig:RightForeArm",
    "mixamorig:LeftUpLeg": "mixamorig:Hips",
    "mixamorig:LeftLeg": "mixamorig:LeftUpLeg",
    "mixamorig:LeftFoot": "mixamorig:LeftLeg",
    "mixamorig:LeftToeBase": "mixamorig:LeftFoot",
    "mixamorig:RightUpLeg": "mixamorig:Hips",
    "mixamorig:RightLeg": "mixamorig:RightUpLeg",
    "mixamorig:RightFoot": "mixamorig:RightLeg",
    "mixamorig:RightToeBase": "mixamorig:RightFoot",
}

SMPL22_PARENTS = (
    -1, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7,
    8, 9, 9, 9, 12, 13, 14, 16, 17, 18, 19,
)

CONTRACT_NAME = "smpl22-mixamo-v1"
SKINTOKENS_TRANSFER_ARMATURE_NAME = "Armature"

PREFERRED_TAIL_CHILD = {
    parent: child
    for child, parent in SMPL22_TARGET_PARENTS.items()
    if parent is not None
}
PREFERRED_TAIL_CHILD.update(
    {"mixamorig:Hips": "mixamorig:Spine", "mixamorig:Spine2": "mixamorig:Neck"}
)


def validate_template_payload(payload: Mapping) -> list[str]:
    problems = []
    joints = payload.get("joints", [])
    names = [joint.get("name") for joint in joints]
    parents = {joint.get("name"): joint.get("parent") for joint in joints}
    indices = [joint.get("smpl22_index") for joint in joints]
    if payload.get("contract") != CONTRACT_NAME:
        problems.append(f"template contract must be {CONTRACT_NAME!r}")
    if names != list(SMPL22_TARGET_PARENTS):
        problems.append("template joint order must match the fixed target contract")
    if parents != SMPL22_TARGET_PARENTS:
        problems.append("template parent graph does not match the fixed target contract")
    if sorted(indices) != list(range(22)):
        problems.append("template SMPL-22 indices must cover 0..21 exactly")
    for joint in joints:
        name = joint.get("name")
        if name in TARGET_TO_SMPL22 and joint.get("smpl22_index") != TARGET_TO_SMPL22[name]:
            problems.append(f"template index for {name} does not match the contract")
    return problems


def canonical_parent_map(
    bone_names: Sequence[str],
    parent_by_name: Mapping[str, str | None],
) -> list[str]:
    problems = []
    actual = set(bone_names)
    expected = set(SMPL22_TARGET_PARENTS)
    if len(bone_names) != len(actual):
        problems.append("skeleton contains duplicate bone names")
    if actual != expected:
        problems.append(
            f"bone set does not match {CONTRACT_NAME}; found {len(actual)} bones"
        )
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        if missing:
            problems.append(f"missing semantic bones: {missing}")
        if extra:
            problems.append(f"unexpected bones: {extra}")
        return problems
    for name, expected_parent in SMPL22_TARGET_PARENTS.items():
        actual_parent = parent_by_name.get(name)
        if actual_parent != expected_parent:
            problems.append(
                f"{name} parent must be {expected_parent!r}, found {actual_parent!r}"
            )
    return problems


def match_to_reference(
    bone_names: Sequence[str],
    parent_by_name: Mapping[str, str | None],
    positions: Mapping[str, Sequence[float]],
    reference_positions: Mapping[str, Sequence[float]],
    max_mean_error: float = 0.12,
    max_joint_error: float = 0.25,
):
    """Infer generated-name -> semantic-name from tree topology and joint heads.

    SkinTokens/glTF may reorder or rename joints even when ``--use_skeleton``
    preserves the supplied graph. The match therefore never trusts ``bone_N``.
    """
    names = list(bone_names)
    actual = set(names)
    expected = set(SMPL22_TARGET_PARENTS)
    if len(names) != len(actual):
        return {}, {}, ["skeleton contains duplicate bone names"]
    if len(names) != len(expected):
        return {}, {}, [f"bone count {len(names)} != {len(expected)}"]
    if actual - set(positions):
        return {}, {}, [f"missing joint positions: {sorted(actual - set(positions))}"]
    if expected - set(reference_positions):
        return {}, {}, [
            f"reference is missing semantic positions: {sorted(expected - set(reference_positions))}"
        ]

    children = {name: [] for name in names}
    roots = []
    problems = []
    for name in names:
        parent = parent_by_name.get(name)
        if parent is None:
            roots.append(name)
        elif parent not in actual:
            problems.append(f"bone {name} references unknown parent {parent}")
        else:
            children[parent].append(name)
    if len(roots) != 1:
        problems.append(f"expected one root, found {len(roots)}: {roots}")
    if problems:
        return {}, {}, problems

    reference_children = {name: [] for name in SMPL22_TARGET_PARENTS}
    for name, parent in SMPL22_TARGET_PARENTS.items():
        if parent is not None:
            reference_children[parent].append(name)

    def subtree_sizes(root, child_map):
        visiting = set()
        sizes = {}

        def visit(node):
            if node in visiting:
                raise ValueError(f"cycle detected at {node}")
            if node in sizes:
                return sizes[node]
            visiting.add(node)
            size = 1 + sum(visit(child) for child in child_map[node])
            visiting.remove(node)
            sizes[node] = size
            return size

        visit(root)
        return sizes

    try:
        actual_sizes = subtree_sizes(roots[0], children)
        reference_sizes = subtree_sizes("mixamorig:Hips", reference_children)
    except ValueError as error:
        return {}, {}, [str(error)]
    if len(actual_sizes) != len(names):
        return {}, {}, ["skeleton contains joints not reachable from its root"]

    def normalize(source, root):
        origin = source[root]
        scale = max(dist(source[name], origin) for name in source)
        if scale <= 1e-8:
            raise ValueError("skeleton joint positions are degenerate")
        return {
            name: tuple(
                (float(value) - float(origin[index])) / scale
                for index, value in enumerate(point)
            )
            for name, point in source.items()
        }

    try:
        actual_normalized = normalize(positions, roots[0])
        reference_normalized = normalize(reference_positions, "mixamorig:Hips")
    except ValueError as error:
        return {}, {}, [str(error)]

    def solve(actual_name, semantic_name):
        if actual_sizes[actual_name] != reference_sizes[semantic_name]:
            return None
        actual_children = children[actual_name]
        semantic_children = reference_children[semantic_name]
        if len(actual_children) != len(semantic_children):
            return None
        joint_error = dist(
            actual_normalized[actual_name], reference_normalized[semantic_name]
        )
        if not actual_children:
            return joint_error * joint_error, {actual_name: semantic_name}, [joint_error]
        best = None
        for ordered_actual in permutations(actual_children):
            cost = joint_error * joint_error
            mapping = {actual_name: semantic_name}
            errors = [joint_error]
            for child, semantic_child in zip(ordered_actual, semantic_children):
                result = solve(child, semantic_child)
                if result is None:
                    break
                child_cost, child_mapping, child_errors = result
                cost += child_cost
                mapping.update(child_mapping)
                errors.extend(child_errors)
            else:
                if best is None or cost < best[0]:
                    best = (cost, mapping, errors)
        return best

    result = solve(roots[0], "mixamorig:Hips")
    if result is None:
        return {}, {}, [f"parent graph is not isomorphic to {CONTRACT_NAME}"]
    cost, mapping, errors = result
    metrics = {
        "mean_normalized_error": sqrt(cost / len(errors)),
        "max_normalized_error": max(errors),
    }
    problems = []
    if metrics["mean_normalized_error"] > max_mean_error:
        problems.append(
            "joint geometry differs from the fixed reference: mean normalized "
            f"error {metrics['mean_normalized_error']:.4f} > {max_mean_error:.4f}"
        )
    if metrics["max_normalized_error"] > max_joint_error:
        problems.append(
            "joint geometry differs from the fixed reference: max normalized "
            f"error {metrics['max_normalized_error']:.4f} > {max_joint_error:.4f}"
        )
    return mapping, metrics, problems
