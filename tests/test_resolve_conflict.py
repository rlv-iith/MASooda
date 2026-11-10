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


def test_health_weight_overrides_the_class_weight():
    from conflict_resolution.adapter import resolve_conflict_event
    agents = _head_on()
    same = {3: 2, 7: 2}

    def moved(weights):
        ev = resolve_conflict_event(agents, priorities=same, weights=weights)
        return {a.id: float(np.linalg.norm(ev.resolution[a.id][:2] - a.velocity[:2])) for a in agents}

    even = moved(None)
    assert abs(even[3] - even[7]) < 1e-6 * max(1.0, even[3])        # equal classes share the manoeuvre
    low_battery = moved({3: 10.0})                                   # drone 3 is short of energy
    assert low_battery[3] < low_battery[7]                           # the other drone does more of it


def test_mock_resolve_conflict_returns_current_velocity():
    agents = _head_on()
    out = mock_resolve_conflict(agents, {})
    for a in agents:
        np.testing.assert_array_equal(out[a.id], a.velocity)
