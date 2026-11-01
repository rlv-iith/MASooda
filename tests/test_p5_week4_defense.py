"""Tests for trusted-range and W-MSR neighbour-report defence."""

from __future__ import annotations

import numpy as np

from resilience.defense import defend_neighbor_reports
from simulation.schema import AgentState, AgentType


def _agent(agent_id, position):
    return AgentState(id=agent_id, type=AgentType.DELIVERY, position=position)


def test_honest_reports_are_kept():
    own = _agent(0, [100.0, 100.0, 5.0])
    true_neighbors = [_agent(1, [110.0, 100.0, 0.0]), _agent(2, [100.0, 112.0, 0.0])]
    result = defend_neighbor_reports(own, true_neighbors, true_neighbors)
    assert result.dropped_ids == []
    assert result.kept == true_neighbors


def test_large_reported_displacement_is_flagged_and_corrected_to_sensed_range():
    own = _agent(0, [100.0, 100.0, 0.0])
    true_neighbors = [_agent(1, [110.0, 100.0, 0.0]), _agent(2, [100.0, 112.0, 0.0])]
    reports = [_agent(1, [135.0, 100.0, 0.0]), true_neighbors[1]]
    result = defend_neighbor_reports(own, reports, true_neighbors)
    assert result.dropped_ids == [1]
    # The flagged neighbour stays visible, placed at the trusted sensed range (10 m).
    assert [neighbor.id for neighbor in result.kept] == [1, 2]
    corrected = result.kept[0]
    assert np.isclose(np.linalg.norm(corrected.position[:2] - own.position[:2]), 10.0)
    np.testing.assert_allclose(corrected.position[:2], [110.0, 100.0])


def test_small_falsification_within_tolerance_is_kept():
    own = _agent(0, [100.0, 100.0, 0.0])
    true_neighbor = _agent(1, [110.0, 100.0, 0.0])
    report = _agent(1, [111.0, 100.0, 0.0])
    result = defend_neighbor_reports(own, [report], [true_neighbor])
    assert result.dropped_ids == []
    assert result.kept == [report]


def test_empty_reports_return_own_position_copy():
    own = _agent(0, [100.0, 100.0, 5.0])
    result = defend_neighbor_reports(own, [], [])
    assert result.kept == []
    assert result.dropped_ids == []
    np.testing.assert_array_equal(result.wmsr_estimate, own.position)
    assert result.wmsr_estimate is not own.position


def test_inputs_are_not_mutated():
    own = _agent(0, [100.0, 100.0, 5.0])
    true_neighbors = [_agent(1, [110.0, 100.0, 0.0]), _agent(2, [100.0, 112.0, 0.0])]
    reports = [_agent(1, [135.0, 100.0, 0.0]), true_neighbors[1]]
    original = [own, *true_neighbors, *reports]
    before = [agent.position.copy() for agent in original]

    defend_neighbor_reports(own, reports, true_neighbors)

    for agent, position in zip(original, before):
        np.testing.assert_array_equal(agent.position, position)


def test_wmsr_estimate_stays_within_honest_x_range_with_one_liar():
    own = _agent(0, [100.0, 100.0, 7.0])
    honest = [_agent(i, [95.0 + i * 2.0, 99.0 + i, 0.0]) for i in range(1, 6)]
    liar = _agent(6, [500.0, 100.0, 0.0])
    reports = [*honest, liar]
    result = defend_neighbor_reports(own, reports, reports, f=1)
    honest_x = [agent.position[0] for agent in honest]
    assert min(honest_x) <= result.wmsr_estimate[0] <= max(honest_x)
    assert result.wmsr_estimate[2] == own.position[2]
