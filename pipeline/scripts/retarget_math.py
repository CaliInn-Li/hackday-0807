"""Blender-independent math used by fixed SMPL-22 motion retargeting."""

import numpy as np


def accumulate_global_rotations(local_rotations, parents):
    rotations = np.asarray(local_rotations)
    if rotations.ndim != 4 or rotations.shape[-2:] != (3, 3):
        raise ValueError(f"Expected rotations[T,J,3,3], got {rotations.shape}")
    if rotations.shape[1] != len(parents):
        raise ValueError(
            f"Rotation joint count {rotations.shape[1]} != parent count {len(parents)}"
        )
    global_rotations = np.empty_like(rotations)
    for index, parent in enumerate(parents):
        if parent < 0:
            global_rotations[:, index] = rotations[:, index]
        elif parent >= index:
            raise ValueError(f"Parent {parent} must precede joint {index}")
        else:
            global_rotations[:, index] = (
                global_rotations[:, parent] @ rotations[:, index]
            )
    return global_rotations
