"""Formation and corridor merge metrics for MASooda (P3 Week 5).

Provides FormationLogger to capture agent positions and corridor occupancy per tick,
and evaluation functions for corridor merge outcomes and corridor utilization.
"""

from __future__ import annotations

import collections
import math
from typing import Any, Sequence
import numpy as np

from config.load_config import get_config
from simulation.environment import (
    CorridorGeometry,
    build_corridors,
    corridor_occupancy,
    corridor_of_position,
)
from simulation.schema import AgentState


class FormationLogger:
    """Simulation logger recording agent kinematics, corridor assignment, and occupancy."""

    def __init__(self, corridors: list[CorridorGeometry] | None = None) -> None:
        self.corridors = corridors
        self.history: list[dict[str, Any]] = []
        self.agent_records: dict[int, list[dict[str, Any]]] = collections.defaultdict(list)
        self.occupancies: list[dict[int, int]] = []
        self.times: list[float] = []

    def log_state(self, t: float, agents: Sequence[AgentState]) -> None:
        """Store simulation state at time t.

        Parameters
        ----------
        t : float
            Simulation time in seconds.
        agents : Sequence[AgentState]
            Current true agent states.
        """
        t_float = float(t)
        corridors = self.corridors if self.corridors is not None else build_corridors()
        occupancy = corridor_occupancy(agents, corridors)

        agent_snapshots = []
        for a in agents:
            pos = np.asarray(a.position, dtype=float)
            alt_layer = int(getattr(a, "altitude_layer", 0))
            aid = int(a.id)
            corr_assign = a.corridor_assignment
            rec = {
                "id": aid,
                "x": float(pos[0]),
                "y": float(pos[1]),
                "altitude_layer": alt_layer,
                "corridor_assignment": corr_assign,
            }
            agent_snapshots.append(rec)
            self.agent_records[aid].append({"t": t_float, **rec})

        record = {
            "t": t_float,
            "occupancy": occupancy,
            "agents": agent_snapshots,
        }
        self.history.append(record)
        self.occupancies.append(occupancy)
        self.times.append(t_float)


def merge_outcomes(
    logger: FormationLogger,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate merge outcomes for all agents recorded by FormationLogger.

    Parameters
    ----------
    logger : FormationLogger
        Logger containing recorded history.
    cfg : dict, optional
        Configuration dictionary. If None, loaded via get_config().

    Returns
    -------
    dict[str, Any]
        Dictionary containing counts of success, failed, not_reached,
        no_merge_needed, merge_attempts, merge_success_rate, and per-agent list.
    """
    config = cfg if cfg is not None else get_config()
    corridors = logger.corridors if logger.corridors is not None else build_corridors(config)

    merge_zone = config["corridors"]["merge_zone_x_meters"]
    merge_end = float(merge_zone[1])

    success_count = 0
    failed_count = 0
    not_reached_count = 0
    no_merge_needed_count = 0
    agent_list: list[dict[str, Any]] = []

    if not logger.history or not logger.agent_records:
        return {
            "success": 0,
            "failed": 0,
            "not_reached": 0,
            "no_merge_needed": 0,
            "merge_success": 0,
            "merge_failed": 0,
            "merge_attempts": 0,
            "merge_success_rate": float("nan"),
            "agents": [],
            "per_agent": [],
        }

    # Process all agents sorted by ID
    for aid in sorted(logger.agent_records.keys()):
        records = logger.agent_records[aid]
        if not records:
            continue

        # Start corridor at t = 0
        start_y = records[0]["y"]
        start_corridor = corridor_of_position(start_y, corridors)

        # Find first tick where x >= merge_end
        first_tick = None
        for r in records:
            if r["x"] >= merge_end:
                first_tick = r
                break

        if first_tick is None:
            outcome = "not_reached"
            target = None
        else:
            target = first_tick["corridor_assignment"]
            if target is None:
                target = start_corridor

            if target == start_corridor:
                outcome = "no_merge_needed"
            else:
                end_corridor = corridor_of_position(first_tick["y"], corridors)
                if end_corridor == target:
                    outcome = "success"
                else:
                    outcome = "failed"

        if outcome == "success":
            success_count += 1
        elif outcome == "failed":
            failed_count += 1
        elif outcome == "not_reached":
            not_reached_count += 1
        elif outcome == "no_merge_needed":
            no_merge_needed_count += 1

        agent_info = {
            "id": aid,
            "agent_id": aid,
            "start_corridor": start_corridor,
            "target": target,
            "target_corridor": target,
            "outcome": outcome,
        }
        agent_list.append(agent_info)

    merge_attempts = success_count + failed_count
    if merge_attempts > 0:
        merge_success_rate = float(success_count / merge_attempts)
    else:
        merge_success_rate = float("nan")

    return {
        "success": success_count,
        "failed": failed_count,
        "not_reached": not_reached_count,
        "no_merge_needed": no_merge_needed_count,
        "merge_success": success_count,
        "merge_failed": failed_count,
        "merge_attempts": merge_attempts,
        "merge_success_rate": merge_success_rate,
        "agents": agent_list,
        "per_agent": agent_list,
    }


def corridor_utilization(
    logger: FormationLogger,
    capacity: int | float | None = None,
) -> dict[str, Any]:
    """Compute per-corridor and overall utilization metrics over all logged ticks.

    Parameters
    ----------
    logger : FormationLogger
        Logger containing recorded corridor occupancies.
    capacity : int or float, optional
        Capacity per corridor. If None, read from config.

    Returns
    -------
    dict[str, Any]
        Utilization statistics per corridor and overall mean_utilization.
    """
    if capacity is None:
        cfg = get_config()
        cap_val = float(cfg["corridors"]["capacity"])
    else:
        cap_val = float(capacity)

    corridors = logger.corridors if logger.corridors is not None else build_corridors()
    corridor_ids = [c.id for c in corridors]

    num_ticks = len(logger.occupancies)
    per_corridor: dict[int, dict[str, Any]] = {}

    for cid in corridor_ids:
        if num_ticks > 0:
            counts = [float(occ.get(cid, 0)) for occ in logger.occupancies]
            mean_util = float(np.mean(counts) / cap_val)
            peak_util = float(np.max(counts) / cap_val)
            ticks_over = int(sum(1 for c in counts if c > cap_val))
        else:
            mean_util = 0.0
            peak_util = 0.0
            ticks_over = 0

        per_corridor[cid] = {
            "id": cid,
            "mean_utilization": mean_util,
            "util": mean_util,
            "peak_utilization": peak_util,
            "ticks_over_capacity": ticks_over,
        }

    if corridor_ids:
        overall_mean_utilization = float(
            np.mean([per_corridor[cid]["mean_utilization"] for cid in corridor_ids])
        )
        total_ticks_over_capacity = int(
            sum(per_corridor[cid]["ticks_over_capacity"] for cid in corridor_ids)
        )
    else:
        overall_mean_utilization = 0.0
        total_ticks_over_capacity = 0

    result: dict[str, Any] = {
        "mean_utilization": overall_mean_utilization,
        "ticks_over_capacity": total_ticks_over_capacity,
        "corridors": per_corridor,
    }

    for cid in corridor_ids:
        result[cid] = per_corridor[cid]
        result[f"util_c{cid}"] = per_corridor[cid]["mean_utilization"]
        result[f"peak_c{cid}"] = per_corridor[cid]["peak_utilization"]
        result[f"ticks_over_c{cid}"] = per_corridor[cid]["ticks_over_capacity"]

    return result

