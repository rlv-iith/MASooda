"""E2 - corridor formation, merge success, throughput, utilisation (Table 10, 13.3, 14.3).

Runs matrix ``e2`` (hierarchical, no attack, N = 30/45/60/75, seeds 42-44) into
outputs/week6/e2_formation. Merge and utilisation columns come from
local_behavior/formation_metrics.py (FormationLogger, merge_outcomes,
corridor_utilization) via experiments.week6.run_one; per-tick corridor
occupancy is in occupancy/<spec_hash>.npz. Weak groups are listed, never re-run.

    python scripts/week6_e2_run.py [--quick] [--workers N] [--fresh]
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.week6 import FORMATION_COLUMNS  # noqa: E402
from experiments.week6_common import (  # noqa: E402
    aggregate_rows,
    common_args,
    run_matrices,
    update_manifest,
    weak_groups,
    write_weak,
)

MATRICES = ["e2"]
GROUP_BY = ["num_agents"]
METRICS = FORMATION_COLUMNS + ["throughput_per_s", "arrivals", "safety_violation_ticks", "min_robustness_m"]
WEAK_METRICS = ["merge_success_rate", "throughput_per_s"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    common_args(ap)
    args = ap.parse_args(argv)
    out_dir, specs, rows = run_matrices(MATRICES, quick=args.quick, workers=args.workers, resume=not args.fresh,
                                        max_runs=args.max_runs)
    summary = aggregate_rows(rows, out_dir, GROUP_BY, METRICS)
    weak = weak_groups(summary, GROUP_BY, WEAK_METRICS)
    write_weak(out_dir, weak, WEAK_METRICS)
    update_manifest(out_dir, {
        "summary_csv": {"file": "summary.csv", "group_by": GROUP_BY, "metrics": METRICS, "groups": len(summary)},
        "weak_results": {"file": "weak_results.json", "groups": len(weak)},
    })
    print(f"[e2] {len(rows)} runs, {len(weak)} weak group(s) -> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
