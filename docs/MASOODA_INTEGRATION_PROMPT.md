# MASooda — Final integration prompt (web live demo = the whole project)

Paste everything inside the code block into your coding session. It works in phases and stops for your OK after each one.

```
GOAL
Make the web live demo (web_sandbox/ + simulation/route_engine.py, IITH and Hyderabad maps) the single,
complete front end of MASooda. Every workflow component (P1–P6) must be visible and working in it.
Then raise its fleet/time limits, add custom drone input, give every drone a health profile (battery, BMS,
temperatures, link/GNSS quality), and add a DTC operator console with real-world air-traffic-control commands.
Then offer research features for an IEEE paper.

CURRENT STATE (verified; re-check before relying on it)
- The live demo streams frames from simulation/route_engine.py:simulate_routes via web_sandbox/server.py
  (/api/runs, /api/runs/<id>/frames, /stop). Limits: MAX_FLEET = 150, MAX_DURATION_S = 900, FRAME_STRIDE = 2,
  hard-coded in server.py.
- route_engine already uses: step_dynamics, build_radius_graph/build_knn_graph, boids.separation + alignment,
  resolve_all_conflicts (ADMM everywhere, merge_zone_only forced off), GlobalOverseer (priority_aware per
  sector x layer), OverseerLink (outage), inject_attack/apply_attack, defend_neighbor_reports.
- NOT linked to the live demo:
  * P3: cohesion, corridor_following, target_corridor, active_corridor, merge_adjustment,
    compute_desired_velocity, local_behavior/formation_metrics.py (merging / platoon headway)
  * P6: verification/stl_monitor.py, live_monitor.py, metrics.py, near_collision.py. route_engine has its
    own layer-aware 3D robustness (layered_min_separation), so demo and experiment numbers use DIFFERENT
    safety definitions.
  * P4: simulation/priority_metrics.py (compliance rate, emergency delay); no compliance shown.
  * P2: ADMM iterations / solve time (conflict_resolution/profiling.py ADMMRecorder, simulation/telemetry.py);
    the UI only shows event counts, but the README demo plan promises an "ADMM convergence timer".
  * P5: the W-MSR estimate is computed but not shown or used; resilience/consensus.py unused.
  * Baselines: simulation/centralized.py has no route-mode equivalent; "decentral" preset only switches the
    DTC off; resilience/decentralized_undefended.py unused.
  * Week 6 outputs (E1–E6, visualization/dashboard.py, telemetry) are not reachable from the web.
  * Dead routes: /prototype serves a missing index.html (404); /api/simulate is never called by the page.

RULES (apply to every phase)
1. Do ONLY the steps of the current phase. After each phase STOP, report, and wait for my "OK" before
   starting the next one. Never start optional work on your own.
2. If anything is unexpected (a test unrelated to your change fails, a shared function doesn't fit the road
   model, a target can't be met), stop and ask. Don't work around it silently.
3. Don't modify my teammate's bug-fix files: verification/metrics.py, verification/stl_monitor.py,
   verification/live_monitor.py, resilience/defense.py, resilience/attack.py, resilience/wmsr.py,
   simulation/priority_metrics.py, simulation/overseer_link.py, conflict_resolution/detection.py,
   conflict_resolution/solver.py. Call them; if one blocks you, ask.
4. Changes to simulation/engine.py, main.py, experiments/runner.py must be opt-in additions with default
   behaviour unchanged. The abstract engine and the Week 6 experiments must keep working.
5. Every new limit, threshold or default goes in configs/base_config.yaml under a new `web:` section (or the
   existing relevant section). Nothing hard-coded in server.py or app.js except UI layout.
6. Determinism: same seed + same scenario + same command log must reproduce the same frames. Every
   operator command is logged with its tick so a run can be replayed exactly.
7. Tests: write tests for each new module and run ONLY those test files plus the existing tests of files you
   changed. Never run the full test suite. Don't run tests while a benchmark is running.
8. When you point me to code, show the surrounding code snippet, not line numbers.
9. Work on a new branch `integration` created from main. Never commit or push unless I say "commit".
10. Report per phase in at most 15 lines: what was built, files changed, how to try it (exact command and
    what to click), test results, measured numbers, open questions.

PHASE 0 — Read and plan (no code changes)
a) Read route_engine.py, road_network.py, scenario_manifest.py, server.py, app.js, live_demo.html, styles.css,
   and the shared modules listed above.
b) Benchmark the current route engine headless on the IITH map: fleet 60, 150 for 180 s (default seed).
   Report ticks/s, ms per tick broken down (neighbour search, separation, ADMM, overseer, safety check,
   frame building), and frame size in KB.
c) Write docs/INTEGRATION_PLAN.md: the frame schema changes, the command API (below), where each
   unlinked component plugs in, and any shared function that does NOT fit the road model with a proposed
   route-mode equivalent that keeps the same definition. Stop and wait.

PHASE 1 — Scale: higher limits without breaking real-time
a) Move limits into config `web:`: max_fleet (target 500), max_duration_s (target 3600), frame_stride,
   max_frames_in_memory, max_edges_per_frame, poll batch size.
b) Make the hot paths scale: uniform-grid spatial hashing for neighbour queries (comm graph, separation,
   safety / near-miss check, layer-transition check). Results must be identical to the current
   brute-force code for the same seed: test a 60-drone, 120 s run before/after with positions equal
   within 1e-9.
c) Streaming: adaptive frame stride (keep the browser at most ~10 frames/s of sim time at 1x), compact
   frames (numeric arrays, layer/status as small ints, edges capped), and a memory cap on stored frames
   (downsample older frames, keep all events).
d) Benchmark fleet 100 / 250 / 500 for 300 s; report ticks/s and whether 1x real-time holds. If 500 can't
   run at least 1x, tell me the largest fleet that can and ask before setting the limits.
e) UI: the fleet and duration inputs read the limits from /api/limits; show a warning when a request
   will run slower than real time.

PHASE 2 — Integrate every workflow component into the live demo
a) P2 ADMM convergence timer: wrap resolve_all_conflicts with ADMMRecorder (or simulation/telemetry.py) and
   add per-tick ADMM data to frames: events, iterations (mean/max), solve time (ms), converged vs fallback.
   UI: a live "ADMM convergence" panel (iterations and solve ms over time, p95, fallback count) and the
   selected drone's last ADMM negotiation (partners, iterations, converged).
b) P4 emergency-priority compliance: per emergency drone, delay vs nominal free-flow time along its route,
   whether it was forced to yield or left its reserved layer, and a fleet compliance rate. Reuse
   simulation/priority_metrics.py functions where they fit; if they assume corridors, write route-mode
   equivalents with the SAME definitions in a new module and say so. UI: KPI card + per-drone line.
c) P3 junction merging and platoons: at road-graph junctions apply the P3 merge rule (merge_gap, headway
   d_0 + h·v, k_s, k_v, cohesion/alignment within a road segment) using local_behavior/boids.py functions
   where they fit, else route-mode equivalents with the same parameters. Record merge attempts, success,
   platoon headway (formation_metrics definitions). UI: merge KPI + junction highlights.
d) P6 single safety definition: check whether verification/metrics.py now implements a layer-aware
   separation. If yes, make route_engine use it (and stl_monitor for the windowed G-spec). If not, STOP and
   ask me (options: wait for the fix, or keep route_engine's definition and label it in the UI and docs).
e) P5 W-MSR visible: in the drone card and on the map, show for each spoofer its reported position, true
   position and the W-MSR estimate; trust status of each neighbour report (kept / dropped / corrected).
   Do not change defense.py.
f) Architecture selector (UI + server): hierarchical (current), centralized (route-mode port of
   simulation/centralized.py: DTC with full state computes every drone's velocity: route following,
   car-following headway, priority-weighted separation, trusts reports), decentralized (no DTC, ADMM +
   defence), decentralized-undefended (no DTC, no defence). Same seed and fleet => identical initial flights
   across architectures (show the initial-conditions hash in the UI).
g) Run export / replay: "Download run" gives a zip/JSON with scenario manifest, resolved config, command
   log, per-tick KPIs and events; "Load run" replays it without re-simulating. Remove the dead /prototype
   route; keep /api/simulate but mark it legacy in a comment.

PHASE 3 — Custom drone input
a) Scenario builder panel (before launch): add/edit/delete drones with: type (EMERGENCY / EVTOL / DELIVERY),
   priority (default from type, override allowed), origin and destination (vertiport dropdown or click a
   node on the map), departure time, cruise speed (bounded by safety.maximum_velocity), preferred layer,
   cooperative flag (broadcasts Remote-ID-style reports or not), malicious flag (spoofer) with offset,
   and the health inputs from Phase 3B: battery capacity (Wh), initial state of charge (%), battery state of
   health (%), payload mass (kg), and an optional scheduled fault (type + time) for failure scenarios.
b) Mid-run injection: "Add drone now" sends the same form through the command channel (Phase 4), departing at
   the current sim time.
c) Import/export the drone list as JSON and CSV through simulation/scenario_manifest.py (extend validation;
   clear error messages per row). Random fleet + custom drones can be combined.
d) Tests: manifest validation (good and bad rows), custom drones reproduce identically for the same seed.

PHASE 3B — Drone health profile (battery, BMS, temperatures, link quality)
Before coding, show me the model equations and the default parameters per drone type, and wait for my OK.
a) New module simulation/drone_health.py with a simplified, documented, deterministic (seeded) model. All
   parameters in config `drone_health:` per type (EMERGENCY / EVTOL / DELIVERY): mass, battery capacity
   (Wh), nominal voltage, cell count (series), internal resistance, thermal constants, thresholds.
   State per drone, updated every tick:
   - Power draw (W): hover/base power + speed-dependent term + climb/descent term (layer changes) + payload
     term (+ wind term if a wind field is enabled). Hover/holding still draws power.
   - Battery: state of charge (%), pack voltage (open-circuit voltage from SoC minus I·R sag), current (A),
     remaining energy (Wh), state of health (capacity fade), estimated flight time left (s) and range left (m)
     at the current power.
   - BMS: per-cell voltages (small seeded imbalance), cell imbalance (mV), pack temperature, charge/discharge
     limits, and a BMS status: NORMAL / WARNING (low SoC, high temp, imbalance) / CRITICAL / FAULT, with fault
     codes (UNDER_VOLTAGE, OVER_TEMP, CELL_IMBALANCE, OVER_CURRENT, SENSOR_FAULT).
   - Temperatures: battery pack, motor/ESC (first-order thermal model driven by power and ambient
     temperature from config, e.g. Hyderabad summer 40 °C).
   - Link and navigation quality: DTC link RSSI / packet loss (worse with distance from the DTC and during
     outages), GNSS fix quality / HDOP (degraded during spoofing near the attacker).
   - Motor health: nominal, or a scheduled degradation fault.
b) Fault injection (from custom drone input, scenario scripts, or the DTC console in demo mode): sudden
   capacity loss, cell failure/imbalance, overheating, motor degradation, GNSS degradation.
c) Automatic onboard responses (config thresholds, each logged as an event):
   - Low reserve: divert to the nearest reachable pad (reserve = energy to reach it + safety margin).
   - CRITICAL: land at the nearest pad if reachable, else land in place.
   - Overheating: speed limit / power cap until temperature recovers, then CRITICAL if it doesn't.
   - The DTC sees the health of every drone; priority/overseer may treat a CRITICAL drone like an emergency
     (it gets right of way to land) — show me this rule before implementing it.
d) Frames: compact health per drone for all drones (SoC as int %, BMS status code, max temperature as int),
   full detail only for the selected drone (requested separately so frames stay small at 500 drones).
e) UI:
   - Map: colour or ring per drone by BMS status; low-battery and fault icons.
   - Drone card "Health" tab: battery gauge (SoC, voltage, current, power), time/range left, SoH, per-cell
     voltages bar chart, pack and motor temperatures with thresholds, BMS status + active fault codes, link RSSI,
     GNSS quality, and small live charts of SoC and temperature over time.
   - Fleet health panel: count by BMS status, lowest-SoC drones list (click to select), active alerts.
   - Alerts feed into the governance log with severity.
f) KPIs and export: energy used (Wh) per delivered drone, diversions and forced landings due to battery,
   drones that ran out of energy (must be 0 in a correct run, reported if not), max temperatures. Included in
   run export.
g) Tests: energy is conserved (integrated power = energy drawn), SoC decreases monotonically without
   charging, hold still drains battery, each fault triggers the right BMS status and onboard response,
   same seed = same health trace.

PHASE 4 — DTC operator console (real-world ATC/UTM controls)
a) Command channel: POST /api/runs/<id>/commands {type, targets[], params{}, reason}. The server puts commands
   in a thread-safe queue; the engine applies them at the next tick boundary. Commands travel over the same
   OverseerLink: while the link is down they are queued or lost per config and the UI shows
   sent / delivered / acknowledged / failed. Every command (and its outcome) goes into the governance log and
   the run's command log (tick-stamped, replayable).
b) Commands:
   1. Reroute: new destination or via-waypoint; re-plan on the road graph.
   2. Ground now: precautionary landing at the nearest pad/vertiport; land-in-place if none within a config
      distance.
   3. Hold / loiter at the current position; Resume.
   4. Return to base (origin vertiport).
   5. Change layer (climb/descend) through the existing layer-transition safety check.
   6. Speed restriction for a drone or a sector (with expiry).
   7. Priority override: promote to EMERGENCY (e.g. medical) or demote.
   8. Dynamic geofence / temporary flight restriction: draw a polygon on the map with start/end time; drones
      inside are rerouted out or landed, routes avoid it, departures inside are held.
   9. Sector ground stop / departure hold (ground-delay program) with release.
   10. Quarantine suspect: mark a drone untrusted (its reports ignored network-wide) and order it to land.
   11. Lost-link contingency policy (fleet default + per drone): continue / hold / return to base / land.
   12. Divert to charging pad / battery swap: route to a chosen pad, recharge or swap (time from config),
       then resume the mission.
   13. Health-based fleet actions: "ground all drones with BMS CRITICAL", "recall drones below X% SoC".
   Every movement command (reroute, hold, RTB, speed restriction, layer change, geofence detour) is checked
   against the drone's remaining energy: if it can't be completed with the reserve margin, the console warns
   the operator and shows the feasible alternative (nearest reachable pad) before sending.
b2) UI: select drones by click, box-select, or filter (type, sector, layer, status); right-click context menu
   and a command bar; confirmation for fleet-wide actions; keyboard shortcuts; command history panel.
c) Tests: each command's effect on a tiny scripted run; commands during an outage follow the configured
   policy; replay of a run with commands reproduces identical frames.

PHASE 5 — Real-world scenario presets
Scripted, deterministic presets (scenario manifest + timed command script in data/scenarios/), selectable
in the UI, each with a one-paragraph description:
1. IITH medical emergency: blood/medicine delivery to the campus hospital during peak delivery traffic.
2. Peak-hour vertiport congestion: departures held by ground-delay program, then released.
3. Pop-up TFR (VIP visit / fire): geofence appears mid-run; reroutes and holds.
4. GPS spoofing near a restricted zone: attack, defence, operator quarantine.
5. DTC outage: link loss with lost-link procedures (compare hold vs continue vs RTB).
6. Weather cell: a moving no-fly polygon crossing the corridors.
7. Non-cooperative intruder: a drone without Remote-ID reports; detected via V2V proximity only.
8. Battery failure mid-route: a delivery drone loses capacity / a cell fails; BMS escalates, it diverts or
   lands, and the DTC clears a path.
9. Hyderabad heat wave (ambient 44 °C): higher power and pack temperatures, overheating limits, more
   diversions; compare with a normal-temperature run.
10. Long-duration operations (e.g. 60 min): fleet-wide battery depletion, charging-pad queues and
    recharging/swaps under the DTC.
Show me the preset list with timelines before building them.

PHASE 6 — Research features (MENU ONLY: present it, estimate effort, wait for my choice)
Present these with effort estimates and what each would add to an IEEE paper; implement only what I pick:
R1. STL runtime assurance ("shield"): predictive robustness over a look-ahead horizon triggers automatic DTC
    interventions (hold / layer change / speed restriction) before a violation; compare intervention count
    vs safety vs throughput.
R2. Oracle-free resilience: replace true-neighbour checks with noisy onboard range sensing; per-neighbour trust
    scores over time feeding W-MSR and DTC quarantine; measure detection latency and false-positive rate.
R3. (r,s)-robustness of the live V2V graph: compute it online and show when W-MSR's guarantee holds vs fails
    on real road maps; correlate with attack impact.
R4. Lost-link contingency study: hold vs continue vs RTB vs decentralized-ADMM takeover under DTC outages of
    varying length.
R5. Human-in-the-loop DTC: operator workload (commands/min), command latency, automatic advisories the
    operator accepts or rejects; automatic vs manual vs mixed control.
R6. Fairness of priority: Jain's fairness index of delay across drone types/operators and the delay
    externality emergencies impose on others.
R7. Asynchronous ADMM with communication delay and packet loss; convergence vs link quality.
R8. Energy- and health-aware traffic management: the DTC uses each drone's battery/BMS/thermal state in
    layer allocation, priority and routing (e.g. low-SoC drones get shorter routes or landing priority);
    compare health-aware vs health-blind DTC on energy-exhaustion events, diversions and throughput, incl.
    wind fields and heat-wave conditions.
R10. Predictive health monitoring: forecast BMS escalation (time-to-critical) from SoC, temperature and
    imbalance trends, and act before it happens; measure lead time and false alarms.
R9. Open benchmark: release scenario manifests, command scripts and run logs for IITH/Hyderabad as a
    reproducible UTM benchmark.

PHASE 7 — Experiments on the live engine (ask before starting; estimate runtime first)
Headless batch runner for route mode reusing experiments/week6.py (run_matrix, aggregate, manifests, resume)
and visualization/plots.py: the four architectures x {nominal, attack, outage, emergency surge, TFR} x fleet
sizes x seeds on the IITH map, plus the metrics of the research features I chose. Results and figures in
outputs/web_experiments/ with auto-generated README tables. Include the health metrics from Phase 3B
(energy per delivery, diversions, forced landings, max temperatures).

PHASE 8 — Documentation and final check
docs/WEB_DEMO.md (start the server, every control and command, scenario file format, command API, export
format, limits), README "Live demo" section, and a manual click-through checklist that I run in the browser.
Report the final list of workflow components with where each appears in the UI.

Start with Phase 0 only.
```
