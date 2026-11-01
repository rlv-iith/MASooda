"""Unit tests for LiveSTLMonitor (P6 Week 3 online safety monitoring)."""

from __future__ import annotations

import csv
from pathlib import Path
import numpy as np

from simulation.schema import INSUFFICIENT_HISTORY, AgentState, AgentType
from verification.live_monitor import LiveSTLMonitor


def test_live_monitor_safe_trajectory() -> None:
    """Feed 3 hand-made AgentState objects far apart for 20 ticks -> violation_count == 0, min_robustness > 0."""
    a0 = AgentState(id=0, type=AgentType.EMERGENCY, position=np.array([0.0, 0.0, 0.0]))
    a1 = AgentState(id=1, type=AgentType.EVTOL, position=np.array([50.0, 0.0, 0.0]))
    a2 = AgentState(id=2, type=AgentType.DELIVERY, position=np.array([100.0, 0.0, 0.0]))
    agents = [a0, a1, a2]

    monitor = LiveSTLMonitor()

    for k in range(20):
        t = k * 0.1
        monitor.log_state(t, agents)

    assert monitor.violation_count() == 0
    assert len(monitor.violations()) == 0
    assert monitor.min_robustness() > 0.0
    # Pairwise distance is 50.0 m, d_min is 8.0 m -> rho = 42.0 m
    assert np.isclose(monitor.min_robustness(), 42.0)


def test_live_monitor_first_tick_neutral_status() -> None:
    """First tick returns neutral / insufficient-history status, not a violation."""
    a0 = AgentState(id=0, type=AgentType.EMERGENCY, position=np.array([0.0, 0.0, 0.0]))
    a1 = AgentState(id=1, type=AgentType.EVTOL, position=np.array([5.0, 0.0, 0.0]))
    agents = [a0, a1]

    monitor = LiveSTLMonitor()
    res = monitor.log_state(0.0, agents)

    assert res.status == INSUFFICIENT_HISTORY
    assert res.violation is False
    assert res.value == 0.0


def test_live_monitor_violation_detection() -> None:
    """Two agents 5 m apart (d_min is 8) for 20 ticks -> violation_count > 0, rho < 0."""
    a0 = AgentState(id=0, type=AgentType.EMERGENCY, position=np.array([0.0, 0.0, 0.0]))
    a1 = AgentState(id=1, type=AgentType.EVTOL, position=np.array([5.0, 0.0, 0.0]))
    agents = [a0, a1]

    monitor = LiveSTLMonitor()

    for k in range(20):
        t = k * 0.1
        monitor.log_state(t, agents)

    assert monitor.violation_count() > 0
    assert monitor.violation_count() == 20
    assert monitor.min_robustness() < 0.0
    # 5.0 - 8.0 = -3.0
    assert np.isclose(monitor.min_robustness(), -3.0)

    # Check violations list
    violations = monitor.violations()
    assert len(violations) == 20
    for t, rho, worst_pair in violations:
        assert rho < 0.0
        assert worst_pair == (0, 1)


def test_live_monitor_to_csv(tmp_path: Path) -> None:
    """to_csv writes one row per tick with columns t,rho,window_rho,violation,status."""
    a0 = AgentState(id=0, type=AgentType.EMERGENCY, position=np.array([0.0, 0.0, 0.0]))
    a1 = AgentState(id=1, type=AgentType.EVTOL, position=np.array([20.0, 0.0, 0.0]))
    agents = [a0, a1]

    monitor = LiveSTLMonitor()
    n_ticks = 15
    for k in range(n_ticks):
        monitor.log_state(k * 0.1, agents)

    csv_path = tmp_path / "live_stl.csv"
    saved = monitor.to_csv(csv_path)
    assert saved.is_file()

    with open(saved, "r", encoding="utf-8") as f:
        reader = list(csv.reader(f))

    # Header + n_ticks data rows
    assert len(reader) == n_ticks + 1
    assert reader[0] == ["t", "rho", "window_rho", "violation", "status"]
    # Check first data row (t=0.0, insufficient history status)
    assert float(reader[1][0]) == 0.0
    assert reader[1][4] == INSUFFICIENT_HISTORY

