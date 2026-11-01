"""Unit and contract tests for P4's global overseer (Week 1 mock & Week 2 Section 10.4)."""

import pytest
from simulation.interfaces import overseer_update
from simulation.overseer import (
    GlobalOverseer,
    WEEK1_ALTITUDE_MAP,
    WEEK1_CORRIDOR_MAP,
    WEEK1_PRIORITY_TABLE,
    STANDARD_PRIORITY_TABLE,
    mock_overseer_update,
    real_overseer_update,
)
from simulation.schema import AgentType, GlobalStateSnapshot, OverseerDirective


def test_mock_returns_the_required_directive() -> None:
    """The Week 1 mock returns the fixed contract values."""
    print("\n" + "=" * 70)
    print("TEST: test_mock_returns_the_required_directive")
    print("INTENDED FOR: Validating Week 1 mock contract backward compatibility.")
    print("INPUT: GlobalStateSnapshot(timestamp=12.5, corridor_occupancy={1: 2, 2: 1})")

    snapshot = GlobalStateSnapshot(timestamp=12.5, corridor_occupancy={1: 2, 2: 1})
    directive = mock_overseer_update(snapshot)

    print(f"OUTPUT DIRECTIVE: corridor_map={directive.corridor_map}")
    print(f"                  priority_table={directive.priority_table}")
    print(f"                  altitude_map={directive.altitude_map}")
    print(f"                  timestamp={directive.timestamp}")
    print("VERIFICATION: Returned directive matches frozen Week 1 mappings.")
    print("=" * 70)

    assert isinstance(directive, OverseerDirective)
    assert directive.corridor_map == WEEK1_CORRIDOR_MAP
    assert directive.priority_table == WEEK1_PRIORITY_TABLE
    assert directive.altitude_map == WEEK1_ALTITUDE_MAP
    assert directive.timestamp == 12.5


def test_priority_order_is_emergency_then_evtol_then_delivery() -> None:
    """Lower rank means higher priority in the shared priority table."""
    print("\n" + "=" * 70)
    print("TEST: test_priority_order_is_emergency_then_evtol_then_delivery")
    print("INTENDED FOR: Ensuring priority ranks enforce Emergency > eVTOL > Delivery.")
    print(f"TABLE: {STANDARD_PRIORITY_TABLE}")

    assert STANDARD_PRIORITY_TABLE[AgentType.EMERGENCY] < STANDARD_PRIORITY_TABLE[AgentType.EVTOL]
    assert STANDARD_PRIORITY_TABLE[AgentType.EVTOL] < STANDARD_PRIORITY_TABLE[AgentType.DELIVERY]

    print("OUTPUT: EMERGENCY (0) < EVTOL (1) < DELIVERY (2). Priority ordering confirmed.")
    print("=" * 70)


def test_snapshot_validation_rejects_invalid_timestamp() -> None:
    """Malformed snapshots fail before creating a directive."""
    print("\n" + "=" * 70)
    print("TEST: test_snapshot_validation_rejects_invalid_timestamp")
    print("INTENDED FOR: Safety precondition check rejecting negative timestamp (-1.0).")
    snapshot = GlobalStateSnapshot(timestamp=-1.0)
    with pytest.raises(ValueError, match="timestamp") as exc_info:
        overseer_update(snapshot)
    print(f"OUTPUT: Successfully caught expected error -> {exc_info.value}")
    print("=" * 70)


def test_snapshot_validation_rejects_negative_occupancy() -> None:
    """Negative occupancy counts are rejected."""
    print("\n" + "=" * 70)
    print("TEST: test_snapshot_validation_rejects_negative_occupancy")
    print("INTENDED FOR: Safety check rejecting invalid negative occupancy count ({0: -2}).")
    snapshot = GlobalStateSnapshot(timestamp=1.0, corridor_occupancy={0: -2})
    with pytest.raises(ValueError, match="occupancy") as exc_info:
        overseer_update(snapshot)
    print(f"OUTPUT: Successfully caught expected error -> {exc_info.value}")
    print("=" * 70)


def test_snapshot_validation_rejects_negative_agent_id() -> None:
    """Negative agent IDs are rejected."""
    print("\n" + "=" * 70)
    print("TEST: test_snapshot_validation_rejects_negative_agent_id")
    print("INTENDED FOR: Safety check rejecting impossible negative agent IDs ([-5]).")
    snapshot = GlobalStateSnapshot(timestamp=1.0, agent_ids=[-5])
    with pytest.raises(ValueError, match="agent IDs") as exc_info:
        overseer_update(snapshot)
    print(f"OUTPUT: Successfully caught expected error -> {exc_info.value}")
    print("=" * 70)


def test_real_overseer_least_loaded_policy() -> None:
    """Section 10.4: Assign incoming agents to least-loaded corridors first."""
    print("\n" + "=" * 70)
    print("TEST: test_real_overseer_least_loaded_policy")
    print("INTENDED FOR: Section 10.4 core requirement - dynamic least-loaded corridor allocation.")
    print("INPUT OCCUPANCIES: {Corridor 0: 5, Corridor 1: 2, Corridor 2: 7}")
    print("INCOMING AGENTS: [101, 102, 103, 104]")

    snapshot = GlobalStateSnapshot(
        timestamp=5.0,
        corridor_occupancy={0: 5, 1: 2, 2: 7},
        agent_ids=[101, 102, 103, 104],
    )

    directive = real_overseer_update(snapshot, policy="least_loaded")

    print("ALLOCATION PROCESS:")
    print("  • Agent 101 -> Assigned to least-loaded Corridor 1 (occupancy was 2 -> now 3)")
    print("  • Agent 102 -> Assigned to least-loaded Corridor 1 (occupancy was 3 -> now 4)")
    print("  • Agent 103 -> Assigned to least-loaded Corridor 1 (occupancy was 4 -> now 5)")
    print("  • Agent 104 -> Tie between Corridor 0 (5) and Corridor 1 (5) -> Assigned to Corridor 0")
    print(f"FINAL OUTPUT CORRIDOR MAP: {directive.corridor_map}")
    print("=" * 70)

    assert isinstance(directive, OverseerDirective)
    assert directive.timestamp == 5.0
    assert directive.corridor_map[101] == 1
    assert directive.corridor_map[102] == 1
    assert directive.corridor_map[103] == 1
    assert directive.corridor_map[104] == 0


def test_real_overseer_tie_breaking_distribution() -> None:
    """When all corridors have equal occupancy, agents distribute evenly starting from lowest ID."""
    print("\n" + "=" * 70)
    print("TEST: test_real_overseer_tie_breaking_distribution")
    print("INTENDED FOR: Verifying deterministic tie-breaking and even load distribution across equal corridors.")
    print("INPUT OCCUPANCIES: {Corridor 0: 0, Corridor 1: 0, Corridor 2: 0}")
    print("INCOMING AGENTS: [1, 2, 3, 4]")

    snapshot = GlobalStateSnapshot(
        timestamp=10.0,
        corridor_occupancy={0: 0, 1: 0, 2: 0},
        agent_ids=[1, 2, 3, 4],
    )

    directive = real_overseer_update(snapshot, policy="least_loaded")

    print(f"FINAL OUTPUT CORRIDOR MAP: {directive.corridor_map}")
    print("  • Agent 1 -> Corridor 0")
    print("  • Agent 2 -> Corridor 1")
    print("  • Agent 3 -> Corridor 2")
    print("  • Agent 4 -> Corridor 0 (cycled back to lowest load)")
    print("=" * 70)

    assert directive.corridor_map[1] == 0
    assert directive.corridor_map[2] == 1
    assert directive.corridor_map[3] == 2
    assert directive.corridor_map[4] == 0


def test_real_overseer_round_robin_policy() -> None:
    """Section 10.4: Round-robin cycling policy assigns agents in cyclic order."""
    print("\n" + "=" * 70)
    print("TEST: test_real_overseer_round_robin_policy")
    print("INTENDED FOR: Section 10.4 alternative policy - cyclic Round-Robin allocation.")
    print("CORRIDORS: [0, 1, 2]")
    print("INCOMING AGENTS: [10, 20, 30, 40, 50]")

    overseer = GlobalOverseer(corridors=[0, 1, 2], policy="round_robin")
    snapshot = GlobalStateSnapshot(
        timestamp=2.0,
        agent_ids=[10, 20, 30, 40, 50],
    )

    directive = overseer.update(snapshot)

    print(f"FINAL OUTPUT CORRIDOR MAP: {directive.corridor_map}")
    print(f"ALTITUDE MAP: {directive.altitude_map}")
    print("=" * 70)

    assert directive.corridor_map == {10: 0, 20: 1, 30: 2, 40: 0, 50: 1}
    assert all(directive.altitude_map[agent_id] == 0 for agent_id in [10, 20, 30, 40, 50])


def test_real_overseer_empty_agent_list() -> None:
    """An empty agent list returns a valid directive with empty mapping without errors."""
    print("\n" + "=" * 70)
    print("TEST: test_real_overseer_empty_agent_list")
    print("INTENDED FOR: Edge-case resilience - verifying overseer handles empty agent list gracefully.")
    print("INPUT: agent_ids=[]")

    snapshot = GlobalStateSnapshot(
        timestamp=0.0,
        corridor_occupancy={0: 3, 1: 4, 2: 1},
        agent_ids=[],
    )

    directive = real_overseer_update(snapshot, policy="least_loaded")

    print(f"FINAL OUTPUT DIRECTIVE: corridor_map={directive.corridor_map}, altitude_map={directive.altitude_map}")
    print("=" * 70)

    assert directive.corridor_map == {}
    assert directive.altitude_map == {}
    assert directive.timestamp == 0.0


def test_non_trivial_directive_definition_of_done() -> None:
    """Week 2 DoD: Overseer generates dynamic non-trivial directives matching scenario inputs."""
    print("\n" + "=" * 70)
    print("TEST: test_non_trivial_directive_definition_of_done")
    print("INTENDED FOR: Week 2 Definition of Done - proving directives are dynamic and non-trivial.")
    
    s1 = GlobalStateSnapshot(timestamp=1.0, corridor_occupancy={0: 10, 1: 0}, agent_ids=[99])
    s2 = GlobalStateSnapshot(timestamp=2.0, corridor_occupancy={0: 0, 1: 10}, agent_ids=[99])

    d1 = real_overseer_update(s1, policy="least_loaded")
    d2 = real_overseer_update(s2, policy="least_loaded")

    print(f"Scenario 1 (Corridor 0 crowded, Corridor 1 empty) -> Agent 99 assigned to: Corridor {d1.corridor_map[99]}")
    print(f"Scenario 2 (Corridor 0 empty, Corridor 1 crowded) -> Agent 99 assigned to: Corridor {d2.corridor_map[99]}")
    print("VERIFICATION: Directives adapt to actual traffic conditions.")
    print("=" * 70)

    assert d1.corridor_map[99] == 1
    assert d2.corridor_map[99] == 0
    assert d1.corridor_map != d2.corridor_map



