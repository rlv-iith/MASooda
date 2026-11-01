"""P1 Week 2 Demo: 60-agent simulation run and visualization animation."""

from __future__ import annotations

from pathlib import Path
import numpy as np

from config.load_config import get_config
from simulation.engine import run_simulation
from simulation.renderer import animate_simulation
from simulation.scenario import make_initial_agents


def main() -> None:
    cfg = get_config()
    dt = float(cfg["simulation"]["timestep_seconds"])

    print("Generating 60 initial agents...")
    agents = make_initial_agents(60)

    print("Running simulation for 60.0 seconds...")
    result = run_simulation(agents, duration_s=60.0)

    # 1. Check for NaN values
    has_no_nan = bool(np.all(np.isfinite(result.positions)))
    print(f"no NaN: {has_no_nan}")

    # 2. Compute maximum speed
    vel_xy = np.diff(result.positions[:, :, :2], axis=0) / dt
    speeds = np.linalg.norm(vel_xy, axis=-1)
    max_speed = float(np.max(speeds))
    print(f"max speed: {max_speed:.2f} m/s")

    # 3. Save animation GIF to outputs/
    output_gif = Path("outputs/p1_week2.gif")
    print(f"Rendering animation to {output_gif}...")
    animate_simulation(result, output_gif, every_n_ticks=5)
    print(f"Saved {output_gif}")


if __name__ == "__main__":
    main()

