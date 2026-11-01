"""Unit tests for shared schema data models."""

import numpy as np
import pytest

from simulation.schema import AgentState, AgentType, CommunicationGraph


def test_agent_state_defaults() -> None:
    """AgentState instantiates with sensible defaults and correct types."""
    agent = AgentState(id=0, type=AgentType.DELIVERY)
    assert agent.id == 0
    assert agent.type == AgentType.DELIVERY
    assert agent.priority == 2
    assert agent.corridor_assignment is None
    assert agent.neighbor_set == []
    assert agent.altitude_layer == 0
    assert isinstance(agent.position, np.ndarray)
    assert agent.position.shape == (3,)
    assert isinstance(agent.velocity, np.ndarray)
    assert isinstance(agent.acceleration, np.ndarray)
    assert isinstance(agent.destination, np.ndarray)


def test_agent_state_equality() -> None:
    """AgentState implements custom equality handling numpy arrays without error."""
    a1 = AgentState(id=1, type=AgentType.EVTOL, position=[1.0, 2.0, 3.0])
    a2 = AgentState(id=1, type=AgentType.EVTOL, position=[1.0, 2.0, 3.0])
    a3 = AgentState(id=1, type=AgentType.EVTOL, position=[1.0, 2.0, 4.0])

    assert a1 == a2
    assert a1 != a3
    assert a1 != "not an agent"


def test_agent_state_to_dict_and_from_dict() -> None:
    """AgentState serializes to and deserializes from dictionary round-trip."""
    agent = AgentState(
        id=5,
        type=AgentType.EMERGENCY,
        position=np.array([12.5, 45.0, 1.0]),
        velocity=np.array([5.0, -2.0, 0.0]),
        acceleration=np.array([0.5, 0.1, 0.0]),
        destination=np.array([100.0, 50.0, 1.0]),
        priority=0,
        corridor_assignment=2,
        neighbor_set=[1, 3],
        altitude_layer=1,
    )

    d = agent.to_dict()
    assert d["id"] == 5
    assert d["type"] == "EMERGENCY"
    assert d["priority"] == 0
    assert d["neighbor_set"] == [1, 3]

    reconstructed = AgentState.from_dict(d)
    assert reconstructed == agent


def test_communication_graph() -> None:
    """CommunicationGraph stores adjacency and provides neighbor querying."""
    cg = CommunicationGraph(adjacency={0: [1, 2], 1: [0], 2: [0]})
    assert cg.neighbors(0) == [1, 2]
    assert cg.neighbors(1) == [0]
    assert cg.neighbors(99) == []

    d = cg.to_dict()
    reconstructed = CommunicationGraph.from_dict(d)
    assert reconstructed.adjacency == cg.adjacency
