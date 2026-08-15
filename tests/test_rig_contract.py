import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline" / "scripts"))

from rig_contract import (
    CONTRACT_NAME,
    SMPL22_TARGET_PARENTS,
    TARGET_TO_SMPL22,
    canonical_parent_map,
    match_to_reference,
    validate_template_payload,
    weight_distance_policy,
)


class RigContractTests(unittest.TestCase):

    def test_axial_accessory_centroid_is_warning_not_limb_failure(self):
        spine = weight_distance_policy("mixamorig:Spine2", 0.357)
        arm = weight_distance_policy("mixamorig:LeftArm", 0.357)
        severe_spine = weight_distance_policy("mixamorig:Spine2", 0.501)
        self.assertEqual("warning", spine["level"])
        self.assertEqual("error", arm["level"])
        self.assertEqual("error", severe_spine["level"])
    @classmethod
    def setUpClass(cls):
        cls.template = json.loads(
            (ROOT / "pipeline" / "config" / "smpl22_skeleton.json").read_text(
                encoding="utf-8"
            )
        )

    def test_template_is_exact_smpl22_contract(self):
        self.assertEqual(CONTRACT_NAME, self.template["contract"])
        self.assertEqual([], validate_template_payload(self.template))
        self.assertEqual(
            list(range(22)), sorted(TARGET_TO_SMPL22.values())
        )

    def test_semantic_parent_graph_is_exact(self):
        self.assertEqual(
            [],
            canonical_parent_map(
                list(SMPL22_TARGET_PARENTS), SMPL22_TARGET_PARENTS
            ),
        )
        broken = dict(SMPL22_TARGET_PARENTS)
        broken["mixamorig:LeftHand"] = "mixamorig:Spine2"
        self.assertTrue(canonical_parent_map(list(broken), broken))

    def test_reference_matching_ignores_generated_joint_order(self):
        imported_order = [
            "mixamorig:Hips", "mixamorig:LeftUpLeg", "mixamorig:LeftLeg",
            "mixamorig:LeftFoot", "mixamorig:LeftToeBase", "mixamorig:RightUpLeg",
            "mixamorig:RightLeg", "mixamorig:RightFoot", "mixamorig:RightToeBase",
            "mixamorig:Spine", "mixamorig:Spine1", "mixamorig:Spine2",
            "mixamorig:LeftShoulder", "mixamorig:LeftArm", "mixamorig:LeftForeArm",
            "mixamorig:LeftHand", "mixamorig:Neck", "mixamorig:Head",
            "mixamorig:RightShoulder", "mixamorig:RightArm",
            "mixamorig:RightForeArm", "mixamorig:RightHand",
        ]
        semantic_to_raw = {
            semantic: f"bone_{index}" for index, semantic in enumerate(imported_order)
        }
        raw_parents = {
            semantic_to_raw[name]: (
                None if parent is None else semantic_to_raw[parent]
            )
            for name, parent in SMPL22_TARGET_PARENTS.items()
        }
        reference = {
            joint["name"]: joint["position"] for joint in self.template["joints"]
        }
        raw_positions = {
            semantic_to_raw[name]: position for name, position in reference.items()
        }
        mapping, metrics, problems = match_to_reference(
            list(semantic_to_raw.values()), raw_parents, raw_positions, reference
        )
        self.assertEqual([], problems)
        self.assertEqual(
            {raw: semantic for semantic, raw in semantic_to_raw.items()}, mapping
        )
        self.assertAlmostEqual(0.0, metrics["max_normalized_error"])


if __name__ == "__main__":
    unittest.main()
