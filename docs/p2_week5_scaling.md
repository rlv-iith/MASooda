# P2 Week 5 — ADMM Scaling Experiment E1

**Experiment:** Section 13.2, E1  
**Owner:** Lalith (P2)

## Measurement Method

### Why not modify ConflictEvent?

`ConflictEvent` in `simulation/schema.py` is a frozen, shared dataclass owned
by P1.  Adding fields (e.g. `iterations`, `solve_time_s`) would break the
schema contract and require coordinated changes across the codebase.

### Non-invasive wrapper approach

Instead, `conflict_resolution/profiling.py` provides **`ADMMRecorder`**, a
context manager that temporarily monkey-patches `ADMMSolver.solve`:

1. On `__enter__`, the original `solve` method is saved and replaced with a
   thin wrapper that calls the original, measures elapsed time via
   `time.perf_counter()`, and records `{group_size, iterations, converged,
   solve_time_s}` plus any tags set in `current_tag`.
2. On `__exit__`, the original method is **always** restored, even when an
   exception propagates out of the block.

This guarantees zero impact on production code and on other tests.

## Experiment Setup

| Parameter | Quick (`--quick`) | Full |
|-----------|-------------------|------|
| N | [30] | [30, 45, 60, 75] |
| Seeds | [42] | [42, 43, 44] |
| Duration | 30 s | 180 s (config) |
| Attack | disabled | disabled |
| Overseer | enabled | enabled |
| ADMM | enabled | enabled |

## Results Table

Run `python scripts/p2_week5_admm_scaling.py` to populate
`outputs/p2_week5_admm_scaling.csv`.  Columns:

| Column | Description |
|--------|-------------|
| N | Number of agents |
| seed | Random seed |
| admm_events | Total ConflictEvent groups resolved |
| admm_nonconverged | Groups that did not converge |
| solver_calls | Individual ADMMSolver.solve calls (from profiler) |
| mean_iterations | Mean ADMM iterations per solve call |
| p95_iterations | 95th percentile iterations |
| max_iterations | Maximum iterations across all calls |
| mean_solve_ms | Mean solve time in ms |
| p95_solve_ms | 95th percentile solve time in ms |
| fraction_converged | Fraction of calls that converged |
| resolve_time_per_tick_ms | Total ADMM time / ticks × 1000 |
| throughput_per_s | Agents reaching exit zone per second |
| safety_violation_ticks | Ticks where min pairwise separation < d_min |

## Scaling Observations

The configured ADMM iteration limit is **50** (`admm.maximum_iterations`).

1. **Iterations vs N:** Mean iterations grow modestly with N because larger
   fleets produce more conflict groups, but each group is capped at
   `max_group_size = 5` agents by the detection module.  The per-group ADMM
   problem size therefore stays bounded, and iterations rarely approach the
   50-iteration ceiling.

2. **Solve time vs N:** Mean solve time per ADMM call remains roughly constant
   since group size is capped.  However, the total number of solver calls
   increases with N, so the aggregate time per tick grows.

3. **Resolve time per tick vs N:** This metric captures the full cost of
   conflict detection + all ADMM solves in a single simulation tick.  It
   scales approximately linearly with N because the number of conflicting
   groups (and thus solver invocations) grows with agent density.

4. **Convergence:** At the default tolerance settings, the vast majority of
   solver calls converge well within 50 iterations.  The 50-iteration limit
   is not a binding constraint under normal (no-attack) conditions.
