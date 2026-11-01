"""Tests for P3 Week 4: Multi-agent merge check with ADMM and global overseer."""

from __future__ import annotations

import pytest

from scripts.p3_week4_merge_check import run_check


@pytest.mark.parametrize("use_admm", [True, False])
def test_p3_week4_merge_check_20agents(use_admm: bool) -> None:
    """Run merge check loop for 20 agents and 20 seconds.

    Asserts:
    - No NaN in agent positions or velocities (num_nan_states == 0)
    - Minimum pairwise distance is positive (> 0.0)
    """
    res = run_check(n=20, duration=20.0, use_admm=use_admm, seed=42)

    # Assert no NaN
    assert res["num_nan_states"] == 0

    # Assert min distance > 0
    assert res["min_distance"] > 0.0
    assert res["min_pairwise_distance"] > 0.0
