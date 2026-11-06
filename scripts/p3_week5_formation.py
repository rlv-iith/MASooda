"""P3 Week 5: Formation metrics, corridor merge success, throughput, and utilization sweep.

Evaluates multi-agent traffic across density levels N in {30, 45, 60, 75}
for corridor merge success rate, throughput, and corridor utilization (Section 13.3, E2).
"""

from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path
import sys

# Ensure repository root is on sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from config.load_config import get_config
from local_behavior.boids import reset_local_behavior_cache
from local_behavior.formation_metrics import FormationLogger, corridor_utilization, merge_outcomes
import simulation.engine
from simulation.overseer import reset_default_overseer
from simulation.scenario import make_initial_agents
from verification.metrics import compute_run_metrics


def run_experiment(quick: bool = False) -> tuple[list[dict], Path, Path]:
    """Execute the formation sweep experiment across agent counts and seeds.

    Parameters
    ----------
    quick : bool, default False
        Whether to run in quick test mode (N=30, seed=42, duration=30s).

    Returns
    -------
    tuple[list[dict], Path, Path]
        List of result row dictionaries, path to written CSV, path to saved PNG plot.
    """
    cfg = get_config()

    if quick:
        n_list = [30]
        seeds = [42]
        duration_s = 30.0
    else:
        exp_cfg = cfg.get("experiments", {})
        n_list = exp_cfg.get("agent_counts", [30, 45, 60, 75])
        seeds = exp_cfg.get("seeds", [42, 43, 44])
        duration_s = float(cfg["simulation"]["duration_seconds"])

    capacity = int(cfg["corridors"]["capacity"])
    attack_cfg = {**cfg.get("attack", {}), "enabled": False}
    overseer_link_cfg = {"enabled": False}

    output_dir = ROOT / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "p3_week5_formation.csv"
    png_path = output_dir / "p3_week5_formation.png"

    rows: list[dict] = []

    for n in n_list:
        for seed in seeds:
            print(f"Running simulation: N={n}, seed={seed}, duration={duration_s}s...")

            # Reset state before each simulation run
            reset_default_overseer()
            reset_local_behavior_cache()

            agents = make_initial_agents(n, seed)
            logger = FormationLogger()

            result = simulation.engine.run_simulation(
                agents,
                duration_s=duration_s,
                loggers=[logger],
                use_overseer=True,
                use_admm=True,
                attack_config=attack_cfg,
                defended=True,
                overseer_link_config=overseer_link_cfg,
            )

            # Evaluate merge outcomes
            m_res = merge_outcomes(logger, cfg)
            merge_attempts = int(m_res["merge_attempts"])
            merge_success = int(m_res["merge_success"])
            merge_failed = int(m_res["merge_failed"])
            not_reached = int(m_res["not_reached"])
            merge_success_rate = m_res["merge_success_rate"]

            if merge_attempts == 0:
                print(f"Warning: No merges happened at density N={n}, seed={seed}.")

            # Compute throughput, arrivals, and safety violations
            run_m = compute_run_metrics(result, config=cfg)
            throughput_per_s = float(run_m.get("throughput_per_s", 0.0))
            arrivals = int(run_m.get("arrivals", 0))
            safety_violation_ticks = int(run_m.get("safety_violation_ticks", 0))

            # Compute corridor utilization
            u_res = corridor_utilization(logger, capacity=capacity)
            mean_utilization = float(u_res["mean_utilization"])
            util_c0 = float(u_res.get("util_c0", 0.0))
            util_c1 = float(u_res.get("util_c1", 0.0))
            util_c2 = float(u_res.get("util_c2", 0.0))
            peak_c0 = float(u_res.get("peak_c0", 0.0))
            peak_c1 = float(u_res.get("peak_c1", 0.0))
            peak_c2 = float(u_res.get("peak_c2", 0.0))
            ticks_over_capacity = int(u_res.get("ticks_over_capacity", 0))

            row = {
                "N": n,
                "seed": seed,
                "merge_attempts": merge_attempts,
                "merge_success": merge_success,
                "merge_failed": merge_failed,
                "not_reached": not_reached,
                "merge_success_rate": merge_success_rate,
                "throughput_per_s": throughput_per_s,
                "arrivals": arrivals,
                "mean_utilization": mean_utilization,
                "util_c0": util_c0,
                "util_c1": util_c1,
                "util_c2": util_c2,
                "peak_c0": peak_c0,
                "peak_c1": peak_c1,
                "peak_c2": peak_c2,
                "ticks_over_capacity": ticks_over_capacity,
                "safety_violation_ticks": safety_violation_ticks,
            }
            rows.append(row)

    # Write CSV
    fieldnames = [
        "N",
        "seed",
        "merge_attempts",
        "merge_success",
        "merge_failed",
        "not_reached",
        "merge_success_rate",
        "throughput_per_s",
        "arrivals",
        "mean_utilization",
        "util_c0",
        "util_c1",
        "util_c2",
        "peak_c0",
        "peak_c1",
        "peak_c2",
        "ticks_over_capacity",
        "safety_violation_ticks",
    ]

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            formatted_row = dict(r)
            rate = r["merge_success_rate"]
            if np.isnan(rate):
                formatted_row["merge_success_rate"] = "NaN"
            else:
                formatted_row["merge_success_rate"] = f"{rate:.4f}"
            writer.writerow(formatted_row)

    print(f"Results written to {csv_path}")

    # Plot 3-panel figure vs N
    plot_results(rows, n_list, png_path)

    return rows, csv_path, png_path


def plot_results(rows: list[dict], n_list: list[int], png_path: Path) -> None:
    """Generate 3-panel plot of merge success rate, throughput, and utilization vs N.

    Parameters
    ----------
    rows : list[dict]
        Simulation outcome records.
    n_list : list[int]
        Unique agent density counts.
    png_path : Path
        Target image file path.
    """
    sorted_n = sorted(list(set(n_list)))

    # Aggregates vs N
    mean_merge_rate = []
    std_merge_rate = []
    mean_throughput = []
    std_throughput = []
    mean_u0, std_u0 = [], []
    mean_u1, std_u1 = [], []
    mean_u2, std_u2 = [], []

    for n in sorted_n:
        n_rows = [r for r in rows if r["N"] == n]
        count = len(n_rows)

        # Merge success rate
        rates = [r["merge_success_rate"] for r in n_rows if not np.isnan(r["merge_success_rate"])]
        if rates:
            mean_merge_rate.append(float(np.mean(rates)))
            sem = float(np.std(rates) / np.sqrt(len(rates))) if len(rates) > 1 else 0.0
            std_merge_rate.append(sem)
        else:
            mean_merge_rate.append(np.nan)
            std_merge_rate.append(0.0)

        # Throughput
        tp = [r["throughput_per_s"] for r in n_rows]
        mean_throughput.append(float(np.mean(tp)))
        sem_tp = float(np.std(tp) / np.sqrt(count)) if count > 1 else 0.0
        std_throughput.append(sem_tp)

        # Corridor utilizations
        u0 = [r["util_c0"] for r in n_rows]
        u1 = [r["util_c1"] for r in n_rows]
        u2 = [r["util_c2"] for r in n_rows]

        mean_u0.append(float(np.mean(u0)))
        std_u0.append(float(np.std(u0) / np.sqrt(count)) if count > 1 else 0.0)

        mean_u1.append(float(np.mean(u1)))
        std_u1.append(float(np.std(u1) / np.sqrt(count)) if count > 1 else 0.0)

        mean_u2.append(float(np.mean(u2)))
        std_u2.append(float(np.std(u2) / np.sqrt(count)) if count > 1 else 0.0)

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.5), dpi=150)

    # Panel 1: Merge Success Rate vs N
    ax1 = axes[0]
    ax1.errorbar(
        sorted_n,
        mean_merge_rate,
        yerr=std_merge_rate,
        fmt="o-",
        color="#1f77b4",
        capsize=5,
        capthick=1.5,
        linewidth=1.8,
        markersize=6,
    )
    ax1.set_title("Merge Success Rate vs Traffic Density", fontsize=11, fontweight="bold")
    ax1.set_xlabel("Number of Agents (N)", fontsize=10)
    ax1.set_ylabel("Merge Success Rate", fontsize=10)
    ax1.set_ylim(-0.05, 1.05)
    ax1.grid(True, linestyle="--", alpha=0.6)

    # Panel 2: Throughput (agents/s) vs N
    ax2 = axes[1]
    ax2.errorbar(
        sorted_n,
        mean_throughput,
        yerr=std_throughput,
        fmt="s-",
        color="#2ca02c",
        capsize=5,
        capthick=1.5,
        linewidth=1.8,
        markersize=6,
    )
    ax2.set_title("Airspace Throughput vs Traffic Density", fontsize=11, fontweight="bold")
    ax2.set_xlabel("Number of Agents (N)", fontsize=10)
    ax2.set_ylabel("Throughput (agents/s)", fontsize=10)
    ax2.grid(True, linestyle="--", alpha=0.6)

    # Panel 3: Mean Utilization per Corridor vs N
    ax3 = axes[2]
    ax3.errorbar(
        sorted_n,
        mean_u0,
        yerr=std_u0,
        fmt="o-",
        label="Corridor 0",
        color="#1f77b4",
        capsize=4,
        linewidth=1.5,
    )
    ax3.errorbar(
        sorted_n,
        mean_u1,
        yerr=std_u1,
        fmt="^-",
        label="Corridor 1",
        color="#ff7f0e",
        capsize=4,
        linewidth=1.5,
    )
    ax3.errorbar(
        sorted_n,
        mean_u2,
        yerr=std_u2,
        fmt="d-",
        label="Corridor 2",
        color="#9467bd",
        capsize=4,
        linewidth=1.5,
    )
    ax3.set_title("Corridor Utilization vs Traffic Density", fontsize=11, fontweight="bold")
    ax3.set_xlabel("Number of Agents (N)", fontsize=10)
    ax3.set_ylabel("Mean Utilization (Occupancy / Capacity)", fontsize=10)
    ax3.grid(True, linestyle="--", alpha=0.6)
    ax3.legend(loc="best", framealpha=0.9)

    plt.tight_layout()
    plt.savefig(png_path)
    plt.close()
    print(f"Plot saved to {png_path}")


def main() -> None:
    """CLI entry point for p3_week5_formation."""
    parser = argparse.ArgumentParser(description="P3 Week 5 Formation Evaluation")
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Run short single-density sweep (N=30, seed=42, duration=30s)",
    )
    args = parser.parse_args()
    run_experiment(quick=args.quick)


if __name__ == "__main__":
    main()

