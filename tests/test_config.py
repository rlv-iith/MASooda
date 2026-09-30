"""Unit tests for configuration loading."""

from config.load_config import get_config, get_safety_limits, load_config


def test_load_base_config() -> None:
    """Config loads valid parameters matching Table 4."""
    cfg = load_config()
    assert "simulation" in cfg
    assert "safety" in cfg
    assert "corridors" in cfg

    sim = cfg["simulation"]
    assert sim["num_agents"] == 60
    assert sim["timestep_seconds"] == 0.1
    assert sim["random_seed"] == 42

    corridors = cfg["corridors"]
    assert corridors["count"] == 3
    assert corridors["width_meters"] == 20.0
    assert corridors["capacity"] == 15


def test_get_safety_limits() -> None:
    """get_safety_limits returns maximum velocity and acceleration."""
    max_vel, max_acc = get_safety_limits()
    assert max_vel == 15.0
    assert max_acc == 4.0
