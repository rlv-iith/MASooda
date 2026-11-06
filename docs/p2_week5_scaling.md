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

1. **Iterations vs N:** Earlier results used a five-agent chunk limit. Lalith
   (P2) removed this split because it could omit close-pair constraints across
   chunk boundaries. The updated solver processes each connected conflict
   component intact. Component size, iteration count, and convergence must be
   re-measured; the previous bounded-size conclusion no longer applies.

2. **Solve time vs N:** Per-call cost may rise with connected-component size.
   Measure component-size distributions and solver time directly instead of
   assuming constant solve time.

3. **Resolve time per tick vs N:** This metric captures the full cost of
   conflict detection plus all ADMM solves in a tick. Its scaling depends on
   both the number and size of connected components and must be re-measured.

4. **Convergence:** Re-measure after the grouping change. Larger joint solves
   may take longer or reach the configured 50-iteration limit. Report
   convergence and fallback rates along with timing.
