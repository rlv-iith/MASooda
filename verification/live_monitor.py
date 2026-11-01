"""Live Signal Temporal Logic (STL) safety monitor for online execution.

Provides LiveSTLMonitor matching the simulation logger interface log_state(t, agents)
to continuously monitor minimum separation robustness and log violations in real time.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Sequence
import numpy as np

from config.load_config import get_config
from simulation.schema import AgentState, STLRobustness, STLSpec
from .stl_monitor import (
    SlidingSTLMonitor,
    _pairwise_min,
    instantaneous_robustness,
    load_spec_from_config,
)


class LiveSTLMonitor:
    """Online STL safety monitor adhering to the simulation logger protocol."""

    def __init__(
        self,
        spec: STLSpec | None = None,
        window_steps: int | None = None,
    ) -> None:
        cfg = get_config()
        self.spec = spec if spec is not None else load_spec_from_config(cfg)

        if window_steps is None:
            stl_cfg = cfg.get("stl", {})
            self.window_steps = int(stl_cfg.get("window_steps", 10))
        else:
            self.window_steps = int(window_steps)

        self.sliding_monitor = SlidingSTLMonitor(self.spec, window_steps=self.window_steps)
        self.history: list[dict[str, Any]] = []

    def log_state(self, t: float, agents: Sequence[AgentState]) -> STLRobustness:
        """Process simulation state at time t, log metrics, and return window robustness.

        Parameters
        ----------
        t : float
            Simulation time in seconds.
        agents : Sequence[AgentState]
            True agent states for this simulation tick.

        Returns
        -------
        STLRobustness
            Signed robustness result of the sliding window evaluation.
        """
        sorted_agents = sorted(agents, key=lambda a: a.id)
        positions = np.array([a.position[:2] for a in sorted_agents], dtype=float)

        # Evaluate window robustness via SlidingSTLMonitor
        rob_result = self.sliding_monitor.update(positions)

        # Compute instantaneous robustness for this tick
        rho_t = instantaneous_robustness(positions, self.spec.d_min)

        # Identify closest pair at this tick
        if len(sorted_agents) >= 2:
            _, (pi, pj) = _pairwise_min(positions)
            worst_pair = (int(sorted_agents[pi].id), int(sorted_agents[pj].id))
        else:
            worst_pair = None

        record = {
            "t": float(t),
            "rho": float(rho_t),
            "window_rho": float(rob_result.value),
            "violation": bool(rob_result.violation),
            "status": str(rob_result.status),
            "worst_pair": worst_pair,
        }
        self.history.append(record)

        return rob_result

    def violations(self) -> list[tuple[float, float, tuple[int, int] | None]]:
        """Return list of (t, rho, worst_pair) for ticks where instantaneous rho(t) < 0."""
        return [
            (r["t"], r["rho"], r["worst_pair"])
            for r in self.history
            if r["rho"] < 0.0
        ]

    def violation_count(self) -> int:
        """Return number of ticks for which instantaneous robustness was negative."""
        return len(self.violations())

    def min_robustness(self) -> float:
        """Return minimum instantaneous robustness rho(t) across all logged ticks."""
        if not self.history:
            return float("inf")
        return float(min(r["rho"] for r in self.history))

    def to_csv(self, path: str | Path) -> Path:
        """Export logged safety metrics to CSV with columns t,rho,window_rho,violation,status.

        Returns
        -------
        Path
            Path to the written CSV file.
        """
        out_path = Path(path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["t", "rho", "window_rho", "violation", "status"])
            for r in self.history:
                writer.writerow([
                    r["t"],
                    r["rho"],
                    r["window_rho"],
                    r["violation"],
                    r["status"],
                ])

        return out_path

