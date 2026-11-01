"""P1 Week 3 Demo: 30-agent integrated simulation run, trajectory logging, STL check, and animation."""

from __future__ import annotations

from pathlib import Path
import numpy as np

from config.load_config import get_config
from simulation.engine import run_simulation
from simulation.environment import build_corridors, corridor_occupancy
from simulation.logger import TrajectoryLogger
from simulation.renderer import animate_simulation
from simulation.scenario import make_initial_agents
from simulation.schema import AgentState, AgentType
from verification.stl_monitor import load_spec_from_config, load_trajectory_csv, stl_monitor


def main() -> None:
    cfg = get_config()
    dt = float(cfg["simulation"]["timestep_seconds"])
    v_max = float(cfg["safety"]["maximum_velocity_meters_per_second"])

    # 1. Initialize 30 agents and TrajectoryLogger
    print("Generating 30 initial agents...")
    agents = make_initial_agents(30)
    logger = TrajectoryLogger()

    # 2. Run simulation for 60.0 seconds with overseer
    print("Running simulation for 60.0 seconds with overseer...")
    result = run_simulation(agents, duration_s=60.0, loggers=[logger], use_overseer=True)

    # 3. Save trajectory to CSV
    csv_path = Path("outputs/p1_week3_trajectory.csv")
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    logger.to_csv(csv_path)
    print(f"Saved trajectory to {csv_path}")

    # 4. Print metrics
    # a) no NaN: True/False
    has_no_nan = bool(np.all(np.isfinite(result.positions)))
    print(f"no NaN: {has_no_nan}")

    # b) max speed
    vel_xy = np.diff(result.positions[:, :, :2], axis=0) / dt
    speeds = np.linalg.norm(vel_xy, axis=-1)
    max_speed = float(np.max(speeds))
    print(f"max speed: {max_speed:.2f} m/s (limit: {v_max:.2f} m/s)")

    # c) overseer calls and failures
    print(f"overseer calls: {result.overseer_calls}, failures: {result.overseer_failures}")

    # d) final corridor occupancy
    corridors = build_corridors()
    final_agents = [
        AgentState(
            id=aid,
            type=AgentType.DELIVERY,
            position=result.positions[-1, i],
        )
        for i, aid in enumerate(result.agent_ids)
    ]
    occupancy = corridor_occupancy(final_agents, corridors)
    print(f"final corridor occupancy: {occupancy}")

    # e) minimum pairwise distance over the whole run
    pos_2d = result.positions[:, :, :2]
    diffs = pos_2d[:, :, None, :] - pos_2d[:, None, :, :]
    pairwise_dists = np.linalg.norm(diffs, axis=-1)
    eye_mask = np.eye(len(result.agent_ids), dtype=bool)
    pairwise_dists[:, eye_mask] = np.inf
    min_pairwise_dist = float(np.min(pairwise_dists))
    print(f"minimum pairwise distance over run: {min_pairwise_dist:.3f} m")

    # 5. Offline STL check
    print("\n--- Offline STL Verification ---")
    window = load_trajectory_csv(csv_path)
    spec = load_spec_from_config()
    r = stl_monitor(window, spec)
    print(f"STL robustness value: {r.value:+.3f} m")
    print(f"STL violation: {r.violation}")

    # 6. Save animation GIF to outputs/
    output_gif = Path("outputs/p1_week3.gif")
    print(f"\nRendering animation to {output_gif}...")
    animate_simulation(result, output_gif, every_n_ticks=5)
    print(f"Saved {output_gif}")


if __name__ == "__main__":
    main()

