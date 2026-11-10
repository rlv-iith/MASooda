"""Phase 3: custom drone input (validation, JSON/CSV, engine use, mid-run injection, replay)."""

from __future__ import annotations

import copy

import pytest

from config.load_config import get_config
from simulation.scenario_manifest import (drones_from_csv, drones_from_json, drones_to_csv, drones_to_json,
                                          validate_route_drones)

VPS = ["V1", "V2", "V3", "V4", "V5", "V6"]


def _cfg():
    return copy.deepcopy(get_config())


GOOD = [
    {"type": "EMERGENCY", "origin": "V1", "destination": "V4", "depart_s": 2, "cruise_speed_mps": 15,
     "battery_wh": 900, "soc_init_pct": 80, "fault": {"type": "overheating", "t_s": 30}},
    {"type": "delivery", "origin": "V2", "destination": "V5", "cooperative": False, "preferred_layer": 1},
    {"id": 99, "type": "DELIVERY", "origin": "V3", "destination": "V6", "malicious": True, "spoof_offset_m": [0, 30]},
]


def test_good_rows_are_normalized_and_ids_follow_the_random_fleet():
    rows = validate_route_drones(GOOD, VPS, _cfg(), 300.0, taken_ids=set(range(20)))
    assert [r["id"] for r in rows] == [100, 101, 99]          # explicit 99 kept, others after max id
    assert rows[0]["priority"] == 0 and rows[1]["priority"] == 2  # type default
    assert rows[1]["type"] == "DELIVERY" and rows[1]["cooperative"] is False
    assert rows[2]["spoof_offset_m"] == [0.0, 30.0] and rows[0]["spoof_offset_m"] is None
    assert rows[0]["fault"] == {"type": "overheating", "t_s": 30.0} and rows[0]["battery_wh"] == 900.0
    assert rows[1]["depart_s"] == 0.0 and rows[1]["battery_wh"] is None


def test_bad_rows_report_every_problem_per_row():
    cfg = _cfg()
    v_max = cfg["safety"]["maximum_velocity_meters_per_second"]
    em = cfg["airspace"]["emergency_layer"]
    bad = [
        {"type": "BALLOON", "origin": "V1", "destination": "V1"},
        {"origin": "V9", "destination": "V2", "depart_s": -1, "cruise_speed_mps": v_max + 1},
        {"origin": "V1", "destination": "V2", "preferred_layer": em, "soc_init_pct": 120},
        {"origin": "V1", "destination": "V2", "fault": {"type": "meteor", "t_s": 5}},
        {"origin": "V1", "destination": "V2", "malicious": True, "spoof_offset_m": [0, 0], "colour": "red"},
        {"id": 3, "origin": "V1", "destination": "V2"},
    ]
    with pytest.raises(ValueError) as exc:
        validate_route_drones(bad, VPS, cfg, 300.0, taken_ids={3})
    msg = str(exc.value)
    assert msg.startswith("6 invalid drone row(s)")
    for needle in ("row 1", "type must be", "must differ", "row 2", "'V9' is not a vertiport", "depart_s must be",
                   "cruise_speed_mps must be ≤", "row 3", "reserved for EMERGENCY", "soc_init_pct must be ≤ 100",
                   "row 4", "fault.type", "row 5", "spoof_offset_m length", "unknown field(s) colour",
                   "row 6 (D-3): id 3 is already used"):
        assert needle in msg, needle


def test_json_and_csv_round_trip():
    rows = validate_route_drones(GOOD, VPS, _cfg(), 300.0)
    assert validate_route_drones(drones_from_json(drones_to_json(rows)), VPS, _cfg(), 300.0) == rows
    text = drones_to_csv(rows)
    assert text.splitlines()[0].startswith("id,type,priority,origin,destination")
    assert validate_route_drones(drones_from_csv(text), VPS, _cfg(), 300.0) == rows
    with pytest.raises(ValueError, match="unknown CSV column"):
        drones_from_csv("id,type,wings\n1,DELIVERY,4\n")
    with pytest.raises(ValueError, match="line 2: depart_s"):
        drones_from_csv("type,origin,destination,depart_s\nDELIVERY,V1,V2,soon\n")
    with pytest.raises(ValueError, match="not a drone list"):
        drones_from_json({"format": "masooda-run", "drones": []})


# ----------------------------------------------------------------------------- engine
@pytest.fixture(scope="module")
def prepared():
    from web_sandbox.server import prepare_live_run
    return prepare_live_run({"map": "iith", "fleet": 20, "duration_s": 60, "seed": 5, "drones": GOOD})


def _frames(p, **kw):
    from simulation.route_engine import simulate_routes
    return [f for f in simulate_routes(p["network"], p["flights"], p["duration"], config=p["config"],
                                       attack_config=p["attack"], overseer_link_config=p["link"],
                                       frame_every=p["stride"], **kw) if not f.get("partial")]


def _strip(frames):
    return [{k: v for k, v in f.items() if k != "admm"} for f in frames]   # solve ms is wall-clock


def test_custom_drones_reproduce_and_apply_their_settings(prepared):
    from simulation.route_engine import flight_manifest
    a, b = _frames(prepared), _frames(prepared)
    assert _strip(a) == _strip(b)
    man = {f["id"]: f for f in flight_manifest(prepared["flights"])}
    assert man[100]["custom"] and man[100]["cruise_speed_mps"] == 15.0 and man[100]["health"]["battery_wh"] == 900.0
    assert man[101]["cooperative"] is False and man[99]["malicious"] and man[99]["spoof_offset_m"] == [0.0, 30.0]
    ids = [f.agent_id for f in prepared["flights"]]
    k101, k99 = ids.index(101), ids.index(99)
    up = [f for f in a if f["status"][k101] == 1]
    emergency_layer = int(prepared["config"]["airspace"]["emergency_layer"])
    assert up and all(f["layer"][k101] != emergency_layer for f in up)
    assert up[0]["layer"][k101] == 1                      # requested layer at departure
    # non-cooperative: the DTC and the V2V agreement never move it; only one-layer tactical shifts
    assert all(abs(b["layer"][k101] - a_["layer"][k101]) <= 1 for a_, b in zip(up, up[1:]))
    flying = [f for f in a if f["status"][k99] == 1]
    assert flying and all("99" in f["spoof"] for f in flying)
    assert all(f["spoof"]["99"]["err_rep"] == pytest.approx(30.0, abs=0.15) for f in flying)
    # the non-cooperative drone never negotiates in ADMM
    assert all("101" not in f["neg"] for f in a)


def test_add_drone_command_applies_at_a_tick_and_replays(prepared):
    from web_sandbox.server import LiveRun, _run_worker, scripted_commands, submit_command
    from simulation.route_engine import simulate_routes
    run = LiveRun("t", {}, 10_000)
    run.network, run.duration, run.config = prepared["network"], prepared["duration"], prepared["config"]
    run.ids = {f.agent_id for f in prepared["flights"]}
    out = submit_command(run, {"type": "add_drone", "drone": {"type": "EVTOL", "origin": "V5", "destination": "V1"}})
    assert out["status"] == "sent" and out["drone_id"] == 102
    with pytest.raises(ValueError):
        submit_command(run, {"type": "add_drone", "drone": {"origin": "V5", "destination": "V5"}})
    with pytest.raises(ValueError):
        submit_command(run, {"type": "launch_missiles"})
    _run_worker(run, prepared)
    assert run.error is None
    [cmd] = run.commands
    assert cmd["status"] == "applied" and cmd["tick_applied"] == 0
    frames, _ = run.store.since(0, 10_000)
    width0 = len(prepared["flights"])
    added = [f for f in frames if f.get("new_flights")]
    assert len(added) == 1 and added[0]["new_flights"][0]["id"] == 102 and len(added[0]["x"]) == width0 + 1
    assert any("Operator added D-102" in e["text"] for f in frames for e in f["events"])
    items = list(simulate_routes(prepared["network"], prepared["flights"], prepared["duration"],
                                 config=prepared["config"], attack_config=prepared["attack"],
                                 overseer_link_config=prepared["link"], frame_every=prepared["stride"],
                                 command_source=scripted_commands(run.commands), seed=prepared["seed"]))
    replay = [f for f in items if not f.get("partial")]   # same seed as the live run (health is seeded)
    assert [[round(v * 10) for v in f["x"]] for f in replay] == [f["x"] for f in frames]
    assert [e["text"] for f in items for e in f["events"]] == [e["text"] for f in frames for e in f["events"]]


def test_server_accepts_custom_only_and_rejects_over_limit():
    from web_sandbox.server import parse_drones, prepare_live_run
    from web_sandbox.streaming import web_limits
    p = prepare_live_run({"map": "iith", "fleet": 0, "duration_s": 30, "drones": GOOD[:2]})
    assert [f.agent_id for f in p["flights"]] == [1, 0] or sorted(f.agent_id for f in p["flights"]) == [0, 1]
    with pytest.raises(ValueError):
        prepare_live_run({"map": "iith", "fleet": 0, "duration_s": 30})
    lim = int(web_limits(get_config())["max_fleet"])
    with pytest.raises(ValueError, match="exceeds web.max_fleet"):
        prepare_live_run({"map": "iith", "fleet": lim, "duration_s": 30, "drones": GOOD[:1]})
    csv_text = "type,origin,destination,depart_s\nDELIVERY,V1,V2,3\nEVTOL,V1,V99,4\n"
    with pytest.raises(ValueError, match="row 2 .*'V99'"):
        parse_drones({"map": "iith", "format": "csv", "text": csv_text})
    ok = parse_drones({"map": "iith", "format": "csv", "text": csv_text.splitlines()[0] + "\n" + csv_text.splitlines()[1]})
    assert ok["drones"][0]["depart_s"] == 3.0


def test_pacing_holds_the_engine_near_the_watched_time():
    import time
    from web_sandbox.server import LiveRun
    run = LiveRun("p", {}, 100)
    run.lead_s, run.watch_timeout_s = 2.0, 0.3
    t0 = time.time()
    run.pace(50.0)                      # nobody watching: no wait
    run.watch(10.0)
    run.pace(11.0)                      # within the lead: no wait
    assert time.time() - t0 < 0.1
    run.pace(30.0)                      # too far ahead: waits until the watcher times out
    assert time.time() - t0 >= 0.25
    run.watch(10.0); run.stop()
    run.pace(30.0)                      # a stopped run never blocks


def test_imported_rows_without_ids_launch_next_to_a_random_fleet():
    from web_sandbox.server import parse_drones, prepare_live_run
    text = "type,origin,destination\nDELIVERY,V1,V2\nEVTOL,V3,V4\n"
    rows = parse_drones({"map": "iith", "format": "csv", "text": text})["drones"]
    assert [r["id"] for r in rows] == [None, None]
    p = prepare_live_run({"map": "iith", "fleet": 30, "duration_s": 30, "drones": rows})
    assert sorted(f.agent_id for f in p["flights"] if f.custom) == [30, 31]
