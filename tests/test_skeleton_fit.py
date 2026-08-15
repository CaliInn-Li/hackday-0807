import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline" / "scripts"))

from skeleton_fit import estimate_body_axis, quantile


class SkeletonFitTests(unittest.TestCase):
    def test_quantile_interpolates(self):
        self.assertEqual(2.5, quantile([1, 2, 3, 4], 0.5))

    def test_upper_body_axis_ignores_rear_accessory(self):
        points = []
        for z in (5.5, 6.5, 7.5, 8.5, 9.0):
            for x in (-1.0, 0.0, 1.0):
                for y in (-2.2, -2.0, -1.8):
                    points.append((x, y, z))
            points.extend(((0.0, 3.0, z), (0.0, 4.0, z)))
        points.extend((x, 6.0, z) for x in (-5.0, 5.0) for z in (0.0, 4.0))
        result = estimate_body_axis(
            points, minimum=(-5.0, -2.2, 0.0), maximum=(5.0, 6.0, 10.0)
        )
        self.assertEqual("upper_body_center_slab", result["sample_mode"])
        self.assertAlmostEqual(-2.0, result["center_y"])


if __name__ == "__main__":
    unittest.main()
