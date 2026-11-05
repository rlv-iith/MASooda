"""Unit tests for centralized simulation architecture (P1 Week 5)."""

from __future__ import annotations

import copy
import numpy as np
import pytest

from config.load_config import get_config
from local_behavior.boids import reset_local_behavior_cache
from simulation.centralized import run_centralized
from simulation.engine import run_simulation
from simulation.overseer import reset_default_overseer
from simulation.scenario import make_initial_agents


@pytest.fixture(autouse=True)
def clean_state():
    """Reset overseer and boids cache before each test."""
    reset_default_overseer()
    reset_local_behavior_cache()
    yield
    reset_default_overseer()
    reset_local_behavior_cache()


def test_centralized_runs_without_exceptions():
    """Centralized simulation runs without exceptions, returns correct shape and no NaNs."""
    agents = make_initial_agents(n=10, seed=42)
    cfg = get_config()
    dt = float(cfg["simulation"]["timestep_seconds"])
    duration_s = 2.0
    expected_t = int(round(duration_s / dt)) + 1

    result = run_centralized(agents, duration_s=duration_s)

    assert result.positions.shape == (expected_t, 10, 3)
    assert result.velocities.shape == (expected_t, 10, 3)
    assert not np.isnan(result.positions).any()
    assert not np.isnan(result.velocities).any()


def test_centralized_deterministic():
    """Running centralized simulation twice with the same input produces identical positions."""
    agents1 = make_initial_agents(n=10, seed=42)
    agents2 = make_initial_agents(n=10, seed=42)

    res1 = run_centralized(agents1, duration_s=2.0)
    res2 = run_centralized(agents2, duration_s=2.0)

    assert np.array_equal(res1.positions, res2.positions)
    assert np.array_equal(res1.velocities, res2.velocities)


def test_centralized_stats_keys_match_engine():
    """Stats keys match exactly between centralized run and engine run."""
    agents_c = make_initial_agents(n=10, seed=42)
    agents_e = make_initial_agents(n=10, seed=42)

    res_centralized = run_centralized(agents_c, duration_s=1.0)
    res_engine = run_simulation(agents_e, duration_s=1.0)

    assert set(res_centralized.stats.keys()) == set(res_engine.stats.keys())


def test_centralized_admm_events_zero():
    """In centralized architecture, ADMM is bypassed so admm_events must be 0."""
    agents = make_initial_agents(n=10, seed=42)
    result = run_centralized(agents, duration_s=2.0)

    assert result.stats["admm_events"] == 0
    assert result.stats["admm_nonconverged"] == 0
    assert result.stats["admm_time_s"] == 0.0


def test_centralized_attack_active_ticks():
    """Attack with start_time_seconds=1.0 triggers attack_active_ticks > 0."""
    agents = make_initial_agents(n=10, seed=42)
    cfg = get_config()
    attack_cfg = {
        **cfg.get("attack", {}),
        "enabled": True,
        "start_time_seconds": 1.0,
    }

    result = run_centralized(agents, duration_s=3.0, attack_config=attack_cfg)

    assert result.stats["attack_active_ticks"] > 0
    assert len(result.stats["malicious_ids"]) > 0


def test_centralized_overseer_link_down():
    """Link failure causes overseer_failures > 0 and no crash."""
    agents = make_initial_agents(n=10, seed=42)
    link_cfg = {
        "enabled": True,
        "down_start_seconds": 2.0,
        "down_end_seconds": 6.0,
    }

    result = run_centralized(agents, duration_s=7.0, overseer_link_config=link_cfg)

    assert result.overseer_failures > 0
    assert result.stats["overseer_dropped"] > 0
    assert not np.isnan(result.positions).any()


def test_centralized_loggers_receive_calls():
    """Loggers receive one call per tick plus the t = 0 initial call."""
    agents = make_initial_agents(n=10, seed=42)
    cfg = get_config()
    dt = float(cfg["simulation"]["timestep_seconds"])
    duration_s = 1.0
    expected_calls = int(round(duration_s / dt)) + 1

    class MockLogger:
        def __init__(self):
            self.calls: list[tuple[float, int]] = []

        def log_state(self, t: float, agent_list: list) -> None:
            self.calls.append((t, len(agent_list)))

    logger = MockLogger()
    result = run_centralized(agents, duration_s=duration_s, loggers=[logger])

    assert len(logger.calls) == expected_calls
    assert logger.calls[0][0] == pytest.approx(0.0)
    assert logger.calls[-1][0] == pytest.approx(duration_s)

