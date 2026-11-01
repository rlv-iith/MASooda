"""Tests for controlled near-collision STL verification encounters."""

from __future__ import annotations

import numpy as np

from verification.near_collision import run_near_collision


def test_near_collision_safe_case() -> None:
    """closest_gap_m = 20 (safe): rho(t) > 0 at every tick, violation_count == 0."""
    mon_safe = run_near_collision(closest_gap_m=20.0, duration_s=10.0)

    assert mon_safe.violation_count() == 0
    assert mon_safe.min_robustness() > 0.0
    # Minimum separation is 20m, safety threshold d_min is 8m -> min rho is 12m
    assert np.isclose(mon_safe.min_robustness(), 12.0)
    for record in mon_safe.history:
        assert record["rho"] > 0.0


def test_near_collision_unsafe_case() -> None:
    """closest_gap_m = 3 (unsafe): rho > 0 at start/end, rho < 0 around 5s, min rho ~ -5."""
    mon_unsafe = run_near_collision(closest_gap_m=3.0, duration_s=10.0)

    # 1. rho(t) > 0 at the start and at the end
    assert mon_unsafe.history[0]["rho"] > 0.0
    assert mon_unsafe.history[-1]["rho"] > 0.0

    # 2. violation_count > 0
    assert mon_unsafe.violation_count() > 0

    # 3. rho(t) < 0 around the crossing time (~5.0 s)
    crossing_records = [r for r in mon_unsafe.history if 4.8 <= r["t"] <= 5.2]
    assert len(crossing_records) > 0
    for r in crossing_records:
        assert r["rho"] < 0.0

    # 4. The most negative rho is about 3 - 8 = -5 (within 0.5)
    min_rho = mon_unsafe.min_robustness()
    assert abs(min_rho - (-5.0)) <= 0.5

