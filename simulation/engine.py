"""Simulation loop and integration engine for MASooda.

Coordinates agent behavior, dynamics integration, and trajectory recording
across discrete simulation timesteps.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
import time
from typing import Sequence
import numpy as np

from config.load_config import get_config
from conflict_resolution.adapter import resolve_all_conflicts
from resilience.attack import apply_attack, inject_attack

try:
    from resilience.defense import defend_neighbor_reports
except ImportError:
    defend_neighbor_reports = None

try:
    from simulation.overseer_link import OverseerLink
except ImportError:
    OverseerLink = None

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
    stats: dict = field(default_factory=dict)


def run_simulation(
    agents: Sequence[AgentState],
    duration_s: float | None = None,
    loggers: list | None = None,
    use_overseer: bool = True,
    use_admm: bool = True,
    attack_config: dict | None = None,
    defended: bool = True,
    overseer_link_config: dict | None = None,
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
    use_admm : bool, default True
        Whether to resolve conflicts via ADMM every tick.
    attack_config : dict, optional
        Attack injection configuration. If None, defaults to config attack section.
    defended : bool, default True
        Whether honest agents use P5's defence against falsified reports.
    overseer_link_config : dict, optional
        Configuration for OverseerLink communication drops and latency.

    Returns
    -------
    SimulationResult
        Trajectory history containing times, positions, agent IDs, velocities,
        overseer call/failure counters, and execution stats.
    """
    cfg = get_config()
    dt = float(cfg["simulation"]["timestep_seconds"])
    if duration_s is None:
        duration_s = float(cfg["simulation"]["duration_seconds"])

    if attack_config is None:
        attack_cfg = cfg.get("attack", {})
    else:
        attack_cfg = attack_config

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

    if OverseerLink is not None:
        link = OverseerLink(overseer_link_config)
    else:
        link = None

    cached_directive: OverseerDirective | None = None
    last_directive_time: float | None = None
    max_directive_staleness_s: float = 0.0
    overseer_calls = 0
    overseer_failures = 0
    corridors = build_corridors()

    admm_events = 0
    admm_nonconverged = 0
    admm_time_s = 0.0
    component_failures = 0

    attack_active_ticks = 0
    malicious_ids_set: set[int] = set()
    reports_dropped = 0

    last_graph = None

    if n_agents == 0:
        return SimulationResult(
            times=times,
            positions=positions,
            agent_ids=agent_ids,
            velocities=velocities,
            overseer_calls=overseer_calls,
            overseer_failures=overseer_failures,
            stats={
                "admm_events": 0,
                "admm_nonconverged": 0,
                "admm_time_s": 0.0,
                "component_failures": 0,
                "attack_active_ticks": 0,
                "malicious_ids": [],
                "reports_dropped": 0,
                "overseer_dropped": 0,
                "max_directive_staleness_s": 0.0,
            },
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
            if link is None:
                try:
                    fn = getattr(interfaces, "overseer_update", overseer_update)
                    if fn is interfaces.overseer_update and overseer_update is not interfaces.overseer_update:
                        fn = overseer_update
                    res_dir = fn(snapshot)
                    if res_dir is not None:
                        cached_directive = res_dir
                        last_directive_time = t_now
                except Exception:
                    overseer_failures += 1
            else:
                errors_before = getattr(link, "errors", 0)
                directive = link.request(snapshot, t_now)
                if getattr(link, "errors", 0) > errors_before:
                    overseer_failures += 1
                if directive is not None:
                    cached_directive = directive
                    last_directive_time = t_now

            if cached_directive is not None:
                for agent in current_agents:
                    if agent.id in cached_directive.corridor_map:
                        agent.corridor_assignment = cached_directive.corridor_map[agent.id]

        if cached_directive is not None and last_directive_time is not None:
            staleness = t_now - last_directive_time
            if staleness > max_directive_staleness_s:
                max_directive_staleness_s = staleness

        try:
            graph = build_comm_graph(current_agents)
            last_graph = graph
        except Exception:
            if last_graph is not None:
                graph = last_graph
                component_failures += 1
            else:
                raise

        agent_by_id = {a.id: a for a in current_agents}
        directive_for_local = cached_directive if use_overseer else None

        attack_state = inject_attack(current_agents, attack_cfg, t_now)
        reported_by_id = {a.id: a for a in apply_attack(current_agents, attack_state)}
        if attack_state.malicious:
            attack_active_ticks += 1
            malicious_ids_set.update(attack_state.malicious)

        malicious_current = set(attack_state.malicious)

        # Pass 1: compute desired velocity via local behavior (boids)
        desired: dict[int, np.ndarray] = {}
        for agent in current_agents:
            neighbor_ids = graph.neighbors(agent.id)
            true_nbrs = [agent_by_id[nid] for nid in neighbor_ids if nid in agent_by_id]
            reported_nbrs = [reported_by_id[nid] for nid in neighbor_ids if nid in reported_by_id]

            if agent.id in malicious_current:
                nbrs = true_nbrs
            elif defended and defend_neighbor_reports is not None:
                try:
                    res = defend_neighbor_reports(agent, reported_nbrs, true_nbrs)
                    nbrs = res.kept
                    reports_dropped += len(res.dropped_ids)
                except Exception:
                    component_failures += 1
                    nbrs = reported_nbrs
            else:
                nbrs = reported_nbrs

            try:
                v_des = update_local_behavior(agent, nbrs, directive_for_local)
            except Exception:
                v_des = agent.velocity.copy()
                component_failures += 1

            desired[agent.id] = v_des

        # Pass 2: ADMM conflict resolution (if enabled)
        if use_admm:
            boids_desired = {aid: v.copy() for aid, v in desired.items()}
            try:
                intents: list[AgentState] = []
                for agent in current_agents:
                    intent = copy.deepcopy(agent)
                    intent.velocity = desired[agent.id].copy()
                    intents.append(intent)

                priorities = {a.id: a.priority for a in current_agents}
                start = time.perf_counter()
                events = resolve_all_conflicts(intents, priorities)
                admm_time_s += time.perf_counter() - start

                for event in events:
                    admm_events += 1
                    if event.converged:
                        for aid, vel in event.resolution.items():
                            desired[aid] = np.asarray(vel, float)
                    else:
                        admm_nonconverged += 1
            except Exception:
                component_failures += 1
                desired = boids_desired

        # Pass 3: dynamics integration
        next_agents: list[AgentState] = []
        for agent in current_agents:
            neighbor_ids = graph.neighbors(agent.id)
            v_des = desired[agent.id]
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

    overseer_dropped = getattr(link, "dropped", 0) if link is not None else 0

    stats = {
        "admm_events": admm_events,
        "admm_nonconverged": admm_nonconverged,
        "admm_time_s": admm_time_s,
        "component_failures": component_failures,
        "attack_active_ticks": attack_active_ticks,
        "malicious_ids": sorted(list(malicious_ids_set)),
        "reports_dropped": reports_dropped,
        "overseer_dropped": overseer_dropped,
        "max_directive_staleness_s": max_directive_staleness_s,
    }

    return SimulationResult(
        times=times,
        positions=positions,
        agent_ids=agent_ids,
        velocities=velocities,
        overseer_calls=overseer_calls,
        overseer_failures=overseer_failures,
        stats=stats,
    )
