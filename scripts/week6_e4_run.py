"""E4 - three-architecture resilience comparison (Table 10, 13.7, 14.5).

Runs matrices ``e4`` (hierarchical / centralized / decentralized_undefended x
attack off/on x seeds 42-46, N = 60) and ``e4_offset`` (attack on, offsets
from config attack.sweep_offsets_meters, seeds 42-44) into
outputs/week6/e4_resilience. Runs at the default offset are shared.
Identical initial conditions per (seed, N) are checked with
check_identical_conditions and recorded in the manifest.

    python scripts/week6_e4_run.py [--quick] [--workers N] [--fresh] [--only e4|e4_offset]
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.runner import check_identical_conditions  # noqa: E402
from experiments.week6 import expand_matrix  # noqa: E402
from experiments.week6_common import (  # noqa: E402
    aggregate_rows,
    common_args,
    exp_dir,
    rows_for_specs,
    run_matrices,
    update_manifest,
    weak_groups,
    write_weak,
)

MATRICES = ["e4", "e4_offset"]
GROUP_BY = ["architecture", "attack_enabled", "attack_offset_m"]
METRICS = ["throughput_per_s", "arrivals", "safety_violation_ticks", "violation_episodes", "mean_recovery_time_s",
           "max_recovery_time_s", "min_robustness_m", "post_attack_violation_ticks", "reports_dropped",
           "attack_active_ticks", "admm_events"]
WEAK_METRICS = ["throughput_per_s", "safety_violation_ticks", "min_robustness_m"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    common_args(ap)
    ap.add_argument("--only", choices=MATRICES, default=None, help="run only one of the two matrices")
    args = ap.parse_args(argv)
    names = [args.only] if args.only else MATRICES
    run_matrices(names, quick=args.quick, workers=args.workers, resume=not args.fresh, max_runs=args.max_runs)

    # Summaries always cover every e4 / e4_offset spec already present in the folder.
    specs = [s for m in MATRICES for s in expand_matrix(m, quick=args.quick)[0]]
    out_dir = exp_dir("e4_resilience", args.quick)
    rows = rows_for_specs(out_dir / "runs.csv", specs)
    ok, msg = check_identical_conditions([{**r, "seed": int(r["seed"]), "num_agents": int(r["num_agents"])}
                                          for r in rows])
    summary = aggregate_rows(rows, out_dir, GROUP_BY, METRICS)
    weak = weak_groups(summary, GROUP_BY, WEAK_METRICS)
    write_weak(out_dir, weak, WEAK_METRICS)
    update_manifest(out_dir, {
        "matrices_present": MATRICES,
        "rows_in_summary": len(rows),
        "identical_initial_conditions": {"ok": ok, "message": msg,
                                         "checked_with": "experiments.runner.check_identical_conditions"},
        "summary_csv": {"file": "summary.csv", "group_by": GROUP_BY, "metrics": METRICS, "groups": len(summary)},
        "weak_results": {"file": "weak_results.json", "groups": len(weak)},
    })
    print(f"[e4] {len(rows)} runs in summary, identical IC: {ok}, {len(weak)} weak group(s) -> {out_dir}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
