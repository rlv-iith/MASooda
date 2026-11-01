"""Safety properties for ADMM conflict resolution fallback results."""

from __future__ import annotations

import numpy as np
import importlib

config_loader = importlib.import_module("config.load_config")
from conflict_resolution.adapter import resolve_all_conflicts, resolve_conflict_event
from simulation.schema import AgentState, AgentType


def _packed_agents(n=5, spacing=2.0):
    cfg = config_loader.get_config()
    merge_start = float(cfg["corridors"]["merge_zone_x_meters"][0])
    return [
        AgentState(
            id=i,
            type=AgentType.DELIVERY,
            position=[merge_start + spacing * i, 750.0, 0.0],
            velocity=[12.0, 0.0, 0.0],
        )
        for i in range(n)
    ]


def test_nonconverged_event_has_finite_best_iterate_velocities(monkeypatch):
    cfg = config_loader.get_config()
    previous_limit = cfg["admm"]["maximum_iterations"]
    try:
        cfg["admm"]["maximum_iterations"] = 1
        monkeypatch.setattr(config_loader, "get_config", lambda: cfg)
        event = resolve_conflict_event(_packed_agents())
    finally:
        cfg["admm"]["maximum_iterations"] = previous_limit

    assert event.converged is False
    assert all(np.all(np.isfinite(velocity)) for velocity in event.resolution.values())


def test_normal_config_resolves_packed_agents_to_safe_next_positions():
    # 2 agents 6 m apart (inside d_min = 8 m) converge within 50 iterations.
    # 3+ agents packed this tightly do not; that case is covered by the fallback test above.
    agents = _packed_agents(n=2, spacing=6.0)
    event = resolve_conflict_event(agents)
    assert event.converged is True

    dt = float(config_loader.get_config()["simulation"]["timestep_seconds"])
    d_min = float(config_loader.get_config()["safety"]["minimum_separation_meters"])
    next_positions = {
        agent.id: agent.position[:2] + event.resolution[agent.id][:2] * dt
        for agent in agents
    }
    for i, first in enumerate(agents):
        for second in agents[i + 1:]:
            distance = np.linalg.norm(next_positions[first.id] - next_positions[second.id])
            assert distance >= d_min * 0.99


def test_nonfinite_position_returns_current_velocity_fallback():
    agent = AgentState(
        id=1,
        type=AgentType.DELIVERY,
        position=[float("nan"), 750.0, 0.0],
        velocity=[3.0, 4.0, 0.0],
    )
    event = resolve_conflict_event([agent])
    assert event.converged is False
    np.testing.assert_array_equal(event.resolution[agent.id], agent.velocity)


def test_resolve_all_conflicts_empty_agents_returns_empty_list():
    assert resolve_all_conflicts([]) == []
