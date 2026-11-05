"""Experiment runner and standardized metric collector for MASooda (Week 5).

Supports running hierarchical, centralized, and decentralized_undefended
architectures through a unified interface with standardized output schemas
and verified identical initial conditions.
"""

from __future__ import annotations

from collections import defaultdict
import csv
import hashlib
import json
from pathlib import Path
import time
from typing import Any, Sequence
import numpy as np

from config.load_config import get_config
from local_behavior.boids import reset_local_behavior_cache
from simulation.logger import TrajectoryLogger
from simulation.overseer import reset_default_overseer
from simulation.scenario import make_initial_agents
from verification.live_monitor import LiveSTLMonitor
from verification.metrics import compute_run_metrics, robustness_series


ARCHITECTURES = ("hierarchical", "centralized", "decentralized_undefended")

STANDARD_COLUMNS = [
    "architecture",
    "scenario",
    "seed",
    "num_agents",
    "duration_s",
    "attack_enabled",
    "link_failure",
    "initial_conditions_hash",
    "throughput_per_s",
    "arrivals",
    "safety_violation_ticks",
    "violation_episodes",
    "mean_recovery_time_s",
    "max_recovery_time_s",
    "min_robustness_m",
    "min_separation_m",
    "admm_events",
    "admm_nonconverged",
    "reports_dropped",
    "overseer_calls",
    "overseer_failures",
    "wall_time_s",
]


def get_runner(name: str):
    """Retrieve the simulation runner callable for the specified architecture."""
    if name == "hierarchical":
        from simulation.engine import run_simulation

        def run_hierarchical(
            agents,
            duration_s=None,
            loggers=None,
            attack_config=None,
            overseer_link_config=None,
        ):
            return run_simulation(
                agents,
                duration_s=duration_s,
                loggers=loggers,
                use_overseer=True,
                use_admm=True,
                attack_config=attack_config,
                defended=True,
                overseer_link_config=overseer_link_config,
            )

        return run_hierarchical

    elif name == "centralized":
        try:
            from simulation.centralized import run_centralized
            return run_centralized
        except ImportError as e:
            raise RuntimeError(f"architecture '{name}' is not merged into this branch yet") from e

    elif name == "decentralized_undefended":
        try:
            from resilience.decentralized_undefended import run_decentralized_undefended
            return run_decentralized_undefended
        except ImportError as e:
            raise RuntimeError(f"architecture '{name}' is not merged into this branch yet") from e

    else:
        raise ValueError(f"Unknown architecture: '{name}'")


def initial_conditions_hash(agents: Sequence[Any]) -> str:
    """Compute sha256 of sorted initial conditions JSON."""
    sorted_agents = sorted(agents, key=lambda a: a.id)
    records = []
    for a in sorted_agents:
        type_val = a.type.value if hasattr(a.type, "value") else str(a.type)
        pos = [round(float(x), 6) for x in a.position]
        dest = None if a.destination is None else [round(float(x), 6) for x in a.destination]
        layer = int(getattr(a, "altitude_layer", 0))
        corr = None if getattr(a, "corridor_assignment", None) is None else int(a.corridor_assignment)
        pri = int(getattr(a, "priority", 2))
        records.append([
            int(a.id),
            type_val,
            pri,
            pos,
            dest,
            layer,
            corr,
        ])
    payload = json.dumps(records, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_run_row(result: Any, metrics: dict, info: dict) -> dict:
    """Build a dictionary matching STANDARD_COLUMNS exactly."""
    stats = getattr(result, "stats", {})
    if not isinstance(stats, dict):
        stats = {}

    row = {
        "architecture": str(info.get("architecture", "")),
        "scenario": str(info.get("scenario", "")),
        "seed": int(info.get("seed", 0)),
        "num_agents": int(info.get("num_agents", 0)),
        "duration_s": float(info.get("duration_s", 0.0)),
        "attack_enabled": bool(info.get("attack_enabled", False)),
        "link_failure": bool(info.get("link_failure", False)),
        "initial_conditions_hash": str(info.get("initial_conditions_hash", "")),
        "throughput_per_s": float(metrics.get("throughput_per_s", 0.0)),
        "arrivals": int(metrics.get("arrivals", 0)),
        "safety_violation_ticks": int(metrics.get("safety_violation_ticks", 0)),
        "violation_episodes": int(metrics.get("violation_episodes", 0)),
        "mean_recovery_time_s": float(metrics.get("mean_recovery_time_s", float("nan"))),
        "max_recovery_time_s": float(metrics.get("max_recovery_time_s", float("nan"))),
        "min_robustness_m": float(metrics.get("min_robustness_m", metrics.get("min_robustness", float("nan")))),
        "min_separation_m": float(metrics.get("min_separation_m", float("nan"))),
        "admm_events": int(stats.get("admm_events", metrics.get("admm_events", 0))),
        "admm_nonconverged": int(stats.get("admm_nonconverged", metrics.get("admm_nonconverged", 0))),
        "reports_dropped": int(stats.get("reports_dropped", metrics.get("reports_dropped", 0))),
        "overseer_calls": int(getattr(result, "overseer_calls", metrics.get("overseer_calls", 0))),
        "overseer_failures": int(getattr(result, "overseer_failures", metrics.get("overseer_failures", 0))),
        "wall_time_s": float(info.get("wall_time_s", 0.0)),
    }
    return {col: row[col] for col in STANDARD_COLUMNS}


def run_experiment(
    architecture: str,
    n_agents: int,
    seed: int,
    duration_s: float | None = None,
    attack_enabled: bool = False,
    link_failure: bool = False,
    scenario: str = "custom",
    return_series: bool = False,
):
    """Execute forward simulation for one experiment configuration."""
    reset_default_overseer()
    reset_local_behavior_cache()

    cfg = get_config()
    if duration_s is None:
        duration_s = float(cfg["simulation"]["duration_seconds"])

    agents = make_initial_agents(n_agents, seed=seed)
    h = initial_conditions_hash(agents)

    attack_config = {**cfg.get("attack", {}), "enabled": attack_enabled}

    link_failure_cfg = cfg.get("overseer", {}).get("link_failure", {})
    if link_failure:
        overseer_link_config = {
            "enabled": True,
            "down_start_seconds": float(link_failure_cfg.get("down_start_seconds", 90.0)),
            "down_end_seconds": float(link_failure_cfg.get("down_end_seconds", 120.0)),
        }
    else:
        overseer_link_config = {"enabled": False}

    monitor = LiveSTLMonitor(console_every_seconds=1e9)
    traj = TrajectoryLogger()

    runner = get_runner(architecture)
    start_time = time.perf_counter()
    result = runner(
        agents,
        duration_s=duration_s,
        loggers=[traj, monitor],
        attack_config=attack_config,
        overseer_link_config=overseer_link_config,
    )
    wall_time_s = time.perf_counter() - start_time

    metrics = compute_run_metrics(result, config=cfg)
    info = {
        "architecture": architecture,
        "scenario": scenario,
        "seed": seed,
        "num_agents": n_agents,
        "duration_s": duration_s,
        "attack_enabled": attack_enabled,
        "link_failure": link_failure,
        "initial_conditions_hash": h,
        "wall_time_s": wall_time_s,
    }
    row = build_run_row(result, metrics, info)

    if return_series:
        d_min = float(cfg["safety"]["minimum_separation_meters"])
        series = robustness_series(result.positions, d_min)
        return row, (result.times, series)
    return row


def write_rows(rows: Sequence[dict], path: str | Path) -> None:
    """Write rows to a CSV file matching STANDARD_COLUMNS header."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=STANDARD_COLUMNS)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def check_identical_conditions(rows: Sequence[dict]) -> tuple[bool, str]:
    """Verify that rows with the same (seed, num_agents) share one initial_conditions_hash."""
    hashes_by_group: dict[tuple[int, int], set[str]] = defaultdict(set)
    for r in rows:
        key = (r["seed"], r["num_agents"])
        hashes_by_group[key].add(r["initial_conditions_hash"])

    for (seed, n), hashes in hashes_by_group.items():
        if len(hashes) > 1:
            return False, f"Mismatch in initial conditions for (seed={seed}, num_agents={n}): {hashes}"

    return True, "All groups with matching (seed, num_agents) have identical initial conditions."

