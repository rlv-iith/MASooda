"""Map-constrained route mode: road graph, boundary conditions, governance hooks."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from config.load_config import get_config
from simulation.road_network import GeoFrame, RoutePath, _segment_distance, _corridor_segments, load_road_network
from simulation.route_engine import (
    AIRBORNE, _layer_transition_clear, layered_min_separation, plan_flights, simulate_routes,
)
from simulation.schema import AgentState, AgentType

ROADS = Path(__file__).resolve().parents[1] / "data" / "hyderabad_roads_sample.geojson"


@pytest.fixture(scope="module")
def network():
    return load_road_network(ROADS)


def test_geoframe_round_trip():
    frame = GeoFrame(78.365, 17.44)
    x, y = frame.to_local(78.37, 17.445)
    lon, lat = frame.to_geo(x, y)
    assert lon == pytest.approx(78.37, abs=1e-9) and lat == pytest.approx(17.445, abs=1e-9)
    assert 500 < x < 560 and 550 < y < 560  # ~0.005 deg in metres at 17.44 N


def test_network_is_connected_and_pads_are_set_back(network):
    assert len(network.nodes) > 500
    seen, stack = {0}, [0]
    while stack:
        for v, _ in network.adjacency[stack.pop()]:
            if v not in seen:
                seen.add(v)
                stack.append(v)
    assert len(seen) == len(network.nodes)
    seg_a, seg_b = _corridor_segments(network)
    for vp in network.vertiports:
        clearance = _segment_distance(np.asarray(vp.position), seg_a, seg_b).min()
        assert clearance > 15.0, f"{vp.id} pad sits on a corridor"


def test_route_path_projection():
    path = RoutePath(np.array([[0.0, 0.0], [100.0, 0.0], [100.0, 100.0]]))
    assert path.length == pytest.approx(200.0)
    s, q, tan = path.project(np.array([50.0, 3.0]), 40.0)
    assert s == pytest.approx(50.0) and q == pytest.approx([50.0, 0.0]) and tan == pytest.approx([1.0, 0.0])


def test_flights_follow_corridor_graph(network):
    flights = plan_flights(network, 12, {"EMERGENCY": 1, "EVTOL": 1, "DELIVERY": 1}, 5, 10.0)
    assert len(flights) == 12
    pads = {vp.id: vp for vp in network.vertiports}
    for f in flights:
        assert f.origin != f.destination
        assert f.route.points[0] == pytest.approx(pads[f.origin].position)
        assert f.route.points[-1] == pytest.approx(pads[f.destination].position)
        if f.type == AgentType.EMERGENCY:
            assert pads[f.destination].role == "hospital"


def test_boundary_conditions_hold_every_tick(network):
    cfg = get_config()
    half_w = cfg["corridors"]["width_meters"] / 2.0
    flights = plan_flights(network, 24, cfg["scenario"]["type_mix"], 42, 20.0)
    by_index = list(flights)
    xmin, ymin, xmax, ymax = network.bounds
    frame = None
    for frame in simulate_routes(network, flights, 60.0, cfg):
        for k, st in enumerate(frame["status"]):
            if st != AIRBORNE:
                continue
            p = np.array([frame["x"][k], frame["y"][k]])
            route = by_index[k].route
            _, q, _ = route.project(p, frame["progress"][k] * route.length)
            assert np.linalg.norm(p - q) <= half_w + 0.01, "drone left its corridor tube"  # frames round to 1 cm
            assert xmin - 0.01 <= p[0] <= xmax + 0.01 and ymin - 0.01 <= p[1] <= ymax + 0.01
    assert frame is not None
    assert frame["stats"]["safety_violation_ticks"] == 0
    assert frame["stats"]["min_separation_m"] >= cfg["safety"]["minimum_separation_meters"]


def test_emergency_layer_and_outage(network):
    cfg = get_config()
    flights = plan_flights(network, 20, {"EMERGENCY": 1, "EVTOL": 1, "DELIVERY": 2}, 3, 5.0)
    emergency = [k for k, f in enumerate(flights) if f.type == AgentType.EMERGENCY]
    link = {"enabled": True, "down_start_seconds": 10.0, "down_end_seconds": 20.0}
    frames = list(simulate_routes(network, flights, 30.0, cfg, overseer_link_config=link))
    stats = frames[-1]["stats"]
    assert stats["overseer_dropped"] == 5  # 2 s period inside a 10 s outage
    assert any(not f["link_up"] for f in frames) and frames[-1]["link_up"]
    for f in frames:
        for k in emergency:
            if f["status"][k] == AIRBORNE:
                assert f["layer"][k] == cfg["airspace"]["emergency_layer"]


def test_spoofing_reports_filtered_or_accepted(network):
    cfg = get_config()
    flights = plan_flights(network, 40, cfg["scenario"]["type_mix"], 42, 10.0)
    liar = [f.agent_id for f in flights if f.type == AgentType.DELIVERY][:8]
    attack = {**cfg["attack"], "enabled": True, "start_time_seconds": 5.0, "malicious_ids": liar}
    *_, defended = simulate_routes(network, flights, 70.0, cfg, attack_config=attack)
    *_, open_ = simulate_routes(network, flights, 70.0, cfg, attack_config=attack, defended=False)
    assert defended["stats"]["reports_dropped"] > 0 and defended["stats"]["spoofed_reports_accepted"] == 0
    assert open_["stats"]["spoofed_reports_accepted"] > 0 and open_["stats"]["reports_dropped"] == 0


def test_layer_transition_gate_blocks_occupied_layer():
    me = AgentState(id=1, type=AgentType.DELIVERY, position=np.array([0.0, 0.0, 1.0]),
                    velocity=np.array([10.0, 0.0, 0.0]), altitude_layer=1)
    ahead = AgentState(id=2, type=AgentType.DELIVERY, position=np.array([40.0, 0.0, 0.0]),
                       velocity=np.array([0.5, 0.0, 0.0]), altitude_layer=0)
    far = AgentState(id=3, type=AgentType.DELIVERY, position=np.array([400.0, 300.0, 0.0]), altitude_layer=0)
    assert not _layer_transition_clear(me, 0, [me, ahead, far], 8.0)  # closing on a slow drone
    assert _layer_transition_clear(me, 0, [me, far], 8.0)
    assert _layer_transition_clear(me, 2, [me, ahead, far], 8.0)


def test_layered_min_separation_ignores_vertical_neighbours():
    xy = np.array([[0.0, 0.0], [3.0, 0.0], [100.0, 0.0]])
    assert layered_min_separation(xy, np.array([0, 1, 0]), 30.0) == pytest.approx(np.hypot(3.0, 30.0))
    assert layered_min_separation(xy, np.array([0, 0, 0]), 30.0) == pytest.approx(3.0)


def test_live_run_request_validation():
    from web_sandbox.server import prepare_live_run
    with pytest.raises(ValueError):
        prepare_live_run({"fleet": 0})
    with pytest.raises(ValueError):
        prepare_live_run({"fleet": 5, "config": {"unknown": 1}})
    with pytest.raises(ValueError):
        prepare_live_run({"fleet": 5, "mix": {"EMERGENCY": 0, "EVTOL": 0, "DELIVERY": 0}})
    prepared = prepare_live_run({"fleet": 8, "duration_s": 20, "attack": {"enabled": True, "count": 1}})
    assert len(prepared["flights"]) == 8 and len(prepared["attack"]["malicious_ids"]) == 1


def _straight_road(width_hint_m: float = 0.0):
    """Synthetic 1.2 km straight east-west road with a pad beside each end."""
    from simulation.road_network import GeoFrame, build_road_network
    frame = GeoFrame(78.0, 17.0)
    ll = lambda x, y: list(frame.to_geo(x, y))
    feats = [{"type": "Feature", "properties": {"highway": "primary"},
              "geometry": {"type": "LineString", "coordinates": [ll(-600, 0), ll(0, 0), ll(600, 0)]}}]
    for ref, x in (("W", -560.0), ("E", 560.0)):
        feats.append({"type": "Feature", "properties": {"vertiport": "hospital", "name": ref, "ref": ref},
                      "geometry": {"type": "Point", "coordinates": ll(x, 30.0)}})
    gj = {"type": "FeatureCollection", "bbox": ll(-700, -200) + ll(700, 200), "features": feats}
    return build_road_network(gj)


def _head_on_pair(network):
    from simulation.route_engine import Flight, RoutePath
    a, b = network.vertiports[0], network.vertiports[1]
    route = network.vertiport_route(a, b)
    # both emergencies -> same reserved layer, so the semicircular rule cannot separate them
    return [Flight(0, AgentType.EMERGENCY, a.id, b.id, RoutePath(route), 0.0),
            Flight(1, AgentType.EMERGENCY, b.id, a.id, RoutePath(route[::-1]), 0.0)]


def test_crash_is_detected_and_counted():
    """With every safety layer disabled, a head-on pair must collide and be reported."""
    road = _straight_road()
    cfg = get_config()
    cfg = {**cfg, "safety": {**cfg["safety"], "minimum_separation_meters": 0.05},
           "corridors": {**cfg["corridors"], "width_meters": 0.4},
           "local_behavior": {**cfg["local_behavior"], "w_sep": 0.0, "w_ali": 0.0}}
    frames = list(simulate_routes(road, _head_on_pair(road), 120.0, cfg, use_admm=False, use_overseer=False))
    last = frames[-1]
    assert last["stats"]["crashes"] == 1 and last["stats"]["crashed_drones"] == 2
    assert last["status"] == [3, 3]
    crash = [e for f in frames for e in f["events"] if e["kind"] == "crash"]
    assert len(crash) == 1 and sorted(crash[0]["ids"]) == [0, 1] and crash[0]["scope"] == "global"


def test_head_on_pair_is_separated_with_governance_on():
    road = _straight_road()
    frames = list(simulate_routes(road, _head_on_pair(road), 150.0, get_config()))
    last = frames[-1]
    assert last["stats"]["crashes"] == 0 and last["stats"]["safety_violation_ticks"] == 0
    assert last["status"] == [2, 2]


def test_frames_carry_network_and_dtc_metrics(network):
    cfg = get_config()
    flights = plan_flights(network, 20, cfg["scenario"]["type_mix"], 7, 5.0)
    link = {"enabled": True, "down_start_seconds": 6.0, "down_end_seconds": 14.0}
    frames = list(simulate_routes(network, flights, 20.0, cfg, overseer_link_config=link))
    mid = [f for f in frames if 8.0 <= f["t"] <= 12.0]
    assert all(not f["dtc"]["link_up"] and f["dtc"]["connected"] == 0 for f in mid)
    assert max(f["dtc"]["staleness_s"] for f in mid) >= 6.0
    busy = max(frames, key=lambda f: f["net"]["edges"])
    n = busy["net"]
    assert n["nodes"] == sum(1 for s in busy["status"] if s == 1)
    assert n["edges"] == len(busy["edges"]) and 0.0 <= n["transitivity"] <= 1.0
    assert 0.0 < n["largest_component"] <= 1.0


def test_iith_campus_map():
    from simulation.road_network import load_road_network as load
    campus = load(Path(__file__).resolve().parents[1] / "data" / "iith_campus.geojson")
    names = {v.name for v in campus.vertiports}
    assert {"Hospital", "Main Gate", "LHC", "Mess A", "SNCC"} <= names
    assert campus.geofence and campus.backdrop and campus.backdrop["url"].endswith(".jpg")
    assert all(campus.inside(*v.position) for v in campus.vertiports)
    x, y, moved = campus.clamp(campus.bounds[2] + 200.0, 0.0)
    assert moved and campus.inside(x, y)
    flights = plan_flights(campus, 30, get_config()["scenario"]["type_mix"], 42, 20.0)
    *_, last = simulate_routes(campus, flights, 90.0, get_config())
    assert last["stats"]["crashes"] == 0 and last["stats"]["geofence_corrections"] == 0
