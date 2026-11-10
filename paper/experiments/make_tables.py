"""Tables V-VIII (LaTeX rows), Figs. 4-5 and results/numbers.json from results/runs_final.jsonl."""
import json, math, sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import paths
import analyze as A
R = A.R
g, select, ci, paired = A.g, A.select, A.ci, A.paired
OUT = {}


def cfmt(m, h, d):
    if not np.isfinite(m):
        return "--"
    if not np.isfinite(h):
        return f"{m:.{d}f}"
    return f"{m:.{d}f}\\,{{\\scriptsize({h:.{d}f})}}"


def cell(rs, k, d=1, scale=1.0):
    m, h, n = ci([None if g(r, k) is None else g(r, k) * scale for r in rs])
    return cfmt(m, h, d), m, h, n


def row(label, rs, metrics):
    out = [label]
    for k, d, sc in metrics:
        s, m, h, n = cell(rs, k, d, sc)
        out.append(s)
    return " & ".join(out) + r" \\"


lines = []
print("runs:", len(R))

# ---------------- S1 ----------------
M1 = [("forced_landings", 1, 1), ("diversions", 1, 1), ("grounded_preflight", 1, 1),
      ("pads_held_short", 1, 1), ("arrival_frac", 1, 100), ("mean_delay_s", 1, 1), ("on_time_rate", 1, 100),
      ("min_separation_m", 1, 1)]
M1X = [("energy_depleted", 2, 1), ("near_misses", 2, 1)]
t1 = []
for scn, lab in (("nominal", "Nominal"), ("lowsoc", "Low-SoC fleet"), ("faults", "Battery faults"), ("heat", r"Heat wave 44\,$^\circ$C")):
    t1.append(r"\multicolumn{9}{@{}l}{\textit{" + lab + r"}} \\")
    for m, ml in (("blind", "Health-blind"), ("rule", "Rule"), ("full", "Full")):
        rs = select(suite="S1", scenario=scn, manager=m)
        t1.append(row(ml, rs, M1))
        OUT[f"S1_{scn}_{m}_n"] = len(rs)
        for k, d, sc in M1 + M1X + [("fault_to_land_s", 1, 1), ("fault_forced", 2, 1), ("pad_holds", 1, 1), ("mean_ground_hold_s", 2, 1), ("energy_per_delivered_wh", 1, 1)]:
            mm, hh, nn = ci([None if g(r, k) is None else g(r, k) * sc for r in rs])
            OUT[f"S1_{scn}_{m}_{k}"] = [mm, hh, nn]
    for m in ("rule", "full"):
        for k in ("diversions", "pads_held_short", "mean_delay_s", "on_time_rate", "grounded_preflight", "arrival_frac", "near_misses", "min_separation_m", "fault_to_land_s"):
            OUT[f"S1_{scn}_d_{m}_vs_blind_{k}"] = list(paired(select(suite="S1", scenario=scn, manager="blind"),
                                                              select(suite="S1", scenario=scn, manager=m), k))
    # identical runs (by construction) between arms
    for m in ("rule", "full"):
        a = {r["seed"]: r for r in select(suite="S1", scenario=scn, manager="blind")}
        b = {r["seed"]: r for r in select(suite="S1", scenario=scn, manager=m)}
        OUT[f"S1_{scn}_identical_{m}"] = sum(1 for s in a if s in b and a[s]["stats"] == b[s]["stats"])
open(paths.TABLES / "tab_s1.tex", "w").write("\n".join(t1))

# ---------------- S2 ----------------
M2 = [("diversions", 1, 1), ("grounded_preflight", 1, 1),
      ("arrival_frac", 1, 100), ("delivered", 1, 1), ("mean_delay_s", 1, 1)]
M2X = [("energy_depleted", 2, 1), ("forced_landings", 2, 1)]
t2 = []
for scn, lab in (("lowsoc", "Low-SoC fleet"), ("faults", "Battery faults")):
    t2.append(r"\multicolumn{6}{@{}l}{\textit{" + lab + r"}} \\")
    for kn, kl in (("oracle", "Oracle"), ("ekf_z0", "EKF, $z = 0$"), ("ekf", "EKF, $z = 1.645$")):
        rs = select(suite="S1", scenario=scn, manager="full") if kn == "ekf" else select(suite="S2", scenario=scn, knowledge=kn)
        t2.append(row(kl, rs, M2))
        for k, d, sc in M2 + M2X + [("fault_min_true_soc", 1, 1), ("fault_to_land_s", 1, 1)]:
            OUT[f"S2_{scn}_{kn}_{k}"] = list(ci([None if g(r, k) is None else g(r, k) * sc for r in rs]))
        OUT[f"S2_{scn}_{kn}_forced_runs"] = sum(1 for r in rs if g(r, "forced_landings") > 0)
        OUT[f"S2_{scn}_{kn}_forced_total"] = sum(g(r, "forced_landings") for r in rs)
    ek = select(suite="S1", scenario=scn, manager="full")
    for kn in ("oracle", "ekf_z0"):
        for k in ("grounded_preflight", "arrival_frac", "diversions", "delivered"):
            OUT[f"S2_{scn}_d_ekf_vs_{kn}_{k}"] = list(paired(select(suite="S2", scenario=scn, knowledge=kn), ek, k))
open(paths.TABLES / "tab_s2.tex", "w").write("\n".join(t2))

# ---------------- S3 / S4 / S6 ----------------
M3 = [("arrival_frac", 1, 100), ("near_misses", 2, 1), ("safety_violation_ticks", 1, 1), ("min_separation_m", 1, 1),
      ("crashes", 2, 1), ("mean_delay_s", 1, 1), ("admm_groups", 0, 1), ("rtf", 1, 1)]
t3 = []
for arch, al in (("hierarchical", "Hierarchical"), ("centralized", "Centralized"), ("decentralized", "Decentralized"),
                 ("decentralized_undefended", "Decentr., undefended")):
    rs = select(suite="S1", scenario="nominal", manager="full") if arch == "hierarchical" else select(suite="S3", architecture=arch)
    t3.append(row(al, rs, M3))
    for k, d, sc in M3 + [("admm_ms_p95", 2, 1), ("energy_per_delivered_wh", 1, 1), ("on_time_rate", 2, 100)]:
        OUT[f"S3_{arch}_{k}"] = list(ci([None if g(r, k) is None else g(r, k) * sc for r in rs]))
open(paths.TABLES / "tab_s3.tex", "w").write("\n".join(t3))

M4 = [("spoofed_reports_accepted", 0, 1), ("min_separation_m", 1, 1), ("arrival_frac", 1, 100)]
M4X = [("near_misses", 2, 1), ("safety_violation_ticks", 1, 1), ("crashes", 2, 1)]
t4 = []
for lab, rs in (("No attack", select(suite="S1", scenario="nominal", manager="full")),
                ("Attack, defended", select(suite="S4", extra={"attack": True, "defended": True})),
                ("Attack, undefended", select(suite="S4", extra={"attack": True, "defended": False})),
                (r"DTC outage", select(suite="S6"))):
    t4.append(row(lab, rs, M4))
    for k, d, sc in M4 + M4X + [("mean_delay_s", 1, 1), ("attack_active_ticks", 0, 1), ("overseer_dropped", 0, 1), ("dtc_directives", 0, 1)]:
        OUT[f"S4_{lab}_{k}"] = list(ci([None if g(r, k) is None else g(r, k) * sc for r in rs]))
open(paths.TABLES / "tab_s4.tex", "w").write("\n".join(t4))
# outage paired against nominal (same seeds)
for k in ("arrival_frac", "near_misses", "mean_delay_s", "min_separation_m"):
    OUT[f"S6_d_{k}"] = list(paired(select(suite="S1", scenario="nominal", manager="full", seed=None) if False else
                                   [r for r in select(suite="S1", scenario="nominal", manager="full") if r["seed"] <= 10],
                                   select(suite="S6"), k))
for k in ("near_misses", "safety_violation_ticks", "min_separation_m", "spoofed_reports_accepted"):
    OUT[f"S4_d_undef_vs_def_{k}"] = list(paired(select(suite="S4", extra={"attack": True, "defended": True}),
                                               select(suite="S4", extra={"attack": True, "defended": False}), k))

# ---------------- S5 scaling ----------------
Ns = [50, 100, 150, 200]
sc = {}
for n in Ns:
    rs = [r for r in select(suite="S1", scenario="nominal", manager="full") if r["seed"] <= 10] if n == 100 else select(suite="S5", fleet=n)
    sc[n] = {k: ci([g(r, k) for r in rs]) for k in ("admm_groups", "admm_it_mean", "admm_it_p95", "admm_ms_mean", "admm_ms_p95", "admm_conv", "rtf", "near_misses", "arrival_frac", "min_separation_m")}
    for k, v in sc[n].items():
        OUT[f"S5_N{n}_{k}"] = list(v)
fig, ax = plt.subplots(1, 2, figsize=(3.5, 1.55))
plt.rcParams.update({"font.size": 7})
for key, lab, c in (("admm_ms_mean", "mean", "#1d4ed8"), ("admm_ms_p95", "95th pct", "#dc2626")):
    m = [sc[n][key][0] for n in Ns]; h = [sc[n][key][1] for n in Ns]
    ax[0].errorbar(Ns, m, yerr=h, marker="o", ms=2.5, lw=0.9, capsize=2, color=c, label=lab)
ax[0].set_xlabel("fleet size", fontsize=7); ax[0].set_ylabel("ADMM solve (ms)", fontsize=7); ax[0].legend(fontsize=6, frameon=False)
m = [sc[n]["rtf"][0] for n in Ns]; h = [sc[n]["rtf"][1] for n in Ns]
ax[1].errorbar(Ns, m, yerr=h, marker="o", ms=2.5, lw=0.9, capsize=2, color="#0f766e")
ax[1].axhline(1.0, color="black", lw=0.5, ls=":"); ax[1].set_xlabel("fleet size", fontsize=7); ax[1].set_ylabel("real-time factor", fontsize=7)
for a in ax:
    a.tick_params(labelsize=6)
    for s in ("top", "right"):
        a.spines[s].set_visible(False)
fig.tight_layout(pad=0.3, w_pad=1.0); fig.savefig(paths.MANUSCRIPT / "fig_scaling.pdf")

# ---------------- S1/S2 low-SoC figure ----------------
fig, axs = plt.subplots(1, 4, figsize=(7.1, 1.6))
arms = [("blind", "ekf", "Blind"), ("rule", "ekf", "Rule"), ("full", "ekf", "Full"), ("full", "oracle", "Full+oracle"), ("full", "ekf_z0", "Full, z=0")]
def arm_runs(m, kn):
    return select(suite="S1", scenario="lowsoc", manager=m) if kn == "ekf" else select(suite="S2", scenario="lowsoc", knowledge=kn)
for ax, (k, lab, scl) in zip(axs, (("grounded_preflight", "grounded pre-flight", 1), ("diversions", "diversions", 1),
                                   ("pads_held_short", "arrivals held short", 1), ("arrival_frac", "arrived (%)", 100))):
    ms, hs = [], []
    for m, kn, _ in arms:
        mm, hh, _ = ci([g(r, k) * scl for r in arm_runs(m, kn)]); ms.append(mm); hs.append(hh)
    cols = ["#94a3b8", "#60a5fa", "#1d4ed8", "#16a34a", "#f59e0b"]
    ax.bar(range(len(arms)), ms, yerr=hs, color=cols, width=0.7, capsize=1.5, error_kw={"lw": 0.6})
    ax.set_xticks(range(len(arms))); ax.set_xticklabels([a[2] for a in arms], rotation=35, ha="right", fontsize=5.5)
    ax.set_title(lab, fontsize=6.5, pad=2); ax.tick_params(labelsize=5.5)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    if k == "arrival_frac":
        ax.set_ylim(min(ms) - 6, 100)
fig.tight_layout(pad=0.3, w_pad=0.8); fig.savefig(paths.MANUSCRIPT / "fig_lowsoc.pdf")

json.dump(OUT, open(paths.RESULTS / "numbers.json", "w"), indent=0, default=float)
print("written", len(OUT))
