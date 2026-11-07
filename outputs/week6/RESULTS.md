# MASooda — Week 6 results

> **PROVISIONAL — pre-bug-fix results.**

- Commit: `285920f04b0213b0a66c759be8aa05a5e340c090-dirty`
- Config hash: `e4509b11210199a7`
- Generated: 2026-11-07 01:23:37 +0530
- Provisional: True
- Experiments present: E1, E2, E3, E4, E5, E6
- Total runs (current config): 141
- Total wall time recorded in the manifests: 7.94 min (last invocation per folder; resumed runs are not re-timed)

ADMM is reported as conflict *mitigation*; none of these numbers is a safety guarantee. Tables are copied from each experiment README, which generates them from its summary CSV (mean ± 95% CI half-width, n = runs with a value; n/a = not observed).

## E1 — Evaluate ADMM scaling

**Table 10:** Hierarchical; 30/45/60/75 agents, no attack; owner P2.  
**Setup (manifest):** matrices e1, e1_iter; seeds [42, 43, 44]; N = [30, 45, 60, 75]; 24 runs in runs.csv; commit `285920f04b0213b0a66c759be8aa05a5e340c090-dirty`; [README](e1_admm_scaling/README.md)

### Results — scaling with N (iteration limit 50)

<!-- table src=summary.csv group_by=num_agents metrics=admm_solver_calls,admm_iter_mean,admm_iter_p95,admm_converged_frac,admm_solve_ms_mean,admm_time_per_tick_ms,admm_max_group_size,safety_violation_ticks,min_robustness_m where=admm_max_iterations:50 -->
| N | solver calls | mean iterations | p95 iterations | converged frac. | mean solve (ms) | ADMM time / tick (ms) | max group | violation ticks | min ρ (m) |
|---|---|---|---|---|---|---|---|---|---|
| 30 | 946.7 ± 3e+02 (n=3) | 10.15 ± 0.45 (n=3) | 14.33 ± 1.4 (n=3) | 1 ± 0 (n=3) | 0.9006 ± 0.17 (n=3) | 0.771 ± 0.094 (n=3) | 5 ± 0 (n=3) | 826 ± 7.1e+02 (n=3) | -7.987 ± 0.018 (n=3) |
| 45 | 1360 ± 5.3e+02 (n=3) | 10.46 ± 0.31 (n=3) | 15 ± 0 (n=3) | 1 ± 0 (n=3) | 1.057 ± 0.088 (n=3) | 1.214 ± 0.3 (n=3) | 5 ± 0 (n=3) | 1704 ± 3.2e+02 (n=3) | -7.966 ± 0.069 (n=3) |
| 60 | 1809 ± 6.4e+02 (n=3) | 10.02 ± 0.14 (n=3) | 15 ± 0 (n=3) | 1 ± 0 (n=3) | 1.029 ± 0.12 (n=3) | 1.549 ± 0.29 (n=3) | 5 ± 0 (n=3) | 1777 ± 10 (n=3) | -7.994 ± 0.019 (n=3) |
| 75 | 2126 ± 3.3e+02 (n=3) | 9.964 ± 0.52 (n=3) | 15 ± 0 (n=3) | 1 ± 0 (n=3) | 0.9972 ± 0.14 (n=3) | 1.785 ± 0.13 (n=3) | 5 ± 0 (n=3) | 1782 ± 14 (n=3) | -7.998 ± 0.0044 (n=3) |

### Results — iteration limit (N = 60)

<!-- table src=summary.csv group_by=admm_max_iterations metrics=admm_solver_calls,admm_iter_mean,admm_converged_frac,admm_time_per_tick_ms,safety_violation_ticks where=num_agents:60 -->
| iter. limit | solver calls | mean iterations | converged frac. | ADMM time / tick (ms) | violation ticks |
|---|---|---|---|---|---|
| 5 | 1817 ± 6.4e+02 (n=3) | 4.93 ± 0.1 (n=3) | 0.07013 ± 0.1 (n=3) | 1.06 ± 0.17 (n=3) | 1777 ± 10 (n=3) |
| 10 | 1815 ± 6.5e+02 (n=3) | 9.154 ± 0.77 (n=3) | 0.7779 ± 0.14 (n=3) | 1.48 ± 0.31 (n=3) | 1777 ± 10 (n=3) |
| 20 | 1812 ± 6.3e+02 (n=3) | 10 ± 0.19 (n=3) | 0.9971 ± 0.012 (n=3) | 1.587 ± 0.27 (n=3) | 1777 ± 9 (n=3) |
| 50 | 1809 ± 6.4e+02 (n=3) | 10.02 ± 0.14 (n=3) | 1 ± 0 (n=3) | 1.549 ± 0.29 (n=3) | 1777 ± 10 (n=3) |
| 100 | 1809 ± 6.4e+02 (n=3) | 10.02 ± 0.14 (n=3) | 1 ± 0 (n=3) | 1.599 ± 0.21 (n=3) | 1777 ± 10 (n=3) |

### Figures

- [e1_iterations_vs_N](figures/e1_iterations_vs_N.png)
- [e1_solve_time_vs_N](figures/e1_solve_time_vs_N.png)
- [e1_convergence_rate_vs_N](figures/e1_convergence_rate_vs_N.png)
- [e1_time_per_tick_vs_N](figures/e1_time_per_tick_vs_N.png)
- [e1_convergence_vs_iteration_limit](figures/e1_convergence_vs_iteration_limit.png)
- [e1_iterations_distribution](figures/e1_iterations_distribution.png)

### Observations

- Mean iterations per solver call: 10.15 at N=30 and 9.964 at N=75.
- Solver calls per run: 946.7 at N=30 and 2126 at N=75.
- ADMM time per tick: 0.771 ms at N=30 and 1.785 ms at N=75.
- Converged fraction by N: N=30: 1, N=45: 1, N=60: 1, N=75: 1.
- At N=60, converged fraction is 0.07013 at limit 5, 0.7779 at limit 10, 0.9971 at limit 20, 1 at limit 50, 1 at limit 100.

## E2 — Evaluate corridor merge success and throughput

**Table 10:** Hierarchical; Three corridors with varying density; owner P3.  
**Setup (manifest):** matrices e2; seeds [42, 43, 44]; N = [30, 45, 60, 75]; 12 runs in runs.csv; commit `285920f04b0213b0a66c759be8aa05a5e340c090-dirty`; [README](e2_formation/README.md)

### Results — merges

<!-- table src=summary.csv group_by=num_agents metrics=merge_attempts,merge_success,merge_failed,not_reached,merge_success_rate -->
| N | merge attempts | successes | failed | not reached | success rate |
|---|---|---|---|---|---|
| 30 | 21 ± 5 (n=3) | 0 ± 0 (n=3) | 21 ± 5 (n=3) | 0 ± 0 (n=3) | 0 ± 0 (n=3) |
| 45 | 29.67 ± 12 (n=3) | 0 ± 0 (n=3) | 29.67 ± 12 (n=3) | 0 ± 0 (n=3) | 0 ± 0 (n=3) |
| 60 | 40 ± 6.6 (n=3) | 0.3333 ± 1.4 (n=3) | 39.67 ± 7.2 (n=3) | 0 ± 0 (n=3) | 0.008547 ± 0.037 (n=3) |
| 75 | 47.67 ± 7.2 (n=3) | 0 ± 0 (n=3) | 47.67 ± 7.2 (n=3) | 0 ± 0 (n=3) | 0 ± 0 (n=3) |

### Results — throughput and utilisation (occupancy / capacity)

<!-- table src=summary.csv group_by=num_agents metrics=throughput_per_s,arrivals,safety_violation_ticks,util_mean_c0,util_mean_c1,util_mean_c2,util_peak_c0,util_peak_c1,util_peak_c2,ticks_over_capacity -->
| N | throughput (agents/s) | arrivals | violation ticks | util_mean_c0 | util_mean_c1 | util_mean_c2 | util_peak_c0 | util_peak_c1 | util_peak_c2 | ticks over capacity |
|---|---|---|---|---|---|---|---|---|---|---|
| 30 | 0.1556 ± 0.048 (n=3) | 28 ± 8.6 (n=3) | 826 ± 7.1e+02 (n=3) | 0.5253 ± 0.011 (n=3) | 0.6549 ± 0.096 (n=3) | 0.4825 ± 0.078 (n=3) | 0.6889 ± 0.096 (n=3) | 0.8889 ± 0.25 (n=3) | 0.6667 ± 0 (n=3) | 0 ± 0 (n=3) |
| 45 | 0.2333 ± 0.072 (n=3) | 42 ± 13 (n=3) | 1704 ± 3.2e+02 (n=3) | 0.7745 ± 0.044 (n=3) | 0.9523 ± 0.13 (n=3) | 0.7452 ± 0.056 (n=3) | 1 ± 0 (n=3) | 1.133 ± 0.17 (n=3) | 1 ± 0 (n=3) | 299 ± 9.1e+02 (n=3) |
| 60 | 0.3185 ± 0.064 (n=3) | 57.33 ± 11 (n=3) | 1777 ± 10 (n=3) | 1.03 ± 0.12 (n=3) | 1.277 ± 0.32 (n=3) | 0.9821 ± 0.19 (n=3) | 1.333 ± 0 (n=3) | 1.533 ± 0.44 (n=3) | 1.333 ± 0 (n=3) | 3143 ± 4.9e+02 (n=3) |
| 75 | 0.4167 ± 0 (n=3) | 75 ± 0 (n=3) | 1782 ± 14 (n=3) | 1.288 ± 0.036 (n=3) | 1.595 ± 0.15 (n=3) | 1.299 ± 0.055 (n=3) | 1.667 ± 0 (n=3) | 1.822 ± 0.25 (n=3) | 1.667 ± 0 (n=3) | 4540 ± 2.3e+02 (n=3) |

### Figures

- [e2_merge_success_vs_N](figures/e2_merge_success_vs_N.png)
- [e2_throughput_vs_N](figures/e2_throughput_vs_N.png)
- [e2_utilization_vs_N](figures/e2_utilization_vs_N.png)
- [e2_utilization_heatmap_N60](figures/e2_utilization_heatmap_N60.png)
- [e2_formation_snapshot_N60](figures/e2_formation_snapshot_N60.png)

### Observations

- Merge success rate by N: N=30: 0, N=45: 0, N=60: 0.008547, N=75: 0.
- Merge attempts per run by N: N=30: 21, N=45: 29.67, N=60: 40, N=75: 47.67.
- Throughput (arrivals/s) by N: N=30: 0.1556, N=45: 0.2333, N=60: 0.3185, N=75: 0.4167.
- At N=75, peak utilisation per corridor: c0: 1.667, c1: 1.822, c2: 1.667; ticks over capacity: 4540.

## E3 — Evaluate priority compliance

**Table 10:** Hierarchical; Emergency agent injected into traffic; owner P4.  
**Setup (manifest):** matrices e3; seeds [42, 43, 44]; N = [30, 45, 60, 75]; 24 runs in runs.csv; commit `285920f04b0213b0a66c759be8aa05a5e340c090-dirty`; [README](e3_priority/README.md)

### Results — priority (pairs.csv → summary.csv)

<!-- table src=summary.csv group_by=num_agents metrics=priority_compliance_rate,emergency_delay_s,time_saved_vs_control_s,lower_priority_delay_s -->
| N | compliance rate | emergency delay (s) | time saved vs control (s) | imposed delay (s) |
|---|---|---|---|---|
| 30 | 1 ± 0 (n=3) | 8.739 ± 22 (n=3) | 22.5 ± 34 (n=3) | -0.1534 ± 19 (n=3) |
| 45 | 0.01099 ± 0 (n=3) | 8.739 ± 22 (n=3) | 9.95 ± 1.6e+02 (n=2) | 0.5853 ± 20 (n=3) |
| 60 | 0 ± 0 (n=3) | 8.739 ± 22 (n=3) | 35.63 ± 53 (n=3) | 1.806 ± 12 (n=3) |
| 75 | 0 ± 0 (n=3) | 8.739 ± 22 (n=3) | 11.4 ± 37 (n=3) | -0.5267 ± 12 (n=3) |

### Results — travel times

<!-- table src=summary.csv group_by=num_agents metrics=emergency_travel_time_s,control_travel_time_s -->
| N | emergency travel (s) | control travel (s) |
|---|---|---|
| 30 | 125.2 ± 23 (n=3) | 147.7 ± 17 (n=3) |
| 45 | 125.2 ± 23 (n=3) | 138.8 ± 74 (n=2) |
| 60 | 125.2 ± 23 (n=3) | 160.8 ± 41 (n=3) |
| 75 | 125.2 ± 23 (n=3) | 136.6 ± 25 (n=3) |

### Results — fleet metrics, emergency vs control runs

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

### Figures

- [e3_compliance_vs_N](figures/e3_compliance_vs_N.png)
- [e3_emergency_delay_vs_N](figures/e3_emergency_delay_vs_N.png)
- [e3_imposed_delay_vs_N](figures/e3_imposed_delay_vs_N.png)
- [e3_emergency_track_N60](figures/e3_emergency_track_N60.png)

### Observations

- Compliance rate by N: N=30: 1, N=45: 0.01099, N=60: 0, N=75: 0.
- Emergency delay vs nominal (s) by N: N=30: 8.739, N=45: 8.739, N=60: 8.739, N=75: 8.739.
- Time saved vs control (s) by N: N=30: 22.5, N=45: 9.95, N=60: 35.63, N=75: 11.4.
- Delay imposed on others (s) by N: N=30: -0.1534, N=45: 0.5853, N=60: 1.806, N=75: -0.5267.

## E4 — Compare resilience under attack

**Table 10:** Hierarchical / Centralized / Decentralized-undefended; One agent falsifies position at t = 60 s; owner P5.  
**Setup (manifest):** matrices e4, e4_offset; seeds [42, 43, 44, 45, 46]; N = [60]; 57 runs in runs.csv; commit `285920f04b0213b0a66c759be8aa05a5e340c090-dirty`; [README](e4_resilience/README.md)

### Results — attack off

<!-- table src=summary.csv group_by=architecture,attack_enabled metrics=throughput_per_s,safety_violation_ticks,mean_recovery_time_s,min_robustness_m where=attack_enabled:False -->
| architecture | attack | throughput (agents/s) | violation ticks | mean recovery (s) | min ρ (m) |
|---|---|---|---|---|---|
| centralized | False | 0.3333 ± 0 (n=5) | 117.4 ± 64 (n=5) | 3.037 ± 1.2 (n=5) | -1.83 ± 0.78 (n=5) |
| decentralized_undefended | False | 0.3333 ± 0 (n=5) | 0 ± 0 (n=5) | n/a | 0.04458 ± 0.043 (n=5) |
| hierarchical | False | 0.3211 ± 0.024 (n=5) | 1777 ± 5.7 (n=5) | n/a | -7.996 ± 0.0075 (n=5) |

### Results — attack on, by offset

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

### Notes

### Does the attack have a measurable effect?
- hierarchical: **no measurable effect of the attack** — for all four metrics the 95% CI of the paired difference includes 0 (or the difference is exactly 0).
- centralized: **no measurable effect of the attack** — for all four metrics the 95% CI of the paired difference includes 0 (or the difference is exactly 0).
- decentralized_undefended: **no measurable effect of the attack** — for all four metrics the 95% CI of the paired difference includes 0 (or the difference is exactly 0).

### Figures

- [e4_main_comparison](figures/e4_main_comparison.png)
- [e4_attack_effect](figures/e4_attack_effect.png)
- [e4_robustness_timeseries](figures/e4_robustness_timeseries.png)
- [e4_offset_sensitivity](figures/e4_offset_sensitivity.png)

### Observations

- hierarchical: violation ticks 1777 (off) vs 1777 (on); min ρ -7.996 vs -7.997 m; throughput 0.3211 vs 0.31 agents/s.
- centralized: violation ticks 117.4 (off) vs 141 (on); min ρ -1.83 vs -2.477 m; throughput 0.3333 vs 0.3333 agents/s.
- decentralized_undefended: violation ticks 0 (off) vs 75.8 (on); min ρ 0.04458 vs -0.09303 m; throughput 0.3333 vs 0.3333 agents/s.

## E5 — Evaluate STL robustness

**Table 10:** All evaluated architectures; Same scenarios as E1–E4; owner P6.  
**Setup (manifest):** matrices ; seeds [42, 43, 44, 45, 46]; N = [30, 45, 60, 75]; 18 runs in runs.csv; commit `285920f04b0213b0a66c759be8aa05a5e340c090-dirty`; [README](e5_stl/README.md)

### Results — nominal runs pooled across experiments (one run per architecture, N, seed)

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

### Results — every scenario / condition

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

### Figures

- [e5_robustness_distribution](figures/e5_robustness_distribution.png)
- [e5_violation_fraction_vs_N](figures/e5_violation_fraction_vs_N.png)
- [e5_recovery_time](figures/e5_recovery_time.png)
- [e5_robustness_heatmap](figures/e5_robustness_heatmap.png)

### Observations

- Hierarchical: violating fraction N=30: 0.4586, N=45: 0.946, N=60: 0.9868, N=75: 0.9893.
- Centralized: violating fraction N=30: 0.03109, N=45: 0.03183, N=60: 0.06519, N=75: 0.1022.
- Decentralized (undefended): violating fraction N=30: 0, N=45: 0, N=60: 0, N=75: 0.

## E6 — Evaluate graceful degradation

**Table 10:** Hierarchical; Overseer communication link dropped; owner P4 + P1.  
**Setup (manifest):** matrices e6; seeds [42, 43, 44]; N = [60]; 6 runs in runs.csv; commit `285920f04b0213b0a66c759be8aa05a5e340c090-dirty`; [README](e6_degradation/README.md)

### Results — link up vs link failure

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

### Results — degradation per seed

| seed | violations (up) | violations (failure) | score | directive refreshed in outage | max directive age in outage (s) | max position diff (m) | first divergence (s) |
|---|---|---|---|---|---|---|---|
| 42 | 1774 | 1774 | 1 | False | 31.8 | 0 | n/a |
| 43 | 1776 | 1776 | 1 | False | 31.8 | 0 | n/a |
| 44 | 1782 | 1782 | 1 | False | 31.8 | 0 | n/a |

<!-- table src=degradation_summary.csv group_by=num_agents metrics=graceful_degradation_score,directive_age_max_in_outage_s,max_position_diff_m,first_divergence_s -->
| N | degradation score | max directive age in outage (s) | max position diff (m) | first divergence (s) |
|---|---|---|---|---|
| 60 | 1 ± 0 (n=3) | 31.8 ± 0 (n=3) | 0 ± 0 (n=3) | n/a |

### Notes

- In every failure run the directive age rose without a reset inside 90–120 s: directives **stopped refreshing** during the outage (the cached directive was used).
- Trajectories of the normal and failure runs are **identical** for every seed (max position difference 0 m) — the outage had no effect on motion in these runs.

### Figures

- [e6_violations_normal_vs_failure](figures/e6_violations_normal_vs_failure.png)
- [e6_throughput_normal_vs_failure](figures/e6_throughput_normal_vs_failure.png)
- [e6_directive_age_timeline](figures/e6_directive_age_timeline.png)
- [e6_degradation_score](figures/e6_degradation_score.png)

### Observations

- Violation ticks: 1777 with the link up vs 1777 with the link failure (mean over seeds).
- Throughput: 0.3185 vs 0.3185 agents/s.
- Overseer requests dropped: 0 vs 15; max directive age 1.9 vs 31.9 s.
- Degradation score per seed: seed 42: 1, seed 43: 1, seed 44: 1.

## Weak results

Listed only; none was re-run (decision: do not re-run weak groups).

- E1 (admm_max_iterations=5, num_agents=60): admm_converged_frac: std/mean=0.57 > 0.5
- E2 (num_agents=60): merge_success_rate: std/mean=1.73 > 0.5
- E3 (num_agents=30): emergency_delay_s: std/mean=1.03 > 0.5; lower_priority_delay_s: std/mean=48.60 > 0.5
- E3 (num_agents=45): emergency_delay_s: std/mean=1.03 > 0.5; lower_priority_delay_s: std/mean=13.94 > 0.5
- E3 (num_agents=60): emergency_delay_s: std/mean=1.03 > 0.5; lower_priority_delay_s: std/mean=2.57 > 0.5
- E3 (num_agents=75): emergency_delay_s: std/mean=1.03 > 0.5; lower_priority_delay_s: std/mean=9.54 > 0.5
- E4 (architecture=centralized, attack_enabled=True, attack_offset_m=5.0): safety_violation_ticks: std/mean=0.54 > 0.5
- E4 (architecture=centralized, attack_enabled=True, attack_offset_m=10.0): safety_violation_ticks: std/mean=0.54 > 0.5
- E4 (architecture=centralized, attack_enabled=True, attack_offset_m=50.0): safety_violation_ticks: std/mean=0.54 > 0.5
- E4 (architecture=decentralized_undefended, attack_enabled=False, attack_offset_m=nan): min_robustness_m: std/mean=0.78 > 0.5
- E4 (architecture=decentralized_undefended, attack_enabled=True, attack_offset_m=5.0): min_robustness_m: std/mean=0.72 > 0.5
- E4 (architecture=decentralized_undefended, attack_enabled=True, attack_offset_m=10.0): min_robustness_m: std/mean=0.66 > 0.5
- E4 (architecture=decentralized_undefended, attack_enabled=True, attack_offset_m=25.0): safety_violation_ticks: std/mean=2.24 > 0.5; min_robustness_m: std/mean=3.23 > 0.5
- E4 (architecture=decentralized_undefended, attack_enabled=True, attack_offset_m=50.0): safety_violation_ticks: std/mean=0.98 > 0.5; min_robustness_m: std/mean=1.08 > 0.5

## README table check

- Every README table matches its summary CSV.

## Proposed headline figures (report and slides) — *proposed, please confirm*

- [e4_main_comparison](figures/e4_main_comparison.png) — E4 headline: three architectures, attack off vs on (throughput, violations, recovery, min robustness)
- [e4_robustness_timeseries](figures/e4_robustness_timeseries.png) — E4: robustness over time with the attack onset — the resilience story in one plot
- [e1_iterations_vs_N](figures/e1_iterations_vs_N.png) — E1: ADMM effort vs fleet size
- [e1_convergence_vs_iteration_limit](figures/e1_convergence_vs_iteration_limit.png) — E1: convergence vs iteration limit
- [e2_merge_success_vs_N](figures/e2_merge_success_vs_N.png) — E2: corridor merge success vs density
- [e3_emergency_delay_vs_N](figures/e3_emergency_delay_vs_N.png) — E3: emergency-agent delay vs density
- [e5_violation_fraction_vs_N](figures/e5_violation_fraction_vs_N.png) — E5: STL violating fraction per architecture vs N
- [e6_directive_age_timeline](figures/e6_directive_age_timeline.png) — E6: directive age through the overseer outage
