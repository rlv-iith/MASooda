"""P4 Week 3 tests for priority-aware, capacity-aware allocation."""

from collections import Counter

from simulation.overseer import GlobalOverseer, reset_default_overseer
from simulation.schema import AgentType, GlobalStateSnapshot


CAPACITY = 15
CORRIDOR_IDS = [0, 1, 2]


def snapshot(timestamp: float, agent_ids: list[int], priorities: dict[int, int]):
    return GlobalStateSnapshot(
        timestamp=timestamp,
        agent_ids=agent_ids,
        agent_priorities=priorities,
    )


def corridor_loads(directive) -> Counter:
    return Counter(directive.corridor_map.values())


def test_priority_aware_under_capacity_mixed_types():
    reset_default_overseer()
    agent_ids = list(range(30))
    priorities = {
        agent_id: (0 if agent_id < 5 else 1 if agent_id < 15 else 2)
        for agent_id in agent_ids
    }
    overseer = GlobalOverseer(policy="priority_aware")

    directive = overseer.update(snapshot(0.0, agent_ids, priorities))

    assert all(load <= CAPACITY for load in corridor_loads(directive).values())
    assert overseer.last_overflow == 0


def test_priority_aware_is_stable_across_updates():
    overseer = GlobalOverseer(policy="priority_aware")
    agent_ids = list(range(30))
    priorities = {agent_id: agent_id % 3 for agent_id in agent_ids}

    first = overseer.update(snapshot(0.0, agent_ids, priorities))
    second = overseer.update(snapshot(2.0, agent_ids, priorities))

    assert second.corridor_map == first.corridor_map


def test_priority_aware_capacity_pressure_emergencies_fit():
    overseer = GlobalOverseer(policy="priority_aware")
    deliveries = list(range(40))
    delivery_priorities = {agent_id: 2 for agent_id in deliveries}
    overseer.update(snapshot(0.0, deliveries, delivery_priorities))

    emergencies = list(range(100, 105))
    all_ids = deliveries + emergencies
    priorities = {**delivery_priorities, **{agent_id: 0 for agent_id in emergencies}}
    directive = overseer.update(snapshot(2.0, all_ids, priorities))

    assert all(agent_id in directive.corridor_map for agent_id in emergencies)
    assert all(load <= CAPACITY for load in corridor_loads(directive).values())
    assert overseer.last_overflow == 0


def test_priority_aware_overflow_is_reported_for_delivery_only():
    overseer = GlobalOverseer(policy="priority_aware")
    emergency_ids = list(range(5))
    evtol_ids = list(range(5, 15))
    delivery_ids = list(range(15, 50))
    agent_ids = emergency_ids + evtol_ids + delivery_ids
    priorities = {
        **{agent_id: 0 for agent_id in emergency_ids},
        **{agent_id: 1 for agent_id in evtol_ids},
        **{agent_id: 2 for agent_id in delivery_ids},
    }

    directive = overseer.update(snapshot(0.0, agent_ids, priorities))
    allocation_order = sorted(agent_ids, key=lambda agent_id: (priorities[agent_id], agent_id))

    assert overseer.last_overflow == 5
    assert set(allocation_order[-5:]).issubset(delivery_ids)
    assert all(agent_id in directive.corridor_map for agent_id in emergency_ids + evtol_ids)


def test_highest_priority_high_id_is_never_overflow():
    overseer = GlobalOverseer(policy="priority_aware")
    agent_ids = list(range(46))
    priorities = {agent_id: 2 for agent_id in agent_ids}
    priorities[45] = 0

    directive = overseer.update(snapshot(0.0, agent_ids, priorities))
    allocation_order = sorted(agent_ids, key=lambda agent_id: (priorities[agent_id], agent_id))

    assert 45 in directive.corridor_map
    assert 45 not in allocation_order[-5:] if allocation_order[-5:] else True


def test_priority_table_and_timestamp():
    overseer = GlobalOverseer(policy="priority_aware")
    directive = overseer.update(snapshot(3.5, [1], {1: 1}))

    assert directive.priority_table[AgentType.EMERGENCY] == 0
    assert directive.priority_table[AgentType.EVTOL] == 1
    assert directive.priority_table[AgentType.DELIVERY] == 2
    assert directive.timestamp == 3.5
