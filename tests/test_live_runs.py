"""Live-run admission: a new run never stops a run someone is watching; stopped runs say so."""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request

import pytest

import web_sandbox.server as srv

WEB = {"max_live_runs": 2, "abandon_after_s": 30.0}


@pytest.fixture(autouse=True)
def clean_runs():
    srv.RUNS.clear()
    yield
    for r in srv.RUNS.values():
        r.stop()
    srv.RUNS.clear()


def _run(rid: str, idle_s: float = 0.0, done: bool = False) -> srv.LiveRun:
    r = srv.LiveRun(rid, {})
    r.view_seen = time.time() - idle_s
    r.done = done
    srv.RUNS[rid] = r
    return r


def test_watched_runs_are_never_stopped_and_the_limit_answers_busy():
    a, b = _run("a"), _run("b")
    with pytest.raises(srv.SimulatorBusy, match="2 live run"):
        srv.admit_run(WEB)
    assert not a.stop_flag and not b.stop_flag


def test_abandoned_runs_free_their_slot_with_a_reason():
    a, b = _run("a", idle_s=31.0), _run("b", idle_s=1.0)
    srv.admit_run(WEB)
    assert a.stop_flag and "no page watched it for 30 s" in a.stop_reason
    assert not b.stop_flag


def test_a_relaunch_replaces_only_its_own_run():
    a, b = _run("a"), _run("b")
    srv.admit_run(WEB, replaces="a")
    assert a.stop_flag and a.stop_reason.startswith("replaced")
    assert not b.stop_flag


def test_finished_runs_do_not_count_and_keep_no_stop_reason():
    _run("old1", done=True), _run("old2", done=True)
    a = _run("a")
    srv.admit_run(WEB)
    a.done = True
    a.stop("late stop")              # stopping a finished run does not relabel it
    assert a.stop_reason is None


def _http(port: int, method: str, path: str, body: dict | None = None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method,
                                 data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_http_busy_then_stopped_run_is_reported_as_stopped():
    server = srv.ThreadingHTTPServer(("127.0.0.1", 0), srv.ScenarioHandler)
    server.daemon_threads = True
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        req = {"fleet": 3, "duration_s": 600, "seed": 1}
        ok1, r1 = _http(port, "POST", "/api/runs", req)
        ok2, r2 = _http(port, "POST", "/api/runs", req)
        assert ok1 == ok2 == 200
        busy, msg = _http(port, "POST", "/api/runs", req)
        assert busy == 503 and msg["error"] == "busy"
        assert not srv.RUNS[r1["run_id"]].stop_flag          # the watched runs kept going
        # the first page relaunches: only its own run stops, and its frames say why
        ok3, r3 = _http(port, "POST", "/api/runs", dict(req, replaces=r1["run_id"]))
        assert ok3 == 200 and not srv.RUNS[r2["run_id"]].stop_flag
        assert "replaces" not in srv.RUNS[r3["run_id"]].request
        for _ in range(100):
            _, fr = _http(port, "GET", f"/api/runs/{r1['run_id']}/frames?from=0")
            if fr["done"]:
                break
            time.sleep(0.05)
        assert fr["done"] and fr["stopped"].startswith("replaced")
    finally:
        server.shutdown()
        server.server_close()


def test_launch_returns_the_export_header_and_header_only_export_is_cheap():
    server = srv.ThreadingHTTPServer(("127.0.0.1", 0), srv.ScenarioHandler)
    server.daemon_threads = True
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        ok, man = _http(port, "POST", "/api/runs", {"fleet": 3, "duration_s": 10, "seed": 2, "replaces": "nope"})
        assert ok == 200
        hdr = man["export_header"]
        assert hdr["request"] == {"fleet": 3, "duration_s": 10, "seed": 2}       # `replaces` is not part of the run
        assert hdr["config"]["web"]["max_live_runs"] == 2 and len(hdr["config_hash"]) == 12
        run = srv.RUNS[man["run_id"]]
        assert "export_header" not in run.manifest
        for _ in range(200):
            if run.done:
                break
            time.sleep(0.05)
        ok, head = _http(port, "GET", f"/api/runs/{man['run_id']}/export?frames=0")
        assert ok == 200 and head["complete"] is True and head["config_hash"] == hdr["config_hash"]
        assert not {"frames", "kpis", "events"} & set(head)
        assert head["manifest"]["run_id"] == man["run_id"]
        # a stopped run is not "complete"
        ok, m2 = _http(port, "POST", "/api/runs", {"fleet": 3, "duration_s": 600, "seed": 2})
        _http(port, "POST", f"/api/runs/{m2['run_id']}/stop", {})
        for _ in range(200):
            if srv.RUNS[m2["run_id"]].done:
                break
            time.sleep(0.05)
        _, head2 = _http(port, "GET", f"/api/runs/{m2['run_id']}/export?frames=0")
        assert head2["complete"] is False
    finally:
        server.shutdown()
        server.server_close()
