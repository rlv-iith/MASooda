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
