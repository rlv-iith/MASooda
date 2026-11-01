"""Adapter connecting simulation agent states to the ADMM conflict resolution solver (P2)."""

from __future__ import annotations

from typing import Sequence
import numpy as np

from simulation.schema import AgentState, ConflictEvent
from .solver import ADMMSolver


def resolve_conflict_event(
    agent_states: Sequence[AgentState],
    priorities: dict[int, int] | None = None,
) -> ConflictEvent:
    """Resolve pairwise separation conflicts among conflicting agents via ADMM.

    - positions = x,y of each agent; targets = positions + velocity x,y * dt
    - solve with ADMMSolver.from_config()
    - resolution[id] = a copy of the agent's velocity with x,y replaced by (new_position - position) / dt
    - agents_involved = the ids, converged = the solver's flag
    - On any error, returns each agent's current velocity and converged=False.
    """
    try:
        agent_ids = [a.id for a in agent_states]
        if not agent_states:
            return ConflictEvent(agents_involved=[], resolution={}, converged=True)

        solver = ADMMSolver.from_config()
        dt = solver.dt

        positions = np.array([a.position[:2] for a in agent_states], dtype=float)
        targets = positions + np.array([a.velocity[:2] for a in agent_states], dtype=float) * dt

        result = solver.solve(positions, targets)

        resolution: dict[int, np.ndarray] = {}
        for k, agent in enumerate(agent_states):
            vel = agent.velocity.copy()
            vel[:2] = (result.positions[k] - positions[k]) / dt
            resolution[agent.id] = vel

        return ConflictEvent(
            agents_involved=agent_ids,
            resolution=resolution,
            converged=bool(result.converged),
        )
    except Exception:
        fallback_resolution = {a.id: a.velocity.copy() for a in agent_states}
        return ConflictEvent(
            agents_involved=[a.id for a in agent_states],
            resolution=fallback_resolution,
            converged=False,
        )
