"""E6 figures and README from saved outputs only (no simulation).

Reads outputs/week6/e6_degradation/{summary.csv, runs.csv, degradation.csv,
telemetry/}; writes e6_violations_normal_vs_failure,
e6_throughput_normal_vs_failure, e6_directive_age_timeline,
e6_degradation_score and README.md.

    python scripts/week6_e6_plot.py [--quick]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
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
    find_summary,
    fmt,
    manifest_lines,
    md_summary_table,
    md_table,
    provisional_banner,
    weak_lines,
    write_text,
)
from visualization.plots import apply_style, event_color, metric_bars, save_figure  # noqa: E402

SUBDIR = "e6_degradation"
FIGS = ["e6_violations_normal_vs_failure", "e6_throughput_normal_vs_failure", "e6_directive_age_timeline",
        "e6_degradation_score"]
LABELS = {"link_failure": "link failure", "safety_violation_ticks": "violation ticks",
          "violation_episodes": "episodes", "throughput_per_s": "throughput (agents/s)",
          "min_robustness_m": "min ρ (m)", "overseer_failures": "overseer failures",
          "overseer_dropped": "requests dropped", "max_directive_staleness_s": "max directive age (s)",
          "num_agents": "N", "graceful_degradation_score": "degradation score",
          "directive_age_max_in_outage_s": "max directive age in outage (s)",
          "max_position_diff_m": "max position diff (m)", "first_divergence_s": "first divergence (s)"}


def _run_module():
    spec = importlib.util.spec_from_file_location("week6_e6_run", Path(__file__).parent / "week6_e6_run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args(argv)
    cfg = get_config()
    d = exp_dir(SUBDIR, args.quick)
    figs = fig_dir(args.quick)
    summary = read_rows(d / "summary.csv")
    runs = read_rows(d / "runs.csv")
    deg = read_rows(d / "degradation.csv")
    man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    lf = cfg["overseer"]["link_failure"]
    start, end = float(lf["down_start_seconds"]), float(lf["down_end_seconds"])
    rm = _run_module()
    apply_style()

    fig, ax = metric_bars(summary, "safety_violation_ticks", "link_failure", runs_rows=runs,
                          title="E6: safety-violation ticks, link up vs link failure")
    save_figure(fig, "e6_violations_normal_vs_failure", out_dir=figs)
    fig, ax = metric_bars(summary, "throughput_per_s", "link_failure", runs_rows=runs,
                          title="E6: throughput, link up vs link failure")
    save_figure(fig, "e6_throughput_normal_vs_failure", out_dir=figs)

    fig, ax = plt.subplots(figsize=(7.0, 4.0), layout="constrained")
    t_max = 0.0
    for r in sorted(runs, key=lambda r: (r["link_failure"], int(float(r["seed"])))):
        if not r.get("telemetry_file"):
            continue
        t, age, _ = rm.read_telemetry(d / r["telemetry_file"])
        failed = r["link_failure"] == "True"
        ax.plot(t, age, "-" if failed else ":", linewidth=1.2, alpha=0.9,
                color="#AA3377" if failed else "#0072B2",
                label=f"{'link failure' if failed else 'link up'}, seed {r['seed']}")
        t_max = max(t_max, float(t[-1]) if len(t) else 0.0)
    ax.axvspan(start, end, color=event_color("link_down"), alpha=0.18, linewidth=0,
               label=f"configured outage {fmt(start)}–{fmt(end)} s")
    ax.set_xlim(0, max(t_max, 1.0))
    ax.set_xlabel("Simulation time (s)")
    ax.set_ylabel("Age of the cached overseer directive (s)")
    ax.set_title("E6: directive age over time (from per-tick telemetry)")
    ax.legend(loc="upper left", fontsize=7, ncol=2)
    save_figure(fig, "e6_directive_age_timeline", out_dir=figs)

    fig, ax = plt.subplots(figsize=(5.0, 4.0), layout="constrained")
    scores = [(int(float(r["seed"])), float(r["graceful_degradation_score"])) for r in deg]
    finite = [s for _, s in scores if np.isfinite(s)]
    if finite:
        ax.bar(0, np.mean(finite), width=0.5, color="#BBBBBB", edgecolor="black", label="mean over seeds")
    for i, (seed, s) in enumerate(scores):
        if np.isfinite(s):
            ax.scatter(0 + (i - 1) * 0.08, s, color="black", zorder=3)
            ax.annotate(f"seed {seed}", (0 + (i - 1) * 0.08, s), textcoords="offset points", xytext=(6, 0),
                        fontsize=7)
        else:
            ax.text(0, 0.05, f"seed {seed}: ∞ (0 normal violations)", ha="center", fontsize=7,
                    transform=ax.get_xaxis_transform())
    ax.axhline(1.0, color="black", linestyle="--", linewidth=1.0, label="1.0 = no change")
    ax.set_xticks([0])
    ax.set_xticklabels([f"N={runs[0]['num_agents']}" if runs else ""])
    ax.set_ylabel("Violations (link failure) / violations (link up)")
    ax.set_title("E6: graceful-degradation score")
    ax.legend(loc="best", fontsize=8)
    save_figure(fig, "e6_degradation_score", out_dir=figs)

    t1 = md_summary_table(summary, ["link_failure"], ["safety_violation_ticks", "violation_episodes",
                                                      "throughput_per_s", "min_robustness_m"], labels=LABELS)
    t2 = md_summary_table(summary, ["link_failure"], ["overseer_failures", "overseer_dropped",
                                                      "max_directive_staleness_s"], labels=LABELS)
    deg_summary = read_rows(d / "degradation_summary.csv")
    t3 = md_summary_table(deg_summary, ["num_agents"], ["graceful_degradation_score", "directive_age_max_in_outage_s",
                                                        "max_position_diff_m", "first_divergence_s"],
                          src="degradation_summary.csv", labels=LABELS)
    per_seed = md_table(["seed", "violations (up)", "violations (failure)", "score", "directive refreshed in outage",
                         "max directive age in outage (s)", "max position diff (m)", "first divergence (s)"],
                        [[r["seed"], fmt(r["violations_normal"]), fmt(r["violations_failure"]),
                          fmt(r["graceful_degradation_score"]), r["directive_refreshed_in_outage"],
                          fmt(r["directive_age_max_in_outage_s"]), fmt(r["max_position_diff_m"]),
                          fmt(r["first_divergence_s"])] for r in deg])

    refreshed = [r["directive_refreshed_in_outage"] for r in deg]
    if refreshed and all(x == "False" for x in refreshed):
        refresh_txt = (f"In every failure run the directive age rose without a reset inside {fmt(start)}–{fmt(end)} s: "
                       "directives **stopped refreshing** during the outage (the cached directive was used).")
    elif any(x == "True" for x in refreshed):
        refresh_txt = ("In at least one failure run the directive age **dropped** inside the outage window, i.e. a "
                       "directive was refreshed although the link was configured down — reported, not changed.")
    else:
        refresh_txt = "The outage window is not covered by these runs (n/a)."
    diffs = [float(r["max_position_diff_m"]) for r in deg if np.isfinite(float(r["max_position_diff_m"]))]
    if not diffs:
        traj_txt = "Trajectory comparison: n/a (no saved frames)."
    elif max(diffs) == 0.0:
        traj_txt = ("Trajectories of the normal and failure runs are **identical** for every seed (max position "
                    "difference 0 m) — the outage had no effect on motion in these runs.")
    else:
        traj_txt = (f"Trajectories **differ** between normal and failure runs: max position difference "
                    f"{fmt(min(diffs))}–{fmt(max(diffs))} m across seeds; first divergence at "
                    + ", ".join(f"{fmt(r['first_divergence_s'])} s" for r in deg) + ".")
    obs = []
    up, down = find_summary(summary, link_failure="False"), find_summary(summary, link_failure="True")
    if up and down:
        obs.append(f"Violation ticks: {fmt(up['safety_violation_ticks_mean'])} with the link up vs "
                   f"{fmt(down['safety_violation_ticks_mean'])} with the link failure (mean over seeds).")
        obs.append(f"Throughput: {fmt(up['throughput_per_s_mean'])} vs {fmt(down['throughput_per_s_mean'])} agents/s.")
        obs.append(f"Overseer requests dropped: {fmt(up['overseer_dropped_mean'])} vs {fmt(down['overseer_dropped_mean'])};"
                   f" max directive age {fmt(up['max_directive_staleness_s_mean'])} vs "
                   f"{fmt(down['max_directive_staleness_s_mean'])} s.")
    obs.append("Degradation score per seed: " + ", ".join(f"seed {r['seed']}: {fmt(r['graceful_degradation_score'])}"
                                                         for r in deg) + ".")
    dur = float(next(iter(man["config_section_resolved"].values()))["duration_s"])
    text = f"""# E6 — Graceful degradation (overseer link failure)

{provisional_banner()}
Objective (Table 10): evaluate graceful degradation — hierarchical, overseer communication link dropped.

## Setup
{chr(10).join(manifest_lines(d))}
- Duration {fmt(dur)} s, no attack. Link-failure runs drop the overseer link from {fmt(start)} s to {fmt(end)} s
  (config `overseer.link_failure`); each seed has a paired link-up run.

## Method
Per-run counters come from the engine (`overseer_failures`, `overseer_dropped`, `max_directive_staleness_s`); the
per-tick age of the cached directive comes from `simulation/telemetry.py` (`telemetry/*.csv`). The graceful
degradation score is `verification.metrics.graceful_degradation_score(violations_failure, violations_normal)`
per seed, used as-is: 1.0 when both runs have 0 violation ticks, ∞ when only the failure run has violations
(∞ is excluded from the mean and counted in n). Trajectory differences use the saved 1 s fleet snapshots.

## Results — link up vs link failure
{t1}

{t2}

## Results — degradation per seed
{per_seed}

{t3}

## Outage behaviour (reported, not changed)
- {refresh_txt}
- {traj_txt}

## Figures
{chr(10).join(f'- [{f}](../figures/{f}.png)' for f in FIGS)}

## Weak groups
{chr(10).join(weak_lines(d))}

## Observations
{chr(10).join(f'- {o}' for o in obs[:5])}
"""
    write_text(d / "README.md", text)
    print(f"[e6] figures -> {figs}; README -> {d / 'README.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
