"""P2 tests: ADMM conflict handling ignores agents on different altitude layers."""

from __future__ import annotations

import numpy as np

from conflict_resolution.adapter import resolve_conflict_event
from conflict_resolution.detection import detect_conflicts
from simulation.schema import AgentState, AgentType


def agent(aid: int, x: float, y: float, vx: float, layer: int) -> AgentState:
    return AgentState(
        id=aid,
        type=AgentType.DELIVERY,
        position=np.array([x, y, float(layer)]),
        velocity=np.array([vx, 0.0, 0.0]),
        altitude_layer=layer,
    )


def test_same_layer_is_a_conflict():
    groups = detect_conflicts([agent(1, 750.0, 0.0, 10.0, 0), agent(2, 750.0, 5.0, 10.0, 0)])
    assert groups == [[1, 2]]


def test_different_layers_are_not_a_conflict():
    groups = detect_conflicts([agent(1, 750.0, 0.0, 10.0, 0), agent(2, 750.0, 5.0, 10.0, 1)])
    assert groups == []


def test_resolve_ignores_mixed_layer_pair():
    a, b = agent(1, 750.0, 0.0, 10.0, 0), agent(2, 750.0, 2.0, 10.0, 1)
    event = resolve_conflict_event([a, b])
    assert event.converged

    # The solver's speed-ball projection is slightly inexact (~1e-2 m/s), so compare
    # against the same agents far apart (no constraint possible) instead of exactly.
    far = resolve_conflict_event([a, agent(2, 750.0, 200.0, 10.0, 0)])
    for ag in (a, b):
        assert np.allclose(event.resolution[ag.id][:2], far.resolution[ag.id][:2], atol=1e-6)
        assert np.allclose(event.resolution[ag.id][:2], ag.velocity[:2], atol=2e-2)
