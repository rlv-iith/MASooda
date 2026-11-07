# E3 — Emergency priority compliance

> **PROVISIONAL — pre-bug-fix results.** Metric and attack code is still being fixed.

Objective (Table 10): evaluate priority compliance — hierarchical, an emergency agent injected into traffic.

## Setup
- Matrices: e3 (2 unique runs); seeds [42]; N = [12]
- Commit `285920f04b0213b0a66c759be8aa05a5e340c090-dirty`, config hash `e4509b11210199a7`, generated 2026-11-07T01:08:12+0530
- Hardware: Windows 11, Intel64 Family 6 Model 154 Stepping 3, GenuineIntel, 16 logical CPUs; Python 3.14.3, numpy 2.5.3, matplotlib 3.11.2
- Wall time of the last run invocation: 1.439 s (runs resumed from earlier invocations are not re-timed)
- Identical initial conditions per (seed, N): yes
- Duration 20 s, no attack, no link failure. Each (N, seed) has an emergency run and a paired control run
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
| 12 | 1 (n=1) | n/a | n/a | n/a |

## Results — travel times
<!-- table src=summary.csv group_by=num_agents metrics=emergency_travel_time_s,control_travel_time_s -->
| N | emergency travel (s) | control travel (s) |
|---|---|---|
| 12 | n/a | n/a |

## Results — fleet metrics, emergency vs control runs
<!-- table src=runs_summary.csv group_by=num_agents,emergency_control metrics=throughput_per_s,safety_violation_ticks,min_robustness_m,admm_events -->
| N | control run | throughput (agents/s) | violation ticks | min ρ (m) | ADMM events |
|---|---|---|---|---|---|
| 12 | False | n/a | 0 (n=1) | 1.567 (n=1) | 0 (n=1) |
| 12 | True | n/a | 0 (n=1) | 1.567 (n=1) | 0 (n=1) |

## Figures
- [e3_compliance_vs_N](../figures/e3_compliance_vs_N.png)
- [e3_emergency_delay_vs_N](../figures/e3_emergency_delay_vs_N.png)
- [e3_imposed_delay_vs_N](../figures/e3_imposed_delay_vs_N.png)
- [e3_emergency_track_N60](../figures/e3_emergency_track_N60.png)

## Weak groups
Criteria: n < 3 or std/mean > 0.5 on priority_compliance_rate, emergency_delay_s, lower_priority_delay_s. Listed only, not re-run.
- num_agents=12: priority_compliance_rate: n=1 < 3; emergency_delay_s: n=0 < 3; lower_priority_delay_s: n=0 < 3

## Observations
- Compliance rate by N: N=12: 1.
- Emergency delay vs nominal (s) by N: N=12: n/a.
- Time saved vs control (s) by N: N=12: n/a.
- Delay imposed on others (s) by N: N=12: n/a.
