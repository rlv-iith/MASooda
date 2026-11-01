"""Distributed conflict resolution (P2): consensus ADMM separation negotiation."""

from .adapter import resolve_conflict_event, resolve_all_conflicts
from .detection import detect_conflicts
from .solver import ADMMSolver, ADMMResult

__all__ = [
    "ADMMSolver",
    "ADMMResult",
    "resolve_conflict_event",
    "resolve_all_conflicts",
    "detect_conflicts",
]
