"""Week 1 contract tests for P4's global overseer mock."""

from simulation.interfaces import overseer_update
from simulation.overseer import (
    WEEK1_ALTITUDE_MAP,
    WEEK1_CORRIDOR_MAP,
    WEEK1_PRIORITY_TABLE,
)
from simulation.schema import AgentType, GlobalStateSnapshot, OverseerDirective


def test_mock_returns_the_required_directive() -> None:
    """The mock returns the required directive values."""

    # Occupancy maps each corridor to its agent count.
    # The Week 1 mock does not use occupancy for allocation yet.
    snapshot = GlobalStateSnapshot(timestamp=12.5, corridor_occupancy={1: 2, 2: 1})

    directive = overseer_update(snapshot)

    # These mappings are shared with the local behavior module.
    assert isinstance(directive, OverseerDirective)
    assert directive.corridor_map == WEEK1_CORRIDOR_MAP
    assert directive.priority_table == WEEK1_PRIORITY_TABLE
    assert directive.altitude_map == WEEK1_ALTITUDE_MAP
    assert directive.timestamp == 12.5


def test_priority_order_is_emergency_then_evtol_then_delivery() -> None:
    """Lower rank means higher priority in the shared priority table."""

    # Lower rank means higher priority.
    assert WEEK1_PRIORITY_TABLE[AgentType.EMERGENCY] < WEEK1_PRIORITY_TABLE[AgentType.EVTOL]
    assert WEEK1_PRIORITY_TABLE[AgentType.EVTOL] < WEEK1_PRIORITY_TABLE[AgentType.DELIVERY]


def test_snapshot_validation_rejects_invalid_timestamp() -> None:
    """Malformed snapshots fail before the mock creates a directive."""

    # Simulation time cannot be negative.
    snapshot = GlobalStateSnapshot(timestamp = -1.0)

    try:
        overseer_update(snapshot)
    except ValueError as error:
        assert "timestamp" in str(error)
    else:
        raise AssertionError("negative timestamps must be rejected")

