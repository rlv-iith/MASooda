"""Local live-demo server for MASooda.

Run from the repository root:

    python -m web_sandbox.server            # http://127.0.0.1:8765

The browser UI (``web_sandbox/live_demo.html``) starts a run with
``POST /api/runs``. The run executes in a background thread using the
map-constrained route engine and streams frames that the page polls with
``GET /api/runs/<id>/frames?from=<k>``, so playback starts immediately while
the simulation is still computing. ``GET /api/runs/<id>/export`` returns the
run as one replayable JSON document (``web_sandbox.run_export``).
``POST /api/simulate`` (abstract corridor engine) is LEGACY: kept for the
earlier API contract, not used by the page. Binds to loopback only.
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
from simulation.dtc_console import validate_command
from simulation.scenario_presets import build_preset_request, list_presets, load_preset, script_by_tick
from simulation.road_network import load_road_network
from simulation.route_engine import (ARCHITECTURES, flight_from_row, flight_manifest, initial_conditions_hash,
                                     plan_flights, simulate_routes)
from simulation.scenario_manifest import (_merge_config, drones_from_csv, drones_from_json, drones_to_csv,
                                          drones_to_json, prepare_scenario_manifest, validate_route_drones)
from simulation.engine import run_simulation
from web_sandbox.run_export import build_export
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
        self.manifest: dict[str, Any] = {}       # the start response (flights, switches, ...)
        self.config: dict[str, Any] = {}
        self.commands: list[dict[str, Any]] = []  # operator command log: every command with its applied tick
        self.pending: list[dict[str, Any]] = []   # submitted, not yet picked up by the engine
        self.network = None
        self.duration = 0.0
        self.ids: set[int] = set()
        self.view_t: float | None = None     # playback time reported by the page (pacing)
        self.sel: list[int] = []             # drones whose full health detail goes into frames
        self.script: dict[int, list[dict[str, Any]]] = {}   # preset script, by tick
        self.compare: list[dict[str, Any]] = []             # preset variants (headless) for comparison
        self.view_seen = 0.0                 # wall time of the last report
        self.lead_s = 5.0
        self.watch_timeout_s = 5.0

    def watch(self, view_t: float) -> None:
        self.view_t, self.view_seen = float(view_t), time.time()

    def pace(self, t: float) -> None:
        """Hold the engine at most ``lead_s`` ahead of the page's playback while a page is watching.

        Pacing only changes *when* ticks are computed, never what they compute; commands
        are still applied at a logged tick, so replays stay exact.
        """
        while (not self.stop_flag and self.view_t is not None and t > self.view_t + self.lead_s
               and time.time() - self.view_seen < self.watch_timeout_s and not self.pending):
            time.sleep(0.02)

    def submit(self, cmd: dict[str, Any]) -> None:
        with self.lock:
            self.commands.append(cmd)
            self.pending.append(cmd)

    def drain(self, k: int, t: float) -> list[dict[str, Any]]:
        """Engine side: commands to apply at the start of tick k (preset script + all submitted so far)."""
        if k in self.script:   # preset script: logged like operator commands (marked scripted)
            for body in self.script.pop(k):
                with self.lock:
                    cmd = _make_cmd(self, body)
                    cmd["scripted"] = True
                    self.commands.append(cmd)
                    self.pending.append(cmd)
        self.pace(t)
        with self.lock:
            out, self.pending = self.pending, []
        return out

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
    if body.get("preset"):   # Phase 5: scripted preset (its request, named drones and timed commands)
        preset = load_preset(str(body["preset"]))
        variant = _int(body.get("variant", 0), "variant", 0, 20)
        req, script, names = build_preset_request(preset, variant)
        prepared = prepare_live_run(req)
        known = {f.agent_id for f in prepared["flights"]}
        cfg = prepared["config"]
        for e in script:   # validate the whole script before the run starts
            validate_command({k: v for k, v in e.items() if k != "t"}, known,
                             [v.id for v in prepared["network"].vertiports], int(cfg["airspace"]["num_layers"]),
                             prepared["duration"], float(cfg["safety"]["maximum_velocity_meters_per_second"]), 6)
        variants = [v["label"] for v in preset.get("variants", [])]
        prepared.update(script=script_by_tick(script, float(cfg["simulation"]["timestep_seconds"])),
                        preset={"id": preset["id"], "title": preset["title"], "description": preset["description"],
                                "timeline": preset.get("timeline", []), "kpi_focus": preset.get("kpi_focus", []),
                                "variant": variant, "variants": variants, "names": names})
        return prepared
    overrides = body.get("config", {}) or {}
    if isinstance(overrides, dict) and "web" in overrides:
        raise ValueError("web.* limits are server settings and cannot be overridden per run")
    config = _merge_config(get_config(), overrides)
    web = web_limits(config)
    max_fleet, max_duration = int(web["max_fleet"]), float(web["max_duration_s"])
    custom_rows = body.get("drones") or []
    fleet = _int(body.get("fleet", 60), "fleet", 0 if custom_rows else 1, max_fleet)
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
    dh = config.get("drone_health", {}) or {}
    if dh:   # weather controls (ambient temperature, wind) from the page
        _float(dh.get("ambient_c", 35.0), "weather: ambient temperature (°C)", -20.0, 55.0)
        wind = dh.get("wind_mps", [0.0, 0.0])
        if not (isinstance(wind, list) and len(wind) == 2 and all(isinstance(w, (int, float)) for w in wind)):
            raise ValueError("weather: wind must be [east, north] m/s")
        if float(np.hypot(*wind)) > 15.0:
            raise ValueError("weather: wind speed must be at most 15 m/s")

    map_id, network = _network(body.get("map"))
    flights = plan_flights(network, fleet, mix, seed, window) if fleet else []
    if custom_rows:  # custom drones (scenario builder / import) next to the random fleet
        rows = validate_route_drones(custom_rows, [v.id for v in network.vertiports], config, duration,
                                     taken_ids={f.agent_id for f in flights})
        if len(flights) + len(rows) > max_fleet:
            raise ValueError(f"random fleet {len(flights)} + {len(rows)} custom drones exceeds web.max_fleet = {max_fleet}")
        flights = sorted(flights + [flight_from_row(network, r) for r in rows], key=lambda f: f.depart_s)

    attack_cfg = dict(config.get("attack", {}))
    attack = body.get("attack", {}) or {}
    attack_cfg["enabled"] = bool(attack.get("enabled", False))
    if attack_cfg["enabled"]:
        start_s = _float(attack.get("start_s", duration * 0.2), "attack.start_s", 0.0, duration)
        cruise = float(config["local_behavior"]["v_cruise"]) * 0.9
        delivery = [f for f in flights if f.type.value == "DELIVERY" and not f.custom] or [f for f in flights if not f.custom] or list(flights)
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
    for key in ("use_overseer", "use_admm", "defended", "junction_merge"):
        value = body.get(key, True)
        if not isinstance(value, bool):
            raise ValueError(f"{key} must be true or false")
        switches[key] = value
    architecture = body.get("architecture", "hierarchical")
    if architecture not in ARCHITECTURES:
        raise ValueError(f"architecture must be one of: {', '.join(ARCHITECTURES)}")
    fixed = ARCHITECTURES[architecture]
    if fixed is not None:  # the architecture decides DTC / ADMM / defence
        switches["use_overseer"], switches["use_admm"], switches["defended"] = fixed[:3]
        if fixed[3]:
            switches["junction_merge"] = False   # centralized: the DTC computes every velocity

    return {"map": map_id, "network": network, "flights": flights, "duration": duration, "config": config,
            "attack": attack_cfg, "link": link_cfg, "seed": seed, "fleet": fleet, "architecture": architecture,
            "ic_hash": initial_conditions_hash(flights, seed),
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
            spatial_index=bool(prepared["web"]["spatial_index"]),
            architecture=prepared.get("architecture", "hierarchical"),
            junction_merge=prepared.get("junction_merge", True),
            command_source=run.drain, seed=prepared["seed"],
            health_detail_ids=lambda: run.sel)
        seq, prev_stats, prev_prio = 0, None, None
        for item in gen:
            pending_events.extend(item["events"])
            if item.get("partial"):
                continue  # light tick: its events ride on the next full frame
            frame = compact_frame(_json_safe(dict(item, events=pending_events)), seq, prev_stats, max_edges,
                                  prev_prio)
            prev_stats = frame["stats"] if "stats" in frame else prev_stats
            prev_prio = frame["prio"] if "prio" in frame else prev_prio
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
    cfg = prepared["config"]
    manifest = _json_safe({
        "run_id": run_id,
        "map": prepared["map"],
        "architecture": prepared["architecture"],
        "ic_hash": prepared["ic_hash"],
        "preset": prepared.get("preset"),
        "safety_definition": "layer-aware 3D: min over pairs of |(dx, dy, Δlayer·layer height)| (route engine); "
                             "verification/metrics.py robustness_series is horizontal-only",
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
        "switches": {k: prepared[k] for k in ("use_overseer", "use_admm", "defended", "junction_merge")},
        "limits": {
            "d_min": float(cfg["safety"]["minimum_separation_meters"]),
            "corridor_width": float(cfg["corridors"]["width_meters"]),
            "num_layers": int(cfg["airspace"]["num_layers"]),
            "layer_height": float(cfg["airspace"]["layer_height_meters"]),
            "emergency_layer": int(cfg["airspace"].get("emergency_layer", 2)),
            "capacity": int(cfg["corridors"]["capacity"]),
            "merge_gap": float(cfg["local_behavior"]["merge_gap"]),
            "health": ({"enabled": True, "ambient_c": float(cfg["drone_health"]["ambient_c"]),
                        "thresholds": cfg["drone_health"]["thresholds"]}
                       if cfg.get("drone_health", {}).get("enabled") else {"enabled": False}),
            "max_iterations": int(cfg["admm"]["maximum_iterations"]),
        },
    })
    run.manifest, run.config = manifest, _json_safe(cfg)
    run.network, run.duration = prepared["network"], prepared["duration"]
    run.script = dict(prepared.get("script") or {})
    if prepared.get("preset") and len(prepared["preset"]["variants"]) > 1:
        _start_compare(run, body, prepared)
    run.lead_s = float(prepared["web"]["interactive_lead_s"])
    run.watch_timeout_s = float(prepared["web"]["watcher_timeout_s"])
    run.ids = {f.agent_id for f in prepared["flights"]}
    run.thread = threading.Thread(target=_run_worker, args=(run, prepared), daemon=True)
    run.thread.start()
    return manifest


def _make_cmd(run: LiveRun, body: dict[str, Any]) -> dict[str, Any]:
    """Validated command dict (caller holds ``run.lock``)."""
    if not isinstance(body, dict):
        raise ValueError("command must be a JSON object")
    cfg = run.config
    if True:
        cid = f"c{len(run.commands) + 1}"
        if body.get("type") == "add_drone":
            row = dict(body.get("drone") or {})
            row.pop("depart_s", None)   # "Add drone now": departs at the current sim time
            [valid] = validate_route_drones([row], [v.id for v in run.network.vertiports], cfg,
                                            run.duration, taken_ids=set(run.ids))
            run.ids.add(valid["id"])
            cmd = {"command_id": cid, "type": "add_drone", "drone": valid, "targets": [], "params": {},
                   "reason": str(body.get("reason", ""))[:200], "dry_run": False}
        else:
            cmd = {"command_id": cid, **validate_command(
                body, set(run.ids), [v.id for v in run.network.vertiports], int(cfg["airspace"]["num_layers"]),
                run.duration, float(cfg["safety"]["maximum_velocity_meters_per_second"]), 6)}
        cmd.update(status="sent", tick_received=None, t_received=None, tick_delivered=None, results={}, outcome=None)
    return cmd


def submit_command(run: LiveRun, body: dict[str, Any]) -> dict[str, Any]:
    """Validate an operator command and queue it for the engine (applied at the start of its next tick).

    ``add_drone`` (Phase 3) is a ground-side action. Every other type is a DTC console
    command (``simulation.dtc_console``) that crosses the DTC link; with ``dry_run`` the
    engine only reports the energy feasibility per target.
    """
    with run.lock:
        cmd = _make_cmd(run, body)
    run.submit(cmd)
    return {"command_id": cmd["command_id"], "status": "sent", **({"drone_id": cmd["drone"]["id"]} if "drone" in cmd else {})}


def scripted_commands(log: list[dict[str, Any]]):
    """Command source for replay: re-applies each logged command at the tick it entered the engine.

    Delivery (link up / queued / lost) and the outcome are re-derived by the engine, so
    the replay reproduces them; dry-run checks are skipped (they change nothing).
    """
    by_tick: dict[int, list[dict[str, Any]]] = {}
    for c in log:
        k = c.get("tick_received", c.get("tick_applied"))
        if k is not None and not c.get("dry_run"):
            fresh = {key: v for key, v in c.items() if key in ("command_id", "type", "drone", "targets", "params",
                                                               "reason", "force", "dry_run")}
            by_tick.setdefault(int(k), []).append(fresh)
    return lambda k, t: by_tick.pop(k, [])


def _drone_context(body: dict[str, Any]):
    config = get_config()
    _, network = _network(body.get("map"))
    duration = float(body.get("duration_s") or web_limits(config)["max_duration_s"])
    return config, network, duration


def parse_drones(body: dict[str, Any]) -> dict[str, Any]:
    """Import: CSV or JSON text -> validated drone rows (per-row error messages on failure)."""
    config, network, duration = _drone_context(body)
    fmt, text = body.get("format"), body.get("text", "")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("the file is empty")
    if fmt == "csv":
        rows = drones_from_csv(text)
    elif fmt == "json":
        try:
            rows = drones_from_json(json.loads(text))
        except json.JSONDecodeError as exc:
            raise ValueError(f"not valid JSON: {exc}") from None
    else:
        raise ValueError("format must be 'csv' or 'json'")
    taken = set(range(int(body.get("random_fleet", 0) or 0)))
    valid = validate_route_drones(rows, [v.id for v in network.vertiports], config, duration, taken)
    for r, src in zip(valid, rows):   # ids the file did not set are assigned at launch, after the random fleet
        if isinstance(src, dict) and src.get("id") in (None, ""):
            r["id"] = None
    return {"drones": valid}


def export_drones(body: dict[str, Any]) -> dict[str, Any]:
    config, network, duration = _drone_context(body)
    raw = body.get("drones") or []
    rows = validate_route_drones(raw, [v.id for v in network.vertiports], config, duration)
    for r, src in zip(rows, raw):   # keep ids the user set; auto-assigned ids would clash with the random fleet
        if isinstance(src, dict) and src.get("id") in (None, ""):
            r["id"] = None
    if body.get("format") == "csv":
        return {"text": drones_to_csv(rows), "filename": "masooda_drones.csv"}
    return {"text": json.dumps(drones_to_json(rows), indent=1), "filename": "masooda_drones.json"}


COMPARE_KEYS = ("arrivals", "delivered", "crashes", "near_misses", "safety_violation_ticks", "min_separation_m",
                "pad_holds", "admm_events", "tactical_layer_shifts", "diversions", "forced_landings", "energy_depleted",
                "energy_used_wh", "energy_per_delivered_wh", "max_pack_c", "max_motor_c", "bms_alerts", "missions",
                "services", "service_wait_s")


def run_kpis(stats: dict[str, Any], prio: dict[str, Any] | None) -> dict[str, Any]:
    out = {k: stats.get(k) for k in COMPARE_KEYS}
    out["emergency_mean_delay_s"] = (prio or {}).get("mean_delay_s")
    out["priority_compliance"] = (prio or {}).get("rate")
    return out


def _start_compare(run: LiveRun, body: dict[str, Any], prepared: dict[str, Any]) -> None:
    """Run the preset's other variants headless with the same seed, for the comparison table.

    The live run is paced to playback, so these use the idle CPU in between.
    """
    labels = prepared["preset"]["variants"]
    main = prepared["preset"]["variant"]
    run.compare = [{"label": lab, "variant": i, "live": i == main, "done": False, "kpis": None, "error": None}
                   for i, lab in enumerate(labels)]

    def worker():
        for entry in run.compare:
            if entry["live"] or run.stop_flag:
                continue
            try:
                p = prepare_live_run({"preset": prepared["preset"]["id"], "variant": entry["variant"]})
                src = p.get("script") or {}
                last, prio = {}, None
                for item in simulate_routes(
                        p["network"], p["flights"], p["duration"], config=p["config"], use_overseer=p["use_overseer"],
                        use_admm=p["use_admm"], defended=p["defended"], attack_config=p["attack"],
                        overseer_link_config=p["link"], should_stop=lambda: run.stop_flag, frame_every=50,
                        spatial_index=bool(p["web"]["spatial_index"]), architecture=p["architecture"],
                        junction_merge=p["junction_merge"], seed=p["seed"],
                        command_source=lambda k, t, src=src: [_headless_cmd(c) for c in src.pop(k, [])]):
                    last = item.get("stats", last)
                    prio = item.get("prio", prio)
                entry["kpis"] = run_kpis(_json_safe(last), _json_safe(prio))
                entry["done"] = not run.stop_flag
            except Exception as exc:   # shown in the comparison table
                traceback.print_exc()
                entry["error"] = f"{type(exc).__name__}: {exc}"

    threading.Thread(target=worker, daemon=True).start()


def _headless_cmd(body: dict[str, Any]) -> dict[str, Any]:
    return dict(body, command_id="s", status="sent", tick_received=None, results={}, outcome=None)


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
                                                             "target_frames_per_sim_s", "interactive_lead_s")}})
            elif route == "/api/presets":
                self._send_json(200, {"presets": list_presets()})
            elif route.startswith("/api/runs/") and route.endswith("/compare"):
                run = RUNS.get(route.split("/")[3])
                if run is None:
                    self._send_json(404, {"error": "run_not_found"})
                    return
                out = []
                for e in run.compare:
                    e = dict(e)
                    if e["live"]:   # the live variant's numbers come from its own frames
                        frames, _ = run.store.since(0, 10 ** 9)
                        stats, prio = {}, None
                        for f in frames:
                            stats = f.get("stats", stats)
                            prio = f.get("prio", prio)
                        e.update(done=run.done, kpis=run_kpis(stats, prio) if stats else None)
                    out.append(e)
                self._send_json(200, {"variants": out})
            elif route == "/api/architectures":
                self._send_json(200, {"default": "hierarchical", "architectures": list(ARCHITECTURES)})
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
            elif route.startswith("/api/runs/") and route.endswith("/export"):
                run = RUNS.get(route.split("/")[3])
                if run is None:
                    self._send_json(404, {"error": "run_not_found"})
                    return
                frames, _ = run.store.since(0, 10**9)
                export = build_export(run.manifest, run.request, run.config, frames, run.commands,
                                      complete=run.done and run.error is None, thinned=run.store.thinned)
                payload = json.dumps(_json_safe(export), allow_nan=False, separators=(",", ":")).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Content-Disposition", f'attachment; filename="masooda_run_{run.id}.json"')
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(payload)
            elif route.startswith("/api/runs/") and route.endswith("/commands"):
                run = RUNS.get(route.split("/")[3])
                if run is None:
                    self._send_json(404, {"error": "run_not_found"})
                    return
                with run.lock:
                    cmds = [{k: v for k, v in c.items() if k != "drone"} | ({"drone_id": c["drone"]["id"]} if "drone" in c else {})
                            for c in run.commands]
                self._send_json(200, {"commands": cmds})
            elif route.startswith("/api/runs/") and route.endswith("/frames"):
                run = RUNS.get(route.split("/")[3])
                if run is None:
                    self._send_json(404, {"error": "run_not_found"})
                    return
                query = parse_qs(url.query)
                start = int(query.get("from", ["0"])[0])
                if "view_t" in query:   # the page's playback time paces the simulator
                    run.watch(float(query["view_t"][0]))
                if "sel" in query:      # selected drone: full health detail in the next frames
                    run.sel = [int(x) for x in query["sel"][0].split(",") if x.strip().lstrip("-").isdigit()][:4]
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
            elif route.startswith("/api/runs/") and route.endswith("/commands"):
                run = RUNS.get(route.split("/")[3])
                if run is None:
                    self._send_json(404, {"error": "run_not_found"})
                    return
                if run.done:
                    self._send_json(409, {"error": "run_finished", "message": "The run has finished; launch a new one."})
                    return
                self._send_json(202, submit_command(run, self._read_json()))
            elif route == "/api/drones/parse":
                self._send_json(200, parse_drones(self._read_json()))
            elif route == "/api/drones/export":
                self._send_json(200, export_drones(self._read_json()))
            elif route.startswith("/api/runs/") and route.endswith("/stop"):
                run = RUNS.get(route.split("/")[3])
                if run:
                    run.stop()
                self._send_json(200, {"stopped": bool(run)})
            elif route == "/api/simulate":  # LEGACY: abstract three-corridor engine, not used by the page
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
