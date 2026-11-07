"""E6 - graceful degradation under overseer link failure (Table 10, 13.4, 14.4).

Runs matrix ``e6`` (hierarchical, N = 60, seeds 42-44, link_failure false/true
with the window from config overseer.link_failure) into
outputs/week6/e6_degradation.

Per seed (paired normal / failure runs): graceful_degradation_score from
verification.metrics (used as-is), whether the cached directive kept
refreshing during the outage (from the saved telemetry), and the largest
position difference between the two runs (from the saved frames).
Writes runs.csv, summary.csv (runs by link_failure), degradation.csv,
degradation_summary.csv, weak_results.json, manifest.json.

    python scripts/week6_e6_run.py [--quick] [--workers N] [--fresh]
"""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.load_config import get_config  # noqa: E402
from experiments.week6 import write_csv  # noqa: E402
from experiments.week6_common import (  # noqa: E402
    aggregate_rows,
    common_args,
    run_matrices,
    update_manifest,
    weak_groups,
    write_weak,
)

MATRICES = ["e6"]
GROUP_BY = ["link_failure"]
METRICS = ["safety_violation_ticks", "violation_episodes", "throughput_per_s", "arrivals", "min_robustness_m",
           "mean_recovery_time_s", "overseer_calls", "overseer_failures", "overseer_dropped",
           "max_directive_staleness_s", "layer_changes"]
DEG_COLUMNS = ["seed", "num_agents", "violations_normal", "violations_failure", "graceful_degradation_score",
               "throughput_normal", "throughput_failure", "outage_start_s", "outage_end_s",
               "directive_age_max_in_outage_s", "directive_refreshed_in_outage", "max_position_diff_m",
               "first_divergence_s", "normal_spec_hash", "failure_spec_hash"]
DEG_METRICS = ["graceful_degradation_score", "violations_normal", "violations_failure",
               "directive_age_max_in_outage_s", "max_position_diff_m", "first_divergence_s"]
WEAK_METRICS = ["safety_violation_ticks", "throughput_per_s"]


def _f(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


def read_telemetry(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(t, directive_age_s, overseer_link_up as float 1/0/NaN) from a telemetry CSV."""
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    t = np.array([_f(r["t"]) for r in rows])
    age = np.array([_f(r["directive_age_s"]) for r in rows])
    up = np.array([1.0 if r["overseer_link_up"] == "True" else (0.0 if r["overseer_link_up"] == "False" else np.nan)
                   for r in rows])
    return t, age, up


def directive_refresh(t: np.ndarray, age: np.ndarray, start: float, end: float) -> tuple[float, bool | None]:
    """Max directive age inside [start, end) and whether the directive was refreshed there.

    A refresh shows up as the age dropping between consecutive ticks. None if the
    window is not covered by the run.
    """
    m = (t >= start) & (t < end)
    if not m.any():
        return float("nan"), None
    a = age[m]
    return float(np.nanmax(a)), bool(np.any(np.diff(a) < -1e-9))


def position_divergence(f_normal: Path, f_fail: Path, tol: float = 1e-6) -> tuple[float, float]:
    a, b = np.load(f_normal), np.load(f_fail)
    k = min(len(a["t"]), len(b["t"]))
    diff = np.abs(a["positions"][:k].astype(float) - b["positions"][:k].astype(float)).max(axis=(1, 2))
    over = np.where(diff > tol)[0]
    first = float(a["t"][over[0]]) if over.size else float("nan")
    return float(diff.max()) if diff.size else float("nan"), first


def degradation_rows(out_dir: Path, rows: list[dict]) -> list[dict]:
    from verification.metrics import graceful_degradation_score

    lf = get_config()["overseer"]["link_failure"]
    start, end = float(lf["down_start_seconds"]), float(lf["down_end_seconds"])
    by = {(int(float(r["seed"])), int(float(r["num_agents"])), r["link_failure"] == "True"): r for r in rows}
    out = []
    for (seed, n, failed), fail in sorted(by.items()):
        if not failed or (seed, n, False) not in by:
            continue
        norm = by[(seed, n, False)]
        vn, vf = int(_f(norm["safety_violation_ticks"])), int(_f(fail["safety_violation_ticks"]))
        t, age, _ = read_telemetry(out_dir / fail["telemetry_file"])
        age_max, refreshed = directive_refresh(t, age, start, end)
        if fail.get("frames_file") and norm.get("frames_file"):
            pdiff, first = position_divergence(out_dir / norm["frames_file"], out_dir / fail["frames_file"])
        else:
            pdiff, first = float("nan"), float("nan")
        out.append({
            "seed": seed, "num_agents": n, "violations_normal": vn, "violations_failure": vf,
            "graceful_degradation_score": graceful_degradation_score(vf, vn),
            "throughput_normal": _f(norm["throughput_per_s"]), "throughput_failure": _f(fail["throughput_per_s"]),
            "outage_start_s": start, "outage_end_s": end,
            "directive_age_max_in_outage_s": age_max,
            "directive_refreshed_in_outage": "n/a" if refreshed is None else refreshed,
            "max_position_diff_m": pdiff, "first_divergence_s": first,
            "normal_spec_hash": norm["spec_hash"], "failure_spec_hash": fail["spec_hash"],
        })
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    common_args(ap)
    args = ap.parse_args(argv)
    out_dir, specs, rows = run_matrices(MATRICES, quick=args.quick, workers=args.workers, resume=not args.fresh,
                                        max_runs=args.max_runs)
    summary = aggregate_rows(rows, out_dir, GROUP_BY, METRICS)
    deg = degradation_rows(out_dir, rows)
    write_csv(deg, out_dir / "degradation.csv", DEG_COLUMNS)
    aggregate_rows(deg, out_dir, ["num_agents"], DEG_METRICS, name="degradation_summary.csv")
    weak = weak_groups(summary, GROUP_BY, WEAK_METRICS)
    write_weak(out_dir, weak, WEAK_METRICS)
    n_inf = sum(1 for r in deg if not math.isfinite(_f(r["graceful_degradation_score"])))
    update_manifest(out_dir, {
        "summary_csv": {"file": "summary.csv", "group_by": GROUP_BY, "metrics": METRICS},
        "degradation_csv": {"file": "degradation.csv", "rows": len(deg), "infinite_scores": n_inf},
        "degradation_summary_csv": {"file": "degradation_summary.csv", "source": "degradation.csv"},
        "weak_results": {"file": "weak_results.json", "groups": len(weak)},
    })
    print(f"[e6] {len(rows)} runs, {len(deg)} pairs, {len(weak)} weak group(s) -> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
