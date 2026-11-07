"""Scripted scenario presets (Phase 5): ``data/scenarios/<id>.json``.

A preset is a run request (map, fleet, mix, duration, seed, architecture, switches,
weather, attack, outage, operations), named custom drones, and a timed command
script in the DTC console API (``simulation.dtc_console``). Optional ``variants``
re-run the same seed with different overrides for a side-by-side comparison.

Script entries: ``{"t": seconds, "type": ..., "targets": ["@name", 12], "params": {...}, "reason": ...}``.
``@name`` refers to a named custom drone; it gets the id ``fleet + k`` (k = its
position in ``drones``), so ids are fixed before the run and replays are exact.
Macros expand into script entries; ``moving_cell`` makes a drifting restricted area
from a chain of overlapping, time-sliced polygons.
"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any

PRESET_DIR = Path(__file__).resolve().parents[1] / "data" / "scenarios"


def _octagon(cx: float, cy: float, r: float) -> list[list[float]]:
    return [[round(cx + r * math.cos(math.pi / 8 + k * math.pi / 4), 1),
             round(cy + r * math.sin(math.pi / 8 + k * math.pi / 4), 1)] for k in range(8)]


def expand_macros(macros: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for m in macros or []:
        if m.get("type") != "moving_cell":
            raise ValueError(f"unknown preset macro {m.get('type')!r}")
        steps = int(m["steps"])
        t0, t1 = float(m["start_s"]), float(m["end_s"])
        (x0, y0), (x1, y1) = m["from"], m["to"]
        slot = (t1 - t0) / steps
        for k in range(steps):
            a = k / max(1, steps - 1)
            out.append({"t": round(t0 + k * slot - 1.0, 1) if k else t0, "type": "tfr", "targets": [],
                        "params": {"polygon": _octagon(x0 + (x1 - x0) * a, y0 + (y1 - y0) * a, float(m["radius_m"])),
                                   "start_s": round(t0 + k * slot, 1),
                                   "end_s": round(t0 + (k + 1) * slot + float(m.get("overlap_s", 3.0)), 1),
                                   "name": f"{m.get('name', 'Cell')}-{k + 1}"},
                        "reason": m.get("reason", "weather cell")})
    return out


def list_presets() -> list[dict[str, Any]]:
    out = []
    for path in sorted(PRESET_DIR.glob("*.json")):
        p = json.loads(path.read_text(encoding="utf-8"))
        req = p["request"]
        out.append({"id": p["id"], "order": p.get("order", 99), "title": p["title"], "description": p["description"],
                    "timeline": p.get("timeline", []), "kpi_focus": p.get("kpi_focus", []),
                    "variants": [v["label"] for v in p.get("variants", [])],
                    "map": req.get("map", "iith"), "fleet": req.get("fleet"), "duration_s": req.get("duration_s"),
                    "custom_drones": len(p.get("drones", []))})
    return sorted(out, key=lambda x: (x["order"], x["id"]))


def load_preset(preset_id: str) -> dict[str, Any]:
    path = PRESET_DIR / f"{preset_id}.json"
    if not path.is_file() or path.parent != PRESET_DIR:
        raise ValueError(f"unknown preset '{preset_id}'")
    return json.loads(path.read_text(encoding="utf-8"))


def _deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = _deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else copy.deepcopy(v)
    return out


def build_preset_request(preset: dict[str, Any], variant: int = 0) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, int]]:
    """(run request, script with '@name' targets resolved to ids, name -> id) for one variant."""
    variants = preset.get("variants") or [{"label": "main"}]
    if not 0 <= variant < len(variants):
        raise ValueError(f"preset '{preset['id']}' has {len(variants)} variant(s)")
    v = variants[variant]
    req = _deep_merge(preset["request"], v.get("request", {}))
    fleet = int(req.get("fleet", 0))
    names: dict[str, int] = {}
    drones = []
    for k, row in enumerate(preset.get("drones", [])):
        row = dict(row)
        name = row.pop("name", None)
        row["id"] = fleet + k
        if name:
            names[name] = row["id"]
        drones.append(row)
    if drones:
        req["drones"] = drones
    script = [*preset.get("script", []), *expand_macros(preset.get("macros", [])), *v.get("script", [])]
    resolved = []
    for e in sorted(script, key=lambda e: float(e["t"])):
        tg = []
        for x in e.get("targets", []):
            if isinstance(x, str) and x.startswith("@"):
                if x[1:] not in names:
                    raise ValueError(f"preset '{preset['id']}': script target {x} is not a named drone")
                tg.append(names[x[1:]])
            else:
                tg.append(int(x))
        resolved.append({"t": float(e["t"]), "type": e["type"], "targets": tg, "params": dict(e.get("params", {})),
                         "reason": e.get("reason", f"preset {preset['id']}"), "force": bool(e.get("force", False))})
    req["preset"] = None
    return req, resolved, names


def script_by_tick(script: list[dict[str, Any]], dt: float) -> dict[int, list[dict[str, Any]]]:
    out: dict[int, list[dict[str, Any]]] = {}
    for e in script:
        body = {k: v for k, v in e.items() if k != "t"}
        out.setdefault(int(round(e["t"] / dt)), []).append(body)
    return out
