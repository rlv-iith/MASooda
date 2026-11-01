"""Local behavior module for MASooda (P3 Boids flocking and corridor following)."""

from .boids import (
    alignment,
    cohesion,
    compute_desired_velocity,
    corridor_following,
    corridor_of,
    separation,
    target_corridor,
)

__all__ = [
    "corridor_of",
    "separation",
    "alignment",
    "cohesion",
    "corridor_following",
    "target_corridor",
    "compute_desired_velocity",
]
