"""Unit tests for mock data and JSON compatibility."""

from simulation.mock_data import (
    MOCK_AGENTS,
    get_mock_agent_states,
    get_mock_comm_graph,
    load_mock_agents_json,
    save_mock_agents_json,
)
from simulation.schema import AgentType


def test_mock_agents_count_and_types() -> None:
    """Mock agent list has 10 agents with all 3 heterogeneous types."""
    agents = get_mock_agent_states()
    assert len(agents) == 10

    types = {a.type for a in agents}
    assert AgentType.EMERGENCY in types
    assert AgentType.EVTOL in types
    assert AgentType.DELIVERY in types

    layers = {a.altitude_layer for a in agents}
    assert {0, 1, 2}.issubset(layers)


def test_mock_comm_graph() -> None:
    """Mock communication graph contains expected adjacency."""
    graph = get_mock_comm_graph()
    assert 0 in graph.adjacency
    assert 1 in graph.neighbors(0)


def test_mock_json_roundtrip(tmp_path) -> None:
    """Saving and reloading mock agents JSON preserves data."""
    test_file = tmp_path / "agents.json"
    save_mock_agents_json(test_file)
    loaded = load_mock_agents_json(test_file)
    assert len(loaded) == len(MOCK_AGENTS)
    for orig, loaded_agent in zip(MOCK_AGENTS, loaded):
        assert orig == loaded_agent
