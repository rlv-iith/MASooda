"""Unit tests for simulation/environment.py."""

from __future__ import annotations

import numpy as np

from simulation.environment import (
    build_corridors,
    corridor_occupancy,
    corridor_of_position,
    in_merge_zone,
)
from simulation.schema import AgentState, AgentType


def test_build_corridors_ids() -> None:
    """build_corridors returns 3 corridors with ids 0, 1, 2."""
    corridors = build_corridors()
    assert len(corridors) == 3
    assert [c.id for c in corridors] == [0, 1, 2]


def test_corridor_of_position() -> None:
    """corridor_of_position on each centerline, and outside all corridors (None)."""
    corridors = build_corridors()

    # Centerlines
    for c in corridors:
        assert corridor_of_position(c.y_center, corridors) == c.id

    # Outside all corridors
    assert corridor_of_position(-100.0, corridors) is None
    assert corridor_of_position(25.0, corridors) is None  # Between corridor 0 and corridor 1
    assert corridor_of_position(200.0, corridors) is None


def test_in_merge_zone() -> None:
    """in_merge_zone True at x=750, False at x=100."""
    assert in_merge_zone(750.0) is True
    assert in_merge_zone(100.0) is False


def test_corridor_occupancy() -> None:
    """corridor_occupancy on 3 hand-made AgentState objects."""
    corridors = build_corridors()

    # Agent 0 and Agent 1 in corridor 0 (y=0.0), Agent 2 in corridor 2 (y=100.0)
    agents = [
        AgentState(id=0, type=AgentType.EMERGENCY, position=np.array([10.0, 0.0, 0.0])),
        AgentState(id=1, type=AgentType.EVTOL, position=np.array([30.0, 2.0, 0.0])),
        AgentState(id=2, type=AgentType.DELIVERY, position=np.array([50.0, 100.0, 0.0])),
    ]

    occ = corridor_occupancy(agents, corridors)

    # Every corridor id (0, 1, 2) must appear, even with count 0
    assert occ == {0: 2, 1: 0, 2: 1}

