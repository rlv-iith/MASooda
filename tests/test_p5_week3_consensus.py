"""Week 3 P5 tests for W-MSR consensus under constant-value liars."""

from __future__ import annotations

import numpy as np

from resilience.consensus import run_consensus, run_wmsr_consensus
from simulation.schema import CommunicationGraph


def _complete_graph(n: int) -> CommunicationGraph:
    return CommunicationGraph(
        adjacency={aid: [other for other in range(n) if other != aid] for aid in range(n)}
    )


def _spread(values: list[float]) -> float:
    return max(values) - min(values)


def test_wmsr_contains_honest_agents_with_one_liar():
    graph = _complete_graph(10)
    initial = {aid: float(aid) for aid in range(10)}
    liars = {9: 1000.0}
    plain = run_consensus(initial, graph, liars, steps=50)
    filtered = run_wmsr_consensus(initial, graph, liars, steps=50, f=1)

    plain_honest = [plain[-1][aid] for aid in range(9)]
    plain_mean = float(np.mean(plain_honest))
    assert min(abs(plain_mean - 0.0), abs(plain_mean - 8.0)) > 20.0

    honest = [filtered[-1][aid] for aid in range(9)]
    assert min(honest) >= 0.0
    assert max(honest) <= 8.0
    assert _spread(honest) < 1e-3


def test_wmsr_contains_honest_agents_with_two_liars():
    graph = _complete_graph(10)
    initial = {aid: float(aid) for aid in range(10)}
    liars = {8: 1000.0, 9: -1000.0}
    filtered = run_wmsr_consensus(initial, graph, liars, steps=50, f=2)

    honest = [filtered[-1][aid] for aid in range(8)]
    assert min(honest) >= 0.0
    assert max(honest) <= 7.0
    assert _spread(honest) < 1e-3


def test_wmsr_and_plain_consensus_converge_without_liars():
    graph = _complete_graph(10)
    initial = {aid: float(aid) for aid in range(10)}
    plain = run_consensus(initial, graph, liars=None, steps=50)
    filtered = run_wmsr_consensus(initial, graph, liars=None, steps=50, f=1)

    assert _spread(list(plain[-1].values())) < 1e-3
    assert _spread(list(filtered[-1].values())) < 1e-3
