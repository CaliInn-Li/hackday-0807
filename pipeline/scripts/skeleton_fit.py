"""Pure geometry helpers for fitting the fixed SMPL-22 humanoid skeleton."""


DEFAULT_BODY_AXIS_FIT = {
    "z_min": 0.55,
    "z_max": 0.90,
    "x_half_width": 0.18,
    "front_weighted_y_quantile": 0.40,
}

DEFAULT_LIMB_LANDMARK_FIT = {
    "arm_z_min": 0.68,
    "arm_z_max": 0.82,
    "arm_x_radius": 0.018,
    "arm_section_low_quantile": 0.10,
    "arm_section_high_quantile": 0.90,
    "foot_z_max": 0.03,
    "foot_center_exclusion": 0.04,
    "minimum_samples": 24,
}


def quantile(values, probability):
    if not values:
        raise ValueError("quantile requires at least one value")
    if not 0.0 <= probability <= 1.0:
        raise ValueError(f"quantile probability must be in [0, 1], found {probability}")
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def estimate_body_axis(points, minimum, maximum, settings=None):
    """Estimate the torso axis while ignoring rear accessories such as capes.

    Pipeline coordinates define -Y as character-forward. Sampling the upper
    body near its X center avoids using the full AABB midpoint, which is easily
    displaced by capes, long hair, tails, weapons, or backpacks.
    """
    config = dict(DEFAULT_BODY_AXIS_FIT)
    config.update(settings or {})
    z_min = float(config["z_min"])
    z_max = float(config["z_max"])
    x_half_width = float(config["x_half_width"])
    y_quantile = float(config["front_weighted_y_quantile"])
    if not 0.0 <= z_min < z_max <= 1.0:
        raise ValueError(f"invalid body-axis Z range: {z_min}..{z_max}")
    if not 0.0 < x_half_width <= 0.5:
        raise ValueError(f"x_half_width must be in (0, 0.5], found {x_half_width}")
    if not 0.0 <= y_quantile <= 1.0:
        raise ValueError(
            f"front_weighted_y_quantile must be in [0, 1], found {y_quantile}"
        )

    min_x, _, min_z = map(float, minimum)
    max_x, _, max_z = map(float, maximum)
    width = max_x - min_x
    height = max_z - min_z
    center_x = (min_x + max_x) * 0.5
    low_z = min_z + z_min * height
    high_z = min_z + z_max * height
    x_radius = width * x_half_width

    candidates = [
        float(point[1])
        for point in points
        if low_z <= float(point[2]) <= high_z
        and abs(float(point[0]) - center_x) <= x_radius
    ]
    sample_mode = "upper_body_center_slab"
    if not candidates:
        candidates = [
            float(point[1])
            for point in points
            if low_z <= float(point[2]) <= high_z
        ]
        sample_mode = "upper_body_full_width_fallback"
    if not candidates:
        candidates = [float(point[1]) for point in points]
        sample_mode = "all_vertices_fallback"
    if not candidates:
        raise ValueError("body-axis fitting requires at least one mesh vertex")

    return {
        "center_x": center_x,
        "center_y": quantile(candidates, y_quantile),
        "sample_count": len(candidates),
        "sample_mode": sample_mode,
        "settings": config,
    }


def estimate_arm_section_center(points, minimum, maximum, target_x, settings=None):
    """Estimate an arm joint's volume center from a narrow vertical section."""
    config = dict(DEFAULT_LIMB_LANDMARK_FIT)
    config.update(settings or {})
    min_x, _, min_z = map(float, minimum)
    max_x, _, max_z = map(float, maximum)
    width = max_x - min_x
    height = max_z - min_z
    if width <= 1e-8 or height <= 1e-8:
        raise ValueError("arm fitting requires non-degenerate mesh bounds")

    z_min = float(config["arm_z_min"])
    z_max = float(config["arm_z_max"])
    x_radius = width * float(config["arm_x_radius"])
    low_quantile = float(config["arm_section_low_quantile"])
    high_quantile = float(config["arm_section_high_quantile"])
    minimum_samples = int(config["minimum_samples"])
    if not 0.0 <= z_min < z_max <= 1.0:
        raise ValueError(f"invalid arm Z range: {z_min}..{z_max}")
    if x_radius <= 0.0:
        raise ValueError("arm_x_radius must be positive")
    if not 0.0 <= low_quantile < high_quantile <= 1.0:
        raise ValueError("arm section quantiles must be ordered within [0, 1]")

    low_z = min_z + z_min * height
    high_z = min_z + z_max * height
    candidates = [
        point
        for point in points
        if abs(float(point[0]) - float(target_x)) <= x_radius
        and low_z <= float(point[2]) <= high_z
    ]
    if len(candidates) < minimum_samples:
        return {
            "accepted": False,
            "sample_count": len(candidates),
            "reason": f"needs at least {minimum_samples} arm-section vertices",
        }

    result = {"accepted": True, "sample_count": len(candidates)}
    for axis, label in ((1, "y"), (2, "z")):
        values = [float(point[axis]) for point in candidates]
        low = quantile(values, low_quantile)
        high = quantile(values, high_quantile)
        result[label] = (low + high) * 0.5
        result[f"{label}_low"] = low
        result[f"{label}_high"] = high
    return result


def estimate_foot_centers(points, minimum, maximum, settings=None):
    """Find left/right foot centers in the lowest clean silhouette slab."""
    config = dict(DEFAULT_LIMB_LANDMARK_FIT)
    config.update(settings or {})
    min_x, _, min_z = map(float, minimum)
    max_x, _, max_z = map(float, maximum)
    width = max_x - min_x
    height = max_z - min_z
    if width <= 1e-8 or height <= 1e-8:
        raise ValueError("foot fitting requires non-degenerate mesh bounds")

    center_x = (min_x + max_x) * 0.5
    high_z = min_z + float(config["foot_z_max"]) * height
    exclusion = width * float(config["foot_center_exclusion"])
    minimum_samples = int(config["minimum_samples"])
    bottom = [point for point in points if float(point[2]) <= high_z]
    sides = {
        "left": [point for point in bottom if float(point[0]) > center_x + exclusion],
        "right": [point for point in bottom if float(point[0]) < center_x - exclusion],
    }
    result = {
        "accepted": True,
        "bottom_sample_count": len(bottom),
        "z_max": high_z,
    }
    for side, candidates in sides.items():
        if len(candidates) < minimum_samples:
            result.update(
                {
                    "accepted": False,
                    "reason": (
                        f"{side} foot needs at least {minimum_samples} vertices; "
                        f"found {len(candidates)}"
                    ),
                }
            )
            return result
        result[side] = {
            "x": quantile([point[0] for point in candidates], 0.5),
            "y": quantile([point[1] for point in candidates], 0.5),
            "z": quantile([point[2] for point in candidates], 0.5),
            "sample_count": len(candidates),
        }
    return result
