"""Regression and performance checks for vectorized conflict detection."""

from __future__ import annotations

import math
import time

import numpy as np

from config.load_config import get_config
from conflict_resolution.adapter import resolve_all_conflicts
from conflict_resolution.detection import detect_conflicts
from simulation.scenario import make_initial_agents


def old_detect_conflicts(agent_states, config=None):
    """Original implementation retained as a behavioral oracle."""
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
    merge_x_min, merge_x_max = float(merge_zone[0]), float(merge_zone[1])
    agent_map = {a.id: a for a in agent_states}
    agent_list = list(agent_states)
    n = len(agent_list)
    in_merge_zone = lambda x: merge_x_min <= x <= merge_x_max
    adj = {a.id: set() for a in agent_list}
    for i in range(n):
        ai = agent_list[i]
        xi, yi = float(ai.position[0]), float(ai.position[1])
        if merge_zone_only and not in_merge_zone(xi):
            continue
        for j in range(i + 1, n):
            aj = agent_list[j]
            xj, yj = float(aj.position[0]), float(aj.position[1])
            if merge_zone_only and not in_merge_zone(xj):
                continue
            if math.hypot(xi - xj, yi - yj) < detection_radius:
                adj[ai.id].add(aj.id)
                adj[aj.id].add(ai.id)
    conflicted_ids = [aid for aid, nbrs in adj.items() if nbrs]
    visited, components = set(), []
    for aid in sorted(conflicted_ids):
        if aid not in visited:
            comp, queue = [], [aid]
            visited.add(aid)
            while queue:
                curr = queue.pop(0)
                comp.append(curr)
                for nbr in sorted(adj[curr]):
                    if nbr not in visited:
                        visited.add(nbr)
                        queue.append(nbr)
            components.append(comp)
    components.sort(key=lambda c: min(c))
    groups = []
    for comp in components:
        if len(comp) <= max_group_size:
            groups.append(sorted(comp))
        else:
            comp_agents = [agent_map[aid] for aid in comp]
            comp_agents.sort(key=lambda a: (float(a.position[0]), a.id))
            for k in range(0, len(comp_agents), max_group_size):
                groups.append(sorted(a.id for a in comp_agents[k:k + max_group_size]))
    return groups


def _merge_agents(n, seed):
    agents = make_initial_agents(n, seed=seed)
    merge_start = float(get_config()["corridors"]["merge_zone_x_meters"][0])
    for i, agent in enumerate(agents):
        agent.position[0] = merge_start + (i % 20) * 5.0
        agent.velocity[:] = [12.0, 0.0, 0.0]
    return agents


def test_vectorized_detection_matches_original_for_five_seeds():
    for seed in range(5):
        agents = _merge_agents(60, seed)
        assert detect_conflicts(agents) == old_detect_conflicts(agents)


def test_resolve_all_conflicts_on_60_agents_under_one_second():
    agents = _merge_agents(60, 42)
    priorities = {a.id: a.priority for a in agents}
    start = time.perf_counter()
    resolve_all_conflicts(agents, priorities)
    assert time.perf_counter() - start < 1.0
