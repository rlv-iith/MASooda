"""Generate P4 Week 3 priority-aware contention results."""

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
from simulation.overseer import GlobalOverseer
from simulation.schema import AgentType, GlobalStateSnapshot


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPOSITORY_ROOT / "outputs"
CSV_PATH = OUTPUT_DIR / "p4_week3_contention.csv"
PLOT_PATH = OUTPUT_DIR / "p4_week3_contention.png"
CORRIDORS = [0, 1, 2]
TIMESTEPS = [0.0, 2.0, 4.0, 6.0, 8.0]


def build_types(rng: np.random.Generator, count: int, type_mix: dict[str, float]) -> dict[int, AgentType]:
    names = list(type_mix)
    probabilities = np.asarray([type_mix[name] for name in names], dtype=float)
    probabilities /= probabilities.sum()
    sampled = rng.choice(names, size=count, p=probabilities)
    return {agent_id: AgentType(name) for agent_id, name in enumerate(sampled)}


def priority_for(agent_type: AgentType) -> int:
    return {AgentType.EMERGENCY: 0, AgentType.EVTOL: 1, AgentType.DELIVERY: 2}[agent_type]


def run_contention(seed: int, count: int) -> dict[str, float | int]:
    config = get_config()
    type_mix = config["scenario"]["type_mix"]
    capacity = int(config["corridors"]["capacity"])
    rng = np.random.default_rng(seed)
    agent_types = build_types(rng, count, type_mix)
    agent_ids = list(agent_types)
    agent_priorities = {agent_id: priority_for(agent_type) for agent_id, agent_type in agent_types.items()}
    overseer = GlobalOverseer(corridors=CORRIDORS, policy="priority_aware")

    previous_map: dict[int, int] = {}
    changed_counts: list[int] = []
    directive = None
    overflow = 0

    for timestamp in TIMESTEPS:
        snapshot = GlobalStateSnapshot(
            timestamp=timestamp,
            agent_ids=agent_ids,
            agent_types=agent_types,
            agent_priorities=agent_priorities,
        )
        directive = overseer.update(snapshot)
        overflow = overseer.last_overflow
        if previous_map:
            changed_counts.append(sum(
                previous_map[agent_id] != corridor
                for agent_id, corridor in directive.corridor_map.items()
            ))
        previous_map = dict(directive.corridor_map)

    loads = Counter(directive.corridor_map.values())
    emergency_ids = [agent_id for agent_id, agent_type in agent_types.items() if agent_type == AgentType.EMERGENCY]

    # Capacity is exhausted by later agents in priority/id order, so emergency
    # agents are guaranteed to be assigned because they are processed first.
    emergency_not_overflow = sum(agent_id in directive.corridor_map for agent_id in emergency_ids)
    compliance = emergency_not_overflow / len(emergency_ids) if emergency_ids else 1.0

    return {
        "N": count,
        "seed": seed,
        "corridor_0_load": loads[0],
        "corridor_1_load": loads[1],
        "corridor_2_load": loads[2],
        "overflow": overflow,
        "changed_after_first": sum(changed_counts),
        "emergency_priority_compliance": compliance,
        "capacity": capacity,
    }


def write_csv(rows: list[dict[str, float | int]]) -> None:
    fieldnames = list(rows[0])
    with CSV_PATH.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_plot(rows: list[dict[str, float | int]]) -> None:
    counts = sorted({int(row["N"]) for row in rows})
    means = {
        count: [
            np.mean([row[f"corridor_{corridor}_load"] for row in rows if int(row["N"]) == count])
            for corridor in CORRIDORS
        ]
        for count in counts
    }
    capacity = int(rows[0]["capacity"])

    x = np.arange(len(counts))
    width = 0.24
    _, axis = plt.subplots(figsize=(8, 5))
    for corridor_index, corridor in enumerate(CORRIDORS):
        axis.bar(
            x + (corridor_index - 1) * width,
            [means[count][corridor_index] for count in counts],
            width,
            label=f"Corridor {corridor}",
        )
    axis.axhline(capacity, color="black", linestyle="--", label=f"Capacity ({capacity})")
    axis.set_xticks(x, counts)
    axis.set_xlabel("Number of agents (N)")
    axis.set_ylabel("Mean final corridor load")
    axis.set_title("P4 Week 3 Priority-Aware Contention")
    axis.legend()
    axis.grid(axis="y", alpha=0.3)
    figure = axis.figure
    figure.tight_layout()
    figure.savefig(PLOT_PATH, dpi=150)
    plt.close(figure)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = [run_contention(seed, count) for count in (30, 45, 60) for seed in range(10)]
    write_csv(rows)
    write_plot(rows)
    print(f"Wrote {CSV_PATH.relative_to(REPOSITORY_ROOT)}")
    print(f"Wrote {PLOT_PATH.relative_to(REPOSITORY_ROOT)}")


if __name__ == "__main__":
    main()
