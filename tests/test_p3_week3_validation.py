"""Validation tests for P3 Week 3: multi-agent corridor merge scenario."""

from __future__ import annotations

import numpy as np
import pytest

from scripts.p3_week3_merge_demo import run_merge_scenario


def test_merge_scenario_validation():
    """Run merge scenario with enough agents and duration to pass the merge zone at v_cruise.

    Asserts:
    - No NaN in positions, velocities, or accelerations
    - Merge success rate == 1.0
    - Every crossing happened at x >= merge zone start
    - Min pairwise distance >= 8.0 m
    """
    pos_history, agent_ids, metrics = run_merge_scenario(n_agents=8, duration_s=75.0, seed=0)

    # 1. No NaN
    assert not metrics["has_nan"]
    assert not np.isnan(pos_history).any()

    # 2. Merge success rate == 1.0
    assert metrics["merge_success_rate"] == 1.0

    # 3. Every crossing happened at x >= merge zone start
    merge_start = metrics["merge_start"]
    merging_agents = [
        aid for aid in agent_ids
        if metrics["target_corridors"][aid] != metrics["start_corridors"][aid]
    ]
    assert len(merging_agents) > 0
    for aid in merging_agents:
        cx = metrics["crossing_x"][aid]
        assert cx is not None
        assert cx >= merge_start

    # 4. Min pairwise distance >= 8.0 m
    assert metrics["min_pairwise_distance"] >= 8.0
