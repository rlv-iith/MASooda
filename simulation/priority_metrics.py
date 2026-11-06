"""Priority-compliance and delay metrics for the emergency experiment (E3)."""

from __future__ import annotations

import copy
from typing import Sequence

import numpy as np

from config.load_config import get_config
from simulation.schema import AgentState, AgentType


def inject_emergency(agents: Sequence[AgentState]) -> tuple[list[AgentState], int]:
    """Return a copy of the fleet with a single EMERGENCY agent at the queue tail.

    Existing emergency agents are demoted to EVTOL (priority 1). The agent with
    the smallest x (ties: smallest id) becomes EMERGENCY with priority 0.
    """
    new_agents = copy.deepcopy(list(agents))
    for a in new_agents:
        if a.type == AgentType.EMERGENCY:
            a.type = AgentType.EVTOL
            a.priority = 1
    chosen = min(new_agents, key=lambda a: (float(a.position[0]), a.id))
    chosen.type = AgentType.EMERGENCY
    chosen.priority = 0
    return new_agents, chosen.id


def baseline_copy(agents: Sequence[AgentState], emergency_id: int) -> list[AgentState]:
    """Control run fleet: the emergency agent is an ordinary DELIVERY agent."""
    out = copy.deepcopy(list(agents))
    for a in out:
        if a.id == emergency_id:
            a.type = AgentType.DELIVERY
            a.priority = 2
    return out


class PriorityLogger:
    """Logger recording emergency corridor compliance and agent arrival times."""

    def __init__(self, emergency_id: int, cfg: dict | None = None) -> None:
        cfg = cfg if cfg is not None else get_config()
        self.emergency_id = int(emergency_id)
        dt = float(cfg["simulation"]["timestep_seconds"])
        period = float(cfg["overseer"]["update_period_seconds"])
        self._dt = dt
        self._period_steps = max(1, int(round(period / dt)))
        self._capacity = int(cfg["corridors"]["capacity"])
        self._exit_x = float(cfg["corridors"]["exit_zone_x_meters"][0])
        self.checks = 0
        self.compliant = 0
        self._arrival: dict[int, float] = {}
        self._seen: set[int] = set()

    def log_state(self, t: float, agents: Sequence[AgentState]) -> None:
        for a in agents:
            self._seen.add(a.id)
            if a.id not in self._arrival and float(a.position[0]) >= self._exit_x:
                self._arrival[a.id] = float(t)

        if int(round(t / self._dt)) % self._period_steps != 0:
            return
        em = next((a for a in agents if a.id == self.emergency_id), None)
        if em is None:
            return
        self.checks += 1
        corridor = em.corridor_assignment
        if corridor is not None:
            load = sum(1 for a in agents if a.corridor_assignment == corridor)
            if load <= self._capacity:
                self.compliant += 1

    @property
    def compliance_rate(self) -> float:
        return self.compliant / self.checks if self.checks else float("nan")

    @property
    def arrival_times(self) -> dict[int, float]:
        return {i: self._arrival.get(i, float("nan")) for i in sorted(self._seen)}


def nominal_time(agent: AgentState, cfg: dict | None = None) -> float:
    """Free-flow travel time from the agent's start to the exit zone."""
    cfg = cfg if cfg is not None else get_config()
    exit_x = float(cfg["corridors"]["exit_zone_x_meters"][0])
    return (exit_x - float(agent.position[0])) / float(cfg["local_behavior"]["v_cruise"])


def priority_summary(
    logger_emergency_run: PriorityLogger,
    logger_baseline_run: PriorityLogger,
    agents: Sequence[AgentState],
    emergency_id: int,
    cfg: dict | None = None,
) -> dict:
    """Summarise emergency delay and the delay imposed on other agents.

    ``agents`` are the initial agents (used for the nominal time).
    """
    cfg = cfg if cfg is not None else get_config()
    nan = float("nan")
    em_arr = logger_emergency_run.arrival_times
    base_arr = logger_baseline_run.arrival_times
    agent = next(a for a in agents if a.id == emergency_id)

    travel = em_arr.get(emergency_id, nan)
    base_travel = base_arr.get(emergency_id, nan)
    nominal = nominal_time(agent, cfg)

    diffs = [
        em_arr[i] - base_arr[i]
        for i in em_arr
        if i != emergency_id and i in base_arr
        and np.isfinite(em_arr[i]) and np.isfinite(base_arr[i])
    ]
    return {
        "emergency_travel_time": travel,
        "emergency_nominal_time": nominal,
        "emergency_delay_s": travel - nominal,
        "baseline_same_agent_travel_time": base_travel,
        "emergency_time_saved_s": base_travel - travel,
        "lower_priority_delay_imposed_s": float(np.mean(diffs)) if diffs else nan,
        "priority_compliance_rate": logger_emergency_run.compliance_rate,
    }
