"""2.5D Agent Dynamics Engine for MASooda.

Implements the simplified 2.5D double-integrator model:
- Horizontal motion is represented continuously in (x, y)
- Altitude is represented using discrete predefined airspace layers (z_l in Z)
- Velocity and acceleration are clamped against configurable maximums
"""

from __future__ import annotations

from typing import Sequence
import numpy as np

from config.load_config import get_safety_limits
from .schema import AgentState


def clamp_vector_2d(vec: np.ndarray, max_val: float) -> np.ndarray:
    """Clamp the magnitude of a 2D vector to max_val."""
    norm = float(np.linalg.norm(vec))
    if norm > max_val and norm > 1e-9:
        return vec * (max_val / norm)
    return vec


def step_dynamics(
    agent_state: AgentState,
    control_input: np.ndarray | Sequence[float],
    dt: float,
    max_velocity: float | None = None,
    max_acceleration: float | None = None,
) -> AgentState:
    """Step agent kinematics forward in time by dt.

    Equations of motion (2.5D double-integrator):
        p_{t+1}^{xy} = p_t^{xy} + v_t^{xy} * dt
        v_{t+1}^{xy} = v_t^{xy} + a_t^{xy} * dt
        p_{t+1}^z = float(altitude_layer)
        v_{t+1}^z = 0.0

    Constraints:
        ||a_t^{xy}|| <= a_max
        ||v_{t+1}^{xy}|| <= v_max

    Parameters
    ----------
    agent_state : AgentState
        Current agent state.
    control_input : np.ndarray or Sequence[float]
        Desired horizontal acceleration command [ax, ay] (or [ax, ay, az]).
    dt : float
        Simulation timestep in seconds.
    max_velocity : float, optional
        Maximum allowed horizontal speed in m/s. If None, read from config.
    max_acceleration : float, optional
        Maximum allowed horizontal acceleration in m/s^2. If None, read from config.

    Returns
    -------
    AgentState
        Updated agent state at t + dt.
    """
    if dt < 0:
        raise ValueError("Timestep dt must be non-negative")

    # Load default limits from configuration if not explicitly provided
    if max_velocity is None or max_acceleration is None:
        cfg_max_vel, cfg_max_acc = get_safety_limits()
        if max_velocity is None:
            max_velocity = cfg_max_vel
        if max_acceleration is None:
            max_acceleration = cfg_max_acc

    # Extract 2D commanded acceleration
    u = np.asarray(control_input, dtype=float)
    if u.size < 2:
        raise ValueError("control_input must contain at least 2 components [ax, ay]")
    a_cmd_xy = u[:2]

    # 1. Clamp acceleration magnitude
    a_clamped_xy = clamp_vector_2d(a_cmd_xy, max_acceleration)

    # 2. Update horizontal position using current velocity
    p_current_xy = agent_state.position[:2]
    v_current_xy = agent_state.velocity[:2]
    p_next_xy = p_current_xy + v_current_xy * dt

    # 3. Update horizontal velocity using clamped acceleration
    v_next_xy_raw = v_current_xy + a_clamped_xy * dt

    # 4. Clamp horizontal velocity magnitude
    v_next_xy = clamp_vector_2d(v_next_xy_raw, max_velocity)

    # 5. Discrete altitude layer kinematics
    p_next_z = float(agent_state.altitude_layer)
    v_next_z = 0.0
    a_next_z = 0.0

    return AgentState(
        id=agent_state.id,
        type=agent_state.type,
        position=np.array([p_next_xy[0], p_next_xy[1], p_next_z], dtype=float),
        velocity=np.array([v_next_xy[0], v_next_xy[1], v_next_z], dtype=float),
        acceleration=np.array([a_clamped_xy[0], a_clamped_xy[1], a_next_z], dtype=float),
        destination=agent_state.destination.copy(),
        priority=agent_state.priority,
        corridor_assignment=agent_state.corridor_assignment,
        neighbor_set=list(agent_state.neighbor_set),
        altitude_layer=agent_state.altitude_layer,
    )
