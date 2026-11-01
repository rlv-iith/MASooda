"""Mock data for MASooda Week 1 parallel development.

Provides:
- Hand-authored list of 10 mock AgentState objects (covering EMERGENCY, EVTOL, DELIVERY,
  different corridors, and discrete altitude layers).
- Mock CommunicationGraph with fixed adjacency structure.
- JSON serialization/deserialization utilities as required by Table 5.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence
import numpy as np

from .schema import AgentState, AgentType, CommunicationGraph

DEFAULT_JSON_PATH = Path(__file__).resolve().parent.parent / "configs" / "mock_agents.json"

# Hand-authored list of 10 mock agents representing heterogeneous urban air traffic
MOCK_AGENTS: list[AgentState] = [
    AgentState(
        id=0,
        type=AgentType.EMERGENCY,
        position=np.array([10.0, 0.0, 1.0], dtype=float),
        velocity=np.array([12.0, 0.0, 0.0], dtype=float),
        acceleration=np.array([0.0, 0.0, 0.0], dtype=float),
        destination=np.array([180.0, 0.0, 1.0], dtype=float),
        priority=0,
        corridor_assignment=0,
        neighbor_set=[1, 2],
        altitude_layer=1,
    ),
    AgentState(
        id=1,
        type=AgentType.EVTOL,
        position=np.array([25.0, 2.0, 1.0], dtype=float),
        velocity=np.array([10.0, 0.5, 0.0], dtype=float),
        acceleration=np.array([0.0, 0.0, 0.0], dtype=float),
        destination=np.array([170.0, 0.0, 1.0], dtype=float),
        priority=1,
        corridor_assignment=0,
        neighbor_set=[0, 2],
        altitude_layer=1,
    ),
    AgentState(
        id=2,
        type=AgentType.DELIVERY,
        position=np.array([40.0, -1.0, 1.0], dtype=float),
        velocity=np.array([8.0, 0.0, 0.0], dtype=float),
        acceleration=np.array([0.0, 0.0, 0.0], dtype=float),
        destination=np.array([160.0, 0.0, 1.0], dtype=float),
        priority=2,
        corridor_assignment=0,
        neighbor_set=[0, 1, 3],
        altitude_layer=1,
    ),
    AgentState(
        id=3,
        type=AgentType.DELIVERY,
        position=np.array([15.0, 50.0, 0.0], dtype=float),
        velocity=np.array([7.0, 0.0, 0.0], dtype=float),
        acceleration=np.array([0.0, 0.0, 0.0], dtype=float),
        destination=np.array([190.0, 50.0, 0.0], dtype=float),
        priority=2,
        corridor_assignment=1,
        neighbor_set=[2, 4],
        altitude_layer=0,
    ),
    AgentState(
        id=4,
        type=AgentType.EVTOL,
        position=np.array([35.0, 48.0, 0.0], dtype=float),
        velocity=np.array([9.0, 0.0, 0.0], dtype=float),
        acceleration=np.array([0.0, 0.0, 0.0], dtype=float),
        destination=np.array([180.0, 50.0, 0.0], dtype=float),
        priority=1,
        corridor_assignment=1,
        neighbor_set=[3, 5],
        altitude_layer=0,
    ),
    AgentState(
        id=5,
        type=AgentType.DELIVERY,
        position=np.array([55.0, 52.0, 0.0], dtype=float),
        velocity=np.array([8.5, 0.0, 0.0], dtype=float),
        acceleration=np.array([0.0, 0.0, 0.0], dtype=float),
        destination=np.array([175.0, 50.0, 0.0], dtype=float),
        priority=2,
        corridor_assignment=1,
        neighbor_set=[4],
        altitude_layer=0,
    ),
    AgentState(
        id=6,
        type=AgentType.EMERGENCY,
        position=np.array([12.0, 100.0, 2.0], dtype=float),
        velocity=np.array([14.0, 0.0, 0.0], dtype=float),
        acceleration=np.array([0.5, 0.0, 0.0], dtype=float),
        destination=np.array([195.0, 100.0, 2.0], dtype=float),
        priority=0,
        corridor_assignment=2,
        neighbor_set=[7, 8],
        altitude_layer=2,
    ),
    AgentState(
        id=7,
        type=AgentType.EVTOL,
        position=np.array([30.0, 98.0, 2.0], dtype=float),
        velocity=np.array([11.0, 0.0, 0.0], dtype=float),
        acceleration=np.array([0.0, 0.0, 0.0], dtype=float),
        destination=np.array([185.0, 100.0, 2.0], dtype=float),
        priority=1,
        corridor_assignment=2,
        neighbor_set=[6, 8],
        altitude_layer=2,
    ),
    AgentState(
        id=8,
        type=AgentType.DELIVERY,
        position=np.array([50.0, 102.0, 2.0], dtype=float),
        velocity=np.array([7.5, 0.0, 0.0], dtype=float),
        acceleration=np.array([0.0, 0.0, 0.0], dtype=float),
        destination=np.array([170.0, 100.0, 2.0], dtype=float),
        priority=2,
        corridor_assignment=2,
        neighbor_set=[6, 7, 9],
        altitude_layer=2,
    ),
    AgentState(
        id=9,
        type=AgentType.DELIVERY,
        position=np.array([70.0, 100.0, 2.0], dtype=float),
        velocity=np.array([8.0, 0.0, 0.0], dtype=float),
        acceleration=np.array([0.0, 0.0, 0.0], dtype=float),
        destination=np.array([160.0, 100.0, 2.0], dtype=float),
        priority=2,
        corridor_assignment=2,
        neighbor_set=[8],
        altitude_layer=2,
    ),
]

# Fixed mock communication graph matching neighbor sets
MOCK_COMM_GRAPH = CommunicationGraph(
    adjacency={
        0: [1, 2],
        1: [0, 2],
        2: [0, 1, 3],
        3: [2, 4],
        4: [3, 5],
        5: [4],
        6: [7, 8],
        7: [6, 8],
        8: [6, 7, 9],
        9: [8],
    }
)


def get_mock_agent_states() -> list[AgentState]:
    """Return a copy of the 10 hand-authored mock AgentState objects."""
    return [
        AgentState(
            id=a.id,
            type=a.type,
            position=a.position.copy(),
            velocity=a.velocity.copy(),
            acceleration=a.acceleration.copy(),
            destination=a.destination.copy(),
            priority=a.priority,
            corridor_assignment=a.corridor_assignment,
            neighbor_set=list(a.neighbor_set),
            altitude_layer=a.altitude_layer,
        )
        for a in MOCK_AGENTS
    ]


def get_mock_comm_graph() -> CommunicationGraph:
    """Return a copy of the fixed mock CommunicationGraph."""
    return CommunicationGraph(
        adjacency={k: list(v) for k, v in MOCK_COMM_GRAPH.adjacency.items()}
    )


def save_mock_agents_json(file_path: str | Path | None = None) -> Path:
    """Save the mock agents list to a JSON file."""
    path = Path(file_path) if file_path is not None else DEFAULT_JSON_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    data = [agent.to_dict() for agent in MOCK_AGENTS]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return path


def load_mock_agents_json(file_path: str | Path | None = None) -> list[AgentState]:
    """Load mock AgentState objects from JSON file."""
    path = Path(file_path) if file_path is not None else DEFAULT_JSON_PATH
    if not path.is_file():
        # Fall back to regenerating the JSON file
        save_mock_agents_json(path)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [AgentState.from_dict(item) for item in data]
