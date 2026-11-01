"""Trusted-range and W-MSR filtering for neighbour position reports.

A report whose distance disagrees with the physically sensed range is flagged.
The flagged neighbour is NOT removed: removing it makes the receiver blind to a
real aircraft. Instead its position is moved along the reported bearing to the
sensed (trusted) range, so separation still reacts to it.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass

import numpy as np

from config.load_config import get_config
from simulation.schema import AgentState
from .wmsr import wmsr_vector


@dataclass
class DefenseResult:
    kept: list[AgentState]        # all neighbours; flagged ones carry a corrected position
    dropped_ids: list[int]        # ids whose reported position was rejected (flagged)
    wmsr_estimate: np.ndarray   # shape (3,)


def defend_neighbor_reports(
    own_state: AgentState,
    reported_neighbors: list[AgentState],
    true_neighbors: list[AgentState],
    f: int | None = None,
    range_tolerance_m: float | None = None,
) -> DefenseResult:
    """Reject range-inconsistent reports and estimate position with W-MSR."""
    resilience_cfg = get_config().get("resilience", {})
    if f is None:
        f = int(resilience_cfg.get("f", 1))
    if range_tolerance_m is None:
        range_tolerance_m = float(resilience_cfg.get("range_tolerance_meters", 3.0))

    true_by_id = {neighbor.id: neighbor for neighbor in true_neighbors}
    kept: list[AgentState] = []
    dropped_ids: list[int] = []
    own_xy = own_state.position[:2]
    for report in reported_neighbors:
        if report.id not in true_by_id:
            kept.append(report)
            continue
        sensed = np.linalg.norm(true_by_id[report.id].position[:2] - own_xy)
        reported = np.linalg.norm(report.position[:2] - own_xy)
        if abs(reported - sensed) > range_tolerance_m:
            dropped_ids.append(report.id)
            corrected = copy.deepcopy(report)
            bearing = report.position[:2] - own_xy
            norm = float(np.linalg.norm(bearing))
            if norm > 1e-9:
                corrected.position[:2] = own_xy + bearing / norm * sensed
            else:
                corrected.position[:2] = true_by_id[report.id].position[:2]
            kept.append(corrected)
        else:
            kept.append(report)

    if reported_neighbors:
        xy = wmsr_vector(
            own_xy,
            [report.position[:2] for report in reported_neighbors],
            f,
        )
        estimate = np.array([xy[0], xy[1], own_state.position[2]], dtype=float)
    else:
        estimate = own_state.position.copy()

    return DefenseResult(kept=kept, dropped_ids=dropped_ids, wmsr_estimate=estimate)
