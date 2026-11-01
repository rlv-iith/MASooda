"""Controlled near-collision encounter generation for STL robustness validation."""

from __future__ import annotations

import numpy as np

from config.load_config import get_config
from simulation.schema import AgentState, AgentType
from verification.live_monitor import LiveSTLMonitor


def run_near_collision(
    closest_gap_m: float,
    duration_s: float = 10.0,
) -> LiveSTLMonitor:
    """Simulate a controlled two-agent head-on encounter with a calibrated lateral miss distance.

    Parameters
    ----------
    closest_gap_m : float
        Lateral distance between the two crossing tracks in meters.
    duration_s : float, default 10.0
        Total simulation duration in seconds.

    Returns
    -------
    LiveSTLMonitor
        Live monitor containing per-tick instantaneous and windowed robustness history.
    """
    from simulation.interfaces import step_dynamics
    cfg = get_config()
    dt = float(cfg["simulation"]["timestep_seconds"])

    # Agent 0 starts at x = 0.0, moves right (+x) at 10 m/s
    agent0 = AgentState(
        id=0,
        type=AgentType.EVTOL,
        position=np.array([0.0, 0.0, 0.0], dtype=float),
        velocity=np.array([10.0, 0.0, 0.0], dtype=float),
        acceleration=np.zeros(3, dtype=float),
        destination=np.array([100.0, 0.0, 0.0], dtype=float),
        priority=1,
        corridor_assignment=0,
        neighbor_set=[1],
        altitude_layer=0,
    )

    # Agent 1 starts at x = 100.0, moves left (-x) at 10 m/s with y offset = closest_gap_m
    agent1 = AgentState(
        id=1,
        type=AgentType.DELIVERY,
        position=np.array([100.0, float(closest_gap_m), 0.0], dtype=float),
        velocity=np.array([-10.0, 0.0, 0.0], dtype=float),
        acceleration=np.zeros(3, dtype=float),
        destination=np.array([0.0, float(closest_gap_m), 0.0], dtype=float),
        priority=2,
        corridor_assignment=0,
        neighbor_set=[0],
        altitude_layer=0,
    )

    agents = [agent0, agent1]
    monitor = LiveSTLMonitor()

    n_steps = int(round(duration_s / dt))
    t_arr = np.round(np.arange(n_steps + 1) * dt, 8)

    # Log initial state at t = 0
    monitor.log_state(float(t_arr[0]), agents)

    zero_control = np.zeros(3, dtype=float)
    for step_idx in range(n_steps):
        agents = [step_dynamics(a, zero_control, dt) for a in agents]
        monitor.log_state(float(t_arr[step_idx + 1]), agents)

    return monitor
