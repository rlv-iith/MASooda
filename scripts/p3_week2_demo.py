"""P3 Week 2 Demonstration Script: Boids Local Behavior Simulation.

Simulates 10 agents over 60 seconds across corridors 0, 1, 2.
Evaluates separation safety, lateral deviation, and absence of NaNs.
Plots trajectories to outputs/p3_week2.png.
"""

from __future__ import annotations

import os
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np

from config.load_config import get_config
from local_behavior.boids import corridor_of
from simulation.dynamics import step_dynamics
from simulation.interfaces import update_local_behavior
from simulation.overseer import mock_overseer_update
from simulation.schema import AgentState, AgentType, GlobalStateSnapshot


def create_demo_agents() -> list[AgentState]:
    """Create 10 agents by hand across corridors 0, 1, 2.

    Corridors:
      Corridor 0: y = 0 m
      Corridor 1: y = 50 m
      Corridor 2: y = 100 m

    All agents have x between 0 and 100 m, are at least 10 m apart,
    initial velocity (10, 0, 0), and destination (1450, same y, 0).
    """
    initial_specs = [
        # (id, x, y, corridor)
        # Corridor 0 (y = 0.0)
        (0, 10.0, 0.0, 0),
        (1, 40.0, 0.0, 0),
        (3, 70.0, 0.0, 0),
        # Corridor 1 (y = 50.0) - agent 2 matches mock overseer corridor map (2 -> 1)
        (2, 15.0, 50.0, 1),
        (4, 45.0, 50.0, 1),
        (5, 75.0, 50.0, 1),
        # Corridor 2 (y = 100.0)
        (6, 20.0, 100.0, 2),
        (7, 45.0, 100.0, 2),
        (8, 70.0, 100.0, 2),
        (9, 80.0, 100.0, 2),
    ]

    agents = []
    for aid, x, y, corr in initial_specs:
        agent = AgentState(
            id=aid,
            type=AgentType.DELIVERY,
            position=np.array([x, y, 0.0], dtype=float),
            velocity=np.array([10.0, 0.0, 0.0], dtype=float),
            acceleration=np.array([0.0, 0.0, 0.0], dtype=float),
            destination=np.array([1450.0, y, 0.0], dtype=float),
            corridor_assignment=corr,
        )
        agents.append(agent)
    return agents


def run_demo() -> None:
    cfg = get_config()
    dt = float(cfg["simulation"]["timestep_seconds"])
    comm_radius = float(cfg["communication"]["radius_meters"])
    centerline_spacing = float(cfg["corridors"]["centerline_spacing_meters"])
    total_time = 60.0
    num_steps = int(round(total_time / dt))

    agents = create_demo_agents()

    # History tracking for analysis and plotting: agent_id -> list of (x, y)
    trajectory_history: dict[int, list[tuple[float, float]]] = {a.id: [] for a in agents}
    for a in agents:
        trajectory_history[a.id].append((float(a.position[0]), float(a.position[1])))

    has_nan = False
    min_distance = float("inf")
    max_lateral_offset = 0.0

    # Initial distance and offset checks
    n_agents = len(agents)
    for i in range(n_agents):
        y_target = corridor_of(agents[i].position[1]) * centerline_spacing
        max_lateral_offset = max(max_lateral_offset, abs(agents[i].position[1] - y_target))
        for j in range(i + 1, n_agents):
            d = float(np.linalg.norm(agents[i].position[:2] - agents[j].position[:2]))
            min_distance = min(min_distance, d)

    # Simulation loop
    for step in range(num_steps):
        t = step * dt
        snapshot = GlobalStateSnapshot(
            timestamp=t,
            agent_ids=[a.id for a in agents],
            corridor_occupancy={0: 3, 1: 3, 2: 4},
        )
        directive = mock_overseer_update(snapshot)

        commands: list[np.ndarray] = []
        for agent in agents:
            # Neighbors within communication radius (x, y distance)
            neighbors = [
                other
                for other in agents
                if other.id != agent.id
                and float(np.linalg.norm(agent.position[:2] - other.position[:2])) <= comm_radius
            ]

            v_des = update_local_behavior(agent, neighbors, directive)
            if np.isnan(v_des).any():
                has_nan = True

            accel = (v_des - agent.velocity) / dt
            if np.isnan(accel).any():
                has_nan = True

            commands.append(accel)

        # Step dynamics for all agents
        new_agents: list[AgentState] = []
        for agent, accel in zip(agents, commands):
            stepped = step_dynamics(agent, accel, dt)
            if np.isnan(stepped.position).any() or np.isnan(stepped.velocity).any():
                has_nan = True
            new_agents.append(stepped)
        agents = new_agents

        # Record metrics and trajectories
        for i in range(n_agents):
            pos_xy = (float(agents[i].position[0]), float(agents[i].position[1]))
            trajectory_history[agents[i].id].append(pos_xy)

            # Lateral offset from assigned/target corridor centerline
            target_corr = agents[i].corridor_assignment
            if target_corr is None:
                target_corr = corridor_of(agents[i].position[1])
            y_target = float(target_corr) * centerline_spacing
            lat_offset = abs(agents[i].position[1] - y_target)
            max_lateral_offset = max(max_lateral_offset, lat_offset)

            for j in range(i + 1, n_agents):
                d = float(np.linalg.norm(agents[i].position[:2] - agents[j].position[:2]))
                min_distance = min(min_distance, d)

    print(f"no NaN: {not has_nan}")
    print(f"minimum distance between any two agents over the run: {min_distance:.3f} m")
    print(f"max lateral offset from the corridor centerline: {max_lateral_offset:.3f} m")

    # Plot trajectories
    os.makedirs("outputs", exist_ok=True)
    plt.figure(figsize=(12, 6))

    colors = plt.cm.tab10(np.linspace(0, 1, n_agents))
    for idx, (aid, traj) in enumerate(trajectory_history.items()):
        xs = [pt[0] for pt in traj]
        ys = [pt[1] for pt in traj]
        plt.plot(xs, ys, label=f"Agent {aid}", color=colors[idx], linewidth=1.8)
        plt.scatter(xs[0], ys[0], color=colors[idx], marker="o", s=30)
        plt.scatter(xs[-1], ys[-1], color=colors[idx], marker="x", s=40)

    # Plot corridor centerlines
    corridor_ys = [0.0, 50.0, 100.0]
    for cy in corridor_ys:
        plt.axhline(cy, color="gray", linestyle="--", alpha=0.6, label="Centerline" if cy == 0 else "")
        plt.axhline(cy - 10.0, color="gray", linestyle=":", alpha=0.3)
        plt.axhline(cy + 10.0, color="gray", linestyle=":", alpha=0.3)

    plt.xlabel("X Position (m)")
    plt.ylabel("Y Position (m)")
    plt.title("P3 Week 2: Local Behavior Simulation Trajectories (60 s)")
    plt.legend(bbox_to_anchor=(1.02, 1), loc="upper left")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plot_path = Path("outputs") / "p3_week2.png"
    plt.savefig(plot_path, dpi=150)
    plt.close()
    print(f"Saved trajectory plot to {plot_path}")


if __name__ == "__main__":
    run_demo()
