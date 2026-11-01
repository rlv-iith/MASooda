"""Simulation loop and integration engine for MASooda.

Coordinates agent behavior, dynamics integration, and trajectory recording
across discrete simulation timesteps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence
import numpy as np

from config.load_config import get_config
from simulation import interfaces
from simulation.environment import build_corridors, corridor_occupancy
from simulation.interfaces import (
    build_comm_graph,
    overseer_update,
    step_dynamics,
    update_local_behavior,
)
from simulation.schema import AgentState, GlobalStateSnapshot, OverseerDirective


@dataclass
class SimulationResult:
    """Store complete multi-agent simulation trajectory history."""

    times: np.ndarray
    positions: np.ndarray
    agent_ids: list[int]
    velocities: np.ndarray = field(default_factory=lambda: np.empty((0, 0, 3), dtype=float))
    overseer_calls: int = 0
    overseer_failures: int = 0


def run_simulation(
    agents: Sequence[AgentState],
    duration_s: float | None = None,
    loggers: list | None = None,
    use_overseer: bool = True,
) -> SimulationResult:
    """Execute forward simulation for a fleet of agents.

    Parameters
    ----------
    agents : Sequence[AgentState]
        Initial agent states.
    duration_s : float, optional
        Simulation duration in seconds. If None, defaults to config duration_seconds.
    loggers : list, optional
        List of logger instances providing a log_state(t, agents) method.
    use_overseer : bool, default True
        Whether to call the global overseer periodically.

    Returns
    -------
    SimulationResult
        Trajectory history containing times, positions, agent IDs, velocities,
        and overseer call/failure counters.
    """
    cfg = get_config()
    dt = float(cfg["simulation"]["timestep_seconds"])
    if duration_s is None:
        duration_s = float(cfg["simulation"]["duration_seconds"])

    tau_v = float(cfg["control"]["velocity_time_constant_seconds"])

    overseer_cfg = cfg.get("overseer", {})
    period_s = float(overseer_cfg.get("update_period_seconds", 2.0))
    period_steps = max(1, int(round(period_s / dt)))

    n_steps = int(round(duration_s / dt))
    t_count = n_steps + 1
    n_agents = len(agents)

    times = np.round(np.arange(t_count) * dt, 8)
    positions = np.zeros((t_count, n_agents, 3), dtype=float)
    velocities = np.zeros((t_count, n_agents, 3), dtype=float)
    agent_ids = [agent.id for agent in agents]

    cached_directive: OverseerDirective | None = None
    overseer_calls = 0
    overseer_failures = 0
    corridors = build_corridors()

    if n_agents == 0:
        return SimulationResult(
            times=times,
            positions=positions,
            agent_ids=agent_ids,
            velocities=velocities,
            overseer_calls=overseer_calls,
            overseer_failures=overseer_failures,
        )

    # Record initial positions and velocities at t = 0
    positions[0] = np.array([a.position for a in agents], dtype=float)
    velocities[0] = np.array([a.velocity for a in agents], dtype=float)

    current_agents = list(agents)

    # Call loggers at t = 0
    if loggers:
        for logger in loggers:
            logger.log_state(float(times[0]), current_agents)

    for step_idx in range(n_steps):
        t_now = float(times[step_idx])

        # Overseer update on step 0 and every period_steps thereafter
        if use_overseer and (step_idx % period_steps == 0):
            overseer_calls += 1
            snapshot = GlobalStateSnapshot(
                timestamp=t_now,
                corridor_occupancy=corridor_occupancy(current_agents, corridors),
                agent_ids=[a.id for a in current_agents],
                agent_types={a.id: a.type for a in current_agents},
                agent_priorities={a.id: a.priority for a in current_agents},
            )
            try:
                fn = getattr(interfaces, "overseer_update", overseer_update)
                if fn is interfaces.overseer_update and overseer_update is not interfaces.overseer_update:
                    fn = overseer_update
                cached_directive = fn(snapshot)
            except Exception:
                overseer_failures += 1

            if cached_directive is not None:
                for agent in current_agents:
                    if agent.id in cached_directive.corridor_map:
                        agent.corridor_assignment = cached_directive.corridor_map[agent.id]

        graph = build_comm_graph(current_agents)
        agent_by_id = {a.id: a for a in current_agents}

        next_agents: list[AgentState] = []
        directive_for_local = cached_directive if use_overseer else None
        for agent in current_agents:
            neighbor_ids = graph.neighbors(agent.id)
            neighbours = [agent_by_id[nid] for nid in neighbor_ids if nid in agent_by_id]
            v_des = update_local_behavior(agent, neighbours, directive_for_local)
            accel = (v_des - agent.velocity) / tau_v
            new_agent = step_dynamics(agent, accel, dt)
            new_agent.neighbor_set = list(neighbor_ids)
            next_agents.append(new_agent)

        current_agents = next_agents
        positions[step_idx + 1] = np.array([a.position for a in current_agents], dtype=float)
        velocities[step_idx + 1] = np.array([a.velocity for a in current_agents], dtype=float)

        # Call loggers after step
        if loggers:
            for logger in loggers:
                logger.log_state(float(times[step_idx + 1]), current_agents)

    return SimulationResult(
        times=times,
        positions=positions,
        agent_ids=agent_ids,
        velocities=velocities,
        overseer_calls=overseer_calls,
        overseer_failures=overseer_failures,
    )
