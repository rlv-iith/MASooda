"""P4 tests for 2.5D altitude layer assignment."""

from collections import Counter

from config.load_config import get_config
from simulation.overseer import GlobalOverseer
from simulation.schema import AgentType, GlobalStateSnapshot

CAPACITY = 15


def make_snapshot(types: dict[int, AgentType]) -> GlobalStateSnapshot:
    prio = {AgentType.EMERGENCY: 0, AgentType.EVTOL: 1, AgentType.DELIVERY: 2}
    return GlobalStateSnapshot(
        timestamp=0.0,
        agent_ids=list(types),
        agent_types=types,
        agent_priorities={a: prio[t] for a, t in types.items()},
    )


def mixed_types() -> dict[int, AgentType]:
    types = {}
    for i in range(6):
        types[i] = AgentType.EMERGENCY
    for i in range(6, 24):
        types[i] = AgentType.EVTOL
    for i in range(24, 60):
        types[i] = AgentType.DELIVERY
    return types


def test_mixed_fleet_layers():
    types = mixed_types()
    overseer = GlobalOverseer(policy="priority_aware")
    d = overseer.update(make_snapshot(types))

    emergency_layer = int(get_config()["airspace"]["emergency_layer"])
    assert all(d.altitude_map[a] == emergency_layer for a, t in types.items() if t == AgentType.EMERGENCY)
    loads = Counter((d.corridor_map[a], d.altitude_map[a]) for a in types)
    assert all(n <= CAPACITY for n in loads.values())
    normal = [a for a, t in types.items() if t != AgentType.EMERGENCY]
    assert any(d.altitude_map[a] == 1 for a in normal)
    assert overseer.last_overflow == 0


def test_normal_agents_fit_on_layer_zero():
    types = {i: AgentType.DELIVERY for i in range(30)}
    d = GlobalOverseer(policy="priority_aware").update(make_snapshot(types))
    assert set(d.altitude_map.values()) == {0}


def test_update_is_sticky_and_deterministic():
    snap = make_snapshot(mixed_types())
    overseer = GlobalOverseer(policy="priority_aware")
    first = overseer.update(snap)
    second = overseer.update(snap)
    assert second.corridor_map == first.corridor_map
    assert second.altitude_map == first.altitude_map


def test_round_robin_stays_on_layer_zero():
    d = GlobalOverseer(policy="round_robin").update(make_snapshot(mixed_types()))
    assert set(d.altitude_map.values()) == {0}
