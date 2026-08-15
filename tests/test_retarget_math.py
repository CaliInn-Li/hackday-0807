import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline" / "scripts"))

from retarget_math import accumulate_global_rotations
from rig_contract import SMPL22_PARENTS


class RetargetMathTests(unittest.TestCase):
    def test_identity_motion_remains_identity(self):
        local = np.broadcast_to(np.eye(3), (2, 22, 3, 3)).copy()
        result = accumulate_global_rotations(local, SMPL22_PARENTS)
        np.testing.assert_allclose(local, result)

    def test_child_global_includes_parent_rotation(self):
        local = np.broadcast_to(np.eye(3), (1, 22, 3, 3)).copy()
        angle = np.pi / 2
        root = np.array(
            [[np.cos(angle), -np.sin(angle), 0],
             [np.sin(angle), np.cos(angle), 0], [0, 0, 1]]
        )
        local[0, 0] = root
        result = accumulate_global_rotations(local, SMPL22_PARENTS)
        np.testing.assert_allclose(root, result[0, 3])


if __name__ == "__main__":
    unittest.main()
