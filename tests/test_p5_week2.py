"""P5 Week 2 unit tests: Attack injection, reported views, and consensus baseline."""

from __future__ import annotations

import copy
import numpy as np
import pytest

from config.load_config import get_config
from resilience.attack import apply_attack, inject_attack
from resilience.consensus import plain_average, run_consensus
from simulation.mock_data import get_mock_agent_states, get_mock_comm_graph
from simulation.schema import AgentType, AttackState


def test_inject_attack_enabled_malicious_ids():
    states = get_mock_agent_states()
    cfg = {
        **get_config()["attack"],
        "enabled": True,
        "malicious_ids": [2],
        "offset_magnitude_meters": 25.0,
    }
    t = float(cfg["start_time_seconds"])
    result = inject_attack(states, cfg, t)
    assert result.malicious == [2]
    assert 2 in result.falsified
    diff = np.linalg.norm(result.falsified[2] - states[2].position)
    assert abs(diff - 25.0) < 1e-9


def test_inject_attack_before_start():
    states = get_mock_agent_states()
    cfg = {
        **get_config()["attack"],
        "enabled": True,
        "malicious_ids": [2],
    }
    t = float(cfg["start_time_seconds"]) - 1.0
    result = inject_attack(states, cfg, t)
    assert isinstance(result, AttackState)
    assert result.malicious == []
    assert result.falsified == {}


def test_inject_attack_ramp_mode():
    states = get_mock_agent_states()
    cfg = {
        **get_config()["attack"],
        "enabled": True,
        "malicious_ids": [2],
        "mode": "ramp",
        "ramp_rate_meters_per_second": 1.0,
        "offset_magnitude_meters": 25.0,
    }
    t = float(cfg["start_time_seconds"]) + 5.0
    result = inject_attack(states, cfg, t)
    assert 2 in result.falsified
    offset_length = np.linalg.norm(result.falsified[2] - states[2].position)
    assert np.isclose(offset_length, 5.0, atol=1e-9)


def test_empty_malicious_ids_picks_delivery_agent():
    states = get_mock_agent_states()
    cfg = {
        **get_config()["attack"],
        "enabled": True,
        "malicious_ids": [],
    }
    t = float(cfg["start_time_seconds"])
    res1 = inject_attack(states, cfg, t)
    res2 = inject_attack(states, cfg, t)
    assert len(res1.malicious) == 1
    assert res1.malicious == res2.malicious
    chosen_id = res1.malicious[0]
    agent = next(a for a in states if a.id == chosen_id)
    assert agent.type == AgentType.DELIVERY


def test_apply_attack_changes_only_agent_2_position():
    states = get_mock_agent_states()
    before = copy.deepcopy(states)
    attack_state = AttackState(
        malicious=[2],
        falsified={2: states[2].position + np.array([25.0, 0.0, 0.0])},
    )
    reported = apply_attack(states, attack_state)
    # Does not change input list
    assert states == before
    # Changes only agent 2's position
    assert np.array_equal(reported[2].position, attack_state.falsified[2])
    for a_rep, a_orig in zip(reported, states):
        if a_rep.id != 2:
            assert np.array_equal(a_rep.position, a_orig.position)
        assert a_rep.id == a_orig.id
        assert a_rep.type == a_orig.type
        assert np.array_equal(a_rep.velocity, a_orig.velocity)


def test_plain_average():
    # plain_average([1, 2] neighbors, own 3) == 2
    assert plain_average(3, [1, 2]) == 2
    assert plain_average(3.0, [1.0, 2.0]) == 2.0
    arr_res = plain_average(np.array([3.0, 6.0]), [np.array([1.0, 2.0]), np.array([2.0, 4.0])])
    assert np.allclose(arr_res, [2.0, 4.0])


def test_run_consensus_no_liars():
    states = get_mock_agent_states()
    graph = get_mock_comm_graph()
    initial_values = {a.id: float(a.position[0]) for a in states}
    history = run_consensus(initial_values, graph, liars={}, steps=100)
    final_step = history[-1]
    comp1_vals = [final_step[i] for i in range(6)]
    spread = max(comp1_vals) - min(comp1_vals)
    assert spread < 1e-3


def test_run_consensus_with_liar():
    states = get_mock_agent_states()
    graph = get_mock_comm_graph()
    initial_values = {a.id: float(a.position[0]) for a in states}
    steps = int(get_config()["attack"]["consensus_steps"])

    no_liar_history = run_consensus(initial_values, graph, liars={}, steps=steps)
    no_liar_final = no_liar_history[-1]

    liar_offset = 25.0
    liar_val = initial_values[2] + liar_offset
    liar_history = run_consensus(initial_values, graph, liars={2: liar_val}, steps=steps)
    liar_final = liar_history[-1]

    honest_comp1 = [0, 1, 3, 4, 5]
    dist_with_liar = [abs(liar_final[i] - liar_val) for i in honest_comp1]
    dist_without_liar = [abs(no_liar_final[i] - liar_val) for i in honest_comp1]
    assert np.mean(dist_with_liar) < np.mean(dist_without_liar)

    for i in [6, 7, 8, 9]:
        assert np.isclose(liar_final[i], no_liar_final[i], atol=1e-12)
