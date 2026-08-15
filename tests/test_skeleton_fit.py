import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline" / "scripts"))

from skeleton_fit import (
    estimate_arm_section_center,
    estimate_body_axis,
    estimate_foot_centers,
    estimate_head_center,
    quantile,
)


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

    def test_arm_section_uses_robust_surface_midpoint(self):
        points = []
        for index in range(30):
            x = 0.30 + (index % 3 - 1) * 0.002
            points.extend(((x, -0.10, 0.70), (x, 0.10, 0.80)))
        # Sparse outliers must not pull the fitted joint to the arm surface.
        points.extend(((0.30, -0.8, 0.69), (0.30, 0.8, 0.81)))
        result = estimate_arm_section_center(
            points,
            minimum=(-1.0, -1.0, 0.0),
            maximum=(1.0, 1.0, 1.0),
            target_x=0.30,
        )
        self.assertTrue(result["accepted"])
        self.assertAlmostEqual(0.0, result["y"], places=3)
        self.assertAlmostEqual(0.75, result["z"], places=3)

    def test_lowest_slab_finds_two_feet_and_ignores_dress(self):
        points = []
        for index in range(30):
            offset = (index % 5 - 2) * 0.005
            points.append((0.60 + offset, -0.20, 0.01))
            points.append((-0.50 + offset, -0.18, 0.01))
        # Wide lower-body accessory is above the configured foot slab.
        points.extend((x, 0.30, 0.20) for x in (-0.9, -0.4, 0.4, 0.9))
        result = estimate_foot_centers(
            points,
            minimum=(-1.0, -1.0, 0.0),
            maximum=(1.0, 1.0, 1.0),
        )
        self.assertTrue(result["accepted"])
        self.assertAlmostEqual(0.60, result["left"]["x"], places=3)
        self.assertAlmostEqual(-0.50, result["right"]["x"], places=3)

    def test_head_center_uses_face_band_instead_of_hair_top(self):
        points = []
        for index in range(40):
            x = (index % 5 - 2) * 0.01
            # Face/front samples occupy the lower skull band.
            points.append((x, -0.20, 0.86 + (index % 4) * 0.005))
            points.append((x, 0.00, 0.88 + (index % 4) * 0.005))
        # Large hair mass is high and behind the face.
        points.extend((0.0, 0.10, 0.96) for _ in range(80))
        result = estimate_head_center(
            points,
            minimum=(-1.0, -1.0, 0.0),
            maximum=(1.0, 1.0, 1.0),
        )
        self.assertTrue(result["accepted"])
        self.assertLess(result["z"], 0.90)
        self.assertAlmostEqual(0.0, result["x"], places=3)


if __name__ == "__main__":
    unittest.main()
