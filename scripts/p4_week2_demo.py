"""Week 2 Global Overseer Demo (P4).

Demonstrates:
- Case A: Least-loaded allocation with unbalanced starting occupancy.
- Case B: Least-loaded allocation of 60 agents from empty occupancy.
- Case C: Round-robin allocation of 60 agents from empty occupancy.
"""

from __future__ import annotations

from global_overseer.policy import least_loaded_assign, round_robin_assign
from simulation.schema import GlobalStateSnapshot


def run_demo() -> None:
    print("=" * 70)
    print("MASooda P4 Week 2 Overseer Demo: Coarse Occupancy-Based Allocation")
    print("=" * 70)

    # -------------------------------------------------------------
    # Case A: Starting occupancy {0: 10, 1: 2, 2: 5} and 9 new agent IDs
    # -------------------------------------------------------------
    print("\n--- Case A: Least-Loaded Allocation with Initial Imbalance ---")
    initial_occ_a = {0: 10, 1: 2, 2: 5}
    new_agent_ids_a = list(range(100, 109))  # 9 new agent IDs
    snapshot_a = GlobalStateSnapshot(
        timestamp=0.0,
        corridor_occupancy=dict(initial_occ_a),
        agent_ids=new_agent_ids_a,
    )

    assignment_a = least_loaded_assign(snapshot_a)
    print("Initial occupancy:", initial_occ_a)
    print("New agent assignments:")
    for aid in sorted(assignment_a):
        print(f"  Agent {aid} -> Corridor {assignment_a[aid]}")

    final_occ_a = dict(initial_occ_a)
    for cid in assignment_a.values():
        final_occ_a[cid] += 1
    print("Final occupancy:", final_occ_a)

    # -------------------------------------------------------------
    # Case B: 60 agents from empty occupancy (least_loaded)
    # -------------------------------------------------------------
    print("\n--- Case B: Least-Loaded Allocation of 60 Agents from Empty ---")
    agent_ids_b = list(range(60))
    snapshot_b = GlobalStateSnapshot(
        timestamp=0.0,
        corridor_occupancy={0: 0, 1: 0, 2: 0},
        agent_ids=agent_ids_b,
    )

    assignment_b = least_loaded_assign(snapshot_b)
    final_occ_b = {0: 0, 1: 0, 2: 0}
    for cid in assignment_b.values():
        final_occ_b[cid] += 1
    print("Final occupancy (least_loaded):", final_occ_b)

    # -------------------------------------------------------------
    # Case C: 60 agents from empty occupancy (round_robin)
    # -------------------------------------------------------------
    print("\n--- Case C: Round-Robin Allocation of 60 Agents from Empty ---")
    snapshot_c = GlobalStateSnapshot(
        timestamp=0.0,
        corridor_occupancy={0: 0, 1: 0, 2: 0},
        agent_ids=agent_ids_b,
    )

    assignment_c = round_robin_assign(snapshot_c)
    final_occ_c = {0: 0, 1: 0, 2: 0}
    for cid in assignment_c.values():
        final_occ_c[cid] += 1
    print("Final occupancy (round_robin):", final_occ_c)
    print("\n" + "=" * 70 + "\n")


if __name__ == "__main__":
    run_demo()
