"""Fig. 3 (manuscript/fig_estimator.pdf) from results/estimator/s0_estimator.csv.gz (seed 1)."""
import csv, gzip, collections, numpy as np, matplotlib
import paths
matplotlib.use("Agg"); import matplotlib.pyplot as plt
plt.rcParams.update({"font.size": 7, "axes.linewidth": 0.6, "font.family": "serif"})
rows = list(csv.DictReader(gzip.open(paths.ESTIMATOR / "s0_estimator.csv.gz", "rt")))
by = collections.defaultdict(list)
for r in rows: by[(r["cond"], r["seed"])].append(r)
fig, axs = plt.subplots(2, 2, figsize=(3.5, 2.9), sharex=True)
titles = {"nominal": "nominal", "capacity_loss": "capacity loss at 60 s", "cell_failure": "cell failure at 60 s", "overheating": "overheating at 60 s"}
for ax, cond in zip(axs.flat, ("nominal", "capacity_loss", "cell_failure", "overheating")):
    R = by[(cond, "1")]
    ts = sorted({float(r["t"]) for r in R})
    E = np.array([[float(r["err_pct"]) for r in R if float(r["t"]) == t] for t in ts])
    S = np.array([[float(r["sigma_pct"]) for r in R if float(r["t"]) == t] for t in ts])
    D = np.array([[float(r["e_bms"]) - float(r["e_true"]) for r in R if float(r["t"]) == t] for t in ts])
    ax.fill_between(ts, -3 * S.mean(1), 3 * S.mean(1), color="#cbd5e1", lw=0, label=r"$\pm3\sigma$ (mean)")
    ax.plot(ts, E.mean(1), color="#1d4ed8", lw=0.9, label="SoC error, mean")
    ax.plot(ts, np.percentile(np.abs(E), 95, axis=1), color="#1d4ed8", lw=0.6, ls="--", label="|error|, 95th pct")
    ax2 = ax.twinx(); ax2.plot(ts, D.max(1), color="#dc2626", lw=0.7, label=r"max $E^{BMS}-E^{true}$")
    ax2.axhline(0, color="#dc2626", lw=0.4, ls=":"); ax2.set_ylim(-150, 150); ax2.tick_params(labelsize=6, colors="#dc2626")
    ax.set_ylim(-2.5, 2.5); ax.set_title(titles[cond], fontsize=7, pad=2)
    if cond != "nominal": ax.axvline(60, color="black", lw=0.4, ls=":")
for ax in axs[1]: ax.set_xlabel("time (s)")
for ax in axs[:, 0]: ax.set_ylabel("SoC (%)")
h1, l1 = axs[0, 0].get_legend_handles_labels()
fig.legend(h1 + [plt.Line2D([], [], color="#dc2626", lw=0.7)], l1 + [r"max $E^{\mathrm{BMS}}-E^{\mathrm{true}}$ (Wh, right)"], loc="lower center", ncol=2, fontsize=5.5, frameon=False)
fig.tight_layout(rect=(0, 0.1, 1, 1), pad=0.3, h_pad=0.6, w_pad=0.9)
fig.savefig(paths.MANUSCRIPT / "fig_estimator.pdf"); print("ok")
