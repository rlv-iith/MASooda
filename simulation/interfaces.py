"""Public function shapes shared by the project modules.

- This file defines the cross-module interfaces and function signatures.
- Each module provides its public interface here to allow independent development.
- P1 owns step_dynamics and build_comm_graph.
- P4 owns overseer_update.
"""

from __future__ import annotations

from typing import Protocol, Sequence
import numpy as np

from .dynamics import step_dynamics as _step_dynamics
from .mock_data import get_mock_comm_graph
from .overseer import mock_overseer_update
from .schema import AgentState, CommunicationGraph, GlobalStateSnapshot, OverseerDirective


class StepDynamics(Protocol):
    """Describe the input and output shape of agent dynamics integration."""

    def __call__(
        self,
        agent_state: AgentState,
        control_input: np.ndarray | Sequence[float],
        dt: float,
    ) -> AgentState:
        """Step an agent's kinematics forward by timestep dt."""


def step_dynamics(
    agent_state: AgentState,
    control_input: np.ndarray | Sequence[float],
    dt: float,
    max_velocity: float | None = None,
    max_acceleration: float | None = None,
) -> AgentState:
    """Provide the project's single entry point for agent dynamics stepping.

    - P1 owns and implements this 2.5D double-integrator model.
    - Motion is continuous in (x, y) and discrete in altitude layer.
    - Clamps velocity and acceleration to configured maximums.
    """
    return _step_dynamics(
        agent_state=agent_state,
        control_input=control_input,
        dt=dt,
        max_velocity=max_velocity,
        max_acceleration=max_acceleration,
    )


class BuildCommGraph(Protocol):
    """Describe the input and output shape of communication graph construction."""

    def __call__(
        self,
        all_agent_states: Sequence[AgentState],
        radius_or_k: float | int | None = None,
    ) -> CommunicationGraph:
        """Construct an undirected communication graph."""


def build_comm_graph(
    all_agent_states: Sequence[AgentState] | None = None,
    radius_or_k: float | int | None = None,
) -> CommunicationGraph:
    """Build communication graph among active agents.

    - In Week 1, returns the mock fixed communication graph.
    - In Week 2, real radius-based and k-nearest-neighbor graphs will be computed.
    """
    return get_mock_comm_graph()


class OverseerUpdate(Protocol):
    """Describe the input and output shape of any overseer implementation."""

    def __call__(self, global_state_snapshot: GlobalStateSnapshot) -> OverseerDirective:
        """Create one global directive from the current state summary."""


def overseer_update(global_state_snapshot: GlobalStateSnapshot) -> OverseerDirective:
    """Provide the project's single entry point for an overseer update.

    - P1 or P3 can call this function without knowing where the implementation lives.  
    - In Week 1 it returns the fixed mock directive.  
    - In Week 2 P4 will replace the mock with occupancy-based corridor allocation.  
    - In Week 3 P4 will add priority-aware allocation and capacity handling.  
    - In Week 4 P4 will support cached directives when the overseer link fails.
    """
    return mock_overseer_update(global_state_snapshot)
