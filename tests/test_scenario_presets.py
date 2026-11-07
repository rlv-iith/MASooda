"""Phase 5: scripted scenario presets, detect-and-avoid sensing, repeated sorties, comparison variants."""

from __future__ import annotations

import copy
import time

import numpy as np
import pytest

from simulation.scenario_presets import build_preset_request, expand_macros, list_presets, load_preset, script_by_tick


def test_every_preset_loads_builds_and_validates():
    from web_sandbox.server import prepare_live_run
    presets = list_presets()
    assert [p["order"] for p in presets] == list(range(1, 11))
    for p in presets:
        assert p["description"] and p["timeline"], p["id"]
        for v in range(max(1, len(p["variants"]))):
            prepared = prepare_live_run({"preset": p["id"], "variant": v})   # validates the whole script
            assert prepared["preset"]["id"] == p["id"]
            ids = {f.agent_id for f in prepared["flights"]}
            for name, aid in prepared["preset"]["names"].items():
                assert aid in ids
    with pytest.raises(ValueError):
        prepare_live_run({"preset": "no_such_preset"})
    with pytest.raises(ValueError):
        prepare_live_run({"preset": "../configs/base_config"})


def test_named_drones_and_script_ticks():
    req, script, names = build_preset_request(load_preset("battery_failure"))
    assert names == {"cargo1": req["fleet"], "cargo2": req["fleet"] + 1}
    assert [d["id"] for d in req["drones"]] == [req["fleet"], req["fleet"] + 1]
    by_tick = script_by_tick(script, 0.1)
    assert sorted(by_tick) == [int(round(e["t"] / 0.1)) for e in script]
    bad = copy.deepcopy(load_preset("battery_failure"))
    bad["script"].append({"t": 5, "type": "hold", "targets": ["@ghost"]})
    with pytest.raises(ValueError, match="not a named drone"):
        build_preset_request(bad)


def test_moving_cell_macro_drifts_and_overlaps():
    cmds = expand_macros([{"type": "moving_cell", "from": [0, 0], "to": [1100, 0], "radius_m": 100, "steps": 12,
                           "start_s": 60, "end_s": 180, "name": "S"}])
    assert len(cmds) == 12 and all(c["type"] == "tfr" for c in cmds)
    starts = [c["params"]["start_s"] for c in cmds]
    ends = [c["params"]["end_s"] for c in cmds]
    assert starts[0] == 60 and all(e > s2 for e, s2 in zip(ends, starts[1:]))       # overlapping in time
    xs = [np.mean([p[0] for p in c["params"]["polygon"]]) for c in cmds]
    assert xs == sorted(xs) and xs[0] == pytest.approx(0, abs=1) and xs[-1] == pytest.approx(1100, abs=1)
    assert all(c["t"] <= c["params"]["start_s"] for c in cmds)                        # announced before active


def _run_preset(pid, variant=0, duration=None):
    from web_sandbox.server import LiveRun, _run_worker, prepare_live_run
    p = prepare_live_run({"preset": pid, "variant": variant})
    if duration:
        p["duration"] = duration
    run = LiveRun("t", {}, 100_000)
    run.network, run.duration, run.config = p["network"], p["duration"], p["config"]
    run.ids = {f.agent_id for f in p["flights"]}
    run.script = dict(p["script"])
    _run_worker(run, p)
    assert run.error is None
    frames, _ = run.store.since(0, 10 ** 9)
    return p, run, frames


def test_battery_failure_preset_follows_its_timeline():
    p, run, frames = _run_preset("battery_failure")
    names = p["preset"]["names"]
    texts = [e["text"] for f in frames for e in f["events"]]
    c1, c2 = names["cargo1"], names["cargo2"]
    assert any(f"D-{c1} BMS CRITICAL (CELL_IMBALANCE): DIVERTING" in t for t in texts)
    assert any(f"DTC: D-{c1} BMS CRITICAL → right of way" in t for t in texts)
    assert any(f"D-{c2} low reserve" in t and "DIVERTING" in t for t in texts)
    [cmd] = run.commands
    assert cmd["scripted"] and cmd["status"] == "acknowledged" and cmd["tick_received"] == 850
    stats = {}
    for f in frames:
        stats = f.get("stats", stats)
    assert stats["energy_depleted"] == 0 and stats["crashes"] == 0


def test_intruder_is_sensed_but_not_negotiated():
    p, run, frames = _run_preset("intruder")
    intr = p["preset"]["names"]["intruder"]
    texts = [e["text"] for f in frames for e in f["events"]]
    assert any(f"Non-cooperative D-{intr} detected by onboard sensing" in t for t in texts)
    assert all(str(intr) not in f.get("neg", {}) for f in frames)        # never in an ADMM negotiation
    stats = {}
    for f in frames:
        stats = f.get("stats", stats)
    assert stats["intruder_detections"] >= 1 and stats["crashes"] == 0


def test_sorties_and_service_queue():
    from simulation.route_engine import simulate_routes
    from web_sandbox.server import prepare_live_run
    p = prepare_live_run({"map": "iith", "fleet": 8, "duration_s": 600, "seed": 3, "departure_window_s": 10,
                          "config": {"operations": {"sorties": True, "service_soc_pct": 95.0},
                                     "dtc_console": {"service_pad_capacity": 1, "swap_time_s": 60.0}}})
    last = None
    events = []
    for f in simulate_routes(p["network"], p["flights"], 600, config=p["config"], seed=3, frame_every=10):
        events += f["events"]
        if not f.get("partial"):
            last = f
    st = last["stats"]
    assert st["missions"] >= 8 and st["services"] >= 1 and st["energy_depleted"] == 0
    assert any("waiting at" in e["text"] and "slot" in e["text"] for e in events) or st["service_queue_max"] == 0
    assert any("battery swap complete" in e["text"] for e in events)
    # a swapped drone takes off again (BMS refreshed after the swap)
    assert st["grounded_preflight"] == 0


def test_comparison_variants_run_headless(monkeypatch):
    import web_sandbox.server as S
    small = {"id": "tiny", "title": "tiny", "description": "d", "timeline": [[0, "x"]],
             "request": {"map": "iith", "fleet": 8, "duration_s": 30, "seed": 5},
             "variants": [{"label": "35C"}, {"label": "44C", "request": {"config": {"drone_health": {"ambient_c": 44.0}}}}]}
    monkeypatch.setattr(S, "load_preset", lambda pid: copy.deepcopy(small))
    m = S.start_live_run({"preset": "tiny"})
    run = S.RUNS[m["run_id"]]
    for _ in range(600):
        if run.done and all(e["done"] or e["live"] or e["error"] for e in run.compare):
            break
        time.sleep(0.1)
    assert [e["label"] for e in run.compare] == ["35C", "44C"] and run.compare[0]["live"]
    other = run.compare[1]
    assert other["error"] is None and other["done"] and other["kpis"]["arrivals"] is not None
