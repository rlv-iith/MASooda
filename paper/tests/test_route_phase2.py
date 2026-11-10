"""Phase 2: ADMM timer, emergency compliance, junction merging, W-MSR view, architectures, export."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from config.load_config import get_config
from conflict_resolution.adapter import resolve_all_conflicts
from conflict_resolution.profiling import summarize
from resilience.spoofer_estimate import estimate_spoofer_position, report_status
from simulation.admm_probe import ADMMProbe
from simulation.road_network import RoutePath, load_road_network
from simulation.route_centralized import centralized_commands
from simulation.route_engine import (ARCHITECTURES, TYPE_SPEED_FACTOR, initial_conditions_hash, plan_flights,
                                     simulate_routes)
from simulation.route_formation import MergeTracker, platoon_stats, route_junctions
from simulation.route_priority import EmergencyTracker
from simulation.schema import AgentState, AgentType

IITH = Path(__file__).resolve().parents[1] / "data" / "iith_campus.geojson"
MIX = {"EMERGENCY": 20, "EVTOL": 30, "DELIVERY": 50}


@pytest.fixture(scope="module")
def network():
    return load_road_network(IITH)


def _agent(i, x, y, vx=0.0, vy=0.0, layer=0, typ=AgentType.DELIVERY, prio=2):
    return AgentState(id=i, type=typ, position=np.array([x, y, float(layer)]), velocity=np.array([vx, vy, 0.0]),
                      destination=np.array([x + 100.0, y, float(layer)]), priority=prio, corridor_assignment=None,
                      altitude_layer=layer)


# ----------------------------------------------------------------------------- 2a ADMM probe
def test_admm_probe_matches_adapter_and_profiling_summary():
    from config.load_config import use_run_config
    from simulation.route_engine import _route_mode_config
    cfg = _route_mode_config(get_config())      # route mode: ADMM everywhere, not only the merge zone
    pair = [_agent(0, 0.0, 0.0, 10.0), _agent(1, 8.0, 0.0, -10.0)]
    probe = ADMMProbe(int(cfg["admm"]["maximum_iterations"]))
    with use_run_config(cfg):
        ev_probe = probe.resolve(pair, {0: 2, 1: 2}, 0.0)
        ev_plain = resolve_all_conflicts(pair, {0: 2, 1: 2})
    assert len(ev_plain) == 1
    assert [e.agents_involved for e in ev_probe] == [e.agents_involved for e in ev_plain]
    for a, b in zip(ev_probe, ev_plain):
        assert a.converged == b.converged
        for k in a.resolution:
            np.testing.assert_allclose(a.resolution[k], b.resolution[k])
    out = probe.frame()
    assert out["admm"]["groups"] == len(ev_plain) and out["admm"]["solves"] == len(ev_plain)
    assert set(out["neg"]) == {"0", "1"} and out["neg"]["0"]["partners"] == [1]
    assert probe.frame()["admm"]["solves"] == 0          # window resets, run totals stay
    assert probe.summary()["solves"] == len(ev_plain)


def test_admm_probe_p95_equals_profiling_summarize():
    probe = ADMMProbe(50)
    records = [{"iterations": it, "solve_time_s": 0.001 * (1 + it % 7), "converged": it < 40} for it in
               [3, 9, 9, 10, 12, 4, 40, 7, 8, 8, 11, 2, 5, 9, 10, 10, 6, 13, 45, 9]]
    for r in records:
        probe._add_record(r)
    ref = summarize(records)
    got = probe.summary()
    assert got["it_p95"] == ref["p95_iterations"] and got["it_max"] == ref["max_iterations"]
    assert got["it_mean"] == pytest.approx(ref["mean_iterations"], abs=0.01)
    assert got["ms_p95"] == pytest.approx(ref["p95_solve_ms"], rel=0.13)   # log-histogram bin width


# ----------------------------------------------------------------------------- 2b emergency compliance
def _flight(i, typ, length, depart=0.0):
    route = RoutePath(np.array([[0.0, 0.0], [length, 0.0]]))
    return SimpleNamespace(agent_id=i, type=typ, route=route, depart_s=depart)


def test_emergency_tracker_definitions():
    flights = [_flight(0, AgentType.EMERGENCY, 1440.0, depart=5.0), _flight(1, AgentType.DELIVERY, 500.0)]
    speed = lambda f: 12.0 * TYPE_SPEED_FACTOR[f.type]
    tr = EmergencyTracker(flights, speed, emergency_layer=2, capacity=1, dt=0.1)
    assert 0 in tr and 1 not in tr
    snap = tr.snapshot(0.0)["per"]["0"]
    assert snap["nominal_s"] == pytest.approx(1440.0 / 14.4)       # type's own cruise speed
    tr.on_hold(0); tr.on_shift(0); tr.on_shift(1); tr.on_gate(0)
    em, other = _agent(0, 0, 0, layer=2), _agent(1, 5, 0, layer=2)
    cell = lambda a: (0, int(a.altitude_layer))
    tr.on_dtc_update([em], cell)                 # alone in its cell -> compliant
    tr.on_dtc_update([em, other], cell)          # 2 > capacity 1 -> not compliant
    tr.on_tick([em]); tr.on_tick([_agent(0, 0, 0, layer=1)])
    tr.on_land(0, 115.0)
    s = tr.snapshot(115.0)
    p = s["per"]["0"]
    assert s["rate"] == 0.5 and p["compliance"] == 0.5
    assert (p["holds"], p["shifts"], p["gated"], p["yields"]) == (1, 1, 1, 3)
    assert p["on_layer"] == 0.5
    assert p["travel_s"] == pytest.approx(110.0) and p["delay_s"] == pytest.approx(110.0 - 100.0)


# ----------------------------------------------------------------------------- 2c merging + platoons
def test_route_junctions_are_degree3_nodes(network):
    flights = plan_flights(network, 12, MIX, 3, 30.0)
    for f in flights:
        for s_j, xy, d_out, seg_len in route_junctions(network, f.route):
            node = int(np.argmin(np.linalg.norm(network.nodes - xy, axis=1)))
            assert len(network.adjacency[node]) >= 3
            assert 0.0 < s_j < f.route.length and seg_len > 0 and abs(np.linalg.norm(d_out) - 1) < 1e-9


def test_merge_gap_rule_and_outcomes():
    cfg = get_config()
    # straight road with a junction at x = 100 (fake network: node degree 3)
    net = SimpleNamespace(nodes=np.array([[0.0, 0.0], [100.0, 0.0], [200.0, 0.0], [100.0, 80.0]]),
                          adjacency={0: [1], 1: [0, 2, 3], 2: [1], 3: [1]})
    flight = SimpleNamespace(agent_id=0, route=RoutePath(np.array([[0.0, 0.0], [100.0, 0.0], [200.0, 0.0]])))
    mt = MergeTracker(net, [flight], cfg)
    gap, k_v = float(cfg["local_behavior"]["merge_gap"]), float(cfg["local_behavior"]["k_v"])
    assert mt.factor(0, 20.0, 0, [])[0] == 1.0                       # outside the merge zone
    blocker = _agent(9, 100.0 + gap / 2, 0.0, vx=10.0)               # just past the junction, same direction
    f, why = mt.factor(0, 95.0, 0, [blocker])
    assert f == pytest.approx(1.0 - k_v) and "merge" in why.lower()
    assert mt.factor(0, 95.0, 0, [_agent(9, 100.0 + gap / 2, 0.0, vx=-10.0)])[0] == 1.0   # opposing flow
    assert mt.factor(0, 95.0, 1, [blocker])[0] == 1.0                                       # other layer
    mt.factor(0, 101.0, 0, [])                                         # crossed with the gap open at the end
    assert (mt.success, mt.failed) == (1, 0)
    out = mt.frame()
    assert out["attempts"] == 1 and out["rate"] == 1.0 and out["yield_ticks"] == 1


def test_platoon_chains():
    leaders = {2: (1, 20.0, 10.0), 3: (2, 30.0, 10.0), 5: (4, 25.0, 12.0)}
    out = platoon_stats(leaders, d_0=12.0, h=1.0)
    assert out["platoons"] == 2 and out["in_platoon"] == 5 and out["mean_size"] == 2.5
    assert out["headway_s"] == pytest.approx(np.mean([2.0, 3.0, 25 / 12]), abs=0.01)
    assert platoon_stats({}, 12.0, 1.0)["platoons"] == 0


# ----------------------------------------------------------------------------- 2e W-MSR spoofer view
def test_spoofer_estimate_trims_outlier_and_falls_back_to_median():
    est = estimate_spoofer_position([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [1.0, 1.0], [100.0, 100.0]], f=1)
    assert np.all(np.abs(est - 0.5) <= 0.5)
    np.testing.assert_allclose(estimate_spoofer_position([[2.0, 4.0], [4.0, 8.0]], f=1), [3.0, 6.0])
    assert estimate_spoofer_position([], f=1) is None
    assert report_status([1, 2, 3], dropped_ids=[2], checked_ids=[1, 2]) == [[1, "kept"], [2, "corrected"], [3, "unverified"]]


# ----------------------------------------------------------------------------- 2f centralized controller
def test_centralized_priority_weighted_separation():
    cfg = get_config()
    route = RoutePath(np.array([[0.0, 0.0], [500.0, 0.0]]))
    hi = _agent(0, 100.0, 5.0, vx=10.0, typ=AgentType.EMERGENCY, prio=0)
    lo = _agent(1, 100.0, -5.0, vx=10.0, prio=2)
    cmd = centralized_commands({0: hi, 1: lo}, {0: route, 1: route}, {0: 100.0, 1: 100.0},
                               lambda a, rem: 12.0, cfg, lane=0.0, cell=40.0)
    alone = centralized_commands({1: lo}, {1: route}, {1: 100.0}, lambda a, rem: 12.0, cfg, lane=0.0, cell=40.0)
    alone_hi = centralized_commands({0: hi}, {0: route}, {0: 100.0}, lambda a, rem: 12.0, cfg, lane=0.0, cell=40.0)
    assert cmd[1][1] < alone[1][1] - 1e-6               # lower priority is pushed away (down)
    np.testing.assert_allclose(cmd[0], alone_hi[0])     # higher priority is not pushed
    assert np.linalg.norm(cmd[1][:2]) <= float(cfg["safety"]["maximum_velocity_meters_per_second"]) + 1e-9


# ----------------------------------------------------------------------------- engine integration
def _run(network, flights, arch="hierarchical", attack=None, dur=60.0, **kw):
    frames = [f for f in simulate_routes(network, flights, dur, attack_config=attack, frame_every=5,
                                         architecture=arch, **kw) if not f.get("partial")]
    return frames


def test_architectures_share_initial_conditions_and_differ_in_control(network):
    flights = plan_flights(network, 30, MIX, 7, 20.0)
    h = initial_conditions_hash(flights, 7)
    assert h == initial_conditions_hash(plan_flights(network, 30, MIX, 7, 20.0), 7)
    with pytest.raises(ValueError):
        next(simulate_routes(network, flights, 5.0, architecture="anarchy"))
    first = {}
    for arch in ARCHITECTURES:
        frames = _run(network, flights, arch, dur=40.0)
        first[arch] = (frames[0]["x"], frames[0]["y"], frames[0]["status"])
        last = frames[-1]
        if arch == "centralized":
            assert last["admm"]["run"]["groups"] == 0 and last["merge"] is None
        else:
            assert last["merge"] is not None
        assert last["dtc"]["enabled"] == (arch in ("hierarchical", "centralized"))
    assert len({str(v) for v in first.values()}) == 1      # identical initial frame in every architecture


def test_phase2_frames_are_deterministic(network):
    flights = plan_flights(network, 30, MIX, 11, 20.0)
    attack = {"enabled": True, "malicious_ids": [f.agent_id for f in flights if f.depart_s < 5][:2],
              "start_time_seconds": 5.0, "offset_meters": [25.0, 25.0]}

    def strip(fr):  # wall-clock solve times are not part of the deterministic output
        out = {k: v for k, v in fr.items() if k not in ("admm",)}
        out["admm_it"] = (fr["admm"]["groups"], fr["admm"]["it_mean"], fr["admm"]["run"]["it_p95"])
        return out

    a = [strip(f) for f in _run(network, flights, attack=attack)]
    b = [strip(f) for f in _run(network, flights, attack=attack)]
    assert a == b
    last = a[-1]
    assert last["prio"]["count"] == sum(1 for f in flights if f.type == AgentType.EMERGENCY)
    assert set(last["spoof"]) <= {str(m) for m in attack["malicious_ids"]}
    for v in last["spoof"].values():
        assert v["err_rep"] > 0 and (v["est"] is None) == (v["n"] == 0)


def test_junction_merge_off_has_no_merge_output(network):
    flights = plan_flights(network, 10, MIX, 2, 10.0)
    frames = _run(network, flights, dur=20.0, junction_merge=False)
    assert all(f["merge"] is None for f in frames)


# ----------------------------------------------------------------------------- 2g export / replay
def test_export_round_trip_through_the_worker():
    from web_sandbox.run_export import build_export, validate_export
    from web_sandbox.server import STATIC, LiveRun, _run_worker, prepare_live_run
    assert "/prototype" not in STATIC
    prepared = prepare_live_run({"map": "iith", "fleet": 10, "duration_s": 20, "seed": 4, "architecture": "decentralized"})
    assert (prepared["use_overseer"], prepared["use_admm"], prepared["defended"]) == (False, True, True)
    run = LiveRun("x", {"fleet": 10}, 10_000)
    _run_worker(run, prepared)
    frames, _ = run.store.since(0, 10_000)
    exp = build_export({"flights": [{"id": f.agent_id} for f in prepared["flights"]], "ic_hash": prepared["ic_hash"]},
                       run.request, prepared["config"], frames, [], complete=run.done)
    validate_export(exp)
    assert len(exp["kpis"]) == len(frames) and exp["events"] == [e for f in frames for e in f["events"]]
    assert exp["kpis"][-1]["arrivals"] == frames[-1].get("stats", {}).get("arrivals", exp["kpis"][-1]["arrivals"])
    with pytest.raises(ValueError):
        validate_export({"format": "something-else"})
    bad = dict(exp, manifest={"flights": [{"id": 0}]})
    with pytest.raises(ValueError):
        validate_export(bad)
    with pytest.raises(ValueError):
        prepare_live_run({"fleet": 5, "architecture": "anarchy"})


def test_prio_sent_on_change_and_carried_through_thinning():
    from web_sandbox.streaming import FrameStore, compact_frame
    store, prev = FrameStore(max_frames=16), None
    base = {"t": 0.0, "x": [0.0], "y": [0.0], "layer": [0], "status": [1], "speed": [0.0], "progress": [0.0], "edges": []}
    for k in range(100):
        prio = {"rate": (k // 10) / 10}
        f = compact_frame(dict(base, t=k * 0.2, prio=prio), k, None, 600, prev)
        assert ("prio" in f) == (prio != prev)
        prev = prio
        store.append(f)
    frames, _ = store.since(0, 1000)
    carried = None
    for f in frames:
        carried = f.get("prio", carried)
    assert carried == {"rate": 0.9}
