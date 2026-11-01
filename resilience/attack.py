"""Fault and attack injection (P5).

inject_attack is a pure function: it never mutates the true agent states.
"""

from __future__ import annotations

from typing import Sequence

from simulation.schema import AgentState, AttackState


def inject_attack(
    agent_states: Sequence[AgentState],
    attack_config: dict,
    t: float,
) -> AttackState:
    """Return the attack state for time ``t``.

    Week 1 stub: always returns an empty AttackState (no malicious agents, no falsified positions).
    """
    return AttackState(malicious=[], falsified={})
