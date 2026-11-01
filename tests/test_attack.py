import copy
import numpy as np

from config.load_config import get_config
from simulation.interfaces import inject_attack, wmsr_filter
from simulation.mock_data import get_mock_agent_states
from simulation.schema import AttackState


def test_inject_attack_stub_returns_empty_attack_state():
    cfg = get_config()["attack"]
    for t in (0.0, cfg["start_time_seconds"], 120.0):
        result = inject_attack(get_mock_agent_states(), cfg, t)
        assert isinstance(result, AttackState)
        assert result.malicious == [] and result.falsified == {}


def test_inject_attack_does_not_modify_agent_states():
    states = get_mock_agent_states()
    before = copy.deepcopy(states)
    inject_attack(states, {**get_config()["attack"], "enabled": True, "malicious_ids": [0]}, 100.0)
    assert states == before


def test_attack_config_defaults():
    cfg = get_config()["attack"]
    assert cfg["enabled"] is False and cfg["malicious_ids"] == []
    assert cfg["mode"] == "constant" and cfg["delivery"] == "common"
    assert cfg["offset_magnitude_meters"] == 25.0 and cfg["direction_deg"] is None


def test_wmsr_filter_returns_finite_three_vector():
    states = get_mock_agent_states()
    result = wmsr_filter(states[0], states[1:], 1)
    assert result.shape == (3,)
    assert result.dtype.kind == "f"
    assert np.isfinite(result).all()
    assert result[2] == states[0].position[2]
