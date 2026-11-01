"""Fault and attack injection and resilient consensus (P5)."""

from .attack import apply_attack, inject_attack
from .consensus import plain_average, run_consensus

__all__ = [
    "apply_attack",
    "inject_attack",
    "plain_average",
    "run_consensus",
]
