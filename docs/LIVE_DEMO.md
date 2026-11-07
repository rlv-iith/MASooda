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

## Phase 2 panels and controls

- **Architecture** selector: hierarchical (MASooda), centralized (the DTC computes every velocity,
  no ADMM, trusts reports), decentralized (no DTC, ADMM + defence), decentralized undefended. The
  scenario header shows the initial-conditions hash, identical across architectures for the same
  seed, fleet and map.
- **P2 · ADMM convergence timer** (bottom): iterations (mean/max) and solve time per frame,
  run totals with p95, fallback (non-converged) ticks; the drone card shows the drone's last
  negotiation. Solve time is wall-clock and is the only non-deterministic number.
- **Emergency compliance** KPI and a per-emergency line in the drone card: delay vs nominal free-flow
  time, yields (ground hold / altitude shift / gated directive), time on the reserved layer.
- **Junction merges** KPI and map rings at junctions with a merge in progress (amber: the gap rule
  is slowing the merging drone by `1 - k_v`); platoon count and time headway.
- **Spoofing view**: for each spoofer the map shows its broadcast position (dashed purple) and the
  W-MSR estimate fused from the receivers' corrections (green ×); the drone card lists each
  neighbour report as kept / corrected / unverified (or accepted, when the defence is off).
- **Safety definition**: min separation and ρ(t) are layer-aware 3D (route engine);
  `verification/metrics.py` is horizontal-only, so experiment numbers differ.
- **⤓ Run / ⤒ Load** (top bar): download the run as JSON (manifest, resolved config, command log,
  per-frame KPIs, events, frames) and replay it later without re-simulating.

## Custom drones (Phase 3)

The **Custom drones** card builds drones before launch: type, priority, origin/destination
(dropdown or ◎ then click a vertiport on the map), departure, cruise speed, preferred layer,
cooperative / malicious (+ spoof offset) and health inputs with an optional scheduled fault. They fly
together with the random fleet (fleet size 0 = custom drones only). **Import** reads JSON or CSV
(every bad row is listed), **⤓ JSON / CSV** export the list. During a run, **⚡ Add drone now**
injects the form as a command; the drone departs at the simulator's next tick (the simulator stays
at most 5 s ahead of playback while the page is open).

## Drone health (Phase 3B)

Every drone carries a battery/BMS/thermal model (`docs/DRONE_HEALTH_MODEL.md`). The map rings
drones by BMS status (amber warning, red critical/fault), draws a battery glyph below 30 % SoC and
⊘ where a drone landed in place. The drone card's **Health** tab shows SoC, voltage, current and power,
energy/time/range left, SoH, per-cell voltages, pack and motor temperatures against their limits,
BMS status and fault codes, DTC link RSSI and packet loss, GNSS fix/HDOP, and SoC/temperature over
time. Full detail streams for the selected drone (a few seconds behind selection while live).
**Fleet health** lists counts by BMS status, the lowest-charge airborne drones and alerts from the
last 60 s. Onboard responses (pre-flight check, divert on low reserve or CRITICAL, land in place on
FAULT, speed limit when hot) and the DTC right-of-way rule appear in the governance log with
severity. Schedule faults from the Custom drones form.

## DTC operator console (Phase 4) and weather

The **DTC console** card issues real ATC/UTM-style commands to the selected drones:
- **Selection:** click, Shift+click, Ctrl+drag a box, or the filter.
- **Commands:** hold/resume, ground now, return to base, layer change, reroute (with a via point
  picked on the map), speed limits (drone or sector), priority, quarantine, battery swap/charge,
  lost-link policy, restricted areas drawn on the map, sector ground stops, and fleet health
  actions.
- **Energy check:** movement commands are checked against each drone's energy first. Infeasible
  ones show the nearest reachable pad.
- **Delivery:** commands travel over the DTC link (queued during an outage). The history panel
  shows sent / queued / acknowledged / failed / expired.
- **Shortcuts:** H R G B Q, [ ] layer, Esc. Right-click a drone for a menu.

**Weather** (Scenario card): temperature presets and wind for the battery/thermal/air-density model.

## Scenario presets (Phase 5)

The Scenario card has a **Scenario preset** list with ten scripted IITH scenarios: medical
emergency, vertiport congestion, VIP restricted area, GPS spoofing, DTC outage, weather cell,
non-cooperative intruder, battery failure, heat wave and 60-minute operations. Each shows its
description and timeline before you press **Run this preset**. Scripted commands appear in the
command history like operator commands, and you can still give your own. Presets with variants
(DTC outage: continue / hold / RTB; heat wave: 44 °C / 30 °C) also run the other variants in the
background and fill a comparison table under the KPIs.

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
