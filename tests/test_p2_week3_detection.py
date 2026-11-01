"""P2 Week 3 unit tests: Conflict detection and multi-group resolution."""

from __future__ import annotations

import numpy as np

from config.load_config import get_config
from conflict_resolution.adapter import resolve_all_conflicts
from conflict_resolution.detection import detect_conflicts
from simulation.schema import AgentState, AgentType, ConflictEvent


def test_two_agents_inside_merge_zone():
    """Two agents 10 m apart inside the merge zone -> one group [a, b]."""
    a1 = AgentState(
        id=1,
        type=AgentType.EVTOL,
        position=np.array([750.0, 0.0, 0.0]),
        velocity=np.array([10.0, 0.0, 0.0]),
    )
    a2 = AgentState(
        id=2,
        type=AgentType.DELIVERY,
        position=np.array([750.0, 10.0, 0.0]),
        velocity=np.array([-10.0, 0.0, 0.0]),
    )

    groups = detect_conflicts([a1, a2])
    assert len(groups) == 1
    assert groups[0] == [1, 2]


def test_two_agents_outside_merge_zone():
    """Same 2 agents at x=100 (outside merge zone) -> no groups."""
    a1 = AgentState(
        id=1,
        type=AgentType.EVTOL,
        position=np.array([100.0, 0.0, 0.0]),
        velocity=np.array([10.0, 0.0, 0.0]),
    )
    a2 = AgentState(
        id=2,
        type=AgentType.DELIVERY,
        position=np.array([100.0, 10.0, 0.0]),
        velocity=np.array([-10.0, 0.0, 0.0]),
    )

    groups = detect_conflicts([a1, a2])
    assert groups == []


def test_seven_agents_in_merge_zone_chunked():
    """7 agents all within 15 m in the merge zone -> groups of size 5 and 2."""
    agents = [
        AgentState(
            id=i + 1,
            type=AgentType.DELIVERY,
            position=np.array([710.0 + i * 10.0, 0.0, 0.0]),
            velocity=np.array([10.0, 0.0, 0.0]),
        )
        for i in range(7)
    ]

    groups = detect_conflicts(agents)
    assert len(groups) == 2
    assert len(groups[0]) == 5
    assert len(groups[1]) == 2
    assert groups[0] == [1, 2, 3, 4, 5]
    assert groups[1] == [6, 7]


def test_resolve_all_conflicts_returns_one_event_per_group():
    """resolve_all_conflicts returns one ConflictEvent per group, or empty list if no conflicts."""
    agents = [
        AgentState(
            id=i + 1,
            type=AgentType.EMERGENCY if i == 0 else AgentType.DELIVERY,
            position=np.array([710.0 + i * 10.0, 0.0, 0.0]),
            velocity=np.array([10.0, 0.0, 0.0]),
        )
        for i in range(7)
    ]

    events = resolve_all_conflicts(agents, priorities={1: 0, 2: 2})
    assert len(events) == 2

    for event in events:
        assert isinstance(event, ConflictEvent)
        assert event.converged

    assert set(events[0].agents_involved) == {1, 2, 3, 4, 5}
    assert set(events[1].agents_involved) == {6, 7}

    for aid in [1, 2, 3, 4, 5]:
        assert aid in events[0].resolution
        assert isinstance(events[0].resolution[aid], np.ndarray)

    for aid in [6, 7]:
        assert aid in events[1].resolution
        assert isinstance(events[1].resolution[aid], np.ndarray)

    # Empty list when no conflicts exist
    outside_agents = [
        AgentState(
            id=101,
            type=AgentType.EVTOL,
            position=np.array([50.0, 0.0, 0.0]),
            velocity=np.array([10.0, 0.0, 0.0]),
        ),
        AgentState(
            id=102,
            type=AgentType.DELIVERY,
            position=np.array([50.0, 10.0, 0.0]),
            velocity=np.array([-10.0, 0.0, 0.0]),
        ),
    ]
    assert resolve_all_conflicts(outside_agents) == []
