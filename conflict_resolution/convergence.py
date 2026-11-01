"""Times and logs how fast each conflict resolves."""
from __future__ import annotations

import csv
import json
import time
from dataclasses import dataclass, field, asdict


@dataclass
class ConflictRecord:
    scenario: str
    n_agents: int
    n_constraints: int
    iterations: int
    converged: bool
    solve_time_ms: float
    final_primal_residual: float
    final_dual_residual: float
    min_separation: float


@dataclass
class ConvergenceLogger:
    records: list[ConflictRecord] = field(default_factory=list)
    _t0: float = 0.0

    def start(self) -> None:
        self._t0 = time.perf_counter()

    def stop(self) -> float:
        return (time.perf_counter() - self._t0) * 1000.0

    def add(self, record: ConflictRecord) -> None:
        self.records.append(record)

    def summary(self) -> dict:
        if not self.records:
            return {"conflicts": 0}
        times = [r.solve_time_ms for r in self.records]
        iters = [r.iterations for r in self.records]
        return {
            "conflicts": len(self.records),
            "converged_pct": 100.0 * sum(r.converged for r in self.records) / len(self.records),
            "mean_iters": sum(iters) / len(iters),
            "max_iters": max(iters),
            "mean_ms": sum(times) / len(times),
            "max_ms": max(times),
        }

    def to_csv(self, path: str) -> None:
        with open(path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(asdict(self.records[0]).keys()))
            w.writeheader()
            for r in self.records:
                w.writerow(asdict(r))

    def to_json(self, path: str) -> None:
        with open(path, "w") as f:
            json.dump({"summary": self.summary(),
                       "records": [asdict(r) for r in self.records]}, f, indent=2)
