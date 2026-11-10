"""Reproducibility check quoted in Section VIII-A.

Compares the runs that were executed on both platforms: results/runs_final.jsonl (Linux, Python 3.13,
NumPy 2.5) and results/runs_second_platform.jsonl (a second Linux machine, Python 3.10, NumPy 2.2). Runs that
were re-executed after the hold-short fix (rerun_after_holdshort_fix_keys.txt) are excluded, because
the second-platform copies were produced with the earlier code. Discrete outcomes must match exactly;
continuous ones are reported as the largest absolute difference.
Writes results/cross_platform_check.txt.
"""
import json
import paths

DISCRETE = ["arrivals", "delivered", "diversions", "grounded_preflight", "forced_landings", "energy_depleted",
            "near_misses", "safety_violation_ticks", "crashes", "pads_held_short"]
CONTINUOUS = ["min_separation_m", "mean_delay_s", "energy_per_delivered_wh"]


def load(fn):
    out = {}
    for line in open(fn):
        r = json.loads(line)
        if "stats" in r:
            out[r["key"]] = r
    return out


final, second = load(paths.RUNS), load(paths.RUNS_SECOND)
rerun = set((paths.RESULTS / "rerun_after_holdshort_fix_keys.txt").read_text().split())
common = sorted(k for k in final if k in second and k not in rerun)
lines = [f"runs on both platforms (code unchanged between them): {len(common)}"]
mismatch = []
for k in common:
    a, b = final[k], second[k]
    sa = {**a["stats"], **{f"prio.{x}": y for x, y in a["prio"].items()}}
    sb = {**b["stats"], **{f"prio.{x}": y for x, y in b["prio"].items()}}
    for m in DISCRETE:
        if sa.get(m) != sb.get(m):
            mismatch.append((k, m, sa.get(m), sb.get(m)))
lines.append(f"discrete metrics compared: {', '.join(DISCRETE)}")
lines.append(f"runs with any discrete difference: {len({m[0] for m in mismatch})}")
for m in mismatch:
    lines.append(f"  {m}")
for m in CONTINUOUS:
    get = lambda r: r["stats"].get(m, r["prio"].get(m))
    d = [abs(get(final[k]) - get(second[k])) for k in common if get(final[k]) is not None and get(second[k]) is not None]
    lines.append(f"max |difference| in {m}: {max(d) if d else float('nan'):.6g}")
txt = "\n".join(lines)
print(txt)
(paths.RESULTS / "cross_platform_check.txt").write_text(txt + "\n")
