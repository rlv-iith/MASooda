"""E5 - STL robustness across all evaluated architectures (Table 10), built from saved runs.

1. Reads runs.csv + series/ of e1_admm_scaling, e2_formation, e3_priority,
   e4_resilience (current-config rows only) and e5_stl (extra runs).
2. Lists the (architecture, N) nominal combinations missing for centralized
   and decentralized_undefended at N in experiments.week6.matrices.e5.agent_counts.
   Without --run-missing it stops there (with a runtime estimate).
3. --run-missing runs only those specs into outputs/week6/e5_stl.
4. Writes e5_stl/stl_runs.csv (one row per run) and e5_stl/stl_summary.csv:
   per (scenario, architecture, N) min robustness, 5th-percentile robustness,
   fraction of ticks violating, violation episodes, mean / max recovery time,
   with 95% CI across seeds. Robustness values come from the saved series
   (verification.metrics.robustness_series) and verification.metrics columns.

    python scripts/week6_e5_build.py [--quick] [--run-missing] [--workers N]
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from typing import Mapping, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.load_config import get_config  # noqa: E402
from experiments.week6 import config_hash, expand_matrix, read_rows, run_matrix, write_csv  # noqa: E402
from experiments.week6_common import aggregate_rows, exp_dir, update_manifest, write_manifest  # noqa: E402

SOURCES = ["e1_admm_scaling", "e2_formation", "e3_priority", "e4_resilience", "e5_stl"]
TARGET_ARCHS = ["centralized", "decentralized_undefended"]
STL_COLUMNS = ["scenario", "condition", "architecture", "num_agents", "seed", "source", "spec_hash",
               "min_robustness_m", "p5_robustness_m", "violation_fraction", "violation_episodes",
               "mean_recovery_time_s", "max_recovery_time_s", "series_file"]
STL_METRICS = ["min_robustness_m", "p5_robustness_m", "violation_fraction", "violation_episodes",
               "mean_recovery_time_s", "max_recovery_time_s"]
# CPU seconds per 180 s, N = 60 run measured on the dev laptop (i5-12500H) after the config-path fix
EST_CPU_S = {"centralized": 8.0, "decentralized_undefended": 30.0, "hierarchical": 30.0}


def _f(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


def condition(row: Mapping) -> str:
    """Experimental condition of a run, e.g. 'nominal', 'attack 25 m', 'link failure'."""
    cfg = get_config()
    parts = []
    if str(row.get("attack_enabled")) == "True":
        parts.append(f"attack {_f(row.get('attack_offset_m')):g} m")
    if str(row.get("link_failure")) == "True":
        parts.append("link failure")
    if str(row.get("emergency")) == "True":
        parts.append("emergency control" if str(row.get("emergency_control")) == "True" else "emergency")
    it = _f(row.get("admm_max_iterations"))
    if math.isfinite(it) and int(it) != int(cfg["admm"]["maximum_iterations"]):
        parts.append(f"ADMM limit {int(it)}")
    return ", ".join(parts) if parts else "nominal"


def series_stats(t: np.ndarray, rho: np.ndarray) -> dict[str, float]:
    rho = np.asarray(rho, dtype=float)
    fin = rho[np.isfinite(rho)]
    if fin.size == 0:
        return {"min_robustness_m": float("nan"), "p5_robustness_m": float("nan"), "violation_fraction": float("nan")}
    return {
        "min_robustness_m": float(fin.min()),
        "p5_robustness_m": float(np.percentile(fin, 5.0)),
        "violation_fraction": float(np.mean(rho < 0.0)),
    }


def collect(root: Path) -> list[dict]:
    """One STL row per saved run (current config only) across SOURCES."""
    current = config_hash()
    out = []
    for src in SOURCES:
        d = root / src
        for r in read_rows(d / "runs.csv"):
            if r.get("base_config_hash") != current or not r.get("series_file"):
                continue
            s = np.load(d / r["series_file"])
            st = series_stats(s["t"], s["robustness"])
            out.append({
                "scenario": src, "condition": condition(r), "architecture": r["architecture"],
                "num_agents": int(_f(r["num_agents"])), "seed": int(_f(r["seed"])), "source": src,
                "spec_hash": r["spec_hash"], **st,
                "violation_episodes": _f(r["violation_episodes"]),
                "mean_recovery_time_s": _f(r["mean_recovery_time_s"]),
                "max_recovery_time_s": _f(r["max_recovery_time_s"]),
                "series_file": f"../{src}/{r['series_file']}",
            })
    return out


def missing_combinations(stl_rows: Sequence[Mapping], agent_counts: Sequence[int],
                         archs: Sequence[str] = TARGET_ARCHS) -> list[tuple[str, int]]:
    have = {(r["architecture"], int(r["num_agents"])) for r in stl_rows if r["condition"] == "nominal"}
    return [(a, int(n)) for a in archs for n in agent_counts if (a, int(n)) not in have]


def pooled_nominal(stl_rows: Sequence[Mapping]) -> list[dict]:
    """Nominal runs pooled across experiments, one per (architecture, N, seed)."""
    seen, out = set(), []
    for r in sorted(stl_rows, key=lambda r: (r["architecture"], r["num_agents"], r["seed"], r["source"])):
        if r["condition"] != "nominal":
            continue
        key = (r["architecture"], r["num_agents"], r["seed"])
        if key not in seen:
            seen.add(key)
            out.append({**r, "scenario": "nominal (pooled)"})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--run-missing", action="store_true", help="run the missing nominal combinations")
    ap.add_argument("--workers", type=int, default=None)
    args = ap.parse_args(argv)
    root = exp_dir("", args.quick)
    out_dir = root / "e5_stl"
    out_dir.mkdir(parents=True, exist_ok=True)
    specs_all, used, raw = expand_matrix("e5", quick=args.quick)
    agent_counts = sorted({s.n_agents for s in specs_all})

    rows = collect(root)
    missing = missing_combinations(rows, agent_counts)
    miss_specs = [s for s in specs_all if (s.architecture, s.n_agents) in set(missing)]
    dur = float(used["duration_s"])
    cpu = sum(EST_CPU_S[s.architecture] * (dur / 180.0) * (s.n_agents / 60.0) ** 1.5 for s in miss_specs)
    print(f"[e5] {len(rows)} saved runs; missing nominal combinations: "
          + (", ".join(f"{a} N={n}" for a, n in missing) or "none"))
    import os

    n_workers = max(1, min(int(args.workers or os.cpu_count() or 1), len(miss_specs) or 1))
    # parallel runs on this laptop are ~2.3x slower each than a single run (shared cores)
    print(f"[e5] {len(miss_specs)} runs needed; estimated {cpu / 60:.1f} CPU-min, "
          f"~{max(cpu * 2.3 / n_workers, max(EST_CPU_S.values())) / 60:.1f} min wall with {n_workers} workers")
    if miss_specs and not args.run_missing:
        print("[e5] stopping before running them (pass --run-missing to run).")
        return 3
    if miss_specs:
        run_matrix(miss_specs, out_dir, workers=args.workers)
        rows = collect(root)

    write_csv(rows, out_dir / "stl_runs.csv", STL_COLUMNS)
    pooled = pooled_nominal(rows)
    aggregate_rows(rows, out_dir, ["scenario", "condition", "architecture", "num_agents"], STL_METRICS,
                   name="stl_summary.csv")
    aggregate_rows(pooled, out_dir, ["architecture", "num_agents"], STL_METRICS, name="stl_summary_pooled.csv")
    man_info = {
        "sources": SOURCES, "missing_before": [f"{a} N={n}" for a, n in missing],
        "runs_added": len(miss_specs), "config_section": {"experiments.week6.matrices.e5": raw},
        "seeds": sorted({r["seed"] for r in rows}), "agent_counts": sorted({r["num_agents"] for r in rows}),
        "stl_runs_csv": {"file": "stl_runs.csv", "rows": len(rows)},
        "stl_summary_csv": {"file": "stl_summary.csv",
                            "group_by": ["scenario", "condition", "architecture", "num_agents"],
                            "metrics": STL_METRICS},
        "stl_summary_pooled_csv": {"file": "stl_summary_pooled.csv", "group_by": ["architecture", "num_agents"],
                                   "note": "nominal runs of all experiments, one per (architecture, N, seed)"},
        "quick": bool(args.quick),
    }
    if (out_dir / "manifest.json").is_file():
        update_manifest(out_dir, man_info)
    else:
        write_manifest(out_dir / "stl_runs.csv", man_info)
    print(f"[e5] wrote {out_dir / 'stl_runs.csv'} ({len(rows)} rows) and stl_summary.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
