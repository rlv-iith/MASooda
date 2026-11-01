"""Resilient and plain consensus routines (P5).

Includes:
- plain_average: standard local averaging over self and neighbors.
- run_consensus: discrete-time iterative consensus with Byzantine/malicious liars.
"""

from __future__ import annotations

from typing import Any, Sequence
import numpy as np

from simulation.schema import CommunicationGraph


def plain_average(own_value: Any, neighbor_values: Sequence[Any]) -> Any:
    """Return the mean of own value and all neighbor values.

    Works for floats, ints, and numpy arrays.
    """
    all_values = [own_value] + list(neighbor_values)
    if isinstance(own_value, np.ndarray):
        return np.mean(all_values, axis=0)
    return float(np.mean(all_values))


def run_consensus(
    initial_values: dict[int, float],
    graph: CommunicationGraph,
    liars: dict[int, float] | None,
    steps: int,
) -> list[dict[int, float]]:
    """Run discrete-time plain averaging consensus.

    - initial_values: dict id -> float
    - graph: CommunicationGraph
    - liars: dict id -> float (the constant value that liar always reports)
    - steps: number of consensus iterations

    Returns a list of dicts (one per step, including step 0 at index 0).
    Each step, every HONEST agent sets its value to plain_average(own value, values reported by neighbors).
    A liar reports its constant liar value and never updates.
    All agents update simultaneously using the previous step's values.
    """
    liars_map = dict(liars) if liars else {}

    current: dict[int, float] = {}
    for aid, val in initial_values.items():
        if aid in liars_map:
            current[aid] = float(liars_map[aid])
        else:
            current[aid] = float(val)

    history: list[dict[int, float]] = [dict(current)]

    for _ in range(steps):
        prev = history[-1]
        next_step: dict[int, float] = {}
        for aid in initial_values:
            if aid in liars_map:
                next_step[aid] = float(liars_map[aid])
            else:
                nbr_ids = graph.neighbors(aid)
                nbr_vals = [prev[nid] for nid in nbr_ids if nid in prev]
                next_step[aid] = plain_average(prev[aid], nbr_vals)
        history.append(next_step)

    return history
