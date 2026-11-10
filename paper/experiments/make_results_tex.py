"""Write manuscript/masooda_paper.tex: fills the abstract, results, discussion and conclusion of
manuscript/masooda_paper_template.tex with the measured values (numbers.json, s0_summary.json,
case_study.json, the runs themselves) and inlines the table rows from results/tables/."""
import json, math
import paths

N = json.load(open(paths.RESULTS / "numbers.json"))
S0 = json.load(open(paths.ESTIMATOR / "s0_summary.json"))
CS = json.load(open(paths.RESULTS / "case_study.json"))


def v(key, i=0, d=1, scale=1.0):
    x = N[key]
    x = x[i] if isinstance(x, list) else x
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "--"
    return f"{x * scale:.{d}f}"


def pm(key, d=1, scale=1.0):
    m, h = N[key][0], N[key][1]
    if not math.isfinite(m):
        return "--"
    if not math.isfinite(h) or h == 0:
        return f"{m * scale:.{d}f}"
    return f"{m * scale:.{d}f} $\\pm$ {abs(h * scale):.{d}f}"


def s0up(cond, k):
    return f"{math.ceil(S0[cond][k] * 10) / 10:.1f}"


def s0(cond, k, d=2, scale=1.0):
    return f"{S0[cond][k] * scale:.{d}f}"


_ft = [int(N[f"S2_lowsoc_{k}_forced_total"]) for k in ("oracle", "ekf_z0", "ekf")]
forced_sentence = ("No forced landing occurred in the low-SoC fleet in any knowledge arm." if sum(_ft) == 0 else
                   f"Forced landings over 20 runs: {_ft[0]} (oracle), {_ft[1]} ($z = 0$) and {_ft[2]} ($z = 1.645$).")
import analyze as A
import numpy as _np
_H = [x for r in A.select(suite="S1", scenario="heat") for x in r["faults"]]
_ht = _np.array([[x["crit_t"] - x["t_fault"], x["divert_t"] - x["crit_t"], x["forced_t"] - x["divert_t"], x["forced_t"] - x["crit_t"]] for x in _H])
HT = dict(n=len(_H), crit=_ht[:, 0].mean(), crit_lo=_ht[:, 0].min(), crit_hi=_ht[:, 0].max(), hold=_ht[:, 1].mean(),
          fd_lo=_ht[:, 2].min(), fd_hi=_ht[:, 2].max(), cf=_ht[:, 3].mean(), cf_lo=_ht[:, 3].min(), cf_hi=_ht[:, 3].max())
_F = [(r, x) for r in A.select(suite="S1", scenario="faults") for x in r["faults"]]
FC = dict(cell_div=sum(1 for r, x in _F if x["fault"] == "cell_failure" and x["divert_t"] is not None),
          cell_n=sum(1 for r, x in _F if x["fault"] == "cell_failure"),
          cap_div=sum(1 for r, x in _F if x["fault"] == "capacity_loss" and x["divert_t"] is not None),
          cap_n=sum(1 for r, x in _F if x["fault"] == "capacity_loss"),
          crit_lag=max(x["crit_t"] - x["t_fault"] for r, x in _F if x["fault"] == "cell_failure"))
_b13 = [x for r in A.select(suite="S1", scenario="faults", manager="blind") if r["seed"] == 13 for x in r["faults"] if x["forced_t"] is None and x["id"] == 101][0]
_f13 = [x for r in A.select(suite="S1", scenario="faults", manager="full") if r["seed"] == 13 for x in r["faults"] if x["id"] == 101][0]
S13 = dict(t_fault=_f13["t_fault"], forced=_f13["forced_t"], blind_land=_b13["land_t"], soc=_f13["soc_true_last"])
def _excl(k, sc=1.0):
    m, h = N[k][0] * sc, N[k][1] * sc
    return abs(m) > abs(h)
_dk, _ok = "S1_lowsoc_d_full_vs_blind_mean_delay_s", "S1_lowsoc_d_full_vs_blind_on_time_rate"
delay_sentence = (f"Emergency delay rose by {pm(_dk)}~s" + (" (the interval excludes zero: arbitration cost emergency flights a small delay)" if _excl(_dk) and N[_dk][0] > 0 else " (the interval includes zero)")
                  + f" and the on-time rate of emergency flights changed by {pm(_ok, 1, 100)} points" + (" (the interval includes zero)." if not _excl(_ok) else "."))
XP_N = int((paths.RESULTS / "cross_platform_check.txt").read_text().split(":")[1].split()[0])
cs_ev = {(e[1], e[2]) for e in CS["events"]}
c1, c2 = CS["c1"], CS["c2"]
def cs_t(kind, needle):
    for t, k, text in CS["events"]:
        if k == kind and needle in text:
            return t
    return None

t_c1_div, t_c1_land = cs_t("divert", f"D-{c1} "), cs_t("land", f"D-{c1} ")
t_c2_div, t_c2_land = cs_t("divert", f"D-{c2} "), cs_t("land", f"D-{c2} ")

abstract = rf"""Battery-electric drones are limited by their remaining energy, yet unmanned traffic management (UTM) algorithms assign priority and deconfliction effort by mission class and geometry, and battery health management decides for one vehicle at a time. This paper places the battery management system (BMS) of every drone inside the decision loop of a hierarchical fleet traffic manager. Each drone carries a 1-RC Thevenin pack model with per-cell spread and a lumped thermal model; its BMS estimates the state of charge, polarisation voltage and capacity with an extended Kalman filter from noisy, biased sensors. Every energy decision uses a chance-constrained usable-energy bound together with a weakest-cell voltage-sag check. The drone traffic controller uses the same state to give critical drones right of way, to arbitrate landing pads by remaining endurance, and to set bounded, energy-margin-dependent weights in a consensus-ADMM conflict resolver. The approach is implemented in MASooda, an open simulator built on road-aligned corridors traced from the IIT Hyderabad campus, and evaluated in 460 paired-seed runs with 100 drones. The estimator kept the state-of-charge error below {s0up('nominal','max_abs_pct')}\% and never overestimated usable energy in nominal flight (error below {s0up('cell_failure','max_abs_pct')}\% in all fault conditions); after a sudden 30\% capacity loss it overestimated energy in {s0('capacity_loss','p_overestimate_energy',0,100)}\% of samples during a learning transient of about two minutes. In a low-charge fleet, the chance-constrained check kept {v('S2_lowsoc_d_ekf_vs_oracle_grounded_preflight',0,1)} more drones per run on the ground and avoided {v('S2_lowsoc_d_ekf_vs_oracle_diversions',0,1,-1)} in-flight diversions relative to a BMS with perfect knowledge, at an unchanged number of parcels delivered. Health-aware pad arbitration and ADMM weighting produced no measurable improvement in safety, deliveries or emergency delay in the tested scenarios; in one of 20 battery-fault runs, a drone holding short for a critical drone stood in its path, and the critical drone's failed cell reached its voltage limit during the avoidance manoeuvre. No energy-depletion event occurred in any arm. The evaluation also exposes a limitation: at 44~$^\circ$C every overheating drone reached a thermal fault before its diversion began, which motivates predictive thermal responses."""

results = rf"""%======================================================================
\section{{Experimental Evaluation}}\label{{sec:results}}

\subsection{{Setup}}
All experiments use the campus map of Fig.~\ref{{fig:map}}, a random fleet of 100 drones (10\% emergency, 30\% eVTOL, 60\% delivery) departing within 90~s, and a horizon of 240~s. Four scenarios are used. \emph{{Nominal}}: random-fleet SoC uniform in 35--100\% and SoH in 80--100\%, 35~$^\circ$C ambient. \emph{{Low-SoC}}: as nominal but SoC uniform in 15--50\%. \emph{{Battery faults}}: nominal plus four delivery drones on long routes with a cell failure (two drones) or a 30\% capacity loss (two drones) injected 45~s after departure. \emph{{Heat wave}}: 44~$^\circ$C, 2~m/s wind and four delivery drones with an overheating fault 45~s after departure. The fault drones' routes, departure times and initial SoC are drawn from the seed.

Three traffic-manager arms are compared. \emph{{Blind}}: drones keep all onboard BMS responses (Section~\ref{{sec:health}}-A), but the DTC ignores health and ADMM uses class weights. \emph{{Rule}}: adds the DTC health rule and pad arbitration. \emph{{Full}}: adds the energy-margin ADMM weights \eqref{{eq:weight}}. Three knowledge arms are compared under the full manager: an \emph{{oracle}} BMS that reads the true state, the EKF with $z = 0$, and the EKF with $z = 1.645$ (the default). Further suites compare the four architectures in nominal traffic (hierarchical, centralized, decentralized with ADMM and report defence, decentralized undefended), a position-spoofing attack by two delivery drones from 60~s, fleet sizes of 50--200, and a DTC link outage from 80 to 150~s.

Each cell has 20 seeds (10 for the scaling and outage suites); arms with the same seed share all initial conditions, so differences are computed per seed. Values are means with 95\% $t$-intervals across seeds. In total 460 runs were executed on one platform (Python~3.13, NumPy~2.5); {XP_N} of them were also run on a second machine (Python~3.10, NumPy~2.2). The 160 runs that exercise pad arbitration in the low-SoC and fault scenarios (Rule and Full arms and the knowledge suite) were re-executed on the first platform only, after a fix to the hold-short logic, and are excluded from that comparison. In the {XP_N} common runs every discrete outcome (arrivals, deliveries, diversions, groundings, forced landings, near misses, collisions) was identical and continuous quantities differed only in floating-point detail. Metrics: \emph{{energy depleted}} (true SoC reaches zero in flight), \emph{{forced landings}} (landed in place, off any pad), \emph{{diversions}}, \emph{{grounded}} (failed pre-flight check), \emph{{held short}} (arrivals that waited for a reserved pad), \emph{{arrived}} (fraction of flights that landed at any pad, including diversions), \emph{{delivered}} (landed at the planned destination), emergency \emph{{delay}} (travel time from scheduled departure minus free-flow time) and \emph{{on time}} (delay $\le \max(10\,\mathrm{{s}}, 0.2 \times$ nominal)), \emph{{near misses}} (loss-of-separation episodes, $d_{{ij}} < 8$~m) and minimum layer-aware separation.

\subsection{{State Estimation}}
The estimator was first validated in isolation: 40 delivery drones per condition and seed (3 seeds), starting at 85\% SoC, alternating 60~s of cruise at 11~m/s with 20~s of hover for 360~s, with a fault at 60~s. Table~\ref{{tab:est}} and Fig.~\ref{{fig:est}} summarise the results. The SoC error stayed within $\pm 3\sigma$ in all samples and below {s0up('cell_failure','max_abs_pct')}\% in all conditions. The reported $\sigma$ is conservative: the mean $\sigma$ is {min(S0[c]['mean_sigma_pct']/S0[c]['rmse_pct'] for c in S0):.1f}--{max(S0[c]['mean_sigma_pct']/S0[c]['rmse_pct'] for c in S0):.1f} times the RMS error. In nominal flight, the chance-constrained energy \eqref{{eq:ebms}} never exceeded the true usable energy; it was always at least {s0('nominal','max_over_wh',0,-1)}~Wh (about 7\% of the 500~Wh pack) below it, which is the price of the bound. After a sudden 30\% capacity loss, the BMS still believes the old capacity until the voltage residual corrects $\hat q$: the energy was overestimated in {s0('capacity_loss','p_overestimate_energy',0,100)}\% of post-fault samples, by up to {s0('capacity_loss','max_over_wh',0)}~Wh, and never after 180~s. A failed cell is visible in the cell voltages and the estimate stays conservative. The hidden drain of an overheating fault is absorbed by the capacity state, which falls to {s0('overheating','q_ratio_end_mean',2)} of the true capacity, so the energy bound becomes more conservative rather than optimistic.

\begin{{table}}[t]
\centering
\caption{{EKF validation (40 drones $\times$ 3 seeds per condition, samples after the fault)}}
\label{{tab:est}}
\footnotesize
\setlength{{\tabcolsep}}{{3pt}}
\begin{{tabular}}{{@{{}}lrrrr@{{}}}}
\toprule
 & Nominal & Cap.\ loss & Cell fail. & Overheat \\
\midrule
SoC RMSE (\%) & {s0('nominal','rmse_pct')} & {s0('capacity_loss','rmse_pct')} & {s0('cell_failure','rmse_pct')} & {s0('overheating','rmse_pct')} \\
max $|$error$|$ (\%) & {s0('nominal','max_abs_pct')} & {s0('capacity_loss','max_abs_pct')} & {s0('cell_failure','max_abs_pct')} & {s0('overheating','max_abs_pct')} \\
mean $\sigma$ (\%) & {s0('nominal','mean_sigma_pct')} & {s0('capacity_loss','mean_sigma_pct')} & {s0('cell_failure','mean_sigma_pct')} & {s0('overheating','mean_sigma_pct')} \\
within $3\sigma$ (\%) & {s0('nominal','within_3sigma',1,100)} & {s0('capacity_loss','within_3sigma',1,100)} & {s0('cell_failure','within_3sigma',1,100)} & {s0('overheating','within_3sigma',1,100)} \\
$P(\Ebms > E^{{\mathrm{{true}}}})$ (\%) & {s0('nominal','p_overestimate_energy',1,100)} & {s0('capacity_loss','p_overestimate_energy',1,100)} & {s0('cell_failure','p_overestimate_energy',1,100)} & {s0('overheating','p_overestimate_energy',1,100)} \\
max $\Ebms - E^{{\mathrm{{true}}}}$ (Wh) & {s0('nominal','max_over_wh',0)} & {s0('capacity_loss','max_over_wh',0)} & {s0('cell_failure','max_over_wh',0)} & {s0('overheating','max_over_wh',0)} \\
$\hat Q / Q$ at 360~s & {s0('nominal','q_ratio_end_mean')} & {s0('capacity_loss','q_ratio_end_mean')} & {s0('cell_failure','q_ratio_end_mean')} & {s0('overheating','q_ratio_end_mean')} \\
\bottomrule
\end{{tabular}}
\end{{table}}

\begin{{figure}}[t]
\centering
\includegraphics[width=\columnwidth]{{fig_estimator.pdf}}
\caption{{EKF state-of-charge error across 40 drones (seed 1): mean error, 95th percentile of $|$error$|$ and mean $\pm 3\sigma$ band (left axis), and the largest gap between the chance-constrained and the true usable energy (right axis). Faults at 60~s.}}
\label{{fig:est}}
\end{{figure}}

\subsection{{Traffic-Manager Ablation}}
Table~\ref{{tab:s1}} reports the manager arms. In nominal traffic no drone reached CRITICAL or diverted, so Rule produced runs identical to Blind in {N['S1_nominal_identical_rule']} of 20 seeds; the energy-margin weights changed the trajectory in {20 - N['S1_nominal_identical_full']} seeds, without a measurable change in any metric. This is the behaviour Proposition~\ref{{prop:weights}}(ii) predicts: the health layer is inactive when margins are large.

In the low-SoC fleet the arbitration was active: {pm('S1_lowsoc_d_full_vs_blind_pads_held_short')} arrivals per run held short of a reserved pad (Full minus Blind, paired). Diversions ({pm('S1_lowsoc_d_full_vs_blind_diversions', 2)}), pre-flight groundings and the fraction of flights that arrived ({pm('S1_lowsoc_d_full_vs_blind_arrival_frac', 1, 100)} percentage points) did not change measurably. {delay_sentence} With battery faults, the two cell-failure drones reached CRITICAL on cell imbalance within {FC['crit_lag']:.1f}~s of the fault and diverted in all {FC['cell_n']} cases; the two capacity-loss drones never reached a diversion threshold and continued to their destinations ({FC['cap_div']} of {FC['cap_n']} diverted). Diverted drones landed {v('S1_faults_full_fault_to_land_s')}~s after the fault on average. Arbitration made {pm('S1_faults_d_full_vs_blind_pads_held_short')} arrivals per run hold short and changed the fault-to-landing time by {pm('S1_faults_d_full_vs_blind_fault_to_land_s')}~s. In one seed (13), Rule and Full produced a forced landing that Blind did not: the cell-failure drone diverting to its reserved pad met the drone holding short for it at the tube edge, and during the 7-s ADMM manoeuvre that followed, its failed cell fell below 3.0~V under load. The BMS declared FAULT and the drone landed in place at {S13['forced']:.0f}~s, {S13['forced'] - S13['t_fault']:.0f}~s after the fault with {S13['soc']:.0f}\% SoC; with the same seed in the blind arm it reached the pad at {S13['blind_land']:.1f}~s. Holding traffic at the tube edge can thus put it in the path of the drone it is meant to protect, and a failed cell has little voltage headroom for an avoidance manoeuvre. No arm produced an energy-depletion event or a near miss in any scenario.

The heat-wave scenario shows a limitation of the onboard thermal response rather than of the traffic manager. In all arms and seeds, all four overheating drones reached a pack-temperature FAULT and landed in place ({v('S1_heat_full_fault_forced', 0, 1)} of 4 per run). Over the {HT['n']} overheating drones, the pack reached 65~$^\circ$C (CRITICAL) {HT['crit']:.0f}~s after the fault on average ({HT['crit_lo']:.0f}--{HT['crit_hi']:.0f}~s) and 75~$^\circ$C (FAULT) {HT['cf']:.0f}~s later ({HT['cf_lo']:.1f}--{HT['cf_hi']:.0f}~s). The onboard response diverts only after 30~s at CRITICAL, so the FAULT arrived {HT['fd_lo']:.0f}--{HT['fd_hi']:.0f}~s into the diversion, long before any pad could be reached.

\begin{{table*}}[t]
\centering
\caption{{Traffic-manager ablation (100 drones, 20 paired seeds; per-run mean with 95\% CI half-width in parentheses). No energy-depletion event and no near miss occurred in any run.}}
\label{{tab:s1}}
\footnotesize
\begin{{tabular}}{{@{{}}lrrrrrrrr@{{}}}}
\toprule
Arm & Forced & Diversions & Grounded & Held short & Arrived (\%) & EMG delay (s) & On time (\%) & Min sep. (m) \\
\midrule
\input{{tab_s1.tex}}
\bottomrule
\end{{tabular}}
\end{{table*}}

\subsection{{What the BMS Knows}}
Table~\ref{{tab:s2}} and Fig.~\ref{{fig:lowsoc}} compare the knowledge arms. With battery faults, all three arms produced the same discrete outcomes in every seed, including the forced landing of seed 13: the cell-failure drones diverted on cell imbalance, which does not depend on the SoC estimate, and the capacity-loss drones never came close enough to a threshold for the estimate to change a decision. In the low-SoC fleet, the chance constraint changed when drones were stopped: relative to the oracle it kept {pm('S2_lowsoc_d_ekf_vs_oracle_grounded_preflight')} more drones per run on the ground and avoided {pm('S2_lowsoc_d_ekf_vs_oracle_diversions', 1, -1)} in-flight diversions, while the number of parcels delivered changed by only {pm('S2_lowsoc_d_ekf_vs_oracle_delivered')}. The fraction of flights that landed anywhere fell by {pm('S2_lowsoc_d_ekf_vs_oracle_arrival_frac', 1, -100)} points, because a grounded drone does not count as an arrival while a diverted one does. The EKF without the margin ($z = 0$) stayed close to the oracle. {forced_sentence}

\begin{{table}}[t]
\centering
\caption{{BMS knowledge under the full manager (20 paired seeds; mean with 95\% CI half-width). No depletion occurred; the forced landing with battery faults (seed 13, all arms) is discussed in the text.}}
\label{{tab:s2}}
\footnotesize
\setlength{{\tabcolsep}}{{1.8pt}}
\begin{{tabular}}{{@{{}}lrrrrr@{{}}}}
\toprule
 & Divert. & Ground. & Arrived (\%) & Delivered & Delay (s) \\
\midrule
\input{{tab_s2.tex}}
\bottomrule
\end{{tabular}}
\end{{table}}

\begin{{figure*}}[t]
\centering
\includegraphics[width=\textwidth]{{fig_lowsoc.pdf}}
\caption{{Low-SoC fleet: drones grounded by the pre-flight check, in-flight diversions, arrivals that held short of a reserved pad, and flights that arrived at any pad, per run (mean and 95\% CI over 20 paired seeds). Blind, Rule and Full use the EKF with $z = 1.645$; the last two bars use the full manager with an oracle BMS and with the EKF at $z = 0$.}}
\label{{fig:lowsoc}}
\end{{figure*}}

\subsection{{Architectures, Resilience and Scaling}}
Table~\ref{{tab:s3}} compares the architectures in nominal traffic. The hierarchical and both decentralized variants delivered the same {v('S3_hierarchical_arrival_frac')}\% of flights with no near miss and a minimum separation of {v('S3_hierarchical_min_separation_m')}~m; their emergency delays were within 0.1~s of each other, so in this scenario the DTC's layer allocation did not change the outcome measurably. The centralized baseline, in which the DTC computes every velocity from reports refreshed at its update rate, had {pm('S3_centralized_near_misses')} near misses and {pm('S3_centralized_crashes', 2)} collisions (pairs closer than 2~m) per run, a minimum separation of {pm('S3_centralized_min_separation_m')}~m and {v('S3_centralized_arrival_frac')}\% arrivals.

Under the position-spoofing attack (Table~\ref{{tab:s4}}), the trusted-range check and W-MSR filtering accepted no spoofed report, while the undefended variant accepted {pm('S4_d_undef_vs_def_spoofed_reports_accepted', 0)} per run. Separation was unaffected in both cases (near misses 0; minimum separation changed by {pm('S4_d_undef_vs_def_min_separation_m', 2)}~m): with two spoofers and a 25~m offset, the false reports were not decisive for collision avoidance in this traffic. The DTC outage dropped 35 directives per run but changed no outcome relative to the same seeds without outage, consistent with the small role of the DTC in nominal traffic noted above.

Fig.~\ref{{fig:scale}} shows the scaling from 50 to 200 drones. ADMM groups per run grew from {v('S5_N50_admm_groups',0,0)} to {v('S5_N200_admm_groups',0,0)}, but groups stayed small: mean iterations remained about {v('S5_N200_admm_it_mean')}, every group converged, and the 95th-percentile solve time stayed near {v('S5_N200_admm_ms_p95',0,2)}~ms. The whole simulation ran at {v('S5_N50_rtf')}$\times$ real time with 50 drones and {v('S5_N200_rtf')}$\times$ with 200 on one CPU core. Arrivals fell from {v('S5_N50_arrival_frac',0,1,100)}\% to {v('S5_N200_arrival_frac',0,1,100)}\% within the 240~s horizon as pads and junctions congested, with no near miss.

\begin{{table*}}[t]
\centering
\caption{{Architectures in nominal traffic (100 drones, 20 seeds; mean with 95\% CI half-width; RTF: real-time factor on one CPU core)}}
\label{{tab:s3}}
\footnotesize
\setlength{{\tabcolsep}}{{4pt}}
\begin{{tabular}}{{@{{}}lrrrrrrrr@{{}}}}
\toprule
Architecture & Arrived (\%) & Near misses & Viol.\ ticks & Min sep.\ (m) & Collisions & EMG delay (s) & ADMM groups & RTF \\
\midrule
\input{{tab_s3.tex}}
\bottomrule
\end{{tabular}}
\end{{table*}}

\begin{{table}}[t]
\centering
\caption{{Spoofing attack (20 seeds) and DTC outage (10 seeds), hierarchical architecture with the full manager. No near miss, separation violation or collision occurred in any of these runs.}}
\label{{tab:s4}}
\footnotesize
\begin{{tabular}}{{@{{}}lrrr@{{}}}}
\toprule
 & Spoofed acc. & Min sep.\ (m) & Arrived (\%) \\
\midrule
\input{{tab_s4.tex}}
\bottomrule
\end{{tabular}}
\end{{table}}

\begin{{figure}}[t]
\centering
\includegraphics[width=\columnwidth]{{fig_scaling.pdf}}
\caption{{Scaling with fleet size (10 seeds): ADMM solve time per conflict group (left) and real-time factor of the whole simulation on one CPU core (right).}}
\label{{fig:scale}}
\end{{figure}}

\subsection{{Case Study: Battery Failure Mid-Route}}
The scripted battery-failure scenario (100 random drones and two scripted delivery drones) illustrates the mechanisms. At 70~s, cargo drone D-{c1} loses a cell; its BMS goes CRITICAL on cell imbalance, it diverts to the nearest feasible pad and the DTC reserves that pad. One arrival bound for the same pad holds short at the tube edge, and D-{c1} lands at {t_c1_land:.1f}~s, first on its pad. At 80~s, D-{c2} (31\% SoC) loses 30\% of its capacity. Its BMS does not know this; it learns the loss from the voltage and declares a low-reserve diversion at {t_c2_div:.0f}~s to a different pad, where it lands at {t_c2_land:.1f}~s. The run ends with no forced landing, no depletion and no near miss. On the publicly deployed version that preceded the changes described here, the same scenario let three drones land on one reserved pad within 7~s, sent the low-reserve drone to the pad already reserved for the critical one, and flagged the diverting critical drone as having ``made no progress''.
"""

discussion = r"""%======================================================================
\section{Discussion and Limitations}\label{sec:discussion}

\textbf{What the evidence supports.} The estimator and the chance-constrained feasibility test behave as designed: the SoC estimate is calibrated (conservatively), the energy bound does not overestimate in nominal flight, and its failure mode---a transient after a sudden, unannounced capacity loss---is bounded in time and measured. At fleet level, the bound moved the decision about marginal drones from the air to the ground: fewer diversions and more pre-flight holds, at an unchanged number of deliveries. The health-aware DTC and ADMM weights did what they specify (pads went to the drone with least endurance, others held short, healthy traffic was untouched), but in these scenarios this produced no measurable gain in safety, deliveries or emergency delay over a BMS-blind traffic manager whose drones already respond onboard, and in one seed it caused a forced landing that the blind manager avoided. The claim of this paper is therefore the integration, the estimator-aware feasibility test and the measured trade-offs, not a demonstrated safety improvement from health-aware deconfliction.

\textbf{Why the traffic-level effect is small here.} No arm ever depleted a battery, because onboard feasibility checks with a 20\% reserve already kept every drone landable; the traffic manager can only add value when drones compete for scarce landing capacity or when conflict manoeuvres consume a significant share of the margin. Pad occupancy is not modelled as a resource that can be over-subscribed, and the energy overhead of conflict resolution on a 2-km campus route is small. Scenarios with longer routes, limited pad capacity and denser low-margin traffic are needed to test whether the arbitration and the weights matter.

\textbf{Where to hold.} The seed-13 forced landing shows that the hold-short point matters. Arrivals hold at the edge of the destination's tube on their current layer, which can be the layer the critical drone approaches on (in seed 13 it was, since ADMM only couples drones on the same layer), so the two can meet near the pad, and the resulting avoidance manoeuvre draws current exactly when a failed cell has the least headroom. Holding on a different layer, or outside the approach path, and limiting the avoidance demand on a drone whose weakest-cell margin is small are straightforward refinements; they were not evaluated here.

\textbf{Thermal response.} The heat-wave result shows that a threshold-and-hold thermal response is too slow at high ambient temperature. A predictive response that diverts when the predicted time to the FAULT temperature falls below the time to the nearest pad, for example as an STL specification $\mathbf{G}(T_p \le T_{\max})$ with robustness-driven intervention, is the natural next step.

\textbf{Threats to validity.} (i) The battery, power and thermal models are documented but not calibrated against a specific cell or airframe; public flight-energy data for delivery multicopters~\cite{rodrigues2021dataset} would allow this. (ii) Sensors and faults are simulated, and the BMS is assumed to identify cell offsets and $R_0$ online. (iii) One map, one horizon and 20 seeds per cell were used; effects smaller than the reported intervals cannot be excluded. (iv) The fleet includes 450-kg passenger eVTOLs in 20-m corridors next to 6-kg drones, which is not a realistic campus mix. (v) Wind changes airspeed and power but does not displace the drones. (vi) Health telemetry is trusted; a drone that falsely reports CRITICAL would obtain right of way, and protecting health reports in the way W-MSR protects positions is open. (vii) ADMM is used as a mitigation layer with a convexified, per-tick separation constraint and provides no formal guarantee. (viii) Earlier experiments with the project's first, three-corridor engine are not reported, because that engine evaluated separation horizontally and its results were superseded.
"""

conclusion = r"""%======================================================================
\section{Conclusion}\label{sec:conclusion}
This paper connected the battery management system of each drone to the traffic manager of a drone fleet. A 1-RC pack model with weakest-cell energy, an EKF on state of charge, polarisation voltage and capacity, and a chance-constrained feasibility test with a voltage-sag check feed every onboard and fleet-level decision. The traffic controller uses the same state for right of way, endurance-ordered pad arbitration and bounded energy-margin weights in consensus ADMM. In 460 paired-seed runs on a campus corridor network, the estimator was calibrated and never optimistic in nominal flight, and the chance-constrained check traded in-flight diversions for pre-flight holds without losing deliveries; health-aware arbitration and weighting brought no measurable benefit in the tested scenarios and, in one run, a hold-short placement that led to a forced landing, and a threshold-based thermal response proved too slow at 44~$^\circ$C. Future work will calibrate the models on flight data, add predictive thermal and energy specifications to the STL monitor, protect health telemetry against falsification, and test the fleet-level mechanisms in scenarios where landing capacity and energy margins are genuinely scarce.
"""

tex = open(paths.MANUSCRIPT / "masooda_paper_template.tex").read()
tex = tex.replace("%%ABSTRACT%%", abstract).replace("%%RESULTS%%", results).replace("%%DISCUSSION%%", discussion).replace("%%CONCLUSION%%", conclusion)
import re
tex = re.sub(r"\\input\{(tab_s\d)\.tex\}", lambda m: open(paths.TABLES / f"{m.group(1)}.tex").read().replace("\\", "\\"), tex)
tex = tex.replace(r"\thanks{Code and simulator: \url{", r"\thanks{Code and simulator: \protect\url{")
open(paths.MANUSCRIPT / "masooda_paper.tex", "w").write(tex)
print("ok")
