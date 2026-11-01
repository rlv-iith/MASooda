"""Simulation loop and integration engine for MASooda.

Coordinates agent behavior, dynamics integration, and trajectory recording
across discrete simulation timesteps.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence
import numpy as np

from config.load_config import get_config
from simulation.interfaces import build_comm_graph, step_dynamics, update_local_behavior
from simulation.schema import AgentState


@dataclass
class SimulationResult:
    """Store complete multi-agent simulation trajectory history."""

    times: np.ndarray
    positions: np.ndarray
    agent_ids: list[int]


def run_simulation(
    agents: Sequence[AgentState],
    duration_s: float | None = None,
) -> SimulationResult:
    """Execute forward simulation for a fleet of agents.

    Parameters
    ----------
    agents : Sequence[AgentState]
        Initial agent states.
    duration_s : float, optional
        Simulation duration in seconds. If None, defaults to config duration_seconds.

    Returns
    -------
    SimulationResult
        Trajectory history containing times, positions, and agent IDs.
    """
    cfg = get_config()
    dt = float(cfg["simulation"]["timestep_seconds"])
    if duration_s is None:
        duration_s = float(cfg["simulation"]["duration_seconds"])

    tau_v = float(cfg["control"]["velocity_time_constant_seconds"])

    n_steps = int(round(duration_s / dt))
    t_count = n_steps + 1
    n_agents = len(agents)

    times = np.round(np.arange(t_count) * dt, 8)
    positions = np.zeros((t_count, n_agents, 3), dtype=float)
    agent_ids = [agent.id for agent in agents]

    if n_agents == 0:
        return SimulationResult(times=times, positions=positions, agent_ids=agent_ids)

    # Record initial positions at t = 0
    positions[0] = np.array([a.position for a in agents], dtype=float)

    current_agents = list(agents)

    for step_idx in range(n_steps):
        graph = build_comm_graph(current_agents)
        agent_by_id = {a.id: a for a in current_agents}

        next_agents: list[AgentState] = []
        for agent in current_agents:
            neighbor_ids = graph.neighbors(agent.id)
            neighbours = [agent_by_id[nid] for nid in neighbor_ids if nid in agent_by_id]
            v_des = update_local_behavior(agent, neighbours, None)
            accel = (v_des - agent.velocity) / tau_v
            new_agent = step_dynamics(agent, accel, dt)
            new_agent.neighbor_set = list(neighbor_ids)
            next_agents.append(new_agent)

        current_agents = next_agents
        positions[step_idx + 1] = np.array([a.position for a in current_agents], dtype=float)

    return SimulationResult(times=times, positions=positions, agent_ids=agent_ids)

