"""Run reproducible N-agent ADMM merge scenarios and summarize convergence."""

from __future__ import annotations

import csv
from pathlib import Path
import sys

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config.load_config import get_config
from conflict_resolution.convergence import ConvergenceLogger
from conflict_resolution.solver import ADMMSolver
from simulation.schema import AgentState, AgentType


OUTPUT_DIR = ROOT / "outputs"


def make_merge_scenario(n: int, seed: int) -> list[AgentState]:
    """Create agents clustered between two adjacent corridor centerlines."""
    if n < 2:
        raise ValueError("A merge scenario needs at least two agents")
    cfg = get_config()
    center_y = float(cfg["corridors"]["centerline_spacing_meters"]) / 2.0
    rng = np.random.default_rng(seed)
    phase = float(rng.uniform(-0.06, 0.06))
    radius = float(rng.uniform(5.6, 5.8))
    priorities = rng.choice(np.array([0, 1, 2]), size=n, replace=True)
    types = (AgentType.EMERGENCY, AgentType.EVTOL, AgentType.DELIVERY)
    agents: list[AgentState] = []
    for i in range(n):
        angle = phase + 2.0 * np.pi * i / n
        x = 750.0 + radius * np.cos(angle) + float(rng.uniform(-0.08, 0.08))
        y = center_y + radius * np.sin(angle)
        priority = int(priorities[i])
        agents.append(
            AgentState(
                id=i + 1,
                type=types[priority],
                position=np.array([x, y, 0.0]),
                velocity=np.array([float(rng.uniform(10.0, 12.0)),
                                   float(np.clip(-0.12 * (y - center_y), -0.5, 0.5)), 0.0]),
                destination=np.array([1500.0, y, 0.0]),
                priority=priority,
            )
        )
    return agents


def run_experiment() -> tuple[Path, Path]:
    cfg = get_config()
    rows: list[dict[str, float | int | bool]] = []
    for n in [2, 3, 4, 5]:
        for seed in range(20):
            agents = make_merge_scenario(n, seed)
            positions = np.array([a.position[:2] for a in agents], dtype=float)
            dt = float(cfg["simulation"]["timestep_seconds"])
            velocities = np.array([a.velocity[:2] for a in agents], dtype=float)
            targets = positions + velocities * dt
            priority_weights = cfg["admm"]["priority_weights"]
            weights = np.array([
                float(priority_weights.get(a.priority, priority_weights.get(str(a.priority), 1.0)))
                for a in agents
            ])
            logger = ConvergenceLogger()
            solver = ADMMSolver.from_config(logger=logger)
            solver.solve(positions, targets, scenario=f"{n}-agent merge seed {seed}", weights=weights)
            record = logger.records[-1]
            rows.append({
                "n_agents": n,
                "seed": seed,
                "iterations": record.iterations,
                "converged": record.converged,
                "solve_time_ms": record.solve_time_ms,
            })

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUTPUT_DIR / "p2_week3_nagent.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["n_agents", "seed", "iterations", "converged", "solve_time_ms"])
        writer.writeheader()
        writer.writerows(rows)

    ns = [2, 3, 4, 5]
    means, lower, upper = [], [], []
    for n in ns:
        values = [int(row["iterations"]) for row in rows if row["n_agents"] == n]
        mean = float(np.mean(values))
        means.append(mean)
        lower.append(mean - min(values))
        upper.append(max(values) - mean)

    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.errorbar(ns, means, yerr=np.array([lower, upper]), fmt="o-", capsize=5, linewidth=2)
    ax.set_xticks(ns)
    ax.set_xlabel("Number of agents")
    ax.set_ylabel("ADMM iterations")
    ax.set_title("N-agent merge convergence (20 seeds per group size)")
    ax.grid(True, linestyle="--", alpha=0.5)
    fig.tight_layout()
    png_path = OUTPUT_DIR / "p2_week3_nagent.png"
    fig.savefig(png_path, dpi=200)
    plt.close(fig)
    print(f"Saved {csv_path}\nSaved {png_path}")
    return csv_path, png_path


if __name__ == "__main__":
    run_experiment()
