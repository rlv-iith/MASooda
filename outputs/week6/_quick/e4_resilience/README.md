# E4 — Resilience under attack: three architectures

> **PROVISIONAL — pre-bug-fix results.** Metric and attack code is still being fixed.

Objective (Table 10): compare resilience under attack — hierarchical / centralized / decentralized-undefended,
one agent falsifies its reported position from t = 60 s.

## Setup
- Matrices: e4, e4_offset (15 unique runs); seeds [42]; N = [12]
- Commit `285920f04b0213b0a66c759be8aa05a5e340c090-dirty`, config hash `e4509b11210199a7`, generated 2026-11-07T01:08:16+0530
- Hardware: Windows 11, Intel64 Family 6 Model 154 Stepping 3, GenuineIntel, 16 logical CPUs; Python 3.14.3, numpy 2.5.3, matplotlib 3.11.2
- Wall time of the last run invocation: 3.301 s (runs resumed from earlier invocations are not re-timed)
- Identical initial conditions per (seed, N): yes
- Duration 20 s, N = 60. Attack: config `attack` (mode constant, default offset
  25 m, start 60 s); offset sweep
  [5.0, 10.0, 25.0, 50.0] m on seeds 42–44.
- Identical initial conditions per (seed, N), checked with `check_identical_conditions`:
  yes — All groups with matching (seed, num_agents) have identical initial conditions.

## Method
Per run: throughput, safety-violation ticks (ρ < 0), recovery times (ρ back above 0 for ≥ 1 s), min robustness
(`verification.metrics`), reports dropped by the defence, and post-attack violation ticks (ticks at or after the
attack start with ρ < 0, from the saved series). The paired attack effect is attack-on (default offset) minus
attack-off for the same architecture and seed (`attack_effect.csv`). Recovery time is n/a for runs without a
violation episode. Tables: mean ± 95% CI half-width over seeds.

## Results — attack off
<!-- table src=summary.csv group_by=architecture,attack_enabled metrics=throughput_per_s,safety_violation_ticks,mean_recovery_time_s,min_robustness_m where=attack_enabled:False -->
| architecture | attack | throughput (agents/s) | violation ticks | mean recovery (s) | min ρ (m) |
|---|---|---|---|---|---|
| centralized | False | n/a | 0 (n=1) | n/a | 1.474 (n=1) |
| decentralized_undefended | False | n/a | 0 (n=1) | n/a | 1.567 (n=1) |
| hierarchical | False | n/a | 0 (n=1) | n/a | 1.567 (n=1) |

## Results — attack on, by offset
<!-- table src=summary.csv group_by=architecture,attack_offset_m metrics=throughput_per_s,safety_violation_ticks,mean_recovery_time_s,min_robustness_m,post_attack_violation_ticks where=attack_enabled:True -->
| architecture | offset (m) | throughput (agents/s) | violation ticks | mean recovery (s) | min ρ (m) | post-attack viol. ticks |
|---|---|---|---|---|---|---|
| centralized | 5 | n/a | 0 (n=1) | n/a | 1.474 (n=1) | 0 (n=1) |
| centralized | 10 | n/a | 0 (n=1) | n/a | 1.474 (n=1) | 0 (n=1) |
| centralized | 25 | n/a | 0 (n=1) | n/a | 1.474 (n=1) | 0 (n=1) |
| centralized | 50 | n/a | 0 (n=1) | n/a | 1.474 (n=1) | 0 (n=1) |
| decentralized_undefended | 5 | n/a | 0 (n=1) | n/a | 1.567 (n=1) | 0 (n=1) |
| decentralized_undefended | 10 | n/a | 0 (n=1) | n/a | 1.567 (n=1) | 0 (n=1) |
| decentralized_undefended | 25 | n/a | 0 (n=1) | n/a | 1.567 (n=1) | 0 (n=1) |
| decentralized_undefended | 50 | n/a | 0 (n=1) | n/a | 1.567 (n=1) | 0 (n=1) |
| hierarchical | 5 | n/a | 0 (n=1) | n/a | 1.567 (n=1) | 0 (n=1) |
| hierarchical | 10 | n/a | 0 (n=1) | n/a | 1.567 (n=1) | 0 (n=1) |
| hierarchical | 25 | n/a | 0 (n=1) | n/a | 1.567 (n=1) | 0 (n=1) |
| hierarchical | 50 | n/a | 0 (n=1) | n/a | 1.567 (n=1) | 0 (n=1) |

## Paired attack effect (on − off, same seed)
<!-- table src=attack_effect_summary.csv group_by=architecture metrics=throughput_per_s,safety_violation_ticks,mean_recovery_time_s,min_robustness_m,post_attack_violation_ticks_on -->
| architecture | throughput (agents/s) | violation ticks | mean recovery (s) | min ρ (m) | post-attack viol. ticks (on) |
|---|---|---|---|---|---|
| centralized | n/a | 0 (n=1) | n/a | 0 (n=1) | 0 (n=1) |
| decentralized_undefended | n/a | 0 (n=1) | n/a | 0 (n=1) | 0 (n=1) |
| hierarchical | n/a | 0 (n=1) | n/a | 0 (n=1) | 0 (n=1) |

### Does the attack have a measurable effect?
- hierarchical: **no measurable effect of the attack** — for all four metrics the 95% CI of the paired difference includes 0 (or the difference is exactly 0).
- centralized: **no measurable effect of the attack** — for all four metrics the 95% CI of the paired difference includes 0 (or the difference is exactly 0).
- decentralized_undefended: **no measurable effect of the attack** — for all four metrics the 95% CI of the paired difference includes 0 (or the difference is exactly 0).

## Figures
- [e4_main_comparison](../figures/e4_main_comparison.png)
- [e4_attack_effect](../figures/e4_attack_effect.png)
- [e4_robustness_timeseries](../figures/e4_robustness_timeseries.png)
- [e4_offset_sensitivity](../figures/e4_offset_sensitivity.png)

## Weak groups
Criteria: n < 3 or std/mean > 0.5 on throughput_per_s, safety_violation_ticks, min_robustness_m. Listed only, not re-run.
- architecture=centralized, attack_enabled=False, attack_offset_m=nan: throughput_per_s: n=0 < 3; safety_violation_ticks: n=1 < 3; min_robustness_m: n=1 < 3
- architecture=centralized, attack_enabled=True, attack_offset_m=5.0: throughput_per_s: n=0 < 3; safety_violation_ticks: n=1 < 3; min_robustness_m: n=1 < 3
- architecture=centralized, attack_enabled=True, attack_offset_m=10.0: throughput_per_s: n=0 < 3; safety_violation_ticks: n=1 < 3; min_robustness_m: n=1 < 3
- architecture=centralized, attack_enabled=True, attack_offset_m=25.0: throughput_per_s: n=0 < 3; safety_violation_ticks: n=1 < 3; min_robustness_m: n=1 < 3
- architecture=centralized, attack_enabled=True, attack_offset_m=50.0: throughput_per_s: n=0 < 3; safety_violation_ticks: n=1 < 3; min_robustness_m: n=1 < 3
- architecture=decentralized_undefended, attack_enabled=False, attack_offset_m=nan: throughput_per_s: n=0 < 3; safety_violation_ticks: n=1 < 3; min_robustness_m: n=1 < 3
- architecture=decentralized_undefended, attack_enabled=True, attack_offset_m=5.0: throughput_per_s: n=0 < 3; safety_violation_ticks: n=1 < 3; min_robustness_m: n=1 < 3
- architecture=decentralized_undefended, attack_enabled=True, attack_offset_m=10.0: throughput_per_s: n=0 < 3; safety_violation_ticks: n=1 < 3; min_robustness_m: n=1 < 3
- architecture=decentralized_undefended, attack_enabled=True, attack_offset_m=25.0: throughput_per_s: n=0 < 3; safety_violation_ticks: n=1 < 3; min_robustness_m: n=1 < 3
- architecture=decentralized_undefended, attack_enabled=True, attack_offset_m=50.0: throughput_per_s: n=0 < 3; safety_violation_ticks: n=1 < 3; min_robustness_m: n=1 < 3
- architecture=hierarchical, attack_enabled=False, attack_offset_m=nan: throughput_per_s: n=0 < 3; safety_violation_ticks: n=1 < 3; min_robustness_m: n=1 < 3
- architecture=hierarchical, attack_enabled=True, attack_offset_m=5.0: throughput_per_s: n=0 < 3; safety_violation_ticks: n=1 < 3; min_robustness_m: n=1 < 3
- architecture=hierarchical, attack_enabled=True, attack_offset_m=10.0: throughput_per_s: n=0 < 3; safety_violation_ticks: n=1 < 3; min_robustness_m: n=1 < 3
- architecture=hierarchical, attack_enabled=True, attack_offset_m=25.0: throughput_per_s: n=0 < 3; safety_violation_ticks: n=1 < 3; min_robustness_m: n=1 < 3
- architecture=hierarchical, attack_enabled=True, attack_offset_m=50.0: throughput_per_s: n=0 < 3; safety_violation_ticks: n=1 < 3; min_robustness_m: n=1 < 3

## Observations
- hierarchical: violation ticks 0 (off) vs 0 (on); min ρ 1.567 vs 1.567 m; throughput n/a vs n/a agents/s.
- centralized: violation ticks 0 (off) vs 0 (on); min ρ 1.474 vs 1.474 m; throughput n/a vs n/a agents/s.
- decentralized_undefended: violation ticks 0 (off) vs 0 (on); min ρ 1.567 vs 1.567 m; throughput n/a vs n/a agents/s.
