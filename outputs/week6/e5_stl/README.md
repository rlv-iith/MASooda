# E5 — STL robustness across all evaluated architectures

> **PROVISIONAL — pre-bug-fix results.** Metric and attack code is still being fixed.

Objective (Table 10): evaluate STL robustness — all evaluated architectures, same scenarios as E1–E4. Built from the
saved runs of E1–E4; only the missing nominal centralized / decentralized runs were simulated
(18 runs; missing before: centralized N=30, centralized N=45, centralized N=75, decentralized_undefended N=30, decentralized_undefended N=45, decentralized_undefended N=75).

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
| centralized | 30 | -1.715 ± 3.2 (n=3) | 0.3521 ± 0.71 (n=3) | 0.03109 ± 0.029 (n=3) | 3 ± 2.5 (n=3) | 2.403 ± 2.6 (n=3) |
| centralized | 45 | -2.174 ± 2.2 (n=3) | 0.2391 ± 0.42 (n=3) | 0.03183 ± 0.028 (n=3) | 2.667 ± 1.4 (n=3) | 2.522 ± 0.86 (n=3) |
| centralized | 60 | -1.83 ± 0.78 (n=5) | -0.3066 ± 0.5 (n=5) | 0.06519 ± 0.035 (n=5) | 4.2 ± 1 (n=5) | 3.037 ± 1.2 (n=5) |
| centralized | 75 | -2.789 ± 4.1 (n=3) | -0.554 ± 0.23 (n=3) | 0.1022 ± 0.045 (n=3) | 5.333 ± 5.7 (n=3) | 4.171 ± 4.2 (n=3) |
| decentralized_undefended | 30 | 0.1401 ± 0.22 (n=3) | 3.478 ± 0.38 (n=3) | 0 ± 0 (n=3) | 0 ± 0 (n=3) | n/a |
| decentralized_undefended | 45 | 0.03697 ± 0.066 (n=3) | 1.797 ± 0.065 (n=3) | 0 ± 0 (n=3) | 0 ± 0 (n=3) | n/a |
| decentralized_undefended | 60 | 0.04458 ± 0.043 (n=5) | 1.692 ± 0.24 (n=5) | 0 ± 0 (n=5) | 0 ± 0 (n=5) | n/a |
| decentralized_undefended | 75 | 0.03697 ± 0.066 (n=3) | 1.592 ± 0.062 (n=3) | 0 ± 0 (n=3) | 0 ± 0 (n=3) | n/a |
| hierarchical | 30 | -7.987 ± 0.018 (n=3) | -7.354 ± 0.88 (n=3) | 0.4586 ± 0.4 (n=3) | 3 ± 2.5 (n=3) | 27.89 ± 12 (n=3) |
| hierarchical | 45 | -7.966 ± 0.069 (n=3) | -7.654 ± 0.6 (n=3) | 0.946 ± 0.18 (n=3) | 2.333 ± 5.7 (n=3) | 25.07 (n=1) |
| hierarchical | 60 | -7.996 ± 0.0075 (n=5) | -7.835 ± 0.15 (n=5) | 0.9868 ± 0.0032 (n=5) | 1 ± 0 (n=5) | n/a |
| hierarchical | 75 | -7.998 ± 0.0044 (n=3) | -7.925 ± 0.15 (n=3) | 0.9893 ± 0.0076 (n=3) | 1 ± 0 (n=3) | n/a |

## Results — every scenario / condition
<!-- table src=stl_summary.csv group_by=scenario,condition,architecture,num_agents metrics=min_robustness_m,p5_robustness_m,violation_fraction,max_recovery_time_s -->
| scenario | condition | architecture | N | min ρ (m) | p5 ρ (m) | violating frac. | max recovery (s) |
|---|---|---|---|---|---|---|---|
| e1_admm_scaling | ADMM limit 10 | hierarchical | 60 | -7.991 ± 0.017 (n=3) | -7.775 ± 0.14 (n=3) | 0.9869 ± 0.0057 (n=3) | n/a |
| e1_admm_scaling | ADMM limit 100 | hierarchical | 60 | -7.994 ± 0.019 (n=3) | -7.817 ± 0.34 (n=3) | 0.9869 ± 0.0057 (n=3) | n/a |
| e1_admm_scaling | ADMM limit 20 | hierarchical | 60 | -7.994 ± 0.019 (n=3) | -7.814 ± 0.34 (n=3) | 0.9867 ± 0.005 (n=3) | n/a |
| e1_admm_scaling | ADMM limit 5 | hierarchical | 60 | -7.991 ± 0.017 (n=3) | -7.775 ± 0.017 (n=3) | 0.9869 ± 0.0057 (n=3) | n/a |
| e1_admm_scaling | nominal | hierarchical | 30 | -7.987 ± 0.018 (n=3) | -7.354 ± 0.88 (n=3) | 0.4586 ± 0.4 (n=3) | 61.67 ± 1.8 (n=3) |
| e1_admm_scaling | nominal | hierarchical | 45 | -7.966 ± 0.069 (n=3) | -7.654 ± 0.6 (n=3) | 0.946 ± 0.18 (n=3) | 75.2 (n=1) |
| e1_admm_scaling | nominal | hierarchical | 60 | -7.994 ± 0.019 (n=3) | -7.817 ± 0.34 (n=3) | 0.9869 ± 0.0057 (n=3) | n/a |
| e1_admm_scaling | nominal | hierarchical | 75 | -7.998 ± 0.0044 (n=3) | -7.925 ± 0.15 (n=3) | 0.9893 ± 0.0076 (n=3) | n/a |
| e2_formation | nominal | hierarchical | 30 | -7.987 ± 0.018 (n=3) | -7.354 ± 0.88 (n=3) | 0.4586 ± 0.4 (n=3) | 61.67 ± 1.8 (n=3) |
| e2_formation | nominal | hierarchical | 45 | -7.966 ± 0.069 (n=3) | -7.654 ± 0.6 (n=3) | 0.946 ± 0.18 (n=3) | 75.2 (n=1) |
| e2_formation | nominal | hierarchical | 60 | -7.994 ± 0.019 (n=3) | -7.817 ± 0.34 (n=3) | 0.9869 ± 0.0057 (n=3) | n/a |
| e2_formation | nominal | hierarchical | 75 | -7.998 ± 0.0044 (n=3) | -7.925 ± 0.15 (n=3) | 0.9893 ± 0.0076 (n=3) | n/a |
| e3_priority | emergency | hierarchical | 30 | -7.989 ± 0.017 (n=3) | -6.659 ± 0.53 (n=3) | 0.3633 ± 0.21 (n=3) | 41.77 ± 2.9 (n=3) |
| e3_priority | emergency | hierarchical | 45 | -7.945 ± 0.054 (n=3) | -6.462 ± 0.38 (n=3) | 0.4175 ± 0.12 (n=3) | 36.3 ± 9.5 (n=3) |
| e3_priority | emergency | hierarchical | 60 | -7.994 ± 0.0052 (n=3) | -7.78 ± 0.047 (n=3) | 0.9682 ± 0.075 (n=3) | 93.1 (n=1) |
| e3_priority | emergency | hierarchical | 75 | -7.999 ± 0.0015 (n=3) | -7.8 ± 0.18 (n=3) | 0.9872 ± 0.0077 (n=3) | n/a |
| e3_priority | emergency control | hierarchical | 30 | -0.3441 ± 0.56 (n=3) | 0.6373 ± 1 (n=3) | 0.01296 ± 0.034 (n=3) | 1.767 ± 3.1 (n=3) |
| e3_priority | emergency control | hierarchical | 45 | -1.296 ± 2.7 (n=3) | 0.02426 ± 1 (n=3) | 0.04794 ± 0.059 (n=3) | 4.167 ± 2.2 (n=3) |
| e3_priority | emergency control | hierarchical | 60 | -7.995 ± 0.0079 (n=3) | -7.771 ± 0.16 (n=3) | 0.9887 ± 0.014 (n=3) | n/a |
| e3_priority | emergency control | hierarchical | 75 | -7.983 ± 0.071 (n=3) | -7.858 ± 0.42 (n=3) | 0.99 ± 0.013 (n=3) | n/a |
| e4_resilience | attack 10 m | centralized | 60 | -2.057 ± 1.7 (n=3) | -0.3882 ± 1.3 (n=3) | 0.0707 ± 0.095 (n=3) | 6.833 ± 6.5 (n=3) |
| e4_resilience | attack 10 m | decentralized_undefended | 60 | 0.03333 ± 0.055 (n=3) | 0.7646 ± 1.7 (n=3) | 0 ± 0 (n=3) | n/a |
| e4_resilience | attack 10 m | hierarchical | 60 | -7.994 ± 0.011 (n=3) | -7.778 ± 0.021 (n=3) | 0.9869 ± 0.0057 (n=3) | n/a |
| e4_resilience | attack 25 m | centralized | 60 | -2.477 ± 0.39 (n=5) | -0.4595 ± 0.43 (n=5) | 0.07829 ± 0.028 (n=5) | 6.02 ± 2.8 (n=5) |
| e4_resilience | attack 25 m | decentralized_undefended | 60 | -0.09303 ± 0.37 (n=5) | 0.9985 ± 1.2 (n=5) | 0.04209 ± 0.12 (n=5) | 28.3 (n=1) |
| e4_resilience | attack 25 m | hierarchical | 60 | -7.997 ± 0.0051 (n=5) | -7.811 ± 0.12 (n=5) | 0.9868 ± 0.0032 (n=5) | n/a |
| e4_resilience | attack 5 m | centralized | 60 | -2.057 ± 1.7 (n=3) | -0.3882 ± 1.3 (n=3) | 0.0707 ± 0.095 (n=3) | 6.833 ± 6.5 (n=3) |
| e4_resilience | attack 5 m | decentralized_undefended | 60 | 0.03697 ± 0.066 (n=3) | 1.227 ± 0.71 (n=3) | 0 ± 0 (n=3) | n/a |
| e4_resilience | attack 5 m | hierarchical | 60 | -7.991 ± 0.017 (n=3) | -7.752 ± 0.16 (n=3) | 0.9869 ± 0.0057 (n=3) | n/a |
| e4_resilience | attack 50 m | centralized | 60 | -2.057 ± 1.7 (n=3) | -0.3882 ± 1.3 (n=3) | 0.0707 ± 0.095 (n=3) | 6.833 ± 6.5 (n=3) |
| e4_resilience | attack 50 m | decentralized_undefended | 60 | -0.6522 ± 1.7 (n=3) | -0.2492 ± 3.2 (n=3) | 0.2397 ± 0.59 (n=3) | 0.5 (n=1) |
| e4_resilience | attack 50 m | hierarchical | 60 | -7.991 ± 0.017 (n=3) | -7.765 ± 0.087 (n=3) | 0.9869 ± 0.0057 (n=3) | n/a |
| e4_resilience | nominal | centralized | 60 | -1.83 ± 0.78 (n=5) | -0.3066 ± 0.5 (n=5) | 0.06519 ± 0.035 (n=5) | 6.02 ± 2.8 (n=5) |
| e4_resilience | nominal | decentralized_undefended | 60 | 0.04458 ± 0.043 (n=5) | 1.692 ± 0.24 (n=5) | 0 ± 0 (n=5) | n/a |
| e4_resilience | nominal | hierarchical | 60 | -7.996 ± 0.0075 (n=5) | -7.835 ± 0.15 (n=5) | 0.9868 ± 0.0032 (n=5) | n/a |
| e5_stl | nominal | centralized | 30 | -1.715 ± 3.2 (n=3) | 0.3521 ± 0.71 (n=3) | 0.03109 ± 0.029 (n=3) | 3.467 ± 4.8 (n=3) |
| e5_stl | nominal | centralized | 45 | -2.174 ± 2.2 (n=3) | 0.2391 ± 0.42 (n=3) | 0.03183 ± 0.028 (n=3) | 4.567 ± 3.8 (n=3) |
| e5_stl | nominal | centralized | 75 | -2.789 ± 4.1 (n=3) | -0.554 ± 0.23 (n=3) | 0.1022 ± 0.045 (n=3) | 11.13 ± 8.7 (n=3) |
| e5_stl | nominal | decentralized_undefended | 30 | 0.1401 ± 0.22 (n=3) | 3.478 ± 0.38 (n=3) | 0 ± 0 (n=3) | n/a |
| e5_stl | nominal | decentralized_undefended | 45 | 0.03697 ± 0.066 (n=3) | 1.797 ± 0.065 (n=3) | 0 ± 0 (n=3) | n/a |
| e5_stl | nominal | decentralized_undefended | 75 | 0.03697 ± 0.066 (n=3) | 1.592 ± 0.062 (n=3) | 0 ± 0 (n=3) | n/a |

## Figures
- [e5_robustness_distribution](../figures/e5_robustness_distribution.png)
- [e5_violation_fraction_vs_N](../figures/e5_violation_fraction_vs_N.png)
- [e5_recovery_time](../figures/e5_recovery_time.png)
- [e5_robustness_heatmap](../figures/e5_robustness_heatmap.png)

## Observations
- Hierarchical: violating fraction N=30: 0.4586, N=45: 0.946, N=60: 0.9868, N=75: 0.9893.
- Centralized: violating fraction N=30: 0.03109, N=45: 0.03183, N=60: 0.06519, N=75: 0.1022.
- Decentralized (undefended): violating fraction N=30: 0, N=45: 0, N=60: 0, N=75: 0.
