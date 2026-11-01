"""Tests for P3 Week 3: Merging behavior and gap checking in target corridor."""

from __future__ import annotations

import numpy as np
import pytest

from config.load_config import get_config
from local_behavior import boids
from local_behavior.boids import (
    compute_desired_velocity,
    merge_adjustment,
)
from simulation.schema import AgentState, AgentType, OverseerDirective


@pytest.fixture(autouse=True)
def clean_corridor_cache():
    """Reset the module-level _last_corridor dict between tests."""
    boids._last_corridor.clear()
    yield
    boids._last_corridor.clear()


def make_agent(
    agent_id: int = 0,
    x: float = 750.0,
    y: float = 0.0,
    vx: float = 10.0,
    vy: float = 0.0,
    corridor: int | None = 0,
    dest_x: float = 1450.0,
    dest_y: float = 0.0,
) -> AgentState:
    """Helper to create an AgentState."""
    return AgentState(
        id=agent_id,
        type=AgentType.DELIVERY,
        position=np.array([x, y, 0.0], dtype=float),
        velocity=np.array([vx, vy, 0.0], dtype=float),
        acceleration=np.array([0.0, 0.0, 0.0], dtype=float),
        destination=np.array([dest_x, dest_y, 0.0], dtype=float),
        corridor_assignment=corridor,
    )


def test_merging_agent_empty_target_corridor():
    """Merging agent with an empty target corridor -> vy > 0 and |vy| <= merge_lateral_speed."""
    cfg = get_config()
    merge_lat_speed = float(cfg["local_behavior"]["merge_lateral_speed"])

    # Agent at x=750 (in merge zone [700, 800]) in corridor 0 (y=0) with target corridor 1 (y=50)
    agent = make_agent(agent_id=0, x=750.0, y=0.0, corridor=0)
    directive = OverseerDirective(
        corridor_map={0: 1},
        priority_table={},
        altitude_map={},
        timestamp=0.0,
    )

    v_des = compute_desired_velocity(agent, [], directive)

    # Desired lateral velocity must be positive (towards corridor 1) and capped at merge_lateral_speed
    assert v_des[1] > 0.0
    assert abs(v_des[1]) <= merge_lat_speed + 1e-9


def test_merging_agent_blocked_by_neighbor_ahead():
    """Merging agent with a neighbor in the target corridor 5 m ahead -> vy == 0 and vx smaller than in the empty case."""
    agent = make_agent(agent_id=0, x=750.0, y=0.0, corridor=0)
    directive = OverseerDirective(
        corridor_map={0: 1},
        priority_table={},
        altitude_map={},
        timestamp=0.0,
    )

    # Neighbor in target corridor 1 (y=50) 5 m ahead along x (755 m vs 750 m)
    neighbor = make_agent(agent_id=1, x=755.0, y=50.0, corridor=1)

    v_des_empty = compute_desired_velocity(agent, [], directive)
    v_des_blocked = compute_desired_velocity(agent, [neighbor], directive)

    # vy must be zero (stays in current lane)
    assert abs(v_des_blocked[1]) < 1e-6
    # vx must be smaller than in the empty case (reduced forward speed)
    assert v_des_blocked[0] < v_des_empty[0]


def test_non_merging_agent_identical_output():
    """Non-merging agent -> output identical to before this change (vy ~ 0 on the centerline)."""
    # Agent at corridor 0 centerline with target corridor 0 (not merging)
    agent = make_agent(agent_id=0, x=750.0, y=0.0, corridor=0)
    directive = OverseerDirective(
        corridor_map={0: 0},
        priority_table={},
        altitude_map={},
        timestamp=0.0,
    )

    v_des = compute_desired_velocity(agent, [], directive)

    # Agent maintains forward motion on centerline with zero lateral velocity
    assert v_des[0] > 0.0
    assert abs(v_des[1]) < 1e-6
