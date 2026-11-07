# MASooda live demo (map-constrained flights)

```bash
python -m web_sandbox.server        # then open http://127.0.0.1:8765
```

## Maps

| Map | Source | Notes |
|---|---|---|
| **IITH campus (Kandi)**, the default | `data/iith_campus.geojson`, built by `scripts/build_iith_campus_map.py` from `data/iith_campus_map.jpg` | Roads, the campus perimeter (a polygon geofence) and 13 named vertiports (Hospital, Main Gate, LHC, Admin Block, Mess A/B, hostels, SNCC…) were traced by hand at about 0.95 m/px. The image is drawn as a georeferenced backdrop in the same frame. |
| Hyderabad roads | `data/hyderabad_roads_sample.geojson` (OSM, ODbL) | Major road classes; 8 auto-placed vertiports; rectangular geofence |

Pick the map with the selector on the map header, or open `/?map=hyderabad`.

## Panels

- **2.5D view (right):** a 240 m isometric window around the selected drone. It shows every altitude layer as a plane, neighbouring drones on stems at their layer height, the d_min ring and the route on its layer. Below it are the drone's stats (layer/altitude, speed/heading, remaining/ETA, nearest same-layer drone, V2V degree, DTC link and directive age) and **its own event feed**: ground holds and merge gaps, departure, DTC directives and safety-gate deferrals, ADMM conflict detected/resolved, tactical altitude shifts ("CPA alert: climb L0→L1 to avoid D-36…"), corridor-wall holds, spoofed reports filtered or accepted, loss of separation, landing, crash.
- **Network theory · DTC + V2V:** the DTC (Drone Traffic Controller, the P4 overseer) is the hub node with directive links to every airborne drone; these turn red and dashed when the link is down. V2V radius-graph edges are drawn at drone positions. The live metrics are nodes/edges, average degree, density, transitivity (clustering), maximum degree centrality and the hub drone, components, giant-component share, and algebraic connectivity λ₂. Over time it plots DTC coverage, directive age, transitivity, degree, centrality and giant component, with the outage and attack windows shaded.
- **Selecting a drone:** click it on the map, click its node in the network graph, use the dropdown, or click a log entry. ◎ follows the selected drone.
- **Crashes:** same-layer drones closer than 2 m (`safety.collision_radius_meters` if present) collide. Both are marked lost (✕ on the map) and counted in *Crashes*. Loss-of-separation episodes (< d_min) are counted as *Near misses*.

## Governance additions in this version

- **Tactical altitude shift:** when the CPA check predicts a miss below d_min within 3 s, the lower-priority drone climbs or descends one layer if that layer is clear (never into the emergency layer unless it is an emergency). Any ADMM conflict involved is noted in the event text.
- **Merge-gap departure:** a drone stays on its pad until the junction where its approach leg joins the corridor is clear on its layer.
- **Polygon geofence** (IITH campus boundary): positions outside are projected back inside.

## What changed and why

Before: the Hyderabad map was only a picture behind the simulation. The engine
flew drones in an abstract 0–1500 m corridor frame, so roads, map edges and
vertiports placed no constraints on the paths.

Now (`simulation/road_network.py`, `simulation/route_engine.py`):

| Layer | Implementation |
|---|---|
| Map → graph | Major OSM road classes (motorway…tertiary) are projected to local metres and snapped into a routable graph. The largest connected component is kept (1,532 junctions). |
| Vertiports | 8 pads chosen by farthest-point sampling and set back about 45 m from the corridor, with an approach leg. Roles: hub, hospital and depot. |
| Routing | Dijkstra shortest path from pad to pad along the corridor graph. Emergency flights go to hospitals and deliveries leave depots. |
| **Boundary conditions** | **Corridor tube**: each tick, a drone more than `corridors.width_meters/2` from its route centreline is projected back onto the tube wall and its outward velocity is removed. **Geofence**: drones are clamped to the map extent the same way. |
| P3 local behaviour | Pure-pursuit route following with a keep-left lane offset, car-following gaps (`d_0`, `h`), boids separation/alignment, and CPA avoidance. |
| P2 ADMM | `resolve_all_conflicts` runs anywhere on the map (`merge_zone_only` is turned off for this mode). |
| P4 overseer | `GlobalOverseer` (priority-aware) runs per airspace sector (3×2 grid) through an `OverseerLink` that can fail. It applies a semicircular-rule layer request and keeps an emergency-reserved layer. A safety gate defers re-layering into a layer that isn't locally clear. |
| P5 | Spoofing injection plus trusted-range / W-MSR defence, or no defence. |
| P6 | Layer-aware STL robustness ρ(t) = min 3D separation − d_min. |

The browser starts a run (`POST /api/runs`), and frames stream back
(`GET /api/runs/<id>/frames`) while the simulator computes them, roughly
10–15× faster than real time for 60 drones.

## Verification (seed sweep, 180 s)

- 30 runs (5 seeds × 30/60/90 drones, plus attack, outage and undefended
  variants at 60): 29 have zero separation violations. The exception is a
  90-drone stress run (seed 11) with 5 ticks at a minimum of 5.6 m, a
  head-on meeting on the shared emergency layer, which the STL monitor flags.
- All six UI presets at their defaults (60 drones, 240 s): 0 violations.
- `tests/test_route_mode.py` asserts that every airborne drone stays inside
  its tube and the geofence on every tick.

Limitations: OSM centrelines without `oneway` tags; corridors are a research
planning backbone, not approved airspace.
