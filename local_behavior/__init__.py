"""Local behavior module for MASooda (P3 Boids flocking and corridor following)."""

from .boids import (
    active_corridor,
    alignment,
    cohesion,
    compute_desired_velocity,
    corridor_following,
    corridor_of,
    merge_adjustment,
    separation,
    target_corridor,
)

__all__ = [
    "active_corridor",
    "corridor_of",
    "separation",
    "alignment",
    "cohesion",
    "corridor_following",
    "target_corridor",
    "compute_desired_velocity",
    "merge_adjustment",
]
