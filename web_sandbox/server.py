"""Local HTTP bridge between the scenario editor and MASooda's real simulator.

Run from the repository root with ``python -m web_sandbox.server`` and open
http://127.0.0.1:8765. This demo server intentionally binds to loopback only.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import traceback
from typing import Any
from urllib.parse import urlparse

import numpy as np

from config.load_config import get_config
from simulation.scenario_manifest import prepare_scenario_manifest
from simulation.engine import run_simulation
import local_behavior.boids as boids
import simulation.overseer as overseer
from verification.metrics import compute_run_metrics

ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT / "web_sandbox"
MAX_REQUEST_BYTES = 2_000_000
MAX_AGENT_TICKS = 50_000


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


class ScenarioHandler(BaseHTTPRequestHandler):
    server_version = "MASoodaDemo/1.0"

    def _send_json(self, status: int, value: Any) -> None:
        payload = json.dumps(_json_safe(value), allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        route = urlparse(self.path).path
        if route in ("/", "/index.html"):
            payload = (WEB_ROOT / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        elif route == "/api/config":
            self._send_json(200, get_config())
        else:
            self._send_json(404, {"error": "route_not_found"})

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/api/simulate":
            self._send_json(404, {"error": "route_not_found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_REQUEST_BYTES:
                raise ValueError(f"Request body must be between 1 and {MAX_REQUEST_BYTES} bytes")
            manifest = json.loads(self.rfile.read(length))
            prepared = prepare_scenario_manifest(manifest)
            dt = float(prepared["config"]["simulation"]["timestep_seconds"])
            steps = int(round(float(prepared["duration_s"]) / dt))
            samples = (steps + 1) * len(prepared["agents"])
            if samples > MAX_AGENT_TICKS:
                raise ValueError(
                    f"Run requests {samples} agent-ticks; local web demo limit is {MAX_AGENT_TICKS}"
                )

            # The current simulator has module-level behavioral state. Serve runs
            # sequentially and reset these caches to keep scenarios independent.
            boids.reset_local_behavior_cache()
            overseer.reset_default_overseer()
            result = run_simulation(
                agents=prepared["agents"],
                duration_s=prepared["duration_s"],
                use_overseer=prepared["use_overseer"],
                use_admm=prepared["use_admm"],
                attack_config=prepared["attack_config"],
                defended=prepared["defended"],
                overseer_link_config=prepared["overseer_link_config"],
                config=prepared["config"],
            )
            metrics = compute_run_metrics(result, config=prepared["config"])
            self._send_json(200, {
                "times": result.times,
                "agent_ids": result.agent_ids,
                "tasks": prepared["tasks"],
                "positions": result.positions,
                "velocities": result.velocities,
                "metrics": metrics,
            })
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self._send_json(400, {"error": "invalid_scenario", "message": str(exc)})
        except Exception as exc:  # Return a traceable failure without pretending a run succeeded.
            traceback.print_exc()
            self._send_json(500, {"error": "simulation_failed", "message": str(exc)})

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[web] {self.address_string()} {format % args}")


def main() -> None:
    server = HTTPServer(("127.0.0.1", 8765), ScenarioHandler)
    print("MASooda scenario editor: http://127.0.0.1:8765")
    print("API: GET /api/config, POST /api/simulate")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping MASooda local demo server")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
