"""Road-derived corridor network for map-constrained flights.

The imported road GeoJSON is projected into the simulation's local metric frame
(equirectangular tangent plane around the map centre), the major road classes
are turned into a routable graph, and each flight receives a polyline route
along that graph. The polyline plus the configured corridor width defines the
flight's lateral boundary; the map extent defines the geofence.

This is a research demonstration: OSM road centrelines are used as a planning
backbone, not as surveyed or approved flight corridors.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import heapq
import json
import math
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

EARTH_M_PER_DEG_LAT = 111_132.0
EARTH_M_PER_DEG_LON_EQ = 111_320.0

# Road classes wide/continuous enough to act as the corridor backbone.
DEFAULT_CORRIDOR_CLASSES = (
    "motorway", "motorway_link", "trunk", "trunk_link",
    "primary", "primary_link", "secondary", "secondary_link",
    "tertiary", "tertiary_link",
)


@dataclass(frozen=True)
class GeoFrame:
    """Local tangent-plane registration around a geographic origin."""

    lon0: float
    lat0: float

    def to_local(self, lon: float, lat: float) -> tuple[float, float]:
        x = (lon - self.lon0) * EARTH_M_PER_DEG_LON_EQ * math.cos(math.radians(self.lat0))
        y = (lat - self.lat0) * EARTH_M_PER_DEG_LAT
        return x, y

    def to_geo(self, x: float, y: float) -> tuple[float, float]:
        lon = self.lon0 + x / (EARTH_M_PER_DEG_LON_EQ * math.cos(math.radians(self.lat0)))
        lat = self.lat0 + y / EARTH_M_PER_DEG_LAT
        return lon, lat


@dataclass
class Vertiport:
    id: str
    name: str
    role: str  # hospital | depot | hub
    node: int                       # corridor junction the approach leg joins
    position: tuple[float, float]   # pad, set back from the corridor


@dataclass
class RoadNetwork:
    """Routable corridor graph in local metres."""

    frame: GeoFrame
    nodes: np.ndarray                      # (M, 2) local xy
    adjacency: dict[int, list[tuple[int, float]]]
    bounds: tuple[float, float, float, float]  # xmin, ymin, xmax, ymax (geofence)
    corridor_lines: list[list[tuple[float, float]]] = field(default_factory=list)
    context_lines: list[list[tuple[float, float]]] = field(default_factory=list)
    vertiports: list[Vertiport] = field(default_factory=list)
    geofence: list[tuple[float, float]] | None = None   # polygon (local metres); None -> bounds box
    backdrop: dict[str, Any] | None = None               # optional raster underlay
    name: str = ""

    # --------------------------------------------------------------- geofence
    def inside(self, x: float, y: float) -> bool:
        if not self.geofence:
            xmin, ymin, xmax, ymax = self.bounds
            return xmin <= x <= xmax and ymin <= y <= ymax
        return _point_in_polygon(x, y, self.geofence)

    def clamp(self, x: float, y: float) -> tuple[float, float, bool]:
        """Project a point outside the geofence onto its boundary. Returns (x, y, corrected)."""
        if self.inside(x, y):
            return x, y, False
        if not self.geofence:
            xmin, ymin, xmax, ymax = self.bounds
            return min(max(x, xmin), xmax), min(max(y, ymin), ymax), True
        ring = np.asarray(self.geofence + self.geofence[:1], dtype=float)
        a, b = ring[:-1], ring[1:]
        p = np.array([x, y])
        ab = b - a
        t = np.clip(np.einsum("ij,ij->i", p - a, ab) / np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-9), 0, 1)
        q = a + ab * t[:, None]
        k = int(np.argmin(np.linalg.norm(q - p, axis=1)))
        # nudge 0.5 m inward so the point is strictly inside
        inward = q[k] + (q[k] - p) / max(float(np.linalg.norm(q[k] - p)), 1e-9) * 0.5
        return float(inward[0]), float(inward[1]), True

    # ------------------------------------------------------------------ graph
    def shortest_path(self, start: int, goal: int) -> list[int]:
        """Dijkstra over the corridor graph; returns node ids (empty if unreachable)."""
        if start == goal:
            return [start]
        dist = {start: 0.0}
        prev: dict[int, int] = {}
        heap = [(0.0, start)]
        while heap:
            d, u = heapq.heappop(heap)
            if u == goal:
                break
            if d > dist.get(u, math.inf):
                continue
            for v, w in self.adjacency.get(u, ()):
                nd = d + w
                if nd < dist.get(v, math.inf):
                    dist[v] = nd
                    prev[v] = u
                    heapq.heappush(heap, (nd, v))
        if goal not in dist:
            return []
        path = [goal]
        while path[-1] != start:
            path.append(prev[path[-1]])
        return path[::-1]

    def route_polyline(self, start: int, goal: int) -> np.ndarray:
        path = self.shortest_path(start, goal)
        return self.nodes[path] if path else np.empty((0, 2))

    def vertiport_route(self, origin: "Vertiport", dest: "Vertiport") -> np.ndarray:
        """Pad → approach leg → corridor path → approach leg → pad."""
        core = self.route_polyline(origin.node, dest.node)
        if len(core) == 0:
            return core
        return np.vstack([np.asarray(origin.position)[None, :], core, np.asarray(dest.position)[None, :]])

    def vertiport(self, vid: str) -> Vertiport:
        for vp in self.vertiports:
            if vp.id == vid:
                return vp
        raise KeyError(f"Unknown vertiport {vid}")

    def to_dict(self) -> dict[str, Any]:
        """JSON payload for the browser: all geometry already in local metres."""
        r = lambda pts: [[round(x, 2), round(y, 2)] for x, y in pts]
        return {
            "name": self.name,
            "origin": {"lon": self.frame.lon0, "lat": self.frame.lat0},
            "geofence": r(self.geofence) if self.geofence else None,
            "backdrop": self.backdrop,
            "bounds": [round(v, 2) for v in self.bounds],
            "corridors": [r(line) for line in self.corridor_lines],
            "context": [r(line) for line in self.context_lines],
            "vertiports": [
                {"id": vp.id, "name": vp.name, "role": vp.role,
                 "x": round(vp.position[0], 2), "y": round(vp.position[1], 2),
                 "jx": round(float(self.nodes[vp.node, 0]), 2), "jy": round(float(self.nodes[vp.node, 1]), 2)}
                for vp in self.vertiports
            ],
            "graph": {"nodes": int(len(self.nodes)),
                      "edges": int(sum(len(v) for v in self.adjacency.values()) // 2)},
        }


def _lines(feature: dict[str, Any]) -> Iterable[list[list[float]]]:
    geom = feature.get("geometry") or {}
    if geom.get("type") == "LineString":
        yield geom.get("coordinates", [])
    elif geom.get("type") == "MultiLineString":
        yield from geom.get("coordinates", [])


def _point_in_polygon(x: float, y: float, poly: Sequence[tuple[float, float]]) -> bool:
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _split_t_junctions(lines: list[list[tuple[float, float]]], tol: float) -> list[list[tuple[float, float]]]:
    """Insert a vertex wherever a line's endpoint touches the interior of another segment."""
    if tol <= 0:
        return lines
    segs = [(li, si, np.asarray(l[si]), np.asarray(l[si + 1])) for li, l in enumerate(lines) for si in range(len(l) - 1)]
    if not segs:
        return lines
    A = np.array([s[2] for s in segs]); B = np.array([s[3] for s in segs])
    AB = B - A; L2 = np.maximum(np.einsum("ij,ij->i", AB, AB), 1e-9)
    inserts: dict[tuple[int, int], list[tuple[float, tuple[float, float]]]] = {}
    for li, line in enumerate(lines):
        for end in (line[0], line[-1]):
            p = np.asarray(end)
            t = np.einsum("ij,ij->i", p - A, AB) / L2
            q = A + AB * np.clip(t, 0, 1)[:, None]
            d = np.linalg.norm(q - p, axis=1)
            for k in np.nonzero((d < tol) & (t > 1e-3) & (t < 1 - 1e-3))[0]:
                sli, ssi = segs[k][0], segs[k][1]
                if sli == li:
                    continue
                inserts.setdefault((sli, ssi), []).append((float(t[k]), (float(q[k][0]), float(q[k][1]))))
                if d[k] > 1e-6:  # also pull the endpoint onto the segment so they share a node
                    idx = 0 if end is line[0] else len(line) - 1
                    line[idx] = (float(q[k][0]), float(q[k][1]))
    out = []
    for li, line in enumerate(lines):
        new = [line[0]]
        for si in range(len(line) - 1):
            for _, pt in sorted(inserts.get((li, si), [])):
                new.append(pt)
            new.append(line[si + 1])
        out.append(new)
    return out


def _geo_bbox(geojson: dict[str, Any]) -> tuple[float, float, float, float]:
    bbox = geojson.get("bbox")
    if isinstance(bbox, list) and len(bbox) == 4:
        return tuple(float(v) for v in bbox)  # type: ignore[return-value]
    xs, ys = [], []
    for feature in geojson.get("features", []):
        for line in _lines(feature):
            for lon, lat, *_ in line:
                xs.append(lon)
                ys.append(lat)
    if not xs:
        raise ValueError("GeoJSON contains no line coordinates")
    return min(xs), min(ys), max(xs), max(ys)


def build_road_network(
    geojson: dict[str, Any],
    corridor_classes: Sequence[str] = DEFAULT_CORRIDOR_CLASSES,
    snap_m: float = 1.5,
    vertiport_count: int = 8,
    geofence_margin_m: float = 25.0,
) -> RoadNetwork:
    """Project a road FeatureCollection and build the corridor graph."""
    if geojson.get("type") != "FeatureCollection":
        raise ValueError("Road input must be a GeoJSON FeatureCollection")
    west, south, east, north = _geo_bbox(geojson)
    frame = GeoFrame((west + east) / 2.0, (south + north) / 2.0)
    x0, y0 = frame.to_local(west, south)
    x1, y1 = frame.to_local(east, north)
    bounds = (x0 + geofence_margin_m, y0 + geofence_margin_m,
              x1 - geofence_margin_m, y1 - geofence_margin_m)

    classes = set(corridor_classes)
    key_to_node: dict[tuple[int, int], int] = {}
    coords: list[tuple[float, float]] = []
    adjacency: dict[int, dict[int, float]] = {}
    corridor_lines: list[list[tuple[float, float]]] = []
    context_lines: list[list[tuple[float, float]]] = []

    def node_for(x: float, y: float) -> int:
        key = (int(round(x / snap_m)), int(round(y / snap_m)))
        idx = key_to_node.get(key)
        if idx is None:
            idx = len(coords)
            key_to_node[key] = idx
            coords.append((x, y))
            adjacency[idx] = {}
        return idx

    geofence: list[tuple[float, float]] | None = None
    named_pads: list[tuple[str, str, str, tuple[float, float]]] = []
    for feature in geojson.get("features", []):
        props = feature.get("properties") or {}
        geom = feature.get("geometry") or {}
        if geom.get("type") == "Polygon" and props.get("geofence"):
            geofence = [frame.to_local(float(p[0]), float(p[1])) for p in geom["coordinates"][0]][:-1]
            continue
        if geom.get("type") == "Point" and props.get("vertiport"):
            lon, lat = geom["coordinates"][:2]
            named_pads.append((str(props.get("ref") or feature.get("id") or f"V{len(named_pads) + 1}"),
                               str(props.get("name") or "Vertiport"), str(props["vertiport"]),
                               frame.to_local(float(lon), float(lat))))
            continue
        highway = props.get("highway")
        for line in _lines(feature):
            pts = [frame.to_local(float(p[0]), float(p[1])) for p in line if len(p) >= 2]
            if len(pts) < 2:
                continue
            (corridor_lines if highway in classes else context_lines).append(pts)

    corridor_lines = _split_t_junctions(corridor_lines, float(geojson.get("junction_snap_m", 2.0)))
    for pts in corridor_lines:
        ids = [node_for(x, y) for x, y in pts]
        for a, b in zip(ids, ids[1:]):
            if a == b:
                continue
            w = math.dist(coords[a], coords[b])
            adjacency[a][b] = min(w, adjacency[a].get(b, math.inf))
            adjacency[b][a] = min(w, adjacency[b].get(a, math.inf))

    if not coords:
        raise ValueError("No corridor-class roads found in the GeoJSON")

    # Keep the largest connected component so every route is feasible.
    seen: set[int] = set()
    best: list[int] = []
    for start in adjacency:
        if start in seen:
            continue
        comp, stack = [], [start]
        seen.add(start)
        while stack:
            u = stack.pop()
            comp.append(u)
            for v in adjacency[u]:
                if v not in seen:
                    seen.add(v)
                    stack.append(v)
        if len(comp) > len(best):
            best = comp
    keep = sorted(best)
    remap = {old: new for new, old in enumerate(keep)}
    nodes = np.array([coords[i] for i in keep], dtype=float)
    adj = {remap[u]: [(remap[v], w) for v, w in adjacency[u].items() if v in remap] for u in keep}

    if geofence:
        gx = [p[0] for p in geofence]; gy = [p[1] for p in geofence]
        bounds = (min(gx), min(gy), max(gx), max(gy))
    network = RoadNetwork(frame=frame, nodes=nodes, adjacency=adj, bounds=bounds,
                          corridor_lines=corridor_lines, context_lines=context_lines,
                          geofence=geofence, name=str(geojson.get("name", "")))
    backdrop = geojson.get("backdrop")
    if isinstance(backdrop, dict) and backdrop.get("image") and len(backdrop.get("bbox", [])) == 4:
        bw, bs, be, bn = (float(v) for v in backdrop["bbox"])
        lx0, ly0 = frame.to_local(bw, bs)
        lx1, ly1 = frame.to_local(be, bn)
        network.backdrop = {"url": f"/data/{Path(backdrop['image']).name}",
                            "bounds": [round(lx0, 2), round(ly0, 2), round(lx1, 2), round(ly1, 2)],
                            "attribution": str(backdrop.get("attribution", ""))}
    if named_pads:
        network.vertiports = [Vertiport(id=vid, name=name, role=role, node=_attach_point(network, pos), position=pos)
                              for vid, name, role, pos in named_pads]
    else:
        network.vertiports = _place_vertiports(network, vertiport_count)
    return network


def _attach_point(network: RoadNetwork, pos: tuple[float, float]) -> int:
    """Return a graph node at the point of the corridor network nearest to pos,
    splitting the nearest edge when that point lies inside it."""
    p = np.asarray(pos, dtype=float)
    best = (math.inf, -1, -1, 0.0, p)
    for u, nbrs in network.adjacency.items():
        for v, _ in nbrs:
            if u >= v:
                continue
            a, b = network.nodes[u], network.nodes[v]
            ab = b - a
            t = float(np.clip((p - a) @ ab / max(float(ab @ ab), 1e-9), 0.0, 1.0))
            q = a + ab * t
            d = float(np.linalg.norm(q - p))
            if d < best[0]:
                best = (d, u, v, t, q)
    _, u, v, t, q = best
    if t < 0.05 or float(np.linalg.norm(q - network.nodes[u])) < 3.0:
        return u
    if t > 0.95 or float(np.linalg.norm(q - network.nodes[v])) < 3.0:
        return v
    m = len(network.nodes)
    network.nodes = np.vstack([network.nodes, q[None, :]])
    network.adjacency[u] = [(x, w) for x, w in network.adjacency[u] if x != v] + [(m, float(np.linalg.norm(q - network.nodes[u])))]
    network.adjacency[v] = [(x, w) for x, w in network.adjacency[v] if x != u] + [(m, float(np.linalg.norm(q - network.nodes[v])))]
    network.adjacency[m] = [(u, float(np.linalg.norm(q - network.nodes[u]))), (v, float(np.linalg.norm(q - network.nodes[v])))]
    return m


def _place_vertiports(network: RoadNetwork, count: int) -> list[Vertiport]:
    """Deterministic farthest-point sampling over junction nodes inside the geofence."""
    xmin, ymin, xmax, ymax = network.bounds
    inset = 60.0
    degree = np.array([len(network.adjacency[i]) for i in range(len(network.nodes))])
    inside = ((network.nodes[:, 0] > xmin + inset) & (network.nodes[:, 0] < xmax - inset)
              & (network.nodes[:, 1] > ymin + inset) & (network.nodes[:, 1] < ymax - inset))
    candidates = np.where(inside & (degree >= 3))[0]
    if len(candidates) < count:
        candidates = np.where(inside)[0]
    if len(candidates) == 0:
        candidates = np.arange(len(network.nodes))
    pts = network.nodes[candidates]
    centre = pts.mean(axis=0)
    chosen = [int(np.argmin(np.linalg.norm(pts - centre, axis=1)))]
    d = np.linalg.norm(pts - pts[chosen[0]], axis=1)
    while len(chosen) < min(count, len(candidates)):
        nxt = int(np.argmax(d))
        chosen.append(nxt)
        d = np.minimum(d, np.linalg.norm(pts - pts[nxt], axis=1))

    roles = ["hub", "hospital", "depot", "hub", "depot", "hospital", "hub", "depot"]
    names = {"hub": "Vertiport", "hospital": "Hospital pad", "depot": "Logistics depot"}
    seg_a, seg_b = _corridor_segments(network)
    out = []
    for k, c in enumerate(chosen):
        node = int(candidates[c])
        role = roles[k % len(roles)]
        pad = _setback_pad(network.nodes[node], seg_a, seg_b, network.bounds)
        out.append(Vertiport(id=f"V{k + 1}", name=f"{names[role]} V{k + 1}", role=role,
                             node=node, position=(float(pad[0]), float(pad[1]))))
    return out


def _corridor_segments(network: RoadNetwork) -> tuple[np.ndarray, np.ndarray]:
    a, b = [], []
    for u, nbrs in network.adjacency.items():
        for v, _ in nbrs:
            if u < v:
                a.append(network.nodes[u])
                b.append(network.nodes[v])
    return np.array(a), np.array(b)


def _segment_distance(p: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    ab = b - a
    t = np.clip(np.einsum("ij,ij->i", p - a, ab) / np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-9), 0, 1)
    q = a + ab * t[:, None]
    return np.linalg.norm(q - p, axis=1)


def _setback_pad(junction: np.ndarray, seg_a: np.ndarray, seg_b: np.ndarray,
                 bounds: tuple[float, float, float, float], setback: float = 45.0) -> np.ndarray:
    """Place the pad off the corridor, in the direction with the most clearance."""
    xmin, ymin, xmax, ymax = bounds
    best, best_clear = junction, -1.0
    for ang in np.linspace(0, 2 * np.pi, 24, endpoint=False):
        cand = junction + setback * np.array([np.cos(ang), np.sin(ang)])
        if not (xmin < cand[0] < xmax and ymin < cand[1] < ymax):
            continue
        clear = float(_segment_distance(cand, seg_a, seg_b).min())
        if clear > best_clear:
            best, best_clear = cand, clear
    return best


_cache: dict[str, tuple[tuple, RoadNetwork]] = {}


def load_road_network(path: str | Path, **kwargs: Any) -> RoadNetwork:
    """Load and cache the network for a GeoJSON file (rebuilt when the file changes)."""
    p = Path(path).resolve()
    stamp = (p.stat().st_mtime_ns, tuple(sorted(kwargs.items())))
    hit = _cache.get(str(p))
    if hit is None or hit[0] != stamp:
        _cache[str(p)] = (stamp, build_road_network(json.loads(p.read_text(encoding="utf-8")), **kwargs))
    return _cache[str(p)][1]


# ---------------------------------------------------------------- polyline math
class RoutePath:
    """Arc-length parameterised polyline with nearest-point queries."""

    def __init__(self, points: np.ndarray):
        pts = np.asarray(points, dtype=float)
        # drop zero-length segments
        keep = [0] + [i for i in range(1, len(pts)) if np.linalg.norm(pts[i] - pts[i - 1]) > 1e-6]
        self.points = pts[keep]
        if len(self.points) < 2:
            self.points = np.vstack([self.points[:1], self.points[:1] + [1e-3, 0.0]])
        seg = np.diff(self.points, axis=0)
        self.seg_len = np.linalg.norm(seg, axis=1)
        self.seg_dir = seg / self.seg_len[:, None]
        self.cum = np.concatenate([[0.0], np.cumsum(self.seg_len)])
        self.length = float(self.cum[-1])

    def point_at(self, s: float) -> np.ndarray:
        s = min(max(s, 0.0), self.length)
        i = int(np.clip(np.searchsorted(self.cum, s, side="right") - 1, 0, len(self.seg_len) - 1))
        return self.points[i] + self.seg_dir[i] * (s - self.cum[i])

    def tangent_at(self, s: float) -> np.ndarray:
        s = min(max(s, 0.0), self.length)
        i = int(np.clip(np.searchsorted(self.cum, s, side="right") - 1, 0, len(self.seg_len) - 1))
        return self.seg_dir[i]

    def project(self, p: np.ndarray, s_hint: float, back: float = 40.0, ahead: float = 120.0
                ) -> tuple[float, np.ndarray, np.ndarray]:
        """Nearest point to p on the route within [s_hint-back, s_hint+ahead].

        Returns (s, closest_point, tangent). The window keeps a drone from
        snapping onto another part of its own route where the route crosses itself.
        """
        lo, hi = s_hint - back, s_hint + ahead
        i0 = int(np.clip(np.searchsorted(self.cum, lo, side="right") - 1, 0, len(self.seg_len) - 1))
        i1 = int(np.clip(np.searchsorted(self.cum, hi, side="right") - 1, 0, len(self.seg_len) - 1))
        a = self.points[i0:i1 + 1]
        d = self.seg_dir[i0:i1 + 1]
        L = self.seg_len[i0:i1 + 1]
        t = np.clip(np.einsum("ij,ij->i", p - a, d), 0.0, L)
        q = a + d * t[:, None]
        k = int(np.argmin(np.einsum("ij,ij->i", q - p, q - p)))
        return float(self.cum[i0 + k] + t[k]), q[k], d[k]
