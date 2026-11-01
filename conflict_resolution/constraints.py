"""Separation rules expressed as convex constraints for the ADMM solver.

The true collision-avoidance rule ||x_i - x_j|| >= d_safe is non-convex.
We convexify it by linearising around the agents' CURRENT positions:

    n_ij . (x_i - x_j) >= d_safe,   n_ij = (p_i - p_j) / ||p_i - p_j||

This is a half-space in the joint (x_i, x_j) space. It is conservative:
satisfying it guarantees ||x_i - x_j|| >= d_safe, because
n . v <= ||v|| for any unit vector n.
"""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np


@dataclass(frozen=True)
class PairConstraint:
    i: int
    j: int
    normal: np.ndarray      # unit vector pointing from j to i
    d_safe: float


def build_pair_constraints(positions: np.ndarray, d_safe: float,
                           activation_dist: float | None = None,
                           z: np.ndarray | None = None,
                           layer_gap: float = 1.0) -> list[PairConstraint]:
    """One half-space per agent pair that is close enough to possibly conflict.

    If z (altitude / layer per agent) is given, pairs whose altitude differs
    by >= layer_gap are skipped: they are on different layers and cannot collide.
    """
    n_agents, dim = positions.shape
    activation = activation_dist if activation_dist is not None else 3.0 * d_safe
    out: list[PairConstraint] = []
    for i in range(n_agents):
        for j in range(i + 1, n_agents):
            if z is not None and abs(z[i] - z[j]) >= layer_gap:
                continue  # different layers: no constraint
            diff = positions[i] - positions[j]
            dist = float(np.linalg.norm(diff))
            if dist > activation:
                continue
            if dist < 1e-9:  # exactly co-located: pick a deterministic direction
                normal = np.zeros(dim)
                normal[0] = 1.0
            else:
                normal = diff / dist
            out.append(PairConstraint(i, j, normal, d_safe))
    return out


def project_pair(a: np.ndarray, b: np.ndarray, c: PairConstraint):
    """Euclidean projection of (a, b) onto {(a,b): n.(a-b) >= d_safe}.

    The violation is split equally: a moves +n, b moves -n.
    """
    violation = c.d_safe - float(c.normal @ (a - b))
    if violation <= 0.0:
        return a, b
    shift = 0.5 * violation * c.normal
    return a + shift, b - shift


def project_ball(x: np.ndarray, centre: np.ndarray, radius: float) -> np.ndarray:
    """Projection onto the speed limit: ||x - centre|| <= v_max * dt."""
    delta = x - centre
    norm = float(np.linalg.norm(delta))
    if norm <= radius or norm == 0.0:
        return x
    return centre + delta * (radius / norm)


def min_pairwise_distance(positions: np.ndarray) -> float:
    n = len(positions)
    if n < 2:
        return float("inf")
    return min(float(np.linalg.norm(positions[i] - positions[j]))
               for i in range(n) for j in range(i + 1, n))
