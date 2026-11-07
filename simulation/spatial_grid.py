"""Uniform-grid spatial hashing for the route engine's neighbour queries.

Every query here is *exact*: it returns the same set (and, where the caller
depends on it, the same order) as the brute-force O(N^2) loops it replaces,
using the same floating-point formulas. The grid only skips pairs that are
provably farther apart than the query radius.

Used for the V2V communication graph, the separation / crash safety check,
departure clearance and the minimum-separation (STL robustness) value.
"""

from __future__ import annotations

import math
from typing import Iterable

import numpy as np


class UniformGrid:
    """Bucket 2D points into square cells of side ``cell``."""

    def __init__(self, xy: np.ndarray, cell: float):
        if cell <= 0:
            raise ValueError("grid cell size must be positive")
        self.xy = np.asarray(xy, dtype=float).reshape(-1, 2)
        self.cell = float(cell)
        self.buckets: dict[tuple[int, int], list[int]] = {}
        if len(self.xy):
            keys = np.floor(self.xy / self.cell).astype(np.int64)
            for idx, (cx, cy) in enumerate(keys.tolist()):
                self.buckets.setdefault((cx, cy), []).append(idx)

    def _reach(self, radius: float) -> int:
        return max(1, int(math.ceil(radius / self.cell)))

    def candidates_near(self, x: float, y: float, radius: float) -> list[int]:
        """Indices whose cell may hold a point within ``radius`` of (x, y), ascending."""
        r = self._reach(radius)
        cx, cy = int(math.floor(x / self.cell)), int(math.floor(y / self.cell))
        out: list[int] = []
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                b = self.buckets.get((cx + dx, cy + dy))
                if b:
                    out.extend(b)
        out.sort()
        return out

    def within(self, x: float, y: float, radius: float, strict: bool = True) -> list[int]:
        """Indices with horizontal distance < radius (``strict``) or <= radius, ascending."""
        idx = self.candidates_near(x, y, radius)
        if not idx:
            return []
        d = np.linalg.norm(self.xy[idx] - np.array([x, y]), axis=1)
        keep = d < radius if strict else d <= radius
        return [i for i, k in zip(idx, keep.tolist()) if k]

    def candidate_pairs(self, radius: float) -> np.ndarray:
        """All index pairs (i < j) whose cells are within reach, sorted lexicographically.

        A superset of the pairs closer than ``radius``; callers filter by distance.
        """
        r = self._reach(radius)
        pairs: list[tuple[int, int]] = []
        for (cx, cy), members in self.buckets.items():
            for dx in range(-r, r + 1):
                for dy in range(-r, r + 1):
                    other = self.buckets.get((cx + dx, cy + dy))
                    if not other:
                        continue
                    for i in members:
                        for j in other:
                            if i < j:
                                pairs.append((i, j))
        if not pairs:
            return np.empty((0, 2), dtype=np.int64)
        arr = np.unique(np.asarray(pairs, dtype=np.int64), axis=0)  # sorted, de-duplicated
        return arr


def radius_adjacency(ids: list[int], xy: np.ndarray, radius: float, cell: float) -> dict[int, list[int]]:
    """Same result as ``comm_graph.build_radius_graph(...).adjacency``.

    Distance is ``float(np.hypot(dx, dy)) <= radius`` exactly as in the brute-force
    builder; neighbour lists are sorted by id.
    """
    adj: dict[int, list[int]] = {i: [] for i in ids}
    if len(ids) < 2:
        return adj
    grid = UniformGrid(xy, max(cell, 1e-6))
    pairs = grid.candidate_pairs(radius)
    if len(pairs):
        p = grid.xy
        d = np.hypot(p[pairs[:, 0], 0] - p[pairs[:, 1], 0], p[pairs[:, 0], 1] - p[pairs[:, 1], 1])
        for (i, j), dist in zip(pairs.tolist(), d.tolist()):
            if dist <= radius:
                adj[ids[i]].append(ids[j])
                adj[ids[j]].append(ids[i])
    for k in adj:
        adj[k].sort()
    return adj


def close_same_layer_pairs(xy: np.ndarray, layers: np.ndarray, radius: float, cell: float
                           ) -> list[tuple[int, int, float]]:
    """(u, v, horizontal distance) for u < v on the same layer with distance < radius.

    Matches ``np.argwhere(np.triu(same & (dist < radius), 1))`` ordering and the
    ``sqrt(einsum)`` distance formula used by the brute-force safety check.
    """
    if len(xy) < 2:
        return []
    grid = UniformGrid(xy, max(cell, radius, 1e-6))
    pairs = grid.candidate_pairs(radius)
    if not len(pairs):
        return []
    lay = np.asarray(layers)
    same = lay[pairs[:, 0]] == lay[pairs[:, 1]]
    pairs = pairs[same]
    if not len(pairs):
        return []
    diff = grid.xy[pairs[:, 0]] - grid.xy[pairs[:, 1]]
    dist = np.sqrt(np.einsum("ij,ij->i", diff, diff))
    keep = dist < radius
    return [(int(u), int(v), float(d)) for (u, v), d in zip(pairs[keep].tolist(), dist[keep].tolist())]


def layered_min_separation_grid(xy: np.ndarray, layers: np.ndarray, layer_height_m: float,
                                cell: float, brute_force=None) -> float:
    """Exact minimum 3D pairwise distance (altitude = layer * layer height).

    Searches pairs within a radius that doubles until at least one pair is found
    inside it; any pair farther apart horizontally than the radius is also farther
    in 3D, so the minimum over the found pairs is the global minimum. Falls back to
    ``brute_force(xy, layers, layer_height_m)`` when the radius exceeds the extent.
    """
    n = len(xy)
    if n < 2:
        return math.inf
    xy = np.asarray(xy, dtype=float)
    p3 = np.column_stack([xy, np.asarray(layers, dtype=float) * layer_height_m])
    extent = float(np.max(np.ptp(xy, axis=0))) if n > 1 else 0.0
    radius = max(cell, 1e-6)
    while radius <= 2.0 * extent + cell:
        grid = UniformGrid(xy, radius)
        pairs = grid.candidate_pairs(radius)
        if len(pairs):
            diff = p3[pairs[:, 0]] - p3[pairs[:, 1]]
            d = np.sqrt(np.einsum("ij,ij->i", diff, diff))
            best = float(d.min())
            if best <= radius:
                return best
        radius *= 2.0
    if brute_force is None:
        raise RuntimeError("no brute-force fallback supplied")
    return brute_force(xy, np.asarray(layers), layer_height_m)


def indices_sorted(values: Iterable[int]) -> list[int]:
    return sorted(values)
