"""Trajectory logging for MASooda simulations.

Provides TrajectoryLogger to record agent states at each simulation timestep
and export them to structured arrays or CSV files.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Sequence
import numpy as np

from simulation.schema import AgentState, AgentType


class TrajectoryLogger:
    """Record agent trajectory history across simulation timesteps."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def log_state(self, t: float, agents: Sequence[AgentState]) -> None:
        """Store state for all agents at time t.

        Parameters
        ----------
        t : float
            Simulation time in seconds.
        agents : Sequence[AgentState]
            Current true agent states.
        """
        for agent in agents:
            type_str = agent.type.value if isinstance(agent.type, AgentType) else str(agent.type)
            self.rows.append({
                "t": float(t),
                "agent_id": int(agent.id),
                "x": float(agent.position[0]),
                "y": float(agent.position[1]),
                "vx": float(agent.velocity[0]),
                "vy": float(agent.velocity[1]),
                "corridor": agent.corridor_assignment,
                "type": type_str,
            })

    def as_position_array(self) -> np.ndarray:
        """Return array of shape (T, N, 2) containing only (x, y) coordinates.

        Agents are sorted by ID and timestamps are sorted ascending.
        """
        if not self.rows:
            return np.empty((0, 0, 2), dtype=float)

        ts = sorted({r["t"] for r in self.rows})
        agent_ids = sorted({r["agent_id"] for r in self.rows})
        t_map = {t: i for i, t in enumerate(ts)}
        id_map = {aid: j for j, aid in enumerate(agent_ids)}

        arr = np.zeros((len(ts), len(agent_ids), 2), dtype=float)
        for r in self.rows:
            ti = t_map[r["t"]]
            ii = id_map[r["agent_id"]]
            arr[ti, ii, 0] = r["x"]
            arr[ti, ii, 1] = r["y"]

        return arr

    def to_csv(self, path: str | Path) -> Path:
        """Write recorded trajectory to a CSV file.

        The columns are: t,agent_id,x,y,vx,vy,corridor,type.
        Parent folders are created automatically.

        Returns
        -------
        Path
            Path to the saved CSV file.
        """
        out_path = Path(path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["t", "agent_id", "x", "y", "vx", "vy", "corridor", "type"])
            for r in self.rows:
                corridor_val = r["corridor"] if r["corridor"] is not None else ""
                writer.writerow([
                    r["t"],
                    r["agent_id"],
                    r["x"],
                    r["y"],
                    r["vx"],
                    r["vy"],
                    corridor_val,
                    r["type"],
                ])

        return out_path

