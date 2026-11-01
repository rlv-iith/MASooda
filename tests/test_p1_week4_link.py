"""Tests for P1 Week 4 overseer link down failure and safe fallbacks."""

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


def test_overseer_link_down_staleness() -> None:
    """Overseer link down tracks dropped requests and maximum directive staleness."""
    pytest.importorskip("simulation.overseer_link")
    link_config = {
        "enabled": True,
        "down_start_seconds": 2.0,
        "down_end_seconds": 6.0,
    }
    agents = make_initial_agents(10, seed=42)
    result = run_simulation(agents, duration_s=10.0, overseer_link_config=link_config)

    assert result.stats["overseer_dropped"] > 0
    assert result.stats["max_directive_staleness_s"] >= 3.9
    assert np.all(np.isfinite(result.positions))


def test_update_local_behavior_failure_resilience(monkeypatch: pytest.MonkeyPatch) -> None:
    """Failure in update_local_behavior falls back to current velocity and increments component_failures."""
    agents = make_initial_agents(10, seed=42)

    def failing_local_behavior(agent, neighbours, directive):
        raise RuntimeError("Simulated local behavior calculation failure")

    monkeypatch.setattr(simulation.engine, "update_local_behavior", failing_local_behavior)

    result = run_simulation(agents, duration_s=2.0)

    assert result.stats["component_failures"] > 0
    assert np.all(np.isfinite(result.positions))

