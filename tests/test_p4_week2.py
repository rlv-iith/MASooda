"""P4 Week 2 unit tests: Real overseer coarse occupancy policy and snapshot building."""

from __future__ import annotations

import pytest

from global_overseer.policy import (
    least_loaded_assign,
    real_overseer_update,
    round_robin_assign,
    snapshot_from_agents,
)
from simulation.schema import AgentState, AgentType, GlobalStateSnapshot


def test_least_loaded_sends_first_new_agent_to_emptiest_corridor():
    snapshot = GlobalStateSnapshot(
        timestamp=0.0,
        corridor_occupancy={0: 10, 1: 2, 2: 5},
        agent_ids=[0],
    )
    assignment = least_loaded_assign(snapshot)
    assert assignment[0] == 1


def test_60_agents_from_empty_occupancy_gives_20_per_corridor():
    snapshot = GlobalStateSnapshot(
        timestamp=0.0,
        corridor_occupancy={0: 0, 1: 0, 2: 0},
        agent_ids=list(range(60)),
    )
    assignment = least_loaded_assign(snapshot)
    counts = {0: 0, 1: 0, 2: 0}
    for cid in assignment.values():
        counts[cid] += 1
    assert counts == {0: 20, 1: 20, 2: 20}


def test_ties_go_to_smallest_corridor_id():
    # All corridors tied at count 5; next agent should get corridor 0
    snapshot1 = GlobalStateSnapshot(
        timestamp=0.0,
        corridor_occupancy={0: 5, 1: 5, 2: 5},
        agent_ids=[99],
    )
    assignment1 = least_loaded_assign(snapshot1)
    assert assignment1[99] == 0

    # Corridors 1 and 2 tied at count 3, corridor 0 has 5; next agent gets corridor 1
    snapshot2 = GlobalStateSnapshot(
        timestamp=0.0,
        corridor_occupancy={0: 5, 1: 3, 2: 3},
        agent_ids=[42],
    )
    assignment2 = least_loaded_assign(snapshot2)
    assert assignment2[42] == 1


def test_round_robin_gives_expected_pattern():
    snapshot = GlobalStateSnapshot(
        timestamp=0.0,
        corridor_occupancy={},
        agent_ids=[0, 1, 2, 3, 4, 5],
    )
    assignment = round_robin_assign(snapshot)
    expected = {0: 0, 1: 1, 2: 2, 3: 0, 4: 1, 5: 2}
    assert assignment == expected


def test_every_agent_in_corridor_map_and_valid_corridor():
    agent_ids = [10, 25, 7, 33]
    snapshot = GlobalStateSnapshot(
        timestamp=5.0,
        corridor_occupancy={0: 2, 1: 1, 2: 3},
        agent_ids=agent_ids,
    )
    directive = real_overseer_update(snapshot)
    assert set(directive.corridor_map.keys()) == set(agent_ids)
    assert all(cid in {0, 1, 2} for cid in directive.corridor_map.values())


def test_timestamp_copied_and_snapshot_unchanged():
    snapshot = GlobalStateSnapshot(
        timestamp=42.5,
        corridor_occupancy={0: 4, 1: 2, 2: 3},
        agent_ids=[1, 2, 3],
        agent_types={1: AgentType.EMERGENCY, 2: AgentType.EVTOL, 3: AgentType.DELIVERY},
        agent_priorities={1: 0, 2: 1, 3: 2},
    )
    occ_before = dict(snapshot.corridor_occupancy)
    ids_before = list(snapshot.agent_ids)

    directive = real_overseer_update(snapshot)

    assert directive.timestamp == 42.5
    assert snapshot.corridor_occupancy == occ_before
    assert snapshot.agent_ids == ids_before
    assert snapshot.timestamp == 42.5


def test_negative_timestamp_raises_value_error():
    snapshot = GlobalStateSnapshot(timestamp=-5.0, agent_ids=[1])
    with pytest.raises(ValueError, match="timestamp"):
        real_overseer_update(snapshot)


def test_snapshot_from_agents_counts_corridors_correctly():
    # 3 hand-made agents: 1 in corridor 0, 1 in corridor 2, 1 unassigned (None)
    a1 = AgentState(id=1, type=AgentType.EMERGENCY, corridor_assignment=0)
    a2 = AgentState(id=2, type=AgentType.EVTOL, corridor_assignment=2)
    a3 = AgentState(id=3, type=AgentType.DELIVERY, corridor_assignment=None)

    snapshot = snapshot_from_agents([a1, a2, a3], t=10.0)

    assert snapshot.timestamp == 10.0
    assert snapshot.corridor_occupancy == {0: 1, 1: 0, 2: 1}
    assert snapshot.agent_ids == [1, 2, 3]
    assert snapshot.agent_types == {
        1: AgentType.EMERGENCY,
        2: AgentType.EVTOL,
        3: AgentType.DELIVERY,
    }
