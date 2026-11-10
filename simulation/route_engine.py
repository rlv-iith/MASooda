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
from typing import Any, Callable, Iterable, Iterator, Sequence

import numpy as np

from config.load_config import get_config, use_run_config
from local_behavior.boids import alignment, separation
from resilience.attack import apply_attack, inject_attack
from resilience.defense import defend_neighbor_reports
from resilience.spoofer_estimate import estimate_spoofer_position, report_status
from simulation.admm_probe import ADMMProbe
from simulation.comm_graph import build_knn_graph, build_radius_graph
from simulation.drone_health import CRITICAL, FAULT, STATUS_NAMES, WARNING, HealthModel
from simulation.layer_agreement import LayerAgreement, RoundContext, departure_layer, settings as agreement_settings
from simulation.dtc_console import COMMANDS, plan_route, points_in_polygon, route_hits_zones
from simulation.dynamics import step_dynamics
from simulation.overseer import GlobalOverseer
from simulation.overseer_link import OverseerLink
from simulation.road_network import RoadNetwork, RoutePath
from simulation.route_centralized import centralized_commands
from simulation.route_formation import MergeTracker, platoon_stats
from simulation.route_priority import EmergencyTracker
from simulation.schema import AgentState, AgentType, AttackState, GlobalStateSnapshot
from simulation.spatial_grid import (
    UniformGrid, close_same_layer_pairs, layered_min_separation_grid, radius_adjacency,
)

QUEUED, AIRBORNE, LANDED, CRASHED, FORCED = 0, 1, 2, 3, 4   # FORCED: landed in place (health)
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
    # custom drone input (Phase 3); None = the type default
    priority: int | None = None
    cruise_speed: float | None = None
    preferred_layer: int | None = None
    cooperative: bool = True              # broadcasts Remote-ID-style position reports
    spoof_offset: tuple[float, float] | None = None   # malicious: false-position offset (m)
    spoof_start_s: float | None = None
    health: dict[str, Any] | None = None  # Phase 3B inputs (battery_wh, soc_init_pct, soh_pct, payload_kg, fault)
    custom: bool = False

    @property
    def eff_priority(self) -> int:
        return TYPE_PRIORITY[self.type] if self.priority is None else int(self.priority)


TASKS = {AgentType.EMERGENCY: "medical response", AgentType.EVTOL: "passenger transport",
         AgentType.DELIVERY: "parcel delivery"}


def flight_from_row(network: RoadNetwork, row: dict[str, Any], depart_s: float | None = None) -> Flight:
    """Flight from one validated custom-drone row (``scenario_manifest.validate_route_drones``)."""
    o, d = network.vertiport(row["origin"]), network.vertiport(row["destination"])
    typ = AgentType(row["type"])
    return Flight(
        agent_id=int(row["id"]), type=typ, origin=o.id, destination=d.id,
        route=RoutePath(network.vertiport_route(o, d)),
        depart_s=round(float(row["depart_s"] if depart_s is None else depart_s), 1), task=TASKS[typ] + " (custom)",
        priority=row.get("priority"), cruise_speed=row.get("cruise_speed_mps"),
        preferred_layer=row.get("preferred_layer"), cooperative=bool(row.get("cooperative", True)),
        spoof_offset=tuple(row["spoof_offset_m"]) if row.get("malicious") else None,
        spoof_start_s=row.get("spoof_start_s"),
        health={k: row.get(k) for k in ("battery_wh", "soc_init_pct", "soh_pct", "payload_kg", "fault")},
        custom=True)


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
    tasks = TASKS
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
    # layer agreement (simulation/layer_agreement.py)
    agree_switches: int = 0            # layer changes agreed between drones over V2V
    agree_yields: int = 0              # a neighbour with a larger gain took the layer first
    stuck_requests: int = 0            # stuck drones that asked the DTC for a layer
    dtc_stuck_resolved: int = 0
    dtc_stuck_denied: int = 0
    departures_spread: int = 0         # departures above the lowest layer of their direction
    # Phase 3B health
    delivered: int = 0                 # landed at the planned destination
    diversions: int = 0
    forced_landings: int = 0           # landed in place, off any pad
    precautionary_landings: int = 0    # operator-ordered landings at a pad (Ground now / fleet ground)
    pads_held_short: int = 0           # arrivals that held short of a pad reserved for a more urgent landing
    energy_depleted: int = 0           # must stay 0 in a correct run
    grounded_preflight: int = 0        # failed the pre-flight BMS / energy check, never took off
    intruder_detections: int = 0       # drone pairs where onboard sensing found a non-cooperative drone
    missions: int = 0                  # sorties started after the first (repeated operations)
    services: int = 0                  # battery swaps / charges completed
    service_queue_max: int = 0
    service_wait_s: float = 0.0        # total time drones waited for a service slot
    energy_used_wh: float = 0.0        # all drones, drawn from the cells
    energy_per_delivered_wh: float | None = None   # parcel deliveries (DELIVERY drones) only
    energy_per_delivered_by_type_wh: dict[str, float] = field(default_factory=dict)   # mean per mission type
    max_pack_c: float | None = None
    max_motor_c: float | None = None
    bms_alerts: int = 0                # status rises to WARNING or worse
    bms_by_status: list[int] = field(default_factory=lambda: [0, 0, 0, 0])   # airborne drones now
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
    command_source: Callable[[int, float], list[dict[str, Any]]] | None = None,
    seed: int | None = None,
    health_detail_ids: Callable[[], Iterable[int]] | None = None,
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

    ``command_source(k, t)`` is called at the start of every tick and returns the
    operator commands to apply at tick ``k`` (Phase 3: ``add_drone``). Each command
    dict is updated in place with ``tick_applied``, ``t_applied``, ``status`` and
    ``outcome``; replaying the same commands at the same ticks reproduces the run.

    Phase 3B: with ``drone_health.enabled`` every drone carries the health model of
    ``simulation.drone_health`` (seeded by ``seed``); frames gain ``h`` (compact health
    for all drones, once per simulated second), ``hsel`` (full detail for the ids
    returned by ``health_detail_ids()``) and ``reroutes`` (diversions).
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
                             centralized, bool(junction_merge) and not centralized, command_source,
                             int(cfg["simulation"].get("random_seed", 42) if seed is None else seed),
                             health_detail_ids)


def _graph_metrics(nodes: list[int], adj: dict[int, list[int]]) -> dict[str, Any]:
    """Network-theory summary of the V2V communication graph."""
    n = len(nodes)
    if n == 0:
        return {"nodes": 0, "edges": 0, "avg_degree": 0.0, "density": 0.0, "transitivity": 0.0,
                "max_degree_centrality": 0.0, "hub": None, "components": 0, "largest_component": 0.0,
                "algebraic_connectivity": 0.0, "algebraic_connectivity_giant": 0.0, "isolated": 0}
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
    lam2_big = 0.0
    if len(big) > 1:
        sub = A[np.ix_(big, big)]
        L = np.diag(sub.sum(axis=1)) - sub
        lam2_big = float(np.sort(np.linalg.eigvalsh(L))[1])
    lam2 = lam2_big if len(comps) == 1 else 0.0   # Fiedler value: 0 for any disconnected graph
    hub = int(nodes[int(np.argmax(deg))]) if m else None
    return {
        "nodes": n, "edges": m, "avg_degree": round(float(deg.mean()), 3),
        "density": round(2.0 * m / (n * (n - 1)), 4) if n > 1 else 0.0,
        "transitivity": round(3.0 * triangles / triples, 4) if triples else 0.0,
        "max_degree_centrality": round(float(deg.max()) / (n - 1), 4) if n > 1 else 0.0,
        "hub": hub, "components": len(comps), "largest_component": round(len(big) / n, 4),
        "algebraic_connectivity": round(lam2, 4), "algebraic_connectivity_giant": round(lam2_big, 4),
        "isolated": int(np.sum(deg == 0)),
    }


def _simulate(network, flights, duration_s, cfg, use_overseer, use_admm, defended,
              attack_config, overseer_link_config, should_stop, frame_every=1, spatial=True,
              exact_positions=False, centralized=False, junction_merge=False, command_source=None,
              seed=42, health_detail_ids=None):
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

    flights = [copy.copy(f) for f in flights]   # diversions replace a flight's route: never touch the caller's
    by_id: dict[int, Flight] = {}
    ids: list[int] = []
    index_of: dict[int, int] = {}
    status: dict[int, int] = {}
    progress: dict[int, float] = {}
    agents: dict[int, AgentState] = {}
    preferred_layer: dict[int, int] = {}
    direction_of: dict[int, int] = {}      # semicircular rule: 0 eastbound (even layers), 1 westbound (odd)
    noncoop: set[int] = set()              # drones that do not broadcast position reports
    spoof_custom: dict[int, tuple[np.ndarray, float]] = {}   # custom spoofer -> (offset, start s)

    def register(f: Flight) -> None:
        """Add one flight to the run state (initial fleet and mid-run injections)."""
        i = f.agent_id
        by_id[i] = f
        index_of[i] = len(ids)
        ids.append(i)
        status[i] = QUEUED
        progress[i] = 0.0
        # Semicircular rule: the cruise layer follows the overall course (eastbound -> even
        # layers L0/L2/L4, westbound -> odd L1/L3/L5). The drone starts on the lowest one; the
        # departure check, the V2V layer agreement and the DTC spread traffic over the rest.
        # Emergencies always get the reserved layer. A custom drone may request a layer.
        course = f.route.point_at(f.route.length) - f.route.point_at(0.0)
        direction_of[i] = 0 if course[0] >= 0 else 1
        if f.preferred_layer is not None:
            preferred_layer[i] = int(f.preferred_layer)
        elif f.type == AgentType.EMERGENCY:
            preferred_layer[i] = emergency_layer
        else:
            preferred_layer[i] = direction_of[i]
        start = f.route.point_at(0.0)
        layer = preferred_layer[i]
        agents[i] = AgentState(
            id=i, type=f.type, position=np.array([start[0], start[1], float(layer)]),
            destination=np.array([*f.route.point_at(f.route.length), float(layer)]),
            priority=f.eff_priority, corridor_assignment=None, altitude_layer=layer)
        if not f.cooperative:
            noncoop.add(i)
        if f.spoof_offset is not None:
            spoof_custom[i] = (np.array([f.spoof_offset[0], f.spoof_offset[1], 0.0]),
                               float(f.depart_s if f.spoof_start_s is None else f.spoof_start_s))
        if health is not None:
            health.add(i, f.type.value, f.health, f.custom)
        planned_dest[i] = f.destination

    hcfg = cfg.get("drone_health", {}) or {}
    health = None
    hresp: dict[str, Any] = {}
    if hcfg.get("enabled", False):
        xmin, ymin, xmax, ymax = network.bounds
        health = HealthModel(cfg, seed, ((xmin + xmax) / 2.0, (ymin + ymax) / 2.0))
        hresp = hcfg["responses"]
        bms_every = max(1, int(round(float(hcfg["bms_period_s"]) / dt)))
        resp_every = max(1, int(round(float(hresp["check_period_s"]) / dt)))
    planned_dest: dict[int, str] = {}

    for f in flights:
        register(f)
    cached_layers: dict[int, int] = {}
    stats = RouteRunStats()
    la_cfg = agreement_settings(cfg)
    capacity = int(cfg["corridors"]["capacity"])
    agree = (LayerAgreement(num_layers, emergency_layer, layer_h, d_min, d_0, h_gap, half_w, capacity, la_cfg)
             if la_cfg["enabled"] and not centralized else None)
    agree_steps = max(1, int(round(float(la_cfg["period_s"]) / dt)))
    held: set[int] = set()
    link_was_up = True
    announced_spoofers: set[int] = set()
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

    def cruise_of(f_or_a) -> float:  # flight or agent; a custom drone may set its own cruise speed
        f = by_id[getattr(f_or_a, "agent_id", getattr(f_or_a, "id", None))]
        return min(v_max, f.cruise_speed if f.cruise_speed is not None else v_cruise * TYPE_SPEED_FACTOR[f.type])

    etrack = EmergencyTracker(flights, cruise_of, emergency_layer, int(cfg["corridors"]["capacity"]), dt)
    mtrack = MergeTracker(network, flights, cfg) if junction_merge else None
    wmsr_f = int(cfg.get("resilience", {}).get("f", 1))
    last_cmd: dict[int, np.ndarray] = {}   # centralized: last DTC velocity command per drone
    new_flights: list[Flight] = []          # injected since the last full frame
    # Phase 3B state
    diverting: dict[int, str] = {}          # drone -> pad it is now flying to because of health
    reserved_pads: dict[str, int] = {}      # pad -> most urgent drone landing there (others hold, departures held)
    res_announced: set[tuple[int, str]] = set()
    holding_short: dict[int, str] = {}      # drone -> pad it is holding short of (reserved for someone else)
    health_w: dict[int, float] = {}         # drone -> continuous ADMM weight from its energy margin
    hw_cfg = (cfg.get("admm", {}) or {}).get("health_weight", {}) or {}
    pw_cfg = (cfg.get("admm", {}) or {}).get("priority_weights", {0: 10.0, 1: 3.0, 2: 1.0})

    def _class_w(p: int) -> float:
        return float(pw_cfg.get(p, pw_cfg.get(str(p), 1.0)))
    pad_res_seen: set[tuple[int, str]] = set()
    preflight_ok: set[int] = set()
    preflight_fail: set[int] = set()
    unhealthy: set[int] = set()             # cooperative drones at BMS CRITICAL/FAULT (DTC right of way)
    overheat_s: dict[int, float] = {}
    reroutes: list[dict[str, Any]] = []
    delivered_energy: list[tuple[str, float]] = []   # (mission type, Wh) per delivered mission
    last_layer: dict[int, int] = {}
    last_h_step = -1
    h_every = max(1, int(round(1.0 / dt)))

    def _rank(x) -> tuple:
        """Who yields in a tactical shift (larger rank moves): priority, then a medical emergency keeps
        its order, then between unhealthy drones the lower SoC goes first, then id."""
        soc = health.soc_bms(x.id) if (health is not None and x.id in unhealthy) else 1.0
        return (x.priority, 0 if x.type == AgentType.EMERGENCY else 1, soc, x.id)

    def _land_in_place(i: int, why: str, emit) -> None:
        status[i] = FORCED
        agents[i].velocity[:] = 0.0
        stats.forced_landings += 1
        diverting.pop(i, None)
        if mtrack is not None:
            mtrack.drop(i)
        emit("forced", [i], f"D-{i} FORCED LANDING in place: {why}", "global", "critical")

    def _active_zones() -> list:
        return [z["polygon"] for z in tfrs if z["active"]]

    zone_planned: dict[int, int] = {}   # drone -> zone version its route was planned against
    zone_version = [0]

    def _pad_options(i: int, pads=None) -> list[tuple[float, str, RoutePath]]:
        """Routes from drone i to every pad (avoiding active restricted areas), nearest first."""
        pos = agents[i].position[:2].copy()
        zones = _active_zones()
        out = []
        for v in network.vertiports:
            if pads is not None and v.id not in pads:
                continue
            pad_xy = np.asarray(v.position, dtype=float)
            if zones and any(points_in_polygon(pad_xy[None, :], z)[0] for z in zones):
                continue
            route = plan_route(network, pos, pad_xy, v.node, zones, direct_within_m=look_ahead)
            if route is not None:
                out.append((route.length, v.id, route))
        out.sort(key=lambda o: (o[0], o[1]))
        return out

    def _energy_check(i: int, length_m: float, speed: float | None = None) -> tuple[bool, float, float]:
        """(feasible with the reserve margin, energy needed Wh, energy left Wh); always True without health."""
        if health is None or i not in health.index:
            return True, 0.0, math.inf
        ok, need, e_rem, _ = health.feasible(i, length_m, speed or cruise_of(by_id[i]))
        return ok, need, e_rem

    def _nearest_reachable(i: int) -> tuple[float, str, RoutePath] | None:
        for opt in _pad_options(i):
            if _energy_check(i, opt[0])[0]:
                return opt
        return None

    def _set_route(i: int, route: RoutePath, dest: str, why: str, kind: str, severity: str | None,
                   count_diversion: bool = False) -> None:
        f = by_id[i]
        f.route, f.destination = route, dest
        progress[i] = 0.0
        stuck.pop(i, None)          # progress restarts on the new route: not "no progress"
        holding_short.pop(i, None)
        agents[i].destination = np.array([*route.point_at(route.length), agents[i].position[2]])
        if mtrack is not None:
            mtrack.drop(i)
            mtrack.add(network, f)
        if count_diversion:
            stats.diversions += 1
        reroutes.append({"id": i, "destination": dest, "reason": why, "route_length_m": round(route.length, 1),
                         "route": [[round(float(x), 2), round(float(y), 2)] for x, y in route.points]})

    def _divert(i: int, why: str, emit, severity: str) -> bool:
        """Fly to the nearest pad (by corridor route, avoiding restricted areas) that the energy can reach."""
        f = by_id[i]
        e_rem, cruise = health.e_rem_bms_wh(i), cruise_of(f)
        opts = _pad_options(i)   # a pad reserved for another urgent landing, or a hospital pad, as a last resort
        hospital = {v.id for v in network.vertiports if v.role == "hospital"}
        medical = f.type == AgentType.EMERGENCY
        opts.sort(key=lambda o: (reserved_pads.get(o[1], i) != i, o[1] in hospital and not medical, o[0], o[1]))
        # first choice: energy and voltage margin; fallback: energy only (fly gently, still better than
        # landing off-pad)
        ok_full = {vid for length, vid, _ in opts if health.feasible(i, length, cruise)[0]}
        if not ok_full:
            ok_full = {vid for length, vid, _ in opts if health.feasible(i, length, cruise, check_sag=False)[0]}
        for length, vid, route in opts:
            if vid in ok_full:
                if vid == f.destination and f.route.length - progress[i] <= length + 20.0:   # current route is fine
                    diverting[i] = vid
                    emit("divert", [i], f"D-{i} {why}: continuing to {vid} (nearest reachable pad, "
                         f"{length:.0f} m, {e_rem:.0f} Wh left)", "global", severity)
                    return True
                _set_route(i, route, vid, why, "divert", severity, count_diversion=True)
                diverting[i] = vid
                emit("divert", [i], f"D-{i} {why}: DIVERTING to {vid} ({length:.0f} m, needs "
                     f"{health.energy_needed_wh(i, length, cruise):.0f} of {e_rem:.0f} Wh)", "global", severity)
                return True
        _land_in_place(i, f"{why}; no pad reachable with {e_rem:.0f} Wh", emit)
        return False

    pad_hold_m = float((hresp or {}).get("pad_hold_m", 60.0))
    pad_reserve_radius_m = float((hresp or {}).get("pad_reserve_radius_m", 150.0))

    def _endurance_s(i: int) -> float:
        """Seconds the drone could still hover on its usable energy; a BMS CRITICAL/FAULT pack may fail
        any time, so its endurance is capped at ``responses.critical_endurance_s``."""
        p_hover = max(1.0, float(health.power(np.array([health.index[i]]), np.array([0.0]))[0][0]))
        e = health.e_rem_bms_wh(i) * 3600.0 / p_hover
        if health.status(i) >= CRITICAL:
            e = min(e, float(hresp.get("critical_endurance_s", 120.0)))
        return e

    def _urgency_label(i: int) -> str:
        if health is None:
            return "urgent"
        st = health.status(i)
        return f"BMS {STATUS_NAMES[st]}" if st >= CRITICAL else "low reserve"

    def _reservation_active(pad: str) -> bool:
        """A reservation holds the pad only once its drone is within ``pad_reserve_radius_m`` (route
        distance) of it, so a far-away diversion does not block departures for minutes."""
        h = reserved_pads.get(pad)
        if h is None or status.get(h) != AIRBORNE:
            return False
        return by_id[h].route.length - progress[h] <= pad_reserve_radius_m

    def _reserve_pads(air_ids: list[int], rule: bool, emit) -> None:
        """DTC pad arbitration: each pad goes to the landing with the least endurance (BMS CRITICAL/FAULT
        and low-reserve diversions alike); others bound for that pad hold short. A holder keeps its pad
        unless a challenger has ``reservation_swap_s`` less endurance (no flip-flopping)."""
        if not rule:
            reserved_pads.clear()
            return
        cands: dict[str, list[tuple[float, int]]] = {}
        for i in air_ids:
            if status[i] == AIRBORNE and (i in unhealthy or i in diverting):
                cands.setdefault(diverting.get(i, by_id[i].destination), []).append((_endurance_s(i), i))
        swap = float(hresp.get("reservation_swap_s", 15.0))
        new: dict[str, int] = {}
        for pad, lst in cands.items():
            lst.sort()
            best_e, best = lst[0]
            old = reserved_pads.get(pad)
            for e, j in lst:
                if j == old and e - best_e < swap:
                    best = old
            new[pad] = best
            if (best, pad) not in res_announced and best not in unhealthy:   # unhealthy: announced by the DTC rule
                res_announced.add((best, pad))
                emit("dtc", [best], f"DTC: pad {pad} reserved for D-{best} ({_urgency_label(best)}) landing",
                     "global", "warning")
        reserved_pads.clear()
        reserved_pads.update(new)

    def _health_tick(step: int, t: float, air_ids: list[int], attack_state, emit) -> None:
        idx = health.index
        pad_ids = [i for i in ids if status[i] == QUEUED and t >= by_id[i].depart_s]
        busy = set(air_ids) | set(pad_ids)
        k_air = np.array([idx[i] for i in air_ids], dtype=int)
        vel = np.array([agents[i].velocity[:2] for i in air_ids]).reshape(-1, 2)
        for i in air_ids:   # climbs cost energy (layer changes are instantaneous in the engine)
            up = int(agents[i].altitude_layer) - last_layer.get(i, int(agents[i].altitude_layer))
            if up > 0:
                health.start_climb(i, t, up, layer_h)
            last_layer[i] = int(agents[i].altitude_layer)
        health.step(t, dt, k_air, vel, np.array([idx[i] for i in pad_ids], dtype=int),
                    np.array([idx[i] for i in ids if i not in busy], dtype=int))
        for i, c in charging.items():   # charging pad (swap completes at the end of the service time)
            if c["mode"] == "charge":
                health.charge(i, dt, float(ccfg.get("charge_c_rate", 2.0)), c["target"])
        if step % bms_every == 0:
            sp = [agents[m].position[:2] for m in attack_state.malicious if status.get(m) == AIRBORNE]
            health.link_gnss(k_air, np.array([agents[i].position[:2] for i in air_ids]).reshape(-1, 2),
                             bool(link.is_up(t)), bool(use_overseer), np.array(sp).reshape(-1, 2), t)
            for aid, old, new, codes in health.bms(np.array([idx[i] for i in air_ids + pad_ids], dtype=int)):
                if new > old:
                    stats.bms_alerts += 1
                sev = ("info", "warning", "critical", "critical")[new]
                what = ", ".join(codes) if codes else "all clear"
                d = health.detail(aid, 0.0, 1.0)
                emit("bms", [aid], f"BMS {STATUS_NAMES[old]} → {STATUS_NAMES[new]} ({what}) · SoC {d['soc']:.0f}% · "
                     f"pack {d['t_pack']:.0f} °C · motor {d['t_motor']:.0f} °C",
                     "global" if new >= CRITICAL else "drone", sev)
        for i in air_ids:   # out of energy (must not happen when the responses work)
            if status[i] == AIRBORNE and health.soc(i) <= 0.0:
                stats.energy_depleted += 1
                _land_in_place(i, "battery DEPLETED", emit)
        if step % resp_every == 0:
            for i in air_ids:
                if status[i] != AIRBORNE:
                    continue
                st = health.status(i)
                if st == FAULT:
                    _land_in_place(i, f"BMS FAULT ({', '.join(health.codes(idx[i]))})", emit)
                    continue
                if st == CRITICAL:
                    temp_only = all(health.cat_level(i, c) < CRITICAL for c in ("charge", "imbalance", "current"))
                    if temp_only:
                        overheat_s[i] = overheat_s.get(i, 0.0) + float(hresp["check_period_s"])
                        if overheat_s[i] >= float(hresp["overheat_critical_hold_s"]) and i not in diverting:
                            _divert(i, f"overheating CRITICAL for {overheat_s[i]:.0f} s", emit, "critical")
                    elif i not in diverting:
                        _divert(i, f"BMS CRITICAL ({', '.join(health.codes(idx[i]))})", emit, "critical")
                    continue
                overheat_s.pop(i, None)
                if i in diverting:
                    continue
                f = by_id[i]
                ok, need, e_rem, why = health.feasible(i, max(0.0, f.route.length - progress[i]), cruise_of(f))
                if not ok:
                    what = (f"{e_rem:.0f} Wh left, {need:.0f} Wh needed to reach {f.destination}" if need > e_rem
                            else f"{why} before {f.destination}")
                    _divert(i, f"low reserve ({what})", emit, "warning")
            # DTC rule (docs/DRONE_HEALTH_MODEL.md section 8)
            rule = bool(hresp.get("dtc_unhealthy_priority", True)) and use_overseer
            now = {i for i in air_ids if status[i] == AIRBORNE and i not in noncoop
                   and health.status(i) >= CRITICAL} if rule else set()
            for i in now - unhealthy:
                emit("dtc", [i], f"DTC: D-{i} BMS {STATUS_NAMES[health.status(i)]} → right of way to land "
                     f"(priority 0, stays on L{int(agents[i].altitude_layer)}, pad {diverting.get(i, by_id[i].destination)} reserved)",
                     "global", "critical")
            unhealthy.clear()
            unhealthy.update(now)
            for i in air_ids:
                agents[i].priority = 0 if i in unhealthy else by_id[i].eff_priority
            _reserve_pads(air_ids, rule, emit)
            # continuous ADMM weight: w = w_class + (w_top - w_class) * u, u = clip((m_ref - m) / (m_ref - 1), 0, 1)
            # with m = E_rem,BMS / E_need(rest of route); u = 1 at BMS CRITICAL/FAULT
            health_w.clear()
            if rule and bool(hw_cfg.get("enabled", True)):
                m_ref = max(1.01, float(hw_cfg.get("margin_ref", 2.0)))
                w_top = _class_w(0)
                for i in air_ids:
                    if status[i] != AIRBORNE or i in noncoop:
                        continue
                    base = _class_w(int(agents[i].priority))
                    if i in unhealthy:
                        u = 1.0
                    else:
                        f = by_id[i]
                        need = health.energy_needed_wh(i, max(0.0, f.route.length - progress[i]), cruise_of(f))
                        m = health.e_rem_bms_wh(i) / need if need > 1e-9 else math.inf
                        u = min(1.0, max(0.0, (m_ref - m) / (m_ref - 1.0)))
                    if u > 0.0:
                        health_w[i] = base + (max(w_top, base) - base) * u
        stats.energy_used_wh = round(float(health.a["e_out"].sum()), 1)
        by_type: dict[str, list[float]] = {}
        for typ, wh in delivered_energy:
            by_type.setdefault(typ, []).append(wh)
        stats.energy_per_delivered_by_type_wh = {k: round(sum(v) / len(v), 1) for k, v in sorted(by_type.items())}
        stats.energy_per_delivered_wh = stats.energy_per_delivered_by_type_wh.get("DELIVERY")
        mp, mm = health.max_temps()
        stats.max_pack_c = None if mp is None else round(mp, 1)
        stats.max_motor_c = None if mm is None else round(mm, 1)
        counts = [0, 0, 0, 0]
        for i in air_ids:
            if status[i] == AIRBORNE:
                counts[health.status(i)] += 1
        stats.bms_by_status = counts

    # ------------------------------------------------------------------ Phase 4: DTC operator console
    ccfg = cfg.get("dtc_console", {}) or {}
    tfrs: list[dict[str, Any]] = []                 # temporary flight restrictions (dynamic geofences)
    ground_stops: dict[int, float | None] = {}       # sector -> release time (None = until released)
    hold_at: dict[int, np.ndarray] = {}              # drone -> loiter point (airborne) / departure hold (queued)
    ll_hold: set[int] = set()                        # holds started by the lost-link policy (released on restore)
    pinned_layer: dict[int, int] = {}                # operator layer, kept by the DTC allocation
    speed_cap_drone: dict[int, tuple[float, float]] = {}    # drone -> (v, until)
    speed_cap_sector: dict[int, tuple[float, float]] = {}   # sector -> (v, until)
    promoted: set[int] = set()                       # operator priority 0: emergency privileges
    quarantined: set[int] = set()                    # untrusted: reports ignored network-wide
    lost_link_default = str(ccfg.get("lost_link_default", "continue"))
    lost_link_drone: dict[int, str] = {}
    charge_plan: dict[int, dict[str, Any]] = {}      # drone -> {pad, mode, resume}
    charging: dict[int, dict[str, Any]] = {}         # drone on a pad being charged / swapped
    cancelled: set[int] = set()
    outage_queue: list[dict[str, Any]] = []
    console_dirty = [True]

    def _apply_command(cmd: dict[str, Any]) -> None:
        """Entry point at the start of a tick: ground-side commands now, the rest over the DTC link."""
        cmd["tick_received"], cmd["t_received"] = step, t
        cmd.setdefault("results", {})
        ctype = cmd.get("type")
        if ctype not in COMMANDS:
            cmd["status"], cmd["outcome"] = "failed", f"unknown command type {ctype!r}"
            emit("console", [], f"Command {cmd.get('command_id', '?')} rejected: {cmd['outcome']}", "global", "warning")
            return
        if ctype == "add_drone":
            _add_drone(cmd)
            return
        if cmd.get("dry_run"):
            _check(cmd)
            return
        if not use_overseer:
            cmd["status"], cmd["outcome"] = "failed", "no DTC in this architecture"
            emit("console", [], f"{cmd.get('command_id', '?')} {ctype}: failed — no DTC in this architecture",
                 "global", "warning")
            return
        if not link.is_up(t):
            if str(ccfg.get("outage_policy", "queue")) == "queue":
                cmd["status"] = "queued"
                outage_queue.append(cmd)
                emit("console", [], f"{cmd.get('command_id', '?')} {ctype}: DTC link down — queued "
                     f"(expires in {float(ccfg.get('queue_ttl_s', 30)):.0f} s)", "global", "warning")
            else:
                cmd["status"], cmd["outcome"] = "lost", "DTC link down (policy: drop)"
                emit("console", [], f"{cmd.get('command_id', '?')} {ctype}: LOST — DTC link down", "global", "warning")
            return
        _deliver(cmd)

    def _pump_outage_queue() -> None:
        ttl = float(ccfg.get("queue_ttl_s", 30.0))
        keep = []
        for cmd in outage_queue:
            if t - cmd["t_received"] > ttl:
                cmd["status"], cmd["outcome"] = "expired", f"not delivered within {ttl:.0f} s"
                emit("console", [], f"{cmd.get('command_id', '?')} {cmd['type']}: EXPIRED in the outage queue",
                     "global", "warning")
            elif link.is_up(t):
                _deliver(cmd)
            else:
                keep.append(cmd)
        outage_queue[:] = keep

    def _add_drone(cmd: dict[str, Any]) -> None:
        cmd["tick_applied"], cmd["t_applied"] = step, t
        row = cmd["drone"]
        if row["id"] in by_id:
            cmd["status"], cmd["outcome"] = "failed", f"id {row['id']} already in use"
            emit("command", [], f"Add drone rejected: D-{row['id']} already exists", "global")
            return
        f = flight_from_row(network, row, depart_s=max(t, float(row.get("depart_s") or 0.0)))
        flights.append(f)
        register(f)
        etrack.add(f)
        if mtrack is not None:
            mtrack.add(network, f)
        new_flights.append(f)
        cmd["status"], cmd["outcome"] = "applied", f"D-{f.agent_id} scheduled at {f.origin}"
        emit("command", [f.agent_id], f"Operator added D-{f.agent_id} {f.type.value} {f.origin} → {f.destination} "
             f"(departs at t = {f.depart_s:.1f} s)", "global")

    # -------- energy feasibility (movement commands): what the plan would cost vs what is left
    def _plan_for(cmd: dict[str, Any], i: int) -> tuple[float | None, float | None, str]:
        """(length m, speed m/s, description) of the flight the command would leave drone i with."""
        f, ctype, p = by_id[i], cmd["type"], cmd["params"]
        if status[i] != AIRBORNE:
            return None, None, "not airborne"
        pos = agents[i].position[:2]
        remaining = max(0.0, f.route.length - progress[i])
        if ctype in ("reroute", "rtb", "divert_charge"):
            dest = p.get("dest") or (f.origin if ctype == "rtb" else p.get("pad")) or f.destination
            route = _route_to(i, dest, p.get("via"))
            if route is None:
                return None, None, f"no route to {dest}"
            extra = 0.0
            if ctype == "divert_charge":   # then on to the mission destination after service
                extra = network.vertiport_route(network.vertiport(dest), network.vertiport(f.destination))
                extra = RoutePath(extra).length if len(extra) else 0.0
                return route.length, None, f"{route.length:.0f} m to {dest}"
            return route.length + extra, None, f"{route.length:.0f} m to {dest}"
        if ctype == "speed_limit":
            return remaining, float(p["v"]), f"{remaining:.0f} m at {p['v']:.1f} m/s"
        if ctype == "change_layer":
            return remaining + 3.0 * layer_h * max(0, p["layer"] - int(agents[i].altitude_layer)), None, \
                f"{remaining:.0f} m on L{p['layer']}"
        if ctype == "hold":
            return remaining + float(ccfg.get("hold_check_s", 60.0)) * cruise_of(f) * 1.3, None, \
                f"hold {float(ccfg.get('hold_check_s', 60.0)):.0f} s then {remaining:.0f} m"
        if ctype == "fleet_recall_below_soc":
            route = _route_to(i, f.origin, None)
            return (route.length if route else None), None, f"recall to {f.origin}"
        return remaining, None, ""

    def _feasibility(cmd: dict[str, Any], i: int) -> tuple[bool, str]:
        length, speed, what = _plan_for(cmd, i)
        if length is None:
            return status[i] != AIRBORNE, what
        ok, need, e_rem = _energy_check(i, length, speed)
        if ok:
            return True, f"ok ({what}: {need:.0f} of {e_rem:.0f} Wh)" if math.isfinite(e_rem) else "ok"
        alt = _nearest_reachable(i)
        tip = f"; nearest reachable pad {alt[1]} ({alt[0]:.0f} m)" if alt else "; no pad reachable"
        return False, f"infeasible ({what}: needs {need:.0f} Wh, {e_rem:.0f} Wh left){tip}"

    def _check(cmd: dict[str, Any]) -> None:
        movement = COMMANDS[cmd["type"]][1]
        for i in _targets(cmd):
            ok, why = _feasibility(cmd, i) if movement else (True, "no energy check for this command")
            alt = None if ok else _nearest_reachable(i)
            cmd["results"][str(i)] = {"feasible": ok, "detail": why, "alternative": alt[1] if alt else None}
        cmd["status"] = "checked"

    def _targets(cmd: dict[str, Any]) -> list[int]:
        ctype, p = cmd["type"], cmd["params"]
        if ctype == "fleet_ground_bms_critical":
            return [i for i in ids if status[i] == AIRBORNE and i not in noncoop and health is not None
                    and health.status(i) >= CRITICAL]
        if ctype == "fleet_recall_below_soc":
            return [i for i in ids if status[i] == AIRBORNE and i not in noncoop and health is not None
                    and health.soc_bms(i) * 100.0 < p["threshold_pct"]]
        if ctype == "speed_limit" and p.get("sector") is not None and not cmd["targets"]:
            return [i for i in ids if status[i] == AIRBORNE
                    and _sector(network, agents[i].position[0], agents[i].position[1]) == p["sector"]]
        return [i for i in cmd["targets"] if i in by_id]

    def _route_to(i: int, dest: str, via) -> RoutePath | None:
        v = network.vertiport(dest)
        via_node = None
        if via is not None:
            via_node = int(np.argmin(np.einsum("ij,ij->i", network.nodes - np.asarray(via), network.nodes - np.asarray(via))))
        start = agents[i].position[:2] if status[i] == AIRBORNE else np.asarray(network.vertiport(by_id[i].origin).position)
        return plan_route(network, start, np.asarray(v.position, float), v.node, _active_zones(), via_node,
                          direct_within_m=look_ahead if status[i] == AIRBORNE else 0.0)

    def _ground_now(i: int, why: str) -> str:
        if status[i] == QUEUED:
            status[i] = LANDED
            cancelled.add(i)
            emit("console", [i], f"D-{i} departure cancelled ({why})", "global", "warning")
            return "acknowledged: departure cancelled"
        if status[i] != AIRBORNE:
            return "failed: not airborne"
        limit = float(ccfg.get("ground_now_max_pad_m", 800.0))
        hold_at.pop(i, None)
        for length, vid, route in _pad_options(i):
            if length > limit:
                break
            # a precautionary landing needs the energy; a thin voltage margin is the reason to land, not a veto
            if health is None or health.feasible(i, length, cruise_of(by_id[i]), check_sag=False)[0]:
                _set_route(i, route, vid, why, "console", "warning")
                diverting[i] = vid
                stats.precautionary_landings += 1
                emit("console", [i], f"D-{i} {why}: precautionary landing at {vid} ({length:.0f} m)", "global", "warning")
                return f"acknowledged: landing at {vid}"
        _land_in_place(i, f"{why}; no pad within {limit:.0f} m", emit)
        return "acknowledged: landing in place"

    def _rtb(i: int, why: str, force: bool) -> str:
        f = by_id[i]
        if status[i] == QUEUED:
            return _ground_now(i, why)
        route = _route_to(i, f.origin, None)
        if route is None:
            return "failed: no route back to base"
        ok, need, e_rem = _energy_check(i, route.length)
        if not ok and not force:
            alt = _nearest_reachable(i)
            if alt is None:
                _land_in_place(i, f"{why}: base out of reach, no pad reachable", emit)
                return "acknowledged: landing in place"
            _set_route(i, alt[2], alt[1], why, "console", "warning")
            emit("console", [i], f"D-{i} {why}: base {f.origin} out of reach ({need:.0f} > {e_rem:.0f} Wh) → {alt[1]}",
                 "global", "warning")
            return f"acknowledged: base out of reach, landing at {alt[1]}"
        hold_at.pop(i, None)
        _set_route(i, route, f.origin, why, "console", None)
        emit("console", [i], f"D-{i} {why}: returning to base {f.origin} ({route.length:.0f} m)", "global")
        return f"acknowledged: returning to {f.origin}"

    def _deliver(cmd: dict[str, Any]) -> None:
        cmd["tick_delivered"], cmd["t_delivered"] = step, t
        ctype, p, force = cmd["type"], cmd["params"], cmd.get("force", False)
        cid, why = cmd.get("command_id", "?"), f"operator {cmd['type'].replace('_', ' ')}"
        res: dict[str, str] = {}
        movement = COMMANDS[ctype][1]
        console_dirty[0] = True
        for i in _targets(cmd):
            if movement and not force and status[i] == AIRBORNE and ctype != "fleet_recall_below_soc":
                ok, detail = _feasibility(cmd, i)
                if not ok:
                    res[str(i)] = f"failed: {detail}"
                    continue
            f = by_id[i]
            if ctype == "reroute":
                route = _route_to(i, p["dest"] or f.destination, p.get("via"))
                if route is None:
                    res[str(i)] = "failed: no route (restricted areas?)"
                    continue
                if status[i] == QUEUED:
                    f.route, f.destination = route, p["dest"] or f.destination
                    reroutes.append({"id": i, "destination": f.destination, "reason": why,
                                     "route_length_m": round(route.length, 1),
                                     "route": [[round(float(x), 2), round(float(y), 2)] for x, y in route.points]})
                else:
                    _set_route(i, route, p["dest"] or f.destination, why, "console", None)
                planned_dest[i] = f.destination   # the operator changed the mission
                res[str(i)] = f"acknowledged: {route.length:.0f} m to {f.destination}"
            elif ctype == "ground_now":
                res[str(i)] = _ground_now(i, why)
            elif ctype == "hold":
                hold_at[i] = agents[i].position[:2].copy()
                ll_hold.discard(i)
                res[str(i)] = "acknowledged: " + ("holding position" if status[i] == AIRBORNE else "departure held")
            elif ctype == "resume":
                was = hold_at.pop(i, None)
                ll_hold.discard(i)
                res[str(i)] = "acknowledged: resumed" if was is not None else "acknowledged: was not holding"
            elif ctype in ("rtb", "fleet_recall_below_soc"):
                res[str(i)] = _rtb(i, why, force)
            elif ctype == "change_layer":
                L = int(p["layer"])
                if L == emergency_layer and f.type != AgentType.EMERGENCY and i not in promoted:
                    res[str(i)] = f"failed: L{L} is reserved for emergencies"
                    continue
                if status[i] == AIRBORNE and not _layer_transition_clear(agents[i], L, [agents[j] for j in ids if status[j] == AIRBORNE], d_min):
                    res[str(i)] = f"failed: L{L} not clear (layer-transition safety check)"
                    continue
                if status[i] == AIRBORNE:
                    agents[i].altitude_layer = L
                    agents[i].position[2] = float(L)
                    overseer.last_layer_map[i] = L
                preferred_layer[i] = L
                cached_layers[i] = L
                pinned_layer[i] = L
                res[str(i)] = f"acknowledged: now on L{L}"
            elif ctype == "speed_limit":
                if p.get("sector") is not None and not cmd["targets"]:
                    continue   # sector cap recorded once below
                speed_cap_drone[i] = (float(p["v"]), t + float(p["expires_s"]))
                res[str(i)] = f"acknowledged: ≤ {p['v']:.1f} m/s for {p['expires_s']:.0f} s"
            elif ctype == "priority":
                f.priority = int(p["level"])
                agents[i].priority = f.eff_priority
                (promoted.add if f.priority == 0 else promoted.discard)(i)
                res[str(i)] = f"acknowledged: priority P{f.priority}" + (" (emergency privileges)" if i in promoted else "")
            elif ctype == "quarantine":
                quarantined.add(i)
                res[str(i)] = "acknowledged: reports ignored network-wide; " + _ground_now(i, "quarantine: ordered to land")
            elif ctype == "lost_link_policy":
                lost_link_drone[i] = p["policy"]
                res[str(i)] = f"acknowledged: lost-link policy {p['policy']}"
            elif ctype == "divert_charge":
                route = _route_to(i, p["pad"], None) if status[i] == AIRBORNE else None
                if status[i] == AIRBORNE and route is None:
                    res[str(i)] = "failed: no route to the pad"
                    continue
                charge_plan[i] = {"pad": p["pad"], "mode": p["mode"], "resume": planned_dest.get(i, f.destination)}
                if status[i] == AIRBORNE:
                    hold_at.pop(i, None)
                    _set_route(i, route, p["pad"], why, "console", None)
                    res[str(i)] = f"acknowledged: to {p['pad']} for battery {p['mode']}"
                else:
                    res[str(i)] = "failed: not airborne"
            elif ctype == "fleet_ground_bms_critical":
                res[str(i)] = _ground_now(i, "fleet action: BMS CRITICAL grounded")
        if ctype == "speed_limit" and p.get("sector") is not None and not cmd["targets"]:
            speed_cap_sector[int(p["sector"])] = (float(p["v"]), t + float(p["expires_s"]))
            res["sector"] = f"acknowledged: S{p['sector']} ≤ {p['v']:.1f} m/s for {p['expires_s']:.0f} s"
        elif ctype == "tfr":
            tfrs.append({"name": p["name"], "polygon": p["polygon"], "start_s": p["start_s"], "end_s": p["end_s"],
                         "active": False, "command_id": cid})
            res["airspace"] = f"acknowledged: {p['name']} {p['start_s']:.0f}–{p['end_s']:.0f} s"
        elif ctype == "tfr_cancel":
            hit = [z for z in tfrs if (not p["name"] or z["name"] == p["name"]) and z["end_s"] > t]
            for z in hit:
                z["end_s"] = t
            res["airspace"] = f"acknowledged: {len(hit)} restriction(s) ended" if hit else "failed: no such restriction"
        elif ctype == "ground_stop":
            ground_stops[int(p["sector"])] = p.get("release_s")
            res["airspace"] = f"acknowledged: departures from S{p['sector']} stopped" + (
                f" until {p['release_s']:.0f} s" if p.get("release_s") is not None else "")
        elif ctype == "ground_stop_release":
            res["airspace"] = ("acknowledged: released" if ground_stops.pop(int(p["sector"]), "x") != "x"
                               else "failed: no ground stop there")
        elif ctype == "lost_link_policy" and not cmd["targets"]:
            nonlocal_set("lost_link_default", p["policy"])
            res["fleet"] = f"acknowledged: fleet lost-link policy {p['policy']}"
        cmd["results"] = res
        oks = [v for v in res.values() if v.startswith("acknowledged")]
        cmd["status"] = "acknowledged" if oks or (not res and ctype.startswith("fleet")) else "failed"
        cmd["outcome"] = (f"{len(oks)}/{len(res)} acknowledged" if res else "no drone matched")
        who = sorted(int(k) for k in res if k.isdigit())
        sev = None if cmd["status"] == "acknowledged" and len(oks) == len(res) else "warning"
        detail = "; ".join(f"D-{k}: {v}" if k.isdigit() else v for k, v in list(res.items())[:4])
        emit("console", who[:6], f"DTC {cid} {ctype.replace('_', ' ')}"
             + (f" → {', '.join('D-%d' % w for w in who[:6])}{'…' if len(who) > 6 else ''}" if who else "")
             + f": {cmd['outcome']}" + (f" — {detail}" if detail else "")
             + (f" (reason: {cmd['reason']})" if cmd.get("reason") else ""), "global", sev)

    console_state = {"lost_link_default": lost_link_default}
    # Phase 5: detect-and-avoid sensing, repeated sorties, battery-service pad capacity
    sense_r = float(cfg["safety"].get("detect_and_avoid_radius_meters", 30.0))
    sensed_seen: set[tuple[int, int]] = set()
    intruders_announced: set[int] = set()
    ops = cfg.get("operations", {}) or {}
    sorties = bool(ops.get("sorties", False))
    service_capacity = max(1, int(ccfg.get("service_pad_capacity", 2)))
    pad_queue: dict[str, list[tuple[int, dict[str, Any], float]]] = {}
    sortie_n: dict[int, int] = {}
    energy_at_sortie: dict[int, float] = {}

    def _service_pads() -> list:
        roles = set(ops.get("service_roles", ["depot"]))
        return [v for v in network.vertiports if v.role in roles] or list(network.vertiports)

    def _next_sortie(i: int) -> None:
        """Repeated operations: after a turnaround the drone takes a new mission from the pad it is on,
        or first flies to a battery-service pad when its charge is below ``service_soc_pct``."""
        f = by_id[i]
        here = network.vertiport(f.destination)
        sortie_n[i] = sortie_n.get(i, 0) + 1
        rng = np.random.default_rng([seed, 31337, i, sortie_n[i]])
        others = [v for v in network.vertiports if v.id != here.id]
        if f.type == AgentType.EMERGENCY and here.role != "hospital":
            others = [v for v in others if v.role == "hospital"] or others
        d = np.array([math.dist(here.position, v.position) for v in others])
        w = np.exp(-d / 1500.0)
        nxt_dest = others[int(rng.choice(len(others), p=w / w.sum()))]
        turnaround = float(ops.get("turnaround_s", 30.0))
        need_service = health is not None and health.soc_bms(i) * 100.0 < float(ops.get("service_soc_pct", 35.0))
        mode = str(ops.get("service_mode", "swap"))
        if need_service:
            pads = sorted(_service_pads(), key=lambda v: (RoutePath(network.vertiport_route(here, v)).length
                                                         if v.id != here.id else 0.0, v.id))
            svc = pads[0]
            ferry = RoutePath(network.vertiport_route(here, svc)).length if svc.id != here.id else 0.0
            too_weak = health.status(i) >= CRITICAL or not _energy_check(i, ferry)[0]
            if svc.id == here.id or too_weak:   # on a service pad, or too weak to fly there: ground-crew service
                if too_weak and svc.id != here.id:
                    emit("service", [i], f"D-{i} too low to reach {svc.id}: ground-crew battery {mode} at {here.id}",
                         "global", "warning")
                    svc = here
                status[i] = QUEUED
                charge_plan[i] = {"pad": svc.id, "mode": mode, "resume": nxt_dest.id, "slow": svc.id not in
                                  {v.id for v in _service_pads()}}
                planned_dest[i] = nxt_dest.id
                _start_service(i, agents[i])
                return
            charge_plan[i] = {"pad": svc.id, "mode": mode, "resume": nxt_dest.id}
            dest, why = svc, f"battery {mode} at {svc.id} before the next mission"
        else:
            dest, why = nxt_dest, "next sortie"
        route = RoutePath(network.vertiport_route(here, dest))
        status[i] = QUEUED
        f.origin, f.destination, f.route = here.id, dest.id, route
        f.depart_s = round(t + turnaround, 1)
        planned_dest[i] = nxt_dest.id
        progress[i] = 0.0
        start = route.point_at(0.0)
        agents[i].position[0], agents[i].position[1] = float(start[0]), float(start[1])
        agents[i].velocity[:] = 0.0
        agents[i].destination = np.array([*route.point_at(route.length), agents[i].position[2]])
        preflight_ok.discard(i)
        held.discard(i)
        if mtrack is not None:
            mtrack.drop(i)
            mtrack.add(network, f)
        if health is not None:
            energy_at_sortie[i] = health.energy_used_wh(i)
        stats.missions += 1
        reroutes.append({"id": i, "origin": here.id, "destination": dest.id, "reason": why,
                         "route_length_m": round(route.length, 1),
                         "route": [[round(float(x), 2), round(float(y), 2)] for x, y in route.points]})
        emit("sortie", [i], f"D-{i} {why}: {here.id} → {dest.id}, departs at {f.depart_s:.0f} s", "drone")
    dep_block_seen: set[tuple[int, str]] = set()
    stuck: dict[int, tuple[float, float]] = {}   # drone -> (progress, time) of its last real progress
    tfr_every = max(1, int(round(1.0 / dt)))
    last_console_sent: list[Any] = [None]

    def _departure_block(f: Flight) -> str | None:
        i = f.agent_id
        if i in hold_at:
            return "operator departure hold"
        if i in charging:
            return None
        pad = np.asarray(network.vertiport(f.origin).position, dtype=float)
        sid = _sector(network, pad[0], pad[1])
        if sid in ground_stops:
            rel = ground_stops[sid]
            return f"ground stop S{sid}" + (f" until {rel:.0f} s" if rel is not None else "")
        zones = _active_zones()
        for z in tfrs:
            if z["active"] and points_in_polygon(pad[None, :], z["polygon"])[0]:
                return f"pad inside restricted area {z['name']}"
        if zones and route_hits_zones(f.route, 0.0, zones):   # plan around the restriction before take-off
            v = network.vertiport(f.destination)
            route = plan_route(network, pad, np.asarray(v.position, float), v.node, zones)
            if route is None:
                return "no route around the restricted area"
            f.route = route
            reroutes.append({"id": i, "destination": f.destination, "reason": "route avoids restricted area",
                             "route_length_m": round(route.length, 1),
                             "route": [[round(float(x), 2), round(float(y), 2)] for x, y in route.points]})
        return None

    def _lost_link(airborne_now) -> None:
        for a in airborne_now:
            i = a.id
            pol = lost_link_drone.get(i, console_state["lost_link_default"])
            if pol == "hold" and i not in hold_at:
                hold_at[i] = a.position[:2].copy()
                ll_hold.add(i)
            elif pol == "rtb":
                _rtb(i, "lost-link policy: return to base", False)
            elif pol == "land":
                _ground_now(i, "lost-link policy: land")
        counts: dict[str, int] = {}
        for a in airborne_now:
            pol = lost_link_drone.get(a.id, console_state["lost_link_default"])
            counts[pol] = counts.get(pol, 0) + 1
        emit("console", [], "Lost-link contingency: " + ", ".join(f"{n} {k}" for k, n in sorted(counts.items())),
             "global", "warning")

    def _start_service(i: int, nxt) -> None:
        """Drone arrived at a battery-service pad: start now, or wait for a free slot (FIFO)."""
        plan = charge_plan.pop(i)
        status[i] = QUEUED
        nxt.velocity[:] = 0.0
        pad = network.vertiport(plan["pad"])
        nxt.position[0], nxt.position[1] = float(pad.position[0]), float(pad.position[1])
        by_id[i].depart_s = math.inf      # on the pad until the service is done
        busy = sum(1 for c in charging.values() if c["pad"] == pad.id)
        if busy >= service_capacity:
            pad_queue.setdefault(pad.id, []).append((i, plan, t))
            stats.service_queue_max = max(stats.service_queue_max, len(pad_queue[pad.id]))
            console_dirty[0] = True
            emit("service", [i], f"D-{i} waiting at {pad.id} for a battery {plan['mode']} slot "
                 f"({busy} busy, {len(pad_queue[pad.id])} in queue)", "global")
            return
        _begin_service(i, plan)

    def _begin_service(i: int, plan: dict[str, Any]) -> None:
        f = by_id[i]
        pad = network.vertiport(plan["pad"])
        if plan["mode"] == "swap" or health is None:
            service = float(ccfg.get("swap_time_s", 90.0)) * (2.0 if plan.get("slow") else 1.0)
            target = 1.0
        else:
            target = float(ccfg.get("charge_target_pct", 90.0)) / 100.0
            rate = float(ccfg.get("charge_c_rate", 2.0))
            service = max(30.0, (target - health.soc(i)) / rate * 3600.0)
        charging[i] = {"mode": plan["mode"], "until": t + service, "target": target, "pad": pad.id}
        resume = network.vertiport(plan["resume"])
        route = RoutePath(network.vertiport_route(pad, resume))
        f.origin, f.destination, f.route, f.depart_s = pad.id, resume.id, route, round(t + service, 1)
        progress[i] = 0.0
        agents[i].destination = np.array([*route.point_at(route.length), agents[i].position[2]])
        preflight_ok.discard(i)
        held.discard(i)
        diverting.pop(i, None)
        if mtrack is not None:
            mtrack.drop(i)
            mtrack.add(network, f)
        reroutes.append({"id": i, "destination": resume.id, "origin": pad.id, "reason": f"battery {plan['mode']}",
                         "route_length_m": round(route.length, 1),
                         "route": [[round(float(x), 2), round(float(y), 2)] for x, y in route.points]})
        console_dirty[0] = True
        emit("service", [i], f"D-{i} landed at {pad.id} for battery {plan['mode']} ({service:.0f} s), then on to "
             f"{resume.id}", "global")

    def _console_upkeep() -> None:
        for z in tfrs:   # activate / end restrictions on schedule
            if not z["active"] and z["start_s"] <= t < z["end_s"]:
                z["active"] = True
                zone_version[0] += 1
                console_dirty[0] = True
                emit("tfr", [], f"Restricted area {z['name']} ACTIVE until {z['end_s']:.0f} s", "global", "warning")
            elif z["active"] and t >= z["end_s"]:
                z["active"] = False
                zone_version[0] += 1
                console_dirty[0] = True
                emit("tfr", [], f"Restricted area {z['name']} lifted", "global")
        for sid, rel in list(ground_stops.items()):
            if rel is not None and t >= rel:
                ground_stops.pop(sid)
                console_dirty[0] = True
                emit("console", [], f"Ground stop S{sid} released (scheduled)", "global")
        for d in (speed_cap_drone, speed_cap_sector):
            for key in [k for k, (_, until) in d.items() if t >= until]:
                d.pop(key)
                console_dirty[0] = True
        for i in [i for i, c in charging.items() if t >= c["until"]]:
            c = charging.pop(i)
            if health is not None:
                health.set_soc(i, max(health.soc(i), c["target"]))
                health.bms(np.array([health.index[i]]), initial=True)   # fresh pack: re-evaluate the BMS now
            stats.services += 1
            console_dirty[0] = True
            emit("service", [i], f"D-{i} battery {c['mode']} complete — SoC "
                 f"{(health.soc(i) * 100 if health else 100):.0f}%", "global")
            q = pad_queue.get(c["pad"])
            if q:   # next drone in line at this pad
                j, plan, since = q.pop(0)
                stats.service_wait_s = round(stats.service_wait_s + (t - since), 1)
                _begin_service(j, plan)
        if step % tfr_every == 0:   # no progress for 30 s (e.g. a U-turn route against the tube wall): replan
            for i in ids:
                if status[i] != AIRBORNE or i in hold_at or i in holding_short:
                    stuck.pop(i, None)
                    continue
                s0, t0 = stuck.get(i, (progress[i], t))
                if progress[i] > s0 + 2.0:
                    stuck[i] = (progress[i], t)
                elif t - t0 >= 30.0:
                    f = by_id[i]
                    route = _route_to(i, f.destination, None)
                    stuck[i] = (0.0, t)
                    if route is not None:
                        _set_route(i, route, f.destination, "no progress for 30 s", "replan", "warning")
                        emit("replan", [i], f"D-{i} made no progress for 30 s → new route to {f.destination} "
                             f"({route.length:.0f} m)", "drone", "warning")
                else:
                    stuck.setdefault(i, (s0, t0))
        zones = _active_zones()
        if zones and step % tfr_every == 0:   # keep airborne drones out of active restrictions
            for i in ids:
                if status[i] != AIRBORNE:
                    continue
                f = by_id[i]
                if zone_planned.get(i) == zone_version[0]:
                    continue   # already planned against these restrictions (it may start inside one)
                inside = any(points_in_polygon(agents[i].position[None, :2], z)[0] for z in zones)
                if not inside and not route_hits_zones(f.route, progress[i], zones):
                    continue
                zone_planned[i] = zone_version[0]
                route = _route_to(i, f.destination, None)
                if route is not None and not (inside and route.length < 1.0):
                    _set_route(i, route, f.destination, "restricted area", "tfr", "warning")
                    emit("tfr", [i], f"D-{i} rerouted around the restricted area ({route.length:.0f} m to "
                         f"{f.destination})", "drone", "warning")
                else:
                    emit("tfr", [i], f"D-{i}: no route around the restricted area", "drone", "warning")
                    _ground_now(i, "restricted area")

    def _console_view() -> dict[str, Any]:
        return {
            "tfrs": [{k: z[k] for k in ("name", "polygon", "start_s", "end_s", "active")} for z in tfrs],
            "ground_stops": {str(k): v for k, v in ground_stops.items()},
            "holds": sorted(hold_at), "quarantined": sorted(quarantined), "promoted": sorted(promoted),
            "pinned": {str(k): v for k, v in pinned_layer.items()},
            "speed_caps": {str(k): v[0] for k, v in speed_cap_drone.items()},
            "sector_caps": {str(k): v[0] for k, v in speed_cap_sector.items()},
            "charging": {str(k): {"mode": c["mode"], "until": round(c["until"], 1)} for k, c in charging.items()},
            "lost_link_default": console_state["lost_link_default"],
            "lost_link": {str(k): v for k, v in lost_link_drone.items()},
            "outage_queue": len(outage_queue),
            "service_queue": {k: [x[0] for x in v] for k, v in pad_queue.items() if v},
        }

    def nonlocal_set(key: str, value: Any) -> None:
        console_state[key] = value

    for step in range(n_steps + 1):
        if should_stop and should_stop():
            return
        t = round(step * dt, 6)
        events: list[dict[str, Any]] = []

        def emit(kind: str, who: Sequence[int], text: str, scope: str = "drone", severity: str | None = None) -> None:
            who = [int(w) for w in who]
            ev = {"t": t, "kind": kind, "id": who[0] if who else None, "ids": who, "scope": scope, "text": text}
            if severity:
                ev["severity"] = severity
            events.append(ev)

        # --- operator commands, applied at the start of the tick (deterministic replay by tick index)
        if command_source is not None:
            for cmd in command_source(step, t):
                _apply_command(cmd)
        if outage_queue:
            _pump_outage_queue()
        _console_upkeep()

        # --- departures (pad must be clear: ground holding otherwise)
        dep_grid = None
        dep_load: dict[int, dict[int, int]] | None = None   # sector -> layer -> airborne count (once per tick)
        departed_now: list[int] = []
        for f in flights:
            i = f.agent_id
            if status[i] != QUEUED or t < f.depart_s:
                continue
            why_held = _departure_block(f)
            if why_held:
                if (i, why_held) not in dep_block_seen:
                    dep_block_seen.add((i, why_held))
                    stats.pad_holds += 1
                    emit("hold", [i], f"D-{i} ground hold at {f.origin}: {why_held}", "global", "warning")
                continue
            if (health is not None and i not in preflight_ok and i in preflight_fail
                    and step % max(1, int(round(30.0 / dt))) != 0):
                continue   # failed the pre-flight check: re-run it only every 30 s (noisy estimate, no retry-until-lucky)
            if health is not None and i not in preflight_ok:   # onboard pre-flight check (BMS + energy reserve)
                why = None
                lift, lift_why = health.lift_ok(i)
                if not lift:
                    why = lift_why
                elif health.status(i) >= CRITICAL:
                    why = f"BMS {STATUS_NAMES[health.status(i)]} ({', '.join(health.codes(health.index[i]))})"
                else:
                    ok, _, _, reason = health.feasible(i, f.route.length, cruise_of(f), climb=True)
                    if not ok:
                        why = f"{reason} for {f.destination}"
                if why:
                    if i not in preflight_fail:
                        preflight_fail.add(i)
                        stats.grounded_preflight += 1
                        emit("preflight", [i], f"D-{i} stays on {f.origin}: pre-flight check failed — {why}", "global", "warning")
                    continue
                preflight_ok.add(i)
            if _reservation_active(f.origin):   # DTC: pad kept clear for an urgent landing on final approach
                if (i, f.origin) not in pad_res_seen:
                    pad_res_seen.add((i, f.origin))
                    stats.pad_holds += 1
                    etrack.on_hold(i)
                    emit("hold", [i], f"D-{i} ground hold at {f.origin}: pad reserved for D-{reserved_pads[f.origin]} "
                         f"({_urgency_label(reserved_pads[f.origin])}) landing", "global", "warning")
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
            else:
                busy = [j for j in ids if status[j] == AIRBORNE and np.linalg.norm(agents[j].position[:2] - pad) < 2.0 * d_min]
                near_join = {j for j in ids if status[j] == AIRBORNE
                             and np.linalg.norm(agents[j].position[:2] - join) < MERGE_CLEARANCE_M}
            if (agree is not None and i not in cached_layers and f.preferred_layer is None
                    and f.type != AgentType.EMERGENCY):
                # spread departures over the direction's layers: cheapest layer with a merge gap at the junction
                if dep_load is None:
                    dep_load = {}
                    for j in ids:
                        if status[j] == AIRBORNE:
                            row = dep_load.setdefault(_sector(network, agents[j].position[0], agents[j].position[1]), {})
                            row[int(agents[j].altitude_layer)] = row.get(int(agents[j].altitude_layer), 0) + 1
                load = dep_load.get(_sector(network, float(pad[0]), float(pad[1])), {})
                dep_layer = departure_layer(agree.allowed(direction_of[i]), {int(agents[j].altitude_layer) for j in near_join},
                                            load, capacity, health.soc_bms(i) if health is not None else 1.0, layer_h, la_cfg)
            # merge gap: no same-layer traffic near the junction where the approach leg joins the corridor
            merge = sorted((j for j in near_join if agents[j].altitude_layer == dep_layer), key=index_of.__getitem__)
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
            elif agents[i].altitude_layer != dep_layer:   # departure spread to a higher layer of its direction
                agents[i].altitude_layer = dep_layer
                agents[i].position[2] = float(dep_layer)
                agents[i].destination[2] = float(dep_layer)
                overseer.last_layer_map[i] = dep_layer
                stats.departures_spread += 1
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
                    _lost_link(airborne)
                link_was_up = False
            else:
                if not link_was_up:
                    emit("link", [], "DTC link restored — directives resume", "global")
                    for i in sorted(ll_hold):
                        hold_at.pop(i, None)
                    if ll_hold:
                        emit("console", sorted(ll_hold)[:6], f"Lost-link holds released for {len(ll_hold)} drone(s)", "global")
                    ll_hold.clear()
                link_was_up = True
                last_directive_t = t
                stats.dtc_directives += 1
                sectors: dict[int, list[AgentState]] = {}
                visible = [a for a in airborne if a.id not in noncoop and a.id not in quarantined]   # unseen / untrusted
                for a in visible:
                    sid = _sector(network, a.position[0], a.position[1])
                    a.corridor_assignment = sid
                    sectors.setdefault(sid, []).append(a)
                changed = 0
                prev_corr = dict(overseer.last_corridor_map)
                prev_layer = dict(overseer.last_layer_map)
                merged_c, merged_l = {}, {}
                for a in visible:  # first request = previous layer, else semicircular preference
                    prev_layer.setdefault(a.id, preferred_layer[a.id])
                    prev_corr[a.id] = a.corridor_assignment
                for sid, members in sectors.items():
                    overseer.last_corridor_map, overseer.last_layer_map = prev_corr, prev_layer
                    directive = overseer.update(GlobalStateSnapshot(
                        timestamp=t, corridor_occupancy={sid: len(members)},
                        agent_ids=[a.id for a in members],
                        agent_types={a.id: (AgentType.EMERGENCY if a.id in promoted else a.type) for a in members},
                        agent_priorities={a.id: a.priority for a in members},
                        agent_directions={a.id: direction_of[a.id] for a in members}))
                    merged_c.update(directive.corridor_map)
                    merged_l.update(directive.altitude_map)
                overseer.last_corridor_map, overseer.last_layer_map = merged_c, merged_l
                for aid in unhealthy:   # right of way, but no energy-costly layer change
                    if aid in merged_l:
                        merged_l[aid] = int(agents[aid].altitude_layer)
                for aid, L in pinned_layer.items():   # operator layer changes stick
                    if aid in merged_l:
                        merged_l[aid] = L
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
        custom_spoof = [i for i, (_, t0) in spoof_custom.items() if i in by_air and t >= t0
                        and i not in attack_state.malicious]
        if custom_spoof:  # custom malicious drones: their own offset vector (route-mode extension of attack.py)
            fals = dict(attack_state.falsified)
            for i in custom_spoof:
                fals[i] = by_air[i].position + spoof_custom[i][0]
            attack_state = AttackState(malicious=list(attack_state.malicious) + custom_spoof, falsified=fals)
        if attack_state.falsified:
            reported = {a.id: a for a in apply_attack(airborne, attack_state)}
        else:  # no falsified report this tick: reports equal the true states (read-only below)
            reported = by_air
        if attack_state.malicious:
            stats.attack_active_ticks += 1
            for m in attack_state.malicious:
                if m not in stats.malicious_ids:
                    stats.malicious_ids.append(m)
            new_m = [m for m in attack_state.malicious if m not in announced_spoofers]
            if new_m:
                announced_spoofers.update(new_m)
                emit("attack", new_m,
                     f"Spoofing attack: {', '.join('D-%d' % m for m in new_m)} broadcast false positions", "global")

        # --- layer agreement: drones negotiate layers over V2V; the DTC prices layers and settles stuck drones
        if agree is not None and airborne and step % agree_steps == 0:
            def _apply_layer(i: int, L: int, kind: str, text: str) -> None:
                if L != int(agents[i].altitude_layer):
                    agents[i].altitude_layer = L
                    agents[i].position[2] = float(L)
                    overseer.last_layer_map[i] = L
                    cached_layers[i] = L
                emit(kind, [i], text)

            def _constrained(i: int) -> bool:   # slow on purpose: never "stuck"
                if i in hold_at or i in diverting or (health is not None and health.overheating(i)):
                    return True
                cap = speed_cap_drone.get(i)
                if cap and t < cap[1]:
                    return True
                cap = speed_cap_sector.get(_sector(network, agents[i].position[0], agents[i].position[1]))
                return bool(cap and t < cap[1])

            heard = {j: (by_air[j] if j in quarantined else r) for j, r in reported.items() if j not in noncoop}
            dtc_now = use_overseer and step % period_steps == 0 and link.is_up(t)
            ctx = RoundContext(
                by_air=by_air, heard=heard,
                visible=[a for a in airborne if a.id not in noncoop and a.id not in quarantined],
                adj=adj,
                participants=[a.id for a in airborne if a.id not in noncoop and a.id not in quarantined
                              and a.type != AgentType.EMERGENCY and a.id not in promoted and a.id not in pinned_layer
                              and a.id not in unhealthy and int(a.altitude_layer) != emergency_layer],
                sector_of=lambda a: _sector(network, a.position[0], a.position[1]),
                tangent=lambda i: by_id[i].route.tangent_at(progress[i]),
                remaining=lambda i: by_id[i].route.length - progress[i],
                cruise=lambda i: cruise_of(by_id[i]),
                soc=lambda i: health.soc_bms(i) if health is not None else 1.0,
                priority=lambda i: int(agents[i].priority),
                direction=lambda i: direction_of[i],
                constrained=_constrained,
                transition_clear=lambda a, L: _layer_transition_clear(a, L, airborne, d_min),
                defended=defended, dtc_enabled=use_overseer)
            if dtc_now:   # DTC seeds the per-sector layer prices from its global count
                loads: dict[tuple[int, int], int] = {}
                members: dict[int, list[int]] = {}
                for a in ctx.visible:
                    sid = ctx.sector_of(a)
                    loads[(sid, int(a.altitude_layer))] = loads.get((sid, int(a.altitude_layer)), 0) + 1
                    members.setdefault(sid, []).append(a.id)
                agree.dtc_seed_prices(loads, members)
            moves, reqs = agree.round(t, ctx)
            for i, L0, L1, text in moves:
                _apply_layer(i, L1, "agree", text)
            for i, text in reqs:
                emit("agree", [i], text, "drone", "warning")
            if dtc_now:
                for i, L0, L1, text in agree.dtc_resolve(t, ctx):
                    _apply_layer(i, L1, "dtc", text)
            a_st = agree.stats
            stats.agree_switches, stats.agree_yields = a_st.switches, a_st.yields
            stats.stuck_requests, stats.dtc_stuck_resolved, stats.dtc_stuck_denied = (
                a_st.stuck_requests, a_st.dtc_resolved, a_st.dtc_denied)

        # --- P3 route following + boids -> desired velocity
        desired: dict[int, np.ndarray] = {}
        threat: dict[int, tuple[int, float, float]] = {}   # id -> (other, t_cpa, miss)
        corrections: dict[int, list[list[float]]] = {}    # spoofer -> receivers' corrected xy (this tick)
        trust_tick: dict[int, list[list]] = {}            # receiver -> [[neighbour, status], ...]
        leaders: dict[int, tuple[int, float, float]] = {}  # follower -> (leader, gap, speed)

        def ref_speed(a, remaining: float) -> float:
            # reference speed: cruise by mission type, brake to stop at the pad
            v = min(cruise_of(a), math.sqrt(max(0.0, 2.0 * 0.6 * a_max * max(remaining - 1.0, 0.0))) + 0.3)
            if health is not None and health.overheating(a.id):   # onboard response: limit power until it cools
                v = min(v, float(hresp["overheat_speed_frac"]) * cruise_of(a))
            if health is not None and health.low_voltage(a.id):   # weak cell near cut-off: least-current speed
                v = min(v, health.min_power_speed(a.id, cruise_of(a)))
            dest = by_id[a.id].destination
            holder = reserved_pads.get(dest)
            if (holder is not None and holder != a.id and remaining < pad_hold_m + 40.0 and _reservation_active(dest)
                    and (by_id[a.id].type != AgentType.EMERGENCY or health.status(holder) >= CRITICAL)):
                # (a medical emergency holds only for a BMS CRITICAL/FAULT landing, not for a low-reserve one)
                # arrival on a pad reserved for a more urgent landing: stop short and hover until it is clear
                v = min(v, math.sqrt(max(0.0, 2.0 * 0.6 * a_max * max(remaining - pad_hold_m, 0.0))))
                if holding_short.get(a.id) != dest:
                    holding_short[a.id] = dest
                    stats.pads_held_short += 1
                    emit("hold", [a.id], f"D-{a.id} holds short of {dest} at the tube edge: pad reserved for "
                         f"D-{holder} ({_urgency_label(holder)}) landing", "global", "warning")
            elif a.id in holding_short:
                holding_short.pop(a.id, None)
            cap = speed_cap_drone.get(a.id)
            if cap and t < cap[1]:
                v = min(v, cap[0])
            if speed_cap_sector:
                cap = speed_cap_sector.get(_sector(network, a.position[0], a.position[1]))
                if cap and t < cap[1]:
                    v = min(v, cap[0])
            return v

        if centralized and airborne:  # the DTC computes every drone's velocity from reported states
            for a in airborne:
                s_c, _, _ = by_id[a.id].route.project(a.position[:2], progress[a.id])
                progress[a.id] = max(progress[a.id], s_c)
            routes_now = {a.id: by_id[a.id].route for a in airborne}
            if link.is_up(t):
                last_cmd.update(centralized_commands(
                    {i: r for i, r in reported.items() if i not in noncoop}, routes_now, progress, ref_speed, cfg,
                    lane, grid_cell))
            for a in airborne:   # non-cooperative: unseen by the DTC, follows its route on its own
                if a.id in noncoop:
                    last_cmd.update(centralized_commands({a.id: a}, routes_now, progress, ref_speed, cfg, lane, grid_cell))
            for a in airborne:
                desired[a.id] = last_cmd.get(a.id, np.zeros(3)).copy()
                if a.id in hold_at:
                    to_h = hold_at[a.id] - a.position[:2]
                    desired[a.id] = np.array([*(to_h * float(ccfg.get("hold_gain", 0.5))), 0.0])
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
            rep_n = [(by_air[j] if j in quarantined else reported[j]) for j in nbr_ids if j in reported
                     and j not in noncoop and reported[j].altitude_layer == a.altitude_layer]
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
            if noncoop and sense_r > 0:   # detect-and-avoid: no Remote ID, so only onboard sensing sees it
                for j in nbr_ids:
                    if j not in noncoop or j == a.id or j not in by_air:
                        continue
                    dz = (int(by_air[j].altitude_layer) - int(a.altitude_layer)) * layer_h
                    dj = float(math.hypot(float(np.linalg.norm(by_air[j].position[:2] - p)), dz))   # 3D range
                    if dj < sense_r:
                        if dz == 0:   # avoid in-plane only on its own layer; another layer is already separated
                            nbrs = list(nbrs) + [by_air[j]]
                        stats.intruder_detections += 1 if (a.id, j) not in sensed_seen else 0
                        if (a.id, j) not in sensed_seen:
                            sensed_seen.add((a.id, j))
                            emit("detect", [a.id, j], f"D-{a.id} sensed non-cooperative D-{j} at {dj:.0f} m (no Remote ID) "
                                 + ("→ avoiding" if dz == 0 else "→ tracking (one layer apart)"), "drone", "warning")
                            if j not in intruders_announced:
                                intruders_announced.add(j)
                                emit("detect", [j, a.id], f"Non-cooperative D-{j} detected by onboard sensing of D-{a.id} "
                                     f"— the DTC cannot see it", "global", "warning")

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
            if a.id in hold_at:   # operator / lost-link hold: loiter at the hold point
                to_h = hold_at[a.id] - p
                v_goal = to_h * float(ccfg.get("hold_gain", 0.5))
                sp_h = float(np.linalg.norm(v_goal))
                if sp_h > float(ccfg.get("hold_max_speed", 3.0)):
                    v_goal *= float(ccfg.get("hold_max_speed", 3.0)) / sp_h
                v_ref = 0.0
            elif a.id in holding_short:   # pad reserved for a more urgent landing: loiter at the tube edge
                s_h = max(0.0, route.length - pad_hold_m)
                t_h = route.tangent_at(s_h)
                hp = route.point_at(s_h) + np.array([-t_h[1], t_h[0]]) * (half_w - 2.0)
                v_goal = (hp - p) * float(ccfg.get("hold_gain", 0.5))
                sp_h = float(np.linalg.norm(v_goal))
                if sp_h > float(ccfg.get("hold_max_speed", 3.0)):
                    v_goal *= float(ccfg.get("hold_max_speed", 3.0)) / sp_h
                v_ref = 0.0

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
                if a.id in noncoop or a.id in quarantined:   # cannot negotiate without (trusted) broadcasts
                    continue
                it = copy.copy(a)
                it.velocity = desired[a.id].copy()
                intents.append(it)
            for ev in probe.resolve(intents, {a.id: a.priority for a in intents}, t, weights=health_w or None):
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
            mover = a if _rank(a) > _rank(b) else b
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
            if (remaining < 10.0 and float(np.linalg.norm(nxt.velocity[:2])) < 6.0
                    and a.id in charge_plan and f.destination == charge_plan[a.id]["pad"]):
                _start_service(a.id, nxt)
                continue
            if remaining < 10.0 and float(np.linalg.norm(nxt.velocity[:2])) < 6.0 and a.id not in holding_short:
                status[a.id] = LANDED
                nxt.velocity[:] = 0.0
                stats.arrivals += 1
                if f.destination == planned_dest[a.id]:
                    stats.delivered += 1
                    if health is not None:
                        delivered_energy.append((f.type.value, health.energy_used_wh(a.id) - energy_at_sortie.get(a.id, 0.0)))
                diverting.pop(a.id, None)
                if f.destination == planned_dest[a.id]:   # an emergency counts only at its own destination
                    etrack.on_land(a.id, t)
                if sorties and a.id not in cancelled and a.id not in quarantined:
                    _next_sortie(a.id)
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
        if health is not None:
            _health_tick(step, t, air_ids, attack_state, emit)

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
        if health is not None:
            if step - last_h_step >= h_every or step == n_steps or last_h_step < 0:
                frame["h"] = health.compact(ids)
                last_h_step = step
            sel = [i for i in (health_detail_ids() if health_detail_ids else []) if i in by_id]
            if sel:
                frame["hsel"] = {str(i): {**health.detail(i, float(np.linalg.norm(agents[i].velocity[:2])),
                                                          cruise_of(by_id[i])),
                                          "admm_weight": round(health_w.get(i, _class_w(int(agents[i].priority))), 2)}
                                 for i in sel[:4]}
        if reroutes:
            frame["reroutes"] = list(reroutes)
            reroutes.clear()
        view = _console_view()
        if view != last_console_sent[0]:
            frame["console"] = view
            last_console_sent[0] = view
        if new_flights:  # injected mid-run: the client appends these to its flight list (frame width grows)
            frame["new_flights"] = flight_manifest(new_flights)
            new_flights.clear()
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
        "id": f.agent_id, "type": f.type.value, "task": f.task, "priority": f.eff_priority,
        "origin": f.origin, "destination": f.destination, "depart_s": f.depart_s,
        "route_length_m": round(f.route.length, 1),
        "custom": f.custom, "cooperative": f.cooperative, "malicious": f.spoof_offset is not None,
        "cruise_speed_mps": f.cruise_speed, "preferred_layer": f.preferred_layer,
        **({"spoof_offset_m": list(f.spoof_offset), "spoof_start_s": f.spoof_start_s} if f.spoof_offset else {}),
        **({"health": f.health} if f.health else {}),
        "route": [[round(float(x), 2), round(float(y), 2)] for x, y in f.route.points],
    } for f in flights]
