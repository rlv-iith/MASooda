# E1 — ADMM scaling and convergence

> **PROVISIONAL — pre-bug-fix results.** Metric and attack code is still being fixed.

Objective (Table 10): evaluate ADMM scaling — hierarchical architecture, 30/45/60/75 agents, no attack.
ADMM is used here as *conflict mitigation*: these numbers describe solver effort and convergence, not a
safety guarantee.

## Setup
- Matrices: e1, e1_iter (24 unique runs); seeds [42, 43, 44]; N = [30, 45, 60, 75]
- Commit `285920f04b0213b0a66c759be8aa05a5e340c090-dirty`, config hash `e4509b11210199a7`, generated 2026-11-07T00:42:40+0530
- Hardware: Windows 11, Intel64 Family 6 Model 154 Stepping 3, GenuineIntel, 16 logical CPUs; Python 3.14.3, numpy 2.5.3, matplotlib 3.11.2
- Wall time of the last run invocation: 145.2 s (runs resumed from earlier invocations are not re-timed)
- Identical initial conditions per (seed, N): yes
- Duration 180 s, dt 0.1 s,
  no attack, no link failure. Iteration-limit sweep at N = 60; limit 50 (config default)
  runs are shared with the scaling matrix.

## Method
Every ADMM solver call is recorded with `conflict_resolution.profiling.ADMMRecorder` (solver unchanged):
iterations, converged flag, solve time, group size (`calls.csv`, one row per call). Per run: mean / p95 / max
iterations, converged fraction, mean / p95 solve time, ADMM wall time per tick (engine `admm_time_s` / ticks),
largest group. A run with no solver call reports n/a. Tables: mean ± 95% CI half-width (t-distribution) over
seeds, n = runs with a value.

## Results — scaling with N (iteration limit 50)
<!-- table src=summary.csv group_by=num_agents metrics=admm_solver_calls,admm_iter_mean,admm_iter_p95,admm_converged_frac,admm_solve_ms_mean,admm_time_per_tick_ms,admm_max_group_size,safety_violation_ticks,min_robustness_m where=admm_max_iterations:50 -->
| N | solver calls | mean iterations | p95 iterations | converged frac. | mean solve (ms) | ADMM time / tick (ms) | max group | violation ticks | min ρ (m) |
|---|---|---|---|---|---|---|---|---|---|
| 30 | 946.7 ± 3e+02 (n=3) | 10.15 ± 0.45 (n=3) | 14.33 ± 1.4 (n=3) | 1 ± 0 (n=3) | 0.9006 ± 0.17 (n=3) | 0.771 ± 0.094 (n=3) | 5 ± 0 (n=3) | 826 ± 7.1e+02 (n=3) | -7.987 ± 0.018 (n=3) |
| 45 | 1360 ± 5.3e+02 (n=3) | 10.46 ± 0.31 (n=3) | 15 ± 0 (n=3) | 1 ± 0 (n=3) | 1.057 ± 0.088 (n=3) | 1.214 ± 0.3 (n=3) | 5 ± 0 (n=3) | 1704 ± 3.2e+02 (n=3) | -7.966 ± 0.069 (n=3) |
| 60 | 1809 ± 6.4e+02 (n=3) | 10.02 ± 0.14 (n=3) | 15 ± 0 (n=3) | 1 ± 0 (n=3) | 1.029 ± 0.12 (n=3) | 1.549 ± 0.29 (n=3) | 5 ± 0 (n=3) | 1777 ± 10 (n=3) | -7.994 ± 0.019 (n=3) |
| 75 | 2126 ± 3.3e+02 (n=3) | 9.964 ± 0.52 (n=3) | 15 ± 0 (n=3) | 1 ± 0 (n=3) | 0.9972 ± 0.14 (n=3) | 1.785 ± 0.13 (n=3) | 5 ± 0 (n=3) | 1782 ± 14 (n=3) | -7.998 ± 0.0044 (n=3) |

## Results — iteration limit (N = 60)
<!-- table src=summary.csv group_by=admm_max_iterations metrics=admm_solver_calls,admm_iter_mean,admm_converged_frac,admm_time_per_tick_ms,safety_violation_ticks where=num_agents:60 -->
| iter. limit | solver calls | mean iterations | converged frac. | ADMM time / tick (ms) | violation ticks |
|---|---|---|---|---|---|
| 5 | 1817 ± 6.4e+02 (n=3) | 4.93 ± 0.1 (n=3) | 0.07013 ± 0.1 (n=3) | 1.06 ± 0.17 (n=3) | 1777 ± 10 (n=3) |
| 10 | 1815 ± 6.5e+02 (n=3) | 9.154 ± 0.77 (n=3) | 0.7779 ± 0.14 (n=3) | 1.48 ± 0.31 (n=3) | 1777 ± 10 (n=3) |
| 20 | 1812 ± 6.3e+02 (n=3) | 10 ± 0.19 (n=3) | 0.9971 ± 0.012 (n=3) | 1.587 ± 0.27 (n=3) | 1777 ± 9 (n=3) |
| 50 | 1809 ± 6.4e+02 (n=3) | 10.02 ± 0.14 (n=3) | 1 ± 0 (n=3) | 1.549 ± 0.29 (n=3) | 1777 ± 10 (n=3) |
| 100 | 1809 ± 6.4e+02 (n=3) | 10.02 ± 0.14 (n=3) | 1 ± 0 (n=3) | 1.599 ± 0.21 (n=3) | 1777 ± 10 (n=3) |

## Figures
- [e1_iterations_vs_N](../figures/e1_iterations_vs_N.png)
- [e1_solve_time_vs_N](../figures/e1_solve_time_vs_N.png)
- [e1_convergence_rate_vs_N](../figures/e1_convergence_rate_vs_N.png)
- [e1_time_per_tick_vs_N](../figures/e1_time_per_tick_vs_N.png)
- [e1_convergence_vs_iteration_limit](../figures/e1_convergence_vs_iteration_limit.png)
- [e1_iterations_distribution](../figures/e1_iterations_distribution.png)

## Weak groups
Criteria: n < 3 or std/mean > 0.5 on admm_iter_mean, admm_converged_frac, admm_time_per_tick_ms. Listed only, not re-run.
- admm_max_iterations=5, num_agents=60: admm_converged_frac: std/mean=0.57 > 0.5

## Caveats
- Config: admm.max_group_size = 5, admm.merge_zone_only = True,
  admm.detection_radius_meters = 20.0 — conflicts are only detected inside the merge
  zone and groups are capped, so solver effort reflects merge-zone traffic only.
- Solve times are wall-clock on the hardware above and include Python overhead.

## Observations
- Mean iterations per solver call: 10.15 at N=30 and 9.964 at N=75.
- Solver calls per run: 946.7 at N=30 and 2126 at N=75.
- ADMM time per tick: 0.771 ms at N=30 and 1.785 ms at N=75.
- Converged fraction by N: N=30: 1, N=45: 1, N=60: 1, N=75: 1.
- At N=60, converged fraction is 0.07013 at limit 5, 0.7779 at limit 10, 0.9971 at limit 20, 1 at limit 50, 1 at limit 100.
