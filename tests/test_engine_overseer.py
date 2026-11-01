"""Tests for simulation engine overseer integration."""

from __future__ import annotations

import pytest
import numpy as np

from simulation.engine import run_simulation
from simulation.scenario import make_initial_agents


@pytest.fixture(autouse=True)
def clean_boids_cache():
    """Clean module-level boids cache after tests to avoid polluting legacy tests."""
    yield
    try:
        import local_behavior.boids as boids
        boids._last_corridor.clear()
    except Exception:
        pass


def test_engine_overseer_periodic_calls() -> None:
    """10 agents, 10 s: overseer_calls == 5, overseer_failures == 0, no NaN positions."""
    agents = make_initial_agents(10, seed=42)
    result = run_simulation(agents, duration_s=10.0, use_overseer=True)

    # 10s with dt=0.1 -> 100 steps. Period is 2.0s -> 20 steps.
    # Steps 0, 20, 40, 60, 80 -> 5 calls
    assert result.overseer_calls == 5
    assert result.overseer_failures == 0
    assert np.all(np.isfinite(result.positions))


def test_engine_overseer_disabled() -> None:
    """use_overseer=False: overseer_calls == 0."""
    agents = make_initial_agents(10, seed=42)
    result = run_simulation(agents, duration_s=10.0, use_overseer=False)

    assert result.overseer_calls == 0
    assert result.overseer_failures == 0
    assert np.all(np.isfinite(result.positions))


def test_engine_overseer_exception_resilience(monkeypatch: pytest.MonkeyPatch) -> None:
    """Overseer exception does not crash simulation and increments overseer_failures."""
    agents = make_initial_agents(10, seed=42)

    def failing_overseer(snapshot):
        raise ConnectionError("Simulated overseer communication link failure")

    monkeypatch.setattr("simulation.interfaces.overseer_update", failing_overseer)
    monkeypatch.setattr("simulation.engine.overseer_update", failing_overseer)

    result = run_simulation(agents, duration_s=10.0, use_overseer=True)

    assert result.overseer_calls == 5
    assert result.overseer_failures > 0
    assert result.overseer_failures == 5
    assert np.all(np.isfinite(result.positions))
