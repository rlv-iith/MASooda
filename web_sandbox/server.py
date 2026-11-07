"""Local live-demo server for MASooda.

Run from the repository root:

    python -m web_sandbox.server            # http://127.0.0.1:8765

The browser UI (``web_sandbox/live_demo.html``) starts a run with
``POST /api/runs``. The run executes in a background thread using the
map-constrained route engine and streams frames that the page polls with
``GET /api/runs/<id>/frames?from=<k>``, so playback starts immediately while
the simulation is still computing. ``POST /api/simulate`` (abstract corridor
engine) is kept for compatibility. Binds to loopback only.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
import os
from pathlib import Path
import threading
import time
import traceback
from typing import Any
from urllib.parse import parse_qs, urlparse
import uuid

import numpy as np

from config.load_config import get_config
from simulation.road_network import load_road_network
from simulation.route_engine import flight_manifest, plan_flights, simulate_routes
from simulation.scenario_manifest import _merge_config, prepare_scenario_manifest
from simulation.engine import run_simulation
from web_sandbox.streaming import FrameStore, choose_stride, compact_frame, web_limits
import local_behavior.boids as boids
import simulation.overseer as overseer
from verification.metrics import compute_run_metrics, robustness_series

ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT / "web_sandbox"
MAPS = {
    "iith": {"label": "IITH campus (Kandi)", "file": ROOT / "data" / "iith_campus.geojson",
             "source": "IIT Hyderabad campus map (traced corridors)"},
    "hyderabad": {"label": "Hyderabad roads (OSM)", "file": ROOT / "data" / "hyderabad_roads_sample.geojson",
                  "source": "Hyderabad · © OpenStreetMap contributors (ODbL)"},
}
DEFAULT_MAP = "iith"
ROADS = MAPS["hyderabad"]["file"]
DATA_FILES = {"hyderabad_roads_sample.geojson": "application/geo+json; charset=utf-8",
              "hyderabad_roads_sample.tif": "image/tiff",
              "iith_campus.geojson": "application/geo+json; charset=utf-8",
              "iith_campus_map.jpg": "image/jpeg"}


def _network(map_id: str | None):
    key = map_id or DEFAULT_MAP
    if key not in MAPS:
        raise ValueError(f"Unknown map '{key}'. Choose one of: {', '.join(MAPS)}")
    return key, load_road_network(MAPS[key]["file"])
MAX_REQUEST_BYTES = 2_000_000
MAX_AGENT_TICKS = 50_000          # legacy /api/simulate limit
# Fleet / duration / streaming limits live in configs/base_config.yaml -> web: (see streaming.web_limits).
STATIC = {
    "/": ("live_demo.html", "text/html; charset=utf-8"),
    "/index.html": ("live_demo.html", "text/html; charset=utf-8"),
    "/live": ("live_demo.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/prototype": ("index.html", "text/html; charset=utf-8"),
}


def _json_safe(value: Any) -> Any:
    """Convert NumPy values and non-finite metrics to JSON-safe values."""
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.ndarray):
        return _json_safe(value.tolist())
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        if np.isnan(number):
            return None
        if np.isposinf(number):
            return "Infinity"
        if np.isneginf(number):
            return "-Infinity"
        return number
    return value


# ----------------------------------------------------------------------------- runs
class LiveRun:
    """One background simulation whose frames are appended as they are computed."""

    def __init__(self, run_id: str, request: dict[str, Any], max_frames: int = 6000):
        self.id = run_id
        self.store = FrameStore(max_frames)
        self.done = False
        self.error: str | None = None
        self.stop_flag = False
        self.lock = threading.Lock()
        self.started = time.time()
        self.request = request
        self.thread: threading.Thread | None = None

    def stop(self) -> None:
        self.stop_flag = True


RUNS: dict[str, LiveRun] = {}
RUNS_LOCK = threading.Lock()


def _int(value: Any, name: str, lo: int, hi: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value:
        raise ValueError(f"{name} must be a whole number")
    value = int(value)
    if not lo <= value <= hi:
        raise ValueError(f"{name} must be between {lo} and {hi}")
    return value


def _float(value: Any, name: str, lo: float, hi: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value):
        raise ValueError(f"{name} must be a number")
    value = float(value)
    if not lo <= value <= hi:
        raise ValueError(f"{name} must be between {lo:g} and {hi:g}")
    return value


def prepare_live_run(body: dict[str, Any]) -> dict[str, Any]:
    """Validate a browser run request and build flights + run arguments."""
    if not isinstance(body, dict):
        raise ValueError("Request must be a JSON object")
    overrides = body.get("config", {}) or {}
    if isinstance(overrides, dict) and "web" in overrides:
        raise ValueError("web.* limits are server settings and cannot be overridden per run")
    config = _merge_config(get_config(), overrides)
    web = web_limits(config)
    max_fleet, max_duration = int(web["max_fleet"]), float(web["max_duration_s"])
    fleet = _int(body.get("fleet", 60), "fleet", 1, max_fleet)
    duration = _float(body.get("duration_s", 180), "duration_s", 5.0, max_duration)
    seed = _int(body.get("seed", config["simulation"]["random_seed"]), "seed", 0, 2**31 - 1)
    window = _float(body.get("departure_window_s", min(90.0, duration * 0.5)), "departure_window_s", 0.0, max_duration)
    mix = body.get("mix") or config["scenario"]["type_mix"]
    if not isinstance(mix, dict) or set(mix) - {"EMERGENCY", "EVTOL", "DELIVERY"}:
        raise ValueError("mix must map EMERGENCY / EVTOL / DELIVERY to shares")
    mix = {k: _float(v, f"mix.{k}", 0.0, 100.0) for k, v in mix.items()}
    if sum(mix.values()) <= 0:
        raise ValueError("Vehicle mix must contain at least one non-zero share")
    if not 0.05 <= float(config["simulation"]["timestep_seconds"]) <= 0.5:
        raise ValueError("simulation.timestep_seconds must be between 0.05 and 0.5 for the live demo")
    if not 1 <= int(config["airspace"]["num_layers"]) <= 6:
        raise ValueError("airspace.num_layers must be between 1 and 6")

    map_id, network = _network(body.get("map"))
    flights = plan_flights(network, fleet, mix, seed, window)

    attack_cfg = dict(config.get("attack", {}))
    attack = body.get("attack", {}) or {}
    attack_cfg["enabled"] = bool(attack.get("enabled", False))
    if attack_cfg["enabled"]:
        start_s = _float(attack.get("start_s", duration * 0.2), "attack.start_s", 0.0, duration)
        cruise = float(config["local_behavior"]["v_cruise"]) * 0.9
        delivery = [f for f in flights if f.type.value == "DELIVERY"] or list(flights)
        count = _int(attack.get("count", 2), "attack.count", 1, max(1, len(delivery)))
        # spoofers should be in the air while the attack runs: prefer flights that
        # departed before the attack and still have the longest time left aloft
        aloft = sorted(delivery, key=lambda f: -(f.depart_s + f.route.length / cruise - start_s)
                       if f.depart_s <= start_s else 1e9 + f.depart_s)
        attack_cfg["malicious_ids"] = [f.agent_id for f in aloft[:count]]
        attack_cfg["start_time_seconds"] = start_s
    else:
        attack_cfg["malicious_ids"] = []

    link_cfg = dict(config["overseer"].get("link_failure", {}))
    outage = body.get("outage", {}) or {}
    link_cfg["enabled"] = bool(outage.get("enabled", False))
    if link_cfg["enabled"]:
        link_cfg["down_start_seconds"] = _float(outage.get("start_s", duration * 0.25), "outage.start_s", 0.0, duration)
        link_cfg["down_end_seconds"] = _float(outage.get("end_s", duration * 0.6), "outage.end_s",
                                              link_cfg["down_start_seconds"], duration)
    switches = {}
    for key in ("use_overseer", "use_admm", "defended"):
        value = body.get(key, True)
        if not isinstance(value, bool):
            raise ValueError(f"{key} must be true or false")
        switches[key] = value

    return {"map": map_id, "network": network, "flights": flights, "duration": duration, "config": config,
            "attack": attack_cfg, "link": link_cfg, "seed": seed, "fleet": fleet,
            "stride": choose_stride(config, fleet), "web": web, **switches}


def _run_worker(run: LiveRun, prepared: dict[str, Any]) -> None:
    pending_events: list[dict[str, Any]] = []
    max_edges = int(prepared["web"]["max_edges_per_frame"])
    try:
        gen = simulate_routes(
            prepared["network"], prepared["flights"], prepared["duration"],
            config=prepared["config"], use_overseer=prepared["use_overseer"],
            use_admm=prepared["use_admm"], defended=prepared["defended"],
            attack_config=prepared["attack"], overseer_link_config=prepared["link"],
            should_stop=lambda: run.stop_flag, frame_every=prepared["stride"],
            spatial_index=bool(prepared["web"]["spatial_index"]))
        seq, prev_stats = 0, None
        for item in gen:
            pending_events.extend(item["events"])
            if item.get("partial"):
                continue  # light tick: its events ride on the next full frame
            frame = compact_frame(_json_safe(dict(item, events=pending_events)), seq, prev_stats, max_edges)
            prev_stats = item["stats"] if "stats" in frame else prev_stats
            pending_events = []
            run.store.append(frame)
            seq += 1
    except Exception as exc:  # surfaced to the browser instead of hanging the run
        traceback.print_exc()
        run.error = f"{type(exc).__name__}: {exc}"
    finally:
        run.done = True


def start_live_run(body: dict[str, Any]) -> dict[str, Any]:
    prepared = prepare_live_run(body)
    with RUNS_LOCK:
        for old in RUNS.values():   # single-operator demo: newest run wins the CPU
            old.stop()
        for key in [k for k, r in RUNS.items() if r.done][:-4]:
            RUNS.pop(key, None)
        run_id = uuid.uuid4().hex[:12]
        run = LiveRun(run_id, body, int(prepared["web"]["max_frames_in_memory"]))
        RUNS[run_id] = run
    run.thread = threading.Thread(target=_run_worker, args=(run, prepared), daemon=True)
    run.thread.start()
    cfg = prepared["config"]
    return _json_safe({
        "run_id": run_id,
        "map": prepared["map"],
        "dt": float(cfg["simulation"]["timestep_seconds"]) * prepared["stride"],
        "stride_ticks": prepared["stride"],
        "frame_version": 2,
        "duration_s": prepared["duration"],
        "seed": prepared["seed"],
        "flights": flight_manifest(prepared["flights"]),
        "attack": {"enabled": prepared["attack"]["enabled"], "malicious_ids": prepared["attack"].get("malicious_ids", []),
                   "start_s": prepared["attack"].get("start_time_seconds")},
        "outage": {"enabled": prepared["link"]["enabled"], "start_s": prepared["link"].get("down_start_seconds"),
                   "end_s": prepared["link"].get("down_end_seconds")},
        "switches": {k: prepared[k] for k in ("use_overseer", "use_admm", "defended")},
        "limits": {
            "d_min": float(cfg["safety"]["minimum_separation_meters"]),
            "corridor_width": float(cfg["corridors"]["width_meters"]),
            "num_layers": int(cfg["airspace"]["num_layers"]),
            "layer_height": float(cfg["airspace"]["layer_height_meters"]),
            "emergency_layer": int(cfg["airspace"].get("emergency_layer", 2)),
            "capacity": int(cfg["corridors"]["capacity"]),
        },
    })


# --------------------------------------------------------------------------- handler
class ScenarioHandler(BaseHTTPRequestHandler):
    server_version = "MASoodaDemo/2.0"

    def _send_bytes(self, status: int, payload: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def _send_json(self, status: int, value: Any) -> None:
        payload = json.dumps(_json_safe(value), allow_nan=False, separators=(",", ":")).encode("utf-8")
        self._send_bytes(status, payload, "application/json; charset=utf-8")

    def _read_json(self) -> Any:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > MAX_REQUEST_BYTES:
            raise ValueError(f"Request body must be between 1 and {MAX_REQUEST_BYTES} bytes")
        return json.loads(self.rfile.read(length))

    def do_GET(self) -> None:
        url = urlparse(self.path)
        route = url.path
        try:
            if route in STATIC:
                name, ctype = STATIC[route]
                path = WEB_ROOT / name
                if not path.is_file():
                    self._send_json(404, {"error": "asset_not_found"})
                    return
                self._send_bytes(200, path.read_bytes(), ctype)
            elif route == "/api/config":
                self._send_json(200, get_config())
            elif route == "/api/limits":
                web = web_limits(get_config())
                self._send_json(200, {"max_agent_ticks": MAX_AGENT_TICKS,
                                      **{k: web[k] for k in ("max_fleet", "max_duration_s", "realtime_max_fleet",
                                                             "max_frames_in_memory", "poll_batch",
                                                             "target_frames_per_sim_s")}})
            elif route == "/api/maps":
                self._send_json(200, {"default": DEFAULT_MAP,
                                      "maps": [{"id": k, "label": v["label"]} for k, v in MAPS.items()]})
            elif route == "/api/map":
                map_id = parse_qs(url.query).get("map", [DEFAULT_MAP])[0]
                try:
                    map_id, network = _network(map_id)
                except ValueError as exc:
                    self._send_json(404, {"error": "map_not_found", "message": str(exc)})
                    return
                payload = network.to_dict()
                payload["id"] = map_id
                payload["label"] = MAPS[map_id]["label"]
                payload["source"] = MAPS[map_id]["source"]
                self._send_json(200, payload)
            elif route.startswith("/api/runs/") and route.endswith("/frames"):
                run = RUNS.get(route.split("/")[3])
                if run is None:
                    self._send_json(404, {"error": "run_not_found"})
                    return
                start = int(parse_qs(url.query).get("from", ["0"])[0])
                finished = run.done  # read before the store so no frame can arrive unseen
                frames, stored = run.store.since(start, int(web_limits(get_config())["poll_batch"]))
                nxt = frames[-1]["n"] + 1 if frames else start
                self._send_json(200, {"frames": frames, "from": start, "next": nxt, "stored": stored,
                                      "thinned": run.store.thinned,
                                      "done": finished and nxt > run.store.last_seq(), "error": run.error})
            elif route.startswith("/data/") and route[6:] in DATA_FILES:
                path = ROOT / "data" / route[6:]
                if not path.is_file():
                    self._send_json(404, {"error": "data_not_found"})
                    return
                self._send_bytes(200, path.read_bytes(), DATA_FILES[route[6:]])
            else:
                self._send_json(404, {"error": "route_not_found"})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            traceback.print_exc()
            self._send_json(500, {"error": "server_error", "message": str(exc)})

    def do_POST(self) -> None:
        route = urlparse(self.path).path
        try:
            if route == "/api/runs":
                self._send_json(200, start_live_run(self._read_json()))
            elif route.startswith("/api/runs/") and route.endswith("/stop"):
                run = RUNS.get(route.split("/")[3])
                if run:
                    run.stop()
                self._send_json(200, {"stopped": bool(run)})
            elif route == "/api/simulate":  # legacy: abstract three-corridor engine, not used by the page
                self._legacy_simulate()
            else:
                self._send_json(404, {"error": "route_not_found"})
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            self._send_json(400, {"error": "invalid_request", "message": str(exc)})
        except Exception as exc:
            traceback.print_exc()
            self._send_json(500, {"error": "simulation_failed", "message": str(exc)})

    def _legacy_simulate(self) -> None:
        """Abstract three-corridor engine (kept for the earlier API contract)."""
        manifest = self._read_json()
        prepared = prepare_scenario_manifest(manifest)
        dt = float(prepared["config"]["simulation"]["timestep_seconds"])
        steps = int(round(float(prepared["duration_s"]) / dt))
        samples = (steps + 1) * len(prepared["agents"])
        if samples > MAX_AGENT_TICKS:
            raise ValueError(f"Run requests {samples} agent-ticks; local web demo limit is {MAX_AGENT_TICKS}")
        boids.reset_local_behavior_cache()
        overseer.reset_default_overseer(config=prepared["config"])
        result = run_simulation(
            agents=prepared["agents"], duration_s=prepared["duration_s"],
            use_overseer=prepared["use_overseer"], use_admm=prepared["use_admm"],
            attack_config=prepared["attack_config"], defended=prepared["defended"],
            overseer_link_config=prepared["overseer_link_config"], config=prepared["config"])
        metrics = compute_run_metrics(result, config=prepared["config"])
        d_safe = float(prepared["config"]["safety"]["minimum_separation_meters"])
        record = {"duration_s": prepared["duration_s"], "config": prepared["config"],
                  "agents": [a.to_dict() for a in prepared["agents"]]}
        self._send_json(200, {
            "run_hash": hashlib.sha256(json.dumps(_json_safe(record), sort_keys=True).encode()).hexdigest(),
            "times": result.times, "agent_ids": result.agent_ids, "tasks": prepared["tasks"],
            "positions": result.positions, "velocities": result.velocities,
            "robustness_m": robustness_series(result.positions, d_safe),
            "mean_speed_mps": float(np.mean(np.linalg.norm(result.velocities, axis=2))),
            "metrics": metrics,
        })

    def log_message(self, format: str, *args: Any) -> None:
        if "/frames" not in (args[0] if args else ""):
            print(f"[web] {self.address_string()} {format % args}")


def main() -> None:
    host = os.environ.get("MASOODA_HOST", "127.0.0.1")
    port = int(os.environ.get("MASOODA_PORT", "8765"))
    for spec in MAPS.values():  # warm the corridor graphs
        load_road_network(spec["file"])
    # On Windows SO_REUSEADDR lets a second process bind the same port, so an old
    # server keeps answering some requests (e.g. /app.js) with stale code. Refuse instead.
    ThreadingHTTPServer.allow_reuse_address = os.name != "nt"
    try:
        server = ThreadingHTTPServer((host, port), ScenarioHandler)
    except OSError as exc:
        raise SystemExit(
            f"Port {port} is already in use ({exc}). Stop the other MASooda/Python server first.\n"
            f"Windows: netstat -ano | findstr :{port}   then   taskkill /PID <pid> /F\n"
            f"Or run on another port:  set MASOODA_PORT=8766 && python -m web_sandbox.server")
    server.daemon_threads = True
    print(f"MASooda live demo: http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping MASooda live demo server")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
