"""E1 - ADMM scaling and convergence (workflow Table 10, 13.2, 14.2).

Runs matrices ``e1`` (N = 30/45/60/75, default iteration limit) and
``e1_iter`` (N = 60, limit 5/10/20/50/100) into outputs/week6/e1_admm_scaling.
The N = 60 / default-limit runs are the same specs in both and run once.

Writes runs.csv, summary.csv (by num_agents x admm_max_iterations),
calls.csv (one row per ADMM solver call), weak_results.json, manifest.json.
Weak groups are listed, never re-run.

    python scripts/week6_e1_run.py [--quick] [--workers N] [--fresh]
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.week6 import write_csv  # noqa: E402
from experiments.week6_common import (  # noqa: E402
    aggregate_rows,
    common_args,
    run_matrices,
    update_manifest,
    weak_groups,
    write_weak,
)

MATRICES = ["e1", "e1_iter"]
GROUP_BY = ["num_agents", "admm_max_iterations"]
METRICS = [
    "admm_solver_calls",
    "admm_iter_mean",
    "admm_iter_p95",
    "admm_iter_max",
    "admm_converged_frac",
    "admm_solve_ms_mean",
    "admm_solve_ms_p95",
    "admm_time_per_tick_ms",
    "admm_max_group_size",
    "admm_events",
    "safety_violation_ticks",
    "min_robustness_m",
    "throughput_per_s",
]
WEAK_METRICS = ["admm_iter_mean", "admm_converged_frac", "admm_time_per_tick_ms"]
CALL_COLUMNS = ["spec_hash", "num_agents", "seed", "admm_max_iterations", "call_index",
                "iterations", "converged", "solve_ms", "group_size"]


def write_calls_csv(out_dir: Path, rows: list[dict]) -> int:
    calls = []
    for r in rows:
        f = out_dir / r["calls_file"] if r.get("calls_file") else None
        if f is None or not f.is_file():
            continue
        d = np.load(f)
        for i in range(len(d["iterations"])):
            calls.append({
                "spec_hash": r["spec_hash"], "num_agents": r["num_agents"], "seed": r["seed"],
                "admm_max_iterations": r["admm_max_iterations"], "call_index": i,
                "iterations": int(d["iterations"][i]), "converged": bool(d["converged"][i]),
                "solve_ms": float(d["solve_ms"][i]), "group_size": int(d["group_size"][i]),
            })
    write_csv(calls, out_dir / "calls.csv", CALL_COLUMNS)
    return len(calls)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    common_args(ap)
    args = ap.parse_args(argv)

    out_dir, specs, rows = run_matrices(MATRICES, quick=args.quick, workers=args.workers, resume=not args.fresh,
                                        max_runs=args.max_runs)
    summary = aggregate_rows(rows, out_dir, GROUP_BY, METRICS)
    n_calls = write_calls_csv(out_dir, rows)
    weak = weak_groups(summary, GROUP_BY, WEAK_METRICS)
    write_weak(out_dir, weak, WEAK_METRICS)
    update_manifest(out_dir, {
        "summary_csv": {"file": "summary.csv", "group_by": GROUP_BY, "metrics": METRICS, "groups": len(summary)},
        "calls_csv": {"file": "calls.csv", "rows": n_calls},
        "weak_results": {"file": "weak_results.json", "groups": len(weak)},
        "command": "python scripts/week6_e1_run.py" + (" --quick" if args.quick else ""),
    })
    print(f"[e1] {len(rows)} runs, {n_calls} solver calls, {len(weak)} weak group(s) -> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
