"""P3 Week 4: Merge check with ADMM conflict resolution and overseer in 60-agent traffic.

Evaluates boids local flocking + corridor merging combined with distributed ADMM
conflict resolution and the priority-aware global overseer in multi-agent traffic.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Any
import matplotlib.pyplot as plt
import numpy as np

from config.load_config import get_config
from conflict_resolution.adapter import resolve_all_conflicts
from local_behavior import boids
from local_behavior.boids import corridor_of
from simulation.environment import build_corridors, corridor_occupancy
from simulation.interfaces import build_comm_graph, step_dynamics, update_local_behavior
from simulation.overseer import real_overseer_update, reset_default_overseer
from simulation.scenario import make_initial_agents
from simulation.schema import AgentState, GlobalStateSnapshot, OverseerDirective


def run_check(
    n: int = 60,
    duration: float = 120.0,
    use_admm: bool = True,
    seed: int = 42,
) -> dict[str, Any]:
    """Run multi-agent simulation with boids, overseer updates, and optional ADMM.

    Parameters
    ----------
    n : int
        Number of agents.
    duration : float
        Simulation duration in seconds.
    use_admm : bool
        Whether to enable ADMM conflict resolution.
    seed : int
        Random seed for initial scenario generation.

    Returns
    -------
    dict[str, Any]
        Metrics dictionary containing merge success rate, min distance,
        ticks below 8 m, NaN count, throughput, and time series of min distance.
    """
    # 7. Reset overseer and local behavior cache before each run
    reset_default_overseer()
    if hasattr(boids, "reset_local_behavior_cache"):
        boids.reset_local_behavior_cache()

    cfg = get_config()
    dt = float(cfg["simulation"]["timestep_seconds"])
    tau_v = float(cfg["control"]["velocity_time_constant_seconds"])
    corridors = build_corridors()
    exit_start = float(cfg["corridors"]["exit_zone_x_meters"][0])
    period_s = float(cfg.get("overseer", {}).get("update_period_seconds", 2.0))
    period_steps = max(1, int(round(period_s / dt)))
    num_steps = int(round(duration / dt))

    # Optimization: cache configuration in boids during tick evaluation
    orig_boids_get_config = getattr(boids, "get_config", None)
    boids.get_config = lambda: cfg

    try:
        # 1. Initialize agents
        agents: list[AgentState] = make_initial_agents(n, seed=seed)
        start_corridors: dict[int, int] = {a.id: corridor_of(a.position[1]) for a in agents}

        cached_directive: OverseerDirective | None = None
        overseer_targets: dict[int, int] = {}
        min_pairwise_distance = float("inf")
        ticks_below_8m = 0
        num_nan_states = 0
        min_distances_over_time: list[float] = []
        times: list[float] = []

        for step in range(num_steps):
            t_now = step * dt
            times.append(t_now)

            # 2. Every 2.0 s build GlobalStateSnapshot and call real_overseer_update
            if step % period_steps == 0:
                snapshot = GlobalStateSnapshot(
                    timestamp=t_now,
                    corridor_occupancy=corridor_occupancy(agents, corridors),
                    agent_ids=[a.id for a in agents],
                    agent_types={a.id: a.type for a in agents},
                    agent_priorities={a.id: a.priority for a in agents},
                )
                cached_directive = real_overseer_update(snapshot)
                for aid, corr in cached_directive.corridor_map.items():
                    overseer_targets[aid] = corr
                for a in agents:
                    if a.id in cached_directive.corridor_map:
                        a.corridor_assignment = cached_directive.corridor_map[a.id]

            # Measure pairwise distance at this tick
            coords = np.array([a.position[:2] for a in agents], dtype=float)
            if len(agents) > 1:
                diff = coords[:, None, :] - coords[None, :, :]
                dist_matrix = np.linalg.norm(diff, axis=-1)
                np.fill_diagonal(dist_matrix, float("inf"))
                tick_min = float(np.min(dist_matrix))
            else:
                tick_min = float("inf")

            min_distances_over_time.append(tick_min)
            if tick_min < min_pairwise_distance:
                min_pairwise_distance = tick_min
            if tick_min < 8.0:
                ticks_below_8m += 1

            # 3. Build communication graph and compute v_des for each agent
            graph = build_comm_graph(agents)
            agent_by_id = {a.id: a for a in agents}
            v_des_dict: dict[int, np.ndarray] = {}

            for a in agents:
                neighbor_ids = graph.neighbors(a.id)
                neighbours = [agent_by_id[nid] for nid in neighbor_ids if nid in agent_by_id]
                v_des = update_local_behavior(a, neighbours, cached_directive)
                if not np.all(np.isfinite(v_des)):
                    num_nan_states += 1
                v_des_dict[a.id] = v_des

            # ADMM conflict resolution on intent copies
            if use_admm:
                intents = [
                    AgentState(
                        id=a.id,
                        type=a.type,
                        position=a.position.copy(),
                        velocity=v_des_dict[a.id].copy(),
                        acceleration=a.acceleration.copy(),
                        destination=a.destination.copy(),
                        priority=a.priority,
                        corridor_assignment=a.corridor_assignment,
                        neighbor_set=list(a.neighbor_set),
                        altitude_layer=a.altitude_layer,
                    )
                    for a in agents
                ]
                priorities = {a.id: a.priority for a in agents}
                events = resolve_all_conflicts(intents, priorities)
                for event in events:
                    if event.converged:
                        for aid, res_vel in event.resolution.items():
                            v_des_dict[aid] = res_vel

            # Dynamics update
            next_agents: list[AgentState] = []
            for a in agents:
                v_des = v_des_dict[a.id]
                accel = (v_des - a.velocity) / tau_v
                new_agent = step_dynamics(a, accel, dt)
                new_agent.neighbor_set = list(graph.neighbors(a.id))
                if not (np.all(np.isfinite(new_agent.position)) and np.all(np.isfinite(new_agent.velocity))):
                    num_nan_states += 1
                next_agents.append(new_agent)

            agents = next_agents

        # 5. Measure metrics
        diff_agents = [aid for aid in overseer_targets if overseer_targets[aid] != start_corridors.get(aid)]
        if diff_agents:
            success_count = sum(
                1 for a in agents
                if a.id in diff_agents and corridor_of(a.position[1]) == overseer_targets[a.id]
            )
            merge_success_rate = success_count / len(diff_agents)
        else:
            merge_success_rate = 1.0

        throughput = sum(1 for a in agents if a.position[0] >= exit_start) / duration

        return {
            "use_admm": use_admm,
            "n_agents": n,
            "duration_s": duration,
            "merge_success_rate": float(merge_success_rate),
            "min_distance": float(min_pairwise_distance),
            "min_pairwise_distance": float(min_pairwise_distance),
            "ticks_below_8m": int(ticks_below_8m),
            "num_nan_states": int(num_nan_states),
            "nan_count": int(num_nan_states),
            "throughput": float(throughput),
            "times": times,
            "min_distances_over_time": min_distances_over_time,
        }
    finally:
        if orig_boids_get_config is not None:
            boids.get_config = orig_boids_get_config


def main() -> None:
    """Run 60-agent 120s scenario with ADMM ON and ADMM OFF, save CSV and plot."""
    output_dir = Path("outputs")
    output_dir.mkdir(parents=True, exist_ok=True)

    print("Running 60-agent 120s merge check with ADMM ON...")
    res_admm_on = run_check(n=60, duration=120.0, use_admm=True, seed=42)
    print(
        f"ADMM ON: min_dist={res_admm_on['min_distance']:.3f}m, "
        f"ticks_below_8m={res_admm_on['ticks_below_8m']}, "
        f"merge_success={res_admm_on['merge_success_rate']:.2%}, "
        f"throughput={res_admm_on['throughput']:.4f}, "
        f"nans={res_admm_on['num_nan_states']}"
    )

    print("Running 60-agent 120s merge check with ADMM OFF...")
    res_admm_off = run_check(n=60, duration=120.0, use_admm=False, seed=42)
    print(
        f"ADMM OFF: min_dist={res_admm_off['min_distance']:.3f}m, "
        f"ticks_below_8m={res_admm_off['ticks_below_8m']}, "
        f"merge_success={res_admm_off['merge_success_rate']:.2%}, "
        f"throughput={res_admm_off['throughput']:.4f}, "
        f"nans={res_admm_off['num_nan_states']}"
    )

    # 6. Save outputs/p3_week4_merge_check.csv
    csv_path = output_dir / "p3_week4_merge_check.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "run",
            "use_admm",
            "n_agents",
            "duration_s",
            "merge_success_rate",
            "min_pairwise_distance",
            "ticks_below_8m",
            "num_nan_states",
            "throughput",
        ])
        for name, r in [("admm_on", res_admm_on), ("admm_off", res_admm_off)]:
            writer.writerow([
                name,
                r["use_admm"],
                r["n_agents"],
                r["duration_s"],
                f"{r['merge_success_rate']:.4f}",
                f"{r['min_pairwise_distance']:.4f}",
                r["ticks_below_8m"],
                r["num_nan_states"],
                f"{r['throughput']:.6f}",
            ])
    print(f"Saved CSV metrics to {csv_path}")

    # 6. Save plot outputs/p3_week4_merge_check.png
    png_path = output_dir / "p3_week4_merge_check.png"
    plt.figure(figsize=(10, 5), dpi=150)
    plt.plot(res_admm_on["times"], res_admm_on["min_distances_over_time"], label="ADMM ON", color="#1f77b4", linewidth=1.5)
    plt.plot(res_admm_off["times"], res_admm_off["min_distances_over_time"], label="ADMM OFF", color="#ff7f0e", linestyle="--", linewidth=1.5)
    plt.axhline(8.0, color="crimson", linestyle=":", linewidth=1.5, label="Min Separation Threshold (8.0 m)")
    plt.xlabel("Simulation Time (s)", fontsize=11)
    plt.ylabel("Min Pairwise Distance (m)", fontsize=11)
    plt.title("P3 Week 4: Minimum Pairwise Separation Over Time (60 Agents, 120 s)", fontsize=12, fontweight="bold")
    plt.grid(True, linestyle="--", alpha=0.6)
    plt.legend(loc="upper right", framealpha=0.9)
    plt.tight_layout()
    plt.savefig(png_path)
    plt.close()
    print(f"Saved plot to {png_path}")


if __name__ == "__main__":
    main()
