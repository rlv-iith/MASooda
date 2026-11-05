"""P2 Week 5 — ADMM scaling experiment E1 (Lalith).

Measures how ADMM conflict resolution scales inside the full hierarchical
simulation for varying agent counts N, with no attack.

Metrics per run:
  - ADMM convergence iterations (mean, p95, max)
  - Convergence (solve) time per ADMM call
  - Conflict-resolution time per simulation tick

Outputs:
  - outputs/p2_week5_admm_scaling.csv       (summary rows)
  - outputs/p2_week5_admm_scaling_calls.csv  (every solver call record)
  - outputs/p2_week5_admm_scaling.png        (3-panel figure)
"""

from __future__ import annotations

import argparse
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
from conflict_resolution.profiling import ADMMRecorder, summarize
from simulation.scenario import make_initial_agents
import simulation.engine
import simulation.overseer
import local_behavior.boids
from verification.metrics import compute_run_metrics


OUT = ROOT / "outputs"


def _run_one(N: int, seed: int, duration_s: float, cfg: dict) -> dict:
    """Run a single simulation and return a summary row dict."""
    simulation.overseer.reset_default_overseer()
    local_behavior.boids.reset_local_behavior_cache()

    agents = make_initial_agents(N, seed)

    with ADMMRecorder() as rec:
        rec.current_tag = {"N": N, "seed": seed}
        result = simulation.engine.run_simulation(
            agents,
            duration_s=duration_s,
            use_overseer=True,
            use_admm=True,
            attack_config={**cfg["attack"], "enabled": False},
            defended=True,
            overseer_link_config={"enabled": False},
        )

    ticks = len(result.times) - 1
    stats = result.stats
    admm_events = stats.get("admm_events", 0)
    admm_nonconverged = stats.get("admm_nonconverged", 0)
    admm_time_s = stats.get("admm_time_s", 0.0)

    s = summarize(rec.records)

    run_metrics = compute_run_metrics(result)
    throughput_per_s = run_metrics.get("throughput_per_s", 0.0)
    safety_violation_ticks = run_metrics.get("safety_violation_ticks", 0)

    resolve_time_per_tick_ms = (admm_time_s / ticks * 1000.0) if ticks > 0 else float("nan")

    row = {
        "N": N,
        "seed": seed,
        "admm_events": admm_events,
        "admm_nonconverged": admm_nonconverged,
        "solver_calls": s["count"],
        "mean_iterations": s["mean_iterations"],
        "p95_iterations": s["p95_iterations"],
        "max_iterations": s["max_iterations"],
        "mean_solve_ms": s["mean_solve_ms"],
        "p95_solve_ms": s["p95_solve_ms"],
        "fraction_converged": s["fraction_converged"],
        "resolve_time_per_tick_ms": resolve_time_per_tick_ms,
        "throughput_per_s": throughput_per_s,
        "safety_violation_ticks": safety_violation_ticks,
    }

    return row, rec.records


def main() -> None:
    parser = argparse.ArgumentParser(description="ADMM scaling experiment E1")
    parser.add_argument("--quick", action="store_true",
                        help="Quick smoke test: N=30, seed=42, 30 s")
    args = parser.parse_args()

    cfg = get_config()

    if args.quick:
        agent_counts = [30]
        seeds = [42]
        duration_s = 30.0
    else:
        experiments = cfg.get("experiments", {})
        agent_counts = experiments.get("agent_counts", [30, 45, 60, 75])
        seeds = experiments.get("seeds", [42, 43, 44])
        duration_s = float(cfg["simulation"]["duration_seconds"])

    OUT.mkdir(parents=True, exist_ok=True)

    summary_rows: list[dict] = []
    all_call_records: list[dict] = []

    for N in agent_counts:
        for seed in seeds:
            print(f"Running N={N}, seed={seed}, duration={duration_s:.0f}s ...")
            row, call_records = _run_one(N, seed, duration_s, cfg)
            summary_rows.append(row)
            all_call_records.extend(call_records)

    # ---- Write summary CSV ----
    csv_path = OUT / "p2_week5_admm_scaling.csv"
    with csv_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(summary_rows[0].keys()))
        writer.writeheader()
        writer.writerows(summary_rows)

    # ---- Write per-call CSV ----
    calls_csv = OUT / "p2_week5_admm_scaling_calls.csv"
    if all_call_records:
        with calls_csv.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(all_call_records[0].keys()))
            writer.writeheader()
            writer.writerows(all_call_records)

    # ---- Aggregate by N for plotting ----
    from collections import defaultdict
    by_n: dict[int, list[dict]] = defaultdict(list)
    for row in summary_rows:
        by_n[row["N"]].append(row)

    ns = sorted(by_n.keys())
    mean_iters = [np.mean([r["mean_iterations"] for r in by_n[n]]) for n in ns]
    std_iters = [np.std([r["mean_iterations"] for r in by_n[n]]) for n in ns]
    mean_solve = [np.mean([r["mean_solve_ms"] for r in by_n[n]]) for n in ns]
    std_solve = [np.std([r["mean_solve_ms"] for r in by_n[n]]) for n in ns]
    mean_resolve_tick = [np.mean([r["resolve_time_per_tick_ms"] for r in by_n[n]]) for n in ns]
    std_resolve_tick = [np.std([r["resolve_time_per_tick_ms"] for r in by_n[n]]) for n in ns]

    max_iters_cfg = int(cfg.get("admm", {}).get("maximum_iterations", 50))

    # ---- 3-panel plot ----
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.8))

    ax = axes[0]
    ax.errorbar(ns, mean_iters, yerr=std_iters, marker="o", capsize=4, linewidth=1.5)
    ax.axhline(max_iters_cfg, color="red", linestyle="--", alpha=0.7,
               label=f"max_iterations = {max_iters_cfg}")
    ax.set_xlabel("Number of agents (N)")
    ax.set_ylabel("Mean ADMM iterations")
    ax.set_title("ADMM Iterations vs N")
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.25)

    ax = axes[1]
    ax.errorbar(ns, mean_solve, yerr=std_solve, marker="s", capsize=4, linewidth=1.5,
                color="tab:orange")
    ax.set_xlabel("Number of agents (N)")
    ax.set_ylabel("Mean solve time (ms)")
    ax.set_title("ADMM Solve Time vs N")
    ax.grid(axis="y", alpha=0.25)

    ax = axes[2]
    ax.errorbar(ns, mean_resolve_tick, yerr=std_resolve_tick, marker="^", capsize=4,
                linewidth=1.5, color="tab:green")
    ax.set_xlabel("Number of agents (N)")
    ax.set_ylabel("Resolve time per tick (ms)")
    ax.set_title("Resolve Time per Tick vs N")
    ax.grid(axis="y", alpha=0.25)

    fig.suptitle("P2 Week 5 — ADMM Scaling Experiment E1", fontsize=13, y=1.02)
    fig.tight_layout()
    fig.savefig(OUT / "p2_week5_admm_scaling.png", dpi=160, bbox_inches="tight")
    plt.close(fig)

    # ---- Print table ----
    print()
    header = f"{'N':>4}  {'seed':>4}  {'events':>6}  {'nonconv':>7}  {'calls':>6}  " \
             f"{'mean_it':>8}  {'p95_it':>7}  {'max_it':>7}  " \
             f"{'solve_ms':>9}  {'res/tick_ms':>11}  {'thr/s':>6}  {'viol':>5}"
    print(header)
    print("-" * len(header))
    for r in summary_rows:
        print(f"{r['N']:>4}  {r['seed']:>4}  {r['admm_events']:>6}  "
              f"{r['admm_nonconverged']:>7}  {r['solver_calls']:>6}  "
              f"{r['mean_iterations']:>8.1f}  {r['p95_iterations']:>7.1f}  "
              f"{r['max_iterations']:>7.0f}  "
              f"{r['mean_solve_ms']:>9.3f}  {r['resolve_time_per_tick_ms']:>11.3f}  "
              f"{r['throughput_per_s']:>6.2f}  {r['safety_violation_ticks']:>5}")

    print(f"\nSaved: {csv_path}")
    print(f"Saved: {calls_csv}")
    print(f"Saved: outputs/p2_week5_admm_scaling.png")


if __name__ == "__main__":
    main()
