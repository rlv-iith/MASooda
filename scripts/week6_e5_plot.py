"""E5 figures and README from e5_stl/{stl_runs.csv, stl_summary.csv} only.

Figures: e5_robustness_distribution, e5_violation_fraction_vs_N,
e5_recovery_time, e5_robustness_heatmap.

    python scripts/week6_e5_plot.py [--quick]
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from config.load_config import get_config  # noqa: E402
from experiments.week6 import read_rows  # noqa: E402
from experiments.week6_common import (  # noqa: E402
    exp_dir,
    fig_dir,
    fmt,
    md_summary_table,
    provisional_banner,
    write_text,
)
from visualization.plots import (  # noqa: E402
    apply_style,
    display_label,
    distribution_plot,
    metric_bars,
    metric_vs_param,
    save_figure,
)

SUBDIR = "e5_stl"
FIGS = ["e5_robustness_distribution", "e5_violation_fraction_vs_N", "e5_recovery_time", "e5_robustness_heatmap"]
POOLED = "nominal (pooled)"
LABELS = {"scenario": "scenario", "condition": "condition", "architecture": "architecture", "num_agents": "N",
          "min_robustness_m": "min ρ (m)", "p5_robustness_m": "p5 ρ (m)", "violation_fraction": "violating frac.",
          "violation_episodes": "episodes", "mean_recovery_time_s": "mean recovery (s)",
          "max_recovery_time_s": "max recovery (s)"}


def _f(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args(argv)
    cfg = get_config()
    d = exp_dir(SUBDIR, args.quick)
    figs = fig_dir(args.quick)
    runs = read_rows(d / "stl_runs.csv")
    summary = read_rows(d / "stl_summary.csv")
    man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    d_min = float(cfg["safety"]["minimum_separation_meters"])
    apply_style()

    nominal_runs = []
    seen = set()
    for r in sorted(runs, key=lambda r: (r["architecture"], int(r["num_agents"]), int(r["seed"]), r["source"])):
        key = (r["architecture"], r["num_agents"], r["seed"])
        if r["condition"] == "nominal" and key not in seen:
            seen.add(key)
            nominal_runs.append(r)
    fig, ax = distribution_plot(nominal_runs, "p5_robustness_m", "architecture",
                                ylabel="5th-percentile robustness ρ over the run (m)",
                                title="E5: robustness distribution, nominal runs (all N)")
    ax.axhline(0.0, color="black", linestyle="--", linewidth=1.0)
    save_figure(fig, "e5_robustness_distribution", out_dir=figs)

    pooled = read_rows(d / "stl_summary_pooled.csv")
    fig, ax = metric_vs_param(pooled, "num_agents", "violation_fraction", hue="architecture",
                              xlabel="Number of agents N", ylabel="Fraction of ticks with ρ < 0",
                              title="E5: violating fraction vs N (nominal runs)")
    save_figure(fig, "e5_violation_fraction_vs_N", out_dir=figs)

    # recovery: one bar per (scenario/condition) x architecture, N = 60 where available
    rec_rows = []
    for r in summary:
        if r["scenario"] == POOLED or int(_f(r["num_agents"])) != 60:
            continue
        rec_rows.append({**r, "setting": f"{r['scenario'].split('_')[0].upper()} {r['condition']}"})
    fig, ax = metric_bars(rec_rows, "mean_recovery_time_s", "setting", hue="architecture",
                          title="E5: mean recovery time per condition (N = 60)")
    for lab in ax.get_xticklabels():
        lab.set_rotation(30)
        lab.set_ha("right")
    save_figure(fig, "e5_recovery_time", out_dir=figs)

    # heatmap: rows = scenario|condition|architecture, cols = N, value = mean p5 robustness
    keys = sorted({(r["scenario"], r["condition"], r["architecture"]) for r in summary if r["scenario"] != POOLED})
    ns = sorted({int(_f(r["num_agents"])) for r in summary})
    mat = np.full((len(keys), len(ns)), np.nan)
    for r in summary:
        k = (r["scenario"], r["condition"], r["architecture"])
        if k in keys:
            mat[keys.index(k), ns.index(int(_f(r["num_agents"])))] = _f(r["p5_robustness_m_mean"])
    fig, ax = plt.subplots(figsize=(7.5, max(3.0, 0.32 * len(keys) + 1.2)), layout="constrained")
    finite = mat[np.isfinite(mat)]
    lim = max(1.0, float(np.max(np.abs(finite)))) if finite.size else 1.0
    im = ax.imshow(np.ma.masked_invalid(mat), cmap=plt.get_cmap("RdBu").with_extremes(bad="#DDDDDD"),
                   vmin=-lim, vmax=lim, aspect="auto")
    for i in range(len(keys)):
        for j in range(len(ns)):
            ax.text(j, i, "n/a" if not np.isfinite(mat[i, j]) else f"{mat[i, j]:.1f}", ha="center", va="center",
                    fontsize=7)
    ax.set_xticks(range(len(ns)))
    ax.set_xticklabels([str(n) for n in ns])
    ax.set_yticks(range(len(keys)))
    ax.set_yticklabels([f"{s.split('_')[0].upper()} · {c} · {display_label('architecture', a)}" for s, c, a in keys],
                       fontsize=7)
    ax.set_xlabel("Number of agents N")
    ax.grid(False)
    cb = fig.colorbar(im, ax=ax)
    cb.set_label("Mean 5th-percentile ρ (m); < 0 = violation")
    ax.set_title("E5: robustness by scenario, architecture and N")
    save_figure(fig, "e5_robustness_heatmap", out_dir=figs)

    t_pooled = md_summary_table(pooled, ["architecture", "num_agents"],
                                ["min_robustness_m", "p5_robustness_m", "violation_fraction", "violation_episodes",
                                 "mean_recovery_time_s"], src="stl_summary_pooled.csv", labels=LABELS)
    t_all = md_summary_table(summary, ["scenario", "condition", "architecture", "num_agents"],
                             ["min_robustness_m", "p5_robustness_m", "violation_fraction", "max_recovery_time_s"],
                             src="stl_summary.csv", labels=LABELS)
    obs = []
    for arch in ("hierarchical", "centralized", "decentralized_undefended"):
        rs = [r for r in pooled if r["architecture"] == arch]
        if rs:
            obs.append(f"{display_label('architecture', arch)}: violating fraction "
                       + ", ".join(f"N={int(_f(r['num_agents']))}: {fmt(r['violation_fraction_mean'])}" for r in rs)
                       + ".")
    text = f"""# E5 — STL robustness across all evaluated architectures

{provisional_banner()}
Objective (Table 10): evaluate STL robustness — all evaluated architectures, same scenarios as E1–E4. Built from the
saved runs of E1–E4; only the missing nominal centralized / decentralized runs were simulated
({man.get('runs_added', 0)} runs; missing before: {', '.join(man.get('missing_before') or []) or 'none'}).

## Specification
- Safety specification: **G (d_ij(t) ≥ d_min)** for every pair i ≠ j, with d_min = {fmt(d_min)} m
  (config `safety.minimum_separation_meters`).
- Robustness ρ(t) = min over pairs of d_ij(t) − d_min, as implemented by `verification.metrics.robustness_series`
  (read, not changed). **Separation definition currently implemented:** planar distance in (x, y) only, over *all*
  pairs, regardless of altitude layer (agents on different layers are still counted).
- Per run: min ρ, 5th-percentile ρ, fraction of ticks with ρ < 0, violation episodes and recovery times
  (`verification.metrics`: recovery = ρ back above 0 and staying positive for ≥ 1 s). n/a when a run has no episode.

## Results — nominal runs pooled across experiments (one run per architecture, N, seed)
{t_pooled}

## Results — every scenario / condition
{t_all}

## Figures
{chr(10).join(f'- [{f}](../figures/{f}.png)' for f in FIGS)}

## Observations
{chr(10).join(f'- {o}' for o in obs[:5])}
"""
    write_text(d / "README.md", text)
    print(f"[e5] figures -> {figs}; README -> {d / 'README.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
