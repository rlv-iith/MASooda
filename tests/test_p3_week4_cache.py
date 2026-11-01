"""Tests for P3 Week 4: Local behavior cache reset and fallback cases."""

from __future__ import annotations

import numpy as np
import pytest

from local_behavior.boids import (
    compute_desired_velocity,
    reset_local_behavior_cache,
    target_corridor,
)
from simulation.schema import AgentState, AgentType, OverseerDirective


@pytest.fixture(autouse=True)
def clean_cache():
    """Ensure cache is reset before and after every test."""
    reset_local_behavior_cache()
    yield
    reset_local_behavior_cache()


def make_agent(
    agent_id: int = 0,
    x: float = 100.0,
    y: float = 0.0,
    corridor: int | None = 0,
    dest_x: float = 1450.0,
    dest_y: float = 0.0,
) -> AgentState:
    """Helper to create an AgentState for testing."""
    return AgentState(
        id=agent_id,
        type=AgentType.DELIVERY,
        position=np.array([x, y, 0.0], dtype=float),
        velocity=np.array([10.0, 0.0, 0.0], dtype=float),
        acceleration=np.array([0.0, 0.0, 0.0], dtype=float),
        destination=np.array([dest_x, dest_y, 0.0], dtype=float),
        corridor_assignment=corridor,
    )


def test_reset_local_behavior_cache_clears_stale_corridor():
    """Calling reset_local_behavior_cache clears cached directives across runs."""
    agent = make_agent(agent_id=0, corridor=0)
    directive = OverseerDirective(
        corridor_map={0: 2},
        priority_table={},
        altitude_map={},
        timestamp=0.0,
    )

    # First call with directive mapping agent 0 -> corridor 2
    v1 = compute_desired_velocity(agent, [], directive)
    assert np.all(np.isfinite(v1))
    assert target_corridor(agent, None) == 2

    # Reset cache
    reset_local_behavior_cache()

    # Second call with directive=None for agent 0 with corridor_assignment=0
    v2 = compute_desired_velocity(agent, [], None)
    assert np.all(np.isfinite(v2))
    assert target_corridor(agent, None) == 0


def test_missing_directive_fallback():
    """Failure case #3: After one call with a directive, target_corridor(agent, None) returns cached target."""
    agent = make_agent(agent_id=0, corridor=0)
    directive = OverseerDirective(
        corridor_map={0: 1},
        priority_table={},
        altitude_map={},
        timestamp=0.0,
    )

    # Call with directive (agent 0 -> corridor 1)
    target = target_corridor(agent, directive)
    assert target == 1

    # Missing directive fallback on subsequent call
    assert target_corridor(agent, None) == 1


def test_no_neighbors_returns_finite_forward_vector():
    """Failure case #2: compute_desired_velocity with empty neighbor list returns finite 3-vector toward destination."""
    agent = make_agent(agent_id=0, x=100.0, y=0.0, dest_x=1450.0, dest_y=0.0, corridor=0)

    v_des = compute_desired_velocity(agent, [], None)
    assert isinstance(v_des, np.ndarray)
    assert v_des.shape == (3,)
    assert np.all(np.isfinite(v_des))
    # Pointing towards destination with positive x component
    assert v_des[0] > 0.0
