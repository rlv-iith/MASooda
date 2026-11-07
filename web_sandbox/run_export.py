"""Run export for the live demo ("Download run" / "Load run").

An export is one JSON document that replays without re-simulating:

* ``manifest``: what the browser received when the run started (map, seed,
  architecture, initial-conditions hash, flights with routes, switches, limits);
* ``request``: the run request as sent by the browser;
* ``config``: the fully resolved configuration used by the engine;
* ``commands``: operator command log with ticks (empty until the Phase 4 DTC console);
* ``frames``: every stored compact v2 frame (``web_sandbox.streaming``);
* ``kpis``: per-frame KPI rows (time, robustness, stats, ADMM, compliance, merging);
* ``events``: every governance event, in order.

``config_hash`` and the initial-conditions hash let two exports be compared.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

EXPORT_FORMAT = "masooda-run"
EXPORT_VERSION = 1
KPI_STATS = ("arrivals", "crashes", "near_misses", "safety_violation_ticks", "min_separation_m", "admm_events",
             "admm_nonconverged", "tactical_layer_shifts", "dtc_directives", "layer_changes", "pad_holds",
             "reports_dropped", "spoofed_reports_accepted", "tube_corrections")


def config_hash(config: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()[:12]


def kpi_rows(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows, stats, prio = [], {}, {}
    for f in frames:
        stats = f.get("stats", stats)  # carried forward (v2 frames omit unchanged stats / prio)
        prio = f.get("prio") or prio
        admm = (f.get("admm") or {}).get("run", {})
        merge = f.get("merge") or {}
        rows.append({
            "t": f["t"], "rho": f.get("rho"),
            "airborne": sum(1 for v in f.get("ls", []) if v >> 3 == 1),
            **{k: stats.get(k) for k in KPI_STATS},
            "admm_it_p95": admm.get("it_p95"), "admm_ms_p95": admm.get("ms_p95"), "admm_fallback": admm.get("fallback"),
            "priority_compliance": prio.get("rate"), "emergency_mean_delay_s": prio.get("mean_delay_s"),
            "merge_success_rate": merge.get("rate"), "platoons": merge.get("platoons"),
        })
    return rows


def build_export(manifest: dict[str, Any], request: dict[str, Any], config: dict[str, Any],
                 frames: list[dict[str, Any]], commands: list[dict[str, Any]], complete: bool,
                 thinned: int = 0) -> dict[str, Any]:
    return {
        "format": EXPORT_FORMAT, "version": EXPORT_VERSION,
        "complete": bool(complete), "frames_thinned": int(thinned),
        "config_hash": config_hash(config),
        "manifest": manifest, "request": request, "config": config, "commands": list(commands),
        "frames": frames, "kpis": kpi_rows(frames),
        "events": [e for f in frames for e in f.get("events", [])],
    }


def validate_export(data: Any) -> None:
    """Raise ValueError with a readable message when ``data`` is not a replayable export."""
    if not isinstance(data, dict) or data.get("format") != EXPORT_FORMAT:
        raise ValueError("not a MASooda run export (format field missing)")
    if data.get("version") != EXPORT_VERSION:
        raise ValueError(f"unsupported export version {data.get('version')} (expected {EXPORT_VERSION})")
    for key in ("manifest", "frames", "config"):
        if key not in data:
            raise ValueError(f"export is missing '{key}'")
    if not data["frames"] or any(f.get("v") != 2 for f in data["frames"]):
        raise ValueError("export frames must be non-empty compact v2 frames")
    if len(data["manifest"].get("flights", [])) != len(data["frames"][0]["x"]):
        raise ValueError("export flights do not match the frame width")
