"""E2 figures and README, generated from saved outputs only (no simulation).

Reads outputs/week6/e2_formation/{runs.csv, summary.csv, occupancy/, frames/};
writes e2_merge_success_vs_N, e2_throughput_vs_N, e2_utilization_vs_N,
e2_utilization_heatmap_N60, e2_formation_snapshot_N60 and README.md.

    python scripts/week6_e2_plot.py [--quick]
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
from experiments.week6 import _corridor_ids, read_rows  # noqa: E402
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
from visualization.plots import apply_style, metric_vs_param, save_figure, utilization_heatmap  # noqa: E402

SUBDIR = "e2_formation"
FIGS = ["e2_merge_success_vs_N", "e2_throughput_vs_N", "e2_utilization_vs_N",
        "e2_utilization_heatmap_N60", "e2_formation_snapshot_N60"]
LABELS = {"num_agents": "N", "merge_attempts": "merge attempts", "merge_success": "successes",
          "merge_failed": "failed", "not_reached": "not reached", "merge_success_rate": "success rate",
          "throughput_per_s": "throughput (agents/s)", "arrivals": "arrivals",
          "ticks_over_capacity": "ticks over capacity", "safety_violation_ticks": "violation ticks"}


def frames_agents(frames_npz: Path, k: int):
    """AgentState list for snapshot index k of a frames/*.npz file."""
    from simulation.schema import AgentState, AgentType

    d = np.load(frames_npz)
    out = []
    for i, aid in enumerate(d["ids"]):
        corr = int(d["corridors"][k, i])
        out.append(AgentState(
            id=int(aid), type=AgentType[str(d["types"][i])],
            position=np.asarray(d["positions"][k, i], dtype=float),
            velocity=np.asarray(d["velocities"][k, i], dtype=float),
            corridor_assignment=None if corr < 0 else corr,
            altitude_layer=int(d["layers"][k, i]),
        ))
    return out, float(d["t"][k])


def busiest_merge_frame(frames_npz: Path, merge_zone: tuple[float, float]) -> int:
    d = np.load(frames_npz)
    x = d["positions"][:, :, 0]
    counts = ((x >= merge_zone[0]) & (x <= merge_zone[1])).sum(axis=1)
    return int(np.argmax(counts))


def _pick_run(runs: list[dict], n: int, seed: int) -> dict | None:
    for r in runs:
        if int(float(r["num_agents"])) == n and int(float(r["seed"])) == seed:
            return r
    return None


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
    focus_seed = 42
    cids = _corridor_ids()
    capacity = float(cfg["corridors"]["capacity"])
    apply_style()

    fig, ax = metric_vs_param(summary, "num_agents", "merge_success_rate", xlabel="Number of agents N",
                              ylabel="Merge success rate (successes / attempts)",
                              title="E2: corridor merge success vs N")
    save_figure(fig, "e2_merge_success_vs_N", out_dir=figs)

    fig, ax = metric_vs_param(summary, "num_agents", "throughput_per_s", xlabel="Number of agents N",
                              ylabel="Throughput (arrivals / s)", title="E2: throughput vs N")
    save_figure(fig, "e2_throughput_vs_N", out_dir=figs)

    long_rows = []  # one row per (N, corridor) so corridors become the hue
    for r in summary:
        for c in cids:
            rec = {"num_agents": r["num_agents"], "corridor": f"corridor {c}"}
            for stat in ("mean", "std", "n", "ci_lo", "ci_hi"):
                rec[f"util_mean_{stat}"] = r.get(f"util_mean_c{c}_{stat}")
            long_rows.append(rec)
    fig, ax = metric_vs_param(long_rows, "num_agents", "util_mean", hue="corridor", xlabel="Number of agents N",
                              ylabel="Mean occupancy / capacity", title="E2: corridor utilisation vs N")
    ax.axhline(1.0, color="black", linestyle="--", linewidth=1.0, label=f"capacity ({fmt(capacity)} agents)")
    ax.legend(loc="best")
    save_figure(fig, "e2_utilization_vs_N", out_dir=figs)

    run = _pick_run(runs, focus_n, focus_seed)
    if run is not None and run.get("occupancy_file"):
        occ = np.load(d / run["occupancy_file"])
        fig, ax = utilization_heatmap(occ["occupancy"].T, [f"corridor {c}" for c in occ["corridor_ids"]],
                                      occ["t"], float(occ["capacity"]),
                                      title=f"E2: corridor utilisation, N={focus_n}, seed {focus_seed}")
        save_figure(fig, "e2_utilization_heatmap_N60", out_dir=figs)
    if run is not None and run.get("frames_file") and (d / run["frames_file"]).is_file():
        from simulation.renderer import render_top_down

        mz = tuple(cfg["corridors"]["merge_zone_x_meters"])
        k = busiest_merge_frame(d / run["frames_file"], mz)
        agents, t = frames_agents(d / run["frames_file"], k)
        fig = render_top_down(agents=agents, title=f"E2 formation snapshot: N={focus_n}, seed {focus_seed}, "
                                                    f"t = {t:.0f} s (busiest merge-zone frame)")
        save_figure(fig, "e2_formation_snapshot_N60", out_dir=figs)

    # ------------------------------------------------------------------ README
    t1 = md_summary_table(summary, ["num_agents"], ["merge_attempts", "merge_success", "merge_failed",
                                                    "not_reached", "merge_success_rate"], labels=LABELS)
    util_cols = [f"util_mean_c{c}" for c in cids] + [f"util_peak_c{c}" for c in cids] + ["ticks_over_capacity"]
    t2 = md_summary_table(summary, ["num_agents"], ["throughput_per_s", "arrivals", "safety_violation_ticks"]
                          + util_cols, labels=LABELS)
    ns = sorted({int(float(r["num_agents"])) for r in summary})
    obs = []
    if ns:
        obs.append("Merge success rate by N: " + ", ".join(
            f"N={n}: {fmt(find_summary(summary, num_agents=n)['merge_success_rate_mean'])}" for n in ns) + ".")
        obs.append("Merge attempts per run by N: " + ", ".join(
            f"N={n}: {fmt(find_summary(summary, num_agents=n)['merge_attempts_mean'])}" for n in ns) + ".")
        obs.append("Throughput (arrivals/s) by N: " + ", ".join(
            f"N={n}: {fmt(find_summary(summary, num_agents=n)['throughput_per_s_mean'])}" for n in ns) + ".")
        hi = find_summary(summary, num_agents=ns[-1])
        obs.append(f"At N={ns[-1]}, peak utilisation per corridor: " + ", ".join(
            f"c{c}: {fmt(hi[f'util_peak_c{c}_mean'])}" for c in cids)
            + f"; ticks over capacity: {fmt(hi['ticks_over_capacity_mean'])}.")
    dur = float(next(iter(man["config_section_resolved"].values()))["duration_s"])
    text = f"""# E2 — Corridor formation, merge success, throughput and utilisation

{provisional_banner()}
Objective (Table 10): evaluate corridor merge success and throughput — hierarchical, three corridors with
varying density. The N = 45–75 rows in `docs/p3_week5_formation.md` are not backed by a CSV and are not used.

## Setup
{chr(10).join(manifest_lines(d))}
- Duration {fmt(dur)} s, no attack, no link failure; {len(cids)} corridors, capacity {fmt(capacity)} agents each;
  merge zone x = {cfg['corridors']['merge_zone_x_meters']} m.

## Method
`local_behavior/formation_metrics.py` as-is: `merge_outcomes` classifies each agent at the end of the merge zone
(success / failed / not reached / no merge needed); merge attempts = success + failed; success rate is n/a when a run
has no attempt. `corridor_utilization` gives mean and peak occupancy / capacity per corridor and the ticks any
corridor exceeds capacity. Throughput = arrivals / duration (n/a with no arrivals). Tables: mean ± 95% CI
half-width over seeds.

## Results — merges
{t1}

## Results — throughput and utilisation (occupancy / capacity)
{t2}

## Figures
{chr(10).join(f'- [{f}](../figures/{f}.png)' for f in FIGS)}

## Weak groups
{chr(10).join(weak_lines(d))}

## Observations
{chr(10).join(f'- {o}' for o in obs[:5])}
"""
    write_text(d / "README.md", text)
    print(f"[e2] figures -> {figs}; README -> {d / 'README.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
