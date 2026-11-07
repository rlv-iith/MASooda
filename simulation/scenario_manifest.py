"""Validate and materialize user-authored simulation run manifests.

This module is the input boundary for the browser-based simulator. A manifest
contains a complete (or partial) config override and explicit per-agent start,
destination, type, and control state. It never writes the shared YAML file.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import numpy as np

from config.load_config import get_config
from .schema import AgentState, AgentType


_PRIORITY_BY_TYPE = {
    AgentType.EMERGENCY: 0,
    AgentType.EVTOL: 1,
    AgentType.DELIVERY: 2,
}
_TOP_LEVEL_KEYS = {
    "config",
    "duration_s",
    "agents",
    "use_overseer",
    "use_admm",
    "defended",
    "overseer_link_config",
    "attack_config",
}


def _merge_config(base: dict[str, Any], override: dict[str, Any], path: str = "config") -> dict[str, Any]:
    """Deep-merge known config keys, rejecting typos and incompatible value types."""
    if not isinstance(override, dict):
        raise ValueError(f"{path} must be an object")
    merged = deepcopy(base)
    for key, value in override.items():
        normalized_key = key
        if normalized_key not in base and isinstance(normalized_key, str):
            # JSON object keys are strings, while YAML priority maps use integers.
            try:
                candidate = int(normalized_key)
            except ValueError:
                candidate = None
            if candidate in base:
                normalized_key = candidate
        if normalized_key not in base:
            raise ValueError(f"Unknown configuration key: {path}.{key}")
        current = base[normalized_key]
        current_path = f"{path}.{normalized_key}"
        if isinstance(current, dict):
            if not isinstance(value, dict):
                raise ValueError(f"{current_path} must be an object")
            merged[normalized_key] = _merge_config(current, value, current_path)
        elif isinstance(current, bool):
            if not isinstance(value, bool):
                raise ValueError(f"{current_path} must be a boolean")
            merged[normalized_key] = value
        elif isinstance(current, (int, float)) and not isinstance(current, bool):
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not np.isfinite(value)
                or (isinstance(current, int) and not isinstance(value, int))
            ):
                raise ValueError(f"{current_path} must be numeric")
            merged[normalized_key] = value
        elif isinstance(current, list):
            if not isinstance(value, list):
                raise ValueError(f"{current_path} must be a list")
            merged[normalized_key] = deepcopy(value)
        elif not isinstance(value, type(current)):
            raise ValueError(f"{current_path} must be a {type(current).__name__}")
        else:
            merged[normalized_key] = value
    return merged


def _vector3(value: Any, field_name: str) -> np.ndarray:
    """Parse a finite three-component vector supplied by the user interface."""
    try:
        vector = np.asarray(value, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"agents[].{field_name} must be a numeric 3-vector") from exc
    if vector.shape != (3,) or not np.all(np.isfinite(vector)):
        raise ValueError(f"agents[].{field_name} must be a finite 3-vector")
    return vector


def prepare_scenario_manifest(
    manifest: dict[str, Any],
    base_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate one browser/API request and return run-ready config and agents.

    Each agent can specify ``task`` as a UI label, ``type``, ``position``,
    ``destination``, optional velocity/acceleration, priority, corridor, and
    altitude layer. The label is returned as metadata for display; motion is
    driven by the supplied destination and simulation configuration.
    """
    if not isinstance(manifest, dict):
        raise ValueError("manifest must be a JSON object")
    unknown = set(manifest) - _TOP_LEVEL_KEYS
    if unknown:
        raise ValueError(f"Unknown manifest fields: {', '.join(sorted(unknown))}")

    config_base = deepcopy(base_config if base_config is not None else get_config())
    config = _merge_config(config_base, manifest.get("config", {}))

    duration_s = manifest.get("duration_s", config.get("simulation", {}).get("duration_seconds"))
    if not isinstance(duration_s, (int, float)) or isinstance(duration_s, bool):
        raise ValueError("duration_s must be numeric")
    duration_s = float(duration_s)
    if not np.isfinite(duration_s) or duration_s <= 0.0:
        raise ValueError("duration_s must be finite and greater than zero")

    raw_agents = manifest.get("agents")
    if not isinstance(raw_agents, list) or not raw_agents:
        raise ValueError("agents must be a non-empty list")

    agents: list[AgentState] = []
    tasks: dict[int, str] = {}
    seen_ids: set[int] = set()
    corridor_count = int(config.get("corridors", {}).get("count", 0))
    for index, raw in enumerate(raw_agents):
        if not isinstance(raw, dict):
            raise ValueError(f"agents[{index}] must be an object")
        allowed_agent_keys = {
            "id", "type", "task", "position", "velocity", "acceleration",
            "destination", "priority", "corridor_assignment", "altitude_layer",
        }
        extra = set(raw) - allowed_agent_keys
        if extra:
            raise ValueError(f"Unknown agents[{index}] fields: {', '.join(sorted(extra))}")

        agent_id = raw.get("id", index)
        if isinstance(agent_id, bool) or not isinstance(agent_id, int) or agent_id < 0:
            raise ValueError(f"agents[{index}].id must be a non-negative integer")
        if agent_id in seen_ids:
            raise ValueError(f"Duplicate agent id: {agent_id}")
        seen_ids.add(agent_id)

        try:
            agent_type = AgentType(str(raw.get("type", "DELIVERY")).upper())
        except ValueError as exc:
            choices = ", ".join(item.value for item in AgentType)
            raise ValueError(f"agents[{index}].type must be one of: {choices}") from exc

        default_priority = _PRIORITY_BY_TYPE[agent_type]
        priority = raw.get("priority", default_priority)
        if isinstance(priority, bool) or not isinstance(priority, int) or priority < 0:
            raise ValueError(f"agents[{index}].priority must be a non-negative integer")

        corridor = raw.get("corridor_assignment")
        if corridor is not None:
            if isinstance(corridor, bool) or not isinstance(corridor, int):
                raise ValueError(f"agents[{index}].corridor_assignment must be an integer or null")
            if corridor < 0 or corridor >= corridor_count:
                raise ValueError(f"agents[{index}].corridor_assignment must be within configured corridors")

        layer = raw.get("altitude_layer", 0)
        if isinstance(layer, bool) or not isinstance(layer, int):
            raise ValueError(f"agents[{index}].altitude_layer must be an integer layer index")

        agents.append(AgentState(
            id=agent_id,
            type=agent_type,
            position=_vector3(raw.get("position"), "position"),
            velocity=_vector3(raw.get("velocity", [0.0, 0.0, 0.0]), "velocity"),
            acceleration=_vector3(raw.get("acceleration", [0.0, 0.0, 0.0]), "acceleration"),
            destination=_vector3(raw.get("destination"), "destination"),
            priority=priority,
            corridor_assignment=corridor,
            altitude_layer=layer,
        ))
        task = raw.get("task", "")
        if not isinstance(task, str):
            raise ValueError(f"agents[{index}].task must be text")
        tasks[agent_id] = task

    for key in ("use_overseer", "use_admm", "defended"):
        if key in manifest and not isinstance(manifest[key], bool):
            raise ValueError(f"{key} must be a boolean")
    for key in ("overseer_link_config", "attack_config"):
        if key in manifest and not isinstance(manifest[key], dict):
            raise ValueError(f"{key} must be an object")

    return {
        "config": config,
        "duration_s": duration_s,
        "agents": agents,
        "tasks": tasks,
        "use_overseer": manifest.get("use_overseer", True),
        "use_admm": manifest.get("use_admm", True),
        "defended": manifest.get("defended", True),
        "overseer_link_config": deepcopy(manifest.get("overseer_link_config")),
        "attack_config": deepcopy(manifest.get("attack_config", config.get("attack", {}))),
    }


# ============================================================================ route mode
# Custom drones for the map-constrained live demo (Phase 3). One row per drone;
# the same rows come from the scenario builder form, JSON and CSV import, and
# the mid-run "Add drone now" command.

FAULT_TYPES = ("capacity_loss", "cell_failure", "overheating", "motor_degradation", "gnss_degradation")
DRONE_FIELDS = (
    "id", "type", "priority", "origin", "destination", "depart_s", "cruise_speed_mps", "preferred_layer",
    "cooperative", "malicious", "spoof_offset_m", "spoof_start_s",
    "battery_wh", "soc_init_pct", "soh_pct", "payload_kg", "fault",
)
CSV_COLUMNS = (
    "id", "type", "priority", "origin", "destination", "depart_s", "cruise_speed_mps", "preferred_layer",
    "cooperative", "malicious", "spoof_dx_m", "spoof_dy_m", "spoof_start_s",
    "battery_wh", "soc_init_pct", "soh_pct", "payload_kg", "fault_type", "fault_t_s",
)
DRONES_FORMAT = "masooda-drones"


def _num(row: dict, key: str, errs: list[str], lo: float | None = None, hi: float | None = None,
         lo_open: bool = False, default: Any = None, integer: bool = False) -> Any:
    value = row.get(key, default)
    if value is None or value == "":
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not np.isfinite(value):
        errs.append(f"{key} must be a number")
        return default
    if integer and int(value) != value:
        errs.append(f"{key} must be a whole number")
        return default
    value = int(value) if integer else float(value)
    if lo is not None and (value <= lo if lo_open else value < lo):
        errs.append(f"{key} must be {'>' if lo_open else '≥'} {lo:g}")
    if hi is not None and value > hi:
        errs.append(f"{key} must be ≤ {hi:g}")
    return value


def validate_route_drones(rows: Any, vertiports: list[str], config: dict[str, Any], duration_s: float,
                          taken_ids: set[int] | None = None, depart_floor_s: float = 0.0) -> list[dict[str, Any]]:
    """Validate custom drone rows and return normalized rows.

    All rows are checked; one ``ValueError`` lists every problem as
    ``row <n> (D-<id>): <field> ...`` so the user can fix a whole file at once.
    Missing ids are assigned after ``taken_ids`` (the random fleet) in row order.
    Health inputs are validated and stored; ``simulation/drone_health.py``
    (Phase 3B) fills type defaults for the ones left empty.
    """
    if not isinstance(rows, list):
        raise ValueError("drones must be a list of objects")
    num_layers = int(config["airspace"]["num_layers"])
    emergency_layer = int(config["airspace"].get("emergency_layer", num_layers - 1))
    v_max = float(config["safety"]["maximum_velocity_meters_per_second"])
    default_offset = float(config.get("attack", {}).get("offset_magnitude_meters", 25.0))
    vp = set(vertiports)
    taken = set(taken_ids or set())
    problems: list[str] = []
    out: list[dict[str, Any]] = []
    explicit = [r.get("id") for r in rows if isinstance(r, dict) and isinstance(r.get("id"), int)
                and not isinstance(r.get("id"), bool)]
    next_id = max([*taken, *explicit, -1]) + 1
    for n, row in enumerate(rows, start=1):
        errs: list[str] = []
        if not isinstance(row, dict):
            problems.append(f"row {n}: must be an object")
            continue
        extra = set(row) - set(DRONE_FIELDS)
        if extra:
            errs.append(f"unknown field(s) {', '.join(sorted(extra))}")
        did = row.get("id")
        if did is None or did == "":
            did = next_id
            next_id += 1
        elif isinstance(did, bool) or not isinstance(did, int) or did < 0:
            errs.append("id must be a non-negative whole number")
            did = None
        elif did in taken:
            errs.append(f"id {did} is already used")
        if did is not None:
            taken.add(did)
        try:
            typ = AgentType(str(row.get("type", "DELIVERY")).strip().upper())
        except ValueError:
            errs.append("type must be EMERGENCY, EVTOL or DELIVERY")
            typ = AgentType.DELIVERY
        priority = _num(row, "priority", errs, 0, 9, default=_PRIORITY_BY_TYPE[typ], integer=True)
        origin, dest = row.get("origin"), row.get("destination")
        if origin not in vp:
            errs.append(f"origin '{origin}' is not a vertiport on this map ({', '.join(sorted(vp))})")
        if dest not in vp:
            errs.append(f"destination '{dest}' is not a vertiport on this map")
        if origin == dest and origin in vp:
            errs.append("origin and destination must differ")
        depart = _num(row, "depart_s", errs, depart_floor_s, duration_s, default=depart_floor_s)
        speed = _num(row, "cruise_speed_mps", errs, 0.0, v_max, lo_open=True)
        layer = _num(row, "preferred_layer", errs, 0, num_layers - 1, integer=True)
        if layer is not None and layer == emergency_layer and typ != AgentType.EMERGENCY:
            errs.append(f"preferred_layer {layer} is reserved for EMERGENCY drones")
        flags = {}
        for key, default in (("cooperative", True), ("malicious", False)):
            value = row.get(key, default)
            if isinstance(value, str) and value.strip().lower() in ("true", "false", "1", "0", "yes", "no", ""):
                value = value.strip().lower() in ("true", "1", "yes") if value.strip() else default
            if not isinstance(value, bool):
                errs.append(f"{key} must be true or false")
                value = default
            flags[key] = value
        offset = row.get("spoof_offset_m")
        if flags["malicious"]:
            if offset in (None, ""):
                offset = [default_offset, 0.0]
            if (not isinstance(offset, (list, tuple)) or len(offset) != 2
                    or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and np.isfinite(v) for v in offset)):
                errs.append("spoof_offset_m must be [dx, dy] in metres")
                offset = [default_offset, 0.0]
            elif float(np.hypot(*offset)) <= 0.0 or float(np.hypot(*offset)) > 500.0:
                errs.append("spoof_offset_m length must be in (0, 500] m")
            offset = [float(offset[0]), float(offset[1])]
        else:
            offset = None
        spoof_start = _num(row, "spoof_start_s", errs, 0.0, duration_s) if flags["malicious"] else None
        health = {
            "battery_wh": _num(row, "battery_wh", errs, 0.0, 100000.0, lo_open=True),
            "soc_init_pct": _num(row, "soc_init_pct", errs, 0.0, 100.0, lo_open=True),
            "soh_pct": _num(row, "soh_pct", errs, 0.0, 100.0, lo_open=True),
            "payload_kg": _num(row, "payload_kg", errs, 0.0, 1000.0),
        }
        fault = row.get("fault")
        if fault not in (None, "", {}):
            if not isinstance(fault, dict) or set(fault) - {"type", "t_s"}:
                errs.append("fault must be {type, t_s}")
                fault = None
            else:
                if fault.get("type") not in FAULT_TYPES:
                    errs.append(f"fault.type must be one of {', '.join(FAULT_TYPES)}")
                t_s = _num(fault, "t_s", errs, 0.0, duration_s, default=None)
                if t_s is None:
                    errs.append("fault.t_s (time of the fault) is required")
                fault = {"type": fault.get("type"), "t_s": t_s}
        else:
            fault = None
        if errs:
            problems.append(f"row {n} (D-{did if did is not None else '?'}): " + "; ".join(errs))
            continue
        out.append({"id": did, "type": typ.value, "priority": priority, "origin": origin, "destination": dest,
                    "depart_s": depart, "cruise_speed_mps": speed, "preferred_layer": layer,
                    "cooperative": flags["cooperative"], "malicious": flags["malicious"],
                    "spoof_offset_m": offset, "spoof_start_s": spoof_start, **health, "fault": fault})
    if problems:
        raise ValueError(f"{len(problems)} invalid drone row(s):\n" + "\n".join(problems))
    return out


def drones_to_json(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"format": DRONES_FORMAT, "version": 1, "drones": rows}


def drones_from_json(data: Any) -> list[dict[str, Any]]:
    """Accept ``{"format": "masooda-drones", "drones": [...]}`` or a bare list."""
    if isinstance(data, dict):
        if data.get("format") not in (None, DRONES_FORMAT):
            raise ValueError(f"not a drone list (format '{data.get('format')}')")
        data = data.get("drones")
    if not isinstance(data, list):
        raise ValueError("drone list JSON must be a list or {\"drones\": [...]}")
    return data


def drones_to_csv(rows: list[dict[str, Any]]) -> str:
    import csv
    import io
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_COLUMNS, lineterminator="\n")
    w.writeheader()
    for r in rows:
        off = r.get("spoof_offset_m") or [None, None]
        fault = r.get("fault") or {}
        flat = {k: r.get(k) for k in CSV_COLUMNS if k in r}
        flat.update({"spoof_dx_m": off[0], "spoof_dy_m": off[1], "fault_type": fault.get("type"),
                     "fault_t_s": fault.get("t_s")})
        w.writerow({k: ("" if flat.get(k) is None else str(flat[k]).lower() if isinstance(flat.get(k), bool)
                        else flat[k]) for k in CSV_COLUMNS})
    return buf.getvalue()


def drones_from_csv(text: str) -> list[dict[str, Any]]:
    """CSV with a header row (``CSV_COLUMNS``; unknown columns are reported per row by validation)."""
    import csv
    import io
    reader = csv.DictReader(io.StringIO(text.strip()))
    if not reader.fieldnames:
        raise ValueError("CSV is empty")
    unknown = set(reader.fieldnames) - set(CSV_COLUMNS)
    if unknown:
        raise ValueError(f"unknown CSV column(s): {', '.join(sorted(unknown))}")
    numeric = {"id", "priority", "depart_s", "cruise_speed_mps", "preferred_layer", "spoof_dx_m", "spoof_dy_m",
               "spoof_start_s", "battery_wh", "soc_init_pct", "soh_pct", "payload_kg", "fault_t_s"}
    rows: list[dict[str, Any]] = []
    for n, rec in enumerate(reader, start=2):
        row: dict[str, Any] = {}
        for k, v in rec.items():
            v = (v or "").strip()
            if v == "":
                continue
            if k in numeric:
                try:
                    num = float(v)
                except ValueError:
                    raise ValueError(f"CSV line {n}: {k} = '{v}' is not a number") from None
                row[k] = int(num) if k in ("id", "priority", "preferred_layer") and num.is_integer() else num
            else:
                row[k] = v
        if "spoof_dx_m" in row or "spoof_dy_m" in row:
            row["spoof_offset_m"] = [row.pop("spoof_dx_m", 0.0), row.pop("spoof_dy_m", 0.0)]
        if "fault_type" in row or "fault_t_s" in row:
            row["fault"] = {"type": row.pop("fault_type", None), "t_s": row.pop("fault_t_s", None)}
        rows.append(row)
    return rows
