"""Tests for P1 Week 4 attack injection and defence integration in simulation/engine.py."""

from __future__ import annotations

import numpy as np
import pytest

from config.load_config import get_config
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


def test_attack_active() -> None:
    """Running with enabled attack increments attack_active_ticks and tracks malicious_ids."""
    attack_config = {
        **get_config()["attack"],
        "enabled": True,
        "start_time_seconds": 1.0,
        "malicious_ids": [0],
    }
    agents = make_initial_agents(10, seed=42)
    result = run_simulation(agents, duration_s=3.0, attack_config=attack_config)

    assert result.stats["attack_active_ticks"] > 0
    assert result.stats["malicious_ids"] == [0]
    assert np.all(np.isfinite(result.positions)), "Positions contain NaN or Inf"


def test_attack_disabled_by_default() -> None:
    """With default config (attack disabled), attack_active_ticks == 0."""
    agents = make_initial_agents(10, seed=42)
    result = run_simulation(agents, duration_s=3.0)

    assert result.stats["attack_active_ticks"] == 0
    assert result.stats["malicious_ids"] == []
    assert np.all(np.isfinite(result.positions))


def test_malicious_logged_positions_are_true_physics() -> None:
    """The malicious agent's logged positions are the true positions and never jump by > v_max * dt."""
    cfg = get_config()
    dt = float(cfg["simulation"]["timestep_seconds"])
    v_max = float(cfg["safety"]["maximum_velocity_meters_per_second"])
    attack_config = {
        **cfg["attack"],
        "enabled": True,
        "start_time_seconds": 1.0,
        "malicious_ids": [0],
        "offset_magnitude_meters": 50.0,
    }
    agents = make_initial_agents(10, seed=42)
    result = run_simulation(agents, duration_s=3.0, attack_config=attack_config)

    idx_0 = result.agent_ids.index(0)
    pos_0 = result.positions[:, idx_0, :2]
    displacements = np.linalg.norm(np.diff(pos_0, axis=0), axis=-1)
    max_jump = float(np.max(displacements))
    assert max_jump <= v_max * dt + 1e-6, f"Max jump {max_jump} exceeded limit {v_max * dt}"

