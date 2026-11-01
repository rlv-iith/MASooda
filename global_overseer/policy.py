"""Global overseer policy and snapshot utilities (P4)."""

from __future__ import annotations

from typing import Sequence

from config.load_config import get_config
from simulation.overseer import WEEK1_PRIORITY_TABLE
from simulation.schema import (
    AgentState,
    GlobalStateSnapshot,
    OverseerDirective,
    validate_snapshot,
)


def snapshot_from_agents(agents: Sequence[AgentState], t: float) -> GlobalStateSnapshot:
    """Construct a GlobalStateSnapshot from a list of agent states at time t.

    - corridor_occupancy counts agents per corridor (0..corridors.count-1, even if 0).
    - Agents with corridor_assignment None are not counted in corridor_occupancy.
    - agent_ids, agent_types, agent_priorities are extracted from all agents.
    """
    cfg = get_config()
    corridor_count = int(cfg["corridors"]["count"])

    occupancy: dict[int, int] = {c: 0 for c in range(corridor_count)}
    for agent in agents:
        if agent.corridor_assignment is not None:
            c = int(agent.corridor_assignment)
            occupancy[c] = occupancy.get(c, 0) + 1

    agent_ids = [a.id for a in agents]
    agent_types = {a.id: a.type for a in agents}
    agent_priorities = {a.id: a.priority for a in agents}

    return GlobalStateSnapshot(
        timestamp=float(t),
        corridor_occupancy=occupancy,
        agent_ids=agent_ids,
        agent_types=agent_types,
        agent_priorities=agent_priorities,
    )


def least_loaded_assign(snapshot: GlobalStateSnapshot) -> dict[int, int]:
    """Assign sorted agent IDs to corridors based on least occupancy.

    Starts from a copy of snapshot.corridor_occupancy (missing corridors = 0).
    Iterates through snapshot.agent_ids in sorted order.
    Assigns each agent the corridor with the smallest count (ties broken by smallest corridor id),
    then increments that corridor's count by 1.
    """
    cfg = get_config()
    corridor_count = int(cfg["corridors"]["count"])

    counts: dict[int, int] = {c: 0 for c in range(corridor_count)}
    if snapshot.corridor_occupancy:
        for c, count in snapshot.corridor_occupancy.items():
            counts[int(c)] = int(count)

    corridor_map: dict[int, int] = {}
    sorted_ids = sorted(snapshot.agent_ids)

    # Corridors ordered by id for deterministic tie-breaking
    all_corridors = sorted(counts.keys())

    for aid in sorted_ids:
        best_corridor = min(all_corridors, key=lambda c: counts[c])
        corridor_map[aid] = best_corridor
        counts[best_corridor] += 1

    return corridor_map


def round_robin_assign(snapshot: GlobalStateSnapshot) -> dict[int, int]:
    """Assign sorted agent IDs to corridors in round-robin fashion (0, 1, 2, 0, 1, 2, ...)."""
    cfg = get_config()
    corridor_count = int(cfg["corridors"]["count"])

    corridor_map: dict[int, int] = {}
    sorted_ids = sorted(snapshot.agent_ids)

    for idx, aid in enumerate(sorted_ids):
        corridor_map[aid] = idx % corridor_count

    return corridor_map


def real_overseer_update(snapshot: GlobalStateSnapshot) -> OverseerDirective:
    """Create an OverseerDirective using coarse corridor occupancy data.

    - Validates the snapshot first using validate_snapshot.
    - Selects corridor_map based on config policy ('least_loaded' or 'round_robin').
    - Sets priority_table to WEEK1_PRIORITY_TABLE.
    - Sets altitude_map = 0 for every agent (layers unused in Week 2).
    - Preserves snapshot.timestamp and never mutates the snapshot.
    """
    validate_snapshot(snapshot)

    cfg = get_config()
    policy = cfg.get("overseer", {}).get("policy", "least_loaded")

    if policy == "round_robin":
        corridor_map = round_robin_assign(snapshot)
    else:
        corridor_map = least_loaded_assign(snapshot)

    altitude_map = {aid: 0 for aid in snapshot.agent_ids}

    return OverseerDirective(
        corridor_map=corridor_map,
        priority_table=dict(WEEK1_PRIORITY_TABLE),
        altitude_map=altitude_map,
        timestamp=snapshot.timestamp,
    )
