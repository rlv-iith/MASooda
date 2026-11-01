"""
MASooda -- P6: STL verification (Week 1 + Week 2).

Core specification (safety):      phi_safe = G ( d_ij(t) >= d_min )  for all i != j
Quantitative (robust) semantics:  rho(t)   = min_{i != j} ( ||p_i(t) - p_j(t)|| - d_min )
                                  rho(G phi over window) = min_t rho(t)

rho > 0  -> spec satisfied with margin (metres)
rho < 0  -> violated (the pair is closer than d_min by |rho| metres)

Interface (simulation/interfaces.py, section 4.8):
    stl_monitor(trajectory_window, spec) -> STLRobustness
Synchronous, read-only. During start-up (not enough history) it returns a
NEUTRAL value and never a false violation.

trajectory_window : array-like, shape (T, N, D)   T time samples, N agents, D=2 (or 3)
"""
from __future__ import annotations

import csv
from collections import deque
from typing import Sequence, Tuple

import numpy as np

from config.load_config import get_config
from simulation.schema import (
    INSUFFICIENT_HISTORY,
    INVALID_DATA,
    NOT_ENOUGH_AGENTS,
    OK,
    STLRobustness,
    STLSpec,
)

def _pairwise_min(positions: np.ndarray) -> Tuple[float, Tuple[int, int]]:
    diff = positions[:, None, :] - positions[None, :, :]
    dist = np.linalg.norm(diff, axis=-1)
    np.fill_diagonal(dist, np.inf)
    flat = int(np.argmin(dist))
    i, j = divmod(flat, dist.shape[0])
    return float(dist[i, j]), (min(i, j), max(i, j))


def instantaneous_robustness(positions: np.ndarray, d_min: float) -> float:
    """rho(t) = min_{i!=j} ||p_i - p_j|| - d_min for one snapshot (N, D)."""
    positions = np.asarray(positions, dtype=float)
    if positions.shape[0] < 2:
        return float("inf")
    return _pairwise_min(positions)[0] - d_min


def robustness_series(window: np.ndarray, d_min: float) -> np.ndarray:
    """rho(t_k) for every sample in a (T, N, D) window. Shape (T,)."""
    window = np.asarray(window, dtype=float)
    return np.array([instantaneous_robustness(w, d_min) for w in window])


def stl_monitor(trajectory_window, spec: STLSpec) -> STLRobustness:
    """Robustness of G(d_ij >= d_min) over the supplied sliding window."""
    try:
        w = np.asarray(trajectory_window, dtype=float)
    except (ValueError, TypeError):
        return STLRobustness(0.0, False, INVALID_DATA)

    if w.ndim == 2:
        w = w[None, ...]
    elif w.ndim != 3:
        return STLRobustness(0.0, False, INVALID_DATA)

    T, N, _ = w.shape
    if T < spec.min_window_steps:
        return STLRobustness(0.0, False, INSUFFICIENT_HISTORY)
    if N < 2:
        return STLRobustness(0.0, False, NOT_ENOUGH_AGENTS)
    if not np.all(np.isfinite(w)):
        return STLRobustness(0.0, False, INVALID_DATA)

    rho = robustness_series(w, spec.d_min)
    k = int(np.argmin(rho))
    _, pair = _pairwise_min(w[k])
    val = float(rho[k])
    return STLRobustness(val, val < 0.0, OK, worst_step=k, worst_pair=pair)


class SlidingSTLMonitor:
    """Live wrapper: feed one (N, D) snapshot per tick (P1's log_state hook, Week 3)."""
    def __init__(self, spec: STLSpec, window_steps: int = 10):
        self.spec = spec
        self.buf: deque = deque(maxlen=window_steps)

    def update(self, positions: np.ndarray) -> STLRobustness:
        self.buf.append(np.asarray(positions, dtype=float).copy())
        return stl_monitor(np.stack(self.buf), self.spec)


def window_from_states(history: Sequence[Sequence]) -> np.ndarray:
    """history[t][i] is an AgentState (needs .position) -> array (T, N, D)."""
    return np.array([[a.position for a in snap] for snap in history], dtype=float)


def liveness_robustness(window: np.ndarray, destinations: np.ndarray, radius: float = 5.0) -> float:
    """Optional F(reach destination): rho = min_i max_t (radius - ||p_i(t) - dest_i||)."""
    w = np.asarray(window, float)
    d = np.linalg.norm(w - np.asarray(destinations, float)[None], axis=-1)
    return float(np.min(np.max(radius - d, axis=0)))


def load_trajectory_csv(path) -> np.ndarray:
    """CSV columns t,agent_id,x,y -> array (T, N, 2)."""
    with open(path) as f:
        rows = list(csv.DictReader(f))
    ts = sorted({float(r["t"]) for r in rows})
    ids = sorted({int(r["agent_id"]) for r in rows})
    ti = {t: k for k, t in enumerate(ts)}
    ii = {a: k for k, a in enumerate(ids)}
    out = np.full((len(ts), len(ids), 2), np.nan)
    for r in rows:
        out[ti[float(r["t"])], ii[int(r["agent_id"])]] = (float(r["x"]), float(r["y"]))
    return out


def load_spec_from_config(config: dict | None = None) -> STLSpec:
    """Build an STLSpec from safety.minimum_separation_meters and simulation.timestep_seconds."""
    cfg = config if config is not None else get_config()
    return STLSpec(
        d_min=float(cfg["safety"]["minimum_separation_meters"]),
        dt=float(cfg["simulation"]["timestep_seconds"]),
    )
