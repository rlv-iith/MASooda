"""Adapter connecting simulation agent states to the ADMM conflict resolution solver (P2)."""

from __future__ import annotations

from typing import Sequence
import numpy as np

from config.load_config import get_config
from simulation.schema import AgentState, ConflictEvent
from .detection import detect_conflicts
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

        if any(
            not np.all(np.isfinite(agent.position))
            or not np.all(np.isfinite(agent.velocity))
            for agent in agent_states
        ):
            return ConflictEvent(
                agents_involved=agent_ids,
                resolution={a.id: a.velocity.copy() for a in agent_states},
                converged=False,
            )

        solver = ADMMSolver.from_config()
        dt = solver.dt

        positions = np.array([a.position[:2] for a in agent_states], dtype=float)
        targets = positions + np.array([a.velocity[:2] for a in agent_states], dtype=float) * dt

        cfg = get_config()
        priority_weights = cfg.get("admm", {}).get("priority_weights", {0: 10.0, 1: 3.0, 2: 1.0})
        default_weight = float(priority_weights.get(2, priority_weights.get("2", 1.0)))

        if priorities is None:
            w = None
        else:
            w_list: list[float] = []
            for a in agent_states:
                if a.id in priorities:
                    p = priorities[a.id]
                    if hasattr(p, "value"):
                        p = p.value
                    if isinstance(p, str) and p.isdigit():
                        p = int(p)
                    elif isinstance(p, str):
                        p_map = {"EMERGENCY": 0, "EVTOL": 1, "DELIVERY": 2}
                        p = p_map.get(p.upper(), p)
                    w_list.append(float(priority_weights.get(p, priority_weights.get(str(p), default_weight))))
                else:
                    w_list.append(default_weight)
            w = np.array(w_list, dtype=float)

        result = solver.solve(positions, targets, weights=w)

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


def resolve_all_conflicts(
    agent_states: Sequence[AgentState],
    priorities: dict[int, int] | None = None,
) -> list[ConflictEvent]:
    """Detect conflicts and resolve each conflicting group via ADMM.

    - groups = detect_conflicts(agent_states)
    - for each group, call resolve_conflict_event on just those agents (with priorities)
    - return the list of ConflictEvent. Empty list if no conflicts.
    """
    groups = detect_conflicts(agent_states)
    if not groups:
        return []

    agent_map = {a.id: a for a in agent_states}
    events: list[ConflictEvent] = []
    for group in groups:
        group_states = [agent_map[aid] for aid in group]
        event = resolve_conflict_event(group_states, priorities=priorities)
        events.append(event)

    return events
