# MASooda web live demo — integration plan (Phase 0)

Branch: `p2_week7` (author: R Lalith Vishnu), created from `main` @ `91cca35` (which contains `p2_week6` and the Week 6 work).
Nothing below has been implemented yet. This document is the Phase 0 deliverable: what was read,
what was measured, and how each phase will plug into the code. The novelty focus (health/BMS-aware
traffic management) is grounded in `docs/RESEARCH_GAP_HEALTH_AWARE_UTM.md`.

## 1. What was read (Phase 0a)

| Area | Files | State on `main` |
|---|---|---|
| Live engine | `simulation/route_engine.py`, `simulation/road_network.py` | Identical to `p2_week6` |
| Web | `web_sandbox/server.py`, `app.js`, `live_demo.html`, `styles.css`; `simulation/scenario_manifest.py` | Identical to `p2_week6` |
| P3 | `local_behavior/boids.py`, `local_behavior/formation_metrics.py` | Corridor/+x based |
| P6 | `verification/metrics.py`, `stl_monitor.py`, `live_monitor.py`, `near_collision.py` | **Horizontal (x,y) distance only** |
| P4 | `simulation/priority_metrics.py`, `simulation/overseer.py`, `simulation/overseer_link.py` | Exit-x / corridor based |
| P2 | `conflict_resolution/adapter.py`, `profiling.py`; `simulation/telemetry.py` | Fits route mode (see §4) |
| P5 | `resilience/defense.py`, `wmsr.py`, `attack.py`, `consensus.py`, `decentralized_undefended.py` | Fits; W-MSR meaning needs a decision (§7) |
| Baselines / Week 6 | `simulation/centralized.py`, `experiments/week6.py`, `week6_common.py`, `visualization/dashboard.py` | Corridor based |

## 2. Benchmark of the current route engine (Phase 0b)

IITH campus map, default seed 42, 180 s at dt = 0.1 s, defaults (DTC on, ADMM on, defence on, no
attack), departure window 90 s, frames streamed every 2nd tick as the server does. Host: 2-vCPU
Intel Xeon @ 2.10 GHz, Python 3.13 (Claude's cloud workspace; your laptop will differ). Timings
come from an instrumented copy of `route_engine.py` kept in the scratch area; the repo file is
unchanged.

| | Fleet 60 | Fleet 150 |
|---|---|---|
| Peak airborne drones | 46 | 81 |
| Wall time (engine + JSON serialisation) | 11.4 s → **158.6 ticks/s** | 33.1 s → **54.3 ticks/s** |
| Engine only, ms per tick | **5.61 ms** (17.8× real time) | **16.76 ms** (6.0× real time) |
| Frame size (JSON, mean / max) | 2.72 / 3.26 KB | 5.37 / 6.21 KB |
| Whole run streamed (901 frames) | 2.39 MB | 4.72 MB |
| JSON serialisation per streamed frame | 1.37 ms | 3.26 ms |
| Arrivals · ADMM events · violation ticks · crashes | 46 · 249 · 0 · 0 | 93 · 1525 · 0 · 0 |

Per-tick breakdown (ms per tick, engine phases in loop order):

| Phase | Fleet 60 | Fleet 150 | Notes |
|---|---|---|---|
| Local behaviour (route following + boids + CPA + defence) | 2.47 | 5.72 | defence alone 0.34 / 1.09; boids separation+alignment 0.15 / 0.44 |
| Dynamics + tube/geofence boundary | 1.36 | 2.77 | per-drone `RoutePath.project` twice per tick |
| Departures (pad + merge-gap checks) | 0.16 | **3.94** | O(queued × airborne) Python loops — biggest scaling problem |
| Neighbour search (`build_radius_graph`) | 0.51 | 1.90 | O(N²) |
| Attack injection | 0.34 | 0.65 | copies every agent even with no attack |
| ADMM (`resolve_all_conflicts`) | 0.23 | 0.64 | |
| Frame build | 0.19 | 0.47 | |
| Network metrics (`_graph_metrics`, λ₂ eigen-solve) | 0.20 | 0.34 | |
| Safety check (pairwise, crash / LoS) | 0.14 | 0.28 | |
| DTC update | 0.02 | 0.04 | every 2 s |

Frame payload by field at 150 drones (KB per frame): x 1.05, y 1.00, progress 0.83, speed 0.66,
stats 0.48, layer 0.29, status 0.29, edges 0.21, net 0.20, dtc 0.12, events 0.09.

**What this means for Phase 1:** 150 drones runs at 6× real time on this host, so the 500 target
depends on removing the O(N²)/O(Q·A) loops: departures, neighbour search, CPA/separation, the
layer-transition check and the safety check. All of these are spatial queries that a uniform grid
hash solves. Frame size scales linearly. Quantising (positions in decimetres as ints,
progress/speed as small ints) and sending `stats` only when they change should cut it by roughly
2–3×. These are estimates, not measurements, and Phase 1d will measure them.

## 3. Frame schema v2 (Phase 1c + 2 + 3B)

```jsonc
{
  "v": 2, "k": 900, "t": 90.0,               // tick index (deterministic replay key) and sim time
  "xy": [x0, y0, x1, y1, ...],               // int decimetres, all drones
  "ls": [..],                                // status*8 + layer   (status 0 queued,1 air,2 landed,3 crashed,4 grounded-by-DTC)
  "spd": [..], "prog": [..],                 // dm/s ints, per-mille ints
  "hp": [..], "bms": [..], "tmax": [..],     // health: SoC % int, BMS code 0..3, max temp °C int   (Phase 3B)
  "edges": [[i, j], ...],                    // capped at web.max_edges_per_frame (sampled, flagged when truncated)
  "rho": 7.3,                                // layer-aware safety robustness (see §5, P6 decision)
  "admm": {"n": 3, "it_mean": 41.0, "it_max": 88, "ms": 0.9, "fb": 0},       // Phase 2a
  "dtc":  {"up": true, "age": 0.4, "conn": 81, "cmds_pending": 0},
  "net":  {...},                             // unchanged metrics, sent every frame
  "stats": {...},                            // only when changed (delta), full every web.stats_full_every frames
  "events": [...],                           // unchanged shape, never downsampled
  "trust": [{"spoofer": 34, "reported": [..], "true": [..], "est": [..], "status": "corrected"}]  // Phase 2e
}
```
Selected-drone detail (full health, per-cell voltages, last ADMM negotiation, neighbour trust table)
comes from a separate request so frames stay small at 500 drones:
`GET /api/runs/<id>/drones/<drone_id>?from=<k>`.

Memory cap: `web.max_frames_in_memory`. When it is exceeded, older frames are thinned to every 2nd,
then every 4th frame, and so on. Events are always kept.

## 4. Command API (Phase 4)

```
POST /api/runs/<id>/commands   {type, targets: [ids] | {"filter": {...}}, params: {...}, reason}
  -> 202 {command_id, status: "sent", tick_submitted}
GET  /api/runs/<id>/commands   -> [{command_id, type, targets, params, reason,
                                    status: sent|delivered|acknowledged|failed|expired,
                                    tick_sent, tick_delivered, tick_applied, outcome}]
```
- **Queue:** the server pushes to a thread-safe `queue.Queue` owned by the run. The engine drains
  it at the *start* of a tick, so each command is applied at a defined tick index `k`. This keeps
  runs deterministic.
- **Link:** a command is *delivered* only while `OverseerLink.is_up(t)`. During an outage the
  policy is `web.commands.outage_policy: queue | drop`, with `queue_ttl_s`; a queued command that
  expires becomes `expired`. *Acknowledged* means the drone accepted it this tick. *Failed* means
  it was infeasible (for example, an energy check failed or no pad was reachable), with a reason.
- **Replay:** the run record stores `{manifest, resolved_config, seed, command_log[(k, command)]}`.
  Replay re-runs the engine and injects each command at its logged `k`. A test asserts identical
  frames.
- **Types** (params): `reroute{dest|via}`, `ground_now{}`, `hold{}`, `resume{}`, `rtb{}`,
  `change_layer{layer}`, `speed_limit{v, expires_s, sector?}`, `priority{level}`,
  `tfr{polygon, start_s, end_s}`, `ground_stop{sector, release_s?}`, `quarantine{}`,
  `lost_link_policy{continue|hold|rtb|land}`, `divert_charge{pad, mode: charge|swap}`,
  `fleet_health{rule: ground_bms_critical | recall_below_soc, threshold}`. Every movement command is
  checked against the energy reserve (Phase 3B) **before** it is sent. If it is infeasible, the
  console shows the nearest reachable pad instead.

## 5. Where each unlinked component plugs in

| Component | Shared function(s) | Fits the road model? | Route-mode plan (same definition) | Phase |
|---|---|---|---|---|
| **P2 ADMM convergence timer** | `profiling.ADMMRecorder`, `telemetry.admm_solver_records` | **Yes.** It patches `ADMMSolver.solve`. | Wrap `resolve_all_conflicts` per tick and read records → `frame.admm`; per-drone last negotiation from event groups. **Caveat:** the patch is process-global, so concurrent runs in one process would mix records. The server runs one run at a time; tag records with the run's thread id and filter them. | 2a |
| **P4 emergency compliance** | `priority_metrics.PriorityLogger`, `nominal_time`, `priority_summary` | **No.** It uses `exit_zone_x`, corridor load and abstract corridors. | New `simulation/route_priority_metrics.py`. *Compliance* = at each DTC period, the emergency drone's (sector, layer) load ≤ `corridors.capacity`, which is the same rule applied to sectors. *Nominal time* = route length / `v_cruise`, the same formula with the route instead of the corridor. *Delay* = arrival − depart − nominal. Plus "forced to yield" (it was the ADMM/CPA mover) and "left reserved layer". | 2b |
| **P3 merging and platoons** | `boids.cohesion`, `merge_adjustment`, `corridor_following`, `formation_metrics.merge_outcomes` | **No.** They use `corridor_of(y)`, the +x axis and the merge-zone x range. | New `local_behavior/route_behavior.py` with the same parameters (`merge_gap`, `d_0`, `h`, `k_s`, `k_v`, `w_coh`), measured along the road segment's arc length. *Merge attempt* = joining a corridor edge at a junction (approach leg or turn). *Success* = joined with no loss of separation within the merge window. *Headway* = gap to the leader on the same edge and layer versus `d_0 + h·v`. `separation` and `alignment` are already reused unchanged. | 2c |
| **P6 single safety definition** | `metrics.robustness_series`, `stl_monitor`, `live_monitor` | **Not layer-aware.** `metrics.robustness_series` and `live_monitor` slice `[:2]`. `stl_monitor` uses the Cartesian norm of whatever D it gets. | **Stop-and-ask item (rule 2d), see §7.** `route_engine.layered_min_separation` uses 3D metric distance with z = layer × `layer_height`. | 2d |
| **P5 W-MSR visible** | `defense.defend_neighbor_reports` → `DefenseResult(kept, dropped_ids, wmsr_estimate)` | **Yes**, called already. | Keep the result per receiver and send kept / dropped / corrected status per report in `frame.trust`. `defense.py` is unchanged. **Meaning of the estimate needs a decision (§7).** | 2e |
| **Architecture selector** | `centralized.run_centralized`, `decentralized_undefended` | Centralized: **no** (corridor centres, +x). Undefended: **yes** (it is `use_overseer=False, defended=False`). | New `simulation/route_centralized.py`: the DTC sees the full *reported* state and commands every velocity (route following, `d_0 + h·v` headway, priority-weighted separation with the same factor 1 / 0.5 / 0 rule, trusts reports, no ADMM). Decentralized = no DTC + ADMM + defence. Initial-conditions hash = SHA-256 of `flight_manifest` + seed, shown in the UI. | 2f |
| **Telemetry rows** | `telemetry.build_tick_info` | Partly. It needs `corridors` for occupancy. | Route-mode builder with the same `INFO_KEYS`; occupancy keyed by sector id. | 2a/2g |
| **Resilient consensus** | `consensus.run_wmsr_consensus` | Yes (scalar). | Optional (R2/R4): fleet consensus on a lost-link policy or trust score during an outage. Not wired unless chosen. | R2/R4 |
| **Week 6 outputs** | `experiments/week6.py`, `visualization/dashboard.py` | Corridor runs. | Read-only "Experiments" tab that lists `outputs/week6/**` figures and README tables (open question §7); route-mode batch runner in Phase 7. | 2g/7 |
| **Dead routes** | `/prototype`, `/api/simulate` | — | Remove `/prototype`; keep `/api/simulate` with a `# legacy` comment. | 2g |

Untouchable files (rule 3) are only *called*: `verification/metrics.py`, `stl_monitor.py`,
`live_monitor.py`, `resilience/defense.py`, `attack.py`, `wmsr.py`, `simulation/priority_metrics.py`,
`overseer_link.py`, `conflict_resolution/detection.py`, `solver.py`.

## 6. New configuration (rule 5)

```yaml
web:
  max_fleet: 500            # set after the Phase 1d benchmark
  max_duration_s: 3600
  frame_stride: auto        # aim for <= web.target_frames_per_sim_s at 1x
  target_frames_per_sim_s: 10
  max_frames_in_memory: 20000
  max_edges_per_frame: 600
  poll_batch: 400
  stats_full_every: 25
  grid_cell_m: 40           # spatial hash cell (>= comm radius)
  commands: {outage_policy: queue, queue_ttl_s: 30}
drone_health:               # Phase 3B — equations and defaults shown for approval first
  ambient_c: 35.0
  EMERGENCY: {mass_kg: ..., capacity_wh: ..., cells_s: ..., r_int_ohm: ..., thresholds: {...}}
  EVTOL: {...}
  DELIVERY: {...}
```

## 7. Open questions (need your answer before the phase that uses them)

1. **P6 (Phase 2d):** `verification/metrics.py` is still horizontal-only. Options: (a) wait for your
   teammate's layer-aware fix; (b) keep `route_engine`'s 3D layer-aware definition and label it in
   the UI and docs as "layer-aware; differs from `metrics.robustness_series`"; (c) call `stl_monitor`
   with (x, y, layer × height) positions. This gives the same Cartesian definition without editing
   the file, but `live_monitor`/`metrics` would still differ.
2. **P5 (Phase 2e):** `wmsr_estimate` is the *receiver's own-position* estimate from neighbour
   reports, not an estimate of the spoofer. Show it per receiver as "own-position consensus
   vs truth", or add a route-mode spoofer-position estimate (W-MSR over the corrected positions of
   all receivers) in a new module?
3. **P4 nominal time:** the shared definition is distance / `v_cruise`. Emergencies fly at 1.2 ×
   `v_cruise` in route mode, so their delay can be negative. Keep the shared definition, or use the
   type's own cruise speed and say so?
4. **Week 6 outputs in the web UI:** a read-only gallery of existing figures and tables, or only the
   new Phase 7 route-mode experiments?
5. **Phase 1 target host:** benchmark limits on your laptop (Windows) or on this cloud host? The
   limits in config should match the machine that will run the demo.

## 8. Phase 1 results (scale)

Same host as §2 (2-vCPU Xeon @ 2.1 GHz), IITH map, seed 42, defaults, measured the way the server
streams (compact v2 frames at the adaptive stride, JSON serialisation included).

| Fleet × duration | Grid | Ticks/s | × real time (whole run / worst 5 s) | Peak airborne | Frame KB | Stream KB per sim-s |
|---|---|---|---|---|---|---|
| 60 × 180 s | on | 189.5 | 19.0 | 46 | 1.97 | — |
| 150 × 180 s | on | 87.9 | 8.8 | 81 | 3.91 | — |
| 100 × 300 s | off / on | 152.9 / 169.4 | 15.3 / 16.9 (7.2 / 9.2) | 62 | 2.77 | 13.8 |
| 250 × 300 s | off / on | 36.6 / 63.4 | 3.7 / 6.3 (1.8 / 3.8) | 114 | 5.90 | 29.5 |
| 500 × 300 s | on | 34.4 | **3.4 (2.3)** | 177 | 11.08 (stride 3) | 37.0 |

- Grid on and grid off give identical runs (same stats, events and positions;
  `tests/test_route_spatial.py`). At 150 drones: 54.3 → 87.9 ticks/s compared with Phase 0, and
  frames 5.37 → 3.91 KB (27% smaller, less than the 2–3× estimated in §2).
- 500 drones holds ≥ 1× real time throughout, so `web.max_fleet = 500` and
  `web.realtime_max_fleet = 500` *for this host*. Re-measure on the demo laptop and lower
  `realtime_max_fleet` if needed; the UI warns above it.
- At 500 the campus is limited by vertiport capacity, not compute: 464 ground holds and a peak of
  177 airborne. At 250 and 500 the runs show 2–3 near misses (25–26 violation ticks), whether the
  grid is on or off. This is a traffic-density finding for later phases, not a Phase 1 regression.
- Remaining cost at 500 (ms/tick): defence 2.5, ADMM 2.3, dynamics 1.4, boids 1.0, grid queries ≈ 1.2.

## 9. Phase 2 results (every workflow component in the live demo)

Decisions taken before coding (answers to §7): safety keeps the route engine's layer-aware 3D
definition and is labelled in the UI; the P5 view adds a spoofer-position estimate in a new module;
emergency nominal time uses the type's own cruise speed.

| Step | Module (new unless noted) | Shared code reused | Route-mode deviation |
|---|---|---|---|
| 2a ADMM timer | `simulation/admm_probe.py` | `ADMMRecorder`, `resolve_all_conflicts` (serialised by a lock: the recorder patches the class) | ms p95 from a log histogram (±1 bin ≈ 12 %); iteration p95 exact |
| 2b P4 compliance | `simulation/route_priority.py` | definitions of `priority_metrics.py` | cell = (sector, layer) instead of corridor; nominal = route length / type cruise speed; travel from scheduled departure (holds count) |
| 2c P3 merging | `simulation/route_formation.py` | `merge_gap`, `k_v`, `d_0`, `h`, `r_sep`, `w_coh`, `r_plat`; `boids.separation/alignment` | target corridor = outgoing road after a degree ≥ 3 junction; cohesion along the road and off inside `max(r_sep, d_0 + h·v)` (with plain `r_sep` it pulled drones inside their headway: ADMM groups ×4); platoon definition is new (none in `formation_metrics.py`) |
| 2d P6 safety | — | — | kept 3D layer-aware; UI and run manifest state that `metrics.py` is horizontal-only |
| 2e P5 W-MSR | `resilience/spoofer_estimate.py` | `defend_neighbor_reports` (unchanged), `wmsr_vector` | estimate = W-MSR over the receivers' range-corrected positions, anchored at their median |
| 2f architectures | `simulation/route_centralized.py`, `ARCHITECTURES` in `route_engine.py` | control law of `centralized.py`; switch sets of `decentralized_undefended.py` | lane-following replaces corridor centreline |
| 2g export/replay | `web_sandbox/run_export.py`, `GET /api/runs/<id>/export` | — | `/prototype` removed; `/api/simulate` marked legacy |

Architectures (IITH, 60 drones, 180 s, seed 42, spoofing attack, same IC hash `6f591df49df4`):

| Architecture | Arrivals | Crashes | Near misses | Violation ticks | Min sep (m) |
|---|---|---|---|---|---|
| hierarchical (merging off / on) | 46 / 46 | 0 / 0 | 0 / 0 | 0 / 0 | 12.87 / 12.90 |
| centralized | 42 | 1 | 6 | 93 | 1.42 |
| decentralized | 46 | 0 | 0 | 0 | 12.90 |
| decentralized, undefended | 46 | 0 | 0 | 0 | 11.12 |

W-MSR spoofer estimate (25 m spoof offset, hierarchical, 180 s): at 150 drones the estimate is
closer to the truth than the broadcast in 88 % of ticks with one receiver (10.5 m vs 25 m), 100 %
with two (16.4 m) and 100 % with three or more (7.0 m). At 60 drones there is usually one receiver
and the estimate is no better than the broadcast (25.7 m): `defense.py` corrects only the range,
along the false bearing, so one receiver cannot remove a sideways offset.

Cost (worker, frames included): 250 × 300 s 54.4 ticks/s (5.4×; Phase 1 63.4), 500 × 300 s
32.8 ticks/s (3.3×; Phase 1 34.4). Frames grew to 8.5 KB (250) and 16.5 KB (500); the stream at 500
is 55 KB per sim-second, above `web.max_kb_per_sim_s = 40` because `est_bytes_per_drone_frame`
(22 B) no longer includes the Phase 2 fields.

## 10. Phase 3 results (custom drone input)

- **Rows**: `simulation/scenario_manifest.py` gains `validate_route_drones` (all rows checked, one
  error lists every problem as `row n (D-id): …`), JSON (`masooda-drones` v1) and CSV import/export.
  Fields: type, priority, origin/destination vertiport, departure, cruise speed (≤ v_max), preferred
  layer (emergency layer only for EMERGENCY), cooperative, malicious + offset [dx, dy] + start, and
  the health inputs (battery Wh, initial SoC %, SoH %, payload kg, scheduled fault type + time).
  Health inputs are validated and carried on the flight; the Phase 3B model will use them.
- **Engine**: custom drones run with the random fleet. A non-cooperative drone sends no reports: it is
  invisible to other drones' boids/CPA, to the DTC and to ADMM (it still listens and avoids). A custom
  spoofer broadcasts its own offset vector (applied after `inject_attack`; `attack.py` unchanged).
- **Command channel** (first type of the Phase 4 API): `POST /api/runs/<id>/commands
  {type: "add_drone", drone}` → validated, queued, applied by the engine at the start of the next
  tick; the log records `tick_applied`, and `scripted_commands(log)` replays it exactly (test).
  New drones reach the page as `new_flights` in frames (kept through thinning).
- **Pacing**: while a page is watching, the simulator stays at most `web.interactive_lead_s` (5 s)
  ahead of playback, so "Add drone now" lands near the time on screen. Without a watcher (tests,
  closed tab after `web.watcher_timeout_s`) it runs ahead freely. Pacing changes only when ticks are
  computed, not their content.

## 11. Phase 3B results (drone health)

Model as approved in `docs/DRONE_HEALTH_MODEL.md` (momentum-theory power with hot-air density, Rint
battery, per-cell BMS, lumped temperatures, path-loss link, GNSS HDOP), in
`simulation/drone_health.py`, parameters in `drone_health:`. Changes made during implementation
(also recorded in the model document):

- eVTOL `c_max` 4C → 5C: at 4C every eVTOL hover raised OVER_CURRENT warnings.
- `overheating_heat_frac_hover` 0.15 → 0.6: with 0.15 the fault never reached WARNING on a 2–3 min
  campus flight.
- Pre-flight check: a drone already CRITICAL, or unable to reach its destination with the reserve,
  stays on its pad (event + `grounded_preflight`).
- A pad within one approach leg (40 m) is reached by a straight leg: the corridor-graph route
  from the pad just left was an out-and-back that the drone circled until its battery failed.

Finding: with the approved 30 s hold at overheating CRITICAL, the faulted delivery drone's pack goes
from 65 °C to the 75 °C FAULT limit about 8 s after it starts diverting, and it lands in place.
Diverting at the first overheating CRITICAL would reach the pad.

Measured (IITH, seed 42, 300 s, worker incl. frames): 250 drones 48.4 ticks/s (4.8×, Phase 2
54.4), 500 drones 26.5 ticks/s (2.6×, Phase 2 32.8); frames 9.2 / 17.7 KB. Random fleets
(SoC 35–100 %) on campus routes: 0 diversions, 0 forced landings, 0 depleted, max pack 39 °C,
energy per delivered drone 768 Wh (250) and 960 Wh (500, more eVTOLs delivered).

## 12. Phase 4 results (DTC operator console) and weather controls

- `simulation/dtc_console.py`: command validation, polygon geometry, road-graph planning that avoids
  restricted areas. The command handlers are in `route_engine.py` (they need the run state).
- **Delivery.** `POST /api/runs/<id>/commands` → queue → applied at the start of the engine's next
  tick (`tick_received`).
  - Console commands cross the DTC link (`tick_delivered`). While the link is down they are
    `queued` until `dtc_console.queue_ttl_s` (then `expired`), or `lost` with
    `outage_policy: drop`.
  - Each target is `acknowledged` or `failed` with a reason, and every outcome goes to the
    governance log.
  - Architectures without a DTC refuse console commands.
  - Replay re-applies commands at `tick_received`, so frames and events are identical (test).
- **All 13 command types:**
  - reroute (destination and/or via point);
  - ground now (nearest pad within `ground_now_max_pad_m`, else land in place; queued drones are
    cancelled);
  - hold / resume (loiter; for queued drones, a departure hold);
  - return to base;
  - change layer (layer-transition safety check, pinned against later DTC allocation);
  - speed limit per drone or per sector, with expiry;
  - priority (P0 = emergency privileges: the DTC treats it as EMERGENCY);
  - restricted area / TFR (polygon, start/end): routes avoid it, drones inside are rerouted out or
    landed, departures inside are held;
  - sector ground stop with optional release time, and release;
  - quarantine (reports ignored network-wide: neighbours use sensed positions; excluded from DTC
    and ADMM; ordered to land);
  - lost-link policy, fleet default and per drone (continue / hold / rtb / land; holds are
    released when the link returns);
  - divert to charge or swap (`charge_c_rate`, `charge_target_pct`, `swap_time_s`; the drone
    resumes its mission afterwards);
  - fleet actions: ground all BMS CRITICAL, recall below X % SoC.
- **Energy check.** Movement commands are checked against the reserve: `dry_run` returns
  feasibility per target with the nearest reachable pad. The page shows the warning first and
  offers "send to the nearest reachable pad instead", "send anyway" or cancel. Without `force`,
  the engine refuses an infeasible movement.
- **UI:**
  - selection by click, Shift+click, Ctrl+drag box or filter (type / sector / layer / status);
  - right-click menu, command bar and keyboard shortcuts (H R G B Q [ ] Esc);
  - restricted areas drawn on the map;
  - inline confirmation for fleet-wide actions;
  - command history with status and per-drone results;
  - map overlays for restricted areas, ground stops, holds, quarantine and charging.
- **Weather (user request).** Temperature with presets (winter 15 °C, pre-monsoon 35 °C,
  heat wave 42 °C) and wind speed/direction feed `drone_health.ambient_c` / `wind_mps` (validated:
  −20…55 °C, ≤ 15 m/s). Temperature drives air density (hover power +4.6 % at 42 °C vs 15 °C),
  battery resistance and the thermal models. Wind changes airspeed and power, not the drones'
  motion.
