import numpy as np
import pytest

from config.load_config import get_config
from simulation.interfaces import update_local_behavior
from simulation.schema import AgentState, AgentType


def _agent(position, destination):
    return AgentState(id=1, type=AgentType.EVTOL, position=position, destination=destination)


def test_stub_points_at_destination_at_cruise_speed():
    v = update_local_behavior(_agent([0, 0, 0], [300, 400, 2]), [], None)
    assert v.shape == (3,)
    assert v[2] == 0.0
    assert np.linalg.norm(v) == pytest.approx(get_config()["local_behavior"]["v_cruise"])
    assert v[:2] / np.linalg.norm(v) == pytest.approx([0.6, 0.8])


def test_stub_at_destination_returns_zero():
    assert not update_local_behavior(_agent([5, 5, 0], [5, 5, 0]), [], None).any()


def test_local_behavior_and_corridor_config_present():
    cfg = get_config()
    assert cfg["local_behavior"]["r_sep"] == 20.0
    assert cfg["corridors"]["centerline_spacing_meters"] == 50.0
    assert cfg["corridors"]["merge_zone_x_meters"] == [700.0, 800.0]
