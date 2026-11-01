"""Public function shapes shared by the project modules.

- This file defines the cross-module interfaces and function signatures.
- Each module provides its public interface here to allow independent development.

| Function              | Owner | Purpose                                       |
|-----------------------|-------|-----------------------------------------------|
| step_dynamics         | P1    | 2.5D double-integrator step                   |
| build_comm_graph      | P1    | Communication graph from agent states         |
| update_local_behavior | P3    | Boids-style desired velocity                  |
| resolve_conflict      | P2    | ADMM separation negotiation                   |
| overseer_update       | P4    | Global corridor/priority/altitude directive   |
| inject_attack         | P5    | Fault and attack injection                    |
| wmsr_filter           | P5    | W-MSR resilient consensus filter              |
| stl_monitor           | P6    | STL minimum-separation robustness             |
"""

from __future__ import annotations

from typing import Protocol, Sequence
import numpy as np

from config.load_config import get_config
from conflict_resolution.solver import ADMMSolver
from resilience.attack import inject_attack as _inject_attack
from verification.stl_monitor import stl_monitor as _stl_monitor
from .dynamics import step_dynamics as _step_dynamics
from .mock_data import get_mock_comm_graph
from .overseer import mock_overseer_update
from .schema import (
    AgentState,
    AttackState,
    CommunicationGraph,
    GlobalStateSnapshot,
    OverseerDirective,
    STLRobustness,
    STLSpec,
)


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
    from .comm_graph import build_knn_graph, build_radius_graph

    if all_agent_states is None:
        all_agent_states = []

    cfg = get_config()
    comm_cfg = cfg.get("communication", {})

    if isinstance(radius_or_k, float):
        return build_radius_graph(all_agent_states, radius_or_k)
    elif isinstance(radius_or_k, int) and not isinstance(radius_or_k, bool):
        return build_knn_graph(all_agent_states, radius_or_k)
    elif radius_or_k is None:
        mode = comm_cfg.get("mode", "radius")
        if mode == "radius":
            radius = float(comm_cfg.get("radius_meters", 40.0))
            return build_radius_graph(all_agent_states, radius)
        elif mode == "knn":
            k = int(comm_cfg.get("nearest_neighbors", 6))
            return build_knn_graph(all_agent_states, k)
        else:
            raise ValueError(f"Unknown communication mode: {mode}")
    else:
        raise TypeError(f"radius_or_k must be float, int, or None; got {type(radius_or_k)}")


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


def stl_monitor(trajectory_window: np.ndarray | Sequence, spec: STLSpec) -> STLRobustness:
    """Provide the project's single entry point for STL safety monitoring.

    - P6 owns the robustness computation of G(d_ij >= d_min) over the window.
    - ``trajectory_window`` has shape (T, N, D); the call is read-only.
    - Returns a neutral result, never a false violation, when the window is too short.
    """
    return _stl_monitor(trajectory_window, spec)


def resolve_conflict(
    agent_states: Sequence[AgentState],
    priorities: dict[int, int] | None = None,
) -> dict[int, np.ndarray]:
    """Provide the project's single entry point for distributed conflict resolution.

    - P2 owns the ADMM negotiation over the horizontal (x, y) motion of each agent.
    - Each agent's target is position + velocity * dt; the solver returns separated positions.
    - Returns agent id -> resolved velocity (new_pos - pos) / dt; z velocity is left unchanged.
    - ``priorities`` is ignored in Week 1; Week 3 will use it to bias who yields.
    """
    cfg = get_config()
    dt = float(cfg["simulation"]["timestep_seconds"])
    solver = ADMMSolver(
        d_safe=float(cfg["safety"]["minimum_separation_meters"]),
        v_max=float(cfg["safety"]["maximum_velocity_meters_per_second"]),
        dt=dt,
        eps_abs=float(cfg["admm"]["tolerance"]),
        max_iters=int(cfg["admm"]["maximum_iterations"]),
    )
    positions = np.array([a.position[:2] for a in agent_states], dtype=float)
    targets = positions + np.array([a.velocity[:2] for a in agent_states], dtype=float) * dt
    result = solver.solve(positions, targets)

    resolved: dict[int, np.ndarray] = {}
    for k, agent in enumerate(agent_states):
        velocity = agent.velocity.copy()
        velocity[:2] = (result.positions[k] - positions[k]) / dt
        resolved[agent.id] = velocity
    return resolved


def mock_resolve_conflict(
    agent_states: Sequence[AgentState],
    priorities: dict[int, int] | None = None,
) -> dict[int, np.ndarray]:
    """Identity mock: every agent keeps its current velocity."""
    return {agent.id: agent.velocity.copy() for agent in agent_states}


def update_local_behavior(
    agent_state: AgentState,
    neighbor_states: Sequence[AgentState],
    corridor_directive: OverseerDirective | None,
) -> np.ndarray:
    """Provide the project's single entry point for local (boids-style) behavior.

    - P3 owns the desired-velocity computation; P1 applies the dynamics limits afterwards.
    - Week 1 stub: head toward the destination at v_cruise, capped at the maximum velocity.
    - Neighbors and the directive are accepted but unused until the boids terms arrive in Week 2.
    - Returns a 3-vector with desired vz = 0, since altitude is a discrete layer.
    """
    cfg = get_config()
    speed = min(
        float(cfg["local_behavior"]["v_cruise"]),
        float(cfg["safety"]["maximum_velocity_meters_per_second"]),
    )
    to_goal = (agent_state.destination - agent_state.position)[:2]
    distance = float(np.linalg.norm(to_goal))
    desired = np.zeros(3)
    if distance > 0.0:
        desired[:2] = speed * to_goal / distance
    return desired


def inject_attack(
    agent_states: Sequence[AgentState],
    attack_config: dict,
    t: float,
) -> AttackState:
    """Provide the project's single entry point for fault and attack injection.

    - P5 owns this pure function: it never mutates ``agent_states``.
    - ``attack_config`` is the ``attack:`` section of base_config.yaml and ``t`` is simulation time in seconds.
    - Week 1 stub: always returns an empty AttackState.
    """
    return _inject_attack(agent_states, attack_config, t)


def wmsr_filter(
    own_state: AgentState,
    neighbor_reports: Sequence[AgentState],
    f: int,
) -> np.ndarray:
    """Filter neighbor reports with W-MSR, tolerating up to ``f`` misbehaving neighbors.

    - P5 owns this resilient-consensus filter, applied to x and y independently.
    - Week 3 will implement it; it is a signature only for now.
    """
    raise NotImplementedError("Week 3")
