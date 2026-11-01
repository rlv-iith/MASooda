"""Tests for P1 Week 3 integration checkpoint pipeline."""

from __future__ import annotations

from pathlib import Path
import pytest
import numpy as np

from config.load_config import get_config
from simulation.engine import run_simulation
from simulation.environment import build_corridors, corridor_occupancy
from simulation.logger import TrajectoryLogger
from simulation.scenario import make_initial_agents
from simulation.schema import AgentState, AgentType
from verification.stl_monitor import load_trajectory_csv


@pytest.fixture(autouse=True)
def clean_boids_cache():
    """Clean module-level boids cache after test."""
    yield
    try:
        import local_behavior.boids as boids
        boids._last_corridor.clear()
    except Exception:
        pass


def test_p1_week3_pipeline(tmp_path: Path) -> None:
    """Test 30-agent, 10-s pipeline with logging, overseer, speed checks, and CSV loading."""
    cfg = get_config()
    dt = float(cfg["simulation"]["timestep_seconds"])
    v_max = float(cfg["safety"]["maximum_velocity_meters_per_second"])
    duration_s = 10.0
    expected_t = int(round(duration_s / dt)) + 1

    agents = make_initial_agents(30, seed=42)
    logger = TrajectoryLogger()

    result = run_simulation(agents, duration_s=duration_s, loggers=[logger], use_overseer=True)

    # 1. Assert no NaN
    assert np.all(np.isfinite(result.positions)), "Positions contain NaN or Inf"
    assert np.all(np.isfinite(result.velocities)), "Velocities contain NaN or Inf"

    # 2. Max speed within limit
    speeds = np.linalg.norm(np.diff(result.positions[:, :, :2], axis=0), axis=-1) / dt
    max_speed = float(np.max(speeds))
    assert max_speed <= v_max + 1e-6, f"Speed {max_speed:.2f} m/s exceeded max limit {v_max} m/s"

    # 3. 3 corridor keys in occupancy
    corridors = build_corridors()
    final_agents = [
        AgentState(id=aid, type=AgentType.DELIVERY, position=result.positions[-1, i])
        for i, aid in enumerate(result.agent_ids)
    ]
    occ = corridor_occupancy(final_agents, corridors)
    assert len(occ) == 3
    assert set(occ.keys()) == {0, 1, 2}

    # 4. overseer_failures == 0
    assert result.overseer_failures == 0

    # 5. CSV loads with shape (T, 30, 2)
    csv_file = tmp_path / "p1_week3_test.csv"
    logger.to_csv(csv_file)
    window = load_trajectory_csv(csv_file)
    assert window.shape == (expected_t, 30, 2)
    assert np.all(np.isfinite(window))

