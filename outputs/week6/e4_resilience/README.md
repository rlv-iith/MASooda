# E4 — Resilience under attack: three architectures

> **PROVISIONAL — pre-bug-fix results.** Metric and attack code is still being fixed.

Objective (Table 10): compare resilience under attack — hierarchical / centralized / decentralized-undefended,
one agent falsifies its reported position from t = 60 s.

## Setup
- Matrices: e4, e4_offset (57 unique runs); seeds [42, 43, 44, 45, 46]; N = [60]
- Commit `285920f04b0213b0a66c759be8aa05a5e340c090-dirty`, config hash `e4509b11210199a7`, generated 2026-11-07T00:53:41+0530
- Hardware: Windows 11, Intel64 Family 6 Model 154 Stepping 3, GenuineIntel, 16 logical CPUs; Python 3.14.3, numpy 2.5.3, matplotlib 3.11.2
- Wall time of the last run invocation: 0.441 s (runs resumed from earlier invocations are not re-timed)
- Identical initial conditions per (seed, N): yes
- Duration 180 s, N = 60. Attack: config `attack` (mode constant, default offset
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
| centralized | False | 0.3333 ± 0 (n=5) | 117.4 ± 64 (n=5) | 3.037 ± 1.2 (n=5) | -1.83 ± 0.78 (n=5) |
| decentralized_undefended | False | 0.3333 ± 0 (n=5) | 0 ± 0 (n=5) | n/a | 0.04458 ± 0.043 (n=5) |
| hierarchical | False | 0.3211 ± 0.024 (n=5) | 1777 ± 5.7 (n=5) | n/a | -7.996 ± 0.0075 (n=5) |

## Results — attack on, by offset
<!-- table src=summary.csv group_by=architecture,attack_offset_m metrics=throughput_per_s,safety_violation_ticks,mean_recovery_time_s,min_robustness_m,post_attack_violation_ticks where=attack_enabled:True -->
| architecture | offset (m) | throughput (agents/s) | violation ticks | mean recovery (s) | min ρ (m) | post-attack viol. ticks |
|---|---|---|---|---|---|---|
| centralized | 5 | 0.3333 ± 0 (n=3) | 127.3 ± 1.7e+02 (n=3) | 3.253 ± 3.3 (n=3) | -2.057 ± 1.7 (n=3) | 0 ± 0 (n=3) |
| centralized | 10 | 0.3333 ± 0 (n=3) | 127.3 ± 1.7e+02 (n=3) | 3.253 ± 3.3 (n=3) | -2.057 ± 1.7 (n=3) | 0 ± 0 (n=3) |
| centralized | 25 | 0.3333 ± 0 (n=5) | 141 ± 50 (n=5) | 3.209 ± 1.1 (n=5) | -2.477 ± 0.39 (n=5) | 23.6 ± 27 (n=5) |
| centralized | 50 | 0.3333 ± 0 (n=3) | 127.3 ± 1.7e+02 (n=3) | 3.253 ± 3.3 (n=3) | -2.057 ± 1.7 (n=3) | 0 ± 0 (n=3) |
| decentralized_undefended | 5 | 0.3333 ± 0 (n=3) | 0 ± 0 (n=3) | n/a | 0.03697 ± 0.066 (n=3) | 0 ± 0 (n=3) |
| decentralized_undefended | 10 | 0.3333 ± 0 (n=3) | 0 ± 0 (n=3) | n/a | 0.03333 ± 0.055 (n=3) | 0 ± 0 (n=3) |
| decentralized_undefended | 25 | 0.3333 ± 0 (n=5) | 75.8 ± 2.1e+02 (n=5) | 19.05 (n=1) | -0.09303 ± 0.37 (n=5) | 75.8 ± 2.1e+02 (n=5) |
| decentralized_undefended | 50 | 0.3333 ± 0 (n=3) | 431.7 ± 1.1e+03 (n=3) | 0.5 (n=1) | -0.6522 ± 1.7 (n=3) | 431.7 ± 1.1e+03 (n=3) |
| hierarchical | 5 | 0.3074 ± 0.056 (n=3) | 1777 ± 10 (n=3) | n/a | -7.991 ± 0.017 (n=3) | 1201 ± 0 (n=3) |
| hierarchical | 10 | 0.313 ± 0.088 (n=3) | 1777 ± 10 (n=3) | n/a | -7.994 ± 0.011 (n=3) | 1201 ± 0 (n=3) |
| hierarchical | 25 | 0.31 ± 0.03 (n=5) | 1777 ± 5.7 (n=5) | n/a | -7.997 ± 0.0051 (n=5) | 1201 ± 0 (n=5) |
| hierarchical | 50 | 0.3204 ± 0.029 (n=3) | 1777 ± 10 (n=3) | n/a | -7.991 ± 0.017 (n=3) | 1201 ± 0 (n=3) |

## Paired attack effect (on − off, same seed)
<!-- table src=attack_effect_summary.csv group_by=architecture metrics=throughput_per_s,safety_violation_ticks,mean_recovery_time_s,min_robustness_m,post_attack_violation_ticks_on -->
| architecture | throughput (agents/s) | violation ticks | mean recovery (s) | min ρ (m) | post-attack viol. ticks (on) |
|---|---|---|---|---|---|
| centralized | 0 ± 0 (n=5) | 23.6 ± 27 (n=5) | 0.1717 ± 0.2 (n=5) | -0.646 ± 0.78 (n=5) | 23.6 ± 27 (n=5) |
| decentralized_undefended | 0 ± 0 (n=5) | 75.8 ± 2.1e+02 (n=5) | n/a | -0.1376 ± 0.38 (n=5) | 75.8 ± 2.1e+02 (n=5) |
| hierarchical | -0.01111 ± 0.043 (n=5) | 0 ± 0 (n=5) | n/a | -0.0009314 ± 0.01 (n=5) | 1201 ± 0 (n=5) |

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
- architecture=centralized, attack_enabled=True, attack_offset_m=5.0: safety_violation_ticks: std/mean=0.54 > 0.5
- architecture=centralized, attack_enabled=True, attack_offset_m=10.0: safety_violation_ticks: std/mean=0.54 > 0.5
- architecture=centralized, attack_enabled=True, attack_offset_m=50.0: safety_violation_ticks: std/mean=0.54 > 0.5
- architecture=decentralized_undefended, attack_enabled=False, attack_offset_m=nan: min_robustness_m: std/mean=0.78 > 0.5
- architecture=decentralized_undefended, attack_enabled=True, attack_offset_m=5.0: min_robustness_m: std/mean=0.72 > 0.5
- architecture=decentralized_undefended, attack_enabled=True, attack_offset_m=10.0: min_robustness_m: std/mean=0.66 > 0.5
- architecture=decentralized_undefended, attack_enabled=True, attack_offset_m=25.0: safety_violation_ticks: std/mean=2.24 > 0.5; min_robustness_m: std/mean=3.23 > 0.5
- architecture=decentralized_undefended, attack_enabled=True, attack_offset_m=50.0: safety_violation_ticks: std/mean=0.98 > 0.5; min_robustness_m: std/mean=1.08 > 0.5

## Observations
- hierarchical: violation ticks 1777 (off) vs 1777 (on); min ρ -7.996 vs -7.997 m; throughput 0.3211 vs 0.31 agents/s.
- centralized: violation ticks 117.4 (off) vs 141 (on); min ρ -1.83 vs -2.477 m; throughput 0.3333 vs 0.3333 agents/s.
- decentralized_undefended: violation ticks 0 (off) vs 75.8 (on); min ρ 0.04458 vs -0.09303 m; throughput 0.3333 vs 0.3333 agents/s.
