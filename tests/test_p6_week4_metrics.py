"""Unit tests for P6 Week 4 simulation run metrics calculation (Table 11)."""

from __future__ import annotations

import json
from pathlib import Path
import types
import numpy as np
import pytest

from verification.metrics import (
    compute_run_metrics,
    graceful_degradation_score,
    recovery_times,
    robustness_series,
    write_metrics,
)


def test_robustness_series_safe() -> None:
    """Two agents 10 m apart for 5 ticks, d_min 8 -> rho == 2 everywhere, 0 violation ticks."""
    positions = np.zeros((5, 2, 3), dtype=float)
    # Agent 0 at (0, 0), Agent 1 at (10, 0) -> distance is 10 m
    positions[:, 1, 0] = 10.0
    d_min = 8.0

    rho = robustness_series(positions, d_min)
    assert rho.shape == (5,)
    assert np.all(rho == 2.0)

    times = np.round(np.arange(5) * 0.1, 2)
    fake_result = types.SimpleNamespace(
        times=times,
        positions=positions,
        agent_ids=[0, 1],
        overseer_calls=2,
        overseer_failures=0,
        stats={},
    )
    config = {
        "safety": {"minimum_separation_meters": 8.0},
        "corridors": {"exit_zone_x_meters": [1400.0, 1500.0]},
        "simulation": {"duration_seconds": 0.5},
    }
    metrics = compute_run_metrics(fake_result, config=config)

    assert metrics["safety_violation_ticks"] == 0
    assert metrics["min_robustness_m"] == 2.0
    assert metrics["min_separation_m"] == 10.0
    assert metrics["violation_episodes"] == 0
    assert metrics["unrecovered_episodes"] == 0


def test_recovery_times_hand_computed() -> None:
    """Agents 10,10,5,5,10,... apart, dt 0.1, hold 1.0 s: one episode, recovery time 0.2 s."""
    # dt = 0.1 s.
    # Ticks 0, 1: dist = 10 m (rho = +2.0)
    # Ticks 2, 3: dist = 5 m (rho = -3.0) -> Episode starts at t = 0.2 s
    # Ticks 4..19: dist = 10 m (rho = +2.0) (16 ticks >= 1.0 s hold)
    # Candidate recovery at tick 4 (t = 0.4 s), holds through tick 14 (t = 1.4 s, 1.4 - 0.4 = 1.0 s)
    # Expected recovery time = 0.4 s - 0.2 s = 0.2 s.
    times = np.round(np.arange(20) * 0.1, 2)
    dists = [10.0, 10.0, 5.0, 5.0] + [10.0] * 16
    positions = np.zeros((20, 2, 3), dtype=float)
    for t_idx, d in enumerate(dists):
        positions[t_idx, 1, 0] = d

    d_min = 8.0
    rho = robustness_series(positions, d_min)
    rec = recovery_times(times, rho, hold_s=1.0)

    assert len(rec) == 1
    assert rec[0] == pytest.approx(0.2)

    fake_result = types.SimpleNamespace(
        times=times,
        positions=positions,
        agent_ids=[0, 1],
        overseer_calls=1,
        overseer_failures=0,
        stats={},
    )
    config = {
        "safety": {"minimum_separation_meters": 8.0},
        "corridors": {"exit_zone_x_meters": [1400.0, 1500.0]},
    }
    metrics = compute_run_metrics(fake_result, config=config)

    assert metrics["violation_episodes"] == 1
    assert metrics["unrecovered_episodes"] == 0
    assert metrics["mean_recovery_time_s"] == pytest.approx(0.2)
    assert metrics["max_recovery_time_s"] == pytest.approx(0.2)
    assert metrics["safety_violation_ticks"] == 2


def test_unrecovered_episode() -> None:
    """An episode that never recovers -> unrecovered_episodes == 1."""
    times = np.array([0.0, 0.1, 0.2])
    positions = np.zeros((3, 2, 3), dtype=float)
    positions[0, 1, 0] = 10.0
    positions[1, 1, 0] = 5.0
    positions[2, 1, 0] = 5.0

    fake_result = types.SimpleNamespace(
        times=times,
        positions=positions,
        agent_ids=[0, 1],
        overseer_calls=0,
        overseer_failures=0,
        stats={},
    )
    config = {
        "safety": {"minimum_separation_meters": 8.0},
        "corridors": {"exit_zone_x_meters": [1400.0, 1500.0]},
    }
    metrics = compute_run_metrics(fake_result, config=config)

    assert metrics["violation_episodes"] == 1
    assert metrics["unrecovered_episodes"] == 1
    assert np.isnan(metrics["mean_recovery_time_s"])
    assert np.isnan(metrics["max_recovery_time_s"])


def test_arrivals_count() -> None:
    """Arrivals counts an agent whose x position ever reached exit_zone_x_meters[0]."""
    times = np.array([0.0, 1.0, 2.0])
    positions = np.zeros((3, 2, 3), dtype=float)
    # Agent 0 crosses exit x = 1400 at tick 1 (x=1450) and moves further to 1500
    positions[0, 0, 0] = 1000.0
    positions[1, 0, 0] = 1450.0
    positions[2, 0, 0] = 1500.0

    # Agent 1 stays at x=100
    positions[:, 1, 0] = 100.0

    fake_result = types.SimpleNamespace(
        times=times,
        positions=positions,
        agent_ids=[0, 1],
        overseer_calls=0,
        overseer_failures=0,
        stats={},
    )
    config = {
        "safety": {"minimum_separation_meters": 8.0},
        "corridors": {"exit_zone_x_meters": [1400.0, 1500.0]},
    }
    metrics = compute_run_metrics(fake_result, config=config)

    assert metrics["arrivals"] == 1
    assert metrics["throughput_per_s"] == pytest.approx(1.0 / 2.0)


def test_graceful_degradation_score() -> None:
    """graceful_degradation_score(0,0)==1.0, (4,2)==2.0, (3,0)==inf."""
    assert graceful_degradation_score(0, 0) == 1.0
    assert graceful_degradation_score(4, 2) == 2.0
    assert graceful_degradation_score(3, 0) == float("inf")


def test_fake_result_stats_preservation(tmp_path: Path) -> None:
    """A fake result object with a stats dict has all its keys preserved in metrics."""
    times = np.array([0.0, 1.0])
    positions = np.zeros((2, 2, 3), dtype=float)
    positions[:, 1, 0] = 10.0
    fake_stats = {
        "admm_events": 42,
        "admm_time_s": 0.123,
        "custom_metric": "test_val",
        "malicious_ids": [1],
    }
    fake_result = types.SimpleNamespace(
        times=times,
        positions=positions,
        agent_ids=[0, 1],
        overseer_calls=5,
        overseer_failures=1,
        stats=fake_stats,
    )
    config = {
        "safety": {"minimum_separation_meters": 8.0},
        "corridors": {"exit_zone_x_meters": [1400.0, 1500.0]},
    }
    metrics = compute_run_metrics(fake_result, config=config)

    for k, v in fake_stats.items():
        assert k in metrics
        assert metrics[k] == v
    assert metrics["overseer_calls"] == 5
    assert metrics["overseer_failures"] == 1

    # Verify write_metrics creates both files
    j_path = tmp_path / "metrics.json"
    c_path = tmp_path / "metrics.csv"
    write_metrics(metrics, j_path, c_path)

    assert j_path.exists()
    assert c_path.exists()

    with open(j_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["admm_events"] == 42
    assert data["overseer_calls"] == 5

