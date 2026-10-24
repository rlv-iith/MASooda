"""Rules used by the global overseer.

- The overseer looks at a summary of the whole airspace and sends one clear directive to the local agents.  
- This Week 1 file provides the fixed mock that the other modules need while they are being developed.  
- In later weeks P4 will replace it with occupancy-based allocation (Week 2), priority-aware and capacity-aware allocation (Week 3), 
and cached-directive handling during link failure (Week 4).
"""

from __future__ import annotations

from .schema import (
    AgentType,
    GlobalStateSnapshot,
    OverseerDirective,
    validate_snapshot,
)


# Agents 0 and 1 share corridor 1, while agent 2 uses corridor 2. 
# It is not a traffic decision yet.  
# The small fixed example gives P3 a predictable directive to test with and shows that more than one corridor can be represented.
WEEK1_CORRIDOR_MAP: dict[int, int] = {0: 1, 1: 1, 2: 2}
WEEK1_PRIORITY_TABLE: dict[AgentType, int] = {
    AgentType.EMERGENCY: 0,
    AgentType.EVTOL: 1,
    AgentType.DELIVERY: 2,
}

# Week 1 also assigns the mock altitude layers so the directive is complete.
# The workflow does not define physical heights or a layer count, so these are
# labels: agents 0 and 1 use the default layer 0, while agent 2 uses layer 1.
# Giving the second corridor a different label makes the mock demonstrate how separate traffic layers can be represented.  
# P1 will later map these labels to the project's configured airspace layers.
WEEK1_ALTITUDE_MAP: dict[int, int] = {0: 0, 1: 0, 2: 1}

# Default corridor indices based on base configuration (3 corridors: 0, 1, 2)
DEFAULT_CORRIDOR_IDS: list[int] = [0, 1, 2]

# Standard priority ordering: Emergency (0) > eVTOL (1) > Delivery (2)
STANDARD_PRIORITY_TABLE: dict[AgentType, int] = {
    AgentType.EMERGENCY: 0,
    AgentType.EVTOL: 1,
    AgentType.DELIVERY: 2,
}


class GlobalOverseer:
    """Overseer that computes global corridor assignments for agents.

    Week 2 (Section 10.4):
    - Accepts coarse information (corridor occupancy and agent IDs).
    - Implements least-loaded and round-robin corridor allocation policies.
    - Emits a valid OverseerDirective.
    - Remains independent of P1's main simulation loop until Week 3.
    """

    def __init__(
        self,
        corridors: list[int] | None = None,
        policy: str = "least_loaded",
    ) -> None:
        self.corridors = list(corridors) if corridors is not None else list(DEFAULT_CORRIDOR_IDS)
        self.policy = policy

    def update(
        self,
        global_state_snapshot: GlobalStateSnapshot,
        policy: str | None = None,
    ) -> OverseerDirective:
        """Create a non-trivial OverseerDirective from a coarse global snapshot.

        Validates snapshot preconditions, then assigns each agent to a corridor
        using the selected policy (least-loaded by default, or round-robin).
        """
        validate_snapshot(global_state_snapshot)

        active_policy = policy or self.policy

        # Determine corridors to use: if snapshot reports occupancy for specific corridors,
        # use those corridors, otherwise use configured default corridors.
        if global_state_snapshot.corridor_occupancy:
            available_corridors = sorted(list(global_state_snapshot.corridor_occupancy.keys()))
        else:
            available_corridors = list(self.corridors)

        if not available_corridors:
            available_corridors = list(DEFAULT_CORRIDOR_IDS)

        # Track running occupancy during batch allocation so agents are distributed evenly
        current_occupancy: dict[int, int] = {
            c: global_state_snapshot.corridor_occupancy.get(c, 0)
            for c in available_corridors
        }

        corridor_map: dict[int, int] = {}
        altitude_map: dict[int, int] = {}

        if active_policy == "round_robin":
            for idx, agent_id in enumerate(global_state_snapshot.agent_ids):
                assigned_corridor = available_corridors[idx % len(available_corridors)]
                corridor_map[agent_id] = assigned_corridor
                # Default layer 0 for 2.5D airspace until P1 discrete layer mapping in W3
                altitude_map[agent_id] = 0
        else:  # "least_loaded" policy
            for agent_id in global_state_snapshot.agent_ids:
                # Find corridor with minimum occupancy.
                # Tie-breaking: lower corridor id is selected first.
                least_corridor = min(available_corridors, key=lambda c: (current_occupancy[c], c))
                corridor_map[agent_id] = least_corridor
                current_occupancy[least_corridor] += 1
                altitude_map[agent_id] = 0

        return OverseerDirective(
            corridor_map=corridor_map,
            priority_table=STANDARD_PRIORITY_TABLE,
            altitude_map=altitude_map,
            timestamp=global_state_snapshot.timestamp,
        )


_default_overseer = GlobalOverseer()


def real_overseer_update(
    global_state_snapshot: GlobalStateSnapshot,
    policy: str = "least_loaded",
) -> OverseerDirective:
    """Public Week 2 overseer update using real coarse allocation logic."""
    return _default_overseer.update(global_state_snapshot, policy=policy)


def mock_overseer_update(
    global_state_snapshot: GlobalStateSnapshot,
) -> OverseerDirective:
    """Build and return the complete Week 1 mock directive.

    - The snapshot is checked first, then its timestamp is copied into the directive.  
    - The fixed corridor, priority, and altitude maps are used in Week 1 so P3 can work immediately.  
    - In Week 2 this function will use corridor occupancy, in Week 3 it will consider priority and capacity, and
    in Week 4 it will support the cached directive used during link failure.
    """

    validate_snapshot(global_state_snapshot)

    return OverseerDirective(
        corridor_map = WEEK1_CORRIDOR_MAP,
        priority_table = WEEK1_PRIORITY_TABLE,
        altitude_map = WEEK1_ALTITUDE_MAP,
        timestamp = global_state_snapshot.timestamp,
    )
