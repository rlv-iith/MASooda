"""Phase 1a/1c: web limits from config, adaptive stride, compact frames, memory cap."""

from __future__ import annotations

import copy

import pytest

from config.load_config import get_config
from web_sandbox.streaming import FrameStore, choose_stride, compact_frame, web_limits


def _cfg(**web):
    cfg = copy.deepcopy(get_config())
    cfg.setdefault("web", {}).update(web)
    return cfg


def test_limits_come_from_config():
    cfg = get_config()
    web = web_limits(cfg)
    for key in ("max_fleet", "max_duration_s", "realtime_max_fleet", "max_frames_in_memory",
                "max_edges_per_frame", "poll_batch", "target_frames_per_sim_s"):
        assert web[key] == cfg["web"][key]


def test_stride_targets_frame_rate_and_byte_budget():
    cfg = _cfg(target_frames_per_sim_s=5, max_kb_per_sim_s=40, est_bytes_per_drone_frame=22)
    assert choose_stride(cfg, 60) == 2                 # 10 ticks/s -> 5 frames/s
    big = choose_stride(cfg, 500)                      # 500 * 22 B * 5 /s = 54 KB/s > 40
    assert big > 2 and (10 / big) * 500 * 22 / 1024 <= 40
    assert choose_stride(cfg, 500) == big              # deterministic
    assert choose_stride(_cfg(target_frames_per_sim_s=10), 10) == 1


def _engine_frame(k, n=4, stats=None, edges=None, events=None):
    return {
        "t": k * 0.2, "k": k * 2,
        "x": [1.234 * i for i in range(n)], "y": [-5.06 * i for i in range(n)],
        "layer": [i % 3 for i in range(n)], "status": [1, 0, 2, 3][:n],
        "speed": [12.04] * n, "progress": [0.1234] * n, "rho": 4.5, "link_up": True, "attack": False,
        "net": {"nodes": 2}, "dtc": {"link_up": True},
        "edges": edges if edges is not None else [[0, 1]], "events": events or [],
        "stats": stats if stats is not None else {"arrivals": k},
    }


def test_compact_frame_encoding():
    f = compact_frame(_engine_frame(3), seq=7, prev_stats=None, max_edges=600)
    assert f["v"] == 2 and f["n"] == 7 and f["k"] == 6
    assert f["x"] == [0, 12, 25, 37] and f["y"] == [0, -51, -101, -152]       # decimetres
    assert f["ls"] == [1 * 8 + 0, 0 * 8 + 1, 2 * 8 + 2, 3 * 8 + 0]          # status*8 + layer
    assert f["spd"] == [120] * 4 and f["prog"] == [123] * 4
    assert f["stats"] == {"arrivals": 3}
    same = compact_frame(_engine_frame(3), seq=8, prev_stats={"arrivals": 3}, max_edges=600)
    assert "stats" not in same                                                # unchanged -> omitted


def test_edges_are_capped_evenly():
    edges = [[i, i + 1] for i in range(1000)]
    f = compact_frame(_engine_frame(0, edges=edges), 0, None, max_edges=100)
    assert len(f["edges"]) == 100 and f["edges_total"] == 1000
    assert f["edges"][0] == [0, 1] and f["edges"][-1][0] >= 980


def test_frame_store_thinning_keeps_every_event_and_stats():
    store = FrameStore(max_frames=16)
    sent_events, last_stats = [], None
    for k in range(200):
        ev = [{"t": k, "text": f"e{k}"}] if k % 3 == 0 else []
        sent_events += ev
        stats = {"arrivals": k // 10}
        f = compact_frame(_engine_frame(k, events=ev, stats=stats), k, last_stats, 600)
        last_stats = stats
        store.append(f)
    frames, stored = store.since(0, 10_000)
    assert stored == len(frames) <= 16 and store.thinned == 200 - stored
    assert [e["text"] for f in frames for e in f["events"]] == [e["text"] for e in sent_events]
    assert frames[-1]["n"] == 199
    carried = None                                       # stats carried forward still end correct
    for f in frames:
        carried = f.get("stats", carried)
    assert carried == {"arrivals": 19}
    later, _ = store.since(150, 10)
    assert all(f["n"] >= 150 for f in later)


def test_server_rejects_over_limit_and_web_overrides():
    from web_sandbox.server import prepare_live_run
    lim = web_limits(get_config())
    with pytest.raises(ValueError):
        prepare_live_run({"fleet": int(lim["max_fleet"]) + 1})
    with pytest.raises(ValueError):
        prepare_live_run({"fleet": 5, "duration_s": float(lim["max_duration_s"]) + 1})
    with pytest.raises(ValueError):
        prepare_live_run({"fleet": 5, "config": {"web": {"max_fleet": 10_000}}})
    prepared = prepare_live_run({"fleet": 5, "duration_s": 20})
    assert prepared["stride"] == choose_stride(prepared["config"], 5)


def test_worker_streams_compact_frames_without_losing_events():
    """End-to-end through the server worker on the IITH map (no HTTP)."""
    from simulation.route_engine import simulate_routes
    from web_sandbox.server import LiveRun, _run_worker, prepare_live_run
    prepared = prepare_live_run({"map": "iith", "fleet": 12, "duration_s": 40, "seed": 3})
    run = LiveRun("test", {}, 10_000)
    _run_worker(run, prepared)
    assert run.error is None and run.done
    frames, _ = run.store.since(0, 10_000)
    assert all(f["v"] == 2 for f in frames)
    assert [f["n"] for f in frames] == list(range(len(frames)))
    assert frames[-1]["t"] == pytest.approx(40.0)
    direct = list(simulate_routes(prepared["network"], prepared["flights"], 40.0, config=prepared["config"],
                                  attack_config=prepared["attack"], overseer_link_config=prepared["link"]))
    assert [e["text"] for f in frames for e in f["events"]] == [e["text"] for f in direct for e in f["events"]]
    final = direct[-1]
    assert [round(x * 10) for x in final["x"]] == frames[-1]["x"]
