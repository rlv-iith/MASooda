# E3 — Emergency priority compliance

> **PROVISIONAL — pre-bug-fix results.** Metric and attack code is still being fixed.

Objective (Table 10): evaluate priority compliance — hierarchical, an emergency agent injected into traffic.

## Setup
- Matrices: e3 (24 unique runs); seeds [42, 43, 44]; N = [30, 45, 60, 75]
- Commit `285920f04b0213b0a66c759be8aa05a5e340c090-dirty`, config hash `e4509b11210199a7`, generated 2026-11-07T00:47:31+0530
- Hardware: Windows 11, Intel64 Family 6 Model 154 Stepping 3, GenuineIntel, 16 logical CPUs; Python 3.14.3, numpy 2.5.3, matplotlib 3.11.2
- Wall time of the last run invocation: 142.5 s (runs resumed from earlier invocations are not re-timed)
- Identical initial conditions per (seed, N): yes
- Duration 180 s, no attack, no link failure. Each (N, seed) has an emergency run and a paired control run
  (`emergency_control = True`) with the same fleet in which the same agent stays an ordinary DELIVERY agent.

## Method
`simulation/priority_metrics.py` is used as-is (its compliance definition is owned by P4 and may change):
`inject_emergency` makes the rear-most agent EMERGENCY (priority 0), `baseline_copy` builds the control fleet,
`PriorityLogger` records compliance and arrival times, and `priority_summary` gives emergency delay (arrival time
− nominal free-flow time), time saved vs the control run, and the mean delay imposed on the other agents. A value
is n/a when the agent did not reach the exit in the run. Tables: mean ± 95% CI half-width over seeds.

## Results — priority (pairs.csv → summary.csv)
<!-- table src=summary.csv group_by=num_agents metrics=priority_compliance_rate,emergency_delay_s,time_saved_vs_control_s,lower_priority_delay_s -->
| N | compliance rate | emergency delay (s) | time saved vs control (s) | imposed delay (s) |
|---|---|---|---|---|
| 30 | 1 ± 0 (n=3) | 8.739 ± 22 (n=3) | 22.5 ± 34 (n=3) | -0.1534 ± 19 (n=3) |
| 45 | 0.01099 ± 0 (n=3) | 8.739 ± 22 (n=3) | 9.95 ± 1.6e+02 (n=2) | 0.5853 ± 20 (n=3) |
| 60 | 0 ± 0 (n=3) | 8.739 ± 22 (n=3) | 35.63 ± 53 (n=3) | 1.806 ± 12 (n=3) |
| 75 | 0 ± 0 (n=3) | 8.739 ± 22 (n=3) | 11.4 ± 37 (n=3) | -0.5267 ± 12 (n=3) |

## Results — travel times
<!-- table src=summary.csv group_by=num_agents metrics=emergency_travel_time_s,control_travel_time_s -->
| N | emergency travel (s) | control travel (s) |
|---|---|---|
| 30 | 125.2 ± 23 (n=3) | 147.7 ± 17 (n=3) |
| 45 | 125.2 ± 23 (n=3) | 138.8 ± 74 (n=2) |
| 60 | 125.2 ± 23 (n=3) | 160.8 ± 41 (n=3) |
| 75 | 125.2 ± 23 (n=3) | 136.6 ± 25 (n=3) |

## Results — fleet metrics, emergency vs control runs
<!-- table src=runs_summary.csv group_by=num_agents,emergency_control metrics=throughput_per_s,safety_violation_ticks,min_robustness_m,admm_events -->
| N | control run | throughput (agents/s) | violation ticks | min ρ (m) | ADMM events |
|---|---|---|---|---|---|
| 30 | False | 0.1593 ± 0.032 (n=3) | 654.3 ± 3.8e+02 (n=3) | -7.989 ± 0.017 (n=3) | 993.3 ± 1.2e+02 (n=3) |
| 30 | True | 0.1648 ± 0.008 (n=3) | 23.33 ± 61 (n=3) | -0.3441 ± 0.56 (n=3) | 1016 ± 1.3e+02 (n=3) |
| 45 | False | 0.2241 ± 0.056 (n=3) | 752 ± 2.1e+02 (n=3) | -7.945 ± 0.054 (n=3) | 1467 ± 75 (n=3) |
| 45 | True | 0.2407 ± 0.04 (n=3) | 86.33 ± 1.1e+02 (n=3) | -1.296 ± 2.7 (n=3) | 1540 ± 1.9e+02 (n=3) |
| 60 | False | 0.3111 ± 0.096 (n=3) | 1744 ± 1.4e+02 (n=3) | -7.994 ± 0.0052 (n=3) | 1978 ± 1.4e+02 (n=3) |
| 60 | True | 0.313 ± 0.029 (n=3) | 1781 ± 25 (n=3) | -7.995 ± 0.0079 (n=3) | 2071 ± 3.7e+02 (n=3) |
| 75 | False | 0.3981 ± 0.042 (n=3) | 1778 ± 14 (n=3) | -7.999 ± 0.0015 (n=3) | 2522 ± 3.6e+02 (n=3) |
| 75 | True | 0.3944 ± 0.055 (n=3) | 1783 ± 24 (n=3) | -7.983 ± 0.071 (n=3) | 2484 ± 2.4e+02 (n=3) |

## Figures
- [e3_compliance_vs_N](../figures/e3_compliance_vs_N.png)
- [e3_emergency_delay_vs_N](../figures/e3_emergency_delay_vs_N.png)
- [e3_imposed_delay_vs_N](../figures/e3_imposed_delay_vs_N.png)
- [e3_emergency_track_N60](../figures/e3_emergency_track_N60.png)

## Weak groups
Criteria: n < 3 or std/mean > 0.5 on priority_compliance_rate, emergency_delay_s, lower_priority_delay_s. Listed only, not re-run.
- num_agents=30: emergency_delay_s: std/mean=1.03 > 0.5; lower_priority_delay_s: std/mean=48.60 > 0.5
- num_agents=45: emergency_delay_s: std/mean=1.03 > 0.5; lower_priority_delay_s: std/mean=13.94 > 0.5
- num_agents=60: emergency_delay_s: std/mean=1.03 > 0.5; lower_priority_delay_s: std/mean=2.57 > 0.5
- num_agents=75: emergency_delay_s: std/mean=1.03 > 0.5; lower_priority_delay_s: std/mean=9.54 > 0.5

## Observations
- Compliance rate by N: N=30: 1, N=45: 0.01099, N=60: 0, N=75: 0.
- Emergency delay vs nominal (s) by N: N=30: 8.739, N=45: 8.739, N=60: 8.739, N=75: 8.739.
- Time saved vs control (s) by N: N=30: 22.5, N=45: 9.95, N=60: 35.63, N=75: 11.4.
- Delay imposed on others (s) by N: N=30: -0.1534, N=45: 0.5853, N=60: 1.806, N=75: -0.5267.
