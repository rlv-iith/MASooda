"""Conflict detection and grouping for distributed ADMM negotiation (P2)."""

from __future__ import annotations

from typing import Sequence
import math
import numpy as np

from config.load_config import get_config
from simulation.schema import AgentState


def detect_conflicts(
    agent_states: Sequence[AgentState],
    config: dict | None = None,
) -> list[list[int]]:
    """Find which agents are in conflict and partition them into groups of up to max_group_size.

    - Two agents are "in conflict" if their x,y distance < admm.detection_radius_meters
      AND (if merge_zone_only is true) both have x inside corridors.merge_zone_x_meters.
      Read merge_zone_x_meters directly from the config.
    - Build groups = connected components of the conflict pairs (only agents with at least
      one conflict). Each group is a sorted list of agent ids. Groups sorted by first id.
    - If a group is bigger than max_group_size, split it into chunks of max_group_size after
      sorting the agents by x position.
    """
    if not agent_states:
        return []

    if config is None:
        config = get_config()

    admm_cfg = config.get("admm", {})
    corridors_cfg = config.get("corridors", {})

    detection_radius = float(admm_cfg.get("detection_radius_meters", 20.0))
    merge_zone_only = bool(admm_cfg.get("merge_zone_only", True))
    max_group_size = int(admm_cfg.get("max_group_size", 5))

    merge_zone = corridors_cfg.get("merge_zone_x_meters", [700.0, 800.0])
    merge_x_min = float(merge_zone[0])
    merge_x_max = float(merge_zone[1])

    agent_map: dict[int, AgentState] = {a.id: a for a in agent_states}
    agent_list = list(agent_states)
    n = len(agent_list)

    def in_merge_zone(x: float) -> bool:
        return merge_x_min <= x <= merge_x_max

    # Build adjacency among conflicting agents
    adj: dict[int, set[int]] = {a.id: set() for a in agent_list}

    for i in range(n):
        ai = agent_list[i]
        xi = float(ai.position[0])
        yi = float(ai.position[1])

        if merge_zone_only and not in_merge_zone(xi):
            continue

        for j in range(i + 1, n):
            aj = agent_list[j]
            xj = float(aj.position[0])
            yj = float(aj.position[1])

            if merge_zone_only and not in_merge_zone(xj):
                continue

            dist_xy = math.hypot(xi - xj, yi - yj)
            if dist_xy < detection_radius:
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

    # Process components and split if bigger than max_group_size
    groups: list[list[int]] = []
    for comp in components:
        if len(comp) <= max_group_size:
            groups.append(sorted(comp))
        else:
            comp_agents = [agent_map[aid] for aid in comp]
            comp_agents.sort(key=lambda a: (float(a.position[0]), a.id))
            for k in range(0, len(comp_agents), max_group_size):
                chunk = comp_agents[k : k + max_group_size]
                groups.append(sorted([a.id for a in chunk]))

    return groups
