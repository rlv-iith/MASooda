import pytest

from simulation import interfaces
from simulation.overseer_link import OverseerLink
from simulation.schema import GlobalStateSnapshot, OverseerDirective


def test_default_config_link_is_up():
    link = OverseerLink()

    assert link.is_up(0.0)
    assert link.is_up(100.0)
    assert link.is_up(1000.0)


def test_configured_link_outage_window():
    link = OverseerLink({
        "enabled": True,
        "down_start_seconds": 10,
        "down_end_seconds": 20,
    })

    assert link.is_up(9.9)
    assert not link.is_up(10.0)
    assert not link.is_up(19.9)
    assert link.is_up(20.0)


def test_request_during_outage_is_dropped():
    link = OverseerLink({
        "enabled": True,
        "down_start_seconds": 10,
        "down_end_seconds": 20,
    })
    snapshot = GlobalStateSnapshot(timestamp=15.0, agent_ids=[1])

    assert link.request(snapshot, 15.0) is None
    assert link.calls == 1
    assert link.dropped == 1
    assert link.errors == 0


def test_request_while_up_returns_directive():
    link = OverseerLink({"enabled": False})
    snapshot = GlobalStateSnapshot(
        timestamp=1.0,
        corridor_occupancy={0: 0, 1: 0, 2: 0},
        agent_ids=[1],
    )

    directive = link.request(snapshot, 1.0)

    assert isinstance(directive, OverseerDirective)
    assert link.calls == 1
    assert link.dropped == 0
    assert link.errors == 0


def test_request_exception_is_counted(monkeypatch):
    def raise_error(_snapshot):
        raise RuntimeError("link failure")

    monkeypatch.setattr(interfaces, "overseer_update", raise_error)
    link = OverseerLink({"enabled": False})
    snapshot = GlobalStateSnapshot(timestamp=1.0, agent_ids=[1])

    assert link.request(snapshot, 1.0) is None
    assert link.errors == 1
