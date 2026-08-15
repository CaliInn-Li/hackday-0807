"""Pure geometry helpers for fitting the fixed SMPL-22 humanoid skeleton."""


DEFAULT_BODY_AXIS_FIT = {
    "z_min": 0.55,
    "z_max": 0.90,
    "x_half_width": 0.18,
    "front_weighted_y_quantile": 0.40,
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
