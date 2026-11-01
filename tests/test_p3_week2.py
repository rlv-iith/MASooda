"""Tests for P3 Week 2: Boids local behavior and corridor following."""

from __future__ import annotations

import numpy as np
import pytest

from config.load_config import get_config
from local_behavior.boids import (
    _last_corridor,
    alignment,
    cohesion,
    compute_desired_velocity,
    corridor_following,
    corridor_of,
    separation,
    target_corridor,
)
from simulation.interfaces import update_local_behavior
from simulation.overseer import mock_overseer_update
from simulation.schema import AgentState, AgentType, GlobalStateSnapshot


@pytest.fixture(autouse=True)
def clean_corridor_cache():
    """Clear module-level cached corridor map before each test."""
    _last_corridor.clear()
    yield
    _last_corridor.clear()


def make_agent(
    agent_id: int = 0,
    x: float = 10.0,
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


def test_no_neighbors_points_forward_and_toward_centerline():
    """No neighbors: output points forward (+x) and toward the corridor centerline."""
    # Agent in corridor 0 (centerline y = 0.0), positioned at y = 5.0 (above centerline)
    agent_above = make_agent(agent_id=0, x=50.0, y=5.0, vx=10.0, vy=0.0, corridor=0, dest_y=0.0)
    v_des_above = compute_desired_velocity(agent_above, [], None)

    # Must point forward (+x)
    assert v_des_above[0] > 0.0
    # Must point toward centerline (y=0), so vy must be negative
    assert v_des_above[1] < 0.0

    # Agent in corridor 0, positioned at y = -5.0 (below centerline)
    agent_below = make_agent(agent_id=1, x=50.0, y=-5.0, vx=10.0, vy=0.0, corridor=0, dest_y=0.0)
    v_des_below = compute_desired_velocity(agent_below, [], None)

    assert v_des_below[0] > 0.0
    # Must point toward centerline (y=0), so vy must be positive
    assert v_des_below[1] > 0.0


def test_two_agents_5m_apart_separation_pushes_away():
    """Two agents 5 m apart: the separation term pushes them away from each other."""
    agent_a = make_agent(agent_id=0, x=20.0, y=0.0)
    agent_b = make_agent(agent_id=1, x=25.0, y=0.0)

    sep_a = separation(agent_a, [agent_b])
    sep_b = separation(agent_b, [agent_a])

    # Agent A is behind Agent B; separation should push Agent A in -x direction
    assert sep_a[0] < 0.0
    # Agent B is ahead of Agent A; separation should push Agent B in +x direction
    assert sep_b[0] > 0.0

    # Opposite equal separation
    assert np.allclose(sep_a, -sep_b)


def test_same_corridor_neighbor_moving_faster_increases_x_velocity():
    """A same-corridor neighbor moving faster increases the output x-velocity (alignment)."""
    # Agent at x=10 with vx=10
    agent = make_agent(agent_id=0, x=10.0, y=0.0, vx=10.0, vy=0.0, corridor=0)

    # Neighbor far enough (x=50, dist=40 > r_sep=20) so separation & cohesion don't interfere
    faster_neighbor = make_agent(agent_id=1, x=50.0, y=0.0, vx=14.0, vy=0.0, corridor=0)

    ali_term = alignment(agent, [faster_neighbor])
    # Alignment term should be positive along x (14 - 10 = +4)
    assert ali_term[0] > 0.0

    v_alone = compute_desired_velocity(agent, [], None)
    v_with_faster = compute_desired_velocity(agent, [faster_neighbor], None)

    # Desired x velocity increases with faster neighbor in same corridor
    assert v_with_faster[0] > v_alone[0]


def test_cohesion_zero_when_neighbor_closer_than_r_sep():
    """Cohesion is zero when a same-corridor neighbor is closer than r_sep."""
    cfg = get_config()
    r_sep = float(cfg["local_behavior"]["r_sep"])

    agent = make_agent(agent_id=0, x=10.0, y=0.0, corridor=0)
    # Neighbor distance = 15.0 < r_sep (20.0)
    close_neighbor = make_agent(agent_id=1, x=10.0 + (r_sep - 5.0), y=0.0, corridor=0)

    coh = cohesion(agent, [close_neighbor])
    assert np.allclose(coh, [0.0, 0.0])

    # In contrast, when neighbor is farther than r_sep (e.g. dist = r_sep + 5.0), cohesion is non-zero
    far_neighbor = make_agent(agent_id=2, x=10.0 + (r_sep + 5.0), y=0.0, corridor=0)
    coh_far = cohesion(agent, [far_neighbor])
    assert coh_far[0] > 0.0


def test_output_length_and_z_zero():
    """Output length <= 15 and z == 0."""
    cfg = get_config()
    v_max = float(cfg["safety"]["maximum_velocity_meters_per_second"])
    assert v_max == 15.0

    # Agent with huge velocity requirement and many neighbors pushing
    agent = make_agent(agent_id=0, x=10.0, y=0.0, vx=20.0, vy=10.0, corridor=0)
    neighbors = [
        make_agent(agent_id=i, x=10.0 - 0.5 * i, y=0.0, vx=30.0, vy=10.0, corridor=0)
        for i in range(1, 5)
    ]

    v_des = compute_desired_velocity(agent, neighbors, None)

    speed = np.linalg.norm(v_des[:2])
    assert speed <= 15.0 + 1e-9
    assert v_des[2] == 0.0


def test_neighbor_at_same_position_no_nan():
    """A neighbor at exactly the same position gives no NaN."""
    agent = make_agent(agent_id=0, x=50.0, y=0.0, corridor=0)
    coincident_neighbor = make_agent(agent_id=1, x=50.0, y=0.0, corridor=0)

    sep = separation(agent, [coincident_neighbor])
    assert not np.isnan(sep).any()
    assert np.allclose(sep, [0.0, 0.0])

    v_des = compute_desired_velocity(agent, [coincident_neighbor], None)
    assert not np.isnan(v_des).any()


def test_cached_corridor_with_directive_none_after_mock_directive():
    """With directive None after one call with the mock directive, the agent keeps the cached corridor."""
    snapshot = GlobalStateSnapshot(
        timestamp=0.0,
        corridor_occupancy={0: 2, 1: 1},
        agent_ids=[0, 1, 2],
    )
    directive = mock_overseer_update(snapshot)

    # In mock directive, agent 2 is assigned to corridor 1
    # Create agent 2 without corridor_assignment
    agent_2 = make_agent(agent_id=2, x=20.0, y=50.0, corridor=None)

    # First call with directive
    corr_1 = target_corridor(agent_2, directive)
    assert corr_1 == 1

    # Second call with directive = None
    corr_cached = target_corridor(agent_2, None)
    assert corr_cached == 1

    # Velocity computation also retains corridor 1
    v_des = compute_desired_velocity(agent_2, [], None)
    # Target was corridor 1 (y = 50.0), agent is at y = 50.0, lateral term should be 0
    assert abs(v_des[1]) < 1e-6


def test_update_local_behavior_returns_three_number_array():
    """The update_local_behavior function in interfaces.py returns a 3-number array."""
    agent = make_agent(agent_id=0, x=10.0, y=0.0)
    neighbor = make_agent(agent_id=1, x=30.0, y=0.0)

    snapshot = GlobalStateSnapshot(timestamp=0.0, agent_ids=[0, 1])
    directive = mock_overseer_update(snapshot)

    result = update_local_behavior(agent, [neighbor], directive)

    assert isinstance(result, np.ndarray)
    assert result.shape == (3,)
    assert np.issubdtype(result.dtype, np.floating)
    assert not np.isnan(result).any()
    assert result[2] == 0.0
