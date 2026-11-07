"""E1 figures and README, generated from the CSVs only (no simulation).

Reads outputs/week6/e1_admm_scaling/{summary.csv, calls.csv, manifest.json,
weak_results.json}; writes six figures (PNG + PDF) to outputs/week6/figures
and e1_admm_scaling/README.md.

    python scripts/week6_e1_plot.py [--quick]
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from config.load_config import get_config  # noqa: E402
from experiments.week6 import read_rows  # noqa: E402
from experiments.week6_common import (  # noqa: E402
    exp_dir,
    fig_dir,
    find_summary,
    fmt,
    manifest_lines,
    md_summary_table,
    provisional_banner,
    weak_lines,
    write_text,
)
from visualization.plots import apply_style, distribution_plot, metric_vs_param, save_figure  # noqa: E402

SUBDIR = "e1_admm_scaling"
FIGS = [
    "e1_iterations_vs_N",
    "e1_solve_time_vs_N",
    "e1_convergence_rate_vs_N",
    "e1_time_per_tick_vs_N",
    "e1_convergence_vs_iteration_limit",
    "e1_iterations_distribution",
]
LABELS = {
    "num_agents": "N", "admm_max_iterations": "iter. limit", "admm_solver_calls": "solver calls",
    "admm_iter_mean": "mean iterations", "admm_iter_p95": "p95 iterations", "admm_converged_frac": "converged frac.",
    "admm_solve_ms_mean": "mean solve (ms)", "admm_time_per_tick_ms": "ADMM time / tick (ms)",
    "admm_max_group_size": "max group", "safety_violation_ticks": "violation ticks",
    "min_robustness_m": "min ρ (m)",
}


def _duration(d: Path) -> float:
    import json

    man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    return float(next(iter(man["config_section_resolved"].values()))["duration_s"])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args(argv)
    cfg = get_config()
    d = exp_dir(SUBDIR, args.quick)
    figs = fig_dir(args.quick)
    summary = read_rows(d / "summary.csv")
    calls = read_rows(d / "calls.csv")
    default_iters = int(cfg["admm"]["maximum_iterations"])
    sweep_n = 60 if not args.quick else int(cfg["experiments"]["week6"]["quick"]["agent_counts"][0])

    apply_style()
    by_n = [r for r in summary if int(float(r["admm_max_iterations"])) == default_iters]
    by_limit = [r for r in summary if int(float(r["num_agents"])) == sweep_n]

    for name, metric, ylabel in [
        ("e1_iterations_vs_N", "admm_iter_mean", "Mean ADMM iterations per solver call"),
        ("e1_solve_time_vs_N", "admm_solve_ms_mean", "Mean solve time per call (ms)"),
        ("e1_convergence_rate_vs_N", "admm_converged_frac", "Fraction of solver calls converged"),
        ("e1_time_per_tick_vs_N", "admm_time_per_tick_ms", "ADMM wall time per tick (ms)"),
    ]:
        fig, ax = metric_vs_param(by_n, "num_agents", metric, ylabel=ylabel, xlabel="Number of agents N",
                                  title=f"E1: {ylabel.split(' (')[0].lower()} vs N (limit {default_iters})")
        save_figure(fig, name, out_dir=figs)

    fig, axes = plt.subplots(1, 2, figsize=(10.0, 4.0))
    metric_vs_param(by_limit, "admm_max_iterations", "admm_converged_frac", ax=axes[0],
                    ylabel="Fraction of solver calls converged", xlabel="ADMM iteration limit",
                    title=f"Converged fraction (N={sweep_n})")
    metric_vs_param(by_limit, "admm_max_iterations", "admm_iter_mean", ax=axes[1],
                    ylabel="Mean iterations per call", xlabel="ADMM iteration limit",
                    title=f"Mean iterations (N={sweep_n})")
    lims_present = sorted({int(float(r["admm_max_iterations"])) for r in by_limit})
    for ax in axes:
        if any(len(ln.get_xdata()) for ln in ax.lines):  # no data (e.g. --quick): keep linear axis
            ax.set_xscale("log")
            ax.set_xticks(lims_present)
            ax.set_xticklabels([str(v) for v in lims_present])
            ax.minorticks_off()
    fig.tight_layout()
    save_figure(fig, "e1_convergence_vs_iteration_limit", out_dir=figs)

    dist_rows = [c for c in calls if int(float(c["admm_max_iterations"])) == default_iters]
    fig, ax = distribution_plot(dist_rows, "iterations", "num_agents", ylabel="Iterations per solver call",
                                title=f"E1: per-call ADMM iterations by N (limit {default_iters})")
    save_figure(fig, "e1_iterations_distribution", out_dir=figs)

    # ------------------------------------------------------------------ README
    t1_metrics = ["admm_solver_calls", "admm_iter_mean", "admm_iter_p95", "admm_converged_frac",
                  "admm_solve_ms_mean", "admm_time_per_tick_ms", "admm_max_group_size",
                  "safety_violation_ticks", "min_robustness_m"]
    t2_metrics = ["admm_solver_calls", "admm_iter_mean", "admm_converged_frac", "admm_time_per_tick_ms",
                  "safety_violation_ticks"]
    table1 = md_summary_table(summary, ["num_agents"], t1_metrics, where={"admm_max_iterations": default_iters},
                              labels=LABELS)
    table2 = md_summary_table(summary, ["admm_max_iterations"], t2_metrics, where={"num_agents": sweep_n},
                              labels=LABELS)

    obs = []
    ns = sorted({int(float(r["num_agents"])) for r in by_n})
    if ns:
        lo, hi = find_summary(by_n, num_agents=ns[0]), find_summary(by_n, num_agents=ns[-1])
        obs.append(f"Mean iterations per solver call: {fmt(lo['admm_iter_mean_mean'])} at N={ns[0]} and "
                   f"{fmt(hi['admm_iter_mean_mean'])} at N={ns[-1]}.")
        obs.append(f"Solver calls per run: {fmt(lo['admm_solver_calls_mean'])} at N={ns[0]} and "
                   f"{fmt(hi['admm_solver_calls_mean'])} at N={ns[-1]}.")
        obs.append(f"ADMM time per tick: {fmt(lo['admm_time_per_tick_ms_mean'])} ms at N={ns[0]} and "
                   f"{fmt(hi['admm_time_per_tick_ms_mean'])} ms at N={ns[-1]}.")
        obs.append("Converged fraction by N: " + ", ".join(
            f"N={n}: {fmt(find_summary(by_n, num_agents=n)['admm_converged_frac_mean'])}" for n in ns) + ".")
    lims = sorted({int(float(r["admm_max_iterations"])) for r in by_limit})
    if lims:
        obs.append(f"At N={sweep_n}, converged fraction is "
                   + ", ".join(f"{fmt(find_summary(by_limit, admm_max_iterations=lim)['admm_converged_frac_mean'])}"
                               f" at limit {lim}" for lim in lims) + ".")

    admm = cfg["admm"]
    text = f"""# E1 — ADMM scaling and convergence

{provisional_banner()}
Objective (Table 10): evaluate ADMM scaling — hierarchical architecture, 30/45/60/75 agents, no attack.
ADMM is used here as *conflict mitigation*: these numbers describe solver effort and convergence, not a
safety guarantee.

## Setup
{chr(10).join(manifest_lines(d))}
- Duration {fmt(_duration(d))} s, dt {fmt(cfg['simulation']['timestep_seconds'])} s,
  no attack, no link failure. Iteration-limit sweep at N = {sweep_n}; limit {default_iters} (config default)
  runs are shared with the scaling matrix.

## Method
Every ADMM solver call is recorded with `conflict_resolution.profiling.ADMMRecorder` (solver unchanged):
iterations, converged flag, solve time, group size (`calls.csv`, one row per call). Per run: mean / p95 / max
iterations, converged fraction, mean / p95 solve time, ADMM wall time per tick (engine `admm_time_s` / ticks),
largest group. A run with no solver call reports n/a. Tables: mean ± 95% CI half-width (t-distribution) over
seeds, n = runs with a value.

## Results — scaling with N (iteration limit {default_iters})
{table1}

## Results — iteration limit (N = {sweep_n})
{table2}

## Figures
{chr(10).join(f'- [{f}](../figures/{f}.png)' for f in FIGS)}

## Weak groups
{chr(10).join(weak_lines(d))}

## Caveats
- Config: admm.max_group_size = {admm.get('max_group_size', 'removed (conflict groups kept whole)')}, admm.merge_zone_only = {admm['merge_zone_only']},
  admm.detection_radius_meters = {admm['detection_radius_meters']} — conflicts are only detected inside the merge
  zone and groups are capped, so solver effort reflects merge-zone traffic only.
- Solve times are wall-clock on the hardware above and include Python overhead.

## Observations
{chr(10).join(f'- {o}' for o in obs[:5])}
"""
    write_text(d / "README.md", text)
    print(f"[e1] figures -> {figs}; README -> {d / 'README.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
