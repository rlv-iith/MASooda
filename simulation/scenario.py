"""Scenario generation for MASooda multi-agent simulation.

Generates heterogeneous agent fleets deployed into predefined flight corridors
with collision-free initial positions in the entry zone.
"""

from __future__ import annotations

import numpy as np

from config.load_config import get_config
from .schema import AgentState, AgentType


def make_initial_agents(
    n: int | None = None,
    seed: int | None = None,
) -> list[AgentState]:
    """Generate initial agent population for the simulation.

    Parameters
    ----------
    n : int, optional
        Number of agents. Defaults to simulation.num_agents from config.
    seed : int, optional
        Random seed. Defaults to simulation.random_seed from config.

    Returns
    -------
    list[AgentState]
        List of initialized AgentState objects.
    """
    cfg = get_config()
    sim_cfg = cfg.get("simulation", {})
    corridors_cfg = cfg.get("corridors", {})
    safety_cfg = cfg.get("safety", {})
    scenario_cfg = cfg.get("scenario", {})

    if n is None:
        n = int(sim_cfg.get("num_agents", 60))
    if seed is None:
        seed = int(sim_cfg.get("random_seed", 42))

    rng = np.random.default_rng(seed)

    centerline_spacing = float(corridors_cfg.get("centerline_spacing_meters", 50.0))
    entry_zone = corridors_cfg.get("entry_zone_x_meters", [0.0, 100.0])
    exit_zone = corridors_cfg.get("exit_zone_x_meters", [1400.0, 1500.0])
    x_min = float(entry_zone[0])
    x_max = float(entry_zone[1])
    min_sep = float(safety_cfg.get("minimum_separation_meters", 8.0))

    dest_x = (float(exit_zone[0]) + float(exit_zone[1])) / 2.0

    # Parse type mix probabilities
    type_mix = scenario_cfg.get("type_mix", {"EMERGENCY": 0.1, "EVTOL": 0.3, "DELIVERY": 0.6})
    types = [AgentType.EMERGENCY, AgentType.EVTOL, AgentType.DELIVERY]
    probs = [
        float(type_mix.get("EMERGENCY", 0.1)),
        float(type_mix.get("EVTOL", 0.3)),
        float(type_mix.get("DELIVERY", 0.6)),
    ]
    prob_sum = sum(probs)
    probs = [p / prob_sum for p in probs]

    priority_map = {
        AgentType.EMERGENCY: 0,
        AgentType.EVTOL: 1,
        AgentType.DELIVERY: 2,
    }

    agents: list[AgentState] = []
    positions: list[tuple[float, float]] = []

    for i in range(n):
        corridor_id = i % 3
        y_center = corridor_id * centerline_spacing
        y = y_center + float(rng.uniform(-2.0, 2.0))

        # Sample x in entry zone, expanding range if density exceeds geometric packing
        placed = False
        cur_xmax = x_max
        for attempt in range(200):
            x = float(rng.uniform(x_min, cur_xmax))
            if all(np.hypot(x - px, y - py) >= min_sep for px, py in positions):
                positions.append((x, y))
                placed = True
                break
            if attempt > 40 and attempt % 10 == 0:
                cur_xmax += 10.0

        if not placed:
            while not placed:
                x = float(rng.uniform(x_min, cur_xmax))
                if all(np.hypot(x - px, y - py) >= min_sep for px, py in positions):
                    positions.append((x, y))
                    placed = True
                    break
                cur_xmax += 5.0

        chosen_type_idx = int(rng.choice(len(types), p=probs))
        chosen_type = types[chosen_type_idx]
        priority = priority_map[chosen_type]
        destination = np.array([dest_x, y_center, 0.0], dtype=float)

        agent = AgentState(
            id=i,
            type=chosen_type,
            position=np.array([x, y, 0.0], dtype=float),
            velocity=np.zeros(3, dtype=float),
            acceleration=np.zeros(3, dtype=float),
            destination=destination,
            priority=priority,
            corridor_assignment=corridor_id,
            neighbor_set=[],
            altitude_layer=0,
        )
        agents.append(agent)

    return agents
