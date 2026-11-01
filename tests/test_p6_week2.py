"""Unit tests for P6 Week 2 deliverables.

Verifies:
- window_from_result on a simulation run of 5 agents for 2 s produces shape (T, 5, 2).
- stl_monitor on the extracted window returns status "OK" and a finite robustness value.
- stl_monitor evaluation is deterministic (running twice gives identical results).
- load_spec_from_config returns d_min 8.0, dt 0.1, min_window_steps 2.
"""

from __future__ import annotations

import numpy as np

from simulation.engine import run_simulation
from simulation.scenario import make_initial_agents
from verification.from_engine import window_from_result
from verification.stl_monitor import load_spec_from_config, stl_monitor


def test_window_from_result_shape() -> None:
    """window_from_result on a run of 5 agents for 2 s has shape (T, 5, 2)."""
    agents = make_initial_agents(5, seed=42)
    duration_s = 2.0
    dt = 0.1
    expected_t = int(round(duration_s / dt)) + 1

    result = run_simulation(agents, duration_s=duration_s)
    window = window_from_result(result)

    assert window.shape == (expected_t, 5, 2)
    assert np.all(np.isfinite(window))


def test_stl_monitor_on_engine_window() -> None:
    """stl_monitor on that window returns status 'OK' and a finite value."""
    agents = make_initial_agents(5, seed=42)
    result = run_simulation(agents, duration_s=2.0)
    window = window_from_result(result)
    spec = load_spec_from_config()

    res = stl_monitor(window, spec)

    assert res.status == "OK"
    assert np.isfinite(res.value)
    assert isinstance(res.violation, bool)
    assert res.worst_step is not None
    assert res.worst_pair is not None


def test_stl_monitor_determinism() -> None:
    """Running stl_monitor twice gives the same value (deterministic)."""
    agents = make_initial_agents(5, seed=42)
    result = run_simulation(agents, duration_s=2.0)
    window = window_from_result(result)
    spec = load_spec_from_config()

    res1 = stl_monitor(window, spec)
    res2 = stl_monitor(window, spec)

    assert res1.value == res2.value
    assert res1.violation == res2.violation
    assert res1.status == res2.status
    assert res1.worst_step == res2.worst_step
    assert res1.worst_pair == res2.worst_pair


def test_load_spec_from_config() -> None:
    """load_spec_from_config gives d_min 8.0, dt 0.1, min_window_steps 2."""
    spec = load_spec_from_config()

    assert spec.d_min == 8.0
    assert spec.dt == 0.1
    assert spec.min_window_steps == 2

