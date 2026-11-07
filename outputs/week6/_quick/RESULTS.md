# MASooda — Week 6 results

> **PROVISIONAL — pre-bug-fix results.**

- Commit: `285920f04b0213b0a66c759be8aa05a5e340c090-dirty`
- Config hash: `e4509b11210199a7`
- Generated: 2026-11-07 01:08:50 +0530
- Provisional: True
- Experiments present: E1, E2, E3, E4, E5, E6
- Total runs (current config): 25
- Total wall time recorded in the manifests: 0.1518 min (last invocation per folder; resumed runs are not re-timed)

ADMM is reported as conflict *mitigation*; none of these numbers is a safety guarantee. Tables are copied from each experiment README, which generates them from its summary CSV (mean ± 95% CI half-width, n = runs with a value; n/a = not observed).

## E1 — Evaluate ADMM scaling

**Table 10:** Hierarchical; 30/45/60/75 agents, no attack; owner P2.  
**Setup (manifest):** matrices e1, e1_iter; seeds [42]; N = [12]; 5 runs in runs.csv; commit `285920f04b0213b0a66c759be8aa05a5e340c090-dirty`; [README](e1_admm_scaling/README.md)

### Results — scaling with N (iteration limit 50)

<!-- table src=summary.csv group_by=num_agents metrics=admm_solver_calls,admm_iter_mean,admm_iter_p95,admm_converged_frac,admm_solve_ms_mean,admm_time_per_tick_ms,admm_max_group_size,safety_violation_ticks,min_robustness_m where=admm_max_iterations:50 -->
| N | solver calls | mean iterations | p95 iterations | converged frac. | mean solve (ms) | ADMM time / tick (ms) | max group | violation ticks | min ρ (m) |
|---|---|---|---|---|---|---|---|---|---|
| 12 | 0 (n=1) | n/a | n/a | n/a | n/a | n/a | n/a | 0 (n=1) | 1.567 (n=1) |

### Results — iteration limit (N = 12)

<!-- table src=summary.csv group_by=admm_max_iterations metrics=admm_solver_calls,admm_iter_mean,admm_converged_frac,admm_time_per_tick_ms,safety_violation_ticks where=num_agents:12 -->
| iter. limit | solver calls | mean iterations | converged frac. | ADMM time / tick (ms) | violation ticks |
|---|---|---|---|---|---|
| 5 | 0 (n=1) | n/a | n/a | n/a | 0 (n=1) |
| 10 | 0 (n=1) | n/a | n/a | n/a | 0 (n=1) |
| 20 | 0 (n=1) | n/a | n/a | n/a | 0 (n=1) |
| 50 | 0 (n=1) | n/a | n/a | n/a | 0 (n=1) |
| 100 | 0 (n=1) | n/a | n/a | n/a | 0 (n=1) |

### Figures

- [e1_iterations_vs_N](figures/e1_iterations_vs_N.png)
- [e1_solve_time_vs_N](figures/e1_solve_time_vs_N.png)
- [e1_convergence_rate_vs_N](figures/e1_convergence_rate_vs_N.png)
- [e1_time_per_tick_vs_N](figures/e1_time_per_tick_vs_N.png)
- [e1_convergence_vs_iteration_limit](figures/e1_convergence_vs_iteration_limit.png)
- [e1_iterations_distribution](figures/e1_iterations_distribution.png)

### Observations

- Mean iterations per solver call: n/a at N=12 and n/a at N=12.
- Solver calls per run: 0 at N=12 and 0 at N=12.
- ADMM time per tick: n/a ms at N=12 and n/a ms at N=12.
- Converged fraction by N: N=12: n/a.
- At N=12, converged fraction is n/a at limit 5, n/a at limit 10, n/a at limit 20, n/a at limit 50, n/a at limit 100.

## E2 — Evaluate corridor merge success and throughput

**Table 10:** Hierarchical; Three corridors with varying density; owner P3.  
**Setup (manifest):** matrices e2; seeds [42]; N = [12]; 1 runs in runs.csv; commit `285920f04b0213b0a66c759be8aa05a5e340c090-dirty`; [README](e2_formation/README.md)

### Results — merges

<!-- table src=summary.csv group_by=num_agents metrics=merge_attempts,merge_success,merge_failed,not_reached,merge_success_rate -->
| N | merge attempts | successes | failed | not reached | success rate |
|---|---|---|---|---|---|
| 12 | 0 (n=1) | 0 (n=1) | 0 (n=1) | 12 (n=1) | n/a |

### Results — throughput and utilisation (occupancy / capacity)

<!-- table src=summary.csv group_by=num_agents metrics=throughput_per_s,arrivals,safety_violation_ticks,util_mean_c0,util_mean_c1,util_mean_c2,util_peak_c0,util_peak_c1,util_peak_c2,ticks_over_capacity -->
| N | throughput (agents/s) | arrivals | violation ticks | util_mean_c0 | util_mean_c1 | util_mean_c2 | util_peak_c0 | util_peak_c1 | util_peak_c2 | ticks over capacity |
|---|---|---|---|---|---|---|---|---|---|---|
| 12 | n/a | 0 (n=1) | 0 (n=1) | 0.2667 (n=1) | 0.2667 (n=1) | 0.2667 (n=1) | 0.2667 (n=1) | 0.2667 (n=1) | 0.2667 (n=1) | 0 (n=1) |

### Figures

- [e2_merge_success_vs_N](figures/e2_merge_success_vs_N.png)
- [e2_throughput_vs_N](figures/e2_throughput_vs_N.png)
- [e2_utilization_vs_N](figures/e2_utilization_vs_N.png)
- [e2_utilization_heatmap_N60](figures/e2_utilization_heatmap_N60.png)
- [e2_formation_snapshot_N60](figures/e2_formation_snapshot_N60.png)

### Observations

- Merge success rate by N: N=12: n/a.
- Merge attempts per run by N: N=12: 0.
- Throughput (arrivals/s) by N: N=12: n/a.
- At N=12, peak utilisation per corridor: c0: 0.2667, c1: 0.2667, c2: 0.2667; ticks over capacity: 0.

## E3 — Evaluate priority compliance

**Table 10:** Hierarchical; Emergency agent injected into traffic; owner P4.  
**Setup (manifest):** matrices e3; seeds [42]; N = [12]; 2 runs in runs.csv; commit `285920f04b0213b0a66c759be8aa05a5e340c090-dirty`; [README](e3_priority/README.md)

### Results — priority (pairs.csv → summary.csv)

<!-- table src=summary.csv group_by=num_agents metrics=priority_compliance_rate,emergency_delay_s,time_saved_vs_control_s,lower_priority_delay_s -->
| N | compliance rate | emergency delay (s) | time saved vs control (s) | imposed delay (s) |
|---|---|---|---|---|
| 12 | 1 (n=1) | n/a | n/a | n/a |

### Results — travel times

<!-- table src=summary.csv group_by=num_agents metrics=emergency_travel_time_s,control_travel_time_s -->
| N | emergency travel (s) | control travel (s) |
|---|---|---|
| 12 | n/a | n/a |

### Results — fleet metrics, emergency vs control runs

<!-- table src=runs_summary.csv group_by=num_agents,emergency_control metrics=throughput_per_s,safety_violation_ticks,min_robustness_m,admm_events -->
| N | control run | throughput (agents/s) | violation ticks | min ρ (m) | ADMM events |
|---|---|---|---|---|---|
| 12 | False | n/a | 0 (n=1) | 1.567 (n=1) | 0 (n=1) |
| 12 | True | n/a | 0 (n=1) | 1.567 (n=1) | 0 (n=1) |

### Figures

- [e3_compliance_vs_N](figures/e3_compliance_vs_N.png)
- [e3_emergency_delay_vs_N](figures/e3_emergency_delay_vs_N.png)
- [e3_imposed_delay_vs_N](figures/e3_imposed_delay_vs_N.png)
- [e3_emergency_track_N60](figures/e3_emergency_track_N60.png)

### Observations

- Compliance rate by N: N=12: 1.
- Emergency delay vs nominal (s) by N: N=12: n/a.
- Time saved vs control (s) by N: N=12: n/a.
- Delay imposed on others (s) by N: N=12: n/a.

## E4 — Compare resilience under attack

**Table 10:** Hierarchical / Centralized / Decentralized-undefended; One agent falsifies position at t = 60 s; owner P5.  
**Setup (manifest):** matrices e4, e4_offset; seeds [42]; N = [12]; 15 runs in runs.csv; commit `285920f04b0213b0a66c759be8aa05a5e340c090-dirty`; [README](e4_resilience/README.md)

### Results — attack off

<!-- table src=summary.csv group_by=architecture,attack_enabled metrics=throughput_per_s,safety_violation_ticks,mean_recovery_time_s,min_robustness_m where=attack_enabled:False -->
| architecture | attack | throughput (agents/s) | violation ticks | mean recovery (s) | min ρ (m) |
|---|---|---|---|---|---|
| centralized | False | n/a | 0 (n=1) | n/a | 1.474 (n=1) |
| decentralized_undefended | False | n/a | 0 (n=1) | n/a | 1.567 (n=1) |
| hierarchical | False | n/a | 0 (n=1) | n/a | 1.567 (n=1) |

### Results — attack on, by offset

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

- hierarchical: violation ticks 0 (off) vs 0 (on); min ρ 1.567 vs 1.567 m; throughput n/a vs n/a agents/s.
- centralized: violation ticks 0 (off) vs 0 (on); min ρ 1.474 vs 1.474 m; throughput n/a vs n/a agents/s.
- decentralized_undefended: violation ticks 0 (off) vs 0 (on); min ρ 1.567 vs 1.567 m; throughput n/a vs n/a agents/s.

## E5 — Evaluate STL robustness

**Table 10:** All evaluated architectures; Same scenarios as E1–E4; owner P6.  
**Setup (manifest):** matrices ; seeds [42]; N = [12]; 0 runs in runs.csv; commit `285920f04b0213b0a66c759be8aa05a5e340c090-dirty`; [README](e5_stl/README.md)

### Results — nominal runs pooled across experiments (one run per architecture, N, seed)

<!-- table src=stl_summary_pooled.csv group_by=architecture,num_agents metrics=min_robustness_m,p5_robustness_m,violation_fraction,violation_episodes,mean_recovery_time_s -->
| architecture | N | min ρ (m) | p5 ρ (m) | violating frac. | episodes | mean recovery (s) |
|---|---|---|---|---|---|---|
| centralized | 12 | 1.474 (n=1) | 1.577 (n=1) | 0 (n=1) | 0 (n=1) | n/a |
| decentralized_undefended | 12 | 1.567 (n=1) | 1.572 (n=1) | 0 (n=1) | 0 (n=1) | n/a |
| hierarchical | 12 | 1.567 (n=1) | 1.572 (n=1) | 0 (n=1) | 0 (n=1) | n/a |

### Results — every scenario / condition

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

### Figures

- [e5_robustness_distribution](figures/e5_robustness_distribution.png)
- [e5_violation_fraction_vs_N](figures/e5_violation_fraction_vs_N.png)
- [e5_recovery_time](figures/e5_recovery_time.png)
- [e5_robustness_heatmap](figures/e5_robustness_heatmap.png)

### Observations

- Hierarchical: violating fraction N=12: 0.
- Centralized: violating fraction N=12: 0.
- Decentralized (undefended): violating fraction N=12: 0.

## E6 — Evaluate graceful degradation

**Table 10:** Hierarchical; Overseer communication link dropped; owner P4 + P1.  
**Setup (manifest):** matrices e6; seeds [42]; N = [12]; 2 runs in runs.csv; commit `285920f04b0213b0a66c759be8aa05a5e340c090-dirty`; [README](e6_degradation/README.md)

### Results — link up vs link failure

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

### Results — degradation per seed

| seed | violations (up) | violations (failure) | score | directive refreshed in outage | max directive age in outage (s) | max position diff (m) | first divergence (s) |
|---|---|---|---|---|---|---|---|
| 42 | 0 | 0 | 1 | n/a | n/a | 0 | n/a |

<!-- table src=degradation_summary.csv group_by=num_agents metrics=graceful_degradation_score,directive_age_max_in_outage_s,max_position_diff_m,first_divergence_s -->
| N | degradation score | max directive age in outage (s) | max position diff (m) | first divergence (s) |
|---|---|---|---|---|
| 12 | 1 (n=1) | n/a | 0 (n=1) | n/a |

### Notes

- The outage window is not covered by these runs (n/a).
- Trajectories of the normal and failure runs are **identical** for every seed (max position difference 0 m) — the outage had no effect on motion in these runs.

### Figures

- [e6_violations_normal_vs_failure](figures/e6_violations_normal_vs_failure.png)
- [e6_throughput_normal_vs_failure](figures/e6_throughput_normal_vs_failure.png)
- [e6_directive_age_timeline](figures/e6_directive_age_timeline.png)
- [e6_degradation_score](figures/e6_degradation_score.png)

### Observations

- Violation ticks: 0 with the link up vs 0 with the link failure (mean over seeds).
- Throughput: n/a vs n/a agents/s.
- Overseer requests dropped: 0 vs 0; max directive age 1.9 vs 1.9 s.
- Degradation score per seed: seed 42: 1.

## Weak results

Listed only; none was re-run (decision: do not re-run weak groups).

- E1 (admm_max_iterations=5, num_agents=12): admm_iter_mean: n=0 < 3; admm_converged_frac: n=0 < 3; admm_time_per_tick_ms: n=0 < 3
- E1 (admm_max_iterations=10, num_agents=12): admm_iter_mean: n=0 < 3; admm_converged_frac: n=0 < 3; admm_time_per_tick_ms: n=0 < 3
- E1 (admm_max_iterations=20, num_agents=12): admm_iter_mean: n=0 < 3; admm_converged_frac: n=0 < 3; admm_time_per_tick_ms: n=0 < 3
- E1 (admm_max_iterations=50, num_agents=12): admm_iter_mean: n=0 < 3; admm_converged_frac: n=0 < 3; admm_time_per_tick_ms: n=0 < 3
- E1 (admm_max_iterations=100, num_agents=12): admm_iter_mean: n=0 < 3; admm_converged_frac: n=0 < 3; admm_time_per_tick_ms: n=0 < 3
- E2 (num_agents=12): merge_success_rate: n=0 < 3; throughput_per_s: n=0 < 3
- E3 (num_agents=12): priority_compliance_rate: n=1 < 3; emergency_delay_s: n=0 < 3; lower_priority_delay_s: n=0 < 3
- E4 (architecture=centralized, attack_enabled=False, attack_offset_m=nan): throughput_per_s: n=0 < 3; safety_violation_ticks: n=1 < 3; min_robustness_m: n=1 < 3
- E4 (architecture=centralized, attack_enabled=True, attack_offset_m=5.0): throughput_per_s: n=0 < 3; safety_violation_ticks: n=1 < 3; min_robustness_m: n=1 < 3
- E4 (architecture=centralized, attack_enabled=True, attack_offset_m=10.0): throughput_per_s: n=0 < 3; safety_violation_ticks: n=1 < 3; min_robustness_m: n=1 < 3
- E4 (architecture=centralized, attack_enabled=True, attack_offset_m=25.0): throughput_per_s: n=0 < 3; safety_violation_ticks: n=1 < 3; min_robustness_m: n=1 < 3
- E4 (architecture=centralized, attack_enabled=True, attack_offset_m=50.0): throughput_per_s: n=0 < 3; safety_violation_ticks: n=1 < 3; min_robustness_m: n=1 < 3
- E4 (architecture=decentralized_undefended, attack_enabled=False, attack_offset_m=nan): throughput_per_s: n=0 < 3; safety_violation_ticks: n=1 < 3; min_robustness_m: n=1 < 3
- E4 (architecture=decentralized_undefended, attack_enabled=True, attack_offset_m=5.0): throughput_per_s: n=0 < 3; safety_violation_ticks: n=1 < 3; min_robustness_m: n=1 < 3
- E4 (architecture=decentralized_undefended, attack_enabled=True, attack_offset_m=10.0): throughput_per_s: n=0 < 3; safety_violation_ticks: n=1 < 3; min_robustness_m: n=1 < 3
- E4 (architecture=decentralized_undefended, attack_enabled=True, attack_offset_m=25.0): throughput_per_s: n=0 < 3; safety_violation_ticks: n=1 < 3; min_robustness_m: n=1 < 3
- E4 (architecture=decentralized_undefended, attack_enabled=True, attack_offset_m=50.0): throughput_per_s: n=0 < 3; safety_violation_ticks: n=1 < 3; min_robustness_m: n=1 < 3
- E4 (architecture=hierarchical, attack_enabled=False, attack_offset_m=nan): throughput_per_s: n=0 < 3; safety_violation_ticks: n=1 < 3; min_robustness_m: n=1 < 3
- E4 (architecture=hierarchical, attack_enabled=True, attack_offset_m=5.0): throughput_per_s: n=0 < 3; safety_violation_ticks: n=1 < 3; min_robustness_m: n=1 < 3
- E4 (architecture=hierarchical, attack_enabled=True, attack_offset_m=10.0): throughput_per_s: n=0 < 3; safety_violation_ticks: n=1 < 3; min_robustness_m: n=1 < 3
- E4 (architecture=hierarchical, attack_enabled=True, attack_offset_m=25.0): throughput_per_s: n=0 < 3; safety_violation_ticks: n=1 < 3; min_robustness_m: n=1 < 3
- E4 (architecture=hierarchical, attack_enabled=True, attack_offset_m=50.0): throughput_per_s: n=0 < 3; safety_violation_ticks: n=1 < 3; min_robustness_m: n=1 < 3
- E6 (link_failure=False): safety_violation_ticks: n=1 < 3; throughput_per_s: n=0 < 3
- E6 (link_failure=True): safety_violation_ticks: n=1 < 3; throughput_per_s: n=0 < 3

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
