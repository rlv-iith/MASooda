"""P2 Week 2 unit tests: ADMM from_config, non-convergence tracking, adapter, and interfaces."""

from __future__ import annotations

import numpy as np

from config.load_config import get_config
from conflict_resolution.adapter import resolve_conflict_event
from conflict_resolution.solver import ADMMSolver
from simulation.interfaces import resolve_conflict
from simulation.schema import AgentState, AgentType


def test_from_config_defaults():
    solver = ADMMSolver.from_config()
    assert np.isclose(solver.d_safe, 8.08)
    assert solver.max_iters == 50


def test_two_agents_head_on_separation():
    dt = float(get_config()["simulation"]["timestep_seconds"])
    a1 = AgentState(
        id=1,
        type=AgentType.EVTOL,
        position=np.array([-5.0, 0.0, 0.0]),
        velocity=np.array([10.0, 0.0, 0.0]),
    )
    a2 = AgentState(
        id=2,
        type=AgentType.DELIVERY,
        position=np.array([5.0, 0.0, 0.0]),
        velocity=np.array([-10.0, 0.0, 0.0]),
    )

    event = resolve_conflict_event([a1, a2])
    assert event.converged

    next_p1 = a1.position[:2] + event.resolution[1][:2] * dt
    next_p2 = a2.position[:2] + event.resolution[2][:2] * dt
    dist = float(np.linalg.norm(next_p1 - next_p2))

    # Next positions are at least 8 m apart
    assert dist >= 8.0 - 1e-3


def test_max_iters_1_on_close_agents_returns_converged_false_and_finite():
    solver = ADMMSolver.from_config(max_iters=1)
    pos = np.array([[-1.0, 0.0], [1.0, 0.0], [0.0, -1.0], [0.0, 1.0]], dtype=float)
    tgt = np.zeros_like(pos)
    result = solver.solve(pos, tgt)

    assert not result.converged
    assert np.all(np.isfinite(result.positions))


def test_resolve_conflict_returns_dict_of_3_number_arrays():
    a1 = AgentState(
        id=10,
        type=AgentType.EMERGENCY,
        position=np.array([0.0, 0.0, 1.0]),
        velocity=np.array([5.0, 0.0, 0.0]),
    )
    a2 = AgentState(
        id=20,
        type=AgentType.DELIVERY,
        position=np.array([10.0, 0.0, 1.0]),
        velocity=np.array([-5.0, 0.0, 0.0]),
    )

    res = resolve_conflict([a1, a2])
    assert isinstance(res, dict)
    assert set(res.keys()) == {10, 20}
    for aid, vel in res.items():
        assert isinstance(vel, np.ndarray)
        assert vel.shape == (3,)
        assert np.all(np.isfinite(vel))
