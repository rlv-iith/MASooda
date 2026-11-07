"""E3 figures and README from saved outputs only (no simulation).

Reads outputs/week6/e3_priority/{summary.csv, pairs.csv, runs.csv, frames/};
writes e3_compliance_vs_N, e3_emergency_delay_vs_N, e3_imposed_delay_vs_N,
e3_emergency_track_N60 and README.md.

    python scripts/week6_e3_plot.py [--quick]
"""

from __future__ import annotations

import argparse
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
    provisional_banner,
    weak_lines,
    write_text,
)
from visualization.plots import apply_style, metric_vs_param, save_figure, type_color  # noqa: E402

SUBDIR = "e3_priority"
FIGS = ["e3_compliance_vs_N", "e3_emergency_delay_vs_N", "e3_imposed_delay_vs_N", "e3_emergency_track_N60"]
LABELS = {"num_agents": "N", "priority_compliance_rate": "compliance rate", "emergency_delay_s": "emergency delay (s)",
          "time_saved_vs_control_s": "time saved vs control (s)", "lower_priority_delay_s": "imposed delay (s)",
          "emergency_travel_time_s": "emergency travel (s)", "control_travel_time_s": "control travel (s)",
          "emergency_control": "control run", "throughput_per_s": "throughput (agents/s)",
          "safety_violation_ticks": "violation ticks", "min_robustness_m": "min ρ (m)", "admm_events": "ADMM events"}


def _row(runs, n, seed, control):
    for r in runs:
        if (int(float(r["num_agents"])) == n and int(float(r["seed"])) == seed
                and r["emergency_control"] == str(control)):
            return r
    return None


def emergency_track(d: Path, row: dict) -> tuple[np.ndarray, np.ndarray]:
    f = np.load(d / row["frames_file"])
    idx = int(np.where(f["ids"] == int(row["emergency_id"]))[0][0])
    return f["t"], f["positions"][:, idx, :]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args(argv)
    cfg = get_config()
    d = exp_dir(SUBDIR, args.quick)
    figs = fig_dir(args.quick)
    summary = read_rows(d / "summary.csv")
    runs = read_rows(d / "runs.csv")
    man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    focus_n = 60 if not args.quick else int(cfg["experiments"]["week6"]["quick"]["agent_counts"][0])
    apply_style()

    for name, metric, ylabel, title in [
        ("e3_compliance_vs_N", "priority_compliance_rate", "Priority-compliance rate",
         "E3: emergency corridor compliance vs N"),
        ("e3_emergency_delay_vs_N", "emergency_delay_s", "Emergency delay vs nominal (s)",
         "E3: emergency-agent delay vs N"),
        ("e3_imposed_delay_vs_N", "lower_priority_delay_s", "Mean delay imposed on others (s)",
         "E3: delay imposed on lower-priority agents vs N"),
    ]:
        fig, ax = metric_vs_param(summary, "num_agents", metric, xlabel="Number of agents N", ylabel=ylabel, title=title)
        if metric != "priority_compliance_rate":
            ax.axhline(0.0, color="black", linewidth=0.8)
        save_figure(fig, name, out_dir=figs)

    em, ctrl = _row(runs, focus_n, 42, False), _row(runs, focus_n, 42, True)
    if em and ctrl and em.get("frames_file") and ctrl.get("frames_file"):
        fig, axes = plt.subplots(1, 2, figsize=(10.0, 4.0), layout="constrained")
        v = float(cfg["local_behavior"]["v_cruise"])
        exit_x = float(cfg["corridors"]["exit_zone_x_meters"][0])
        for row, label, style in [(em, "emergency (priority 0)", "-"), (ctrl, "control (DELIVERY)", "--")]:
            t, p = emergency_track(d, row)
            color = type_color("EMERGENCY") if style == "-" else type_color("DELIVERY")
            axes[0].plot(t, p[:, 0], style, color=color, label=label)
            axes[1].plot(p[:, 0], p[:, 1], style, color=color, label=label)
        t0, p0 = emergency_track(d, em)
        axes[0].plot(t0, p0[0, 0] + v * t0, ":", color="black", label=f"nominal (v_cruise = {fmt(v)} m/s)")
        axes[0].axhline(exit_x, color="#7F7F7F", linewidth=0.8)
        axes[0].set_ylim(top=exit_x * 1.05)
        axes[0].set_xlabel("Simulation time (s)")
        axes[0].set_ylabel("Along-corridor position x (m)")
        axes[0].set_title("Progress of the chosen agent")
        mz = cfg["corridors"]["merge_zone_x_meters"]
        axes[1].axvspan(mz[0], mz[1], color="#DDDDDD", alpha=0.6, label="merge zone")
        axes[1].set_xlabel("x (m)")
        axes[1].set_ylabel("y (m)")
        axes[1].set_title("Path (top-down)")
        for ax in axes:
            ax.legend(loc="best", fontsize=8)
        fig.suptitle(f"E3: emergency agent {em['emergency_id']} vs its control run, N={focus_n}, seed 42")
        save_figure(fig, "e3_emergency_track_N60", out_dir=figs)

    t1 = md_summary_table(summary, ["num_agents"], ["priority_compliance_rate", "emergency_delay_s",
                                                    "time_saved_vs_control_s", "lower_priority_delay_s"], labels=LABELS)
    t2 = md_summary_table(summary, ["num_agents"], ["emergency_travel_time_s", "control_travel_time_s"], labels=LABELS)
    runs_summary = read_rows(d / "runs_summary.csv")
    t3 = md_summary_table(runs_summary, ["num_agents", "emergency_control"],
                          ["throughput_per_s", "safety_violation_ticks", "min_robustness_m", "admm_events"],
                          src="runs_summary.csv", labels=LABELS)
    ns = sorted({int(float(r["num_agents"])) for r in summary})
    obs = []
    if ns:
        for metric, what in [("priority_compliance_rate", "Compliance rate"),
                             ("emergency_delay_s", "Emergency delay vs nominal (s)"),
                             ("time_saved_vs_control_s", "Time saved vs control (s)"),
                             ("lower_priority_delay_s", "Delay imposed on others (s)")]:
            obs.append(f"{what} by N: " + ", ".join(
                f"N={n}: {fmt(find_summary(summary, num_agents=n)[f'{metric}_mean'])}" for n in ns) + ".")
    dur = float(next(iter(man["config_section_resolved"].values()))["duration_s"])
    text = f"""# E3 — Emergency priority compliance

{provisional_banner()}
Objective (Table 10): evaluate priority compliance — hierarchical, an emergency agent injected into traffic.

## Setup
{chr(10).join(manifest_lines(d))}
- Duration {fmt(dur)} s, no attack, no link failure. Each (N, seed) has an emergency run and a paired control run
  (`emergency_control = True`) with the same fleet in which the same agent stays an ordinary DELIVERY agent.

## Method
`simulation/priority_metrics.py` is used as-is (its compliance definition is owned by P4 and may change):
`inject_emergency` makes the rear-most agent EMERGENCY (priority 0), `baseline_copy` builds the control fleet,
`PriorityLogger` records compliance and arrival times, and `priority_summary` gives emergency delay (arrival time
− nominal free-flow time), time saved vs the control run, and the mean delay imposed on the other agents. A value
is n/a when the agent did not reach the exit in the run. Tables: mean ± 95% CI half-width over seeds.

## Results — priority (pairs.csv → summary.csv)
{t1}

## Results — travel times
{t2}

## Results — fleet metrics, emergency vs control runs
{t3}

## Figures
{chr(10).join(f'- [{f}](../figures/{f}.png)' for f in FIGS)}

## Weak groups
{chr(10).join(weak_lines(d))}

## Observations
{chr(10).join(f'- {o}' for o in obs[:5])}
"""
    write_text(d / "README.md", text)
    print(f"[e3] figures -> {figs}; README -> {d / 'README.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
