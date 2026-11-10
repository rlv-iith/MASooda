"""Table IV / Fig. 3: EKF validation on the standalone health model.

40 delivery drones per condition and seed (default seeds 1,2,3), 85% initial SoC, 60 s cruise at
11 m/s / 20 s hover cycles for 360 s, fault at 60 s. Writes results/estimator/s0_estimator.csv.gz
(one row per drone and second) and results/estimator/s0_summary.json.
Usage: python estimator_validation.py [seeds, e.g. 1,2,3]
"""
import sys, copy, csv, json, gzip
import paths
import numpy as np
from config.load_config import get_config
from simulation.drone_health import HealthModel

N, T, DT = 40, 360.0, 0.1
SEEDS = tuple(int(x) for x in (sys.argv[1] if len(sys.argv) > 1 else "1,2,3").split(","))
def speed_at(t):            # 60 s cruise / 20 s hover cycle
    return 11.0 if (t % 80.0) < 60.0 else 0.0
rows, summ = [], {}
for cond in ("nominal", "capacity_loss", "cell_failure", "overheating"):
    for seed in SEEDS:
        hm = HealthModel(copy.deepcopy(get_config()), seed, (0, 0))
        for j in range(N):
            o = {"soc_init_pct": 85.0}
            if cond != "nominal":
                o["fault"] = {"type": cond, "t_s": 60.0}
            hm.add(j, "DELIVERY", o, custom=True)
        k = np.arange(N)
        for n in range(int(T / DT)):
            t = n * DT
            v = speed_at(t)
            hm.step(t, DT, k, np.tile([[v, 0.0]], (N, 1)), np.array([], int), np.array([], int))
            if n % 10 == 9:
                a = hm.a
                tt = round(t + DT, 1)
                for j in range(N):
                    rows.append({"cond": cond, "seed": seed, "t": tt, "drone": j,
                                 "err_pct": (a["soc_hat"][j] - a["soc"][j]) * 100, "sigma_pct": np.sqrt(a["P11"][j]) * 100,
                                 "q_ratio": 1.0 / a["qinv_hat"][j] / a["qeff"][j],
                                 "e_bms": hm.e_rem_bms_wh(j), "e_true": hm.e_rem_wh(j)})
paths.ESTIMATOR.mkdir(parents=True, exist_ok=True)
with gzip.open(paths.ESTIMATOR / "s0_estimator.csv.gz", "wt", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
import collections
out = {}
for cond in ("nominal", "capacity_loss", "cell_failure", "overheating"):
    R = [r for r in rows if r["cond"] == cond]
    post = [r for r in R if r["t"] > 60.0] if cond != "nominal" else R
    late = [r for r in R if r["t"] > 180.0]
    e = np.array([r["err_pct"] for r in post]); s = np.array([r["sigma_pct"] for r in post])
    over = np.array([r["e_bms"] > r["e_true"] for r in post]); over_late = np.array([r["e_bms"] > r["e_true"] for r in late])
    out[cond] = {"n": len(post), "rmse_pct": float(np.sqrt(np.mean(e**2))), "max_abs_pct": float(np.max(np.abs(e))),
                 "within_2sigma": float(np.mean(np.abs(e) <= 2 * s)), "within_3sigma": float(np.mean(np.abs(e) <= 3 * s)),
                 "mean_sigma_pct": float(np.mean(s)), "p_overestimate_energy": float(np.mean(over)),
                 "p_overestimate_energy_after180": float(np.mean(over_late)),
                 "max_over_wh": float(np.max([r["e_bms"] - r["e_true"] for r in post])),
                 "q_ratio_end_mean": float(np.mean([r["q_ratio"] for r in R if r["t"] == T]))}
json.dump(out, open(paths.ESTIMATOR / "s0_summary.json", "w"), indent=1)
print(json.dumps(out, indent=1))
