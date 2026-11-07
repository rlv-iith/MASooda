"""P3 junction merging and platoons in road-corridor (route) mode.

Route-mode equivalents of the P3 merge rule in ``local_behavior/boids.py``
(``merge_adjustment``) and of the merge outcome in
``local_behavior/formation_metrics.py`` (``merge_outcomes``). Those assume
straight corridors along +x with a merge zone at ``corridors.merge_zone_x_meters``;
on the road graph the "target corridor" is the outgoing road segment after a
junction (a graph node with degree >= 3). Same parameters, same rule:

* merge zone: the last ``local_behavior.junction_merge_zone_m`` metres before a
  junction on the drone's route;
* gap check (``merge_adjustment``): the gap is NOT ok when a same-layer drone
  already on the outgoing segment, flying the same direction, is closer than
  ``local_behavior.merge_gap`` along the segment axis to the merging drone;
* when the gap is not ok the forward speed is multiplied by ``1 - k_v`` to open
  a gap (no lateral move; the tube keeps the drone in lane);
* outcome (``merge_outcomes``): an attempt is a junction crossed by a drone that
  entered its merge zone; success = it crossed with the gap ok and had no
  loss-of-separation during the attempt, failed = otherwise; attempts cut short
  by landing or a crash are "not reached".

Platoons (no platoon definition exists in ``formation_metrics.py``; this uses
the config parameters ``r_plat``, ``d_0`` and ``h``): a drone's leader is the
nearest same-layer, same-direction drone ahead of it inside its corridor tube
within ``r_plat``. Chains of leader links are platoons. Desired spacing is the
car-following gap ``d_0 + h * v``; time headway = gap / speed.
"""

from __future__ import annotations

from typing import Any, Iterable

import numpy as np


def route_junctions(network: Any, route: Any, degree_min: int = 3) -> list[tuple[float, np.ndarray, np.ndarray, float]]:
    """Junctions on a route: (arc length, xy, outgoing direction, outgoing segment length)."""
    key = {(round(float(x), 3), round(float(y), 3)): i for i, (x, y) in enumerate(network.nodes)}
    out = []
    for k in range(1, len(route.points) - 1):
        p = route.points[k]
        node = key.get((round(float(p[0]), 3), round(float(p[1]), 3)))
        if node is None or len(network.adjacency.get(node, [])) < degree_min:
            continue
        out.append((float(route.cum[k]), p.copy(), route.seg_dir[k].copy(), float(route.seg_len[k])))
    return out


class MergeTracker:
    def __init__(self, network: Any, flights: Iterable[Any], cfg: dict[str, Any]):
        lb = cfg["local_behavior"]
        self.zone = float(lb.get("junction_merge_zone_m", lb.get("look_ahead", 40.0)))
        self.merge_gap = float(lb["merge_gap"])
        self.k_v = float(lb["k_v"])
        self.half_w = float(cfg["corridors"]["width_meters"]) / 2.0
        self._cache: dict[int, list] = {}
        self.junctions: dict[int, list] = {}
        self.next_j: dict[int, int] = {}
        for f in flights:
            self.add(network, f)
        self.open: dict[int, dict[str, Any]] = {}   # drone -> current attempt
        self.success = 0
        self.failed = 0
        self.not_reached = 0
        self.yield_ticks = 0
        self.blocked_now: dict[int, tuple[float, float]] = {}   # drone -> junction xy (this tick)
        self.active_now: dict[int, tuple[float, float]] = {}

    def add(self, network: Any, f: Any) -> None:
        rid = id(f.route)
        if rid not in self._cache:
            self._cache[rid] = route_junctions(network, f.route)
        self.junctions[f.agent_id] = self._cache[rid]
        self.next_j[f.agent_id] = 0

    def factor(self, aid: int, s: float, layer: int, nbrs: Iterable[Any]) -> tuple[float, str | None]:
        """Speed factor for drone ``aid`` at arc length ``s`` (1.0 or 1 - k_v) and an event text."""
        js = self.junctions.get(aid, [])
        k = self.next_j[aid]
        while k < len(js) and s >= js[k][0]:   # crossed: close the attempt
            att = self.open.pop(aid, None)
            if att is not None:
                if att["gap_ok"] and not att["los"]:
                    self.success += 1
                else:
                    self.failed += 1
            k += 1
        self.next_j[aid] = k
        if k >= len(js):
            return 1.0, None
        s_j, xy, d_out, seg_len = js[k]
        d_me = s_j - s
        if d_me > self.zone:
            return 1.0, None
        att = self.open.get(aid)
        new = att is None
        if new:
            att = self.open[aid] = {"j": k, "gap_ok": True, "los": False, "yields": 0}
        left = np.array([-d_out[1], d_out[0]])
        gap_ok, blocker = True, None
        for n in nbrs:
            if n.id == aid or int(n.altitude_layer) != int(layer):
                continue
            rel = np.asarray(n.position[:2], float) - xy
            u = float(rel @ d_out)
            if u < 0.0 or u > seg_len or abs(float(rel @ left)) > self.half_w:
                continue
            if float(np.asarray(n.velocity[:2], float) @ d_out) <= 0.0:
                continue   # opposing flow on the outgoing road is not the target stream
            if u + d_me < self.merge_gap:
                gap_ok, blocker = False, n.id
                break
        att["gap_ok"] = gap_ok
        pos = (round(float(xy[0]), 1), round(float(xy[1]), 1))
        self.active_now[aid] = pos
        if gap_ok:
            return 1.0, None
        self.blocked_now[aid] = pos
        self.yield_ticks += 1
        att["yields"] += 1
        text = None
        if att["yields"] == 1:
            text = (f"Junction merge: gap to D-{blocker} on the outgoing road < {self.merge_gap:.0f} m "
                    f"→ slowing ×{1 - self.k_v:.1f} to open a gap")
        return 1.0 - self.k_v, text

    def on_los(self, ids: Iterable[int]) -> None:
        for i in ids:
            if i in self.open:
                self.open[i]["los"] = True

    def drop(self, aid: int) -> None:
        """Drone landed or crashed: an open attempt was not completed."""
        if self.open.pop(aid, None) is not None:
            self.not_reached += 1

    def frame(self) -> dict[str, Any]:
        """Active / gap-blocked junctions (accumulated since the last frame) and run totals."""
        att = self.success + self.failed
        active = sorted(set(self.active_now.values()))
        blocked = set(self.blocked_now.values())
        out = {
            "attempts": att, "success": self.success, "failed": self.failed, "not_reached": self.not_reached,
            "rate": (self.success / att) if att else None, "yield_ticks": self.yield_ticks,
            "open": len(self.open),
            "junctions": [[x, y, 1 if (x, y) in blocked else 0] for x, y in active],
        }
        self.active_now, self.blocked_now = {}, {}
        return out


def platoon_stats(leaders: dict[int, tuple[int, float, float]], d_0: float, h: float) -> dict[str, Any]:
    """``leaders``: follower id -> (leader id, along-track gap m, follower speed m/s)."""
    if not leaders:
        return {"platoons": 0, "in_platoon": 0, "mean_size": None, "headway_s": None, "spacing_err_m": None}
    followers = set(leaders)
    lead_ids = {v[0] for v in leaders.values()}
    heads = lead_ids - followers
    # chain length from each head (followers point to their leader; invert once)
    behind: dict[int, list[int]] = {}
    for f, (l, _, _) in leaders.items():
        behind.setdefault(l, []).append(f)
    sizes = []
    for hd in sorted(heads):
        size, stack, seen = 0, [hd], set()
        while stack:
            u = stack.pop()
            if u in seen:
                continue
            seen.add(u)
            size += 1
            stack.extend(behind.get(u, []))
        sizes.append(size)
    hw = [g / max(v, 0.5) for _, g, v in leaders.values()]
    err = [abs(g - (d_0 + h * v)) for _, g, v in leaders.values()]
    return {"platoons": len(sizes), "in_platoon": int(sum(sizes)),
            "mean_size": round(float(np.mean(sizes)), 2) if sizes else None,
            "headway_s": round(float(np.mean(hw)), 2), "spacing_err_m": round(float(np.mean(err)), 2)}
