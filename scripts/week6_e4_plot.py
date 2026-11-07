"""E4 figures, paired attack effect and README from saved outputs only.

Reads outputs/week6/e4_resilience/{runs.csv, summary.csv, series/}; computes
the paired attack effect (attack on minus attack off, same architecture and
seed, default offset) into attack_effect.csv / attack_effect_summary.csv;
writes e4_main_comparison, e4_attack_effect, e4_robustness_timeseries,
e4_offset_sensitivity and README.md.

    python scripts/week6_e4_plot.py [--quick]
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from config.load_config import get_config  # noqa: E402
from experiments.week6 import read_rows, write_csv  # noqa: E402
from experiments.week6_common import (  # noqa: E402
    aggregate_rows,
    exp_dir,
    fig_dir,
    find_summary,
    fmt,
    manifest_lines,
    md_summary_table,
    provisional_banner,
    update_manifest,
    weak_lines,
    write_text,
)
from visualization.plots import (  # noqa: E402
    apply_style,
    metric_bars,
    metric_vs_param,
    robustness_timeseries,
    save_figure,
)

SUBDIR = "e4_resilience"
FIGS = ["e4_main_comparison", "e4_attack_effect", "e4_robustness_timeseries", "e4_offset_sensitivity"]
MAIN = ["throughput_per_s", "safety_violation_ticks", "mean_recovery_time_s", "min_robustness_m"]
EFFECT_METRICS = MAIN + ["post_attack_violation_ticks_on", "violation_episodes"]
ARCHS = ["hierarchical", "centralized", "decentralized_undefended"]
LABELS = {"architecture": "architecture", "attack_enabled": "attack", "attack_offset_m": "offset (m)",
          "throughput_per_s": "throughput (agents/s)", "safety_violation_ticks": "violation ticks",
          "violation_episodes": "episodes", "mean_recovery_time_s": "mean recovery (s)",
          "min_robustness_m": "min ρ (m)", "post_attack_violation_ticks": "post-attack viol. ticks",
          "post_attack_violation_ticks_on": "post-attack viol. ticks (on)", "reports_dropped": "reports dropped"}


def _f(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


def paired_effects(runs: Sequence[Mapping], metrics: Sequence[str], default_offset: float) -> list[dict]:
    """attack-on minus attack-off per (architecture, num_agents, seed).

    Only attack-on runs at the default offset are paired. A difference is NaN
    when either side is NaN (e.g. no recovery episode). ``post_attack_violation_ticks_on``
    is the attack-on value itself (it is undefined without an attack).
    """
    off, on = {}, {}
    for r in runs:
        key = (r["architecture"], int(float(r["num_agents"])), int(float(r["seed"])))
        if str(r["attack_enabled"]) == "True":
            if math.isclose(_f(r["attack_offset_m"]), default_offset):
                on[key] = r
        else:
            off[key] = r
    out = []
    for key in sorted(set(on) & set(off)):
        a, b = on[key], off[key]
        rec = {"architecture": key[0], "num_agents": key[1], "seed": key[2]}
        for m in metrics:
            if m == "post_attack_violation_ticks_on":
                rec[m] = _f(a.get("post_attack_violation_ticks"))
            else:
                rec[m] = _f(a.get(m)) - _f(b.get(m))
        out.append(rec)
    return out


def effect_verdict(effect_summary_row: Mapping, metrics: Sequence[str]) -> str:
    """'measurable' if any metric's 95% CI of the paired difference excludes 0."""
    any_values = False
    for m in metrics:
        lo, hi, mean = _f(effect_summary_row.get(f"{m}_ci_lo")), _f(effect_summary_row.get(f"{m}_ci_hi")), \
            _f(effect_summary_row.get(f"{m}_mean"))
        if math.isfinite(mean):
            any_values = True
        if math.isfinite(lo) and math.isfinite(hi) and (lo > 0 or hi < 0):
            return "measurable"
    return "none" if any_values else "n/a"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args(argv)
    cfg = get_config()
    d = exp_dir(SUBDIR, args.quick)
    figs = fig_dir(args.quick)
    summary = read_rows(d / "summary.csv")
    man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    current = man.get("config_hash")
    runs = [r for r in read_rows(d / "runs.csv") if r.get("base_config_hash") == current]
    default_offset = float(cfg["attack"]["offset_magnitude_meters"])
    d_min = float(cfg["safety"]["minimum_separation_meters"])
    apply_style()

    # ---------------------------------------------------------------- paired effect
    effects = paired_effects(runs, EFFECT_METRICS, default_offset)
    write_csv(effects, d / "attack_effect.csv", ["architecture", "num_agents", "seed"] + EFFECT_METRICS)
    eff_summary = aggregate_rows(effects, d, ["architecture"], EFFECT_METRICS, name="attack_effect_summary.csv")
    update_manifest(d, {"attack_effect_csv": {"file": "attack_effect.csv", "pairs": len(effects),
                                              "definition": "attack on (default offset) minus attack off, same seed"},
                        "attack_effect_summary_csv": {"file": "attack_effect_summary.csv", "group_by": ["architecture"]}})

    # main comparison: attack off vs on (default offset)
    main_rows = [r for r in summary if r["attack_enabled"] == "False"
                 or math.isclose(_f(r["attack_offset_m"]), default_offset)]
    main_runs = [r for r in runs if r["attack_enabled"] == "False"
                 or math.isclose(_f(r["attack_offset_m"]), default_offset)]
    fig, axes = plt.subplots(2, 2, figsize=(11.0, 8.0), layout="constrained")
    for ax, m in zip(axes.flat, MAIN):
        metric_bars(main_rows, m, "architecture", hue="attack_enabled", runs_rows=main_runs, ax=ax,
                    title=LABELS[m].split(" (")[0].capitalize())
    fig.suptitle(f"E4: attack off vs on (offset {fmt(default_offset)} m), N=60")
    save_figure(fig, "e4_main_comparison", out_dir=figs)

    fig, axes = plt.subplots(2, 2, figsize=(11.0, 8.0), layout="constrained")
    for ax, m in zip(axes.flat, MAIN):
        metric_bars(eff_summary, m, "architecture", runs_rows=effects, ax=ax,
                    title=f"Δ {LABELS[m].split(' (')[0]}", ylabel=f"attack on − off: {LABELS[m]}")
    fig.suptitle("E4: paired attack effect (same seed), mean ± 95% CI")
    save_figure(fig, "e4_attack_effect", out_dir=figs)

    fig, axes = plt.subplots(1, 2, figsize=(12.0, 4.2), layout="constrained", sharey=True)
    attack_start = None
    for ax, on in zip(axes, (False, True)):
        series = {}
        for arch in ARCHS:
            sel = [r for r in main_runs if r["architecture"] == arch and r["attack_enabled"] == str(on)
                   and r.get("series_file")]
            if sel:
                series[arch] = [dict(np.load(d / r["series_file"])) for r in sel]
                if on:
                    attack_start = _f(sel[0]["attack_start_s"])
        events = [{"kind": "attack", "start": attack_start, "end": None}] if on and attack_start is not None else []
        robustness_timeseries(series, d_min, events=events, ax=ax,
                              title=f"Attack {'on' if on else 'off'}")
    fig.suptitle("E4: STL robustness over time, mean per architecture across seeds")
    save_figure(fig, "e4_robustness_timeseries", out_dir=figs)

    on_rows = [r for r in summary if r["attack_enabled"] == "True"]
    fig, axes = plt.subplots(1, 2, figsize=(11.0, 4.2), layout="constrained")
    metric_vs_param(on_rows, "attack_offset_m", "safety_violation_ticks", hue="architecture", ax=axes[0],
                    title="Violation ticks vs offset")
    metric_vs_param(on_rows, "attack_offset_m", "min_robustness_m", hue="architecture", ax=axes[1],
                    title="Min robustness vs offset")
    axes[1].axhline(0.0, color="black", linestyle="--", linewidth=0.8)
    fig.suptitle("E4: sensitivity to the falsified-position offset (attack on)")
    save_figure(fig, "e4_offset_sensitivity", out_dir=figs)

    # ---------------------------------------------------------------- README
    t_main = md_summary_table(main_rows, ["architecture", "attack_enabled"],
                              MAIN + ["post_attack_violation_ticks", "reports_dropped"], labels=LABELS)
    # the filtered table above is not regenerable from a filter on summary.csv; mark default-offset rows explicitly
    t_off = md_summary_table(summary, ["architecture", "attack_enabled"], MAIN, where={"attack_enabled": "False"},
                             labels=LABELS)
    t_on = md_summary_table(summary, ["architecture", "attack_offset_m"], MAIN + ["post_attack_violation_ticks"],
                            where={"attack_enabled": "True"}, labels=LABELS)
    t_eff = md_summary_table(eff_summary, ["architecture"], MAIN + ["post_attack_violation_ticks_on"],
                             src="attack_effect_summary.csv", labels=LABELS)
    del t_main
    verdicts = []
    for arch in ARCHS:
        row = find_summary(eff_summary, architecture=arch)
        if row is None:
            verdicts.append(f"- {arch}: n/a (no paired runs).")
            continue
        v = effect_verdict(row, MAIN)
        if v == "measurable":
            verdicts.append(f"- {arch}: measurable effect — the 95% CI of the paired difference excludes 0 for at "
                            "least one of throughput, violation ticks, recovery time, min robustness.")
        elif v == "none":
            verdicts.append(f"- {arch}: **no measurable effect of the attack** — for all four metrics the 95% CI of "
                            "the paired difference includes 0 (or the difference is exactly 0).")
        else:
            verdicts.append(f"- {arch}: n/a (metric values missing).")
    obs = []
    for arch in ARCHS:
        off = find_summary(summary, architecture=arch, attack_enabled="False")
        on = next((r for r in summary if r["architecture"] == arch and r["attack_enabled"] == "True"
                   and math.isclose(_f(r["attack_offset_m"]), default_offset)), None)
        if off and on:
            obs.append(f"{arch}: violation ticks {fmt(off['safety_violation_ticks_mean'])} (off) vs "
                       f"{fmt(on['safety_violation_ticks_mean'])} (on); min ρ {fmt(off['min_robustness_m_mean'])} vs "
                       f"{fmt(on['min_robustness_m_mean'])} m; throughput {fmt(off['throughput_per_s_mean'])} vs "
                       f"{fmt(on['throughput_per_s_mean'])} agents/s.")
    dur = float(next(iter(man["config_section_resolved"].values()))["duration_s"]) \
        if man.get("config_section_resolved") else float(cfg["simulation"]["duration_seconds"])
    ic = man.get("identical_initial_conditions", {})
    text = f"""# E4 — Resilience under attack: three architectures

{provisional_banner()}
Objective (Table 10): compare resilience under attack — hierarchical / centralized / decentralized-undefended,
one agent falsifies its reported position from t = {fmt(_f(cfg['attack']['start_time_seconds']))} s.

## Setup
{chr(10).join(manifest_lines(d))}
- Duration {fmt(dur)} s, N = 60. Attack: config `attack` (mode {cfg['attack']['mode']}, default offset
  {fmt(default_offset)} m, start {fmt(_f(cfg['attack']['start_time_seconds']))} s); offset sweep
  {cfg['attack']['sweep_offsets_meters']} m on seeds 42–44.
- Identical initial conditions per (seed, N), checked with `check_identical_conditions`:
  {'yes' if ic.get('ok') else 'NO'} — {ic.get('message', 'n/a')}

## Method
Per run: throughput, safety-violation ticks (ρ < 0), recovery times (ρ back above 0 for ≥ 1 s), min robustness
(`verification.metrics`), reports dropped by the defence, and post-attack violation ticks (ticks at or after the
attack start with ρ < 0, from the saved series). The paired attack effect is attack-on (default offset) minus
attack-off for the same architecture and seed (`attack_effect.csv`). Recovery time is n/a for runs without a
violation episode. Tables: mean ± 95% CI half-width over seeds.

## Results — attack off
{t_off}

## Results — attack on, by offset
{t_on}

## Paired attack effect (on − off, same seed)
{t_eff}

### Does the attack have a measurable effect?
{chr(10).join(verdicts)}

## Figures
{chr(10).join(f'- [{f}](../figures/{f}.png)' for f in FIGS)}

## Weak groups
{chr(10).join(weak_lines(d))}

## Observations
{chr(10).join(f'- {o}' for o in obs[:5])}
"""
    write_text(d / "README.md", text)
    print(f"[e4] figures -> {figs}; README -> {d / 'README.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
