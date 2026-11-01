"""Distributed conflict resolution (P2): consensus ADMM separation negotiation."""

from .adapter import resolve_conflict_event
from .solver import ADMMSolver, ADMMResult

__all__ = [
    "ADMMSolver",
    "ADMMResult",
    "resolve_conflict_event",
]
