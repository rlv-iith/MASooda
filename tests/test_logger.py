"""Unit tests for trajectory logging (simulation/logger.py and engine hook)."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence
import numpy as np

from config.load_config import get_config
from simulation.engine import run_simulation
from simulation.logger import TrajectoryLogger
from simulation.scenario import make_initial_agents
from simulation.schema import AgentState
from verification.stl_monitor import load_trajectory_csv


class CountingLogger:
    """Mock logger tracking call count."""

    def __init__(self) -> None:
        self.call_count: int = 0
        self.recorded_times: list[float] = []

    def log_state(self, t: float, agents: Sequence[AgentState]) -> None:
        self.call_count += 1
        self.recorded_times.append(t)


def test_trajectory_logger(tmp_path: Path) -> None:
    """Test TrajectoryLogger logging, row count, position array, CSV export, and custom logger."""
    cfg = get_config()
    dt = float(cfg["simulation"]["timestep_seconds"])
    duration_s = 2.0
    steps = int(round(duration_s / dt))  # 20 steps -> 21 time samples

    agents = make_initial_agents(5, seed=42)
    logger = TrajectoryLogger()
    custom_logger = CountingLogger()

    result = run_simulation(agents, duration_s=duration_s, loggers=[logger, custom_logger])

    # 1. Check number of rows == (steps + 1) * 5
    expected_rows = (steps + 1) * 5
    assert len(logger.rows) == expected_rows

    # 2. Check as_position_array() equals result.positions[:, :, :2]
    pos_arr = logger.as_position_array()
    assert pos_arr.shape == (steps + 1, 5, 2)
    assert np.allclose(pos_arr, result.positions[:, :, :2])

    # 3. Write to CSV and verify with load_trajectory_csv
    csv_file = tmp_path / "subdir" / "trajectory.csv"
    saved_path = logger.to_csv(csv_file)
    assert saved_path.is_file()

    loaded_arr = load_trajectory_csv(saved_path)
    assert loaded_arr.shape == (steps + 1, 5, 2)
    assert np.allclose(loaded_arr, result.positions[:, :, :2])

    # 4. Check custom logger called steps + 1 times
    assert custom_logger.call_count == steps + 1
    assert len(custom_logger.recorded_times) == steps + 1
    assert np.isclose(custom_logger.recorded_times[0], 0.0)
    assert np.isclose(custom_logger.recorded_times[-1], duration_s)

    # 5. Check velocities in result
    assert result.velocities.shape == (steps + 1, 5, 3)
    assert np.all(np.isfinite(result.velocities))

