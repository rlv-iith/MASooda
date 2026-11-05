"""E4: compare architectures under a position-falsification attack."""

from __future__ import annotations

import argparse
import copy
import csv
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("MPLCONFIGDIR", "/tmp/masooda-matplotlib")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from config.load_config import get_config
from local_behavior.boids import reset_local_behavior_cache
from resilience.decentralized_undefended import run_decentralized_undefended
from simulation.engine import run_simulation
from simulation.overseer import reset_default_overseer
from simulation.scenario import make_initial_agents
from verification.metrics import compute_run_metrics, robustness_series

METRIC_KEYS = [
    "throughput_per_s", "arrivals", "safety_violation_ticks", "violation_episodes",
    "mean_recovery_time_s", "min_robustness_m", "reports_dropped", "malicious_ids",
]


def _hierarchical(agents, duration_s, loggers, attack_config, overseer_link_config):
    return run_simulation(
        agents, duration_s=duration_s, loggers=loggers, use_overseer=True,
        use_admm=True, attack_config=attack_config, defended=True,
        overseer_link_config=overseer_link_config,
    )


def build_architectures() -> dict:
    archs = {
        "hierarchical": _hierarchical,
        "decentralized_undefended": run_decentralized_undefended,
    }
    try:
        from simulation.centralized import run_centralized
        archs["centralized"] = run_centralized
    except ImportError:
        print("centralized baseline not merged yet - skipped")
    return archs


def run_one(fn, base, duration, attack_cfg):
    reset_default_overseer()
    reset_local_behavior_cache()
    return fn(copy.deepcopy(base), duration, None, attack_cfg, {"enabled": False})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()

    cfg = get_config()
    d_min = float(cfg["safety"]["minimum_separation_meters"])
    if args.quick:
        n_agents, duration, seeds = 30, 90.0, [42]
    else:
        n_agents = 60
        duration = float(cfg["simulation"]["duration_seconds"])
        seeds = cfg.get("experiments", {}).get("seeds", [42, 43, 44])
    attack_start = float(cfg["attack"]["start_time_seconds"])
    conditions = {
        False: {**cfg["attack"], "enabled": False},
        True: {**cfg["attack"], "enabled": True},
    }
    archs = build_architectures()

    rows = []
    rob_series = {}
    times_ref = None
    for seed in seeds:
        base = make_initial_agents(n_agents, seed)
        for name, fn in archs.items():
            for enabled, acfg in conditions.items():
                result = run_one(fn, base, duration, acfg)
                m = compute_run_metrics(result)
                rho = robustness_series(result.positions, d_min)
                post = int(np.sum((np.asarray(result.times) >= attack_start) & (rho < 0.0)))
                row = {"architecture": name, "seed": seed, "attack_enabled": enabled}
                row.update({k: m.get(k) for k in METRIC_KEYS})
                row["post_attack_violation_ticks"] = post
                rows.append(row)
                if enabled and seed == seeds[0]:
                    rob_series[name] = rho
                    times_ref = np.asarray(result.times)
                print(f"{name} seed={seed} attack={enabled}: "
                      f"viol={row['safety_violation_ticks']} post={post} "
                      f"minrho={row['min_robustness_m']:.2f}")

    out_dir = ROOT / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "p5_week5_e4_resilience.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    panels = [
        ("throughput_per_s", "Throughput (agents/s)"),
        ("safety_violation_ticks", "Safety violation ticks"),
        ("mean_recovery_time_s", "Mean recovery time (s)"),
        ("min_robustness_m", "Min robustness (m)"),
    ]
    names = list(archs)
    x = np.arange(len(names))
    fig, axes = plt.subplots(2, 2, figsize=(11, 8))
    for ax, (key, title) in zip(axes.ravel(), panels):
        for i, (enabled, label) in enumerate([(False, "attack off"), (True, "attack on")]):
            vals = []
            for name in names:
                v = [float(r[key]) for r in rows
                     if r["architecture"] == name and r["attack_enabled"] == enabled
                     and r[key] is not None]
                vals.append(float(np.nanmean(v)) if v and not np.all(np.isnan(v)) else 0.0)
            ax.bar(x + (i - 0.5) * 0.38, vals, 0.38, label=label)
        ax.set_xticks(x, names, rotation=12)
        ax.set_title(title)
        ax.grid(axis="y", alpha=0.25)
    axes[0, 0].legend()
    fig.tight_layout()
    fig.savefig(out_dir / "p5_week5_e4_resilience.png", dpi=150)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 4.8))
    for name, rho in rob_series.items():
        ax.plot(times_ref[: len(rho)], rho, label=name)
    ax.axvline(attack_start, color="k", linestyle="--", label="attack start")
    ax.axhline(0.0, color="gray", linewidth=0.8)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Robustness (m)")
    ax.set_title(f"Robustness under attack (seed {seeds[0]})")
    ax.legend()
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(out_dir / "p5_week5_e4_robustness_time.png", dpi=150)
    plt.close(fig)
    print(f"Saved {csv_path}")


if __name__ == "__main__":
    main()
