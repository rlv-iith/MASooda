"""Map-constrained multi-drone simulation (road-corridor mode).

Each flight follows a shortest-path route on the road-derived corridor graph
between two vertiports. The project's own modules are used unchanged for the
governance layers:

* P1  ``step_dynamics`` (2.5D double integrator) and ``build_comm_graph``
* P3  boids separation/alignment (``local_behavior.boids``) on top of route following
* P2  ADMM conflict resolution (``resolve_all_conflicts``) everywhere on the map
* P4  ``GlobalOverseer`` priority-aware layer allocation per airspace sector,
      reached through an ``OverseerLink`` that can drop out
* P5  attack injection + trusted-range / W-MSR neighbour-report defence
* P6  STL minimum-separation robustness (layer-aware, metric 3D)

Boundary conditions enforced every tick after dynamics:

* corridor tube: a drone may not leave ``corridors.width_meters / 2`` of its
  route centreline; the position is projected back onto the tube wall and the
  outward velocity component is removed (sliding wall);
* geofence: the drone is clamped to the map extent with the same rule.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
import math
from typing import Any, Callable, Iterator, Sequence

import numpy as np

from config.load_config import get_config, use_run_config
from local_behavior.boids import alignment, separation
from resilience.attack import apply_attack, inject_attack
from resilience.defense import defend_neighbor_reports
from resilience.spoofer_estimate import estimate_spoofer_position, report_status
from simulation.admm_probe import ADMMProbe
from simulation.comm_graph import build_knn_graph, build_radius_graph
from simulation.dynamics import step_dynamics
from simulation.overseer import GlobalOverseer
from simulation.overseer_link import OverseerLink
from simulation.road_network import RoadNetwork, RoutePath
from simulation.route_centralized import centralized_commands
from simulation.route_formation import MergeTracker, platoon_stats
from simulation.route_priority import EmergencyTracker
from simulation.schema import AgentState, AgentType, GlobalStateSnapshot
from simulation.spatial_grid import (
    UniformGrid, close_same_layer_pairs, layered_min_separation_grid, radius_adjacency,
)

QUEUED, AIRBORNE, LANDED, CRASHED = 0, 1, 2, 3
MERGE_CLEARANCE_M = 45.0  # departure needs this gap at the corridor junction on its layer
CRASH_RADIUS_M = 2.0  # physical contact between ~1 m-class airframes on the same layer
TYPE_PRIORITY = {AgentType.EMERGENCY: 0, AgentType.EVTOL: 1, AgentType.DELIVERY: 2}
TYPE_SPEED_FACTOR = {AgentType.EMERGENCY: 1.2, AgentType.EVTOL: 1.0, AgentType.DELIVERY: 0.9}
SECTOR_COLS, SECTOR_ROWS = 3, 2
# architecture -> (DTC on, ADMM on, report defence on, DTC computes every velocity)
ARCHITECTURES = {
    "hierarchical": None,                          # DTC + local boids/ADMM; switches as requested
    "centralized": (True, False, False, True),     # route-mode port of simulation/centralized.py
    "decentralized": (False, True, True, False),   # no DTC, ADMM + defence
    "decentralized_undefended": (False, True, False, False),  # no DTC, ADMM, no defence
}


@dataclass
class Flight:
    agent_id: int
    type: AgentType
    origin: str
    destination: str
    route: RoutePath
    depart_s: float
    task: str = ""


def _route_mode_config(config: dict[str, Any]) -> dict[str, Any]:
    """Run-scoped config tweaks: ADMM must act at every junction, not only the abstract merge zone."""
    cfg = copy.deepcopy(config)
    cfg.setdefault("admm", {})["merge_zone_only"] = False
    cfg.setdefault("overseer", {})["default_policy"] = "priority_aware"
    return cfg


# --------------------------------------------------------------------- planning
def plan_flights(
    network: RoadNetwork,
    n: int,
    type_mix: dict[str, float],
    seed: int,
    departure_window_s: float,
) -> list[Flight]:
    """Generate n flights with vertiport origin/destination chosen by mission type."""
    rng = np.random.default_rng(seed)
    types = []
    weights = np.array([type_mix.get(t.value, 0.0) for t in AgentType], dtype=float)
    if weights.sum() <= 0:
        raise ValueError("Vehicle mix must contain at least one non-zero share")
    exact = weights / weights.sum() * n
    counts = np.floor(exact).astype(int)
    for k in np.argsort(-(exact - counts))[: n - counts.sum()]:
        counts[k] += 1
    for t, c in zip(AgentType, counts):
        types += [t] * int(c)
    rng.shuffle(types)

    vps = network.vertiports
    by_role = {r: [v for v in vps if v.role == r] for r in ("hub", "hospital", "depot")}
    tasks = {AgentType.EMERGENCY: "medical response", AgentType.EVTOL: "passenger transport",
             AgentType.DELIVERY: "parcel delivery"}
    routes: dict[tuple[str, str], RoutePath] = {}
    flights: list[Flight] = []
    for i, t in enumerate(types):
        if t == AgentType.EMERGENCY:
            dest = by_role["hospital"] or vps
            origin_pool = [v for v in vps if v not in dest] or vps
        elif t == AgentType.DELIVERY:
            origin_pool = by_role["depot"] or vps
            dest = [v for v in vps if v not in origin_pool] or vps
        else:
            origin_pool = by_role["hub"] or vps
            dest = [v for v in vps if v.role != "depot"] or vps
        o = origin_pool[int(rng.integers(len(origin_pool)))]
        choices = [v for v in dest if v.id != o.id] or [v for v in vps if v.id != o.id]
        # favour nearer destinations so most flights complete inside a demo run
        d = np.array([math.dist(o.position, v.position) for v in choices])
        p = np.exp(-d / 1500.0)
        dvp = choices[int(rng.choice(len(choices), p=p / p.sum()))]
        key = (o.id, dvp.id)
        if key not in routes:
            routes[key] = RoutePath(network.vertiport_route(o, dvp))
        depart = 0.0 if t == AgentType.EMERGENCY and i < 2 else float(rng.uniform(0.0, departure_window_s))
        flights.append(Flight(agent_id=i, type=t, origin=o.id, destination=dvp.id,
                              route=routes[key], depart_s=round(depart, 1), task=tasks[t]))
    flights.sort(key=lambda f: f.depart_s)
    return flights


# ------------------------------------------------------------------- run state
@dataclass
class RouteRunStats:
    admm_events: int = 0
    admm_nonconverged: int = 0
    overseer_calls: int = 0
    overseer_dropped: int = 0
    layer_changes: int = 0
    layer_changes_deferred: int = 0
    reports_dropped: int = 0
    spoofed_reports_accepted: int = 0
    attack_active_ticks: int = 0
    tube_corrections: int = 0
    geofence_corrections: int = 0
    max_lateral_error_m: float = 0.0
    arrivals: int = 0
    safety_violation_ticks: int = 0
    min_separation_m: float = math.inf
    pad_holds: int = 0
    crashes: int = 0
    crashed_drones: int = 0
    near_misses: int = 0
    tactical_layer_shifts: int = 0
    dtc_directives: int = 0
    malicious_ids: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = dict(self.__dict__)
        d["min_separation_m"] = None if not math.isfinite(self.min_separation_m) else self.min_separation_m
        return d


def _sector(network: RoadNetwork, x: float, y: float) -> int:
    xmin, ymin, xmax, ymax = network.bounds
    c = int(np.clip((x - xmin) / (xmax - xmin) * SECTOR_COLS, 0, SECTOR_COLS - 1))
    r = int(np.clip((y - ymin) / (ymax - ymin) * SECTOR_ROWS, 0, SECTOR_ROWS - 1))
    return r * SECTOR_COLS + c


def _layer_transition_clear(agent: AgentState, target: int, airborne: Sequence[AgentState], d_min: float,
                            horizon_s: float = 10.0) -> bool:
    """True when no drone on the target layer is close now or on a near-collision course."""
    p, v = agent.position[:2], agent.velocity[:2]
    for other in airborne:
        if other.id == agent.id or int(other.altitude_layer) != target:
            continue
        r = other.position[:2] - p
        if float(np.linalg.norm(r)) < 3.0 * d_min:
            return False
        vrel = other.velocity[:2] - v
        vv = float(vrel @ vrel)
        if vv > 1e-6:
            t_cpa = -float(r @ vrel) / vv
            if 0.0 < t_cpa < horizon_s and float(np.linalg.norm(r + vrel * t_cpa)) < 2.0 * d_min:
                return False
    return True


def layered_min_separation(xy: np.ndarray, layers: np.ndarray, layer_height_m: float) -> float:
    """Minimum metric 3D pairwise distance; altitude = layer * layer height."""
    if len(xy) < 2:
        return math.inf
    p = np.column_stack([xy, layers.astype(float) * layer_height_m])
    diff = p[:, None, :] - p[None, :, :]
    dist = np.sqrt(np.einsum("ijk,ijk->ij", diff, diff))
    np.fill_diagonal(dist, np.inf)
    return float(dist.min())


def simulate_routes(
    network: RoadNetwork,
    flights: Sequence[Flight],
    duration_s: float,
    config: dict[str, Any] | None = None,
    use_overseer: bool = True,
    use_admm: bool = True,
    defended: bool = True,
    attack_config: dict[str, Any] | None = None,
    overseer_link_config: dict[str, Any] | None = None,
    should_stop: Callable[[], bool] | None = None,
    frame_every: int = 1,
    spatial_index: bool | None = None,
    exact_positions: bool = False,
    architecture: str = "hierarchical",
    junction_merge: bool = True,
) -> Iterator[dict[str, Any]]:
    """Yield one item per tick.

    Every ``frame_every``-th tick (and the last tick) is a full frame: positions,
    layers, status, robustness, network metrics, events. The other ticks yield a
    light ``{"t", "k", "partial": True, "events", "stats"}`` item so callers never
    lose events. ``frame_every=1`` (default) yields a full frame every tick.

    ``spatial_index`` (default ``web.spatial_index`` from config, else True) uses
    the uniform-grid queries from ``simulation.spatial_grid``; results are
    identical to the brute-force path (``False``), only faster for large fleets.
    ``exact_positions`` adds unrounded ``"pos"`` [[x, y, layer], ...] to full frames
    (used by the equivalence test).

    ``architecture`` (see ``ARCHITECTURES``): ``hierarchical`` uses the three
    switches as given; the others fix them. ``junction_merge`` turns on the P3
    junction merge rule, platoon metrics and route-mode cohesion
    (``simulation.route_formation``); off reproduces the Phase 1 behaviour.
    """
    if architecture not in ARCHITECTURES:
        raise ValueError(f"Unknown architecture '{architecture}'. Choose one of: {', '.join(ARCHITECTURES)}")
    centralized = False
    if ARCHITECTURES[architecture] is not None:
        use_overseer, use_admm, defended, centralized = ARCHITECTURES[architecture]
    base = config if config is not None else get_config()
    cfg = _route_mode_config(base)
    if spatial_index is None:
        spatial_index = bool(cfg.get("web", {}).get("spatial_index", True))
    with use_run_config(cfg):
        yield from _simulate(network, flights, duration_s, cfg, use_overseer, use_admm, defended,
                             attack_config, overseer_link_config, should_stop,
                             max(1, int(frame_every)), bool(spatial_index), bool(exact_positions),
                             centralized, bool(junction_merge) and not centralized)


def _graph_metrics(nodes: list[int], adj: dict[int, list[int]]) -> dict[str, Any]:
    """Network-theory summary of the V2V communication graph."""
    n = len(nodes)
    if n == 0:
        return {"nodes": 0, "edges": 0, "avg_degree": 0.0, "density": 0.0, "transitivity": 0.0,
                "max_degree_centrality": 0.0, "hub": None, "components": 0, "largest_component": 0.0,
                "algebraic_connectivity": 0.0, "isolated": 0}
    idx = {v: k for k, v in enumerate(nodes)}
    A = np.zeros((n, n))
    for u in nodes:
        for v in adj.get(u, []):
            if v in idx:
                A[idx[u], idx[v]] = A[idx[v], idx[u]] = 1.0
    deg = A.sum(axis=1)
    m = int(A.sum() // 2)
    triangles = float(np.trace(A @ A @ A)) / 6.0
    triples = float(np.sum(deg * (deg - 1)) / 2.0)
    # connected components
    seen, comps = set(), []
    for k in range(n):
        if k in seen:
            continue
        stack, comp = [k], []
        seen.add(k)
        while stack:
            u = stack.pop()
            comp.append(u)
            for v in np.nonzero(A[u])[0]:
                if int(v) not in seen:
                    seen.add(int(v))
                    stack.append(int(v))
        comps.append(comp)
    big = max(comps, key=len)
    lam2 = 0.0
    if len(big) > 1:
        sub = A[np.ix_(big, big)]
        L = np.diag(sub.sum(axis=1)) - sub
        lam2 = float(np.sort(np.linalg.eigvalsh(L))[1])
    hub = int(nodes[int(np.argmax(deg))]) if m else None
    return {
        "nodes": n, "edges": m, "avg_degree": round(float(deg.mean()), 3),
        "density": round(2.0 * m / (n * (n - 1)), 4) if n > 1 else 0.0,
        "transitivity": round(3.0 * triangles / triples, 4) if triples else 0.0,
        "max_degree_centrality": round(float(deg.max()) / (n - 1), 4) if n > 1 else 0.0,
        "hub": hub, "components": len(comps), "largest_component": round(len(big) / n, 4),
        "algebraic_connectivity": round(lam2, 4), "isolated": int(np.sum(deg == 0)),
    }


def _simulate(network, flights, duration_s, cfg, use_overseer, use_admm, defended,
              attack_config, overseer_link_config, should_stop, frame_every=1, spatial=True,
              exact_positions=False, centralized=False, junction_merge=False):
    dt = float(cfg["simulation"]["timestep_seconds"])
    tau_v = float(cfg["control"]["velocity_time_constant_seconds"])
    lb = cfg["local_behavior"]
    v_cruise = float(lb["v_cruise"])
    look_ahead = float(lb["look_ahead"])
    k_lat = float(lb["k_lat"])
    w_sep, w_ali = float(lb["w_sep"]), float(lb["w_ali"])
    d_0, h_gap = float(lb["d_0"]), float(lb["h"])
    v_max = float(cfg["safety"]["maximum_velocity_meters_per_second"])
    a_max = float(cfg["safety"]["maximum_acceleration_meters_per_second_squared"])
    d_min = float(cfg["safety"]["minimum_separation_meters"])
    crash_r = float(cfg["safety"].get("collision_radius_meters", CRASH_RADIUS_M))
    half_w = float(cfg["corridors"]["width_meters"]) / 2.0
    lane = half_w / 2.0  # keep-left lane offset (India drives on the left)
    layer_h = float(cfg["airspace"]["layer_height_meters"])
    num_layers = int(cfg["airspace"]["num_layers"])
    emergency_layer = int(cfg["airspace"].get("emergency_layer", num_layers - 1))
    comm = cfg.get("communication", {})
    comm_radius = float(comm.get("radius_meters", 40.0))
    grid_cell = float(cfg.get("web", {}).get("grid_cell_m", max(comm_radius, 2.0 * d_min)))
    period_steps = max(1, int(round(float(cfg["overseer"]["update_period_seconds"]) / dt)))
    attack_cfg = attack_config if attack_config is not None else cfg.get("attack", {})

    overseer = GlobalOverseer(corridors=list(range(SECTOR_COLS * SECTOR_ROWS)), config=cfg,
                              policy="priority_aware")
    link = OverseerLink(overseer_link_config if overseer_link_config is not None
                        else cfg["overseer"].get("link_failure", {}))

    by_id = {f.agent_id: f for f in flights}
    ids = [f.agent_id for f in flights]
    index_of = {i: k for k, i in enumerate(ids)}
    status = {i: QUEUED for i in ids}
    progress = {i: 0.0 for i in ids}
    agents: dict[int, AgentState] = {}
    # Semicircular rule: the requested cruise layer follows the overall course
    # (eastbound -> layer 0, westbound -> layer 1). The DTC may override it for
    # capacity; emergencies always get the reserved layer.
    preferred_layer: dict[int, int] = {}
    for f in flights:
        if f.type == AgentType.EMERGENCY:
            preferred_layer[f.agent_id] = emergency_layer
        else:
            course = f.route.point_at(f.route.length) - f.route.point_at(0.0)
            preferred_layer[f.agent_id] = 0 if course[0] >= 0 else 1
    for f in flights:
        start = f.route.point_at(0.0)
        layer = preferred_layer[f.agent_id]
        agents[f.agent_id] = AgentState(
            id=f.agent_id, type=f.type, position=np.array([start[0], start[1], float(layer)]),
            destination=np.array([*f.route.point_at(f.route.length), float(layer)]),
            priority=TYPE_PRIORITY[f.type], corridor_assignment=None, altitude_layer=layer)
    cached_layers: dict[int, int] = {}
    stats = RouteRunStats()
    held: set[int] = set()
    link_was_up = True
    attack_announced = False
    last_directive_t: float | None = None
    # episode trackers (events fire on rising/falling edges, not every tick)
    admm_open: dict[int, dict[str, Any]] = {}
    wall_open: set[int] = set()
    fence_open: set[int] = set()
    spoof_seen: set[tuple[int, int]] = set()
    los_open: set[tuple[int, int]] = set()
    shift_cooldown: dict[int, float] = {}
    n_steps = int(round(duration_s / dt))
    # Phase 2 instruments (P2 ADMM timer, P4 compliance, P3 merging, P5 W-MSR view)
    probe = ADMMProbe(int(cfg["admm"].get("maximum_iterations", 50)))
    w_coh, r_sep, r_plat = float(lb["w_coh"]), float(lb["r_sep"]), float(lb.get("r_plat", 40.0))

    def cruise_of(f_or_a) -> float:
        return min(v_max, v_cruise * TYPE_SPEED_FACTOR[f_or_a.type])

    etrack = EmergencyTracker(flights, cruise_of, emergency_layer, int(cfg["corridors"]["capacity"]), dt)
    mtrack = MergeTracker(network, flights, cfg) if junction_merge else None
    wmsr_f = int(cfg.get("resilience", {}).get("f", 1))
    last_cmd: dict[int, np.ndarray] = {}   # centralized: last DTC velocity command per drone

    for step in range(n_steps + 1):
        if should_stop and should_stop():
            return
        t = round(step * dt, 6)
        events: list[dict[str, Any]] = []

        def emit(kind: str, who: Sequence[int], text: str, scope: str = "drone") -> None:
            who = [int(w) for w in who]
            events.append({"t": t, "kind": kind, "id": who[0] if who else None, "ids": who,
                           "scope": scope, "text": text})

        # --- departures (pad must be clear: ground holding otherwise)
        dep_grid = None
        departed_now: list[int] = []
        for f in flights:
            i = f.agent_id
            if status[i] != QUEUED or t < f.depart_s:
                continue
            pad = agents[i].position[:2]
            join = f.route.points[1] if len(f.route.points) > 2 else pad
            dep_layer = cached_layers.get(i, preferred_layer[i])
            if spatial:
                if dep_grid is None:  # airborne at the start of this tick; same-tick departures checked directly
                    dep_ids = [j for j in ids if status[j] == AIRBORNE]
                    dep_grid = UniformGrid(np.array([agents[j].position[:2] for j in dep_ids]).reshape(-1, 2), grid_cell)
                near_pad = {dep_ids[k] for k in dep_grid.within(float(pad[0]), float(pad[1]), 2.0 * d_min)}
                near_join = {dep_ids[k] for k in dep_grid.within(float(join[0]), float(join[1]), MERGE_CLEARANCE_M)}
                for j in departed_now:
                    if np.linalg.norm(agents[j].position[:2] - pad) < 2.0 * d_min:
                        near_pad.add(j)
                    if np.linalg.norm(agents[j].position[:2] - join) < MERGE_CLEARANCE_M:
                        near_join.add(j)
                busy = sorted(near_pad, key=index_of.__getitem__)
                merge = sorted((j for j in near_join if agents[j].altitude_layer == dep_layer), key=index_of.__getitem__)
            else:
                busy = [j for j in ids if status[j] == AIRBORNE and np.linalg.norm(agents[j].position[:2] - pad) < 2.0 * d_min]
                # merge gap: no same-layer traffic near the junction where the approach leg joins the corridor
                merge = [j for j in ids if status[j] == AIRBORNE and agents[j].altitude_layer == dep_layer
                         and np.linalg.norm(agents[j].position[:2] - join) < MERGE_CLEARANCE_M]
            if busy or merge:
                if i not in held:
                    held.add(i)
                    stats.pad_holds += 1
                    etrack.on_hold(i)
                    why = (f"pad airspace occupied by D-{busy[0]}" if busy
                           else f"waiting for a merge gap — D-{merge[0]} near the corridor junction on L{dep_layer}")
                    emit("hold", [i], f"D-{i} ground hold at {f.origin}: {why}", "global")
                continue
            status[i] = AIRBORNE
            departed_now.append(i)
            etrack.on_depart(i, t)
            if i in cached_layers:
                agents[i].altitude_layer = cached_layers[i]
                agents[i].position[2] = float(cached_layers[i])
            emit("depart", [i], f"D-{i} {f.type.value} departs {f.origin} → {f.destination} on layer L{agents[i].altitude_layer}"
                 f" ({f.route.length / 1000:.2f} km corridor route)", "global")

        airborne = [agents[i] for i in ids if status[i] == AIRBORNE]
        dtc_assigned = 0

        # --- P4 DTC (drone traffic controller) through the possibly failing link
        if use_overseer and step % period_steps == 0 and airborne:
            stats.overseer_calls += 1
            link.calls += 1
            if not link.is_up(t):
                link.dropped += 1
                stats.overseer_dropped += 1
                if link_was_up:
                    emit("link", [a.id for a in airborne][:0], "DTC link DOWN — drones keep their last directive", "global")
                link_was_up = False
            else:
                if not link_was_up:
                    emit("link", [], "DTC link restored — directives resume", "global")
                link_was_up = True
                last_directive_t = t
                stats.dtc_directives += 1
                sectors: dict[int, list[AgentState]] = {}
                for a in airborne:
                    sid = _sector(network, a.position[0], a.position[1])
                    a.corridor_assignment = sid
                    sectors.setdefault(sid, []).append(a)
                changed = 0
                prev_corr = dict(overseer.last_corridor_map)
                prev_layer = dict(overseer.last_layer_map)
                merged_c, merged_l = {}, {}
                for a in airborne:  # first request = previous layer, else semicircular preference
                    prev_layer.setdefault(a.id, preferred_layer[a.id])
                    prev_corr[a.id] = a.corridor_assignment
                for sid, members in sectors.items():
                    overseer.last_corridor_map, overseer.last_layer_map = prev_corr, prev_layer
                    directive = overseer.update(GlobalStateSnapshot(
                        timestamp=t, corridor_occupancy={sid: len(members)},
                        agent_ids=[a.id for a in members],
                        agent_types={a.id: a.type for a in members},
                        agent_priorities={a.id: a.priority for a in members}))
                    merged_c.update(directive.corridor_map)
                    merged_l.update(directive.altitude_map)
                overseer.last_corridor_map, overseer.last_layer_map = merged_c, merged_l
                dtc_assigned = len(merged_l)
                deferred = 0
                for aid, layer in merged_l.items():
                    layer = int(np.clip(layer, 0, num_layers - 1))
                    cur = int(agents[aid].altitude_layer)
                    if cur != layer:
                        # safety gate: a directive may only move a drone into a layer
                        # that is locally clear; otherwise defer to the next update
                        if not _layer_transition_clear(agents[aid], layer, airborne, d_min):
                            deferred += 1
                            overseer.last_layer_map[aid] = cur
                            cached_layers[aid] = cur
                            etrack.on_gate(aid)
                            emit("gate", [aid], f"DTC directive L{cur}→L{layer} deferred by safety gate: target layer not clear")
                            continue
                        changed += 1
                        agents[aid].altitude_layer = layer
                        agents[aid].position[2] = float(layer)
                        emit("dtc", [aid], f"DTC directive: layer L{cur}→L{layer} (sector S{merged_c.get(aid, '?')} capacity / priority)")
                    cached_layers[aid] = layer
                stats.layer_changes_deferred += deferred
                if changed or deferred:
                    stats.layer_changes += changed
                    emit("overseer", [], f"DTC re-layered {changed} drone(s) for sector capacity/priority"
                         + (f"; {deferred} deferred by safety gate" if deferred else ""), "global")
        if step % period_steps == 0 and airborne:  # P4 compliance check at every DTC period (any architecture)
            etrack.on_dtc_update(airborne, lambda a: (_sector(network, a.position[0], a.position[1]),
                                                      int(a.altitude_layer)))

        # --- P1 communication graph among airborne drones
        if airborne:
            if comm.get("mode", "radius") == "knn":
                graph = build_knn_graph(airborne, int(comm.get("nearest_neighbors", 6)))
                adj = {a.id: list(graph.neighbors(a.id)) for a in airborne}
            elif spatial:
                adj = radius_adjacency([a.id for a in airborne],
                                       np.array([a.position[:2] for a in airborne]), comm_radius, grid_cell)
            else:
                graph = build_radius_graph(airborne, comm_radius)
                adj = {a.id: list(graph.neighbors(a.id)) for a in airborne}
        else:
            adj = {}
        by_air = {a.id: a for a in airborne}

        # --- P5 attack injection on reported positions
        attack_state = inject_attack(airborne, attack_cfg, t)
        if attack_state.falsified:
            reported = {a.id: a for a in apply_attack(airborne, attack_state)}
        else:  # no falsified report this tick: reports equal the true states (read-only below)
            reported = by_air
        if attack_state.malicious:
            stats.attack_active_ticks += 1
            for m in attack_state.malicious:
                if m not in stats.malicious_ids:
                    stats.malicious_ids.append(m)
            if not attack_announced:
                attack_announced = True
                emit("attack", list(attack_state.malicious),
                     f"Spoofing attack: {', '.join('D-%d' % m for m in attack_state.malicious)} broadcast false positions", "global")

        # --- P3 route following + boids -> desired velocity
        desired: dict[int, np.ndarray] = {}
        threat: dict[int, tuple[int, float, float]] = {}   # id -> (other, t_cpa, miss)
        corrections: dict[int, list[list[float]]] = {}    # spoofer -> receivers' corrected xy (this tick)
        trust_tick: dict[int, list[list]] = {}            # receiver -> [[neighbour, status], ...]
        leaders: dict[int, tuple[int, float, float]] = {}  # follower -> (leader, gap, speed)

        def ref_speed(a, remaining: float) -> float:
            # reference speed: cruise by mission type, brake to stop at the pad
            return min(cruise_of(a), math.sqrt(max(0.0, 2.0 * 0.6 * a_max * max(remaining - 1.0, 0.0))) + 0.3)

        if centralized and airborne:  # the DTC computes every drone's velocity from reported states
            for a in airborne:
                s_c, _, _ = by_id[a.id].route.project(a.position[:2], progress[a.id])
                progress[a.id] = max(progress[a.id], s_c)
            if link.is_up(t):
                last_cmd.update(centralized_commands(
                    reported, {a.id: by_id[a.id].route for a in airborne}, progress, ref_speed, cfg, lane, grid_cell))
            for a in airborne:
                desired[a.id] = last_cmd.get(a.id, np.zeros(3)).copy()
        for a in ([] if centralized else airborne):
            f = by_id[a.id]
            route = f.route
            p = a.position[:2].copy()
            s, q, tan = route.project(p, progress[a.id])
            progress[a.id] = max(progress[a.id], s)
            left = np.array([-tan[1], tan[0]])
            remaining = route.length - s

            nbr_ids = adj.get(a.id, [])
            true_n = [by_air[j] for j in nbr_ids if j in by_air and by_air[j].altitude_layer == a.altitude_layer]
            rep_n = [reported[j] for j in nbr_ids if j in reported and reported[j].altitude_layer == a.altitude_layer]
            if a.id in attack_state.malicious or not defended:
                nbrs = true_n if a.id in attack_state.malicious else rep_n
                if a.id not in attack_state.malicious:
                    if any(r.id in attack_state.falsified for r in rep_n):
                        trust_tick[a.id] = [[int(r.id), "accepted" if r.id in attack_state.falsified else "kept"]
                                            for r in rep_n]
                    for r in rep_n:
                        if r.id in attack_state.falsified:
                            stats.spoofed_reports_accepted += 1
                            if (a.id, r.id) not in spoof_seen:
                                spoof_seen.add((a.id, r.id))
                                emit("spoof", [a.id, r.id], f"Accepted spoofed position from D-{r.id} (defence OFF) — separation acts on false data")
            else:
                res = defend_neighbor_reports(a, rep_n, true_n)
                nbrs = res.kept
                stats.reports_dropped += len(res.dropped_ids)
                if res.dropped_ids or any(r.id in attack_state.malicious for r in rep_n):
                    trust_tick[a.id] = report_status([r.id for r in rep_n], res.dropped_ids, [x.id for x in true_n])
                    for k_ in res.kept:
                        if k_.id in res.dropped_ids:
                            corrections.setdefault(int(k_.id), []).append([float(k_.position[0]), float(k_.position[1])])
                for rid in res.dropped_ids:
                    if (a.id, rid) not in spoof_seen:
                        spoof_seen.add((a.id, rid))
                        emit("defend", [a.id, rid], f"Defence flagged D-{rid}'s report: range mismatch → position corrected (W-MSR)")

            v_ref = ref_speed(a, remaining)
            # car-following along the corridor (gap = d_0 + h * v)
            lead = None
            for nb in nbrs:
                rel = nb.position[:2] - p
                along = float(rel @ tan)
                if along <= 0.0 or abs(float(rel @ left)) > half_w:
                    continue
                if float(np.asarray(nb.velocity[:2]) @ tan) < 0.0:
                    continue  # opposing flow is handled by the lane offset + separation
                v_ref = min(v_ref, max(0.0, (along - d_0) / h_gap))
                if along <= r_plat and (lead is None or along < lead[1]):
                    lead = (int(nb.id), along)
            if mtrack is not None:
                if lead is not None:
                    leaders[a.id] = (lead[0], lead[1], float(np.linalg.norm(a.velocity[:2])))
                fac, why = mtrack.factor(a.id, s, int(a.altitude_layer), nbrs)
                v_ref *= fac
                if why:
                    emit("merge", [a.id], why)

            fade = min(1.0, remaining / 30.0)  # lane offset merges back to the pad
            look = min(route.length, s + look_ahead)
            t_look = route.tangent_at(look)
            q_look = route.point_at(look) + np.array([-t_look[1], t_look[0]]) * lane * fade
            to_q = q_look - p
            dist_q = float(np.linalg.norm(to_q))
            v_goal = (to_q / dist_q) * v_ref if dist_q > 1e-6 else np.zeros(2)
            e = float((p - q) @ left)
            v_goal = v_goal + left * (-k_lat * (e - lane * fade))

            # tactical closest-point-of-approach avoidance (crossing / head-on traffic)
            v_avoid = np.zeros(2)
            own_v = a.velocity[:2]
            for nb in nbrs:
                r = nb.position[:2] - p
                vrel = np.asarray(nb.velocity[:2]) - own_v
                vv = float(vrel @ vrel)
                if vv < 1e-6:
                    continue
                t_cpa = -float(r @ vrel) / vv
                if not 0.0 < t_cpa < 8.0:
                    continue
                miss_vec = r + vrel * t_cpa  # neighbour relative to me at CPA
                miss = float(np.linalg.norm(miss_vec))
                need = 1.6 * d_min
                if miss >= need:
                    continue
                if miss < d_min and t_cpa < 3.0 and (a.id not in threat or t_cpa < threat[a.id][1]):
                    threat[a.id] = (nb.id, t_cpa, miss)
                away = -miss_vec / miss if miss > 1e-3 else left
                urgency = 2.0 * (need - miss) / max(t_cpa, 0.5)
                v_avoid += away * min(urgency, 6.0)
                if float(r @ tan) > 0:  # threat ahead: shed speed as well
                    v_ref = min(v_ref, max(2.0, v_ref * min(1.0, t_cpa / 6.0)))
            if v_ref < float(np.linalg.norm(v_goal)) and float(np.linalg.norm(v_goal)) > 1e-6:
                v_goal = v_goal / float(np.linalg.norm(v_goal)) * v_ref

            if mtrack is None:
                v = v_goal + v_avoid + w_sep * separation(a, nbrs) + w_ali * 0.5 * alignment(
                    a, [nb for nb in nbrs if float(np.asarray(nb.velocity[:2]) @ tan) > 0.0])
            else:
                # P3 within a road segment: alignment and cohesion use only same-direction drones
                # inside this drone's tube; cohesion is along the road (route-mode boids.cohesion:
                # mean along-track offset, zero when any segment mate is closer than r_sep or than
                # the car-following gap d_0 + h*v, so cohesion never pulls a drone inside its headway)
                seg = [nb for nb in nbrs if float(np.asarray(nb.velocity[:2]) @ tan) > 0.0
                       and abs(float((nb.position[:2] - p) @ left)) <= half_w]
                v_coh = np.zeros(2)
                too_close = max(r_sep, d_0 + h_gap * float(np.linalg.norm(a.velocity[:2])))
                if seg and all(float(np.linalg.norm(nb.position[:2] - p)) >= too_close for nb in seg):
                    v_coh = tan * float(np.mean([float((nb.position[:2] - p) @ tan) for nb in seg]))
                v = (v_goal + v_avoid + w_sep * separation(a, nbrs) + w_ali * 0.5 * alignment(a, seg)
                     + w_coh * v_coh)
            sp = float(np.linalg.norm(v))
            if sp > v_max:
                v *= v_max / sp
            desired[a.id] = np.array([v[0], v[1], 0.0])

        # --- P2 ADMM conflict resolution on intents
        in_admm: dict[int, tuple[list[int], bool]] = {}
        if use_admm and airborne:
            intents = []
            for a in airborne:
                it = copy.copy(a)
                it.velocity = desired[a.id].copy()
                intents.append(it)
            for ev in probe.resolve(intents, {a.id: a.priority for a in airborne}, t):
                stats.admm_events += 1
                if ev.converged:
                    for aid, vel in ev.resolution.items():
                        desired[aid] = np.asarray(vel, float)
                else:
                    stats.admm_nonconverged += 1
                for aid in ev.agents_involved:
                    in_admm[aid] = ([x for x in ev.agents_involved if x != aid], bool(ev.converged))
        for aid, (partners, ok) in in_admm.items():
            if aid not in admm_open:
                admm_open[aid] = {"t0": t, "partners": set(partners), "failed": 0}
                neg = probe.last.get(aid, {})
                how = (f" ({neg['it']} iterations, {'converged' if neg['ok'] else 'not converged → fallback'})"
                       if neg.get("it") is not None else "")
                emit("admm", [aid] + partners[:3], f"ADMM conflict detected with {', '.join('D-%d' % x for x in partners[:4])} — negotiating velocities{how}")
            else:
                admm_open[aid]["partners"].update(partners)
            if not ok:
                admm_open[aid]["failed"] += 1
        for aid in [x for x in admm_open if x not in in_admm]:
            ep = admm_open.pop(aid)
            if status.get(aid) == AIRBORNE:
                emit("admm_ok", [aid], f"ADMM conflict resolved in {t - ep['t0']:.1f} s with "
                     f"{', '.join('D-%d' % x for x in sorted(ep['partners'])[:4])}"
                     + (f" ({ep['failed']} non-converged ticks → boids fallback)" if ep["failed"] else ""))

        # --- tactical altitude shift: imminent loss of separation in-plane
        shifted: set[int] = set()
        for aid, (other, t_cpa, miss) in sorted(threat.items(), key=lambda kv: kv[1][1]):
            if aid in shifted or other in shifted or other not in by_air:
                continue
            a, b = by_air[aid], by_air[other]
            # the lower-priority drone yields (larger number = lower priority); tie -> larger id
            mover = a if (a.priority, a.id) > (b.priority, b.id) else b
            if shift_cooldown.get(mover.id, -1e9) > t:
                mover = b if mover is a else a
                if shift_cooldown.get(mover.id, -1e9) > t:
                    continue
            cur = int(mover.altitude_layer)
            options = [cur + 1, cur - 1]
            if mover.type != AgentType.EMERGENCY:
                options = [L for L in options if L != emergency_layer]
            for L in options:
                if 0 <= L < num_layers and _layer_transition_clear(mover, L, airborne, d_min, horizon_s=6.0):
                    mover.altitude_layer = L
                    mover.position[2] = float(L)
                    overseer.last_layer_map[mover.id] = L
                    cached_layers[mover.id] = L
                    shift_cooldown[mover.id] = t + 6.0
                    shifted.update({a.id, b.id})
                    stats.tactical_layer_shifts += 1
                    etrack.on_shift(mover.id)
                    peer = b.id if mover is a else a.id
                    cause = "ADMM conflict not separable in-plane" if mover.id in in_admm else "CPA alert"
                    verb = "climb" if L > cur else "descend"
                    emit("shift", [mover.id, peer], f"{cause}: {verb} L{cur}→L{L} to avoid D-{peer} "
                         f"(predicted miss {miss:.1f} m in {t_cpa:.1f} s)")
                    emit("shift_peer", [peer, mover.id], f"D-{mover.id} shifted L{cur}→L{L} to clear conflict with this drone")
                    break

        # --- P1 dynamics + boundary conditions (corridor tube + geofence)
        for a in airborne:
            accel = (desired[a.id] - a.velocity) / tau_v
            nxt = step_dynamics(a, accel, dt)
            f = by_id[a.id]
            p = nxt.position[:2]
            s, q, tan = f.route.project(p, progress[a.id])
            left = np.array([-tan[1], tan[0]])
            e = float((p - q) @ left)
            stats.max_lateral_error_m = max(stats.max_lateral_error_m, abs(e))
            if abs(e) > half_w:
                wall = left * math.copysign(1.0, e)
                p = q + wall * half_w
                outward = float(nxt.velocity[:2] @ wall)
                if outward > 0:
                    nxt.velocity[:2] -= outward * wall
                stats.tube_corrections += 1
                if a.id not in wall_open:
                    wall_open.add(a.id)
                    emit("wall", [a.id], f"Corridor boundary: lateral {abs(e):.1f} m > {half_w:.0f} m → held on tube wall")
            elif abs(e) < half_w - 2.0:  # hysteresis: episode ends once clearly back inside
                wall_open.discard(a.id)
            cx, cy, fenced = network.clamp(float(p[0]), float(p[1]))
            if fenced:
                stats.geofence_corrections += 1
                nxt.velocity[:2] *= 0.0
                if a.id not in fence_open:
                    fence_open.add(a.id)
                    emit("fence", [a.id], "Geofence: position outside campus boundary → projected back inside")
            else:
                fence_open.discard(a.id)
            nxt.position[0], nxt.position[1] = cx, cy
            agents[a.id] = nxt
            remaining = f.route.length - max(progress[a.id], s)
            # final approach: within 10 m of the pad the drone descends vertically
            # out of the cruise layer (pads sit below the layered airspace)
            if remaining < 10.0 and float(np.linalg.norm(nxt.velocity[:2])) < 6.0:
                status[a.id] = LANDED
                nxt.velocity[:] = 0.0
                stats.arrivals += 1
                etrack.on_land(a.id, t)
                if mtrack is not None:
                    mtrack.drop(a.id)
                emit("land", [a.id], f"D-{a.id} landed at {f.destination}", "global")

        # --- P6 safety: loss of separation, crashes, layer-aware STL robustness
        air_ids = [i for i in ids if status[i] == AIRBORNE]
        if len(air_ids) >= 2:
            xy = np.array([agents[i].position[:2] for i in air_ids])
            lay = np.array([agents[i].altitude_layer for i in air_ids])
            if spatial:
                dmin_now = layered_min_separation_grid(xy, lay, layer_h, grid_cell, layered_min_separation)
                close = close_same_layer_pairs(xy, lay, max(d_min, crash_r), grid_cell)
            else:
                dmin_now = layered_min_separation(xy, lay, layer_h)
                diff = xy[:, None, :] - xy[None, :, :]
                dist = np.sqrt(np.einsum("ijk,ijk->ij", diff, diff))
                same = lay[:, None] == lay[None, :]
                close = [(int(u), int(v), float(dist[u, v]))
                         for u, v in np.argwhere(np.triu(same & (dist < max(d_min, crash_r)), 1))]
            now_pairs = set()
            for u, v, d in close:
                pa, pb = air_ids[u], air_ids[v]
                pair = (pa, pb)
                now_pairs.add(pair)
                if d < crash_r and status[pa] == AIRBORNE and status[pb] == AIRBORNE:
                    status[pa] = status[pb] = CRASHED
                    agents[pa].velocity[:] = 0.0
                    agents[pb].velocity[:] = 0.0
                    stats.crashes += 1
                    stats.crashed_drones += 2
                    if mtrack is not None:
                        mtrack.drop(pa)
                        mtrack.drop(pb)
                    emit("crash", [pa, pb], f"CRASH: D-{pa} × D-{pb} collided on L{int(lay[u])} at "
                         f"({agents[pa].position[0]:.0f}, {agents[pa].position[1]:.0f}) — both drones lost", "global")
                elif d < d_min and pair not in los_open:
                    stats.near_misses += 1
                    if mtrack is not None:
                        mtrack.on_los((pa, pb))
                    emit("los", [pa, pb], f"Loss of separation: D-{pa} ↔ D-{pb} at {d:.1f} m < {d_min:.0f} m on L{int(lay[u])}", "global")
            los_open.intersection_update(now_pairs)
            los_open.update(now_pairs)
        else:
            dmin_now = math.inf
        rho = dmin_now - d_min
        if rho < 0:
            stats.safety_violation_ticks += 1
        stats.min_separation_m = min(stats.min_separation_m, dmin_now)
        etrack.on_tick(agents[i] for i in air_ids)

        if step % frame_every and step != n_steps:
            yield {"t": t, "k": step, "partial": True, "events": events, "stats": stats.to_dict()}
            continue

        # --- network theory of the whole system (V2V graph + DTC hub)
        live = [i for i in ids if status[i] == AIRBORNE]
        net = _graph_metrics(live, adj)
        edges = sorted({(min(index_of[u], index_of[v]), max(index_of[u], index_of[v]))
                        for u, vs in adj.items() for v in vs if u in index_of and v in index_of
                        and status[u] == AIRBORNE and status[v] == AIRBORNE})
        link_up_now = use_overseer and link.is_up(t)
        dtc = {
            "enabled": bool(use_overseer), "link_up": bool(link_up_now),
            "connected": len(live) if link_up_now else 0,
            "staleness_s": None if last_directive_t is None else round(t - last_directive_t, 2),
            "assigned": dtc_assigned, "directives": stats.dtc_directives,
            "layer_changes": stats.layer_changes, "deferred": stats.layer_changes_deferred,
        }

        frame = {
            "t": t,
            "k": step,
            "x": [round(float(agents[i].position[0]), 2) for i in ids],
            "y": [round(float(agents[i].position[1]), 2) for i in ids],
            "layer": [int(agents[i].altitude_layer) for i in ids],
            "speed": [round(float(np.linalg.norm(agents[i].velocity[:2])), 2) for i in ids],
            "status": [status[i] for i in ids],
            "progress": [round(min(1.0, progress[i] / by_id[i].route.length), 4) for i in ids],
            "rho": None if not math.isfinite(rho) else round(rho, 3),
            "link_up": link.is_up(t),
            "attack": bool(attack_state.malicious),
            "edges": [list(e) for e in edges],
            "net": net,
            "dtc": dtc,
            "events": events,
            "stats": stats.to_dict(),
            **probe.frame(),                     # "admm" (window + run p95) and "neg" (last negotiation per drone)
            "prio": etrack.snapshot(t),
            "merge": (dict(mtrack.frame(), **platoon_stats(leaders, d_0, h_gap)) if mtrack is not None else None),
            "spoof": _spoof_view(attack_state.malicious, by_air, reported, corrections, wmsr_f),
            "trust": {str(k): v for k, v in trust_tick.items()},
        }
        if exact_positions:
            frame["pos"] = [[float(agents[i].position[0]), float(agents[i].position[1]),
                             float(agents[i].position[2])] for i in ids]
        yield frame


def _spoof_view(malicious, by_air, reported, corrections, f) -> dict[str, Any]:
    """Per airborne spoofer: reported, true and W-MSR-estimated position (pre-dynamics, this tick)."""
    out: dict[str, Any] = {}
    for m in malicious:
        if m not in by_air:
            continue
        true = by_air[m].position[:2]
        rep = (reported[m] if m in reported else by_air[m]).position[:2]
        corr = corrections.get(m, [])
        est = estimate_spoofer_position(corr, f)
        out[str(m)] = {
            "rep": [round(float(rep[0]), 1), round(float(rep[1]), 1)],
            "true": [round(float(true[0]), 1), round(float(true[1]), 1)],
            "est": None if est is None else [round(float(est[0]), 1), round(float(est[1]), 1)],
            "n": len(corr),
            "err_rep": round(float(np.linalg.norm(rep - true)), 1),
            "err_est": None if est is None else round(float(np.linalg.norm(est - true)), 1),
        }
    return out


def initial_conditions_hash(flights: Sequence[Flight], seed: int | None = None) -> str:
    """Short hash of the planned flights (ids, types, routes, departures): equal across architectures."""
    import hashlib
    import json
    payload = {"seed": seed, "flights": flight_manifest(flights)}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:12]


def flight_manifest(flights: Sequence[Flight]) -> list[dict[str, Any]]:
    return [{
        "id": f.agent_id, "type": f.type.value, "task": f.task, "priority": TYPE_PRIORITY[f.type],
        "origin": f.origin, "destination": f.destination, "depart_s": f.depart_s,
        "route_length_m": round(f.route.length, 1),
        "route": [[round(float(x), 2), round(float(y), 2)] for x, y in f.route.points],
    } for f in flights]
