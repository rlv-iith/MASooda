"""Tests for P2 Week 2 ADMM conflict resolution."""
from __future__ import annotations

import numpy as np
import pytest

from config.load_config import get_config
from conflict_resolution.adapter import resolve_conflict_event
from conflict_resolution.solver import ADMMSolver
from simulation.interfaces import resolve_conflict
from simulation.schema import AgentState, AgentType, ConflictEvent


def test_from_config_defaults():
    solver = ADMMSolver.from_config()
    assert pytest.approx(solver.d_safe, abs=1e-3) == 8.08
    assert solver.max_iters == 50


def test_two_agents_head_on_separation():
    # Two agents 10 m apart flying head-on at 10 m/s
    a = AgentState(
        id=1,
        type=AgentType.EVTOL,
        position=np.array([-5.0, 0.0, 0.0]),
        velocity=np.array([10.0, 0.0, 0.0]),
    )
    b = AgentState(
        id=2,
        type=AgentType.DELIVERY,
        position=np.array([5.0, 0.0, 0.0]),
        velocity=np.array([-10.0, 0.0, 0.0]),
    )

    cfg = get_config()
    dt = float(cfg["simulation"]["timestep_seconds"])

    event = resolve_conflict_event([a, b])
    assert isinstance(event, ConflictEvent)
    assert event.converged

    # next positions (position + resolved velocity * dt)
    next_pos_a = a.position + event.resolution[a.id] * dt
    next_pos_b = b.position + event.resolution[b.id] * dt

    sep = float(np.linalg.norm(next_pos_a[:2] - next_pos_b[:2]))
    assert sep >= 8.0


def test_max_iters_1_on_close_agents_not_converged_and_finite():
    solver = ADMMSolver.from_config()
    solver.max_iters = 1

    # 4 close agents targeting the same centre point
    positions = np.array([
        [-1.0, 0.0],
        [1.0, 0.0],
        [0.0, -1.0],
        [0.0, 1.0],
    ])
    targets = np.zeros_like(positions)

    result = solver.solve(positions, targets)
    assert not result.converged
    assert np.all(np.isfinite(result.positions))


def test_resolve_conflict_returns_dict_of_3_number_arrays():
    a = AgentState(
        id=10,
        type=AgentType.EVTOL,
        position=np.array([0.0, 0.0, 0.0]),
        velocity=np.array([5.0, 0.0, 0.0]),
    )
    b = AgentState(
        id=20,
        type=AgentType.DELIVERY,
        position=np.array([1.0, 0.0, 0.0]),
        velocity=np.array([-5.0, 0.0, 0.0]),
    )

    out = resolve_conflict([a, b])
    assert isinstance(out, dict)
    assert set(out.keys()) == {10, 20}
    for agent_id, vel in out.items():
        assert isinstance(vel, np.ndarray)
        assert vel.shape == (3,)
        assert np.all(np.isfinite(vel))


def test_resolve_conflict_event_safe_on_bad_input():
    # Agent with missing or corrupted velocity
    bad_agent = AgentState(id=99, type=AgentType.EMERGENCY)
    bad_agent.velocity = None  # type: ignore

    event = resolve_conflict_event([bad_agent])
    assert isinstance(event, ConflictEvent)
    assert not event.converged
    assert 99 in event.resolution
    assert np.all(np.isfinite(event.resolution[99]))
