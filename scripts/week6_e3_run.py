"""E3 - emergency priority compliance (workflow Table 10, 13.4, 14.4).

Runs matrix ``e3`` into outputs/week6/e3_priority: for each (N, seed) one run
with an emergency agent injected (simulation.priority_metrics.inject_emergency)
and its paired control run (same fleet, that agent kept as an ordinary
DELIVERY agent via baseline_copy).

Per pair, simulation.priority_metrics.priority_summary (used as-is) gives the
emergency delay vs nominal, the time saved vs the control run and the mean
delay imposed on lower-priority agents. Writes runs.csv, pairs.csv,
summary.csv (pairs by num_agents), weak_results.json, manifest.json.

    python scripts/week6_e3_run.py [--quick] [--workers N] [--fresh]
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from types import SimpleNamespace

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

MATRICES = ["e3"]
GROUP_BY = ["num_agents"]
PAIR_COLUMNS = [
    "num_agents", "seed", "emergency_id", "priority_compliance_rate", "emergency_delay_s",
    "time_saved_vs_control_s", "lower_priority_delay_s", "emergency_travel_time_s",
    "control_travel_time_s", "emergency_nominal_time_s", "emergency_spec_hash", "control_spec_hash",
]
METRICS = ["priority_compliance_rate", "emergency_delay_s", "time_saved_vs_control_s", "lower_priority_delay_s",
           "emergency_travel_time_s", "control_travel_time_s"]
WEAK_METRICS = ["priority_compliance_rate", "emergency_delay_s", "lower_priority_delay_s"]


def _f(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


def _arrivals(out_dir: Path, row: dict) -> dict[int, float]:
    p = out_dir / row["arrivals_file"]
    return {int(k): float(v) for k, v in json.loads(p.read_text(encoding="utf-8")).items()}


def pair_rows(out_dir: Path, rows: list[dict]) -> list[dict]:
    """Pair emergency and control runs per (N, seed) and apply priority_summary."""
    from simulation.priority_metrics import inject_emergency, priority_summary
    from simulation.scenario import make_initial_agents

    cfg = get_config()
    by_key: dict[tuple, dict] = {}
    for r in rows:
        key = (int(float(r["num_agents"])), int(float(r["seed"])), r["emergency_control"] == "True")
        by_key[key] = r
    out = []
    for (n, seed, is_ctrl), em in sorted(by_key.items()):
        if is_ctrl:
            continue
        ctrl = by_key.get((n, seed, True))
        if ctrl is None:
            continue
        agents, eid = inject_emergency(make_initial_agents(n, seed=seed))  # deterministic, no simulation
        assert str(eid) == str(em["emergency_id"]) == str(ctrl["emergency_id"]), "pair uses different agents"
        log_em = SimpleNamespace(arrival_times=_arrivals(out_dir, em),
                                 compliance_rate=_f(em["priority_compliance_rate"]))
        log_ctrl = SimpleNamespace(arrival_times=_arrivals(out_dir, ctrl),
                                   compliance_rate=_f(ctrl["priority_compliance_rate"]))
        s = priority_summary(log_em, log_ctrl, agents, eid, cfg)
        out.append({
            "num_agents": n, "seed": seed, "emergency_id": eid,
            "priority_compliance_rate": s["priority_compliance_rate"],
            "emergency_delay_s": s["emergency_delay_s"],
            "time_saved_vs_control_s": s["emergency_time_saved_s"],
            "lower_priority_delay_s": s["lower_priority_delay_imposed_s"],
            "emergency_travel_time_s": s["emergency_travel_time"],
            "control_travel_time_s": s["baseline_same_agent_travel_time"],
            "emergency_nominal_time_s": s["emergency_nominal_time"],
            "emergency_spec_hash": em["spec_hash"], "control_spec_hash": ctrl["spec_hash"],
        })
    for p in out:  # never a measured 0 for something that did not happen
        for k, v in list(p.items()):
            if isinstance(v, float) and not math.isfinite(v):
                p[k] = float("nan")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    common_args(ap)
    args = ap.parse_args(argv)
    out_dir, specs, rows = run_matrices(MATRICES, quick=args.quick, workers=args.workers, resume=not args.fresh,
                                        max_runs=args.max_runs)
    pairs = pair_rows(out_dir, rows)
    write_csv(pairs, out_dir / "pairs.csv", PAIR_COLUMNS)
    summary = aggregate_rows(pairs, out_dir, GROUP_BY, METRICS)
    aggregate_rows(rows, out_dir, ["num_agents", "emergency_control"],
                   ["throughput_per_s", "safety_violation_ticks", "min_robustness_m", "admm_events"],
                   name="runs_summary.csv")
    weak = weak_groups(summary, GROUP_BY, WEAK_METRICS)
    write_weak(out_dir, weak, WEAK_METRICS)
    update_manifest(out_dir, {
        "pairs_csv": {"file": "pairs.csv", "rows": len(pairs), "source": "runs.csv paired by (N, seed)"},
        "summary_csv": {"file": "summary.csv", "source": "pairs.csv", "group_by": GROUP_BY, "metrics": METRICS},
        "runs_summary_csv": {"file": "runs_summary.csv", "group_by": ["num_agents", "emergency_control"]},
        "weak_results": {"file": "weak_results.json", "groups": len(weak)},
    })
    print(f"[e3] {len(rows)} runs, {len(pairs)} pairs, {len(weak)} weak group(s) -> {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
