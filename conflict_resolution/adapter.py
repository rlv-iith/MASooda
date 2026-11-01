"""Adapter that wraps the ADMMSolver into the project's ConflictEvent interface.

resolve_conflict_event() is the main entry point: it takes a list of AgentState
objects, runs the ADMM solver, and returns a ConflictEvent.
"""
from __future__ import annotations

from typing import Sequence

import numpy as np

from config.load_config import get_config
from conflict_resolution.solver import ADMMSolver
from simulation.schema import AgentState, ConflictEvent


def resolve_conflict_event(
    agent_states: Sequence[AgentState],
    priorities: dict[int, int] | None = None,
) -> ConflictEvent:
    """Resolve a separation conflict and return a ConflictEvent.

    ``priorities`` is accepted but ignored (Week 3 will use it).
    On any exception the function returns an event where every agent keeps its
    current velocity and converged is False.
    """
    try:
        cfg = get_config()
        dt = float(cfg["simulation"]["timestep_seconds"])

        positions = np.array([a.position[:2] for a in agent_states], dtype=float)
        velocities_xy = np.array([a.velocity[:2] for a in agent_states], dtype=float)
        targets = positions + velocities_xy * dt

        solver = ADMMSolver.from_config()
        result = solver.solve(positions, targets)

        resolution: dict[int, np.ndarray] = {}
        for k, agent in enumerate(agent_states):
            vel = agent.velocity.copy()
            vel[:2] = (result.positions[k] - positions[k]) / dt
            resolution[agent.id] = vel

        return ConflictEvent(
            agents_involved=[a.id for a in agent_states],
            resolution=resolution,
            converged=result.converged,
        )
    except Exception:
        resolution = {}
        for agent in agent_states:
            try:
                resolution[agent.id] = agent.velocity.copy()
            except Exception:
                resolution[getattr(agent, "id", 0)] = np.zeros(3)
        return ConflictEvent(
            agents_involved=[getattr(a, "id", 0) for a in agent_states],
            resolution=resolution,
            converged=False,
        )
