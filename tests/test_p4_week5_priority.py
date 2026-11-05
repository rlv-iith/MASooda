"""Checks for the E3 priority metrics."""

from __future__ import annotations

import copy

import numpy as np

from config.load_config import get_config
from local_behavior.boids import reset_local_behavior_cache
from simulation.engine import run_simulation
from simulation.overseer import reset_default_overseer
from simulation.priority_metrics import (
    PriorityLogger, baseline_copy, inject_emergency, priority_summary,
)
from simulation.scenario import make_initial_agents
from simulation.schema import AgentState, AgentType


def test_inject_emergency():
    agents = make_initial_agents(12, 42)
    agents[3].type = AgentType.EMERGENCY
    agents[3].priority = 0
    before = copy.deepcopy(agents)
    new, eid = inject_emergency(agents)
    assert agents == before
    ems = [a for a in new if a.type == AgentType.EMERGENCY]
    assert len(ems) == 1 and ems[0].priority == 0 and ems[0].id == eid
    assert ems[0].position[0] == min(a.position[0] for a in new)


def test_baseline_copy():
    new, eid = inject_emergency(make_initial_agents(12, 42))
    base = baseline_copy(new, eid)
    for a, b in zip(new, base):
        assert np.array_equal(a.position, b.position)
    target = next(a for a in base if a.id == eid)
    assert target.type == AgentType.DELIVERY and target.priority == 2


def _agents(n_in_corridor):
    cfg = get_config()
    em = AgentState(id=0, type=AgentType.EMERGENCY, priority=0, corridor_assignment=1)
    others = [
        AgentState(id=i, type=AgentType.DELIVERY, corridor_assignment=1,
                   position=np.array([10.0, 0.0, 0.0]))
        for i in range(1, n_in_corridor)
    ]
    return [em] + others, cfg


def test_compliance_capacity():
    agents, cfg = _agents(16)
    log = PriorityLogger(0, cfg)
    log.log_state(0.0, agents)
    assert log.checks == 1 and log.compliance_rate == 0.0
    agents, cfg = _agents(5)
    log = PriorityLogger(0, cfg)
    log.log_state(0.0, agents)
    assert log.compliance_rate == 1.0


def test_arrival_time_recorded_at_first_crossing():
    cfg = get_config()
    exit_x = float(cfg["corridors"]["exit_zone_x_meters"][0])
    a = AgentState(id=0, type=AgentType.DELIVERY, position=np.array([0.0, 0.0, 0.0]))
    log = PriorityLogger(0, cfg)
    log.log_state(0.0, [a])
    a.position = np.array([exit_x, 0.0, 0.0])
    log.log_state(3.5, [a])
    a.position = np.array([exit_x + 20, 0.0, 0.0])
    log.log_state(4.0, [a])
    assert log.arrival_times[0] == 3.5


def test_tiny_e3_run_has_all_keys():
    cfg = get_config()
    attack = {**cfg["attack"], "enabled": False}
    new, eid = inject_emergency(make_initial_agents(10, 42))
    base = baseline_copy(new, eid)
    initial = copy.deepcopy(new)
    loggers = []
    for fleet in (new, base):
        reset_default_overseer()
        reset_local_behavior_cache()
        log = PriorityLogger(eid, cfg)
        run_simulation(fleet, duration_s=5.0, loggers=[log], attack_config=attack,
                       overseer_link_config={"enabled": False})
        loggers.append(log)
    summary = priority_summary(loggers[0], loggers[1], initial, eid, cfg)
    assert set(summary) == {
        "emergency_travel_time", "emergency_nominal_time", "emergency_delay_s",
        "baseline_same_agent_travel_time", "emergency_time_saved_s",
        "lower_priority_delay_imposed_s", "priority_compliance_rate",
    }
