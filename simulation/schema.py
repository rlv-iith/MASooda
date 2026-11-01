"""Shared data structures used by all MASooda modules.

- This file defines the common shapes of data passed between team members.
- Using the same structures prevents one module from guessing what another module means by a field.  
- The structures are kept small in Week 1 so the team can work in parallel.
- P1 owns and maintains the core AgentState and CommunicationGraph definitions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Tuple
import numpy as np


class AgentType(str, Enum):
    """The three agent categories."""

    EMERGENCY = "EMERGENCY"
    EVTOL = "EVTOL"
    DELIVERY = "DELIVERY"


@dataclass
class AgentState:
    """Store the complete information needed to describe one agent.

    - P1 owns and updates the complete agent state in the simulation.  
    - P4 uses type, priority, corridor, and altitude fields to create global instructions.  
    - P3 reads those instructions to guide local behavior.
    - Motion is governed by a 2.5D double-integrator model: continuous horizontal
      motion (x, y) and discrete altitude layers (z_l in Z).
    """

    id: int
    type: AgentType
    # Kinematic fields in 2.5D (x, y continuous, z discrete altitude layer)
    position: np.ndarray = field(default_factory=lambda: np.zeros(3, dtype=float))
    velocity: np.ndarray = field(default_factory=lambda: np.zeros(3, dtype=float))
    acceleration: np.ndarray = field(default_factory=lambda: np.zeros(3, dtype=float))
    destination: np.ndarray = field(default_factory=lambda: np.zeros(3, dtype=float))

    # Priority ranking (0: EMERGENCY, 1: EVTOL, 2: DELIVERY)
    priority: int = 2

    # Corridor currently assigned to the agent (None if unassigned)
    corridor_assignment: int | None = None

    # List of neighbor agent IDs currently in communication range
    neighbor_set: list[int] = field(default_factory=list)

    # Discrete airspace layer index (z_l in Z)
    altitude_layer: int = 0

    def __post_init__(self) -> None:
        self.position = np.asarray(self.position, dtype=float)
        self.velocity = np.asarray(self.velocity, dtype=float)
        self.acceleration = np.asarray(self.acceleration, dtype=float)
        self.destination = np.asarray(self.destination, dtype=float)
        self.neighbor_set = list(self.neighbor_set)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, AgentState):
            return False
        return (
            self.id == other.id
            and self.type == other.type
            and np.array_equal(self.position, other.position)
            and np.array_equal(self.velocity, other.velocity)
            and np.array_equal(self.acceleration, other.acceleration)
            and np.array_equal(self.destination, other.destination)
            and self.priority == other.priority
            and self.corridor_assignment == other.corridor_assignment
            and self.neighbor_set == other.neighbor_set
            and self.altitude_layer == other.altitude_layer
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize AgentState to a JSON-compatible dictionary."""
        return {
            "id": self.id,
            "type": self.type.value if isinstance(self.type, AgentType) else str(self.type),
            "position": self.position.tolist(),
            "velocity": self.velocity.tolist(),
            "acceleration": self.acceleration.tolist(),
            "destination": self.destination.tolist(),
            "priority": self.priority,
            "corridor_assignment": self.corridor_assignment,
            "neighbor_set": list(self.neighbor_set),
            "altitude_layer": self.altitude_layer,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentState:
        """Construct AgentState from a dictionary."""
        return cls(
            id=int(data["id"]),
            type=AgentType(data["type"]),
            position=np.array(data.get("position", [0.0, 0.0, 0.0]), dtype=float),
            velocity=np.array(data.get("velocity", [0.0, 0.0, 0.0]), dtype=float),
            acceleration=np.array(data.get("acceleration", [0.0, 0.0, 0.0]), dtype=float),
            destination=np.array(data.get("destination", [0.0, 0.0, 0.0]), dtype=float),
            priority=int(data.get("priority", 2)),
            corridor_assignment=data.get("corridor_assignment"),
            neighbor_set=list(data.get("neighbor_set", [])),
            altitude_layer=int(data.get("altitude_layer", 0)),
        )


@dataclass
class CommunicationGraph:
    """Store the adjacency structure of the agent communication network.

    - P1 builds and maintains this graph.
    - P3 reads it for local swarm interactions (boids).
    - P5 reads it for resilient consensus filtering (W-MSR).
    - P6 reads it for network metrics.
    """

    adjacency: dict[int, list[int]] = field(default_factory=dict)

    def neighbors(self, agent_id: int) -> list[int]:
        """Return the list of neighbor IDs for an agent."""
        return self.adjacency.get(agent_id, [])

    def to_dict(self) -> dict[str, Any]:
        """Serialize graph adjacency to dictionary."""
        return {"adjacency": {str(k): list(v) for k, v in self.adjacency.items()}}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CommunicationGraph:
        """Construct CommunicationGraph from dictionary."""
        adj = {int(k): [int(nid) for nid in v] for k, v in data.get("adjacency", {}).items()}
        return cls(adjacency=adj)


@dataclass
class GlobalStateSnapshot:
    """Give the overseer a small summary of the current simulation state.

    - P1 creates this snapshot from the live simulation and passes it to P4.
    - It contains summary information instead of full mutable ``AgentState`` objects, so P4 can make global decisions without changing agent physics.
    - In Week 1 the snapshot is used to define the interface.  
    - In Week 2 the real overseer will use values such as corridor occupancy to make choices.
    """

    # Simulation time in seconds. All workflow timing values use seconds.
    timestamp: float
    corridor_occupancy: dict[int, int] = field(default_factory=dict)  # corridor -> agent count
    agent_ids: list[int] = field(default_factory=list)  # list of agents
    agent_types: dict[int, AgentType] = field(default_factory=dict)  # agent_id -> agent_type
    agent_priorities: dict[int, int] = field(default_factory=dict)  # agent_id -> priority


@dataclass
class OverseerDirective:
    """Tell local agents which corridor, priority, and layer to use.

    - P4 creates this directive from a global snapshot.  
    - P1 and P3 read it when updating the simulation and local movement.  
    - The timestamp records when it was created, which will help detect an old directive during the Week 4 overseer-link failure test.
    """

    corridor_map: dict[int, int]  # agent_id -> corridor_id
    priority_table: dict[AgentType, int]  # Agent_type -> priority
    altitude_map: dict[int, int]  # agent_id -> altitude layer
    timestamp: float  # simulation time in seconds

    def __post_init__(self) -> None:
        """Copy mappings so a caller cannot mutate the directive's inputs."""
        self.corridor_map = dict(self.corridor_map)
        self.priority_table = dict(self.priority_table)
        self.altitude_map = dict(self.altitude_map)


@dataclass
class AttackState:
    """Describe which agents are malicious and what false positions they broadcast.

    - P5 creates this each tick from the true agent states and the attack configuration.
    - P1 overlays ``falsified`` on the true states to build the reported neighbor states.
    - STL monitoring and metrics keep reading the true states.
    """

    malicious: list[int] = field(default_factory=list)
    falsified: dict[int, np.ndarray] = field(default_factory=dict)  # sender id -> false position


@dataclass
class ConflictEvent:
    """Record one conflict resolved by the distributed optimization layer.

    - P2 creates it when agents negotiate a separation conflict.
    - ``resolution`` maps each involved agent id to its resolved velocity.
    """

    agents_involved: list[int]
    resolution: dict[int, np.ndarray]
    converged: bool


@dataclass
class SimulationMetrics:
    """Collect named evaluation metrics (for example min separation or STL robustness)."""

    metrics: dict[str, float] = field(default_factory=dict)


# Status codes reported by the STL monitor in STLRobustness.status.
OK = "OK"
INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
INVALID_DATA = "INVALID_DATA"
NOT_ENOUGH_AGENTS = "NOT_ENOUGH_AGENTS"


@dataclass(frozen=True)
class STLSpec:
    """Parameters of the minimum-separation STL specification.

    - P6 reads these values from configs/base_config.yaml via load_spec_from_config.
    - ``min_window_steps`` is the number of samples required before a verdict is given.
    """

    name: str = "min_separation"
    d_min: float = 8.0  # m
    min_window_steps: int = 2
    dt: float = 0.1  # s


@dataclass
class STLRobustness:
    """Signed robustness result of an STL check (positive: satisfied, negative: violated).

    - ``value`` is the robustness margin in metres and ``violation`` is True when it is negative.
    - The remaining fields are diagnostics; ``status`` is one of the status codes above.
    """

    value: float
    violation: bool
    status: str = OK
    worst_step: Optional[int] = None
    worst_pair: Optional[Tuple[int, int]] = None


def validate_snapshot(snapshot: GlobalStateSnapshot) -> None:
    """Check that a snapshot contains safe basic values before use.

    - The check is needed because the overseer must not create a directive from impossible values such as negative time or negative occupancy.  
    - It is a separate function so P1 can later choose how strict the larger simulation state should be without changing the overseer interface.
    """
    if snapshot.timestamp < 0:
        raise ValueError("snapshot timestamp must be non-negative")
    if any(count < 0 for count in snapshot.corridor_occupancy.values()):
        raise ValueError("corridor occupancy counts must be non-negative")
    if any(agent_id < 0 for agent_id in snapshot.agent_ids):
        raise ValueError("agent IDs must be non-negative")
