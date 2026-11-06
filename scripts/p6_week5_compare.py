"""Comparison runner for MASooda multi-architecture experiments (Week 5).

Compares hierarchical, centralized, and decentralized_undefended architectures
on identical initial conditions under attack and non-attack conditions.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import matplotlib
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from config.load_config import get_config
from experiments.runner import (
    check_identical_conditions,
    get_runner,
    run_experiment,
    write_rows,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="P6 Week 5 Multi-Architecture Comparison")
    parser.add_argument("--quick", action="store_true", help="Quick run (30 agents, 60 s, seed 42)")
    args = parser.parse_args()

    cfg = get_config()
    exp_cfg = cfg.get("experiments", {})
    output_dir = ROOT / exp_cfg.get("output_dir", "outputs/week5")
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.quick:
        n_agents = 30
        duration_s = 60.0
        seeds = [42]
        attack_start_s = 20.0
    else:
        attack_start_s = None
        n_agents = 60
        duration_s = float(cfg["simulation"]["duration_seconds"])
        seeds = exp_cfg.get("seeds", [42, 43, 44])

    architectures = exp_cfg.get(
        "architectures",
        ["hierarchical", "centralized", "decentralized_undefended"],
    )

    rows: list[dict] = []
    series_by_arch: dict[str, tuple[np.ndarray, np.ndarray]] = {}

    for arch in architectures:
        try:
            get_runner(arch)
        except RuntimeError:
            print(f"skipped {arch}: not merged yet")
            continue

        print(f"Running experiments for architecture: {arch}")
        for seed in seeds:
            for attack_enabled in [False, True]:
                print(f"  arch={arch}, seed={seed}, attack_enabled={attack_enabled}...")
                row, (times, series) = run_experiment(
                    architecture=arch,
                    n_agents=n_agents,
                    seed=seed,
                    duration_s=duration_s,
                    attack_enabled=attack_enabled,
                    link_failure=False,
                    scenario="e4_e5",
                    return_series=True,
                    attack_start_s=attack_start_s,
                )
                rows.append(row)

                if attack_enabled and seed == seeds[0]:
                    series_by_arch[arch] = (times, series)

    # 1. Write comparison CSV
    csv_path = output_dir / "comparison.csv"
    write_rows(rows, csv_path)
    print(f"Saved comparison rows to {csv_path}")

    # 2. Check identical conditions
    passed, msg = check_identical_conditions(rows)
    status_str = "PASS" if passed else "FAIL"
    print(f"{status_str}: {msg}")
    txt_path = output_dir / "identical_conditions.txt"
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(f"{status_str}: {msg}\n")
    print(f"Saved verification report to {txt_path}")

    # 3. Plot STL robustness by architecture
    attack_start = attack_start_s if attack_start_s is not None else float(cfg.get("attack", {}).get("start_time_seconds", 60.0))
    fig, ax = plt.subplots(figsize=(10, 6))
    for arch, (times, series) in series_by_arch.items():
        ax.plot(times, series, label=arch, linewidth=1.5)

    ax.axhline(0.0, color="black", linestyle="--", linewidth=1.2, label="Safety Threshold (rho=0)")
    ax.axvline(attack_start, color="red", linestyle=":", linewidth=1.2, label=f"Attack Start ({attack_start:.0f}s)")
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("STL Robustness rho(t) (m)")
    ax.set_title(f"STL Robustness by Architecture (Attack On, Seed {seeds[0]}, {n_agents} Agents)")
    ax.legend(loc="lower left")
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    rob_plot_path = output_dir / "stl_robustness_by_architecture.png"
    plt.savefig(rob_plot_path, dpi=150)
    plt.close(fig)
    print(f"Saved STL robustness plot to {rob_plot_path}")

    # 4. Plot summary bars
    available_archs = [a for a in architectures if any(r["architecture"] == a for r in rows)]
    if available_archs:
        fig, axes = plt.subplots(1, 3, figsize=(15, 5))
        metrics_to_plot = [
            ("safety_violation_ticks", "Safety Violation Ticks", axes[0]),
            ("mean_recovery_time_s", "Mean Recovery Time (s)", axes[1]),
            ("throughput_per_s", "Throughput (arrivals/s)", axes[2]),
        ]

        x = np.arange(len(available_archs))
        width = 0.35

        for key, title, axis in metrics_to_plot:
            vals_off: list[float] = []
            vals_on: list[float] = []
            for arch in available_archs:
                off_rows = [r[key] for r in rows if r["architecture"] == arch and not r["attack_enabled"]]
                on_rows = [r[key] for r in rows if r["architecture"] == arch and r["attack_enabled"]]

                m_off = float(np.nanmean(off_rows)) if len(off_rows) > 0 and not np.all(np.isnan(off_rows)) else 0.0
                m_on = float(np.nanmean(on_rows)) if len(on_rows) > 0 and not np.all(np.isnan(on_rows)) else 0.0

                vals_off.append(0.0 if np.isnan(m_off) else m_off)
                vals_on.append(0.0 if np.isnan(m_on) else m_on)

            axis.bar(x - width / 2, vals_off, width, label="Attack Off", color="tab:blue")
            axis.bar(x + width / 2, vals_on, width, label="Attack On", color="tab:orange")
            axis.set_xticks(x)
            axis.set_xticklabels(available_archs, rotation=15 if len(available_archs) > 2 else 0)
            axis.set_title(title)
            axis.grid(True, alpha=0.3, axis="y")
            axis.legend()

        plt.tight_layout()
        bars_plot_path = output_dir / "summary_bars.png"
        plt.savefig(bars_plot_path, dpi=150)
        plt.close(fig)
        print(f"Saved summary bars plot to {bars_plot_path}")


if __name__ == "__main__":
    main()

