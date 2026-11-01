"""Centralized configuration loader for MASooda.

All modules load parameters from configs/base_config.yaml using this loader
to ensure experimental consistency and reproducibility.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
import yaml

# Default configuration path relative to repository root
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "configs" / "base_config.yaml"

_CONFIG_CACHE: dict[str, Any] = {}


def load_config(config_path: str | Path | None = None, reload: bool = False) -> dict[str, Any]:
    """Load configuration from a YAML file.

    Parameters
    ----------
    config_path : str or Path, optional
        Path to the configuration YAML file. If None, defaults to configs/base_config.yaml.
    reload : bool, default False
        Whether to bypass the in-memory cache and re-read from disk.

    Returns
    -------
    dict[str, Any]
        Dictionary representation of configuration parameters.
    """
    path = Path(config_path) if config_path is not None else DEFAULT_CONFIG_PATH
    resolved_path = str(path.resolve())

    if not reload and resolved_path in _CONFIG_CACHE:
        return _CONFIG_CACHE[resolved_path]

    if not path.is_file():
        raise FileNotFoundError(f"Configuration file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    _CONFIG_CACHE[resolved_path] = data
    return data


def get_config() -> dict[str, Any]:
    """Get the cached base configuration."""
    return load_config()


def get_safety_limits(config: dict[str, Any] | None = None) -> tuple[float, float]:
    """Extract (max_velocity, max_acceleration) from configuration.

    Returns
    -------
    tuple[float, float]
        (maximum_velocity_meters_per_second, maximum_acceleration_meters_per_second_squared)
    """
    cfg = config or get_config()
    safety = cfg.get("safety", {})
    max_vel = float(safety.get("maximum_velocity_meters_per_second", 15.0))
    max_acc = float(safety.get("maximum_acceleration_meters_per_second_squared", 4.0))
    return max_vel, max_acc
