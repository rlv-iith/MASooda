"""Tests for P1 Week 4 ADMM conflict resolution integration in the simulation engine."""

from __future__ import annotations

import numpy as np
import pytest

import simulation.engine
from simulation.engine import run_simulation
from simulation.scenario import make_initial_agents


@pytest.fixture(autouse=True)
def clean_boids_cache():
    """Clean module-level boids cache after each test to avoid state leakage."""
    yield
    try:
        import local_behavior.boids as boids
        boids._last_corridor.clear()
    except Exception:
        pass


def test_simulation_admm_stats() -> None:
    """run_simulation(make_initial_agents(10), duration_s=5.0) returns result.stats with 4 keys and no NaN."""
    agents = make_initial_agents(10, seed=42)
    result = run_simulation(agents, duration_s=5.0)

    expected_keys = {"admm_events", "admm_nonconverged", "admm_time_s", "component_failures"}
    assert expected_keys.issubset(result.stats.keys())
    assert np.all(np.isfinite(result.positions)), "Positions contain NaN or Inf"
    assert result.stats["component_failures"] == 0
    assert result.stats["admm_time_s"] >= 0.0


def test_simulation_admm_disabled() -> None:
    """use_admm=False gives stats['admm_events'] == 0."""
    agents = make_initial_agents(10, seed=42)
    result = run_simulation(agents, duration_s=5.0, use_admm=False)

    assert result.stats["admm_events"] == 0
    assert result.stats["admm_time_s"] == 0.0
    assert result.stats["component_failures"] == 0
    assert np.all(np.isfinite(result.positions))


def test_simulation_admm_monkeypatch_resilience(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulated ADMM conflict resolution failure does not crash the run and increments component_failures."""
    agents = make_initial_agents(10, seed=42)

    def failing_resolve_all_conflicts(agent_states, priorities=None):
        raise RuntimeError("Simulated ADMM conflict resolution failure")

    monkeypatch.setattr(simulation.engine, "resolve_all_conflicts", failing_resolve_all_conflicts)

    result = run_simulation(agents, duration_s=5.0, use_admm=True)

    assert result.stats["component_failures"] > 0
    assert np.all(np.isfinite(result.positions))


def test_simulation_admm_zero_agents() -> None:
    """Zero agents returns stats with the four keys set to zero."""
    result = run_simulation([], duration_s=5.0)

    expected_keys = {"admm_events", "admm_nonconverged", "admm_time_s", "component_failures"}
    assert expected_keys.issubset(result.stats.keys())
    assert result.stats["admm_events"] == 0
    assert result.stats["admm_nonconverged"] == 0
    assert result.stats["admm_time_s"] == 0.0
    assert result.stats["component_failures"] == 0
