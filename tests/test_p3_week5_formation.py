"""Unit and integration tests for P3 Week 5 formation and merge metrics."""

from __future__ import annotations

import math
import numpy as np
import pytest

from config.load_config import get_config
from local_behavior.boids import reset_local_behavior_cache
from local_behavior.formation_metrics import (
    FormationLogger,
    corridor_utilization,
    merge_outcomes,
)
import simulation.engine
from simulation.overseer import reset_default_overseer
from simulation.scenario import make_initial_agents
from simulation.schema import AgentState, AgentType


def test_merge_success() -> None:
    """One agent starting in corridor 0, assigned to corridor 1, reaching x past merge_end with y on corridor 1 centre -> success."""
    logger = FormationLogger()

    # t=0: in corridor 0 (y=0.0)
    agent_t0 = AgentState(
        id=1,
        type=AgentType.DELIVERY,
        position=np.array([100.0, 0.0, 0.0]),
        corridor_assignment=0,
    )
    logger.log_state(0.0, [agent_t0])

    # t=1: past merge_end (800.0) at x=850.0, on corridor 1 centre (y=50.0), assigned to corridor 1
    agent_t1 = AgentState(
        id=1,
        type=AgentType.DELIVERY,
        position=np.array([850.0, 50.0, 0.0]),
        corridor_assignment=1,
    )
    logger.log_state(1.0, [agent_t1])

    outcomes = merge_outcomes(logger)
    assert outcomes["success"] == 1
    assert outcomes["failed"] == 0
    assert outcomes["not_reached"] == 0
    assert outcomes["no_merge_needed"] == 0
    assert outcomes["merge_attempts"] == 1
    assert outcomes["merge_success_rate"] == 1.0
    assert len(outcomes["agents"]) == 1
    assert outcomes["agents"][0]["outcome"] == "success"


def test_merge_failed() -> None:
    """Agent assigned to corridor 1, reaching past merge_end with y still in corridor 0 -> failed."""
    logger = FormationLogger()

    # t=0: in corridor 0 (y=0.0)
    agent_t0 = AgentState(
        id=1,
        type=AgentType.DELIVERY,
        position=np.array([100.0, 0.0, 0.0]),
        corridor_assignment=0,
    )
    logger.log_state(0.0, [agent_t0])

    # t=1: past merge_end (800.0) at x=850.0, but still in corridor 0 (y=0.0), assigned to corridor 1
    agent_t1 = AgentState(
        id=1,
        type=AgentType.DELIVERY,
        position=np.array([850.0, 0.0, 0.0]),
        corridor_assignment=1,
    )
    logger.log_state(1.0, [agent_t1])

    outcomes = merge_outcomes(logger)
    assert outcomes["success"] == 0
    assert outcomes["failed"] == 1
    assert outcomes["not_reached"] == 0
    assert outcomes["no_merge_needed"] == 0
    assert outcomes["merge_attempts"] == 1
    assert outcomes["merge_success_rate"] == 0.0
    assert outcomes["agents"][0]["outcome"] == "failed"


def test_merge_not_reached() -> None:
    """Agent never passing merge_end -> not_reached."""
    logger = FormationLogger()

    # t=0: in corridor 0 at x=100.0
    agent_t0 = AgentState(
        id=1,
        type=AgentType.DELIVERY,
        position=np.array([100.0, 0.0, 0.0]),
        corridor_assignment=0,
    )
    logger.log_state(0.0, [agent_t0])

    # t=1: at x=600.0, which is before merge_end (800.0)
    agent_t1 = AgentState(
        id=1,
        type=AgentType.DELIVERY,
        position=np.array([600.0, 50.0, 0.0]),
        corridor_assignment=1,
    )
    logger.log_state(1.0, [agent_t1])

    outcomes = merge_outcomes(logger)
    assert outcomes["not_reached"] == 1
    assert outcomes["success"] == 0
    assert outcomes["failed"] == 0
    assert outcomes["merge_attempts"] == 0
    assert math.isnan(outcomes["merge_success_rate"])
    assert outcomes["agents"][0]["outcome"] == "not_reached"


def test_merge_no_merge_needed() -> None:
    """Agent staying in its start corridor -> no_merge_needed."""
    logger = FormationLogger()

    # t=0: in corridor 0 at x=100.0
    agent_t0 = AgentState(
        id=1,
        type=AgentType.DELIVERY,
        position=np.array([100.0, 0.0, 0.0]),
        corridor_assignment=0,
    )
    logger.log_state(0.0, [agent_t0])

    # t=1: past merge_end at x=850.0, assigned to corridor 0 (start corridor)
    agent_t1 = AgentState(
        id=1,
        type=AgentType.DELIVERY,
        position=np.array([850.0, 0.0, 0.0]),
        corridor_assignment=0,
    )
    logger.log_state(1.0, [agent_t1])

    outcomes = merge_outcomes(logger)
    assert outcomes["no_merge_needed"] == 1
    assert outcomes["success"] == 0
    assert outcomes["failed"] == 0
    assert outcomes["not_reached"] == 0
    assert outcomes["merge_attempts"] == 0
    assert math.isnan(outcomes["merge_success_rate"])
    assert outcomes["agents"][0]["outcome"] == "no_merge_needed"


def test_corridor_utilization() -> None:
    """With 15 agents in corridor 0 and capacity 15 -> util 1.0, ticks_over_capacity 0."""
    logger = FormationLogger()

    # 15 agents in corridor 0 (y=0.0)
    agents = [
        AgentState(
            id=i,
            type=AgentType.DELIVERY,
            position=np.array([10.0 * i, 0.0, 0.0]),
            corridor_assignment=0,
        )
        for i in range(15)
    ]
    logger.log_state(0.0, agents)

    res = corridor_utilization(logger, capacity=15)
    assert res[0]["mean_utilization"] == pytest.approx(1.0)
    assert res[0]["util"] == pytest.approx(1.0)
    assert res[0]["ticks_over_capacity"] == 0
    assert res["util_c0"] == pytest.approx(1.0)
    assert res["ticks_over_capacity"] == 0


def test_tiny_real_run() -> None:
    """A tiny real run (10 agents, 3 s) with the logger finishes and merge_outcomes returns all keys."""
    reset_default_overseer()
    reset_local_behavior_cache()

    agents = make_initial_agents(10, seed=42)
    logger = FormationLogger()
    cfg = get_config()

    result = simulation.engine.run_simulation(
        agents,
        duration_s=3.0,
        loggers=[logger],
        use_overseer=True,
        use_admm=True,
        attack_config={**cfg.get("attack", {}), "enabled": False},
        defended=True,
        overseer_link_config={"enabled": False},
    )

    assert result is not None
    assert len(logger.history) > 0

    outcomes = merge_outcomes(logger)
    required_keys = [
        "success",
        "failed",
        "not_reached",
        "no_merge_needed",
        "merge_attempts",
        "merge_success_rate",
        "agents",
    ]
    for key in required_keys:
        assert key in outcomes

