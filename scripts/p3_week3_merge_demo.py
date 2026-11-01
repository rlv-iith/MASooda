"""P3 Week 3 Merge Demonstration Script.

Simulates 12 agents over 90 seconds. Demonstrates agents entering and
merging into corridor 1 when assigned by the overseer directive,
with merge-gap checking to avoid cutting in front of nearby traffic.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path
from typing import Any
import matplotlib.pyplot as plt
import numpy as np

from config.load_config import get_config
from local_behavior import boids
from local_behavior.boids import compute_desired_velocity, corridor_of
from simulation.interfaces import build_comm_graph, step_dynamics
from simulation.scenario import make_initial_agents
from simulation.schema import AgentState, OverseerDirective


def run_merge_scenario(
    n_agents: int = 12,
    duration_s: float = 90.0,
    seed: int = 0,
) -> tuple[np.ndarray, list[int], dict[str, Any]]:
    """Run the merge simulation scenario.

    Parameters
    ----------
    n_agents : int
        Number of agents to generate.
    duration_s : float
        Simulation duration in seconds.
    seed : int
        Random seed for initial scenario generation.

    Returns
    -------
    tuple[np.ndarray, list[int], dict[str, Any]]
        - position_history of shape (T, N, 2)
        - agent_ids list of length N
        - metrics dictionary with merge statistics and pairwise distances
    """
    boids._last_corridor.clear()

    cfg = get_config()
    dt = float(cfg["simulation"]["timestep_seconds"])
    tau = float(cfg["control"]["velocity_time_constant_seconds"])
    merge_zone = cfg["corridors"]["merge_zone_x_meters"]
    merge_start = float(merge_zone[0])
    merge_end = float(merge_zone[1])
    centerline_spacing = float(cfg["corridors"]["centerline_spacing_meters"])

    agents: list[AgentState] = make_initial_agents(n_agents, seed)
    agent_ids = [a.id for a in agents]
    n = len(agents)

    # Build fixed OverseerDirective: sends corridor 0 agents to corridor 1, others stay
    start_corridors: dict[int, int] = {}
    target_corridors: dict[int, int] = {}
    for a in agents:
        start_c = corridor_of(a.position[1])
        start_corridors[a.id] = start_c
        target_c = 1 if start_c == 0 else start_c
        target_corridors[a.id] = target_c

    directive = OverseerDirective(
        corridor_map=target_corridors,
        priority_table={},
        altitude_map={},
        timestamp=0.0,
    )

    num_steps = int(round(duration_s / dt))
    # Record history: shape (T, N, 2)
    history: list[list[list[float]]] = []

    # Track crossing x position for each agent
    crossing_x: dict[int, float | None] = {aid: None for aid in agent_ids}
    min_pairwise_distance = float("inf")
    has_nan = False

    # Check initial pairwise distances
    for i in range(n):
        for j in range(i + 1, n):
            d = float(np.linalg.norm(agents[i].position[:2] - agents[j].position[:2]))
            min_pairwise_distance = min(min_pairwise_distance, d)

    # Record initial position step
    history.append([[float(a.position[0]), float(a.position[1])] for a in agents])

    for step in range(num_steps):
        comm_graph = build_comm_graph(agents)
        agent_by_id = {a.id: a for a in agents}

        commands: list[np.ndarray] = []
        for agent in agents:
            neighbor_ids = comm_graph.neighbors(agent.id)
            neighbors = [agent_by_id[nid] for nid in neighbor_ids if nid in agent_by_id and nid != agent.id]

            v_des = compute_desired_velocity(agent, neighbors, directive)
            if np.isnan(v_des).any():
                has_nan = True

            accel = (v_des - agent.velocity) / tau
            if np.isnan(accel).any():
                has_nan = True
            commands.append(accel)

        new_agents: list[AgentState] = []
        for agent, accel in zip(agents, commands):
            stepped = step_dynamics(agent, accel, dt)
            if np.isnan(stepped.position).any() or np.isnan(stepped.velocity).any():
                has_nan = True
            new_agents.append(stepped)
        agents = new_agents

        # Record positions
        step_pos = [[float(a.position[0]), float(a.position[1])] for a in agents]
        history.append(step_pos)

        # Check pairwise distances & crossings
        for i in range(n):
            aid = agents[i].id
            curr_c = corridor_of(agents[i].position[1])

            # Check crossing for merging agents
            if target_corridors[aid] != start_corridors[aid] and crossing_x[aid] is None:
                if curr_c == target_corridors[aid]:
                    crossing_x[aid] = float(agents[i].position[0])

            for j in range(i + 1, n):
                d = float(np.linalg.norm(agents[i].position[:2] - agents[j].position[:2]))
                min_pairwise_distance = min(min_pairwise_distance, d)

    final_corridors = {a.id: corridor_of(a.position[1]) for a in agents}
    pos_history = np.array(history, dtype=float)  # (T, N, 2)

    # Calculate metrics
    merging_agents = [aid for aid in agent_ids if target_corridors[aid] != start_corridors[aid]]
    num_merging = len(merging_agents)

    successful_merges = [aid for aid in merging_agents if final_corridors[aid] == target_corridors[aid]]
    merge_success_rate = len(successful_merges) / num_merging if num_merging > 0 else 1.0

    inside_merge_zone_crossings = [
        aid for aid in merging_agents
        if crossing_x[aid] is not None and merge_start <= crossing_x[aid] <= merge_end
    ]
    pct_inside_merge_zone = (
        len(inside_merge_zone_crossings) / num_merging * 100.0 if num_merging > 0 else 100.0
    )

    metrics: dict[str, Any] = {
        "start_corridors": start_corridors,
        "target_corridors": target_corridors,
        "final_corridors": final_corridors,
        "crossing_x": crossing_x,
        "has_nan": has_nan,
        "num_merging": num_merging,
        "merge_success_rate": merge_success_rate,
        "pct_inside_merge_zone": pct_inside_merge_zone,
        "min_pairwise_distance": min_pairwise_distance,
        "merge_start": merge_start,
        "merge_end": merge_end,
    }
    return pos_history, agent_ids, metrics


def main() -> None:
    pos_history, agent_ids, metrics = run_merge_scenario(n_agents=12, duration_s=90.0, seed=0)

    os.makedirs("outputs", exist_ok=True)
    csv_path = Path("outputs") / "p3_week3_merge.csv"

    print("=== P3 Week 3 Merge Scenario Results ===")
    print(f"Agent count: {len(agent_ids)}, Duration: 90.0s")
    print(f"No NaN: {not metrics['has_nan']}")
    print(f"Merge success rate: {metrics['merge_success_rate']:.2%}")
    print(f"% of merges whose crossing x was inside merge zone: {metrics['pct_inside_merge_zone']:.1f}%")
    print(f"Minimum pairwise distance over the run: {metrics['min_pairwise_distance']:.3f} m")

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["agent_id", "start_corridor", "target_corridor", "final_corridor", "crossing_x"])
        for aid in agent_ids:
            cx = metrics["crossing_x"][aid]
            cx_str = f"{cx:.2f}" if cx is not None else "N/A"
            writer.writerow([
                aid,
                metrics["start_corridors"][aid],
                metrics["target_corridors"][aid],
                metrics["final_corridors"][aid],
                cx_str,
            ])
            print(
                f"Agent {aid:2d}: start={metrics['start_corridors'][aid]}, "
                f"target={metrics['target_corridors'][aid]}, "
                f"final={metrics['final_corridors'][aid]}, "
                f"crossing_x={cx_str}"
            )

    print(f"Saved CSV results to {csv_path}")

    # Save top-down trajectory plot
    png_path = Path("outputs") / "p3_week3_merge.png"
    plt.figure(figsize=(14, 6))

    merge_start = metrics["merge_start"]
    merge_end = metrics["merge_end"]

    # Shaded merge zone
    plt.axvspan(merge_start, merge_end, color="gold", alpha=0.25, label=f"Merge Zone [{merge_start:.0f}, {merge_end:.0f}] m")

    # Centerlines and corridor boundaries
    corridors = [0, 1, 2]
    cfg = get_config()
    spacing = float(cfg["corridors"]["centerline_spacing_meters"])
    for c in corridors:
        cy = c * spacing
        plt.axhline(cy, color="gray", linestyle="--", alpha=0.6, label="Centerline" if c == 0 else "")
        plt.axhline(cy - 10.0, color="lightgray", linestyle=":", alpha=0.4)
        plt.axhline(cy + 10.0, color="lightgray", linestyle=":", alpha=0.4)

    colors = plt.cm.tab20(np.linspace(0, 1, len(agent_ids)))
    for idx, aid in enumerate(agent_ids):
        traj_x = pos_history[:, idx, 0]
        traj_y = pos_history[:, idx, 1]
        target_c = metrics["target_corridors"][aid]
        start_c = metrics["start_corridors"][aid]
        label = f"Agent {aid} ({start_c}->{target_c})" if start_c != target_c else f"Agent {aid} (corr {start_c})"
        plt.plot(traj_x, traj_y, color=colors[idx], label=label, linewidth=1.8)
        plt.scatter(traj_x[0], traj_y[0], color=colors[idx], marker="o", s=30)
        plt.scatter(traj_x[-1], traj_y[-1], color=colors[idx], marker="x", s=40)

    plt.xlabel("X Position (m)")
    plt.ylabel("Y Position (m)")
    plt.title("P3 Week 3: Multi-Agent Corridor Merge Trajectories (90 s)")
    plt.legend(bbox_to_anchor=(1.02, 1), loc="upper left", fontsize=9)
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(png_path, dpi=150)
    plt.close()
    print(f"Saved trajectory plot to {png_path}")


if __name__ == "__main__":
    main()
