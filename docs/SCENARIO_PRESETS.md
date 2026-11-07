# Scenario presets (Phase 5)

Approved and built. The files are in `data/scenarios/`. Changes made while building are listed under
"Built — changes and results" at the end.

Each preset is one file `data/scenarios/<id>.json`:

- **Header:** map, seed, fleet and mix, duration, architecture, switches.
- **Conditions:** weather, attack, outage.
- **Drones:** custom drones (Phase 3 rows).
- **Command script:** `[{t, type, targets, params}]` using the Phase 4 console API. Targets name custom
  drones (`"@medic1"`) or are resolved at the scripted time (`"fleet"`, `"sector:3"`).

The engine applies scripted commands at the tick for `t`, exactly like operator commands, so a preset
always plays back identically. You can still give live commands during a preset run. The UI gets a
**Presets** list in the Scenario card, with a one-paragraph description and the timeline shown before
launch.

All presets use the IITH campus map, seed 42 and the defaults unless stated. IITH vertiports:

| Pad | Name | Role |
|---|---|---|
| V1 | Hospital | hospital |
| V2 | Main Gate | hub |
| V3 | Guest House | hub |
| V4 | Convention Centre | hub |
| V5 | LHC | hub |
| V6 | Admin Block | hub |
| V7 | Academic Area | hub |
| V8 | Mess B | depot |
| V9 | New Hostels | hub |
| V10 | Mess A | depot |
| V11 | Old Hostels | hub |
| V12 | SNCC | hub |
| V13 | Sampoorna | depot |

## 1. IITH medical emergency — blood delivery during the lunch rush (240 s, 120 drones, 70 % delivery)

| t (s) | Event |
|---|---|
| 0 | Lunch-hour delivery wave: 120 drones, departures within 90 s, mostly from the Mess A/B and Sampoorna depots |
| 45 | Custom `@blood1` EMERGENCY departs SNCC (V12) → Hospital (V1), 2.3 km across campus |
| 45 | `priority @blood1 → 0` (already an emergency; logged so the timeline shows it) |
| 60 | Second request: `@blood2` EMERGENCY Main Gate (V2) → Hospital, 0.6 km, landing on the same pad |
| 60–200 | Watch: reserved layer L2, DTC right of way, ADMM negotiations, emergency delay vs nominal, yields |

KPI focus: emergency compliance, delay vs nominal, lower-priority delay imposed.

## 2. Peak-hour vertiport congestion — ground-delay program (300 s, 200 drones)

| t (s) | Event |
|---|---|
| 0 | 200 drones, departure window 60 s (deliberately overloaded pads) |
| 20 | `ground_stop sector 3` and `ground_stop sector 4` (west campus), with release at 90 s and 120 s |
| 30 | `speed_limit sector 1, 8 m/s for 60 s` (metering into the congested centre) |
| 90 / 120 | Scheduled releases; the held departures go in turn |

KPI focus: ground holds, pad queue length, near misses, arrivals per minute, before vs after release.

## 3. Pop-up restricted area — VIP visit at the Academic Area (240 s, 120 drones)

| t (s) | Event |
|---|---|
| 0 | Normal operations |
| 60 | `tfr "VIP"`: 220 × 160 m polygon over the Academic Area (V7) and LHC (V5) roads, 70–180 s (announced 10 s ahead, shown dashed) |
| 70 | Becomes active: drones inside are rerouted out or land; routes plan around it; departures from V5 and V7 are held |
| 180 | Lifted; held departures go |

KPI focus: reroutes, extra route length, holds, zero drones inside the area while it is active.

## 4. GPS spoofing near the restricted zone (240 s, 100 drones)

| t (s) | Event |
|---|---|
| 0 | Normal operations; `tfr "Hospital approach"` around V1, 0–240 s (pads outside it stay usable) |
| 50 | Two custom spoofers `@spoof1`/`@spoof2` (delivery, offset 30 m toward the zone) start broadcasting false positions near the zone |
| 50–110 | Trusted-range defence + W-MSR: map shows reported vs estimated positions, kept/corrected reports |
| 110 | Operator `quarantine @spoof1, @spoof2`: reports ignored network-wide, ordered to land |

KPI focus: spoofed reports filtered, W-MSR estimate error, safety margin; compare with the defence off.

## 5. DTC outage — lost-link procedures (240 s, 100 drones, outage 80–150 s)

One preset with three variants, run the same seed and compared:

| Variant | t = 0 command | During the outage (80–150 s) |
|---|---|---|
| continue | `lost_link_policy fleet → continue` | drones keep their last directive |
| hold | `lost_link_policy fleet → hold` | airborne drones loiter; released when the link returns |
| rtb | `lost_link_policy fleet → rtb` | drones return to their origin pads |

Also: an operator command sent at 100 s shows as queued, then delivered at 150 s.
KPI focus: arrivals, delay, energy used, near misses, staleness. Shown as a comparison table.

## 6. Weather cell — moving no-fly polygon (300 s, 120 drones, wind 8 m/s from the west)

| t (s) | Event |
|---|---|
| 0 | Wind 8 m/s from 270° (power cost on westbound legs) |
| 60–240 | A 250 m storm cell drifts east across the corridors, Main Gate → SNCC. It is scripted as 12 overlapping restricted areas, each active 25 s and offset 180 m (≈ 7 m/s drift), so the engine's static areas give a moving cell |
| 240 | Cell gone |

KPI focus: reroutes, holds, extra energy, nobody inside the cell.

## 7. Non-cooperative intruder (180 s, 80 drones)

| t (s) | Event |
|---|---|
| 0 | Normal operations |
| 30 | `@intruder` (non-cooperative delivery drone, no Remote ID) departs Main Gate (V2) → SNCC (V12), cutting across the campus on a straight route |
| 30–150 | It is invisible to the DTC and to ADMM. Others detect it only by onboard proximity sensing: needs an engine addition, see choice B |
| 60 | Operator `speed_limit` around its path |

KPI focus: detections, near misses with the intruder, avoidance manoeuvres.

## 8. Battery failure mid-route (240 s, 100 drones)

| t (s) | Event |
|---|---|
| 20 | `@cargo1` DELIVERY Sampoorna (V13) → SNCC (V12), 2.4 km, 45 % SoC |
| 70 | Scheduled `cell_failure` on `@cargo1` → BMS CRITICAL (imbalance) |
| 70 | `@cargo2` DELIVERY with `capacity_loss` at 80 s → low-reserve diversion |
| 70 | DTC right of way: priority 0, landing pad reserved, departures there held |
| 80–150 | Diversion / landing; the operator issues `fleet_ground_bms_critical` at 120 s |

KPI focus: time from fault to landing, BMS escalation events, no energy depletion.

## 9. Hyderabad heat wave (ambient 44 °C) vs a normal day (300 s, 150 drones)

Two variants, same seed, compared:

| Variant | Weather | Faults |
|---|---|---|
| heat wave | 44 °C, wind 2 m/s | two `overheating` faults at 60 s (delivery drones on long routes) |
| normal | 30 °C, wind 2 m/s | same faults |

KPI focus: energy per delivery, max pack/motor temperature, overheating speed limits, diversions.
Shown as a comparison table.

## 10. Long-duration operations — 60 min with recharging (3600 s, 60 drones)

| t (s) | Event |
|---|---|
| 0 | 60 drones fly repeated sorties: after landing and a 30 s turnaround they take a new mission from that pad. This needs an engine addition, see choice D |
| continuous | Before a new sortie, a drone below 35 % SoC is sent to battery service instead: the depots (V8, V10, V13) are swap stations, capacity 2 drones per pad, others queue |
| 1200 | `lost_link_policy → rtb` (shift change) |
| 2400 | `fleet_recall_below_soc 25 %` (end-of-shift recall) |

KPI focus: missions completed, energy per mission, swap/charge queue length and waiting time, SoC
distribution over time (battery matrix).

## Engine additions these presets need (choices)

- **A. Timed scripts (all presets):** scripted commands applied at their tick, plus target
  selectors (`@name`, `fleet`, `sector:k`). Required.
- **B. Proximity sensing for non-cooperative drones (preset 7):** today a non-cooperative drone is
  invisible to everyone, so other drones cannot avoid it. Add onboard sensing: a drone within
  `sensing_radius_m` (default 30 m) is seen at its true position by its neighbours' separation and
  CPA avoidance, with an "intruder detected" event. The DTC and ADMM still cannot see it.
- **C. Comparison variants (presets 5 and 9):** the server runs the variants with the same seed. The
  first streams live, the others run headless. The page shows a comparison table of KPIs when all
  have finished.
- **D. Repeated sorties and pad service capacity (preset 10):** drones re-dispatch after landing;
  battery service pads have a capacity with a FIFO queue.

## Built — changes and results

- **Preset 2:** the stopped sectors are S3 (north-west) and S4 (north-centre); the metered sector is S1
  (south-centre). Sector id = row × 3 + column, with rows south → north.
- **Preset 3:** the VIP area is 360 × 270 m, so it covers both the V5 and V7 approaches (220 × 160 m
  could not reach both).
- **Preset 5:** the operator command goes out at 125 s, not 100 s. The queue lifetime is 30 s, so a
  command sent at 100 s would expire before the link returns at 150 s.
- **Preset 7:** the intruder flies its corridor route (all flights follow the road graph).
- **Preset 8:** @cargo1 starts at 80 % SoC. At 45 % the failed cell sags below 3.0 V under load, which
  is a FAULT (land in place) rather than CRITICAL (divert). @cargo2 starts at 26 % (at 22 % it fails
  the pre-flight check). The fleet grounding is at 85 s, while @cargo1 is still airborne.
- **Preset 10:** a drone too weak to fly to a depot gets a ground-crew swap on the pad it is on
  (twice the swap time).

Headless results (seed 42):

| Preset | Result |
|---|---|
| 1 medical emergency | emergency compliance 100 %, mean emergency delay 4.5 s, 0 near misses |
| 2 congestion | 223 ground holds, 161 of 200 delivered in 300 s, 0 near misses |
| 3 VIP TFR | 17 restricted-area events, departures from V5/V7 held, 0 near misses |
| 4 spoofing | 5 reports corrected, both spoofers quarantined at 110 s, 1 near miss during the attack |
| 5 outage | continue: 91 delivered · hold: 76 delivered, energy +77 %, emergency delay 51 s · rtb: 36 delivered (the rest went home) |
| 6 weather cell | 120 restricted-area events, 3 drones caught inside landed, 0 near misses |
| 7 intruder | detected by onboard sensing, never in ADMM, 0 crashes |
| 8 battery failure | @cargo1 CRITICAL → right of way → diverted and landed; @cargo2 diverted on low reserve; 0 depleted |
| 9 heat wave | 44 °C vs 30 °C: energy/delivery +4 %, max motor 69.8 vs 56.2 °C; the two overheating faults reach the pack limit in both variants |
| 10 long operations | 1469 deliveries in 60 min, 137 swaps, swap queue ≤ 5, 0 forced landings, 0 depleted |

Finding (preset 9): a heat wave alone keeps packs below the 55 °C warning on short campus flights. The
overheating fault dominates the pack temperature at both 30 °C and 44 °C. The 30 s CRITICAL hold
before diverting is what turns those faults into forced landings (still an open question).
