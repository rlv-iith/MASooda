"""Unit tests for P1 Agent Dynamics and Kinematic Clamping.

Tests double-integrator equations of motion and clamping constraints
specified in Section 4.1 and Section 9.1 of the MASooda workflow.
"""

import numpy as np
import pytest

from simulation.dynamics import clamp_vector_2d, step_dynamics
from simulation.schema import AgentState, AgentType


def test_clamp_vector_2d() -> None:
    """Vectors exceeding max_val are clamped; smaller vectors are untouched."""
    # Under limit
    v_small = np.array([3.0, 4.0])  # norm = 5.0
    clamped = clamp_vector_2d(v_small, max_val=10.0)
    np.testing.assert_allclose(clamped, v_small)

    # Over limit
    v_large = np.array([6.0, 8.0])  # norm = 10.0
    clamped_large = clamp_vector_2d(v_large, max_val=5.0)
    assert np.isclose(np.linalg.norm(clamped_large), 5.0)
    # Direction preserved
    np.testing.assert_allclose(clamped_large, np.array([3.0, 4.0]))


def test_step_dynamics_double_integrator_unconstrained() -> None:
    """Verify p_{t+1} = p_t + v_t * dt and v_{t+1} = v_t + a_t * dt when within limits."""
    agent = AgentState(
        id=1,
        type=AgentType.EVTOL,
        position=np.array([10.0, 20.0, 2.0]),
        velocity=np.array([2.0, 1.0, 0.0]),
        acceleration=np.array([0.0, 0.0, 0.0]),
        altitude_layer=2,
    )
    dt = 0.5
    control_input = [1.0, 2.0]  # norm = sqrt(5) ~ 2.236 <= 4.0

    next_agent = step_dynamics(agent, control_input, dt=dt, max_velocity=15.0, max_acceleration=4.0)

    # Expected position: p + v * dt = [10 + 2*0.5, 20 + 1*0.5, 2.0] = [11.0, 20.5, 2.0]
    expected_pos = np.array([11.0, 20.5, 2.0])
    np.testing.assert_allclose(next_agent.position, expected_pos)

    # Expected velocity: v + a * dt = [2 + 1*0.5, 1 + 2*0.5, 0.0] = [2.5, 2.0, 0.0]
    expected_vel = np.array([2.5, 2.0, 0.0])
    np.testing.assert_allclose(next_agent.velocity, expected_vel)

    # Expected acceleration
    expected_acc = np.array([1.0, 2.0, 0.0])
    np.testing.assert_allclose(next_agent.acceleration, expected_acc)

    # Altitude layer preserved
    assert next_agent.altitude_layer == 2
    assert next_agent.position[2] == 2.0
    assert next_agent.velocity[2] == 0.0


def test_step_dynamics_acceleration_clamping() -> None:
    """Verify that commanded acceleration exceeding max_acceleration is clamped."""
    agent = AgentState(
        id=2,
        type=AgentType.DELIVERY,
        position=np.array([0.0, 0.0, 0.0]),
        velocity=np.array([0.0, 0.0, 0.0]),
        altitude_layer=0,
    )
    dt = 1.0
    # Commanded acceleration magnitude: sqrt(30^2 + 40^2) = 50.0 > 4.0
    control_input = [30.0, 40.0]
    max_acc = 4.0

    next_agent = step_dynamics(agent, control_input, dt=dt, max_velocity=15.0, max_acceleration=max_acc)

    acc_norm = np.linalg.norm(next_agent.acceleration[:2])
    assert np.isclose(acc_norm, max_acc)

    # Check direction: 3:4 ratio -> [2.4, 3.2]
    np.testing.assert_allclose(next_agent.acceleration[:2], np.array([2.4, 3.2]))
    # Velocity after 1 second starting from 0 should equal clamped acceleration
    np.testing.assert_allclose(next_agent.velocity[:2], np.array([2.4, 3.2]))


def test_step_dynamics_velocity_clamping() -> None:
    """Verify that updated velocity exceeding max_velocity is clamped."""
    agent = AgentState(
        id=3,
        type=AgentType.EMERGENCY,
        position=np.array([0.0, 0.0, 1.0]),
        velocity=np.array([14.0, 0.0, 0.0]),  # already near max_velocity 15.0
        altitude_layer=1,
    )
    dt = 1.0
    # Accelerate in same direction by 3.0 m/s^2 (unclamped accel, but results in vel = 17.0 > 15.0)
    control_input = [3.0, 0.0]
    max_vel = 15.0
    max_acc = 4.0

    next_agent = step_dynamics(agent, control_input, dt=dt, max_velocity=max_vel, max_acceleration=max_acc)

    vel_norm = np.linalg.norm(next_agent.velocity[:2])
    assert np.isclose(vel_norm, max_vel)
    assert next_agent.velocity[0] == max_vel
    assert next_agent.velocity[1] == 0.0


def test_step_dynamics_negative_dt_raises_error() -> None:
    """Negative dt must be rejected."""
    agent = AgentState(id=1, type=AgentType.DELIVERY)
    with pytest.raises(ValueError, match="non-negative"):
        step_dynamics(agent, [0.0, 0.0], dt=-0.1)


def test_step_dynamics_invalid_control_input_raises_error() -> None:
    """Control input with fewer than 2 dimensions must raise ValueError."""
    agent = AgentState(id=1, type=AgentType.DELIVERY)
    with pytest.raises(ValueError, match="at least 2 components"):
        step_dynamics(agent, [1.0], dt=0.1)
