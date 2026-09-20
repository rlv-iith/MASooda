"""Shared data structures used by all MASooda modules.

- This file defines the common shapes of data passed between team members.
- Using the same structures prevents one module from guessing what another module means by a field.  
- The structures are kept small in Week 1 so the team can work in parallel.
- P1 will add the remaining simulation fields as the dynamics engine is built.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

class AgentType(str, Enum):
    """The three agent categories"""

    EMERGENCY = "EMERGENCY"
    EVTOL = "EVTOL"
    DELIVERY = "DELIVERY"


@dataclass
class AgentState:
    """Store the basic information needed to describe one agent.

    - P1 owns and updates the complete agent state in the simulation.  
    - P4 uses the type, priority, corridor, and altitude fields to create global instructions.  
    - P3 reads those instructions to guide local behavior.
    - This Week 1 version contains only the fields needed to define that shared contract; movement fields will be added by P1 later.
    """

    id: int
    type: AgentType
    # Delivery is the default type, and the workflow gives it priority rank 2.
    # Emergency and eVTOL agents use ranks 0 and 1 respectively.
    priority: int = 2
    # This is the corridor currently assigned to the agent.  
    # None means that the overseer has not assigned a corridor yet.
    corridor_assignment: int | None = None
    # This is a discrete layer label, not a height in metres.  
    # Layer 0 is the default layer used until the simulation assigns another predefined layer.
    altitude_layer: int = 0


@dataclass
class GlobalStateSnapshot:
    """Give the overseer a small summary of the current simulation state.

    - P1 creates this snapshot from the live simulation and passes it to P4.
    - It contains summary information instead of full mutable ``AgentState`` objects, so P4 can make global decisions without changing agent physics.
    - In Week 1 the snapshot is used to define the interface.  
    - In Week 2 the real overseer will use values such as corridor occupancy to make choices.
    """

    # Simulation time in seconds.  All workflow timing values use seconds.
    timestamp: float
    corridor_occupancy: dict[int, int] = field(default_factory = dict)      # corridor -> agent count
    agent_ids: list[int] = field(default_factory = list)                    # list of agents
    agent_types: dict[int, AgentType] = field(default_factory = dict)       # agent_id -> agent_type
    agent_priorities: dict[int, int] = field(default_factory = dict)        # agent_id -> priority 


@dataclass
class OverseerDirective:
    """Tell local agents which corridor, priority, and layer to use.

    - P4 creates this directive from a global snapshot.  
    - P1 and P3 read it when updating the simulation and local movement.  
    - The timestamp records when it was created, which will help detect an old directive during the Week 4 overseer-link failure test.
    """

    corridor_map: dict[int, int]            # agent_id -> corridor_id
    priority_table: dict[AgentType, int]    # Agent_type -> priority
    altitude_map: dict[int, int]            # agent_id -> altitude layer
    timestamp: float                        # simulation time in seconds

    def __post_init__(self) -> None:
        # Make private copies so later changes to the input dictionaries do
        # not silently change a directive that was already issued.
        """Copy mappings so a caller cannot mutate the directive's inputs."""

        self.corridor_map = dict(self.corridor_map)
        self.priority_table = dict(self.priority_table)
        self.altitude_map = dict(self.altitude_map)


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
