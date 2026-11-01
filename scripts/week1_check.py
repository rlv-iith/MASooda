"""Week 1 integration check: call each Week 1 function once and print OK for each."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from config.load_config import get_config
from simulation.interfaces import (
    build_comm_graph,
    inject_attack,
    overseer_update,
    resolve_conflict,
    step_dynamics,
    stl_monitor,
    update_local_behavior,
)
from simulation.mock_data import get_mock_agent_states
from simulation.schema import AttackState, GlobalStateSnapshot, STLSpec
from verification.stl_monitor import load_spec_from_config, load_trajectory_csv

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    cfg = get_config()
    dt = cfg["simulation"]["timestep_seconds"]
    agents = get_mock_agent_states()

    stepped = step_dynamics(agents[0], np.array([1.0, 0.0, 0.0]), dt)
    assert stepped.id == agents[0].id
    print("OK step_dynamics")

    graph = build_comm_graph(agents)
    assert graph.adjacency
    print("OK build_comm_graph (mock)")

    snapshot = GlobalStateSnapshot(
        timestamp=0.0,
        corridor_occupancy={0: 2, 1: 1},
        agent_ids=[a.id for a in agents],
        agent_types={a.id: a.type for a in agents},
        agent_priorities={a.id: a.priority for a in agents},
    )
    directive = overseer_update(snapshot)
    assert directive.corridor_map
    print("OK overseer_update (mock)")

    desired = update_local_behavior(agents[0], agents[1:], directive)
    assert desired.shape == (3,)
    print("OK update_local_behavior (stub)")

    resolved = resolve_conflict(agents[:2], {a.id: a.priority for a in agents[:2]})
    assert set(resolved) == {agents[0].id, agents[1].id}
    print("OK resolve_conflict")

    attack = inject_attack(agents, cfg["attack"], 0.0)
    assert isinstance(attack, AttackState) and not attack.malicious
    print("OK inject_attack (no-op)")

    trajectory = load_trajectory_csv(ROOT / "data" / "stl" / "safe_trajectory.csv")
    result = stl_monitor(trajectory, load_spec_from_config())
    assert isinstance(load_spec_from_config(), STLSpec) and not result.violation
    print(f"OK stl_monitor (safe CSV, robustness {result.value:.2f} m)")


if __name__ == "__main__":
    main()
