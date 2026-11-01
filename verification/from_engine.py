"""Extract STL verification trajectory windows from simulation results."""
from __future__ import annotations

from typing import Any
import numpy as np


def window_from_result(result: Any) -> np.ndarray:
    return np.asarray(result.positions[:, :, :2], dtype=float)

