"""Weighted Mean-Subsequence-Reduced filtering for resilient consensus."""

from __future__ import annotations

import numpy as np


def _validate_f(f: int) -> int:
    if isinstance(f, bool) or not isinstance(f, (int, np.integer)) or f < 0:
        raise ValueError("f must be a non-negative integer")
    return int(f)


def wmsr_scalar(own: float, values: list[float], f: int) -> float:
    """Trim up to ``f`` extreme neighbor reports on each side of ``own``."""
    f = _validate_f(f)
    reports = [float(value) for value in values]
    own_value = float(own)

    if len(reports) <= 2 * f:
        return float(np.median([own_value, *reports]))

    larger = sorted(value for value in reports if value > own_value)
    smaller = sorted(value for value in reports if value < own_value)
    equal = [value for value in reports if value == own_value]
    kept_larger = larger[: max(0, len(larger) - f)]
    kept_smaller = smaller[min(f, len(smaller)) :]
    return float(np.mean([own_value, *kept_larger, *kept_smaller, *equal]))


def wmsr_vector(own: np.ndarray, values: list[np.ndarray], f: int) -> np.ndarray:
    """Apply W-MSR independently to each coordinate of vector reports."""
    f = _validate_f(f)
    own_array = np.asarray(own, dtype=float)
    report_arrays = [np.asarray(value, dtype=float) for value in values]
    if own_array.ndim != 1 or any(value.shape != own_array.shape for value in report_arrays):
        raise ValueError("own and neighbor reports must be vectors with matching shapes")

    if len(report_arrays) <= 2 * f:
        return np.median(np.stack([own_array, *report_arrays]), axis=0)
    return np.array(
        [wmsr_scalar(own_array[i], [value[i] for value in report_arrays], f)
         for i in range(own_array.size)],
        dtype=float,
    )
