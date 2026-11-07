# E2 — Corridor formation, merge success, throughput and utilisation

> **PROVISIONAL — pre-bug-fix results.** Metric and attack code is still being fixed.

Objective (Table 10): evaluate corridor merge success and throughput — hierarchical, three corridors with
varying density. The N = 45–75 rows in `docs/p3_week5_formation.md` are not backed by a CSV and are not used.

## Setup
- Matrices: e2 (1 unique runs); seeds [42]; N = [12]
- Commit `285920f04b0213b0a66c759be8aa05a5e340c090-dirty`, config hash `e4509b11210199a7`, generated 2026-11-07T01:08:09+0530
- Hardware: Windows 11, Intel64 Family 6 Model 154 Stepping 3, GenuineIntel, 16 logical CPUs; Python 3.14.3, numpy 2.5.3, matplotlib 3.11.2
- Wall time of the last run invocation: 0.974 s (runs resumed from earlier invocations are not re-timed)
- Identical initial conditions per (seed, N): yes
- Duration 20 s, no attack, no link failure; 3 corridors, capacity 15 agents each;
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
| 12 | 0 (n=1) | 0 (n=1) | 0 (n=1) | 12 (n=1) | n/a |

## Results — throughput and utilisation (occupancy / capacity)
<!-- table src=summary.csv group_by=num_agents metrics=throughput_per_s,arrivals,safety_violation_ticks,util_mean_c0,util_mean_c1,util_mean_c2,util_peak_c0,util_peak_c1,util_peak_c2,ticks_over_capacity -->
| N | throughput (agents/s) | arrivals | violation ticks | util_mean_c0 | util_mean_c1 | util_mean_c2 | util_peak_c0 | util_peak_c1 | util_peak_c2 | ticks over capacity |
|---|---|---|---|---|---|---|---|---|---|---|
| 12 | n/a | 0 (n=1) | 0 (n=1) | 0.2667 (n=1) | 0.2667 (n=1) | 0.2667 (n=1) | 0.2667 (n=1) | 0.2667 (n=1) | 0.2667 (n=1) | 0 (n=1) |

## Figures
- [e2_merge_success_vs_N](../figures/e2_merge_success_vs_N.png)
- [e2_throughput_vs_N](../figures/e2_throughput_vs_N.png)
- [e2_utilization_vs_N](../figures/e2_utilization_vs_N.png)
- [e2_utilization_heatmap_N60](../figures/e2_utilization_heatmap_N60.png)
- [e2_formation_snapshot_N60](../figures/e2_formation_snapshot_N60.png)

## Weak groups
Criteria: n < 3 or std/mean > 0.5 on merge_success_rate, throughput_per_s. Listed only, not re-run.
- num_agents=12: merge_success_rate: n=0 < 3; throughput_per_s: n=0 < 3

## Observations
- Merge success rate by N: N=12: n/a.
- Merge attempts per run by N: N=12: 0.
- Throughput (arrivals/s) by N: N=12: n/a.
- At N=12, peak utilisation per corridor: c0: 0.2667, c1: 0.2667, c2: 0.2667; ticks over capacity: 0.
