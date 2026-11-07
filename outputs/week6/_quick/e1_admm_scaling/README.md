# E1 — ADMM scaling and convergence

> **PROVISIONAL — pre-bug-fix results.** Metric and attack code is still being fixed.

Objective (Table 10): evaluate ADMM scaling — hierarchical architecture, 30/45/60/75 agents, no attack.
ADMM is used here as *conflict mitigation*: these numbers describe solver effort and convergence, not a
safety guarantee.

## Setup
- Matrices: e1, e1_iter (5 unique runs); seeds [42]; N = [12]
- Commit `285920f04b0213b0a66c759be8aa05a5e340c090-dirty`, config hash `e4509b11210199a7`, generated 2026-11-07T01:08:08+0530
- Hardware: Windows 11, Intel64 Family 6 Model 154 Stepping 3, GenuineIntel, 16 logical CPUs; Python 3.14.3, numpy 2.5.3, matplotlib 3.11.2
- Wall time of the last run invocation: 2.086 s (runs resumed from earlier invocations are not re-timed)
- Identical initial conditions per (seed, N): yes
- Duration 20 s, dt 0.1 s,
  no attack, no link failure. Iteration-limit sweep at N = 12; limit 50 (config default)
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
| 12 | 0 (n=1) | n/a | n/a | n/a | n/a | n/a | n/a | 0 (n=1) | 1.567 (n=1) |

## Results — iteration limit (N = 12)
<!-- table src=summary.csv group_by=admm_max_iterations metrics=admm_solver_calls,admm_iter_mean,admm_converged_frac,admm_time_per_tick_ms,safety_violation_ticks where=num_agents:12 -->
| iter. limit | solver calls | mean iterations | converged frac. | ADMM time / tick (ms) | violation ticks |
|---|---|---|---|---|---|
| 5 | 0 (n=1) | n/a | n/a | n/a | 0 (n=1) |
| 10 | 0 (n=1) | n/a | n/a | n/a | 0 (n=1) |
| 20 | 0 (n=1) | n/a | n/a | n/a | 0 (n=1) |
| 50 | 0 (n=1) | n/a | n/a | n/a | 0 (n=1) |
| 100 | 0 (n=1) | n/a | n/a | n/a | 0 (n=1) |

## Figures
- [e1_iterations_vs_N](../figures/e1_iterations_vs_N.png)
- [e1_solve_time_vs_N](../figures/e1_solve_time_vs_N.png)
- [e1_convergence_rate_vs_N](../figures/e1_convergence_rate_vs_N.png)
- [e1_time_per_tick_vs_N](../figures/e1_time_per_tick_vs_N.png)
- [e1_convergence_vs_iteration_limit](../figures/e1_convergence_vs_iteration_limit.png)
- [e1_iterations_distribution](../figures/e1_iterations_distribution.png)

## Weak groups
Criteria: n < 3 or std/mean > 0.5 on admm_iter_mean, admm_converged_frac, admm_time_per_tick_ms. Listed only, not re-run.
- admm_max_iterations=5, num_agents=12: admm_iter_mean: n=0 < 3; admm_converged_frac: n=0 < 3; admm_time_per_tick_ms: n=0 < 3
- admm_max_iterations=10, num_agents=12: admm_iter_mean: n=0 < 3; admm_converged_frac: n=0 < 3; admm_time_per_tick_ms: n=0 < 3
- admm_max_iterations=20, num_agents=12: admm_iter_mean: n=0 < 3; admm_converged_frac: n=0 < 3; admm_time_per_tick_ms: n=0 < 3
- admm_max_iterations=50, num_agents=12: admm_iter_mean: n=0 < 3; admm_converged_frac: n=0 < 3; admm_time_per_tick_ms: n=0 < 3
- admm_max_iterations=100, num_agents=12: admm_iter_mean: n=0 < 3; admm_converged_frac: n=0 < 3; admm_time_per_tick_ms: n=0 < 3

## Caveats
- Config: admm.max_group_size = 5, admm.merge_zone_only = True,
  admm.detection_radius_meters = 20.0 — conflicts are only detected inside the merge
  zone and groups are capped, so solver effort reflects merge-zone traffic only.
- Solve times are wall-clock on the hardware above and include Python overhead.

## Observations
- Mean iterations per solver call: n/a at N=12 and n/a at N=12.
- Solver calls per run: 0 at N=12 and 0 at N=12.
- ADMM time per tick: n/a ms at N=12 and n/a ms at N=12.
- Converged fraction by N: N=12: n/a.
- At N=12, converged fraction is n/a at limit 5, n/a at limit 10, n/a at limit 20, n/a at limit 50, n/a at limit 100.
