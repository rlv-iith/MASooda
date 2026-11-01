"""Fault and attack injection (P5).

inject_attack is a pure function: it never mutates the true agent states.
"""

from __future__ import annotations

import copy
from typing import Sequence
import numpy as np

from config.load_config import get_config
from simulation.schema import AgentState, AgentType, AttackState


def inject_attack(
    agent_states: Sequence[AgentState],
    attack_config: dict,
    t: float,
) -> AttackState:
    """Return the attack state for time ``t``.

    If attack_config["enabled"] is False or t < start_time_seconds, returns an empty AttackState.
    Otherwise falsifies the position for the configured or randomly chosen delivery agent.
    Never modifies agent_states.
    """
    if not attack_config.get("enabled", False):
        return AttackState(malicious=[], falsified={})

    start_time = float(attack_config.get("start_time_seconds", 60.0))
    if t < start_time:
        return AttackState(malicious=[], falsified={})

    cfg = get_config()
    seed = cfg.get("simulation", {}).get("random_seed", 42)
    rng = np.random.default_rng(seed)

    malicious_ids = attack_config.get("malicious_ids")
    if malicious_ids:
        malicious = [int(i) for i in malicious_ids]
    else:
        delivery_ids = sorted([
            a.id for a in agent_states
            if getattr(a, "type", None) == AgentType.DELIVERY or getattr(a, "type", None) == "DELIVERY"
        ])
        if delivery_ids:
            malicious = [int(rng.choice(delivery_ids))]
        else:
            malicious = []

    direction_deg = attack_config.get("direction_deg")
    if direction_deg is not None:
        angle = float(direction_deg)
    else:
        angle = float(rng.uniform(0.0, 360.0))
    rad = np.deg2rad(angle)
    u = np.array([np.cos(rad), np.sin(rad), 0.0], dtype=float)

    mode = attack_config.get("mode", "constant")
    offset_mag = float(attack_config.get("offset_magnitude_meters", 25.0))
    if mode == "ramp":
        ramp_rate = float(attack_config.get("ramp_rate_meters_per_second", 1.0))
        offset = min(offset_mag, ramp_rate * (t - start_time))
    else:
        offset = offset_mag

    agent_dict = {a.id: a for a in agent_states}
    falsified: dict[int, np.ndarray] = {}
    for m in malicious:
        if m in agent_dict:
            falsified[m] = np.array(agent_dict[m].position, dtype=float, copy=True) + offset * u

    return AttackState(malicious=malicious, falsified=falsified)


def apply_attack(
    agent_states: Sequence[AgentState],
    attack_state: AttackState,
) -> list[AgentState]:
    """Return copies of all agents with falsified positions applied to malicious agents.

    Agents in attack_state.falsified get the false position, all others unchanged.
    This provides the 'reported' view that neighbors see, while true states remain untouched.
    """
    reported: list[AgentState] = []
    for agent in agent_states:
        a_copy = copy.deepcopy(agent)
        if a_copy.id in attack_state.falsified:
            a_copy.position = np.array(attack_state.falsified[a_copy.id], dtype=float, copy=True)
        reported.append(a_copy)
    return reported
