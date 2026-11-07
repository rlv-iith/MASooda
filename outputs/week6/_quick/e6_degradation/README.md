# E6 — Graceful degradation (overseer link failure)

> **PROVISIONAL — pre-bug-fix results.** Metric and attack code is still being fixed.

Objective (Table 10): evaluate graceful degradation — hierarchical, overseer communication link dropped.

## Setup
- Matrices: e6 (2 unique runs); seeds [42]; N = [12]
- Commit `285920f04b0213b0a66c759be8aa05a5e340c090-dirty`, config hash `e4509b11210199a7`, generated 2026-11-07T01:08:18+0530
- Hardware: Windows 11, Intel64 Family 6 Model 154 Stepping 3, GenuineIntel, 16 logical CPUs; Python 3.14.3, numpy 2.5.3, matplotlib 3.11.2
- Wall time of the last run invocation: 1.309 s (runs resumed from earlier invocations are not re-timed)
- Identical initial conditions per (seed, N): yes
- Duration 20 s, no attack. Link-failure runs drop the overseer link from 90 s to 120 s
  (config `overseer.link_failure`); each seed has a paired link-up run.

## Method
Per-run counters come from the engine (`overseer_failures`, `overseer_dropped`, `max_directive_staleness_s`); the
per-tick age of the cached directive comes from `simulation/telemetry.py` (`telemetry/*.csv`). The graceful
degradation score is `verification.metrics.graceful_degradation_score(violations_failure, violations_normal)`
per seed, used as-is: 1.0 when both runs have 0 violation ticks, ∞ when only the failure run has violations
(∞ is excluded from the mean and counted in n). Trajectory differences use the saved 1 s fleet snapshots.

## Results — link up vs link failure
<!-- table src=summary.csv group_by=link_failure metrics=safety_violation_ticks,violation_episodes,throughput_per_s,min_robustness_m -->
| link failure | violation ticks | episodes | throughput (agents/s) | min ρ (m) |
|---|---|---|---|---|
| False | 0 (n=1) | 0 (n=1) | n/a | 1.567 (n=1) |
| True | 0 (n=1) | 0 (n=1) | n/a | 1.567 (n=1) |

<!-- table src=summary.csv group_by=link_failure metrics=overseer_failures,overseer_dropped,max_directive_staleness_s -->
| link failure | overseer failures | requests dropped | max directive age (s) |
|---|---|---|---|
| False | 0 (n=1) | 0 (n=1) | 1.9 (n=1) |
| True | 0 (n=1) | 0 (n=1) | 1.9 (n=1) |

## Results — degradation per seed
| seed | violations (up) | violations (failure) | score | directive refreshed in outage | max directive age in outage (s) | max position diff (m) | first divergence (s) |
|---|---|---|---|---|---|---|---|
| 42 | 0 | 0 | 1 | n/a | n/a | 0 | n/a |

<!-- table src=degradation_summary.csv group_by=num_agents metrics=graceful_degradation_score,directive_age_max_in_outage_s,max_position_diff_m,first_divergence_s -->
| N | degradation score | max directive age in outage (s) | max position diff (m) | first divergence (s) |
|---|---|---|---|---|
| 12 | 1 (n=1) | n/a | 0 (n=1) | n/a |

## Outage behaviour (reported, not changed)
- The outage window is not covered by these runs (n/a).
- Trajectories of the normal and failure runs are **identical** for every seed (max position difference 0 m) — the outage had no effect on motion in these runs.

## Figures
- [e6_violations_normal_vs_failure](../figures/e6_violations_normal_vs_failure.png)
- [e6_throughput_normal_vs_failure](../figures/e6_throughput_normal_vs_failure.png)
- [e6_directive_age_timeline](../figures/e6_directive_age_timeline.png)
- [e6_degradation_score](../figures/e6_degradation_score.png)

## Weak groups
Criteria: n < 3 or std/mean > 0.5 on safety_violation_ticks, throughput_per_s. Listed only, not re-run.
- link_failure=False: safety_violation_ticks: n=1 < 3; throughput_per_s: n=0 < 3
- link_failure=True: safety_violation_ticks: n=1 < 3; throughput_per_s: n=0 < 3

## Observations
- Violation ticks: 0 with the link up vs 0 with the link failure (mean over seeds).
- Throughput: n/a vs n/a agents/s.
- Overseer requests dropped: 0 vs 0; max directive age 1.9 vs 1.9 s.
- Degradation score per seed: seed 42: 1.
