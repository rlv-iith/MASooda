"""Tests for the P2 Week 5 ADMM profiling wrapper and scaling experiment."""

from __future__ import annotations

import math

import numpy as np
import pytest

from conflict_resolution.adapter import resolve_conflict_event
from conflict_resolution.profiling import ADMMRecorder, summarize
from conflict_resolution.solver import ADMMSolver
from simulation.schema import AgentState, AgentType


# ------------------------------------------------------------------ #
#  Test 1: head-on conflict produces at least 1 record with correct  #
#  group_size and iterations >= 1.                                    #
# ------------------------------------------------------------------ #

def test_head_on_produces_records():
    """Two agents 5 m apart on a head-on course must trigger at least one
    solver call recorded by ADMMRecorder."""
    a = AgentState(id=0, type=AgentType.DELIVERY,
                   position=np.array([0.0, 0.0, 0.0]),
                   velocity=np.array([12.0, 0.0, 0.0]))
    b = AgentState(id=1, type=AgentType.DELIVERY,
                   position=np.array([5.0, 0.0, 0.0]),
                   velocity=np.array([-12.0, 0.0, 0.0]))

    with ADMMRecorder() as rec:
        resolve_conflict_event([a, b])

    assert len(rec.records) >= 1, "Expected at least 1 solver record"
    r = rec.records[0]
    assert r["group_size"] == 2
    assert r["iterations"] >= 1
    assert isinstance(r["converged"], bool)
    assert r["solve_time_s"] > 0.0


# ------------------------------------------------------------------ #
#  Test 2: ADMMSolver.solve is restored after the with-block — both  #
#  on normal exit and after an exception.                             #
# ------------------------------------------------------------------ #

def test_restore_on_normal_exit():
    original = ADMMSolver.solve
    with ADMMRecorder():
        assert ADMMSolver.solve is not original
    assert ADMMSolver.solve is original


def test_restore_on_exception():
    original = ADMMSolver.solve
    with pytest.raises(RuntimeError):
        with ADMMRecorder():
            assert ADMMSolver.solve is not original
            raise RuntimeError("deliberate")
    assert ADMMSolver.solve is original


# ------------------------------------------------------------------ #
#  Test 3: summarize edge cases                                       #
# ------------------------------------------------------------------ #

def test_summarize_empty():
    s = summarize([])
    assert s["count"] == 0
    assert math.isnan(s["mean_iterations"])
    assert math.isnan(s["p95_iterations"])
    assert math.isnan(s["max_iterations"])
    assert math.isnan(s["mean_solve_ms"])
    assert math.isnan(s["p95_solve_ms"])
    assert math.isnan(s["fraction_converged"])


def test_summarize_correct_mean():
    records = [
        {"iterations": 10, "converged": True, "solve_time_s": 0.001},
        {"iterations": 20, "converged": True, "solve_time_s": 0.003},
        {"iterations": 30, "converged": False, "solve_time_s": 0.005},
    ]
    s = summarize(records)
    assert s["count"] == 3
    assert abs(s["mean_iterations"] - 20.0) < 1e-9
    assert s["max_iterations"] == 30.0
    assert abs(s["mean_solve_ms"] - 3.0) < 1e-9
    assert abs(s["fraction_converged"] - 2.0 / 3.0) < 1e-9


# ------------------------------------------------------------------ #
#  Test 4: tiny simulation inside the recorder runs without error     #
# ------------------------------------------------------------------ #

def test_tiny_simulation_with_recorder():
    import simulation.overseer
    import local_behavior.boids
    import simulation.engine
    from simulation.scenario import make_initial_agents
    from config.load_config import get_config

    simulation.overseer.reset_default_overseer()
    local_behavior.boids.reset_local_behavior_cache()

    cfg = get_config()
    agents = make_initial_agents(10, seed=42)

    with ADMMRecorder() as rec:
        rec.current_tag = {"N": 10, "seed": 42}
        result = simulation.engine.run_simulation(
            agents,
            duration_s=3.0,
            use_overseer=True,
            use_admm=True,
            attack_config={**cfg["attack"], "enabled": False},
            defended=True,
            overseer_link_config={"enabled": False},
        )

    assert result is not None
    assert len(result.times) > 1
    # Recorder may or may not have captured calls (depends on conflicts);
    # the important thing is it did not crash.
    for r in rec.records:
        assert r["N"] == 10
        assert r["seed"] == 42
