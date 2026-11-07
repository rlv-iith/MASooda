# Drone health model (Phase 3B) — proposal for review

Simplified, documented and deterministic (seeded) model behind `simulation/drone_health.py`.
Every number below goes in `configs/base_config.yaml` under `drone_health:` (per type where it
differs). Updated every tick (dt = 0.1 s) for every airborne or holding drone.

## 1. Power draw (electrical, W)

Air density from the site and ambient temperature (hot air lifts less, so hover costs more):

    ρ = p(h) / (R_d · (T_amb + 273.15)),   p(h) = 101325 · (1 − 2.25577e-5 · h)^5.25588
    Hyderabad h = 542 m:  ρ = 1.074 kg/m³ at 35 °C, 1.050 at 42 °C (1.148 at 15 °C)

Thrust T = (m_empty + m_payload) · g. Momentum theory for the induced velocity in level flight
(hover: v = 0) [Leishman 2006]:

    v_h = √(T / (2 ρ A))                         A = total rotor disc area
    v_i(v) = √( −v²/2 + √(v⁴/4 + v_h⁴) )         v = airspeed = |ground velocity − wind|
    P_mech = T · v_i / FM  +  ½ ρ C_D·A_f · v³  +  P_climb
    P_elec = P_mech / (η_prop · motor_health) + P_avionics

- Hover and ground-hold-in-air still draw P(0) (the largest term), as the prompt requires. A drone
  waiting on its pad draws only P_avionics.
- Climb: the engine changes layer instantly, so a climb of Δh = 30 m adds
  P_climb = m·g·v_climb for Δh / v_climb seconds (v_climb = 3 m/s → 10 s). Descent adds nothing and
  recovers nothing.
- Wind: constant vector `drone_health.wind_mps` (default [0, 0], i.e. off).

## 2. Battery: equivalent circuit with internal resistance (Rint) [Plett 2015]

    OCV_cell(SoC): piecewise-linear Li-ion curve (0 % 3.00 V, 5 % 3.30, 10 % 3.45, 20 % 3.60,
                   40 % 3.72, 60 % 3.85, 80 % 4.00, 100 % 4.20 V);  OCV = n_s · OCV_cell
    R = R_pack · (1 + 0.5·(1 − SoH)) · (1 + α_R·(25 − T_pack))₊         (ageing, cold)
    I = (OCV − √(OCV² − 4 R P_elec)) / (2R)        (P_elec = V·I with V = OCV − I·R)
    V = OCV − I·R          Q_eff = Q_nom · SoH          Q_nom = E_nom / V_nom   (Ah)
    SoC(t+dt) = SoC − I·dt / (3600 · Q_eff)
    energy drawn from the cells per tick = OCV · I · dt = P_elec·dt + I²R·dt   (load + heat)

- If OCV² < 4 R P_elec, the pack cannot deliver the power: OVER_CURRENT / UNDER_VOLTAGE → FAULT.
- Remaining usable energy E_rem = Q_eff · ∫ OCV dSoC from SoC_min (5 %) to SoC.
- Time left = E_rem / P_elec (now). Range left = time left × ground speed (cruise speed while
  hovering).
- SoH is an input (capacity fade). It does not change within a flight, except through the
  `capacity_loss` fault.
- Random-fleet drones draw their initial SoC and SoH from seeded ranges, so batteries matter on short
  campus routes: SoC 35–100 %, SoH 80–100 %. Custom drones use their form values (default 100 %).

## 3. BMS

- n_s series cells; cell k has a seeded SoC offset δ_k ~ N(0, 0.4 %) and resistance factor
  ε_k ~ N(0, 3 %):  V_k = OCV_cell(SoC + δ_k) − I · R_cell · (1 + ε_k).
- Imbalance = max V_k − min V_k (mV). Discharge limit I_max = C_max · Q_nom.
- Status and fault codes (each threshold in config):

| Code | WARNING | CRITICAL | FAULT |
|---|---|---|---|
| low charge (shown as UNDER_VOLTAGE when a cell sags) | SoC < 30 % | SoC < 15 % | any cell < 3.0 V |
| OVER_TEMP (pack) | > 55 °C | > 65 °C | > 75 °C |
| OVER_TEMP (motor/ESC) | > 90 °C | > 110 °C | — |
| CELL_IMBALANCE | > 50 mV | > 100 mV | — |
| OVER_CURRENT | I > 0.8 I_max | I > I_max | power cannot be delivered |
| SENSOR_FAULT | — | — | injected (GNSS/temperature sensor) |

Status = the worst level present: NORMAL / WARNING / CRITICAL / FAULT. A status only drops after the
condition clears by a hysteresis (2 % SoC, 3 °C, 10 mV), so it does not flicker.

## 4. Temperatures: first-order lumped models [Bernardi et al. 1985, simplified]

    C_pack · dT_pack/dt = I²R + q_fault − hA_pack(v) · (T_pack − T_amb),   hA(v) = hA₀ + hA₁·√v
    C_mot  · dT_mot/dt  = (1 − η_prop·motor_health) · P_elec − hA_mot(v) · (T_mot − T_amb)

T_amb comes from `drone_health.ambient_c` (default 35 °C, Hyderabad pre-monsoon; a 42 °C heat-wave
preset comes in Phase 5). The pack and motor start at T_amb. The airspeed term means a hovering
drone cools worse than a cruising one.

## 5. Link and navigation quality

- DTC link: log-distance path loss from the DTC site (map centre) [Rappaport 2002]:
  RSSI = P_tx − PL₀ − 10·n·log₁₀(d/1 m) + X(x, y). Here X is deterministic shadowing (seeded smooth
  field, σ = 4 dB).
- Packet loss = 1 / (1 + exp((RSSI − RSSI₅₀) / s)). During a DTC outage: loss = 100 % and RSSI is
  shown as "no link".
- GNSS: HDOP = HDOP₀ + seeded jitter. Within r_spoof = 150 m of an active spoofer:
  HDOP += 3·(1 − d/r_spoof). Fix quality: GOOD (< 2), DEGRADED (< 5), POOR.
- Motor health: 1.0 nominal; reduced by the motor_degradation fault.

## 6. Faults (custom drone form, scenario scripts, later the DTC console)

| Fault | Effect at t_fault | Expected BMS response |
|---|---|---|
| capacity_loss | Q_eff × 0.7 (remaining charge × 0.7) | low SoC → WARNING/CRITICAL sooner |
| cell_failure | one cell: δ_k −15 %, R × 4 | CELL_IMBALANCE → CRITICAL, cell UNDER_VOLTAGE under load |
| overheating | q_fault = 0.6 × P_hover(type) into the pack (0.15 never reached WARNING on a 2–3 min flight) | OVER_TEMP WARNING → CRITICAL |
| motor_degradation | motor_health 1.0 → 0.8 | more power and motor heat; motor OVER_TEMP |
| gnss_degradation | HDOP + 5; fix POOR | SENSOR_FAULT (navigation) |

## 7. Onboard responses (each logged as an event with severity)

- **Low reserve.** Checked every 1 s:

      E_need(dest) = P_elec(v_cruise) · L_remaining / v_cruise · (1 + margin) + P_elec(0) · t_land

  with margin = 20 % and t_land = 30 s. If E_rem < E_need(dest), the drone **diverts** to the nearest
  pad (by road-corridor route) whose E_need ≤ E_rem. If no pad passes, it lands in place.
- **CRITICAL:** land at the nearest pad if reachable, else land in place.
- **FAULT:** land in place immediately.
- **Overheating:** at WARNING the speed is limited to 60 % of cruise until T < threshold − 3 °C. If it
  reaches CRITICAL and stays there 30 s, the drone lands at the nearest pad.
- Pre-flight check (added during implementation): a drone that is already CRITICAL or cannot reach its
  destination with the reserve stays on its pad (event + `grounded_preflight` count).
- A pad within one approach leg (look-ahead, 40 m) is reached by a straight leg instead of the
  corridor graph.
- New statuses: DIVERTED (flying to an alternate pad; it still counts as airborne) and FORCED (landed
  in place). FORCED is status code 4 in frames.

## 8. DTC rule for unhealthy drones (needs your OK before it is coded)

The DTC sees every cooperative drone's compact health (SoC, BMS status, max temperature). Proposed
rule: **a CRITICAL or FAULT drone is treated like an emergency for right of way to land.**

1. Its priority becomes 0 in the DTC layer allocation, in ADMM (weight 10) and in the tactical
   altitude shift, so the other drone yields.
2. It is **not** moved to the emergency layer: a climb costs energy it may not have.
3. Its landing pad is reserved: departures from that pad are held until it has landed.
4. Two priority-0 drones: the emergency mission keeps its order; between two unhealthy drones the
   lower SoC goes first.
5. A non-cooperative drone sends no health, so the DTC cannot apply this rule to it.

## 9. Default parameters per type

| | DELIVERY | EMERGENCY | EVTOL |
|---|---|---|---|
| Empty mass / default payload | 6 kg / 2 kg | 10 kg / 3 kg | 450 kg / 100 kg |
| Rotors (disc area A) | 4 × 0.38 m (0.45 m²) | 6 × 0.55 m (1.43 m²) | 16 × 1.5 m (28.3 m²) |
| Figure of merit FM / η_prop | 0.65 / 0.80 | 0.65 / 0.80 | 0.70 / 0.85 |
| C_D·A_f / avionics | 0.08 m² / 25 W | 0.12 m² / 40 W | 1.2 m² / 500 W |
| Pack | 6S, 22.2 V, 500 Wh | 12S, 44.4 V, 800 Wh | 108S, 400 V, 25 kWh |
| R_pack / C_max | 0.020 Ω / 5C | 0.040 Ω / 5C | 0.050 Ω / 5C (4C raised OVER_CURRENT warnings in every eVTOL hover) |
| Pack C_th / hA₀ / hA₁ | 2.5 kJ/K / 3 / 1 W/K | 4 kJ/K / 3 / 1 | 139 kJ/K / 60 / 25 |
| Motor C_th / hA₀ / hA₁ | 0.4 kJ/K / 5 / 2 | 0.6 kJ/K / 6 / 2.5 | 20 kJ/K / 200 / 80 |
| Link P_tx / PL₀ / n | 27 dBm / 40 dB / 2.7 | same | same |
| Link RSSI₅₀ / s | −95 dBm / 2.5 dB | same | same |

Shared: α_R = 0.01 /K, SoC_min = 5 %, cells δ σ = 0.4 % and ε σ = 3 %, HDOP₀ = 0.9.

What these defaults give (computed at 35 °C, Hyderabad):

| | DELIVERY | EMERGENCY | EVTOL |
|---|---|---|---|
| Hover / cruise power | 1.38 / 1.06 kW (10.8 m/s) | 1.62 / 0.98 kW (14.4 m/s) | 86.0 / 60.8 kW (12 m/s) |
| Endurance hover / cruise | 21.7 / 28.3 min | 29.6 / 49.2 min | 17.4 / 24.7 min |
| Range at cruise | 18.3 km | 42.5 km | 17.8 km |
| Cruise current / pack heat | 47.8 A / 46 W | 22.0 A / 19 W | 152 A / 1.16 kW |
| Steady pack / motor rise | +7.3 / +18.3 K | +2.8 / +12.6 K | +7.9 / +19.1 K |

At 42 °C, hover power is about 1 % higher than at 35 °C, and about 4 % higher than at 15 °C. The
endurances are in the range of commercial delivery multirotors and of published small-eVTOL figures
[Stolaroff et al. 2018; Yang et al. 2021].

## References

- J. G. Leishman, *Principles of Helicopter Aerodynamics*, 2nd ed., Cambridge University Press, 2006.
- G. L. Plett, *Battery Management Systems, Vol. I: Battery Modeling*, Artech House, 2015.
- D. Bernardi, E. Pawlikowski, J. Newman, "A General Energy Balance for Battery Systems,"
  *J. Electrochem. Soc.*, 132(1):5–12, 1985.
- T. S. Rappaport, *Wireless Communications: Principles and Practice*, 2nd ed., Prentice Hall, 2002.
- J. K. Stolaroff et al., "Energy use and life cycle greenhouse gas emissions of drones for commercial
  package delivery," *Nature Communications*, 9:409, 2018.
- X. G. Yang et al., "Challenges and key requirements of batteries for eVTOL aircraft," *Joule*,
  5(7):1644–1659, 2021 (ref. 18 in `RESEARCH_GAP_HEALTH_AWARE_UTM.md`).
- B. Saha et al., "Battery Health Management System for Electric UAVs," IEEE Aerospace Conf., 2011
  (ref. 9), for the BMS status / prognostics structure.
