"""Layer agreement: semicircular layers, DTC allocator parity, V2V negotiation and DTC stuck resolution."""

from types import SimpleNamespace

import numpy as np

from config.load_config import get_config
from simulation.layer_agreement import (LayerAgreement, RoundContext, departure_layer, direction_layers,
                                        follow_penalty, settings)
from simulation.overseer import GlobalOverseer
from simulation.schema import AgentType, GlobalStateSnapshot

EAST = np.array([1.0, 0.0])


def drone(i, x, layer, v=12.0, y=0.0, priority=2):
    return SimpleNamespace(id=i, position=np.array([x, y, float(layer)]), velocity=np.array([v, 0.0, 0.0]),
                           altitude_layer=layer, priority=priority, type=AgentType.DELIVERY)


def agreement(**over):
    s = settings({"layer_agreement": over})
    return LayerAgreement(num_layers=7, emergency_layer=6, layer_h=30.0, d_min=8.0, d_0=12.0, h_gap=1.0,
                          half_w=10.0, capacity=15, s=s)


def context(drones, participants=None, clear=lambda a, L: True, soc=None, prio=None, remaining=1000.0):
    by = {d.id: d for d in drones}
    ids = list(by)
    return RoundContext(
        by_air=by, heard=by, visible=list(drones), adj={i: [j for j in ids if j != i] for i in ids},
        participants=participants if participants is not None else ids,
        sector_of=lambda a: 0, tangent=lambda i: EAST, remaining=lambda i: remaining, cruise=lambda i: 12.0,
        soc=(soc or (lambda i: 1.0)), priority=(prio or (lambda i: by[i].priority)), direction=lambda i: 0,
        constrained=lambda i: False, transition_clear=clear)


def test_direction_layers_follow_the_semicircular_rule():
    assert direction_layers(0, 7, 6) == [0, 2, 4]
    assert direction_layers(1, 7, 6) == [1, 3, 5]
    assert direction_layers(1, 7, 6, parity=False) == [0, 1, 2, 3, 4, 5]
    assert direction_layers(1, 1, 0) == [0]          # degenerate airspace never returns an empty set


def test_follow_penalty_matches_the_car_following_law():
    assert follow_penalty(np.inf, 12.0, 12.0, 1.0) == 0.0
    assert follow_penalty(24.0, 12.0, 12.0, 1.0) == 0.0          # (24 - 12) / 1 = cruise
    assert follow_penalty(14.0, 12.0, 12.0, 1.0) == 1.0 - 2.0 / 12.0
    assert follow_penalty(5.0, 12.0, 12.0, 1.0) == 1.0


def test_overseer_keeps_direction_parity_and_uses_upper_layers():
    cfg = get_config()
    em = int(cfg["airspace"]["emergency_layer"])
    ids = list(range(40))
    snap = GlobalStateSnapshot(timestamp=0.0, corridor_occupancy={0: 40}, agent_ids=ids,
                               agent_types={i: AgentType.DELIVERY for i in ids}, agent_priorities={i: 2 for i in ids},
                               agent_directions={i: i % 2 for i in ids})
    d = GlobalOverseer(corridors=[0], policy="priority_aware").update(snap)
    assert all(d.altitude_map[i] % 2 == i % 2 and d.altitude_map[i] != em for i in ids)
    # 20 per direction with capacity 15: the 16th eastbound drone goes to L2, not over capacity on L0
    assert sorted(set(d.altitude_map[i] for i in ids if i % 2 == 0)) == [0, 2]
    assert sorted(set(d.altitude_map[i] for i in ids if i % 2 == 1)) == [1, 3]


def test_departure_takes_the_cheapest_layer_with_a_merge_gap():
    s = settings({})
    assert departure_layer([0, 2, 4], blocked=set(), load={}, capacity=15, soc=1.0, layer_h=30.0, s=s) == 0
    assert departure_layer([0, 2, 4], blocked={0}, load={}, capacity=15, soc=1.0, layer_h=30.0, s=s) == 2
    assert departure_layer([0, 2, 4], blocked={0, 2, 4}, load={}, capacity=15, soc=1.0, layer_h=30.0, s=s) == 0


def test_a_drone_stuck_behind_traffic_climbs_to_a_free_layer():
    ag = agreement()
    a, b = drone(1, 0.0, 0, v=2.0), drone(2, 14.0, 0, v=2.0)      # 14 m gap: car-following allows 2 m/s
    moves, _ = ag.round(0.0, context([a, b], participants=[1]))
    assert [(i, L0, L1) for i, L0, L1, _ in moves] == [(1, 0, 2)]


def test_one_mover_per_target_layer_and_neighbourhood():
    ag = agreement()
    lead = drone(9, 30.0, 0, v=2.0)
    a, b = drone(1, 16.0, 0, v=2.0, y=2.0), drone(2, 15.0, 0, v=2.0, y=-2.0)   # both blocked by drone 9
    moves, _ = ag.round(0.0, context([lead, a, b], participants=[1, 2]))
    assert len(moves) == 1 and moves[0][2] == 2
    assert ag.stats.yields == 1


def test_no_move_when_the_transition_is_not_clear():
    ag = agreement()
    a, b = drone(1, 0.0, 0, v=2.0), drone(2, 14.0, 0, v=2.0)
    moves, _ = ag.round(0.0, context([a, b], participants=[1], clear=lambda d, L: False))
    assert moves == [] and ag.stats.blocked == 1


def test_low_battery_makes_climbing_more_expensive():
    full, low = agreement(), agreement()
    a, b = drone(1, 0.0, 0, v=6.0), drone(2, 18.0, 0, v=6.0)      # mild slowdown (phi = 0.5)
    m_full, _ = full.round(0.0, context([a, b], participants=[1]))
    m_low, _ = low.round(0.0, context([drone(1, 0.0, 0, v=6.0), drone(2, 18.0, 0, v=6.0)], participants=[1],
                                      soc=lambda i: 0.05))
    assert full.last_cost[1][2] < low.last_cost[1][2]


def test_stuck_request_and_dtc_resolution_by_priority():
    ag = agreement(stuck_time_s=2.0, gain_threshold=10.0)          # local agreement never fires here
    lead = drone(9, 30.0, 0, v=1.0, priority=2)
    hi, lo = drone(1, 16.0, 0, v=1.0, y=2.0, priority=0), drone(2, 15.0, 0, v=1.0, y=-2.0, priority=3)
    ctx = context([lead, hi, lo], participants=[1, 2])
    for t in (0.0, 1.0, 2.0):
        _, reqs = ag.round(t, ctx)
    assert {i for i, _ in reqs} == {1, 2} and ag.stats.stuck_requests == 2
    # one free seat (capacity 2: L2 holds one drone far ahead, L4 is full): the higher-priority drone gets it
    ag.capacity = 2
    others = [drone(8, 400.0, 2), drone(6, 500.0, 4), drone(7, 600.0, 4)]
    moves = ag.dtc_resolve(2.0, context([lead, hi, lo, *others], participants=[1, 2]))
    assert {i: L1 for i, L0, L1, _ in moves if L1 != L0} == {1: 2}
    assert ag.stats.dtc_resolved == 1 and ag.stats.dtc_denied == 1


def test_engine_spreads_layers_and_replays_deterministically():
    from simulation.route_engine import simulate_routes
    from web_sandbox.server import prepare_live_run
    p = prepare_live_run({"map": "iith", "fleet": 80, "duration_s": 60, "seed": 3})

    def run():
        return [f for f in simulate_routes(p["network"], p["flights"], p["duration"], config=p["config"],
                                           attack_config=p["attack"], overseer_link_config=p["link"],
                                           frame_every=p["stride"], spatial_index=True) if not f.get("partial")]
    a, b = run(), run()
    strip = lambda fr: [{k: v for k, v in f.items() if k != "admm"} for f in fr]   # solve ms is wall-clock
    assert strip(a) == strip(b)
    used = {L for f in a for L, st in zip(f["layer"], f["status"]) if st == 1}
    assert used - {0, 1, 6}, "traffic should use layers above L1"
    assert a[-1]["stats"]["departures_spread"] > 0
