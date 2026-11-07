# E5 — STL robustness across all evaluated architectures

> **PROVISIONAL — pre-bug-fix results.** Metric and attack code is still being fixed.

Objective (Table 10): evaluate STL robustness — all evaluated architectures, same scenarios as E1–E4. Built from the
saved runs of E1–E4; only the missing nominal centralized / decentralized runs were simulated
(0 runs; missing before: none).

## Specification
- Safety specification: **G (d_ij(t) ≥ d_min)** for every pair i ≠ j, with d_min = 8 m
  (config `safety.minimum_separation_meters`).
- Robustness ρ(t) = min over pairs of d_ij(t) − d_min, as implemented by `verification.metrics.robustness_series`
  (read, not changed). **Separation definition currently implemented:** planar distance in (x, y) only, over *all*
  pairs, regardless of altitude layer (agents on different layers are still counted).
- Per run: min ρ, 5th-percentile ρ, fraction of ticks with ρ < 0, violation episodes and recovery times
  (`verification.metrics`: recovery = ρ back above 0 and staying positive for ≥ 1 s). n/a when a run has no episode.

## Results — nominal runs pooled across experiments (one run per architecture, N, seed)
<!-- table src=stl_summary_pooled.csv group_by=architecture,num_agents metrics=min_robustness_m,p5_robustness_m,violation_fraction,violation_episodes,mean_recovery_time_s -->
| architecture | N | min ρ (m) | p5 ρ (m) | violating frac. | episodes | mean recovery (s) |
|---|---|---|---|---|---|---|
| centralized | 12 | 1.474 (n=1) | 1.577 (n=1) | 0 (n=1) | 0 (n=1) | n/a |
| decentralized_undefended | 12 | 1.567 (n=1) | 1.572 (n=1) | 0 (n=1) | 0 (n=1) | n/a |
| hierarchical | 12 | 1.567 (n=1) | 1.572 (n=1) | 0 (n=1) | 0 (n=1) | n/a |

## Results — every scenario / condition
<!-- table src=stl_summary.csv group_by=scenario,condition,architecture,num_agents metrics=min_robustness_m,p5_robustness_m,violation_fraction,max_recovery_time_s -->
| scenario | condition | architecture | N | min ρ (m) | p5 ρ (m) | violating frac. | max recovery (s) |
|---|---|---|---|---|---|---|---|
| e1_admm_scaling | ADMM limit 10 | hierarchical | 12 | 1.567 (n=1) | 1.572 (n=1) | 0 (n=1) | n/a |
| e1_admm_scaling | ADMM limit 100 | hierarchical | 12 | 1.567 (n=1) | 1.572 (n=1) | 0 (n=1) | n/a |
| e1_admm_scaling | ADMM limit 20 | hierarchical | 12 | 1.567 (n=1) | 1.572 (n=1) | 0 (n=1) | n/a |
| e1_admm_scaling | ADMM limit 5 | hierarchical | 12 | 1.567 (n=1) | 1.572 (n=1) | 0 (n=1) | n/a |
| e1_admm_scaling | nominal | hierarchical | 12 | 1.567 (n=1) | 1.572 (n=1) | 0 (n=1) | n/a |
| e2_formation | nominal | hierarchical | 12 | 1.567 (n=1) | 1.572 (n=1) | 0 (n=1) | n/a |
| e3_priority | emergency | hierarchical | 12 | 1.567 (n=1) | 1.572 (n=1) | 0 (n=1) | n/a |
| e3_priority | emergency control | hierarchical | 12 | 1.567 (n=1) | 1.572 (n=1) | 0 (n=1) | n/a |
| e4_resilience | attack 10 m | centralized | 12 | 1.474 (n=1) | 1.577 (n=1) | 0 (n=1) | n/a |
| e4_resilience | attack 10 m | decentralized_undefended | 12 | 1.567 (n=1) | 1.572 (n=1) | 0 (n=1) | n/a |
| e4_resilience | attack 10 m | hierarchical | 12 | 1.567 (n=1) | 1.572 (n=1) | 0 (n=1) | n/a |
| e4_resilience | attack 25 m | centralized | 12 | 1.474 (n=1) | 1.577 (n=1) | 0 (n=1) | n/a |
| e4_resilience | attack 25 m | decentralized_undefended | 12 | 1.567 (n=1) | 1.572 (n=1) | 0 (n=1) | n/a |
| e4_resilience | attack 25 m | hierarchical | 12 | 1.567 (n=1) | 1.572 (n=1) | 0 (n=1) | n/a |
| e4_resilience | attack 5 m | centralized | 12 | 1.474 (n=1) | 1.577 (n=1) | 0 (n=1) | n/a |
| e4_resilience | attack 5 m | decentralized_undefended | 12 | 1.567 (n=1) | 1.572 (n=1) | 0 (n=1) | n/a |
| e4_resilience | attack 5 m | hierarchical | 12 | 1.567 (n=1) | 1.572 (n=1) | 0 (n=1) | n/a |
| e4_resilience | attack 50 m | centralized | 12 | 1.474 (n=1) | 1.575 (n=1) | 0 (n=1) | n/a |
| e4_resilience | attack 50 m | decentralized_undefended | 12 | 1.567 (n=1) | 1.572 (n=1) | 0 (n=1) | n/a |
| e4_resilience | attack 50 m | hierarchical | 12 | 1.567 (n=1) | 1.572 (n=1) | 0 (n=1) | n/a |
| e4_resilience | nominal | centralized | 12 | 1.474 (n=1) | 1.577 (n=1) | 0 (n=1) | n/a |
| e4_resilience | nominal | decentralized_undefended | 12 | 1.567 (n=1) | 1.572 (n=1) | 0 (n=1) | n/a |
| e4_resilience | nominal | hierarchical | 12 | 1.567 (n=1) | 1.572 (n=1) | 0 (n=1) | n/a |

## Figures
- [e5_robustness_distribution](../figures/e5_robustness_distribution.png)
- [e5_violation_fraction_vs_N](../figures/e5_violation_fraction_vs_N.png)
- [e5_recovery_time](../figures/e5_recovery_time.png)
- [e5_robustness_heatmap](../figures/e5_robustness_heatmap.png)

## Observations
- Hierarchical: violating fraction N=12: 0.
- Centralized: violating fraction N=12: 0.
- Decentralized (undefended): violating fraction N=12: 0.
