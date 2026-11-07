"""Centralized architecture in road-corridor (route) mode.

Route-mode port of ``simulation/centralized.py``: the DTC holds the full
(reported) state of every drone and computes every drone's velocity command.
No boids, no ADMM, no tactical altitude shifts, no report defence (it trusts
reports). Same terms and parameters as ``run_centralized``:

* route following: toward the look-ahead point on the route at the type's
  cruise speed (braking to the pad), plus lateral correction ``k_lat`` to the
  keep-left lane (the corridor centreline of the abstract engine);
* car-following: if the closest same-layer, same-direction drone ahead inside
  the tube is nearer than ``d_0 + h * |v|``, speed is scaled by gap / desired gap;
* priority-weighted separation: every same-layer drone within ``r_sep`` pushes
  with ``(w_sep / v_cruise) * ((r_sep - d) / r_sep) / d * diff``, weighted 1 if
  the other drone has higher priority (lower number), 0.5 if equal, 0 if lower;
* speed clipped to ``v_max``.

When the DTC link is down the drones keep their last command (as in
``run_centralized``).
"""

from __future__ import annotations

import math
from typing import Any, Callable

import numpy as np

from simulation.spatial_grid import UniformGrid


def centralized_commands(reported: dict[int, Any], routes: dict[int, Any], progress: dict[int, float],
                         v_ref_of: Callable[[Any, float], float], cfg: dict[str, Any], lane: float,
                         cell: float) -> dict[int, np.ndarray]:
    lb = cfg["local_behavior"]
    v_cruise = float(lb["v_cruise"])
    r_sep, w_sep = float(lb["r_sep"]), float(lb["w_sep"])
    k_lat, look_ahead = float(lb["k_lat"]), float(lb["look_ahead"])
    d_0, h = float(lb["d_0"]), float(lb["h"])
    v_max = float(cfg["safety"]["maximum_velocity_meters_per_second"])
    half_w = float(cfg["corridors"]["width_meters"]) / 2.0

    ids = sorted(reported)
    xy = np.array([reported[i].position[:2] for i in ids], dtype=float).reshape(-1, 2)
    grid = UniformGrid(xy, max(cell, 1e-6))
    reach = max(r_sep, d_0 + h * v_max)
    out: dict[int, np.ndarray] = {}
    for k, i in enumerate(ids):
        a = reported[i]
        route = routes[i]
        p = xy[k]
        s, q, tan = route.project(p, progress[i])
        left = np.array([-tan[1], tan[0]])
        remaining = route.length - s
        v_ref = v_ref_of(a, remaining)
        fade = min(1.0, remaining / 30.0)
        look = min(route.length, s + look_ahead)
        t_look = route.tangent_at(look)
        q_look = route.point_at(look) + np.array([-t_look[1], t_look[0]]) * lane * fade
        to_q = q_look - p
        dist_q = float(np.linalg.norm(to_q))
        v = (to_q / dist_q) * v_ref if dist_q > 1e-6 else np.zeros(2)
        e = float((p - q) @ left)
        v = v + left * (-k_lat * (e - lane * fade))

        near = [ids[j] for j in grid.within(float(p[0]), float(p[1]), reach) if ids[j] != i
                and int(reported[ids[j]].altitude_layer) == int(a.altitude_layer)]
        # car-following
        gap = None
        for j in near:
            rel = np.asarray(reported[j].position[:2], float) - p
            along = float(rel @ tan)
            if along <= 0.0 or abs(float(rel @ left)) > half_w:
                continue
            if float(np.asarray(reported[j].velocity[:2], float) @ tan) < 0.0:
                continue
            gap = along if gap is None else min(gap, along)
        if gap is not None:
            desired_gap = d_0 + h * abs(float(np.linalg.norm(a.velocity[:2])))
            if desired_gap > 1e-9 and gap < desired_gap:
                sp = float(np.linalg.norm(v))
                cap = max(0.0, v_ref * gap / desired_gap)
                if sp > cap and sp > 1e-9:
                    v = v * (cap / sp)
        # priority-weighted separation
        for j in near:
            diff = p - np.asarray(reported[j].position[:2], float)
            d = math.hypot(float(diff[0]), float(diff[1]))
            if 1e-6 < d < r_sep:
                pi, pj = int(a.priority), int(reported[j].priority)
                factor = 1.0 if pi > pj else 0.5 if pi == pj else 0.0
                v = v + factor * (w_sep / v_cruise) * ((r_sep - d) / r_sep) / d * diff
        sp = float(np.linalg.norm(v))
        if sp > v_max:
            v = v * (v_max / sp)
        out[i] = np.array([v[0], v[1], 0.0])
    return out
