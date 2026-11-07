# E6 — Graceful degradation (overseer link failure)

> **PROVISIONAL — pre-bug-fix results.** Metric and attack code is still being fixed.

Objective (Table 10): evaluate graceful degradation — hierarchical, overseer communication link dropped.

## Setup
- Matrices: e6 (6 unique runs); seeds [42, 43, 44]; N = [60]
- Commit `285920f04b0213b0a66c759be8aa05a5e340c090-dirty`, config hash `e4509b11210199a7`, generated 2026-11-07T00:48:28+0530
- Hardware: Windows 11, Intel64 Family 6 Model 154 Stepping 3, GenuineIntel, 16 logical CPUs; Python 3.14.3, numpy 2.5.3, matplotlib 3.11.2
- Wall time of the last run invocation: 50.82 s (runs resumed from earlier invocations are not re-timed)
- Identical initial conditions per (seed, N): yes
- Duration 180 s, no attack. Link-failure runs drop the overseer link from 90 s to 120 s
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
| False | 1777 ± 10 (n=3) | 1 ± 0 (n=3) | 0.3185 ± 0.064 (n=3) | -7.994 ± 0.019 (n=3) |
| True | 1777 ± 10 (n=3) | 1 ± 0 (n=3) | 0.3185 ± 0.064 (n=3) | -7.994 ± 0.019 (n=3) |

<!-- table src=summary.csv group_by=link_failure metrics=overseer_failures,overseer_dropped,max_directive_staleness_s -->
| link failure | overseer failures | requests dropped | max directive age (s) |
|---|---|---|---|
| False | 0 ± 0 (n=3) | 0 ± 0 (n=3) | 1.9 ± 0 (n=3) |
| True | 0 ± 0 (n=3) | 15 ± 0 (n=3) | 31.9 ± 0 (n=3) |

## Results — degradation per seed
| seed | violations (up) | violations (failure) | score | directive refreshed in outage | max directive age in outage (s) | max position diff (m) | first divergence (s) |
|---|---|---|---|---|---|---|---|
| 42 | 1774 | 1774 | 1 | False | 31.8 | 0 | n/a |
| 43 | 1776 | 1776 | 1 | False | 31.8 | 0 | n/a |
| 44 | 1782 | 1782 | 1 | False | 31.8 | 0 | n/a |

<!-- table src=degradation_summary.csv group_by=num_agents metrics=graceful_degradation_score,directive_age_max_in_outage_s,max_position_diff_m,first_divergence_s -->
| N | degradation score | max directive age in outage (s) | max position diff (m) | first divergence (s) |
|---|---|---|---|---|
| 60 | 1 ± 0 (n=3) | 31.8 ± 0 (n=3) | 0 ± 0 (n=3) | n/a |

## Outage behaviour (reported, not changed)
- In every failure run the directive age rose without a reset inside 90–120 s: directives **stopped refreshing** during the outage (the cached directive was used).
- Trajectories of the normal and failure runs are **identical** for every seed (max position difference 0 m) — the outage had no effect on motion in these runs.

## Figures
- [e6_violations_normal_vs_failure](../figures/e6_violations_normal_vs_failure.png)
- [e6_throughput_normal_vs_failure](../figures/e6_throughput_normal_vs_failure.png)
- [e6_directive_age_timeline](../figures/e6_directive_age_timeline.png)
- [e6_degradation_score](../figures/e6_degradation_score.png)

## Weak groups
- None: every group has at least 3 values and std/mean ≤ 0.5.

## Observations
- Violation ticks: 1777 with the link up vs 1777 with the link failure (mean over seeds).
- Throughput: 0.3185 vs 0.3185 agents/s.
- Overseer requests dropped: 0 vs 15; max directive age 1.9 vs 31.9 s.
- Degradation score per seed: seed 42: 1, seed 43: 1, seed 44: 1.
