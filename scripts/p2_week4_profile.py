"""Profile conflict detection and ADMM conflict resolution per tick."""

from __future__ import annotations

import csv
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("MPLCONFIGDIR", "/tmp/masooda-matplotlib")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from config.load_config import get_config
from conflict_resolution.adapter import resolve_all_conflicts
from conflict_resolution.detection import detect_conflicts
from simulation.scenario import make_initial_agents


OUT = ROOT / "outputs"


def in_merge_zone_agents(n: int):
    agents = make_initial_agents(n, seed=42)
    merge_start = float(get_config()["corridors"]["merge_zone_x_meters"][0])
    for i, agent in enumerate(agents):
        agent.position[0] = merge_start + (i % 20) * 5.0
        agent.velocity[:] = [12.0, 0.0, 0.0]
    return agents


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for n in (30, 45, 60, 75):
        agents = in_merge_zone_agents(n)
        priorities = {a.id: a.priority for a in agents}
        groups = detect_conflicts(agents)
        detect_times = []
        for _ in range(20):
            start = time.perf_counter()
            detect_conflicts(agents)
            detect_times.append(time.perf_counter() - start)

        resolve_times = []
        converged = []
        for _ in range(20):
            start = time.perf_counter()
            events = resolve_all_conflicts(agents, priorities)
            resolve_times.append(time.perf_counter() - start)
            converged.extend(event.converged for event in events)

        rows.append({
            "agents": n,
            "mean_resolve_seconds": statistics.mean(resolve_times),
            "max_resolve_seconds": max(resolve_times),
            "groups": len(groups),
            "mean_admm_iterations": float("nan"),
            "fraction_converged": statistics.mean(converged) if converged else float("nan"),
            "mean_detect_seconds": statistics.mean(detect_times),
            "max_detect_seconds": max(detect_times),
        })

    csv_path = OUT / "p2_week4_profile.csv"
    with csv_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    fig, ax = plt.subplots(figsize=(8, 4.8))
    x = np.arange(len(rows))
    width = 0.36
    ax.bar(x - width / 2, [r["mean_resolve_seconds"] * 1000 for r in rows], width, label="Resolve all conflicts")
    ax.bar(x + width / 2, [r["mean_detect_seconds"] * 1000 for r in rows], width, label="Detection only")
    ax.set_xticks(x, [str(r["agents"]) for r in rows])
    ax.set_xlabel("Agents")
    ax.set_ylabel("Mean time per call (ms)")
    ax.set_title("P2 Week 4 conflict resolution profile")
    ax.legend()
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(OUT / "p2_week4_profile.png", dpi=160)
    plt.close(fig)
    print(f"Saved {csv_path} and outputs/p2_week4_profile.png")


if __name__ == "__main__":
    main()
