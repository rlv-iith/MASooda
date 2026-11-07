# E2 — Corridor formation, merge success, throughput and utilisation

> **PROVISIONAL — pre-bug-fix results.** Metric and attack code is still being fixed.

Objective (Table 10): evaluate corridor merge success and throughput — hierarchical, three corridors with
varying density. The N = 45–75 rows in `docs/p3_week5_formation.md` are not backed by a CSV and are not used.

## Setup
- Matrices: e2 (12 unique runs); seeds [42, 43, 44]; N = [30, 45, 60, 75]
- Commit `285920f04b0213b0a66c759be8aa05a5e340c090-dirty`, config hash `e4509b11210199a7`, generated 2026-11-07T00:44:38+0530
- Hardware: Windows 11, Intel64 Family 6 Model 154 Stepping 3, GenuineIntel, 16 logical CPUs; Python 3.14.3, numpy 2.5.3, matplotlib 3.11.2
- Wall time of the last run invocation: 73.7 s (runs resumed from earlier invocations are not re-timed)
- Identical initial conditions per (seed, N): yes
- Duration 180 s, no attack, no link failure; 3 corridors, capacity 15 agents each;
  merge zone x = [700.0, 800.0] m.

## Method
`local_behavior/formation_metrics.py` as-is: `merge_outcomes` classifies each agent at the end of the merge zone
(success / failed / not reached / no merge needed); merge attempts = success + failed; success rate is n/a when a run
has no attempt. `corridor_utilization` gives mean and peak occupancy / capacity per corridor and the ticks any
corridor exceeds capacity. Throughput = arrivals / duration (n/a with no arrivals). Tables: mean ± 95% CI
half-width over seeds.

## Results — merges
<!-- table src=summary.csv group_by=num_agents metrics=merge_attempts,merge_success,merge_failed,not_reached,merge_success_rate -->
| N | merge attempts | successes | failed | not reached | success rate |
|---|---|---|---|---|---|
| 30 | 21 ± 5 (n=3) | 0 ± 0 (n=3) | 21 ± 5 (n=3) | 0 ± 0 (n=3) | 0 ± 0 (n=3) |
| 45 | 29.67 ± 12 (n=3) | 0 ± 0 (n=3) | 29.67 ± 12 (n=3) | 0 ± 0 (n=3) | 0 ± 0 (n=3) |
| 60 | 40 ± 6.6 (n=3) | 0.3333 ± 1.4 (n=3) | 39.67 ± 7.2 (n=3) | 0 ± 0 (n=3) | 0.008547 ± 0.037 (n=3) |
| 75 | 47.67 ± 7.2 (n=3) | 0 ± 0 (n=3) | 47.67 ± 7.2 (n=3) | 0 ± 0 (n=3) | 0 ± 0 (n=3) |

## Results — throughput and utilisation (occupancy / capacity)
<!-- table src=summary.csv group_by=num_agents metrics=throughput_per_s,arrivals,safety_violation_ticks,util_mean_c0,util_mean_c1,util_mean_c2,util_peak_c0,util_peak_c1,util_peak_c2,ticks_over_capacity -->
| N | throughput (agents/s) | arrivals | violation ticks | util_mean_c0 | util_mean_c1 | util_mean_c2 | util_peak_c0 | util_peak_c1 | util_peak_c2 | ticks over capacity |
|---|---|---|---|---|---|---|---|---|---|---|
| 30 | 0.1556 ± 0.048 (n=3) | 28 ± 8.6 (n=3) | 826 ± 7.1e+02 (n=3) | 0.5253 ± 0.011 (n=3) | 0.6549 ± 0.096 (n=3) | 0.4825 ± 0.078 (n=3) | 0.6889 ± 0.096 (n=3) | 0.8889 ± 0.25 (n=3) | 0.6667 ± 0 (n=3) | 0 ± 0 (n=3) |
| 45 | 0.2333 ± 0.072 (n=3) | 42 ± 13 (n=3) | 1704 ± 3.2e+02 (n=3) | 0.7745 ± 0.044 (n=3) | 0.9523 ± 0.13 (n=3) | 0.7452 ± 0.056 (n=3) | 1 ± 0 (n=3) | 1.133 ± 0.17 (n=3) | 1 ± 0 (n=3) | 299 ± 9.1e+02 (n=3) |
| 60 | 0.3185 ± 0.064 (n=3) | 57.33 ± 11 (n=3) | 1777 ± 10 (n=3) | 1.03 ± 0.12 (n=3) | 1.277 ± 0.32 (n=3) | 0.9821 ± 0.19 (n=3) | 1.333 ± 0 (n=3) | 1.533 ± 0.44 (n=3) | 1.333 ± 0 (n=3) | 3143 ± 4.9e+02 (n=3) |
| 75 | 0.4167 ± 0 (n=3) | 75 ± 0 (n=3) | 1782 ± 14 (n=3) | 1.288 ± 0.036 (n=3) | 1.595 ± 0.15 (n=3) | 1.299 ± 0.055 (n=3) | 1.667 ± 0 (n=3) | 1.822 ± 0.25 (n=3) | 1.667 ± 0 (n=3) | 4540 ± 2.3e+02 (n=3) |

## Figures
- [e2_merge_success_vs_N](../figures/e2_merge_success_vs_N.png)
- [e2_throughput_vs_N](../figures/e2_throughput_vs_N.png)
- [e2_utilization_vs_N](../figures/e2_utilization_vs_N.png)
- [e2_utilization_heatmap_N60](../figures/e2_utilization_heatmap_N60.png)
- [e2_formation_snapshot_N60](../figures/e2_formation_snapshot_N60.png)

## Weak groups
Criteria: n < 3 or std/mean > 0.5 on merge_success_rate, throughput_per_s. Listed only, not re-run.
- num_agents=60: merge_success_rate: std/mean=1.73 > 0.5

## Observations
- Merge success rate by N: N=30: 0, N=45: 0, N=60: 0.008547, N=75: 0.
- Merge attempts per run by N: N=30: 21, N=45: 29.67, N=60: 40, N=75: 47.67.
- Throughput (arrivals/s) by N: N=30: 0.1556, N=45: 0.2333, N=60: 0.3185, N=75: 0.4167.
- At N=75, peak utilisation per corridor: c0: 1.667, c1: 1.822, c2: 1.667; ticks over capacity: 4540.
