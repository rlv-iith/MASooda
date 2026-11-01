"""Boids local behavior implementation for MASooda (P3 Week 2).

Implements separation, alignment, cohesion, corridor following, target corridor
resolution, and desired velocity computation following docs/p3_boids_formulation.pdf.
"""

from __future__ import annotations

from typing import Any, Sequence
import numpy as np

from config.load_config import get_config

# Module-level dictionary caching the last known corridor assignment per agent ID
_last_corridor: dict[int, int] = {}


def corridor_of(y: float) -> int:
    """Determine corridor index for a given lateral y coordinate.

    Formula: round(y / centerline_spacing_meters), clipped to 0..count-1.
    """
    cfg = get_config()
    spacing = float(cfg["corridors"]["centerline_spacing_meters"])
    count = int(cfg["corridors"]["count"])
    idx = int(round(float(y) / spacing))
    return int(np.clip(idx, 0, count - 1))


def separation(agent: Any, neighbors: Sequence[Any]) -> np.ndarray:
    """Compute separation velocity term over neighbors within r_sep.

    Formula: sum over neighbors with distance < r_sep of (p_i - p_j) / d^2.
    Skip a neighbor at distance 0.
    """
    cfg = get_config()
    r_sep = float(cfg["local_behavior"]["r_sep"])
    p_i = np.asarray(agent.position[:2], dtype=float)
    v_sep = np.zeros(2, dtype=float)

    for n in neighbors:
        if getattr(n, "id", None) == getattr(agent, "id", None):
            continue
        p_j = np.asarray(n.position[:2], dtype=float)
        diff = p_i - p_j
        d = float(np.linalg.norm(diff))
        if 0.0 < d < r_sep:
            v_sep += diff / (d ** 2)

    return v_sep


def alignment(agent: Any, same_corridor: Sequence[Any]) -> np.ndarray:
    """Compute alignment velocity term matching same-corridor neighbors' velocity.

    Formula: mean velocity of same_corridor minus own velocity. Zero if list is empty.
    """
    valid = [n for n in same_corridor if getattr(n, "id", None) != getattr(agent, "id", None)]
    if not valid:
        return np.zeros(2, dtype=float)
    v_i = np.asarray(agent.velocity[:2], dtype=float)
    v_mean = np.mean([np.asarray(n.velocity[:2], dtype=float) for n in valid], axis=0)
    return v_mean - v_i


def cohesion(agent: Any, same_corridor: Sequence[Any]) -> np.ndarray:
    """Compute cohesion velocity term along the corridor (+x).

    Formula: (mean position - own position), keep only the x part.
    Return zero if the list is empty OR if any same-corridor neighbor is closer than r_sep.
    """
    valid = [n for n in same_corridor if getattr(n, "id", None) != getattr(agent, "id", None)]
    if not valid:
        return np.zeros(2, dtype=float)

    cfg = get_config()
    r_sep = float(cfg["local_behavior"]["r_sep"])
    p_i = np.asarray(agent.position[:2], dtype=float)

    for n in valid:
        p_j = np.asarray(n.position[:2], dtype=float)
        d = float(np.linalg.norm(p_i - p_j))
        if d < r_sep:
            return np.zeros(2, dtype=float)

    p_mean = np.mean([np.asarray(n.position[:2], dtype=float) for n in valid], axis=0)
    diff_x = float(p_mean[0] - p_i[0])
    return np.array([diff_x, 0.0], dtype=float)


def corridor_following(agent: Any, corridor: int) -> np.ndarray:
    """Compute forward and lateral velocity to follow assigned corridor centerline.

    Formula:
    y_target = corridor * centerline_spacing_meters.
    q = (min(x + look_ahead, length_meters), y_target).
    v_goal = v_cruise * (q - p) / |q - p|, then add (0, -k_lat * (y - y_target)).
    """
    cfg = get_config()
    spacing = float(cfg["corridors"]["centerline_spacing_meters"])
    length_meters = float(cfg["corridors"]["length_meters"])
    look_ahead = float(cfg["local_behavior"]["look_ahead"])
    v_cruise = float(cfg["local_behavior"]["v_cruise"])
    k_lat = float(cfg["local_behavior"]["k_lat"])

    x = float(agent.position[0])
    y = float(agent.position[1])
    y_target = float(corridor) * spacing
    q = np.array([min(x + look_ahead, length_meters), y_target], dtype=float)
    p = np.array([x, y], dtype=float)
    diff = q - p
    dist = float(np.linalg.norm(diff))
    if dist > 0.0:
        v_goal = v_cruise * (diff / dist)
    else:
        v_goal = np.zeros(2, dtype=float)
    v_goal += np.array([0.0, -k_lat * (y - y_target)], dtype=float)
    return v_goal


def target_corridor(agent: Any, directive: Any | None) -> int | None:
    """Determine target corridor for the agent using overseer directive or cached/state fallback.

    Formula:
    if directive is not None and agent.id is in directive.corridor_map, use that and save it
    in a module-level dict _last_corridor[agent.id].
    Else use _last_corridor[agent.id] if present.
    Else use agent.corridor_assignment.
    If all are missing return None.
    """
    if directive is not None and hasattr(directive, "corridor_map") and agent.id in directive.corridor_map:
        corr = int(directive.corridor_map[agent.id])
        _last_corridor[agent.id] = corr
        return corr
    if agent.id in _last_corridor:
        return _last_corridor[agent.id]
    if getattr(agent, "corridor_assignment", None) is not None:
        return int(agent.corridor_assignment)
    return None


def active_corridor(agent: Any, target: int | None) -> int | None:
    """Determine the active corridor considering the merge zone.

    - current = corridor_of(agent.position[1])
    - if target is None -> return current
    - if target == current -> return target
    - if agent x is before the merge zone start -> return current (wait for the merge zone)
    - if agent x is inside the merge zone or after it -> return target
    """
    current = corridor_of(agent.position[1])
    if target is None:
        return current
    if target == current:
        return target

    cfg = get_config()
    merge_zone = cfg["corridors"]["merge_zone_x_meters"]
    merge_start = float(merge_zone[0])
    x = float(agent.position[0])

    if x < merge_start:
        return current
    return target


def merge_adjustment(agent: Any, neighbors: Sequence[Any], target: int) -> np.ndarray:
    """Compute adjustment for merging into another corridor.

    Used only when active_corridor(...) != corridor_of(agent y) (the agent is merging):
    - gap_ok = no neighbor that is already in the target corridor (corridor_of(n.y) == target)
      has |n.x - agent.x| < merge_gap
    - if gap_ok: lateral velocity toward the target corridor centerline, capped at
      merge_lateral_speed
    - if not gap_ok: lateral velocity 0 (stay in lane) and reduce forward speed by multiplying
      vx by (1 - k_v) to open a gap (k_v already exists in the config)

    Returns a 2-vector [vx_factor, vy].
    """
    cfg = get_config()
    merge_gap = float(cfg["local_behavior"]["merge_gap"])
    merge_lateral_speed = float(cfg["local_behavior"]["merge_lateral_speed"])
    k_v = float(cfg["local_behavior"]["k_v"])

    agent_x = float(agent.position[0])

    gap_ok = True
    for n in neighbors:
        if getattr(n, "id", None) == getattr(agent, "id", None):
            continue
        if corridor_of(n.position[1]) == target:
            if abs(float(n.position[0]) - agent_x) < merge_gap:
                gap_ok = False
                break

    if gap_ok:
        v_cf_y = corridor_following(agent, target)[1]
        vy = float(np.clip(v_cf_y, -merge_lateral_speed, merge_lateral_speed))
        return np.array([1.0, vy], dtype=float)
    else:
        return np.array([1.0 - k_v, 0.0], dtype=float)


def compute_desired_velocity(
    agent: Any,
    neighbors: Sequence[Any],
    directive: Any | None,
) -> np.ndarray:
    """Compute local boids desired velocity vector for the agent.

    Formula:
    same_corridor = neighbors whose corridor_of(y) equals corridor_of(agent y).
    If target_corridor is None, v_goal = v_cruise toward agent.destination instead.
    v = w_g*v_goal + w_sep*separation + w_ali*alignment + w_coh*cohesion.
    If |v| > maximum_velocity_meters_per_second, scale it down to that.
    Replace any NaN with 0. Return np.array([vx, vy, 0.0]).
    """
    cfg = get_config()
    v_cruise = float(cfg["local_behavior"]["v_cruise"])
    w_g = float(cfg["local_behavior"]["w_g"])
    w_sep = float(cfg["local_behavior"]["w_sep"])
    w_ali = float(cfg["local_behavior"]["w_ali"])
    w_coh = float(cfg["local_behavior"]["w_coh"])
    v_max = float(cfg["safety"]["maximum_velocity_meters_per_second"])

    agent_corr = corridor_of(agent.position[1])
    same_corridor = [
        n for n in neighbors
        if getattr(n, "id", None) != getattr(agent, "id", None)
        and corridor_of(n.position[1]) == agent_corr
    ]

    target_corr = target_corridor(agent, directive)
    if target_corr is not None:
        active_corr = active_corridor(agent, target_corr)
        v_goal = corridor_following(agent, active_corr)
        if active_corr != agent_corr:
            adj = merge_adjustment(agent, neighbors, active_corr)
            v_goal[0] *= adj[0]
            v_goal[1] = adj[1]
    else:
        to_dest = np.asarray(agent.destination[:2], dtype=float) - np.asarray(agent.position[:2], dtype=float)
        dist_dest = float(np.linalg.norm(to_dest))
        if dist_dest > 0.0:
            v_goal = v_cruise * (to_dest / dist_dest)
        else:
            v_goal = np.zeros(2, dtype=float)

    v_sep = separation(agent, neighbors)
    v_ali = alignment(agent, same_corridor)
    v_coh = cohesion(agent, same_corridor)

    v = w_g * v_goal + w_sep * v_sep + w_ali * v_ali + w_coh * v_coh
    v = np.nan_to_num(v, nan=0.0)

    speed = float(np.linalg.norm(v))
    if speed > v_max and speed > 1e-9:
        v = v * (v_max / speed)

    v = np.nan_to_num(v, nan=0.0)
    return np.array([float(v[0]), float(v[1]), 0.0], dtype=float)
