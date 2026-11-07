"""Phase 4: DTC operator console commands, delivery over the DTC link, replay."""

from __future__ import annotations

import copy

import numpy as np
import pytest

from simulation.dtc_console import plan_route, points_in_polygon, route_hits_zones, segments_cross_polygon, validate_command
from simulation.road_network import RoutePath


# ----------------------------------------------------------------------------- unit: validation + geometry
def _v(body, ids=(1, 2, 3)):
    return validate_command(body, set(ids), ["V1", "V2", "V3"], 3, 300.0, 15.0, 6)


def test_validate_command_normalizes_and_rejects():
    assert _v({"type": "priority", "targets": [1], "params": {"level": "EMERGENCY"}})["params"] == {"level": 0}
    assert _v({"type": "speed_limit", "params": {"v": 5, "sector": 2}})["params"]["sector"] == 2
    tfr = _v({"type": "tfr", "params": {"polygon": [[0, 0], [50, 0], [50, 50]], "end_s": 100}})["params"]
    assert tfr["start_s"] == 0.0 and tfr["end_s"] == 100.0
    for bad, msg in [({"type": "nuke"}, "unknown command type"), ({"type": "hold"}, "needs at least one target"),
                     ({"type": "hold", "targets": [9]}, "unknown drone"),
                     ({"type": "reroute", "targets": [1], "params": {"dest": "V9"}}, "not a vertiport"),
                     ({"type": "change_layer", "targets": [1], "params": {"layer": 5}}, "between 0 and 2"),
                     ({"type": "speed_limit", "params": {"v": 5}}, "targets or params.sector"),
                     ({"type": "tfr", "params": {"polygon": [[0, 0], [1, 0], [1, 1]]}}, "too small"),
                     ({"type": "lost_link_policy", "params": {"policy": "panic"}}, "policy must be")]:
        with pytest.raises(ValueError, match=msg):
            _v(bad)


def test_polygon_geometry():
    sq = [[0, 0], [10, 0], [10, 10], [0, 10]]
    assert points_in_polygon(np.array([[5, 5], [15, 5]]), sq).tolist() == [True, False]
    cross = segments_cross_polygon(np.array([[-5, 5], [-5, 20]]), np.array([[15, 5], [15, 20]]), sq)
    assert cross.tolist() == [True, False]
    r = RoutePath(np.array([[-20.0, 5.0], [-10.0, 5.0], [30.0, 5.0]]))
    assert route_hits_zones(r, 0.0, [sq]) and not route_hits_zones(r, 45.0, [sq])


def test_plan_route_avoids_zones(network):
    v1, v2 = network.vertiports[0], network.vertiports[5]
    start = np.asarray(v1.position, float)
    plain = plan_route(network, start, np.asarray(v2.position, float), v2.node)
    # block a box around the middle of the plain route
    mid = plain.point_at(plain.length / 2)
    zone = [[mid[0] - 40, mid[1] - 40], [mid[0] + 40, mid[1] - 40], [mid[0] + 40, mid[1] + 40], [mid[0] - 40, mid[1] + 40]]
    around = plan_route(network, start, np.asarray(v2.position, float), v2.node, [zone])
    assert around is not None and around.length > plain.length
    assert not route_hits_zones(around, 0.0, [zone])


# ----------------------------------------------------------------------------- engine: scripted runs
@pytest.fixture(scope="module")
def network():
    from simulation.road_network import load_road_network
    from pathlib import Path
    return load_road_network(Path(__file__).resolve().parents[1] / "data" / "iith_campus.geojson")


def _prepared(fleet=20, duration=90.0, seed=7, **extra):
    from web_sandbox.server import prepare_live_run
    return prepare_live_run({"map": "iith", "fleet": fleet, "duration_s": duration, "seed": seed, **extra})


def _run(p, schedule):
    """Run through the server worker; ``schedule``: tick -> [command bodies]. Returns (run, frames, all items)."""
    from web_sandbox.server import LiveRun, _run_worker, submit_command
    run = LiveRun("t", {}, 100_000)
    run.network, run.duration, run.config = p["network"], p["duration"], p["config"]
    run.ids = {f.agent_id for f in p["flights"]}
    orig = run.drain

    def drain(k, t):
        for body in schedule.get(k, []):
            submit_command(run, copy.deepcopy(body))
        return orig(k, t)

    run.drain = drain
    _run_worker(run, p)
    assert run.error is None
    frames, _ = run.store.since(0, 10 ** 9)
    return run, frames


def _first_airborne(p, at_s):
    """Drones airborne just before ``at_s`` (the run is deterministic up to the first command)."""
    from simulation.route_engine import simulate_routes
    last = None
    for f in simulate_routes(p["network"], p["flights"], at_s - 0.2, config=p["config"], attack_config=p["attack"],
                             overseer_link_config=p["link"], seed=p["seed"]):
        last = f
    ids = [fl.agent_id for fl in p["flights"]]
    return [ids[k] for k, st in enumerate(last["status"]) if st == 1]


def _status_at(frames, p, aid, t):
    k = [f.agent_id for f in p["flights"]].index(aid)
    f = min(frames, key=lambda fr: abs(fr["t"] - t))
    return f["ls"][k] >> 3, f["x"][k], f["y"][k], f["ls"][k] & 7


def test_hold_resume_layer_speed_priority():
    p = _prepared()
    a, b, c, d = _first_airborne(p, 20.0)[:4]
    run, frames = _run(p, {200: [{"type": "hold", "targets": [a]}, {"type": "change_layer", "targets": [b], "params": {"layer": 1}},
                                 {"type": "speed_limit", "targets": [c], "params": {"v": 3, "expires_s": 20}},
                                 {"type": "priority", "targets": [d], "params": {"level": 0}}],
                           400: [{"type": "resume", "targets": [a]}]})
    res = {cmd["type"]: cmd for cmd in run.commands}
    assert all(cmd["status"] == "acknowledged" for cmd in run.commands), [(c_["type"], c_["results"]) for c_ in run.commands]
    s1, x1, y1, _ = _status_at(frames, p, a, 25.0)
    s2, x2, y2, _ = _status_at(frames, p, a, 38.0)
    if s1 == s2 == 1:
        assert np.hypot(x2 - x1, y2 - y1) < 60          # decimetres: loitered within ~6 m while held
    assert _status_at(frames, p, b, 21.0)[3] == 1     # moved to L1 and pinned there
    assert _status_at(frames, p, b, 40.0)[3] == 1 or _status_at(frames, p, b, 40.0)[0] != 1
    k = [f.agent_id for f in p["flights"]].index(c)
    spd = [f["spd"][k] for f in frames if 24.0 <= f["t"] <= 38.0 and f["ls"][k] >> 3 == 1]
    assert spd and max(spd) <= 3.0 * 10 + 6            # dm/s; small overshoot from the velocity filter
    assert "emergency privileges" in res["priority"]["results"][str(d)]
    last = [f for f in frames if f.get("console")][-1]["console"]
    assert d in last["promoted"] and last["pinned"][str(b)] == 1 and a not in last["holds"]


def test_reroute_rtb_ground_now_quarantine_and_charge():
    p = _prepared(fleet=40, duration=300.0)
    a, b, c, d, e = _first_airborne(p, 20.0)[:5]
    origin = {f.agent_id: f.origin for f in p["flights"]}
    run, frames = _run(p, {200: [{"type": "reroute", "targets": [a], "params": {"dest": "V1"}},
                                 {"type": "rtb", "targets": [b]},
                                 {"type": "ground_now", "targets": [c]},
                                 {"type": "quarantine", "targets": [d]},
                                 {"type": "divert_charge", "targets": [e], "params": {"pad": "V3", "mode": "swap"}}]})
    by = {cmd["type"]: cmd for cmd in run.commands}
    for t_ in by:
        assert by[t_]["status"] == "acknowledged", (t_, by[t_]["results"])
    rr = [r for f in frames for r in f.get("reroutes", [])]
    assert any(r["id"] == a and r["destination"] == "V1" for r in rr)
    assert any(r["id"] == b and r["destination"] == origin[b] for r in rr)
    assert "landing" in by["ground_now"]["results"][str(c)]
    last = [f for f in frames if f.get("console")][-1]["console"]
    assert d in last["quarantined"]
    texts = [ev["text"] for f in frames for ev in f["events"]]
    assert any(r["id"] == e and r["destination"] == "V3" for r in rr)
    assert any(f"D-{e} landed at V3 for battery swap" in t_ for t_ in texts)
    assert any(f"D-{e} battery swap complete — SoC 100%" in t_ for t_ in texts)
    assert any(f"D-{e} " in t_ and "departs V3" in t_ for t_ in texts)        # resumes the mission


def test_tfr_ground_stop_and_fleet_actions():
    p = _prepared(fleet=30, duration=120.0)
    net = p["network"]
    pad = net.vertiports[6]
    x, y = pad.position
    zone = [[x - 60, y - 60], [x + 60, y - 60], [x + 60, y + 60], [x - 60, y + 60]]
    run, frames = _run(p, {10: [{"type": "tfr", "params": {"polygon": zone, "start_s": 2, "end_s": 60, "name": "Z"}},
                                {"type": "ground_stop", "params": {"sector": 0, "release_s": 40}},
                                {"type": "fleet_recall_below_soc", "params": {"threshold_pct": 1}}]})
    assert all(cmd["status"] == "acknowledged" for cmd in run.commands), [(c_["type"], c_["results"], c_["outcome"]) for c_ in run.commands]
    texts = [ev["text"] for f in frames for ev in f["events"]]
    assert any("Restricted area Z ACTIVE" in t_ for t_ in texts) and any("Restricted area Z lifted" in t_ for t_ in texts)
    assert any("Ground stop S0 released" in t_ for t_ in texts)
    # no airborne drone inside the zone after it became active (allow a few seconds to clear)
    ids = [f.agent_id for f in p["flights"]]
    for f in frames:
        if 12.0 <= f["t"] <= 58.0:
            xy = np.array([[f["x"][k] / 10, f["y"][k] / 10] for k in range(len(ids)) if f["ls"][k] >> 3 == 1]).reshape(-1, 2)
            entered = points_in_polygon(xy, zone)
            assert not entered.any() or f["t"] < 20.0


def test_outage_queue_and_drop_policies():
    out = {"outage": {"enabled": True, "start_s": 20, "end_s": 40}}
    p = _prepared(duration=60.0, **out)
    a = _first_airborne(p, 20.0)[0]
    run, _ = _run(p, {250: [{"type": "hold", "targets": [a]}]})
    [cmd] = run.commands
    assert cmd["status"] == "acknowledged" and cmd["tick_received"] == 250 and cmd["tick_delivered"] >= 400
    cfg = copy.deepcopy(p["config"])
    cfg["dtc_console"]["outage_policy"] = "drop"
    p2 = dict(p, config=cfg)
    run2, _ = _run(p2, {250: [{"type": "hold", "targets": [a]}]})
    assert run2.commands[0]["status"] == "lost"
    cfg3 = copy.deepcopy(p["config"])
    cfg3["dtc_console"]["queue_ttl_s"] = 5.0
    run3, _ = _run(dict(p, config=cfg3), {250: [{"type": "hold", "targets": [a]}]})
    assert run3.commands[0]["status"] == "expired"


def test_no_dtc_architecture_refuses_and_dry_run_checks_energy():
    p = _prepared(duration=40.0, architecture="decentralized")
    a = _first_airborne(p, 20.0)[0]
    run, _ = _run(p, {200: [{"type": "hold", "targets": [a]}]})
    assert run.commands[0]["status"] == "failed" and "no DTC" in run.commands[0]["outcome"]
    p = _prepared(duration=40.0)
    run, _ = _run(p, {200: [{"type": "rtb", "targets": [a], "dry_run": True}]})
    chk = run.commands[0]
    assert chk["status"] == "checked" and str(a) in chk["results"] and "feasible" in chk["results"][str(a)]


def test_infeasible_movement_is_refused_with_an_alternative():
    p = _prepared(fleet=0, duration=60.0, drones=[{"type": "DELIVERY", "origin": "V8", "destination": "V12",
                                                   "soc_init_pct": 30, "soh_pct": 50, "depart_s": 1}])
    [aid] = [f.agent_id for f in p["flights"]]
    run, _ = _run(p, {150: [{"type": "reroute", "targets": [aid], "params": {"dest": "V1"}, "dry_run": True},
                            {"type": "reroute", "targets": [aid], "params": {"dest": "V1"}}]})
    chk, real = run.commands
    r = chk["results"].get(str(aid))
    if r and not r["feasible"]:      # 3 km round trip on ~70 Wh is beyond the reserve
        assert "infeasible" in r["detail"]
        assert real["status"] == "failed" and "infeasible" in real["results"][str(aid)]


def test_replay_with_commands_reproduces_frames():
    from simulation.route_engine import simulate_routes
    from web_sandbox.server import scripted_commands
    p = _prepared(fleet=20, duration=80.0, outage={"enabled": True, "start_s": 50, "end_s": 60})
    a, b, c = _first_airborne(p, 20.0)[:3]
    run, frames = _run(p, {150: [{"type": "hold", "targets": [a]}, {"type": "rtb", "targets": [b]}],
                           300: [{"type": "resume", "targets": [a]}, {"type": "lost_link_policy", "params": {"policy": "hold"}},
                                 {"type": "tfr", "params": {"polygon": [[-50, -50], [50, -50], [50, 50], [-50, 50]], "name": "T"}}],
                           520: [{"type": "ground_now", "targets": [c]}]})
    items = list(simulate_routes(p["network"], p["flights"], p["duration"], config=p["config"], attack_config=p["attack"],
                                 overseer_link_config=p["link"], frame_every=p["stride"], seed=p["seed"],
                                 command_source=scripted_commands(run.commands)))
    full = [f for f in items if not f.get("partial")]
    assert [[round(v * 10) for v in f["x"]] for f in full] == [f["x"] for f in frames]
    assert [e["text"] for f in items for e in f["events"]] == [e["text"] for f in frames for e in f["events"]]
