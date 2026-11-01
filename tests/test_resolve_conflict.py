import numpy as np

from simulation.interfaces import mock_resolve_conflict, resolve_conflict
from simulation.schema import AgentState, AgentType


def _head_on():
    a = AgentState(id=3, type=AgentType.EVTOL, position=[-4.0, 0.1, 0.0], velocity=[10.0, 0.0, 0.0])
    b = AgentState(id=7, type=AgentType.DELIVERY, position=[4.0, -0.1, 0.0], velocity=[-10.0, 0.0, 0.0])
    return [a, b]


def test_resolve_conflict_head_on_returns_velocity_for_both_ids():
    out = resolve_conflict(_head_on(), {3: 1, 7: 2})
    assert set(out) == {3, 7}
    assert all(np.all(np.isfinite(v)) for v in out.values())


def test_mock_resolve_conflict_returns_current_velocity():
    agents = _head_on()
    out = mock_resolve_conflict(agents, {})
    for a in agents:
        np.testing.assert_array_equal(out[a.id], a.velocity)
