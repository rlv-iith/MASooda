# Battery- and Health-Aware Drone Traffic Management: Research Scope

**Author:** R Lalith Vishnu (P2) · Nov 9, 2026

## Summary

**Novel claim:** MASooda closes the loop between every drone's live battery state and the multi-agent traffic manager. Who yields, who gets which altitude layer, who lands first and who absorbs the energy cost of avoiding a conflict are decided from each drone's energy margin, thermal margin and BMS status. The loop is also protected against drones that lie about their battery health.

The literature has the two halves but not the join. Battery prognostics for drones are mature, but they decide only for one vehicle: NASA's 2024 flight tests land the same aircraft when remaining flight time drops below 200 s \[Ancel 2024\]. Traffic management, meanwhile, sets priority from operation class and geometry, not battery state \[Jover 2022\]. The closest work uses battery state only as a deadline in offline vertiport arrival sequencing, without en-route conflicts \[Kleinbekman 2018\].

MASooda already has a physics-based health model, BMS fault codes, onboard diversion and a basic "unhealthy drone gets right of way" DTC rule. The publishable step is to make that rule continuous, push it into ADMM conflict resolution and STL safety monitoring, and defend it against falsified health reports.

## Battery and health models

These are the physics behind every drone's health state, ticked every 0.1 s. Sections 1–5 are already implemented in MASooda's health model; section 6 (degradation across flights) is proposed.

### 1. Air density and power draw

Air density at the site comes from elevation h and ambient temperature T\_amb. Hot air lifts less, so hover costs more:

```latex
\rho = \frac{101325\,(1 - 2.25577\times10^{-5} h)^{5.25588}}{R_d\,(T_{amb} + 273.15)}
```

For Hyderabad (542 m) this gives 1.074 kg/m³ at 35 °C and 1.050 kg/m³ at 42 °C. Momentum theory \[Leishman 2006\] gives the induced velocity for thrust T = m·g over rotor disc area A, at airspeed v:

```latex
v_h = \sqrt{\frac{T}{2\rho A}}, \qquad v_i(v) = \sqrt{-\frac{v^2}{2} + \sqrt{\frac{v^4}{4} + v_h^4}}
```

Mechanical power is induced plus parasitic plus climb power; electrical power adds propulsion losses, motor health and avionics:

```latex
P_{mech} = \frac{T\,v_i}{FM} + \tfrac{1}{2}\rho\,C_D A_f\,v^3 + m g\,v_{climb}, \qquad P_{elec} = \frac{P_{mech}}{\eta_{prop}\,h_{motor}} + P_{avionics}
```

### 2. Battery equivalent circuit and state of charge

The pack is an internal-resistance (Rint) circuit \[Plett 2015\]. Open-circuit voltage OCV follows a Li-ion curve of state of charge (SoC); resistance rises with ageing and cold:

```latex
R = R_{pack}\,\bigl(1 + 0.5\,(1 - SoH)\bigr)\,\bigl(1 + \alpha_R\,(25 - T_{pack})\bigr)_+
```

The current that delivers P\_elec, terminal voltage and SoC update are:

```latex
I = \frac{OCV - \sqrt{OCV^2 - 4 R P_{elec}}}{2R}, \qquad V = OCV - I R, \qquad SoC_{t+\Delta t} = SoC_t - \frac{I\,\Delta t}{3600\,Q_{nom}\,SoH}
```

If OCV² < 4·R·P\_elec, the pack cannot deliver the power, which is a BMS FAULT (voltage collapse). A Thevenin 1-RC branch would add voltage-sag transients under climb loads; it is an optional refinement.

### 3. Usable energy and energy to destination

Remaining usable energy counts down to SoC\_min = 5 %:

```latex
E_{rem} = Q_{nom}\,SoH \int_{SoC_{min}}^{SoC} OCV(s)\,ds
```

The energy needed to reach a pad L metres away at cruise speed, with a 20 % margin and a 30 s landing, is:

```latex
E_{need}(L) = P_{elec}(v_{cr})\,\frac{L}{v_{cr}}\,(1 + m) + P_{elec}(0)\,t_{land}
```

Today this check runs every 1 s and triggers a diversion when E\_rem < E\_need(destination).

### 4. Temperature

Pack and motor temperatures follow first-order lumped models \[Bernardi 1985, simplified\], with cooling that improves with airspeed:

```latex
C_{pack}\,\frac{dT_{pack}}{dt} = I^2 R + q_{fault} - hA(v)\,(T_{pack} - T_{amb}), \qquad hA(v) = hA_0 + hA_1\sqrt{v}
```

### 5. BMS status

Each category (low charge, pack and motor temperature, cell imbalance, over-current, sensor fault) maps to NORMAL, WARNING, CRITICAL or FAULT, with hysteresis so the status does not flicker. For example, SoC below 30 % is WARNING and below 15 % is CRITICAL; a pack above 65 °C is CRITICAL.

### 6. Degradation across flights (proposed)

To study fleet-level effects such as which drones age fastest under a given traffic policy, add an Arrhenius cycle-ageing model \[Wang 2011\]. Capacity loss grows with throughput Ah and temperature:

```latex
Q_{loss}\,[\%] = B \exp\!\left(-\frac{E_a}{R\,T}\right) (Ah)^{z}, \qquad SoH = 1 - \frac{Q_{loss}}{100}
```

This lets the paper report battery wear per delivery as a cost of each traffic policy, not just energy per flight.

## What research already exists

Each strand below solves part of the problem; none feeds live battery state of many drones into traffic decisions.

| Theme | Work | What it does | What it lacks for our problem |
| --- | --- | --- | --- |
| Priority in conflict resolution | [Jover et al. 2022](https://www.mdpi.com/2079-9292/11/8/1225) | Priority from operation class and manoeuvrability in U-space tactical deconfliction; low-priority drones fly up to 8 % farther | Battery and health play no part in priority |
| Energy cost of deconfliction | [Zongo & Wei 2026](https://arxiv.org/abs/2604.06093) | Median energy overhead below 1.5 %, 95th percentile 3.84–5.3 %, tails to 44 % at high density; recommends a 4–5 % reserve | Overhead is estimated at mission start; live battery state does not steer manoeuvres |
| Battery-constrained sequencing | [Kleinbekman, Mitici & Wei 2018](https://bpb-us-w2.wpmucdn.com/web.seas.gwu.edu/dist/9/15/files/2019/07/dasc18_imke.pdf) | Battery state sets each eVTOL's latest arrival time in a MILP vertiport schedule | Terminal area only, no en-route conflicts; 80 aircraft took 5,333 s to solve |
| Energy-based flight planning | [Liu & Sengupta 2017](https://its.berkeley.edu/publications/energy-based-flight-planning-system-unmanned-traffic-management) | Pre-flight plans that minimise energy for UTM | Pre-flight only; no live health or tactical decisions |
| Health-aware single-vehicle operation | [Montazeri, Kulkarni & Fink 2024](https://arxiv.org/abs/2404.08497) | Deep RL picks destinations and cruise altitude from inferred SoH (capacity, resistance) | Single aircraft; no traffic, separation or adversarial reports |
| Onboard battery prognostics | [Saha et al. 2011](https://c3.ndc.nasa.gov/dashlink/static/media/publication/2011_IEEEAerospace_UAVBHM.pdf), [Kulkarni et al. 2018](https://ntrs.nasa.gov/citations/20180004466), [Hogge et al. 2024](https://ntrs.nasa.gov/citations/20230012868) | Remaining-flight-time prediction, flight-tested on electric UAVs and octocopters | Decisions stay onboard one vehicle |
| Run-time assurance | [Ancel et al. 2024](https://sacd.larc.nasa.gov/wp-content/uploads/sites/167/2025/04/Ancel-et-al-2024.pdf) | Over 100 flights; battery monitor recommends landing when remaining flight time falls below 200 s | Single vehicle; no coordination with other traffic |
| Prognostics-informed reconfiguration | [Sharma & Atkins 2021](https://arxiv.org/abs/2103.01883), [Darrah 2023](https://ir.vanderbilt.edu/handle/1803/18588) | Switch battery packs or replan after faults using prognostics | One vehicle; no shared airspace or landing capacity |
| Formal safety for fleets | [Pant et al. 2018](https://repository.upenn.edu/handle/20.500.14332/40605) | STL robustness for multi-drone separation and missions | No energy or thermal specifications |
| Resilient consensus | [LeBlanc et al. 2013](https://engineering.purdue.edu/~sundara2/papers/journals/JSAC_robust_consensus.pdf) | W-MSR tolerates misbehaving neighbours | Applied to positions and states, never to health telemetry |
| Attacks on battery estimates | [Lin, Li & Meng 2026](https://www.sciencedirect.com/science/article/abs/pii/S0306261926008718) | RL false-data injection steers cloud-BMS SoH estimates (R² > 0.97) while evading detectors | Batteries in general; no traffic-management consequence studied |
| Battery physics for vertical flight | [Yang et al. 2021](https://doi.org/10.1016/j.joule.2021.05.001), [Zhao et al. 2025](https://doi.org/10.3390/drones9080539) | eVTOL batteries need more than EV batteries in every aspect; reliability review lists cybersecurity and multi-fault diagnosis as open | Component level, not operations |

The nearest overlap is Kleinbekman 2018 (battery as an arrival deadline) and Montazeri 2024 (health-aware decisions). Both must be cited and contrasted explicitly in the paper.

## Ongoing research and programmes

Active work in 2024–2026 is moving health monitoring into operations, but still one aircraft at a time.

| Group / programme | Status (2024–2026) | Relevance to MASooda |
| --- | --- | --- |
| NASA Langley, in-time safety for autonomous UAS | Run-time assurance flight tests with battery, propulsion and autopilot monitors \[Ancel 2024\]; octocopter battery prognostics \[Hogge 2024\]; the HERMES risk-mitigation system, presented January 2026 with battery prognostics as a keyword ([NTRS](https://ntrs.nasa.gov/citations/20260000517)) | Supplies exactly the signals our DTC would consume; its decisions are per vehicle |
| NASA IASMS concept for Advanced Air Mobility | Lists vehicle-health monitors and battery prognostics as in-time risk services that can trigger mitigation \[Ellis 2021\] | Concept asks for health-driven mitigation; the multi-vehicle policy is open |
| India National UTM Policy Framework (2021) | Lists real-time UAS health monitoring and contingency management as UTM services \[MoCA 2021\] | Direct policy hook for a health-aware DTC in the Indian context |
| FAA UTM concept v2.0 | Endurance stays the operator's responsibility \[FAA 2020\] | Shows that today's traffic layer does not own energy |
| George Washington Univ. (Peng Wei's group) | Energy overhead of deconfliction published 2026 \[Zongo & Wei 2026\]; earlier battery-constrained arrival sequencing \[Kleinbekman 2018\] | Most active competitor line; our angle (live health in the loop + adversarial reports) is distinct |
| EPFL / NASA Ames (Fink, Kulkarni) | Health-aware RL mission planning \[Montazeri 2024\] | Single-vehicle; fleet operation named as future work |
| Battery cybersecurity | Stealthy RL attacks on SoH estimation, 2026 \[Lin 2026\] | Motivates our health-report trust layer |

The trend is clear: monitoring is maturing, and the open question every programme points to is the multi-vehicle policy that uses it. That is where MASooda sits.

## The gap

No work we found combines live, multi-vehicle battery state with tactical traffic decisions and defends that input against falsification. Six specific gaps follow (refined from the team's 7 Nov review):

| # | Gap | Evidence |
| --- | --- | --- |
| G1 | The traffic manager is health-blind: priority, layers and deconfliction weights ignore SoC, SoH and temperature | Jover 2022; FAA 2020 |
| G2 | Prognostics stop at one vehicle, without knowledge of surrounding traffic or shared landing pads | Ancel 2024; Hogge 2024; Montazeri 2024 |
| G3 | The energy cost of deconfliction is measured, not managed: a low-reserve drone can still be the one forced to manoeuvre | Zongo & Wei 2026 |
| G4 | Health telemetry is unprotected once it drives priority: a drone could fake CRITICAL to jump the queue, or hide a real fault | Lin 2026 (attacks exist on estimates); no traffic-level study found |
| G5 | Safety specifications ignore energy and heat: STL covers separation, not reserve or temperature | Pant 2018 |
| G6 | No traffic-management study evaluates heat-wave conditions (40–44 °C) and their effect on derating, diversions and throughput | Policy asks for health monitoring (MoCA 2021); no study found |

**Caveat:** G4 and G6 are absences in our searches, not proven absences. Re-search before submission and read the full texts of Kleinbekman 2018, Montazeri 2024 and Zongo & Wei 2026, whose details here come partly from abstracts.

## Link to MASooda

The health foundation is built; the traffic-side uses of it are mostly not. Status as of the p2\_week7 merge:

| Capability | Status | Where |
| --- | --- | --- |
| Power, battery circuit, temperature and BMS model (sections 1–5 above) | Built | simulation/drone\_health.py |
| Fault injection: capacity loss, cell failure, overheating, motor degradation, GNSS degradation | Built | drone\_health.py, scenario presets |
| Onboard response: low-reserve diversion, forced landing, overheat speed limit | Built | simulation/route\_engine.py |
| DTC right of way for CRITICAL/FAULT drones, lower SoC first, landing pad reserved, no energy-costly climb | Built, binary rule | route\_engine.py |
| Fleet recall below a SoC threshold | Built | simulation/dtc\_console.py |
| Continuous health score in DTC priority and layer choice | Not yet | overseer.py |
| Energy-weighted ADMM (who absorbs the manoeuvre) | Not yet | conflict\_resolution/ |
| Energy and thermal STL specifications | Not yet | verification/ |
| Trust checks on health reports | Not yet (W-MSR covers positions only) | resilience/ |
| Energy-aware altitude layers | Designed (Altitude Layer Design doc) | overseer.py, config |
| Health model in the main experiment engine (engine.py) | Not yet: health lives in the live-demo route engine only | simulation/engine.py |

The last row matters for the paper: the Week 6 experiments run on engine.py, so health must reach that engine, or the experiments move to the route engine, before results can be reported. The altitude-layer separation bug from the 9 Nov review must be fixed first in either case.

## Proposed contributions

Five contributions, ordered by value to the paper. C1–C3 form the core claim; C4 is the strongest differentiator; C5 grounds it in Hyderabad conditions.

### C1. Continuous health score for DTC priority (closes G1, G2)

Replace the binary CRITICAL rule with margins. For drone i, the energy and thermal margins are:

```latex
m_{E,i} = \frac{E_{rem,i} - E_{need,i}(\text{nearest pad})}{E_{need,i}(\text{nearest pad})}, \qquad m_{T,i} = \frac{T_{crit} - T_{pack,i}}{T_{crit} - T_{amb}}
```

The health urgency combines them with the BMS level b\_i (0 = NORMAL … 3 = FAULT):

```latex
u_i = w_E\,\sigma\!\left(\frac{\bar m_E - m_{E,i}}{s_E}\right) + w_T\,\sigma\!\left(\frac{\bar m_T - m_{T,i}}{s_T}\right) + w_B\,\frac{b_i}{3}, \qquad \pi_i = \min\bigl(\pi_{type,i},\; \lfloor 3(1 - u_i) \rfloor\bigr)
```

σ is the logistic function, so urgency rises smoothly as margins shrink below their thresholds. Effective priority π\_i takes the more urgent of mission type and health. The DTC then sequences landings by π\_i and, within a pad, by the latest feasible arrival time implied by E\_rem (the online, en-route version of Kleinbekman 2018).

### C2. Energy-fair ADMM conflict resolution (closes G3)

Today's ADMM chooses velocities close to each drone's desired velocity, weighted by type priority. Make the weight grow as energy margin shrinks, so drones with reserve absorb the manoeuvre:

```latex
\min_{v_1..v_N} \sum_i w_i\,\lVert v_i - v_i^{des}\rVert^2 \;\text{s.t. separation}, \qquad w_i = w_{type,i}\left(1 + \frac{\kappa}{\max(m_{E,i}, \varepsilon)}\right)
```

An optional hard constraint caps the extra energy any drone can be asked to spend, where ΔP\_i is the power increase of the new velocity over the manoeuvre time τ:

```latex
\Delta E_i = \Delta P_i(v_i)\,\tau \le \beta\, m_{E,i}\, E_{need,i}
```

The paper reports the energy-overhead distribution (median, 95th percentile, maximum) with and without this, directly comparable to Zongo & Wei 2026.

### C3. Energy and thermal STL shield (closes G5)

Add two specifications beside separation, each with a robustness value:

```latex
\varphi_E = \mathbf{G}\,(E_{rem} - E_{need}(\text{nearest pad}) - E_{res} \ge 0), \qquad \rho_E(t) = \min_i\bigl(E_{rem,i} - E_{need,i} - E_{res}\bigr)
```

```latex
\varphi_T = \mathbf{G}\,(T_{pack} \le T_{max}), \qquad \rho_T(t) = \min_i\,(T_{max} - T_{pack,i})
```

Normalising each by its scale gives one fleet safety robustness, ρ = min(ρ\_sep/d\_min, ρ\_E/E\_res, ρ\_T/ΔT). The shield acts before violation using a time-to-violation estimate, where Ė\_need is how fast the energy to the nearest pad changes as the drone flies:

```latex
t^{*}_{E,i} = \frac{E_{rem,i} - E_{need,i} - E_{res}}{P_{elec,i} - \dot E_{need,i}} \quad\Rightarrow\quad \text{DTC divert or re-sequence if } t^{*}_{E,i} < \tau_{act}
```

### C4. Trusted health telemetry (closes G4)

Once health buys priority, a drone has a reason to lie. Two attacks matter: faking CRITICAL to jump the queue, and hiding a real fault. The DTC can check each report against physics it observes independently: tracked speed and climb imply a power draw, and the reported SoC must fall accordingly.

```latex
r_i(t) = \Bigl|\,\Delta SoC_i^{rep} - \frac{\hat P_{elec}(v_i^{obs}, \dot h_i^{obs})\,\Delta t}{3600\,V\,Q_{nom}\,SoH_i}\Bigr|, \qquad S_i(t) = \max\bigl(0,\; S_i(t-1) + r_i(t) - k\bigr)
```

A CUSUM statistic S\_i above threshold h flags the drone. A trust score τ\_i ∈ \[0, 1\] then blends reported and type-based priority, so an untrusted drone cannot gain right of way:

```latex
\pi_i^{eff} = \tau_i\,\pi_i^{health} + (1 - \tau_i)\,\pi_{type,i}
```

Peer reports of a neighbour's observed motion can be fused with W-MSR, reusing MASooda's existing resilience layer. The metrics are time to detection, false accusations and priority gained by the liar.

### C5. Energy-aware layers and hot-climate operations (closes G6)

Use the 7-layer altitude design. Each drone's layer minimises climb plus cruise energy, with wind rising with height by a power law (α ≈ 0.3 assumed for urban terrain):

```latex
\ell_i^{*} = \arg\min_{\ell}\left[\frac{m_i g\,(h_\ell - h_0)}{\eta} + P_{elec}\bigl(v_{air}(h_\ell)\bigr)\frac{L_i}{v_{g,i}}\right], \qquad w(h) = w_{ref}\left(\frac{h}{h_{ref}}\right)^{\alpha}
```

The choice is subject to layer capacity and direction rules. Low-margin drones are restricted to the lowest feasible layer. All of this runs at 35 °C and at a 42 °C heat wave, where hotter air and worse pack cooling shrink margins across the fleet.

## Applications

| Setting | What health-aware traffic management changes |
| --- | --- |
| Medical delivery (blood, medicines, AEDs to a hospital pad) | A low-battery delivery drone is not forced to yield to routine traffic and land off-site with its payload; the hospital pad is sequenced by urgency and energy deadline |
| Campus and city parcel delivery fleets | Manoeuvre energy shifts to drones with reserve, cutting diversions and forced landings; battery wear per delivery becomes a managed cost (section 6 model) |
| Heat waves in Indian cities | The DTC tightens reserves and restricts layers when 40–44 °C air and hot packs shrink margins fleet-wide |
| Disaster response | Fleets recalled or re-sequenced by remaining energy when charging infrastructure is limited |
| eVTOL vertiports | Arrival sequencing uses live energy deadlines en route, not only at the terminal |
| Regulators and UTM service providers | A concrete design for the real-time health-monitoring and contingency services named in India's UTM policy framework |
| Security | Health-report trust checks stop a compromised or dishonest drone from gaming priority |

## Experiment and evaluation plan

The headline experiment compares three DTC policies on the IITH map under identical seeds.

**Policies:**

1. **Health-blind:** priority from mission type only (today's main engine).
2. **Binary rule:** CRITICAL/FAULT drones get right of way (today's live engine).
3. **Health-aware:** C1 + C2 + C3, with C4 switched on in the attack scenarios.

**Factors:**

| Factor | Levels |
| --- | --- |
| Ambient temperature | 35 °C (pre-monsoon), 42 °C (heat wave) |
| Fault scenario | None; capacity loss; cell failure; overheating |
| Health-report attack | None; fake CRITICAL to gain priority; hidden real fault |
| Fleet size | 30, 60, 90 drones |
| Seeds | 10 per cell |

**Metrics:**

| Metric | Definition | Target |
| --- | --- | --- |
| Energy-exhaustion events | Drones reaching SoC\_min airborne | 0 |
| Diversions and forced landings | Battery-driven events per 100 flights | Lower than both baselines |
| Energy-overhead distribution | Median, 95th percentile and maximum extra energy from deconfliction | Narrower tail than health-blind; compare with Zongo & Wei 2026 |
| Emergency delay | Delay of emergency missions versus nominal | No worse than health-blind |
| Throughput | Arrivals per minute | Within 5 % of health-blind |
| Fleet safety robustness | Minimum of normalised ρ\_sep, ρ\_E, ρ\_T | Positive throughout |
| Fairness | Jain's index of delay and of energy cost across drones | Higher than health-blind |
| Attack resilience | Time to detection, false accusations, priority gained by the liar | Fast detection, no false accusations |

**Ablations:** C1 alone, C1 + C2, C1 + C2 + C3, each with and without C4, to show what each piece contributes.

**Threats to validity:** the battery model is a documented equivalent circuit, not calibrated to a specific cell; corridors are traced from a schematic map and OpenStreetMap; and the ADMM and DTC run in simulation, not on flight hardware. Each is stated in the paper.

**Candidate venues:** IEEE/AIAA Digital Avionics Systems Conference (DASC), where both Kleinbekman 2018 and Ancel 2024 appeared; IEEE ICUAS; and IEEE Transactions on Intelligent Transportation Systems for a full journal version.

## References

Sources marked \* were opened and checked on 9–10 Nov 2026; the rest were checked in the team's 7 Nov literature review or are standard textbooks.

1. \*E. Ancel, A. J. Moore, S. D. Young, E. T. Dill, C. Quach, K. M. Smalling, "[Testing a Run-Time Assurance Framework Coupled with Integrated Risk Mitigation Capabilities for Autonomous Urban UAS Flights](https://sacd.larc.nasa.gov/wp-content/uploads/sites/167/2025/04/Ancel-et-al-2024.pdf)," IEEE/AIAA DASC, 2024.
2. D. Bernardi, E. Pawlikowski, J. Newman, "A General Energy Balance for Battery Systems," *J. Electrochem. Soc.*, 132(1):5–12, 1985.
3. T. Darrah, "[A Health-Aware Replanning Framework for Unmanned Aerial Vehicles in Stochastic Environments](https://ir.vanderbilt.edu/handle/1803/18588)," PhD thesis, Vanderbilt University, 2023.
4. K. Ellis, P. Krois, J. Koelling, L. Prinzel, M. Davies, R. Mah, "[A Concept of Operations and Design Considerations for an In-time Aviation Safety Management System (IASMS) for Advanced Air Mobility](https://ntrs.nasa.gov/api/citations/20205011003/downloads/IASMS%20ConOps%20for%20AIAA%20Sci%20Tech%20Conference%20January%202021%20202011_STRIVESsubmit.docx.pdf)," NASA, 2021.
5. Federal Aviation Administration, "[UTM Concept of Operations v2.0](https://www.faa.gov/sites/faa.gov/files/2022-08/UTM_ConOps_v2.pdf)," 2020.
6. E. F. Hogge, C. S. Kulkarni, K. W. Eure, K. Darafsheh, S. L. Vazquez, K. M. Smalling, C. C. Quach, "[Performance of Two Battery Prognostic Applications used by Two Octocopters](https://ntrs.nasa.gov/citations/20230012868)," NASA/TM-20230012868, 2024.
7. \*J. Jover, A. Bermúdez, R. Casado, "[Priority-Aware Conflict Resolution for U-Space](https://www.mdpi.com/2079-9292/11/8/1225)," *Electronics*, 11(8):1225, 2022.
8. \*I. C. Kleinbekman, M. A. Mitici, P. Wei, "[eVTOL Arrival Sequencing and Scheduling for On-Demand Urban Air Mobility](https://bpb-us-w2.wpmucdn.com/web.seas.gwu.edu/dist/9/15/files/2019/07/dasc18_imke.pdf)," IEEE/AIAA DASC, 2018.
9. C. Kulkarni, E. Hogge, C. C. Quach, "[Remaining Flying Time Prediction Implementing Battery Prognostics Framework for Electric UAVs](https://ntrs.nasa.gov/citations/20180004466)," AIAA Propulsion and Energy Forum, 2018.
10. H. J. LeBlanc, H. Zhang, X. Koutsoukos, S. Sundaram, "[Resilient Asymptotic Consensus in Robust Networks](https://engineering.purdue.edu/~sundara2/papers/journals/JSAC_robust_consensus.pdf)," *IEEE JSAC*, 31(4), 2013.
11. J. G. Leishman, *Principles of Helicopter Aerodynamics*, 2nd ed., Cambridge University Press, 2006.
12. \*M. Lin, H. Li, J. Meng, "[Reinforcement learning-driven adaptive stealthy attacks manipulating battery state of health estimation](https://www.sciencedirect.com/science/article/abs/pii/S0306261926008718)," *Applied Energy*, 421:128217, 2026.
13. Z. Liu, R. Sengupta, "[An Energy-Based Flight Planning System for Unmanned Traffic Management](https://its.berkeley.edu/publications/energy-based-flight-planning-system-unmanned-traffic-management)," IEEE SysCon, 2017.
14. Ministry of Civil Aviation, Government of India, "[National UTM Policy Framework](https://www.civilaviation.gov.in/sites/default/files/migration/National-UTM-Policy-Framework-2021_24_Oct_2021.pdf)," 24 Oct 2021.
15. \*M. Montazeri, C. S. Kulkarni, O. Fink, "[Prescribing Optimal Health-Aware Operation for Urban Air Mobility with Deep Reinforcement Learning](https://arxiv.org/abs/2404.08497)," arXiv:2404.08497, 2024.
16. Y. V. Pant, H. Abbas, R. A. Quaye, R. Mangharam, "[Fly-by-Logic: Control of Multi-Drone Fleets with Temporal Logic Objectives](https://repository.upenn.edu/handle/20.500.14332/40605)," ACM/IEEE ICCPS, 2018.
17. G. L. Plett, *Battery Management Systems, Vol. I: Battery Modeling*, Artech House, 2015.
18. \*C. Quach, K. Darafsheh, "[HERMES: Applications for Safe Autonomous Aircraft Operations](https://ntrs.nasa.gov/citations/20260000517)," NASA cFS Symposium, January 2026.
19. B. Saha et al., "[Battery Health Management System for Electric UAVs](https://c3.ndc.nasa.gov/dashlink/static/media/publication/2011_IEEEAerospace_UAVBHM.pdf)," IEEE Aerospace Conference, 2011.
20. P. Sharma, E. Atkins, "[Prognostics-Informed Battery Reconfiguration in a Multi-Battery Small UAS Energy System](https://arxiv.org/abs/2103.01883)," arXiv:2103.01883, 2021.
21. J. Wang et al., "Cycle-life model for graphite-LiFePO4 cells," *Journal of Power Sources*, 196(8):3942–3948, 2011.
22. X. G. Yang, T. Liu, S. Ge, E. Rountree, C. Y. Wang, "[Challenges and key requirements of batteries for electric vertical takeoff and landing aircraft](https://doi.org/10.1016/j.joule.2021.05.001)," *Joule*, 5(7):1644–1659, 2021.
23. T. Zhao et al., "[A Critical Review on the Battery System Reliability of Drone Systems](https://doi.org/10.3390/drones9080539)," *Drones*, 9(8):539, 2025.
24. \*A. Zongo, P. Wei, "[eVTOL Aircraft Energy Overhead Estimation under Conflict Resolution in High-Density Airspaces](https://arxiv.org/abs/2604.06093)," arXiv:2604.06093, 2026.
