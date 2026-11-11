# MASooda demo: baked showcase run

A 6-minute IITH afternoon that uses every feature in one run. It is simulated ahead of time and
**replayed in the browser** with the site's **⤒ Load** button. Replay never re-simulates, so it
cannot stall: loading a 19 MB file took 0.3 s in testing, with no console errors.

## Files

| File | What it is |
|---|---|
| `showcase_scenario.json` | The scenario (preset format): 200 random + 10 scripted drones, 25 timed operator commands, a storm macro |
| `bake_demo.py` | Bakes the scenario through the same code path as the website (`start_live_run` → `build_export`) |
| `baked/masooda_showcase_hierarchical.json` | **The demo file.** Load this one on the site |
| `baked/masooda_showcase_{centralized,decentralized,decentralized_undefended}.json` | Same seed and scenario under the other architectures, for comparison |
| `baked/showcase_summary.md` / `.json` | Final KPIs for all four architectures, plus two rule-following KPIs |

Re-bake (about 60–90 s per architecture on the laptop):

```bash
python demo/bake_demo.py                         # hierarchical only
python demo/bake_demo.py --architecture centralized
python demo/bake_demo.py --summary-only          # rebuild the table from the baked files
```

## On the day

1. **T−5 min:** open https://masooda.onrender.com/ and wait until the map shows. If the server has
   gone to sleep, the first load can be slow. The page starts a small live run by itself; that is fine.
2. Click **⤒ Load** (top right) and pick `demo/baked/masooda_showcase_hierarchical.json`. The status line
   should read *"Loaded … 1801 frames, 210 flights … replaying without re-simulating"*. Loading also stops
   the live run.
3. Use **2×** speed (the full run takes 3 min). Pause (❚❚) on each beat below, and drag the time bar
   to jump to it.
4. **Fallback if the site is down:** on the laptop run `python -m web_sandbox.server`, open
   http://127.0.0.1:8765 and load the same file. Replay needs only the map from the server, so the laptop
   does no simulation.

Scripted drones (click them on the map, or type the number in the DTC console):
D-200 intruder · D-201 / D-202 blood · D-203 / D-204 spoofers · D-205 courier · D-206 overheating ·
D-207 cell failure · D-208 capacity loss · D-209 GNSS fault.

## Script (cue on the sim time, not the clock)

| Sim t | Open | Point at | Say | Built by (git) |
|---|---|---|---|---|
| 0–30 | Overview | Map, layer buttons L0–L6, Sectors | "200 drones on the IITH corridor network at 38 °C with a westerly wind. Seven altitude layers, six DTC sectors." | P1 engine, Lalith route engine + 2.5D layers |
| 20–60 | Drone → D-200 | Event log "sensed non-cooperative" | "An intruder with no Remote ID. The DTC can't see it, but neighbours detect it with onboard sensing and avoid it." | Lalith (Phase 5) |
| 30–180 | Drone → D-201 | Layer L6, Safety → Emergency compliance | "Blood delivery SNCC → Hospital, priority 0 on the reserved emergency layer. 100 % compliance; D-201 is only 7 s slower than nominal." | Tanmay/Sampad overseer, Lalith DTC |
| 45–113 | — | D-202 into the Hospital pad | "A second emergency to the same pad. Pad arbitration sequences the landings." | Lalith |
| any | ADMM | Iterations / solve time | "Every conflict group is solved by ADMM: 1445 resolutions, none failed to converge, p95 11 iterations, 0 fallbacks." | Lalith (P2), Sampad |
| 75–125 | Map | Dashed ghost → estimate on D-203/204 | "Two drones broadcast positions 30 m off. Trusted-range checks and W-MSR correct them: 0 spoofed reports accepted." | Sampad (P5) |
| 85–115 | DTC | Event log c5–c9 | "The operator console: change layer, hold, resume, reroute to Mess B. Each command is checked against remaining energy." | Lalith (Phase 4) |
| 110–200 | Map | VIP rectangle | "A pop-up restricted area for a VIP visit, announced 10 s ahead. Drones are rerouted around it or land early." | Lalith |
| 125 | Map | QUARANTINED tags | "The operator quarantines both spoofers. Their reports are ignored network-wide and they land." | Sampad / Lalith |
| 137–201 | Health → D-206 | Pack temperature 55 → 65 → 75 °C | "An internal overheating fault: WARNING, then CRITICAL with right of way, then FAULT and a forced landing." | Lalith (BMS) |
| 150–219 | Health → D-207 | Cell voltages, battery matrix | "A cell failure. Cell imbalance takes the BMS to CRITICAL; the DTC gives right of way, reserves a pad and the drone diverts. **This is the paper's novelty.**" | Lalith (1-RC + EKF BMS) |
| 163–261 | Drone → D-208 | SoC, "low reserve" | "Capacity loss the BMS didn't know about. The EKF learns the smaller capacity from voltage, and the chance-constrained energy check (1.645 σ) diverts it in time. 0 drones ran out of energy." | Lalith |
| 220–266 | DTC | Banner "DTC link DOWN" | "The DTC link drops. Routine traffic loiters, emergencies continue. A speed limit sent at 245 s is queued and delivered when the link returns at 265 s." | Tanmay (P4), Lalith |
| 275–358 | Map | Storm-N cells | "A storm cell crosses campus. 60 reroutes, a ground stop in the west, then a recall of drones below 25 % charge." | Lalith (Phase 5) |
| 360 | Safety, Network | ρ(t) never below 0, V2V graph | "0 crashes, 0 near misses, minimum 3D separation 10.7 m against an 8 m requirement. STL robustness stays positive." | Abdur/Dhadheechi (P6), Lalith |

## Architecture comparison (same seed, same scenario)

| KPI | Hierarchical | Centralized | Decentralized | Undefended |
|---|---|---|---|---|
| Operator commands applied | **25/25** | 25/25 | 0/25 | 0/25 |
| Drones inside an active restricted area | **16** | 11 | 36 | 36 |
| Crashes · near misses | **0 · 0** | 11 · 43 | 0 · 0 | 0 · 0 |
| Min 3D separation (m) | **10.7** | 0.3 | 10.7 | 10.7 |
| Spoofed reports accepted | **0** | 0 | 0 | 6 |
| Emergency mean delay (s) | 9.0 | 20.4 | 5.0 | 5.0 |
| Delivered | 148 | 105 | 192 | 192 |
| Energy per delivery (Wh) | 40.3 | 41.2 | 29.7 | 29.7 |

How to present it: **decentralized delivers more because it ignores the operator.** It has no DTC,
so it applied 0 of 25 commands (VIP area, ground stop, quarantine, recall) and 36 drones flew through
active restricted areas. Hierarchical is the only architecture that is collision-free, rule-following
and spoof-proof at once. Centralized follows the rules but breaks down on safety (11 crashes). Don't show
the delivery row without the first two rows.

## Product audit findings

**Demo risks**

1. The page starts a live 60-drone run as soon as it opens, so every viewer uses Render CPU (2 live-run
   slots in total). Load the file straight away.
2. Replay hides the command log. Overview shows "Operator commands: none" and the DTC console shows
   "Command history 0", although the file holds all 25 commands. Narrate commands from the event log.
3. The comparison card is hidden in replay. Use the table above.
4. The legend overlay covers the north-west of the map (Main Gate, Sampoorna).
5. `docs/DEMO_SCRIPT.md` is out of date: it describes the matplotlib Week 6 dashboard and pre-fix
   "provisional" numbers. Don't present from it.

**Product and safety (found while building the run; worth fixing before the paper)**

6. **Lost-link "hold" applies to emergency flights and to drones already diverting on low reserve.**
   With a fleet-wide hold, three emergencies were delayed by 52–70 s, and D-208 (diverting with its
   pad reserved) loitered at 15 % SoC and ended in a forced landing. The baked run works around this by
   holding only routine background traffic. Fix: exempt priority-0 and diverting/landing drones.
7. **A drone that went BMS CRITICAL on the pad was allowed to take off** (early bake: cell failure at
   150 s while ground-held, departure at 157.5 s, diversion at 158 s). Pre-flight checks should re-check
   BMS state at release.
8. Overheating: the 30 s CRITICAL hold before diverting turns the fault into a forced landing
   (reproduced; already listed as an open question in `SCENARIO_PRESETS.md`).
9. GNSS degradation is reported as a BMS SENSOR_FAULT, so the drone lands in place at 96 % charge. A
   navigation fault probably calls for a precautionary landing at the nearest pad.
10. D-207 diverted to V3 but landed at V4. Check whether it re-diverted on purpose.
11. The comparison KPIs reward ignoring the rules (finding above). Add "restricted-area incursions" and
    "commands applied" to the comparison card and the paper's tables. `bake_demo.py` already computes them.
12. The event log is dominated by "Corridor boundary" (wall) events (530 in this run), which bury the governance
    events. Consider filtering them out by default.
