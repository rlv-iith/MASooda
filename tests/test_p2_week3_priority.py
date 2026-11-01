"""P2 Week 3 unit tests: Priority-weighted ADMM conflict resolution."""

from __future__ import annotations

import numpy as np

from config.load_config import get_config
from conflict_resolution.adapter import resolve_conflict_event
from conflict_resolution.solver import ADMMSolver
from simulation.schema import AgentState, AgentType


def test_priorities_none_matches_old_behaviour():
    """With priorities=None the output equals the old behaviour (all weights 1.0)."""
    solver = ADMMSolver.from_config()
    dt = solver.dt

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

    # 1. Output with priorities=None equals output with default argument
    event_none = resolve_conflict_event([a1, a2], priorities=None)
    event_default = resolve_conflict_event([a1, a2])

    assert event_none.converged
    assert event_default.converged
    assert np.allclose(event_none.resolution[1], event_default.resolution[1])
    assert np.allclose(event_none.resolution[2], event_default.resolution[2])

    # 2. Compare directly with ADMMSolver without weights vs weights=ones
    pos = np.array([a1.position[:2], a2.position[:2]], dtype=float)
    tgt = pos + np.array([a1.velocity[:2], a2.velocity[:2]], dtype=float) * dt

    res_none = solver.solve(pos, tgt, weights=None)
    res_ones = solver.solve(pos, tgt, weights=np.ones(2, dtype=float))

    assert np.array_equal(res_none.positions, res_ones.positions)

    # 3. Verify event resolution matches solver output
    expected_v1 = (res_none.positions[0] - pos[0]) / dt
    expected_v2 = (res_none.positions[1] - pos[1]) / dt
    assert np.allclose(event_none.resolution[1][:2], expected_v1)
    assert np.allclose(event_none.resolution[2][:2], expected_v2)


def test_head_on_emergency_vs_delivery():
    """Head-on case with EMERGENCY (priority 0) and DELIVERY (priority 2).

    The emergency agent's resolved velocity must change LESS (smaller norm of velocity change)
    than the delivery agent's resolved velocity.
    """
    dt = float(get_config()["simulation"]["timestep_seconds"])

    a1 = AgentState(
        id=1,
        type=AgentType.EMERGENCY,
        position=np.array([-5.0, 0.0, 0.0]),
        velocity=np.array([10.0, 0.0, 0.0]),
        priority=0,
    )
    a2 = AgentState(
        id=2,
        type=AgentType.DELIVERY,
        position=np.array([5.0, 0.0, 0.0]),
        velocity=np.array([-10.0, 0.0, 0.0]),
        priority=2,
    )

    event = resolve_conflict_event([a1, a2], priorities={1: 0, 2: 2})
    assert event.converged

    # Compute norm of velocity changes
    dv1 = float(np.linalg.norm(event.resolution[1] - a1.velocity))
    dv2 = float(np.linalg.norm(event.resolution[2] - a2.velocity))

    # Emergency agent changes velocity LESS than delivery agent
    assert dv1 < dv2
    # Because priority weight ratio is 10.0 vs 1.0, delivery yields significantly more
    assert dv2 > 5.0 * dv1

    # Separation safety must still be maintained
    next_p1 = a1.position[:2] + event.resolution[1][:2] * dt
    next_p2 = a2.position[:2] + event.resolution[2][:2] * dt
    separation = float(np.linalg.norm(next_p1 - next_p2))
    assert separation >= 8.0 - 1e-3


def test_missing_agent_in_priorities_defaults_to_priority_2():
    """Agents missing from priorities dict use weight for priority 2."""
    a1 = AgentState(
        id=10,
        type=AgentType.EMERGENCY,
        position=np.array([-5.0, 0.0, 0.0]),
        velocity=np.array([10.0, 0.0, 0.0]),
    )
    a2 = AgentState(
        id=20,
        type=AgentType.DELIVERY,
        position=np.array([5.0, 0.0, 0.0]),
        velocity=np.array([-10.0, 0.0, 0.0]),
    )

    # Missing agent 20 in priorities dict
    event_partial = resolve_conflict_event([a1, a2], priorities={10: 0})
    # Explicitly specifying priority 2 for agent 20
    event_explicit = resolve_conflict_event([a1, a2], priorities={10: 0, 20: 2})

    assert event_partial.converged
    assert event_explicit.converged
    assert np.allclose(event_partial.resolution[10], event_explicit.resolution[10])
    assert np.allclose(event_partial.resolution[20], event_explicit.resolution[20])


def test_relative_priority_ordering():
    """EMERGENCY (0) yields less than EVTOL (1), which yields less than DELIVERY (2)."""
    solver = ADMMSolver.from_config()
    dt = solver.dt

    pos = np.array([[-5.0, 0.0], [5.0, 0.0]])
    tgt = pos + np.array([[10.0, 0.0], [-10.0, 0.0]]) * dt

    cfg = get_config()
    pw = cfg["admm"]["priority_weights"]
    w0 = float(pw[0])  # 10.0
    w1 = float(pw[1])  # 3.0
    w2 = float(pw[2])  # 1.0

    # EMERGENCY vs EVTOL
    res_01 = solver.solve(pos, tgt, weights=np.array([w0, w1]))
    dv_0 = np.linalg.norm(res_01.positions[0] - tgt[0])
    dv_1 = np.linalg.norm(res_01.positions[1] - tgt[1])
    assert dv_0 < dv_1

    # EVTOL vs DELIVERY
    res_12 = solver.solve(pos, tgt, weights=np.array([w1, w2]))
    dv_evtol = np.linalg.norm(res_12.positions[0] - tgt[0])
    dv_delivery = np.linalg.norm(res_12.positions[1] - tgt[1])
    assert dv_evtol < dv_delivery


def test_solver_weights_direct():
    """Test weights handling in ADMMSolver.solve directly."""
    solver = ADMMSolver(d_safe=2.0, v_max=5.0, dt=1.0)
    pos = np.array([[-1.0, 0.0], [1.0, 0.0]])
    tgt = np.array([[0.5, 0.0], [-0.5, 0.0]])

    # weights=None vs weights=ones must be strictly identical
    res_none = solver.solve(pos, tgt, weights=None)
    res_ones = solver.solve(pos, tgt, weights=np.ones(2))
    assert np.array_equal(res_none.positions, res_ones.positions)

    # Asymmetric weights: agent 0 has much higher weight
    res_asym = solver.solve(pos, tgt, weights=np.array([100.0, 1.0]))
    shift_0 = np.linalg.norm(res_asym.positions[0] - tgt[0])
    shift_1 = np.linalg.norm(res_asym.positions[1] - tgt[1])
    assert shift_0 < shift_1
