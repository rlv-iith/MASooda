"""DTC operator console (Phase 4): command validation, zone geometry, zone-aware route planning.

Commands follow the API in ``docs/INTEGRATION_PLAN.md`` section 4:
``{type, targets: [drone ids], params: {...}, reason}``. The route engine applies a
command at a tick boundary (``simulation.route_engine``) and stamps it with
``tick_received`` (entered the engine), ``tick_delivered`` (crossed the DTC link) and
per-target results. Replaying the log by ``tick_received`` reproduces the run.

Movement commands are checked against the drone's remaining energy (Phase 3B
health model) before they are applied; ``dry_run`` asks only for that check.
"""

from __future__ import annotations

import heapq
import math
from typing import Any, Sequence

import numpy as np

from simulation.road_network import RoutePath

# type -> (needs targets, movement command checked against energy)
COMMANDS: dict[str, tuple[bool, bool]] = {
    "add_drone": (False, False),
    "reroute": (True, True),
    "ground_now": (True, False),          # landing is never refused for energy
    "hold": (True, True),
    "resume": (True, False),
    "rtb": (True, True),
    "change_layer": (True, True),
    "speed_limit": (False, True),         # targets or a sector
    "priority": (True, False),
    "tfr": (False, False),
    "tfr_cancel": (False, False),
    "ground_stop": (False, False),
    "ground_stop_release": (False, False),
    "quarantine": (True, False),
    "lost_link_policy": (False, False),   # targets or the fleet default
    "divert_charge": (True, True),
    "fleet_ground_bms_critical": (False, False),
    "fleet_recall_below_soc": (False, True),
}
LOST_LINK_POLICIES = ("continue", "hold", "rtb", "land")
PRIORITY_LEVELS = {"EMERGENCY": 0, "EVTOL": 1, "DELIVERY": 2}


def _num(params: dict, key: str, lo: float, hi: float, default: Any = None, required: bool = False) -> Any:
    v = params.get(key, default)
    if v is None:
        if required:
            raise ValueError(f"params.{key} is required")
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ValueError(f"params.{key} must be a number")
    if not lo <= float(v) <= hi:
        raise ValueError(f"params.{key} must be between {lo:g} and {hi:g}")
    return float(v)


def validate_command(body: Any, known_ids: set[int], vertiports: Sequence[str], num_layers: int,
                     duration_s: float, v_max: float, n_sectors: int) -> dict[str, Any]:
    """Check one console command and return it normalized (raises ValueError with a readable message)."""
    if not isinstance(body, dict):
        raise ValueError("command must be a JSON object")
    ctype = body.get("type")
    if ctype not in COMMANDS:
        raise ValueError(f"unknown command type {ctype!r}; choose one of: {', '.join(COMMANDS)}")
    needs_targets, _ = COMMANDS[ctype]
    targets = body.get("targets") or []
    if not isinstance(targets, list) or not all(isinstance(t, int) and not isinstance(t, bool) for t in targets):
        raise ValueError("targets must be a list of drone ids")
    unknown = [t for t in targets if t not in known_ids]
    if unknown:
        raise ValueError(f"unknown drone id(s): {', '.join('D-%d' % t for t in unknown[:5])}")
    if needs_targets and not targets:
        raise ValueError(f"{ctype} needs at least one target drone")
    params = dict(body.get("params") or {})
    vp = set(vertiports)
    out_params: dict[str, Any] = {}
    if ctype == "reroute":
        dest, via = params.get("dest"), params.get("via")
        if dest is None and via is None:
            raise ValueError("reroute needs params.dest (pad) and/or params.via ([x, y])")
        if dest is not None and dest not in vp:
            raise ValueError(f"params.dest '{dest}' is not a vertiport")
        if via is not None:
            if not (isinstance(via, list) and len(via) == 2 and all(isinstance(v, (int, float)) for v in via)):
                raise ValueError("params.via must be [x, y] in metres")
            out_params["via"] = [float(via[0]), float(via[1])]
        out_params["dest"] = dest
    elif ctype == "change_layer":
        out_params["layer"] = int(_num(params, "layer", 0, num_layers - 1, required=True))
    elif ctype == "speed_limit":
        out_params["v"] = _num(params, "v", 0.5, v_max, required=True)
        out_params["expires_s"] = _num(params, "expires_s", 1.0, duration_s, default=60.0)
        sector = params.get("sector")
        if sector is not None:
            out_params["sector"] = int(_num(params, "sector", 0, n_sectors - 1))
        elif not targets:
            raise ValueError("speed_limit needs targets or params.sector")
    elif ctype == "priority":
        level = params.get("level")
        if isinstance(level, str) and level.upper() in PRIORITY_LEVELS:
            level = PRIORITY_LEVELS[level.upper()]
        out_params["level"] = int(_num({"level": level}, "level", 0, 9, required=True))
    elif ctype == "tfr":
        poly = params.get("polygon")
        if (not isinstance(poly, list) or len(poly) < 3
                or not all(isinstance(p, list) and len(p) == 2 and all(isinstance(c, (int, float)) for c in p) for p in poly)):
            raise ValueError("params.polygon must be at least 3 [x, y] points")
        if polygon_area(poly) < 100.0:
            raise ValueError("the restricted area is too small (< 100 m²)")
        out_params["polygon"] = [[float(x), float(y)] for x, y in poly]
        out_params["start_s"] = _num(params, "start_s", 0.0, duration_s, default=0.0)
        out_params["end_s"] = _num(params, "end_s", 0.0, 1e9, default=duration_s)
        if out_params["end_s"] <= out_params["start_s"]:
            raise ValueError("params.end_s must be after params.start_s")
        out_params["name"] = str(params.get("name") or "TFR")[:40]
    elif ctype == "tfr_cancel":
        out_params["name"] = str(params.get("name") or "")[:40]
    elif ctype in ("ground_stop", "ground_stop_release"):
        out_params["sector"] = int(_num(params, "sector", 0, n_sectors - 1, required=True))
        if ctype == "ground_stop":
            out_params["release_s"] = _num(params, "release_s", 0.0, 1e9)
    elif ctype == "lost_link_policy":
        pol = params.get("policy")
        if pol not in LOST_LINK_POLICIES:
            raise ValueError(f"params.policy must be one of {', '.join(LOST_LINK_POLICIES)}")
        out_params["policy"] = pol
    elif ctype == "divert_charge":
        pad = params.get("pad")
        if pad not in vp:
            raise ValueError(f"params.pad '{pad}' is not a vertiport")
        mode = params.get("mode", "swap")
        if mode not in ("charge", "swap"):
            raise ValueError("params.mode must be 'charge' or 'swap'")
        out_params.update(pad=pad, mode=mode)
    elif ctype == "fleet_recall_below_soc":
        out_params["threshold_pct"] = _num(params, "threshold_pct", 1.0, 100.0, required=True)
    return {"type": ctype, "targets": [int(t) for t in targets], "params": out_params,
            "reason": str(body.get("reason") or "")[:200], "dry_run": bool(body.get("dry_run", False)),
            "force": bool(body.get("force", False))}


# ----------------------------------------------------------------------------- geometry
def polygon_area(poly: Sequence[Sequence[float]]) -> float:
    p = np.asarray(poly, dtype=float)
    x, y = p[:, 0], p[:, 1]
    return float(abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))) / 2.0)


def points_in_polygon(xy: np.ndarray, poly: Sequence[Sequence[float]]) -> np.ndarray:
    """Vectorised even-odd rule; ``xy`` (n, 2)."""
    xy = np.asarray(xy, dtype=float).reshape(-1, 2)
    p = np.asarray(poly, dtype=float)
    x, y = xy[:, 0][:, None], xy[:, 1][:, None]
    x1, y1 = p[:, 0][None, :], p[:, 1][None, :]
    x2, y2 = np.roll(p[:, 0], -1)[None, :], np.roll(p[:, 1], -1)[None, :]
    cond = (y1 > y) != (y2 > y)
    with np.errstate(divide="ignore", invalid="ignore"):
        xin = (x2 - x1) * (y - y1) / (y2 - y1) + x1
    return (np.sum(cond & (x < xin), axis=1) % 2) == 1


def segments_cross_polygon(a: np.ndarray, b: np.ndarray, poly: Sequence[Sequence[float]]) -> np.ndarray:
    """For segments a[i]→b[i]: True if either end is inside or the segment crosses an edge."""
    a = np.asarray(a, dtype=float).reshape(-1, 2)
    b = np.asarray(b, dtype=float).reshape(-1, 2)
    if not len(a):
        return np.zeros(0, dtype=bool)
    p = np.asarray(poly, dtype=float)
    c, d = p, np.roll(p, -1, axis=0)

    def orient(p1, p2, p3):
        return (p2[..., 0] - p1[..., 0]) * (p3[..., 1] - p1[..., 1]) - (p2[..., 1] - p1[..., 1]) * (p3[..., 0] - p1[..., 0])

    A, B = a[:, None, :], b[:, None, :]
    C, D = c[None, :, :], d[None, :, :]
    o1, o2 = orient(A, B, C), orient(A, B, D)
    o3, o4 = orient(C, D, A), orient(C, D, B)
    crosses = np.any((o1 * o2 < 0) & (o3 * o4 < 0), axis=1)
    return crosses | points_in_polygon(a, poly) | points_in_polygon(b, poly)


def route_hits_zones(route: RoutePath, s_from: float, zones: Sequence[Sequence[Sequence[float]]]) -> bool:
    """Does the remaining part of ``route`` (from arc length ``s_from``) touch any zone polygon?"""
    if not zones:
        return False
    k = int(np.clip(np.searchsorted(route.cum, s_from, side="right") - 1, 0, len(route.seg_len) - 1))
    pts = np.vstack([route.point_at(s_from)[None, :], route.points[k + 1:]])
    if len(pts) < 2:
        return False
    return any(bool(segments_cross_polygon(pts[:-1], pts[1:], z).any()) for z in zones)


def plan_route(network: Any, start_xy: np.ndarray, goal_xy: np.ndarray, goal_node: int,
               zones: Sequence[Sequence[Sequence[float]]] = (), via_node: int | None = None,
               direct_within_m: float = 0.0) -> RoutePath | None:
    """Road-graph route from a position to a pad that avoids the zone polygons.

    The drone's own position and its nearest node may be inside a zone (it must be
    able to leave); every other node inside a zone and every edge crossing one is
    excluded. Returns None when no route exists.
    """
    start_xy = np.asarray(start_xy, dtype=float)
    goal_xy = np.asarray(goal_xy, dtype=float)
    if direct_within_m and float(np.linalg.norm(goal_xy - start_xy)) <= direct_within_m:
        if not any(segments_cross_polygon(start_xy[None, :], goal_xy[None, :], z)[0] for z in zones):
            return RoutePath(np.vstack([start_xy[None, :], goal_xy[None, :]]))
    nodes = network.nodes
    d2 = np.einsum("ij,ij->i", nodes - start_xy, nodes - start_xy)
    start = int(np.argmin(d2))
    blocked_nodes: set[int] = set()
    for z in zones:
        blocked_nodes.update(np.nonzero(points_in_polygon(nodes, z))[0].tolist())
    blocked_nodes.discard(start)
    if goal_node in blocked_nodes:
        return None

    def path(a: int, b: int) -> list[int]:
        dist, prev, heap = {a: 0.0}, {}, [(0.0, a)]
        while heap:
            d, u = heapq.heappop(heap)
            if u == b:
                break
            if d > dist.get(u, math.inf):
                continue
            nbrs = [(v, w) for v, w in network.adjacency.get(u, ()) if v not in blocked_nodes]
            if zones and nbrs:
                vs = np.array([v for v, _ in nbrs])
                bad = np.zeros(len(vs), dtype=bool)
                for z in zones:
                    bad |= segments_cross_polygon(np.repeat(nodes[[u]], len(vs), axis=0), nodes[vs], z) \
                        & ~points_in_polygon(np.repeat(nodes[[u]], len(vs), axis=0), z)
                nbrs = [n for n, b_ in zip(nbrs, bad.tolist()) if not b_]
            for v, w in nbrs:
                nd = d + w
                if nd < dist.get(v, math.inf):
                    dist[v], prev[v] = nd, u
                    heapq.heappush(heap, (nd, v))
        if b not in dist:
            return []
        out = [b]
        while out[-1] != a:
            out.append(prev[out[-1]])
        return out[::-1]

    if via_node is not None and via_node not in blocked_nodes:
        p1 = path(start, via_node)
        p2 = path(via_node, goal_node)
        if not p1 or not p2:
            return None
        seq = p1 + p2[1:]
    else:
        seq = path(start, goal_node)
        if not seq:
            return None
    pts = np.vstack([start_xy[None, :], nodes[seq], goal_xy[None, :]])
    return RoutePath(pts)
