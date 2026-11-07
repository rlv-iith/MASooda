"""Conflict detection and grouping for distributed ADMM negotiation (P2)."""

from __future__ import annotations

from typing import Sequence
import numpy as np

from config.load_config import get_config
from simulation.schema import AgentState


def detect_conflicts(
    agent_states: Sequence[AgentState],
    config: dict | None = None,
) -> list[list[int]]:
    """Find connected components of agents that may conflict this tick.

    - Two agents are "in conflict" if their x,y distance < admm.detection_radius_meters
      AND they are on the same altitude layer
      AND (if merge_zone_only is true) both have x inside corridors.merge_zone_x_meters.
      Read merge_zone_x_meters directly from the config.
    - Build groups = connected components of the conflict pairs (only agents with at least
      one conflict). Each group is a sorted list of agent ids. Groups sorted by first id.
    - Keep each connected component intact so interactions remain visible to the same solve.
    """
    if not agent_states:
        return []

    if config is None:
        config = get_config()

    admm_cfg = config.get("admm", {})
    corridors_cfg = config.get("corridors", {})

    detection_radius = float(admm_cfg.get("detection_radius_meters", 20.0))
    merge_zone_only = bool(admm_cfg.get("merge_zone_only", True))

    merge_zone = corridors_cfg.get("merge_zone_x_meters", [700.0, 800.0])
    merge_x_min = float(merge_zone[0])
    merge_x_max = float(merge_zone[1])

    agent_list = list(agent_states)
    n = len(agent_list)

    # Compute all pair distances in compiled NumPy operations, then retain only
    # upper-triangle conflicts so each undirected edge is added once.
    positions = np.asarray([a.position[:2] for a in agent_list], dtype=float)
    deltas = positions[:, None, :] - positions[None, :, :]
    distances = np.sqrt(np.sum(deltas * deltas, axis=2))
    conflict_mask = distances < detection_radius
    np.fill_diagonal(conflict_mask, False)
    if merge_zone_only:
        in_zone = (positions[:, 0] >= merge_x_min) & (positions[:, 0] <= merge_x_max)
        conflict_mask &= in_zone[:, None] & in_zone[None, :]

    # Agents on different altitude layers cannot collide, so they never conflict.
    layers = np.asarray([int(getattr(a, "altitude_layer", 0)) for a in agent_list], dtype=int)
    conflict_mask &= layers[:, None] == layers[None, :]

    # Build adjacency among conflicting agents. Keep ids and set-based traversal
    # below unchanged to preserve component and output ordering.
    adj: dict[int, set[int]] = {a.id: set() for a in agent_list}
    rows, cols = np.nonzero(np.triu(conflict_mask, k=1))
    for i, j in zip(rows.tolist(), cols.tolist()):
        ai, aj = agent_list[i], agent_list[j]
        adj[ai.id].add(aj.id)
        adj[aj.id].add(ai.id)

    # Find connected components of agents with at least one conflict
    conflicted_ids = [aid for aid, nbrs in adj.items() if nbrs]
    visited: set[int] = set()
    components: list[list[int]] = []

    for aid in sorted(conflicted_ids):
        if aid not in visited:
            comp: list[int] = []
            queue = [aid]
            visited.add(aid)
            while queue:
                curr = queue.pop(0)
                comp.append(curr)
                for nbr in sorted(adj[curr]):
                    if nbr not in visited:
                        visited.add(nbr)
                        queue.append(nbr)
            components.append(comp)

    # Sort components by first (minimum) id
    components.sort(key=lambda c: min(c))

    # Lalith (P2): preserve the complete conflict component. Fixed-size chunks
    # could separate a conflicting pair at a cut, omitting their joint constraint.
    return [sorted(comp) for comp in components]
