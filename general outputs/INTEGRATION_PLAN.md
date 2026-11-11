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
Intel Xeon @ 2.10 GHz, Python 3.13 (cloud workspace; your laptop will differ). Timings
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
