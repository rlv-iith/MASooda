"""Centralized multi-agent simulation architecture (Section 13.1).

A purely centralized controller receives the full state of every agent
and directly computes corridor assignments and commanded velocities.
Boids local behavior and ADMM conflict resolution are bypassed.
"""

from __future__ import annotations

import copy
import math
from typing import Sequence
import numpy as np

from config.load_config import get_config
from local_behavior.boids import reset_local_behavior_cache
from resilience.attack import apply_attack, inject_attack
from simulation.engine import SimulationResult
from simulation.environment import build_corridors, corridor_of_position, corridor_occupancy
from simulation.interfaces import step_dynamics
from simulation.overseer import GlobalOverseer, reset_default_overseer
from simulation.schema import AgentState, GlobalStateSnapshot
from simulation.telemetry import build_tick_info


def run_centralized(
    agents: Sequence[AgentState],
    duration_s: float | None = None,
    loggers: list | None = None,
    attack_config: dict | None = None,
    overseer_link_config: dict | None = None,
    telemetry: object | None = None,
) -> SimulationResult:
    """Execute forward simulation under a purely centralized architecture.

    Parameters
    ----------
    agents : Sequence[AgentState]
        Initial agent states.
    duration_s : float, optional
        Simulation duration in seconds. If None, defaults to config duration_seconds.
    loggers : list, optional
        List of logger instances providing a log_state(t, agents) method.
    attack_config : dict, optional
        Attack injection configuration. If None, defaults to config attack section.
    overseer_link_config : dict, optional
        Overseer link failure configuration. If None, defaults to {"enabled": False}.
    telemetry : object, optional
        Opt-in (Week 6) per-tick ``telemetry.on_tick(t, info)``; see
        ``simulation.telemetry``. No ADMM runs in this architecture.

    Returns
    -------
    SimulationResult
        Trajectory history containing times, positions, agent IDs, velocities,
        overseer calls, overseer failures, and stats dictionary.
    """
    reset_default_overseer()
    reset_local_behavior_cache()

    cfg = get_config()
    sim_cfg = cfg["simulation"]
    dt = float(sim_cfg["timestep_seconds"])
    if duration_s is None:
        duration_s = float(sim_cfg["duration_seconds"])

    tau_v = float(cfg["control"]["velocity_time_constant_seconds"])

    overseer_cfg = cfg.get("overseer", {})
    period_s = float(overseer_cfg.get("update_period_seconds", 2.0))
    period_steps = max(1, int(round(period_s / dt)))

    lb_cfg = cfg["local_behavior"]
    v_cruise = float(lb_cfg["v_cruise"])
    r_sep = float(lb_cfg["r_sep"])
    w_sep = float(lb_cfg["w_sep"])
    k_lat = float(lb_cfg["k_lat"])
    d_0 = float(lb_cfg["d_0"])
    h = float(lb_cfg["h"])
    merge_lateral_speed = float(lb_cfg["merge_lateral_speed"])

    safety_cfg = cfg["safety"]
    v_max = float(safety_cfg["maximum_velocity_meters_per_second"])

    corridors_cfg = cfg["corridors"]
    corridor_width = float(corridors_cfg["width_meters"])
    half_corridor_width = corridor_width / 2.0

    if attack_config is None:
        attack_cfg = cfg.get("attack", {})
    else:
        attack_cfg = attack_config

    if overseer_link_config is None:
        link_cfg = {"enabled": False}
    else:
        link_cfg = overseer_link_config

    link_enabled = bool(link_cfg.get("enabled", False))
    link_failure_cfg = overseer_cfg.get("link_failure", {})
    down_start_seconds = float(link_cfg.get("down_start_seconds", link_failure_cfg.get("down_start_seconds", 90.0)))
    down_end_seconds = float(link_cfg.get("down_end_seconds", link_failure_cfg.get("down_end_seconds", 120.0)))

    corridors = build_corridors()
    corridor_ids = [c.id for c in corridors]
    corridor_centers = [c.y_center for c in corridors]
    num_corridors = len(corridors)
    policy = overseer_cfg.get("default_policy", "priority_aware")
    controller = GlobalOverseer(corridors=corridor_ids, policy=policy)

    n_steps = int(round(duration_s / dt))
    t_count = n_steps + 1
    n_agents = len(agents)

    times = np.round(np.arange(t_count) * dt, 8)
    positions = np.zeros((t_count, n_agents, 3), dtype=float)
    velocities = np.zeros((t_count, n_agents, 3), dtype=float)
    agent_ids = [agent.id for agent in agents]

    overseer_calls = 0
    overseer_failures = 0
    overseer_dropped = 0
    max_directive_staleness_s = 0.0
    last_directive_time: float | None = None

    attack_active_ticks = 0
    malicious_ids_set: set[int] = set()

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
                "layer_counts_final": {},
                "layer_changes": 0,
            },
        )

    # Record initial positions and velocities at t = 0
    positions[0] = np.array([a.position for a in agents], dtype=float)
    velocities[0] = np.array([a.velocity for a in agents], dtype=float)

    current_agents = [copy.deepcopy(a) for a in agents]

    # Call loggers at t = 0
    if loggers:
        for logger in loggers:
            logger.log_state(float(times[0]), current_agents)

    last_command: dict[int, np.ndarray] = {
        a.id: np.array(a.velocity, dtype=float, copy=True) for a in current_agents
    }

    for k in range(n_steps):
        t_now = float(times[k])

        # a) Attack injection and report falsification
        attack_state = inject_attack(current_agents, attack_cfg, t_now)
        reported = apply_attack(current_agents, attack_state)
        if attack_state.malicious:
            attack_active_ticks += 1
            malicious_ids_set.update(attack_state.malicious)

        # b) Controller down check
        is_down = link_enabled and (down_start_seconds <= t_now < down_end_seconds)
        if is_down:
            if k % period_steps == 0:
                overseer_failures += 1
                overseer_dropped += 1
            if last_directive_time is not None:
                staleness = t_now - last_directive_time
                if staleness > max_directive_staleness_s:
                    max_directive_staleness_s = staleness
            # Every agent keeps its last commanded velocity; skip to step e
        else:
            # c) Periodic overseer update
            if k % period_steps == 0:
                snapshot = GlobalStateSnapshot(
                    timestamp=t_now,
                    corridor_occupancy=corridor_occupancy(reported, corridors),
                    agent_ids=[a.id for a in reported],
                    agent_types={a.id: a.type for a in reported},
                    agent_priorities={a.id: a.priority for a in reported},
                )
                try:
                    directive = controller.update(snapshot)
                    overseer_calls += 1
                    last_directive_time = t_now
                    for agent in current_agents:
                        if agent.id in directive.corridor_map:
                            agent.corridor_assignment = directive.corridor_map[agent.id]
                    for r in reported:
                        if r.id in directive.corridor_map:
                            r.corridor_assignment = directive.corridor_map[r.id]
                except Exception:
                    overseer_failures += 1

            if last_directive_time is not None:
                staleness = t_now - last_directive_time
                if staleness > max_directive_staleness_s:
                    max_directive_staleness_s = staleness

            # d) Velocity command for every agent i using reported states of all agents
            n_rep = len(reported)
            rep_ids = [a.id for a in reported]
            rep_xs = [float(a.position[0]) for a in reported]
            rep_ys = [float(a.position[1]) for a in reported]
            rep_vxs = [float(a.velocity[0]) for a in reported]
            rep_layers = [int(getattr(a, "altitude_layer", 0)) for a in reported]
            rep_pris = [int(getattr(a, "priority", 2)) for a in reported]
            rep_corrs = [getattr(a, "corridor_assignment", None) for a in reported]

            for i in range(n_rep):
                aid_i = rep_ids[i]
                x_i = rep_xs[i]
                y_i = rep_ys[i]
                v_i_x = rep_vxs[i]
                layer_i = rep_layers[i]
                pri_i = rep_pris[i]

                # target_y
                assigned = rep_corrs[i]
                if assigned is not None and 0 <= assigned < num_corridors:
                    target_y = corridor_centers[assigned]
                else:
                    cid = corridor_of_position(y_i, corridors)
                    if cid is not None and 0 <= cid < num_corridors:
                        target_y = corridor_centers[cid]
                    else:
                        target_y = min(corridor_centers, key=lambda yc: abs(yc - y_i))

                lat_raw = k_lat * (target_y - y_i)
                lat_clipped = max(-merge_lateral_speed, min(merge_lateral_speed, lat_raw))
                vx = v_cruise
                vy = lat_clipped

                # Spacing
                closest_gap: float | None = None
                for j in range(n_rep):
                    if j == i or rep_layers[j] != layer_i:
                        continue
                    x_j = rep_xs[j]
                    if x_j <= x_i:
                        continue
                    y_j = rep_ys[j]
                    if abs(y_j - y_i) < half_corridor_width:
                        gap = x_j - x_i
                        if closest_gap is None or gap < closest_gap:
                            closest_gap = gap

                if closest_gap is not None:
                    desired_gap = d_0 + h * abs(v_i_x)
                    if desired_gap > 1e-9 and closest_gap < desired_gap:
                        vx = min(vx, max(0.0, v_cruise * (closest_gap / desired_gap)))

                # Separation with priority
                for j in range(n_rep):
                    if j == i or rep_layers[j] != layer_i:
                        continue
                    diff_x = x_i - rep_xs[j]
                    diff_y = y_i - rep_ys[j]
                    d = math.hypot(diff_x, diff_y)
                    if 1e-6 < d < r_sep:
                        push_scale = (w_sep / v_cruise) * ((r_sep - d) / r_sep) / d
                        push_x = push_scale * diff_x
                        push_y = push_scale * diff_y
                        pri_j = rep_pris[j]
                        if pri_i > pri_j:
                            factor = 1.0
                        elif pri_i == pri_j:
                            factor = 0.5
                        else:
                            factor = 0.0
                        vx += factor * push_x
                        vy += factor * push_y

                # Clip planar speed to v_max
                spd = math.hypot(vx, vy)
                if spd > v_max and spd > 1e-9:
                    scale = v_max / spd
                    vx *= scale
                    vy *= scale

                last_command[aid_i] = np.array([vx, vy, 0.0], dtype=float)

        # e) Dynamics integration for true agents
        next_agents = []
        for agent in current_agents:
            cmd = last_command[agent.id]
            accel = (cmd - agent.velocity) / tau_v
            new_agent = step_dynamics(agent, accel, dt)
            next_agents.append(new_agent)
        current_agents = next_agents

        # f) Trajectory recording and logger notification
        positions[k + 1] = np.array([a.position for a in current_agents], dtype=float)
        velocities[k + 1] = np.array([a.velocity for a in current_agents], dtype=float)
        t_next = float(times[k + 1])
        if loggers:
            for logger in loggers:
                logger.log_state(t_next, current_agents)
        if telemetry is not None:
            telemetry.on_tick(
                t_next,
                build_tick_info(
                    current_agents,
                    corridors,
                    malicious_ids=attack_state.malicious,
                    overseer_link_up=not is_down,
                    directive_age_s=(
                        t_now - last_directive_time if last_directive_time is not None else float("nan")
                    ),
                ),
            )

    layer_counts_final: dict[int, int] = {}
    for a in current_agents:
        layer = int(a.altitude_layer)
        layer_counts_final[layer] = layer_counts_final.get(layer, 0) + 1

    stats = {
        "admm_events": 0,
        "admm_nonconverged": 0,
        "admm_time_s": 0.0,
        "component_failures": 0,
        "attack_active_ticks": attack_active_ticks,
        "malicious_ids": sorted(list(malicious_ids_set)),
        "reports_dropped": 0,
        "overseer_dropped": overseer_dropped,
        "max_directive_staleness_s": max_directive_staleness_s,
        "layer_counts_final": layer_counts_final,
        "layer_changes": 0,
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
