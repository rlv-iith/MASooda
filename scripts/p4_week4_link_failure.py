from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPOSITORY_ROOT))

import matplotlib.pyplot as plt
import numpy as np

from config.load_config import get_config
from local_behavior.boids import _last_corridor, corridor_of
from simulation.interfaces import build_comm_graph, step_dynamics, update_local_behavior
from simulation.overseer import reset_default_overseer
from simulation.overseer_link import OverseerLink
from simulation.scenario import make_initial_agents
from simulation.schema import GlobalStateSnapshot


OUTPUT_DIR = REPOSITORY_ROOT / "outputs"
CSV_PATH = OUTPUT_DIR / "p4_week4_link_failure.csv"
PLOT_PATH = OUTPUT_DIR / "p4_week4_link_failure.png"


def _min_pairwise_distance(agents) -> float:
    if len(agents) < 2:
        return float("inf")
    positions = np.asarray([agent.position[:2] for agent in agents], dtype=float)
    differences = positions[:, None, :] - positions[None, :, :]
    distances = np.linalg.norm(differences, axis=2)
    np.fill_diagonal(distances, np.inf)
    return float(np.min(distances))


def _run_case(link_config: dict, duration: float, n_agents: int, case: str) -> list[dict]:
    config = get_config()
    dt = float(config["simulation"]["timestep_seconds"])
    tau_v = float(config["control"]["velocity_time_constant_seconds"])
    capacity = int(config["corridors"]["capacity"])
    reset_default_overseer()
    _last_corridor.clear()

    agents = make_initial_agents(n_agents, seed=42)
    link = OverseerLink(link_config)
    cached_directive = None
    directive_timestamp = None
    rows: list[dict] = []
    steps = int(round(duration / dt))

    for step in range(steps + 1):
        t = round(step * dt, 10)

        if abs(t / 2.0 - round(t / 2.0)) < 1e-7:
            occupancy = Counter(corridor_of(float(agent.position[1])) for agent in agents)
            snapshot = GlobalStateSnapshot(
                timestamp=t,
                corridor_occupancy={corridor: occupancy[corridor] for corridor in range(3)},
                agent_ids=[agent.id for agent in agents],
                agent_types={agent.id: agent.type for agent in agents},
                agent_priorities={agent.id: agent.priority for agent in agents},
            )
            directive = link.request(snapshot, t)
            if directive is not None:
                cached_directive = directive
                directive_timestamp = t

        staleness = t if directive_timestamp is None else t - directive_timestamp
        staleness = max(0.0, staleness)
        min_distance = _min_pairwise_distance(agents)
        occupancy = Counter(corridor_of(float(agent.position[1])) for agent in agents)
        max_load = max(occupancy.values(), default=0)

        rows.append({
            "case": case,
            "t": t,
            "link_up": int(link.is_up(t)),
            "staleness": staleness,
            "min_distance": min_distance,
            "max_corridor_load_ratio": max_load / capacity,
        })

        if step == steps:
            break

        graph = build_comm_graph(agents)
        agents_by_id = {agent.id: agent for agent in agents}
        next_agents = []
        for agent in agents:
            neighbor_ids = graph.neighbors(agent.id)
            neighbours = [agents_by_id[nid] for nid in neighbor_ids if nid in agents_by_id]
            desired_velocity = update_local_behavior(agent, neighbours, cached_directive)
            acceleration = (desired_velocity - agent.velocity) / tau_v
            new_agent = step_dynamics(agent, acceleration, dt)
            new_agent.neighbor_set = neighbor_ids
            next_agents.append(new_agent)
        agents = next_agents

    return rows


def run(link_config: dict, duration: float = 150.0, n_agents: int = 60) -> list[dict]:
    """Run one failure case and return its per-tick metrics."""
    return _run_case(link_config, duration, n_agents, "failure")


def _write_csv(rows: list[dict]) -> None:
    with CSV_PATH.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _write_plot(normal_rows: list[dict], failure_rows: list[dict]) -> None:
    _, axes = plt.subplots(2, 1, figsize=(10, 8), sharex=True)
    for name, rows, color in (("Normal", normal_rows, "tab:blue"), ("Failure", failure_rows, "tab:red")):
        axes[0].plot([row["t"] for row in rows], [row["staleness"] for row in rows], label=name, color=color)
        axes[1].plot([row["t"] for row in rows], [row["min_distance"] for row in rows], label=name, color=color)

    for axis in axes:
        axis.axvspan(60.0, 100.0, color="orange", alpha=0.2, label="Down window")
        axis.grid(alpha=0.3)
    axes[0].axhline(0.0, color="black", linewidth=0.8)
    axes[1].axhline(8.0, color="black", linestyle="--", linewidth=1.0, label="8 m minimum")
    axes[0].set_ylabel("Directive staleness (s)")
    axes[0].set_title("Overseer link: cached directive and separation")
    axes[1].set_ylabel("Minimum pairwise distance (m)")
    axes[1].set_xlabel("Simulation time (s)")
    axes[0].legend(loc="upper left")
    axes[1].legend(loc="upper right")
    plt.tight_layout()
    plt.savefig(PLOT_PATH, dpi=150)
    plt.close()


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    normal_rows = _run_case({"enabled": False}, 150.0, 60, "normal")
    failure_rows = _run_case({
        "enabled": True,
        "down_start_seconds": 60.0,
        "down_end_seconds": 100.0,
    }, 150.0, 60, "failure")
    _write_csv(normal_rows + failure_rows)
    _write_plot(normal_rows, failure_rows)

    normal_violations = sum(row["min_distance"] < 8.0 for row in normal_rows)
    failure_violations = sum(row["min_distance"] < 8.0 for row in failure_rows)
    normal_max_staleness = max(row["staleness"] for row in normal_rows)
    failure_max_staleness = max(row["staleness"] for row in failure_rows)
    print(f"Normal max staleness: {normal_max_staleness:.3f} s")
    print(f"Failure max staleness: {failure_max_staleness:.3f} s")
    print(f"Normal ticks below 8 m: {normal_violations}")
    print(f"Failure ticks below 8 m: {failure_violations}")
    if normal_violations == 0:
        ratio = 1.0 if failure_violations == 0 else "inf"
    else:
        ratio = failure_violations / normal_violations
    print(f"Graceful-degradation ratio: {ratio}")


if __name__ == "__main__":
    main()
