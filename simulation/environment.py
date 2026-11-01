"""Simulation airspace environment representation and spatial corridor queries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from config.load_config import get_config
from .schema import AgentState


@dataclass
class CorridorGeometry:
    """Predefined spatial corridor lane."""

    id: int
    name: str
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    capacity: int = 15

    @property
    def y_center(self) -> float:
        return (self.y_min + self.y_max) / 2.0

    @property
    def width(self) -> float:
        return self.y_max - self.y_min


def build_corridors(config: dict | None = None) -> list[CorridorGeometry]:
    """Build the parallel corridors (ids 0..count-1) from the corridors section of the config."""
    cfg = (config if config is not None else get_config())["corridors"]
    spacing = float(cfg["centerline_spacing_meters"])
    half_width = float(cfg["width_meters"]) / 2.0
    length = float(cfg["length_meters"])
    return [
        CorridorGeometry(
            id=k,
            name=f"Corridor {k}",
            x_min=0.0,
            x_max=length,
            y_min=k * spacing - half_width,
            y_max=k * spacing + half_width,
            capacity=int(cfg["capacity"]),
        )
        for k in range(int(cfg["count"]))
    ]


def corridor_of_position(y: float, corridors: Sequence[CorridorGeometry]) -> int | None:
    """Return the id of the corridor whose [y_min, y_max] contains y, else None."""
    for corridor in corridors:
        if corridor.y_min <= y <= corridor.y_max:
            return corridor.id
    return None


def in_merge_zone(x: float, config: dict | None = None) -> bool:
    """Return True if x is inside corridors.merge_zone_x_meters."""
    cfg = config if config is not None else get_config()
    merge_zone = cfg["corridors"]["merge_zone_x_meters"]
    return float(merge_zone[0]) <= x <= float(merge_zone[1])


def corridor_occupancy(
    agents: Sequence[AgentState],
    corridors: Sequence[CorridorGeometry],
) -> dict[int, int]:
    """Count agents per corridor id using corridor_of_position(agent.position[1]).

    Every corridor id must appear in the dict, even with count 0.
    """
    occupancy = {c.id: 0 for c in corridors}
    for agent in agents:
        cid = corridor_of_position(float(agent.position[1]), corridors)
        if cid is not None and cid in occupancy:
            occupancy[cid] += 1
    return occupancy

