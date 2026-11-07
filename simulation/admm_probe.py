"""P2 ADMM convergence timer for the route engine (live demo).

Wraps ``conflict_resolution.adapter.resolve_all_conflicts`` with the project's
``conflict_resolution.profiling.ADMMRecorder`` and turns its per-solve records
into per-frame and cumulative statistics:

* iterations per solve (mean / max per frame; exact p95 over the run),
* solve time in ms (mean / max per frame; p95 over the run from a log-spaced
  histogram, so the value is approximate to one bin, ~12 %),
* converged vs fallback (the adapter returns the original intent when ADMM does
  not converge, i.e. the drone falls back to its boids/route velocity).

``ADMMRecorder`` monkey-patches ``ADMMSolver.solve`` on the class while active,
so concurrent runs in the threaded web server must not overlap: every recorded
call holds ``ADMM_LOCK``.

Iteration counts and convergence are deterministic; solve times are wall-clock
measurements and are reported separately (``*_ms`` keys) so they never feed
back into the simulation.
"""

from __future__ import annotations

import math
import threading
from typing import Any, Sequence

import numpy as np

from conflict_resolution.adapter import resolve_all_conflicts
from conflict_resolution.profiling import ADMMRecorder

ADMM_LOCK = threading.Lock()
_MS_EDGES = np.logspace(-3, 4, 141)  # 1 µs .. 10 s, 20 bins per decade


def _p95_from_counts(counts: np.ndarray, values: np.ndarray) -> float | None:
    total = int(counts.sum())
    if total == 0:
        return None
    rank = max(1, math.ceil(0.95 * total))  # same rank rule as profiling.summarize
    return float(values[int(np.searchsorted(np.cumsum(counts), rank))])


class ADMMProbe:
    """Per-run ADMM statistics collector."""

    def __init__(self, max_iterations: int = 50):
        self.iter_counts = np.zeros(max(1, int(max_iterations)) + 2, dtype=np.int64)
        self.ms_counts = np.zeros(len(_MS_EDGES), dtype=np.int64)
        self.solves = 0
        self.groups = 0
        self.converged = 0
        self.fallback = 0
        self.iterations_total = 0
        self.ms_total = 0.0
        self._window: list[tuple[int, float, bool]] = []
        self._window_groups = 0
        self.last: dict[int, dict[str, Any]] = {}   # drone id -> last negotiation (this frame window)

    # ------------------------------------------------------------------ solve
    def resolve(self, intents: Sequence[Any], priorities: dict[int, int], t: float) -> list[Any]:
        """``resolve_all_conflicts`` with every solver call recorded."""
        with ADMM_LOCK, ADMMRecorder() as rec:
            events = resolve_all_conflicts(intents, priorities)
        records = rec.records
        # one solver call per group unless the adapter returned early (non-finite input / error)
        matched = len(records) == len(events)
        for k, ev in enumerate(events):
            r = records[k] if matched else None
            self._add(ev, r, t)
        if not matched:  # still count the solves we saw
            for r in records:
                self._add_record(r)
        return events

    def _add_record(self, r: dict[str, Any]) -> None:
        it = int(r["iterations"])
        ms = float(r["solve_time_s"]) * 1000.0
        if it >= len(self.iter_counts):
            self.iter_counts = np.concatenate([self.iter_counts, np.zeros(it + 1 - len(self.iter_counts), np.int64)])
        self.iter_counts[it] += 1
        self.ms_counts[min(len(_MS_EDGES) - 1, int(np.searchsorted(_MS_EDGES, ms)))] += 1
        self.solves += 1
        self.iterations_total += it
        self.ms_total += ms
        self._window.append((it, ms, bool(r["converged"])))

    def _add(self, ev: Any, r: dict[str, Any] | None, t: float) -> None:
        self.groups += 1
        self._window_groups += 1
        ok = bool(ev.converged)
        if ok:
            self.converged += 1
        else:
            self.fallback += 1
        it = None
        if r is not None:
            self._add_record(r)
            it = int(r["iterations"])
        ids = [int(a) for a in ev.agents_involved]
        for aid in ids:
            self.last[aid] = {"t": t, "partners": [x for x in ids if x != aid], "it": it, "ok": ok}

    # ------------------------------------------------------------------ frame output
    def frame(self) -> dict[str, Any]:
        """Window stats since the previous frame + cumulative run stats; resets the window."""
        w = self._window
        iters = [x[0] for x in w]
        ms = [x[1] for x in w]
        out = {
            "groups": self._window_groups,
            "solves": len(w),
            "it_mean": round(float(np.mean(iters)), 2) if iters else None,
            "it_max": max(iters) if iters else None,
            "ms_mean": round(float(np.mean(ms)), 3) if ms else None,
            "ms_max": round(max(ms), 3) if ms else None,
            "fail": sum(1 for x in w if not x[2]),
            "run": self.summary(),
        }
        self._window = []
        self._window_groups = 0
        neg = {str(k): v for k, v in self.last.items()}
        self.last = {}
        return {"admm": out, "neg": neg}

    def summary(self) -> dict[str, Any]:
        its = np.arange(len(self.iter_counts))
        return {
            "groups": self.groups, "solves": self.solves,
            "converged": self.converged, "fallback": self.fallback,
            "it_mean": round(self.iterations_total / self.solves, 2) if self.solves else None,
            "it_p95": _p95_from_counts(self.iter_counts, its),
            "it_max": int(its[self.iter_counts > 0].max()) if self.solves else None,
            "ms_mean": round(self.ms_total / self.solves, 3) if self.solves else None,
            "ms_p95": (round(v, 3) if (v := _p95_from_counts(self.ms_counts, _MS_EDGES)) is not None else None),
        }
