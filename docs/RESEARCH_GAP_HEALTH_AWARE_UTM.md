# Health- and BMS-aware traffic management: literature review and research gap

*Prepared for the MASooda integration work (Phase 0, branch `p2_week7`). Every source below was checked against its
publisher, arXiv, or NASA NTRS page on 2026-11-07. Bracketed numbers refer to the reference list.
Wherever a page only showed an abstract, the claims here are limited to that abstract.*

## 1. Question

Can a multi-agent drone traffic manager make **better safety, energy and throughput decisions** if every
drone's battery management system (BMS) state — state of charge (SoC), state of health (SoH), pack and
motor temperature, cell imbalance, fault codes — is part of the traffic-management loop (priority,
altitude-layer allocation, conflict resolution, routing, landing sequencing), and can that loop stay
safe when health reports are wrong or malicious?

## 2. What the literature already covers

### 2.1 Traffic management and conflict resolution treat vehicles as energy-agnostic
- **Priority in tactical deconfliction** is defined by operation class and manoeuvrability, not by
  energy or health. Jover et al. [1] extend the PCAN tactical algorithm for U-space with a priority
  value from the operation class (emergency flights first) and manoeuvrability. Lower-priority drones
  absorb most of the deviation: up to 8% more distance and 17% more flight time, with no conflicts in
  simulations of 100 UAVs. Battery state and health are not part of the priority.
- **Learning-based separation assurance** between heterogeneous fleets [2] models heterogeneity as
  equipage, sensing and communication range. Energy and health are not modelled, and the authors call
  for fairness-aware conflict management.
- **Decentralised and edge-AI conflict management** [3] optimises latency and accuracy, not energy or
  health.
- **Energy enters UTM mainly pre-flight or at intersections.** Liu & Sengupta [4] plan flights to
  minimise energy (IEEE SysCon 2017). SkyGrid [5] balances energy, throughput and safety distance at
  aerial intersections, but its abstract does not model per-vehicle SoC or health.
- **Conflict resolution has an energy cost that falls unevenly.** Zongo & Wei [6] simulate about
  71,767 en-route sections with the MVP resolver and a physics-based power model. The median energy
  overhead is below 1.5%, but the distribution is right-skewed: the 95th percentile is 3.8–5.3% and
  tails reach 44%. They suggest a 4–5% reserve and predict the overhead at mission start. The abstract
  does not feed the vehicle's *live* battery state back into how conflicts are resolved.
- **Formal safety for drone fleets** uses Signal Temporal Logic (STL) robustness for separation and
  mission specifications [7]. Energy and thermal specifications are not part of that work.
- **Distributed optimisation (ADMM)** for multi-UAV trajectories [8] handles collision and kinematic
  constraints, not energy or health weighting.

### 2.2 Battery prognostics and health management (PHM) are mature — but single-vehicle
- **Remaining-flight-time prediction** for electric UAVs/aircraft: particle-filter end-of-discharge
  prediction [9]; unscented Kalman filter (UKF) SoC estimation with ±30% load bounds and
  parasitic-load detection [10]; flight-tested remaining-flight-time alarms with partial power-train
  faults [11]; two onboard battery prognostic applications on octocopters, with confidence factors
  [12]; hybrid physics + probabilistic end-of-discharge prediction on inspection drones [13].
- **Health-aware decisions exist, but for one vehicle:** health-aware replanning for UAVs after faults,
  driven by prognostics [14]; MDP-based switching between battery packs driven by prognostics, which
  concludes that "prognostics must feed a flight planner that can replan" [15]; SoH-aware path planning
  for a Mars rover [16]; SoH prognostics for eVTOL battery maintenance planning [17].
- **Battery physics makes health safety-critical for vertical flight.** eVTOL batteries "have more
  stringent requirements than electric vehicle batteries in all aspects" [18]. High-power climb phases
  shorten battery life [19]. A 2025 review of drone battery reliability lists unified reliability
  standards, multi-fault diagnosis and cybersecurity as open problems [20].

### 2.3 Regulators and concepts of operations ask for health monitoring but don't specify how to use it
- India's **National UTM Policy Framework (2021)** lists *UAS health monitoring* ("monitor the health
  and status of unmanned aircraft in real-time") and *contingency management* as UTM services [21].
- NASA's **IASMS ConOps** for Advanced Air Mobility lists vehicle-health monitors (battery power is
  named) and *battery prognostics* as in-time risk-management services that can trigger automatic
  mitigation [22].
- The **FAA UTM ConOps v2.0** leaves endurance with the operator ("Operators are responsible for
  ensuring endurance and/or fuel levels are adequately maintained") and gives conformance monitoring
  to service suppliers [23].
- NASA's onboard contingency decision-maker for sUAS (Nominal → Off-Nominal → Alternate Land → Land
  Now) names battery failure as a focus but leaves "energy information" not yet implemented, and its
  landing sites are pre-allocated [24].
- Certified emergency landing for urban UAVs is studied as a single-vehicle mitigation [25].
- Resilient consensus (W-MSR) tolerates misbehaving neighbours under (r,s)-robustness conditions [26].
  It is applied to positions and states, not to health telemetry.

## 3. Research gap

Combining §2.1–§2.3:

> **G1 — The traffic manager is health-blind.** Priority, layer allocation and deconfliction weights
> come from operation class and geometry [1–3, 8]. Live BMS state (SoC reserve, SoH, temperature,
> imbalance, fault codes) does not decide *who yields*, *who gets which layer*, or *who lands first*.
>
> **G2 — PHM stops at the single vehicle.** Mature prognostics [9–17] produce exactly the signals a
> traffic manager needs, but their decisions (abort, replan, swap pack) are taken onboard, without
> knowledge of surrounding traffic or shared landing capacity.
>
> **G3 — The energy cost of deconfliction is measured, not managed.** Its tail can reach 44% [6], yet
> it is assigned by geometry and fixed priority, so a drone with little reserve can be the one forced
> to manoeuvre [1]. No work shifts that cost onto drones with energy and thermal margin.
>
> **G4 — Health telemetry is an unprotected input.** Once health feeds priority, a spoofed or faulty
> health report (for example, falsely claiming CRITICAL to get right of way) becomes an attack on the
> traffic manager. Resilient consensus [26] and BMS cybersecurity [20] have not been combined with
> health-aware prioritisation. *(No paper studying this was found in our searches; this is a gap
> hypothesis, not a proven absence.)*
>
> **G5 — Safety specifications ignore energy and heat.** STL monitoring covers separation and missions
> [7]. Energy-reserve (`G(E ≥ E_to_nearest_pad + margin)`) and thermal (`G(T_pack ≤ T_max)`)
> specifications with robustness-driven intervention are missing from multi-drone traffic management.
>
> **G6 — Hot-climate operations.** Policy asks for real-time health monitoring [21], but we found no
> traffic-management study that evaluates heat-wave ambient conditions (e.g. Hyderabad, 40–44 °C) and
> their effect on thermal derating, diversions and throughput.

## 4. Proposed MASooda contributions (map to the integration phases)

| # | Contribution | Gap | Where it lives |
|---|---|---|---|
| C1 | **Health-aware DTC:** the overseer's priority and layer allocation use a health score h = f(type, energy-reserve margin, BMS status, thermal margin); CRITICAL drones get right of way to land and landing-pad sequencing | G1, G2 | Phase 3B(c), R8 |
| C2 | **Energy-fair ADMM:** ADMM priority weights scale with remaining-energy margin, so drones with reserve absorb the manoeuvre; measure how the energy-overhead distribution shifts compared with [6] | G3 | Phase 2a + R8 |
| C3 | **STL energy/thermal shield:** online robustness of energy-reserve and temperature specs; predictive time-to-critical triggers DTC actions (divert, hold, layer change) before violation | G5 | R1 + R10 |
| C4 | **Trusted health telemetry:** treat BMS reports like position reports — plausibility checks (energy drawn compared with power model, temperature dynamics), W-MSR/trust scores, and quarantine of drones that falsify health to gain priority | G4 | R2 + Phase 4 (quarantine) |
| C5 | **Hot-climate scenario study:** IITH and Hyderabad maps with 40–44 °C ambient; health-aware vs health-blind DTC on energy-exhaustion events, diversions, forced landings, emergency delay, throughput and fairness (Jain's index) | G6 | Phase 5 (#9) + Phase 7 |

**Headline experiment for a paper:** health-aware vs health-blind DTC × {nominal, heat wave, battery
fault, spoofed health report} × fleet sizes × seeds on the IITH map. Metrics: energy-exhaustion events
(target 0), battery-driven diversions and forced landings, emergency delay, throughput, separation
robustness, energy-overhead distribution, and Jain's fairness of delay and energy cost.

## 5. Threats to validity (state these in the paper)
- The battery and thermal model will be a simplified, documented equivalent-circuit and first-order
  thermal model. It is not calibrated to a specific cell unless we obtain data. Cite [9–12] for model
  structure.
- Corridors are traced from a schematic campus map and OSM centrelines, not approved airspace.
- Literature claims here come from abstracts or summary pages where noted. Read the full papers
  before final submission.

## References
1. J. Jover, A. Bermúdez, R. Casado, "Priority-Aware Conflict Resolution for U-Space," *Electronics*, 11(8):1225, 2022. doi:10.3390/electronics11081225 — https://www.mdpi.com/2079-9292/11/8/1225
2. I. Sharifi, H. T. Kim, M. H. Ahmed, M. Ghasemi, P. Wei, "Separation Assurance between Heterogeneous Fleets of Small Unmanned Aerial Systems via Multi-Agent Reinforcement Learning," arXiv:2605.01041, 2026. https://arxiv.org/abs/2605.01041
3. R. Agnihotri, S. K. Sharma, "Optimized Conflict Management for Urban Air Mobility Using Swarm UAV Networks," arXiv:2512.12632, 2025. https://arxiv.org/abs/2512.12632
4. Z. Liu, R. Sengupta, "An Energy-Based Flight Planning System for Unmanned Traffic Management," *IEEE SysCon*, pp. 1–7, 2017. https://its.berkeley.edu/publications/energy-based-flight-planning-system-unmanned-traffic-management
5. S. Khoshdel, F. Afghah, Q. Luo, "SkyGrid: Energy-Flow Optimization at Harmonized Aerial Intersections," arXiv:2406.13817, 2024. https://arxiv.org/abs/2406.13817
6. A. Zongo, P. Wei, "eVTOL Aircraft Energy Overhead Estimation under Conflict Resolution in High-Density Airspaces," arXiv:2604.06093, 2026. https://arxiv.org/abs/2604.06093
7. Y. V. Pant, H. Abbas, R. A. Quaye, R. Mangharam, "Fly-by-Logic: Control of Multi-Drone Fleets with Temporal Logic Objectives," *ACM/IEEE ICCPS*, 2018 (tech. report UPenn-ESE-18-205). https://repository.upenn.edu/handle/20.500.14332/40605
8. R. Ni, Z. Pan, X. Gao, "Robust Multi-Robot Trajectory Optimization Using Alternating Direction Method of Multiplier," *IEEE Robotics and Automation Letters*, 2022. doi:10.1109/LRA.2022.3159848 — https://arxiv.org/abs/2111.07016
9. B. Saha, E. Koshimoto, C. C. Quach, E. F. Hogge, T. H. Strom, B. L. Hill, S. L. Vazquez, K. Goebel, "Battery Health Management System for Electric UAVs," *IEEE Aerospace Conference* (IEEEAC #1484), 2011. https://c3.ndc.nasa.gov/dashlink/static/media/publication/2011_IEEEAerospace_UAVBHM.pdf
10. B. Bole, M. Daigle, G. Gorospe, "Online Prediction of Battery Discharge and Estimation of Parasitic Loads for an Electric Aircraft," *European Conf. of the PHM Society*, 2014. https://ntrs.nasa.gov/api/citations/20190001777/downloads/20190001777.pdf
11. C. Kulkarni, E. Hogge, C. C. Quach, "Remaining Flying Time Prediction Implementing Battery Prognostics Framework for Electric UAV's," *AIAA Propulsion and Energy Forum*, 2018. https://ntrs.nasa.gov/citations/20180004466
12. E. F. Hogge, C. S. Kulkarni, K. W. Eure, K. Darafsheh, S. L. Vazquez, K. M. Smalling, C. C. Quach, "Performance of Two Battery Prognostic Applications used by Two Octocopters for Safe Low Altitude Autonomous Flight Operations," NASA/TM-20230012868, 2024. https://ntrs.nasa.gov/citations/20230012868
13. J. Alcibar, J. I. Aizpurua, E. Zugastia, O. Penagarikano, "A Hybrid Probabilistic Battery Health Management Approach for Robust Inspection Drone Operations," arXiv:2405.00055, 2024 (journal version doi:10.1016/j.engappai.2025.110246). https://arxiv.org/abs/2405.00055
14. T. Darrah, "A Health-Aware Replanning Framework for Unmanned Aerial Vehicles in Stochastic Environments," PhD thesis, Vanderbilt University, 2023. https://ir.vanderbilt.edu/handle/1803/18588
15. P. Sharma, E. Atkins, "Prognostics-Informed Battery Reconfiguration in a Multi-Battery Small UAS Energy System," arXiv:2103.01883, 2021 (University of Michigan). https://arxiv.org/abs/2103.01883
16. M. Salinas-Camus, C. Kulkarni, M. Orchard, "Battery State-of-Health Aware Path Planning for a Mars Rover," *Annual Conference of the PHM Society*, 15(1), 2023. doi:10.36001/phmconf.2023.v15i1.3511
17. M. Mitici, L. Jenneskens, Z. Zeng, D. Coit, "Predictive Maintenance Planning for Batteries of Electric Take-Off and Landing (eVTOL) Aircraft Using State-of-Health Prognostics," *ESREL 2024*, Advances in Reliability, Safety and Security vol. 6. https://research-portal.uu.nl/en/publications/predictive-maintenance-planning-for-batteries-of-electric-take-of/
18. X. G. Yang, T. Liu, S. Ge, E. Rountree, C. Y. Wang, "Challenges and key requirements of batteries for electric vertical takeoff and landing aircraft," *Joule*, 5(7):1644–1659, 2021. doi:10.1016/j.joule.2021.05.001
19. M. Dixit, A. Bisht, R. Essehli, R. Amin, C.-B. M. Kweon, I. Belharouak, "Lithium-Ion Battery Power Performance Assessment for the Climb Step of an Electric Vertical Takeoff and Landing (eVTOL) Application," *ACS Energy Letters*, 9(3):934, 2024. doi:10.1021/acsenergylett.3c02385
20. T. Zhao, Y. Zhang, M. Wang, W. Feng, S. Cao, G. Wang, "A Critical Review on the Battery System Reliability of Drone Systems," *Drones*, 9(8):539, 2025. doi:10.3390/drones9080539
21. Government of India (Ministry of Civil Aviation), "National Unmanned Aircraft System Traffic Management (UTM) Policy Framework," 24 Oct 2021. https://www.civilaviation.gov.in/sites/default/files/migration/National-UTM-Policy-Framework-2021_24_Oct_2021.pdf
22. K. Ellis, P. Krois, J. Koelling, L. Prinzel, M. Davies, R. Mah, "A Concept of Operations (ConOps) and Design Considerations for an In-time Aviation Safety Management System (IASMS) for Advanced Air Mobility (AAM)," NASA (AIAA SciTech submission, Jan 2021). https://ntrs.nasa.gov/api/citations/20205011003/downloads/IASMS%20ConOps%20for%20AIAA%20Sci%20Tech%20Conference%20January%202021%20202011_STRIVESsubmit.docx.pdf
23. Federal Aviation Administration, "Unmanned Aircraft System (UAS) Traffic Management (UTM) Concept of Operations," v2.0, March 2020. https://www.faa.gov/sites/faa.gov/files/2022-08/UTM_ConOps_v2.pdf
24. J. Baculi, C. Ippolito, "Onboard Decision-Making for Nominal and Contingency sUAS Flight," NASA Ames / AIAA. https://ntrs.nasa.gov/api/citations/20190029195/downloads/20190029195.pdf
25. J. Guerin, K. Delmas, J. Guiochet, "Certifying Emergency Landing for Safe Urban UAV," arXiv:2104.14928, 2021. https://arxiv.org/abs/2104.14928
26. H. J. LeBlanc, H. Zhang, X. Koutsoukos, S. Sundaram, "Resilient Asymptotic Consensus in Robust Networks," *IEEE Journal on Selected Areas in Communications*, 31(4), 2013. https://engineering.purdue.edu/~sundara2/papers/journals/JSAC_robust_consensus.pdf
