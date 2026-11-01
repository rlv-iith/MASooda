"""Air traffic simulation run metrics and safety analysis (P6 Week 4)."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Sequence
import numpy as np


def robustness_series(positions: np.ndarray, d_min: float) -> np.ndarray:
    """Compute safety robustness series rho(t) for every timestep.

    Parameters
    ----------
    positions : np.ndarray
        Trajectory positions of shape (T, N, D), D >= 2.
    d_min : float
        Minimum safety separation distance in meters.

    Returns
    -------
    np.ndarray
        1D array of shape (T,) with rho[t] = min_{i<j} ||p_i - p_j|| (x,y only) - d_min.
        Returns +inf for any tick with N < 2.
    """
    pos = np.asarray(positions, dtype=float)
    if pos.ndim != 3:
        raise ValueError(f"Expected positions array of shape (T, N, >=2), got {pos.shape}")

    T, N, _ = pos.shape
    if N < 2:
        return np.full(T, float("inf"), dtype=float)

    xy = pos[:, :, :2]
    rho = np.empty(T, dtype=float)
    for t in range(T):
        diff = xy[t, :, None, :] - xy[t, None, :, :]
        dist = np.linalg.norm(diff, axis=-1)
        np.fill_diagonal(dist, np.inf)
        rho[t] = float(np.min(dist)) - float(d_min)

    return rho


def _analyze_episodes(
    times: Sequence[float] | np.ndarray,
    rho: Sequence[float] | np.ndarray,
    hold_s: float = 1.0,
) -> tuple[list[float], int, int]:
    """Helper to detect violation episodes and calculate recovery times.

    Returns
    -------
    tuple[list[float], int, int]
        (recovered_times, unrecovered_episodes_count, total_episodes_count)
    """
    times_arr = np.asarray(times, dtype=float)
    rho_arr = np.asarray(rho, dtype=float)
    n = len(rho_arr)
    if n == 0:
        return [], 0, 0

    rec_times: list[float] = []
    in_episode = False
    start_time = 0.0
    episodes_count = 0
    unrecovered_count = 0

    i = 0
    while i < n:
        if not in_episode:
            if rho_arr[i] < 0.0:
                in_episode = True
                episodes_count += 1
                start_time = times_arr[i]
            i += 1
        else:
            if rho_arr[i] >= 0.0:
                t_cand = times_arr[i]
                k = i
                violated = False
                while k < n and (times_arr[k] - t_cand) <= hold_s + 1e-6:
                    if rho_arr[k] < 0.0:
                        violated = True
                        break
                    k += 1

                if violated:
                    i = k
                else:
                    if k > i and (times_arr[k - 1] - t_cand) >= hold_s - 1e-6:
                        rec_times.append(float(t_cand - start_time))
                        in_episode = False
                        i = k
                    else:
                        break
            else:
                i += 1

    if in_episode:
        unrecovered_count = 1

    return rec_times, unrecovered_count, episodes_count


def recovery_times(
    times: Sequence[float] | np.ndarray,
    rho: Sequence[float] | np.ndarray,
    hold_s: float = 1.0,
) -> list[float]:
    """Calculate duration of all recovered violation episodes.

    An episode starts at the first tick with rho < 0 after a tick with rho >= 0 (or t0).
    Recovery is the time from episode start until rho >= 0 and stays >= 0 for hold_s seconds.
    Episodes that never recover are excluded from the returned list.
    """
    rec_times, _, _ = _analyze_episodes(times, rho, hold_s=hold_s)
    return rec_times


def graceful_degradation_score(
    violations_with_failure: float | int,
    violations_normal: float | int,
) -> float:
    """Calculate the graceful degradation score as a ratio of violations."""
    if violations_normal == 0:
        return 1.0 if violations_with_failure == 0 else float("inf")
    return float(violations_with_failure / violations_normal)


def compute_run_metrics(
    result: Any,
    config: dict | None = None,
    *args: Any,
    **kwargs: Any,
) -> dict[str, Any]:
    """Compute official summary metrics for a simulation run (Table 11)."""
    if not isinstance(config, dict):
        config = None
    if config is None:
        from config.load_config import get_config
        config = get_config()

    safety_cfg = config.get("safety", {})
    corridors_cfg = config.get("corridors", {})
    sim_cfg = config.get("simulation", {})

    d_min = float(safety_cfg.get("minimum_separation_meters", 8.0))
    exit_zone = corridors_cfg.get("exit_zone_x_meters", [1400.0, 1500.0])
    exit_x = float(exit_zone[0])

    times = np.asarray(getattr(result, "times", []), dtype=float)
    positions = np.asarray(getattr(result, "positions", np.empty((0, 0, 3))), dtype=float)

    if len(times) > 1:
        duration_s = float(times[-1] - times[0])
    else:
        duration_s = float(sim_cfg.get("duration_seconds", 0.0))

    if positions.ndim >= 2:
        num_agents = int(positions.shape[1])
    elif hasattr(result, "agent_ids"):
        num_agents = len(result.agent_ids)
    else:
        num_agents = 0

    if positions.ndim == 3 and positions.shape[0] > 0 and positions.shape[1] > 0:
        x_coords = positions[:, :, 0]
        arrivals = int(np.sum(np.any(x_coords >= exit_x, axis=0)))
    else:
        arrivals = 0

    throughput_per_s = float(arrivals / duration_s) if duration_s > 0.0 else 0.0

    if positions.ndim == 3 and positions.shape[0] > 0:
        rho = robustness_series(positions, d_min)
        safety_violation_ticks = int(np.sum(rho < 0.0))
        min_robustness_m = float(np.min(rho))
        min_separation_m = float(min_robustness_m + d_min) if np.isfinite(min_robustness_m) else float("inf")
        rec_times, unrecovered_episodes, violation_episodes = _analyze_episodes(times, rho, hold_s=1.0)
    else:
        rho = np.empty(0, dtype=float)
        safety_violation_ticks = 0
        min_robustness_m = float("inf")
        min_separation_m = float("inf")
        rec_times = []
        unrecovered_episodes = 0
        violation_episodes = 0

    mean_recovery_time_s = float(np.mean(rec_times)) if len(rec_times) > 0 else float("nan")
    max_recovery_time_s = float(np.max(rec_times)) if len(rec_times) > 0 else float("nan")

    overseer_calls = int(getattr(result, "overseer_calls", 0))
    overseer_failures = int(getattr(result, "overseer_failures", 0))

    metrics: dict[str, Any] = {
        "duration_s": float(duration_s),
        "num_agents": int(num_agents),
        "arrivals": int(arrivals),
        "throughput_per_s": float(throughput_per_s),
        "min_separation_m": float(min_separation_m),
        "min_robustness_m": float(min_robustness_m),
        "min_robustness": float(min_robustness_m),
        "safety_violation_ticks": int(safety_violation_ticks),
        "violation_episodes": int(violation_episodes),
        "unrecovered_episodes": int(unrecovered_episodes),
        "mean_recovery_time_s": float(mean_recovery_time_s),
        "max_recovery_time_s": float(max_recovery_time_s),
        "overseer_calls": int(overseer_calls),
        "overseer_failures": int(overseer_failures),
    }

    stats = getattr(result, "stats", {})
    if isinstance(stats, dict):
        metrics.update(stats)

    return metrics


def write_metrics(
    metrics: dict[str, Any],
    json_path: str | Path,
    csv_path: str | Path | None = None,
) -> None:
    """Save metrics to JSON and optional single-row CSV."""
    jpath = Path(json_path)
    jpath.parent.mkdir(parents=True, exist_ok=True)
    with open(jpath, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, default=str)

    if csv_path is not None:
        cpath = Path(csv_path)
        cpath.parent.mkdir(parents=True, exist_ok=True)
        with open(cpath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(metrics.keys()))
            writer.writeheader()
            writer.writerow(metrics)

