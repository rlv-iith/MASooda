"""Unit tests for LiveSTLMonitor console output, event logging, and summary (P6 Week 4)."""

from __future__ import annotations

import csv
from pathlib import Path
import numpy as np
import pytest

from simulation.schema import AgentState, AgentType
from verification.live_monitor import LiveSTLMonitor


def test_live_monitor_events(tmp_path: Path) -> None:
    """Feed log_state 2 agents: 10 m (5 ticks), 5 m (5 ticks), 10 m (5 ticks).

    Expect exactly one violation_start and one violation_end,
    summary()["num_violation_episodes"] == 1, and write_events creates a 2-row CSV.
    """
    monitor = LiveSTLMonitor()

    # 15 ticks with dt = 0.1
    # Ticks 0..4: 10 m apart
    # Ticks 5..9: 5 m apart
    # Ticks 10..14: 10 m apart
    for k in range(15):
        t = k * 0.1
        if 5 <= k < 10:
            dist = 5.0
        else:
            dist = 10.0

        a0 = AgentState(id=0, type=AgentType.EMERGENCY, position=np.array([0.0, 0.0, 0.0]))
        a1 = AgentState(id=1, type=AgentType.EVTOL, position=np.array([dist, 0.0, 0.0]))
        monitor.log_state(t, [a0, a1])

    # Expect exactly 2 events: violation_start and violation_end
    assert len(monitor.events) == 2
    assert monitor.events[0]["event"] == "violation_start"
    assert monitor.events[0]["t"] == pytest.approx(0.5)
    assert monitor.events[0]["rho"] == pytest.approx(-3.0)

    assert monitor.events[1]["event"] == "violation_end"
    assert monitor.events[1]["t"] == pytest.approx(1.0)
    assert monitor.events[1]["rho"] == pytest.approx(2.0)

    summ = monitor.summary()
    assert summ["ticks"] == 15
    assert summ["violation_count"] == 5
    assert summ["min_robustness"] == pytest.approx(-3.0)
    assert summ["num_violation_episodes"] == 1

    # write_events creates a file with the header and 2 rows
    csv_file = tmp_path / "events.csv"
    saved = monitor.write_events(csv_file)
    assert saved.is_file()

    with open(saved, "r", encoding="utf-8") as f:
        reader = list(csv.reader(f))

    assert len(reader) == 3  # header + 2 rows
    assert reader[0] == ["t", "event", "rho", "worst_pair"]
    assert reader[1][1] == "violation_start"
    assert reader[2][1] == "violation_end"


def test_live_monitor_console_output(capsys: pytest.CaptureFixture) -> None:
    """With console_every_seconds=0.5, capsys captures '[STL]' output lines."""
    monitor = LiveSTLMonitor(console_every_seconds=0.5)

    a0 = AgentState(id=0, type=AgentType.EMERGENCY, position=np.array([0.0, 0.0, 0.0]))
    a1 = AgentState(id=1, type=AgentType.EVTOL, position=np.array([10.0, 0.0, 0.0]))

    for k in range(15):
        monitor.log_state(k * 0.1, [a0, a1])

    captured = capsys.readouterr()
    assert "[STL]" in captured.out
    lines = [line for line in captured.out.strip().split("\n") if "[STL]" in line]
    assert len(lines) >= 3  # t=0.0, t=0.5, t=1.0
    for line in lines:
        assert "rho=" in line
        assert "status=" in line
        assert "violations=" in line


def test_live_monitor_default_constructor_silent(capsys: pytest.CaptureFixture) -> None:
    """The default constructor prints nothing (capsys output empty)."""
    monitor = LiveSTLMonitor()

    a0 = AgentState(id=0, type=AgentType.EMERGENCY, position=np.array([0.0, 0.0, 0.0]))
    a1 = AgentState(id=1, type=AgentType.EVTOL, position=np.array([10.0, 0.0, 0.0]))

    for k in range(15):
        monitor.log_state(k * 0.1, [a0, a1])

    captured = capsys.readouterr()
    assert captured.out == ""


def test_live_monitor_incremental_event_log_path(tmp_path: Path) -> None:
    """When event_log_path is given, events are appended to the file as they happen."""
    log_path = tmp_path / "live_stream.csv"
    monitor = LiveSTLMonitor(event_log_path=log_path)

    a0 = AgentState(id=0, type=AgentType.EMERGENCY, position=np.array([0.0, 0.0, 0.0]))

    # Feed safe ticks
    for k in range(5):
        a1 = AgentState(id=1, type=AgentType.EVTOL, position=np.array([10.0, 0.0, 0.0]))
        monitor.log_state(k * 0.1, [a0, a1])

    # No violations yet -> file not created or empty
    assert not log_path.exists()

    # Feed violation tick
    a1_bad = AgentState(id=1, type=AgentType.EVTOL, position=np.array([5.0, 0.0, 0.0]))
    monitor.log_state(0.5, [a0, a1_bad])

    # Now violation_start must have been appended
    assert log_path.exists()
    with open(log_path, "r", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert len(rows) == 2  # header + violation_start

    # Recover
    a1_good = AgentState(id=1, type=AgentType.EVTOL, position=np.array([10.0, 0.0, 0.0]))
    monitor.log_state(0.6, [a0, a1_good])

    with open(log_path, "r", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    assert len(rows) == 3  # header + violation_start + violation_end

