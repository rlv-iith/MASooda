"""Load the experiment runs and provide the helpers used by every analysis script.

g(run, metric) reads one metric, select(...) filters runs, ci() is a 95% t-interval and
paired(a, b, metric) is the 95% t-interval of the per-seed difference b - a.
Run directly to print how many runs each experiment cell has.
"""
import json, sys, glob, math, collections
import paths
import numpy as np


def _t_two_sided(t, nu):
    """P(|T| < t) for Student's t with integer nu degrees of freedom (closed form)."""
    th = math.atan(t / math.sqrt(nu))
    c2, s = math.cos(th) ** 2, math.sin(th)
    if nu % 2:   # odd
        term, acc = 1.0, 1.0
        for k in range(1, (nu - 1) // 2):
            term *= c2 * (2 * k) / (2 * k + 1); acc += term
        return (2 / math.pi) * (th + (s * math.cos(th) * acc if nu > 1 else 0.0))
    term, acc = 1.0, 1.0
    for k in range(1, nu // 2):
        term *= c2 * (2 * k - 1) / (2 * k); acc += term
    return s * acc


def t_quantile_975(nu):
    """0.975 quantile of Student's t (two-sided 95%); scipy if installed, else exact bisection."""
    try:
        from scipy import stats
        return float(stats.t.ppf(0.975, nu))
    except ImportError:
        lo, hi = 0.0, 1000.0
        for _ in range(200):
            mid = 0.5 * (lo + hi)
            lo, hi = (mid, hi) if _t_two_sided(mid, nu) < 0.95 else (lo, mid)
        return 0.5 * (lo + hi)

FILES = [a for a in sys.argv[1:] if a.endswith(".jsonl")] or [str(paths.RUNS)]
runs = {}
for fn in FILES:
    try:
        for line in open(fn):
            r = json.loads(line)
            if "error" in r and "stats" not in r:
                continue
            runs[r["key"]] = r
    except FileNotFoundError:
        pass
R = list(runs.values())


def g(r, k):
    st, pr = r["stats"], r["prio"]
    if k in st:
        v = st[k]
    elif k in pr:
        v = pr[k]
    elif k == "fault_to_land_s":
        ts = [f["land_t"] - f["t_fault"] for f in r["faults"] if f["land_t"] is not None and f["divert_t"] is not None]
        v = float(np.mean(ts)) if ts else None
    elif k == "fault_outcome_pad":
        v = sum(1 for f in r["faults"] if f["land_t"] is not None)
    elif k == "fault_forced":
        v = sum(1 for f in r["faults"] if f["forced_t"] is not None)
    elif k == "fault_diverted":
        v = sum(1 for f in r["faults"] if f["divert_t"] is not None)
    elif k == "fault_min_true_soc":
        xs = [f["soc_true_last"] for f in r["faults"] if f["soc_true_last"] is not None]
        v = min(xs) if xs else None
    elif k == "admm_ms_p95":
        v = r["admm_run"].get("ms_p95")
    elif k == "admm_ms_mean":
        v = r["admm_run"].get("ms_mean")
    elif k == "admm_it_mean":
        v = r["admm_run"].get("it_mean")
    elif k == "admm_it_p95":
        v = r["admm_run"].get("it_p95")
    elif k == "admm_groups":
        v = r["admm_run"].get("groups")
    elif k == "admm_conv":
        a = r["admm_run"]; v = a["converged"] / a["groups"] if a.get("groups") else None
    elif k == "rtf":
        v = r["rtf"]
    elif k == "arrival_frac":
        v = st["arrivals"] / r["flights"]
    elif k == "evtol_wh":
        v = (st.get("energy_per_delivered_by_type_wh") or {}).get("EVTOL")
    else:
        raise KeyError(k)
    return None if v is None else float(v)


def ci(xs):
    xs = np.asarray([x for x in xs if x is not None and np.isfinite(x)], float)
    n = len(xs)
    if n == 0:
        return (math.nan, math.nan, 0)
    if n == 1:
        return (xs.mean(), math.nan, 1)
    h = t_quantile_975(n - 1) * xs.std(ddof=1) / math.sqrt(n)
    return (xs.mean(), h, n)


def select(**kw):
    out = []
    for r in R:
        ok = all((r.get(k) == v) if k != "extra" else (r["extra"] == v) for k, v in kw.items())
        if ok:
            out.append(r)
    return out


def paired(a_runs, b_runs, k):
    A = {r["seed"]: g(r, k) for r in a_runs}
    B = {r["seed"]: g(r, k) for r in b_runs}
    d = [B[s] - A[s] for s in A if s in B and A[s] is not None and B[s] is not None]
    return ci(d)


def fmt(m, h, d=1):
    if not np.isfinite(m):
        return "--"
    return f"{m:.{d}f}" + ("" if not np.isfinite(h) else f" $\\pm$ {h:.{d}f}")


if __name__ == "__main__":
    print(len(R), "runs", collections.Counter((r["suite"], r["scenario"], r["manager"], r["knowledge"], r["architecture"], r["fleet"], json.dumps(r["extra"])) for r in R).most_common(60))
