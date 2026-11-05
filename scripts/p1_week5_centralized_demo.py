"""Centralized architecture demonstration script (P1 Week 5)."""

from __future__ import annotations

import argparse
import copy
import csv
from pathlib import Path
import sys

import matplotlib
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from config.load_config import get_config
from simulation.centralized import run_centralized
from simulation.scenario import make_initial_agents
from verification.metrics import compute_run_metrics, robustness_series


def main() -> None:
    parser = argparse.ArgumentParser(description="P1 Week 5 Centralized Architecture Demo")
    parser.add_argument("--quick", action="store_true", help="Run quick demo (30 agents, 30 s, seed 42)")
    args = parser.parse_args()

    cfg = get_config()
    d_min = float(cfg["safety"]["minimum_separation_meters"])

    if args.quick:
        num_agents = 30
        duration_s = 30.0
        seeds = [42]
    else:
        num_agents = int(cfg["simulation"].get("num_agents", 60))
        duration_s = float(cfg["simulation"].get("duration_seconds", 180.0))
        seeds = cfg.get("experiments", {}).get("seeds", [42, 43, 44])

    attack_base = cfg.get("attack", {})

    all_metrics: list[dict] = []
    seed_42_results: dict[bool, tuple] = {}

    print(f"Running centralized demo with num_agents={num_agents}, duration={duration_s}s, seeds={seeds}")

    for seed in seeds:
        print(f"--- Running seed {seed} ---")
        base_agents = make_initial_agents(num_agents, seed=seed)

        for attack_enabled in [False, True]:
            case_label = "attack_on" if attack_enabled else "attack_off"
            print(f"  Simulating {case_label} (seed={seed})...")
            attack_cfg = {**attack_base, "enabled": attack_enabled}
            agents_copy = copy.deepcopy(base_agents)

            result = run_centralized(agents_copy, duration_s=duration_s, attack_config=attack_cfg)
            metrics = compute_run_metrics(result, config=cfg)
            metrics["architecture"] = "centralized"
            metrics["seed"] = seed
            metrics["attack_enabled"] = attack_enabled

            all_metrics.append(metrics)

            if seed == 42:
                seed_42_results[attack_enabled] = (result.times, result.positions)

    # Write outputs/p1_week5_centralized.csv
    csv_path = ROOT / "outputs" / "p1_week5_centralized.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    if all_metrics:
        fieldnames = list(all_metrics[0].keys())
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in all_metrics:
                writer.writerow(row)
        print(f"Saved metrics CSV to {csv_path}")

    # Write outputs/p1_week5_centralized.png
    if False in seed_42_results and True in seed_42_results:
        times_off, pos_off = seed_42_results[False]
        times_on, pos_on = seed_42_results[True]

        dist_off = robustness_series(pos_off, d_min) + d_min
        dist_on = robustness_series(pos_on, d_min) + d_min

        fig, ax = plt.subplots(figsize=(10, 6))
        ax.plot(times_off, dist_off, label="Attack Off", color="tab:blue", linewidth=1.5)
        ax.plot(times_on, dist_on, label="Attack On", color="tab:red", linewidth=1.5)
        ax.axhline(d_min, color="black", linestyle="--", linewidth=1.2, label=f"Minimum Separation ({d_min:.1f} m)")
        ax.set_xlabel("Time (s)")
        ax.set_ylabel("Minimum Pairwise Distance (m)")
        ax.set_title(f"Centralized Architecture: Minimum Pairwise Distance vs Time (Seed 42, {num_agents} agents)")
        ax.legend(loc="upper right")
        ax.grid(True, alpha=0.3)
        plt.tight_layout()

        png_path = ROOT / "outputs" / "p1_week5_centralized.png"
        plt.savefig(png_path, dpi=150)
        plt.close(fig)
        print(f"Saved distance plot to {png_path}")


if __name__ == "__main__":
    main()

