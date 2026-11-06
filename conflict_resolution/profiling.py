"""Non-invasive profiling wrapper for the ADMM conflict resolution solver.

ConflictEvent is frozen (no iteration count), so we record solver calls via a
temporary monkey-patch of ADMMSolver.solve inside a context manager.  The
original method is always restored on exit, even when an exception is raised.
"""

from __future__ import annotations

import math
import time
from typing import Any

from conflict_resolution.solver import ADMMSolver


class ADMMRecorder:
    """Context manager that wraps ADMMSolver.solve to collect per-call stats.

    Usage::

        with ADMMRecorder() as rec:
            rec.current_tag = {"N": 60, "seed": 42}
            result = run_simulation(...)
        print(rec.records)
    """

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []
        self.current_tag: dict[str, Any] = {}
        self._original_solve = None

    # ------------------------------------------------------------------ #
    #  Context manager protocol                                           #
    # ------------------------------------------------------------------ #
    def __enter__(self) -> "ADMMRecorder":
        self._original_solve = ADMMSolver.solve  # keep a reference

        recorder = self  # capture for the closure

        def _wrapped_solve(solver_self, positions, targets, **kwargs):
            t0 = time.perf_counter()
            result = recorder._original_solve(solver_self, positions, targets, **kwargs)
            elapsed = time.perf_counter() - t0
            recorder.records.append({
                "group_size": len(positions),
                "iterations": result.iterations,
                "converged": bool(result.converged),
                "solve_time_s": elapsed,
                **recorder.current_tag,
            })
            return result

        ADMMSolver.solve = _wrapped_solve  # type: ignore[assignment]
        return self

    def __exit__(self, *exc) -> None:
        # Always restore, even on error
        if self._original_solve is not None:
            ADMMSolver.solve = self._original_solve  # type: ignore[assignment]
            self._original_solve = None


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate a list of solver-call records into summary statistics.

    Returns a dict with: count, mean_iterations, p95_iterations,
    max_iterations, mean_solve_ms, p95_solve_ms, fraction_converged.
    All values are ``float('nan')`` when *records* is empty.
    """
    if not records:
        return {
            "count": 0,
            "mean_iterations": float("nan"),
            "p95_iterations": float("nan"),
            "max_iterations": float("nan"),
            "mean_solve_ms": float("nan"),
            "p95_solve_ms": float("nan"),
            "fraction_converged": float("nan"),
        }

    iters = [r["iterations"] for r in records]
    times_ms = [r["solve_time_s"] * 1000.0 for r in records]
    converged = [1.0 if r["converged"] else 0.0 for r in records]

    iters_sorted = sorted(iters)
    times_sorted = sorted(times_ms)
    p95_idx = max(0, math.ceil(0.95 * len(iters_sorted)) - 1)

    return {
        "count": len(records),
        "mean_iterations": sum(iters) / len(iters),
        "p95_iterations": float(iters_sorted[p95_idx]),
        "max_iterations": float(max(iters)),
        "mean_solve_ms": sum(times_ms) / len(times_ms),
        "p95_solve_ms": float(times_sorted[p95_idx]),
        "fraction_converged": sum(converged) / len(converged),
    }
