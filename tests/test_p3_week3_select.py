"""Tests for P3 Week 3: Corridor selection and lane change gating via merge zone."""

from __future__ import annotations

import numpy as np
import pytest

from local_behavior import boids
from local_behavior.boids import (
    active_corridor,
    compute_desired_velocity,
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
    x: float = 100.0,
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


def test_agent_before_merge_zone_keeps_lane():
    """Agent in corridor 0 at x=100 with directive saying corridor 1 -> desired vy is ~0 (|vy| < 0.5)."""
    agent = make_agent(agent_id=0, x=100.0, y=0.0, corridor=0)
    directive = OverseerDirective(
        corridor_map={0: 1},
        priority_table={},
        altitude_map={},
        timestamp=0.0,
    )

    act_corr = active_corridor(agent, 1)
    assert act_corr == 0

    v_des = compute_desired_velocity(agent, [], directive)
    assert abs(v_des[1]) < 0.5


def test_agent_inside_merge_zone_moves_toward_target():
    """Same agent at x=750 -> desired vy > 0 (moves toward corridor 1, which has larger y)."""
    agent = make_agent(agent_id=0, x=750.0, y=0.0, corridor=0)
    directive = OverseerDirective(
        corridor_map={0: 1},
        priority_table={},
        altitude_map={},
        timestamp=0.0,
    )

    act_corr = active_corridor(agent, 1)
    assert act_corr == 1

    v_des = compute_desired_velocity(agent, [], directive)
    assert v_des[1] > 0.0


def test_directive_none_and_no_cache_keeps_current_corridor():
    """Directive None and no cache -> agent keeps its current corridor."""
    boids._last_corridor.clear()
    agent = make_agent(agent_id=0, x=100.0, y=0.0, corridor=None)

    act_corr = active_corridor(agent, None)
    assert act_corr == 0

    v_des = compute_desired_velocity(agent, [], None)
    assert abs(v_des[1]) < 0.5
