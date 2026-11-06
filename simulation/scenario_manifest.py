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
        if key not in base:
            raise ValueError(f"Unknown configuration key: {path}.{key}")
        current = base[key]
        current_path = f"{path}.{key}"
        if isinstance(current, dict):
            if not isinstance(value, dict):
                raise ValueError(f"{current_path} must be an object")
            merged[key] = _merge_config(current, value, current_path)
        elif isinstance(current, bool):
            if not isinstance(value, bool):
                raise ValueError(f"{current_path} must be a boolean")
            merged[key] = value
        elif isinstance(current, (int, float)) and not isinstance(current, bool):
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not np.isfinite(value)
                or (isinstance(current, int) and not isinstance(value, int))
            ):
                raise ValueError(f"{current_path} must be numeric")
            merged[key] = value
        elif isinstance(current, list):
            if not isinstance(value, list):
                raise ValueError(f"{current_path} must be a list")
            merged[key] = deepcopy(value)
        elif not isinstance(value, type(current)):
            raise ValueError(f"{current_path} must be a {type(current).__name__}")
        else:
            merged[key] = value
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
