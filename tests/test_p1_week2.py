"""Unit and integration tests for P1 Week 2 deliverables.

Verifies:
- Radius communication graph on hand-placed and isolated agents.
- Symmetry of the k-nearest-neighbor (KNN) communication graph.
- make_initial_agents produces 60 agents with >= 8m pairwise separation and determinism.
- run_simulation produces non-NaN trajectories of shape (T, 60, 3) satisfying speed limits.
- interfaces.py build_comm_graph dispatching logic.
"""

from __future__ import annotations

import numpy as np

from simulation.comm_graph import build_knn_graph, build_radius_graph
from simulation.engine import run_simulation
from simulation.interfaces import build_comm_graph
from simulation.scenario import make_initial_agents
from simulation.schema import AgentState, AgentType


def test_radius_graph_expected_neighbours() -> None:
    """Radius graph on 3 hand-placed agents gives the expected neighbours."""
    a0 = AgentState(id=0, type=AgentType.EMERGENCY, position=np.array([0.0, 0.0, 0.0]))
    a1 = AgentState(id=1, type=AgentType.EVTOL, position=np.array([5.0, 0.0, 0.0]))
    a2 = AgentState(id=2, type=AgentType.DELIVERY, position=np.array([15.0, 0.0, 0.0]))

    graph = build_radius_graph([a0, a1, a2], radius=6.0)

    assert graph.neighbors(0) == [1]
    assert graph.neighbors(1) == [0]
    assert graph.neighbors(2) == []
    assert set(graph.adjacency.keys()) == {0, 1, 2}


def test_radius_graph_isolated_agent() -> None:
    """An agent far away has an empty neighbour list."""
    a0 = AgentState(id=0, type=AgentType.EMERGENCY, position=np.array([0.0, 0.0, 0.0]))
    a1 = AgentState(id=1, type=AgentType.EVTOL, position=np.array([5.0, 0.0, 0.0]))
    a_far = AgentState(id=99, type=AgentType.DELIVERY, position=np.array([1000.0, 1000.0, 0.0]))

    graph = build_radius_graph([a0, a1, a_far], radius=10.0)

    assert graph.neighbors(99) == []
    assert 99 in graph.adjacency


def test_knn_graph_is_symmetric() -> None:
    """KNN graph is symmetric (if i links to j then j links to i)."""
    rng = np.random.default_rng(123)
    agents = [
        AgentState(
            id=i,
            type=AgentType.DELIVERY,
            position=np.array([float(rng.uniform(0, 50)), float(rng.uniform(0, 50)), 0.0]),
        )
        for i in range(8)
    ]

    graph = build_knn_graph(agents, k=2)

    assert set(graph.adjacency.keys()) == {a.id for a in agents}
    for aid, nbrs in graph.adjacency.items():
        for nid in nbrs:
            assert aid in graph.neighbors(nid), f"Edge {aid}->{nid} is not symmetric in KNN graph"


def test_make_initial_agents() -> None:
    """make_initial_agents returns 60 agents, all pairs at least 8 m apart, and deterministic."""
    agents1 = make_initial_agents(60, seed=42)
    assert len(agents1) == 60

    # Pairwise separation check
    for i in range(len(agents1)):
        for j in range(i + 1, len(agents1)):
            dist_xy = float(
                np.hypot(
                    agents1[i].position[0] - agents1[j].position[0],
                    agents1[i].position[1] - agents1[j].position[1],
                )
            )
            assert dist_xy >= 8.0, f"Pair ({i}, {j}) violates minimum separation: {dist_xy:.3f} m"

    # Determinism check: same seed gives identical agents
    agents2 = make_initial_agents(60, seed=42)
    assert len(agents2) == 60
    for a1, a2 in zip(agents1, agents2):
        assert a1.id == a2.id
        assert a1.type == a2.type
        assert a1.priority == a2.priority
        assert a1.corridor_assignment == a2.corridor_assignment
        assert np.array_equal(a1.position, a2.position)
        assert np.array_equal(a1.destination, a2.destination)


def test_run_simulation() -> None:
    """run_simulation gives positions with shape (T, 60, 3), no NaN, all speeds <= 15."""
    agents = make_initial_agents(60, seed=42)
    duration_s = 2.0
    dt = 0.1
    expected_t = int(round(duration_s / dt)) + 1

    result = run_simulation(agents, duration_s=duration_s)

    assert result.positions.shape == (expected_t, 60, 3)
    assert np.all(np.isfinite(result.positions)), "Simulation produced NaN or Inf positions"

    # Speed limit check
    speeds = np.linalg.norm(np.diff(result.positions[:, :, :2], axis=0), axis=-1) / dt
    max_speed = float(np.max(speeds))
    assert max_speed <= 15.0 + 1e-6, f"Speed {max_speed:.2f} m/s exceeded max limit 15.0 m/s"


def test_build_comm_graph_interface_dispatch() -> None:
    """Verify build_comm_graph in interfaces.py properly dispatches float, int, and None."""
    a0 = AgentState(id=0, type=AgentType.EMERGENCY, position=np.array([0.0, 0.0, 0.0]))
    a1 = AgentState(id=1, type=AgentType.EVTOL, position=np.array([10.0, 0.0, 0.0]))

    # Float radius
    g_radius = build_comm_graph([a0, a1], radius_or_k=15.0)
    assert g_radius.neighbors(0) == [1]

    # Int k (KNN)
    g_knn = build_comm_graph([a0, a1], radius_or_k=1)
    assert g_knn.neighbors(0) == [1]

    # None -> uses config mode (default radius 40.0)
    g_default = build_comm_graph([a0, a1], radius_or_k=None)
    assert g_default.neighbors(0) == [1]

    # Empty agent list
    g_empty = build_comm_graph([])
    assert g_empty.adjacency == {}

