# Layer agreement: V2V negotiation of altitude layers with DTC pricing

Code: `simulation/layer_agreement.py` · config: `layer_agreement:` in `configs/base_config.yaml` ·
tests: `tests/test_layer_agreement.py`.

## Problem

Before this change every non-emergency drone cruised on L0 (eastbound) or L1 (westbound), and the
DTC allocator only knew layers 0, 1 and the emergency layer, so it pushed capacity overflow back onto
L1. Drones queued behind each other under the car-following law `v = (gap − d_0) / h` while L2–L5
stayed empty (300 drones: 84 % of airborne time on L0/L1, 1 % on L2–L5).

## Decision variable

A drone's slot is (sector *s*, direction lane *d*, layer *L*). The lane follows from the route (the
20 m tube fits one keep-left lane per direction at d_min = 8 m), so the free choice is the layer.
Semicircular rule: eastbound drones use even layers, westbound odd layers, never the emergency layer:

  A_d = { L : L ≠ L_emg, L mod 2 = d }   (7 layers: east {0, 2, 4}, west {1, 3, 5}, emergency 6)

## 1. Local cost (onboard, from V2V reports)

  J_i(L) = w_f φ_i(L) + w_p λ_i(L) + w_e c_i(L) + w_s [L ≠ L_i] + w_dir [L ∉ A_d]

| Term | Meaning |
|---|---|
| φ_i(L) = 1 − v_eff / v_c, v_eff = min(v_c, max(0, (g_i(L) − d_0) / h)) | speed lost behind the nearest drone ahead on L in my tube (gap g); 1 if traffic comes head-on |
| λ_i(L) | congestion price of (my sector, L), agreed with neighbours (2) |
| c_i(L) = max(0, L − L_i) · H / H_ref · (1 + k_b (1 − SoC_i)) | climb energy, dearer on a low battery |
| [L ≠ L_i] | switching cost (hysteresis) |
| [L ∉ A_d] | wrong-parity layer (after a tactical shift) |

## 2. Price agreement (consensus-based dual ascent)

Each round (1 s) every drone updates its price vector from its sector neighbours' prices and the load
it hears:

  λ_i(L) ← clip( M{ λ_j(L) : j ∈ N_i(s) ∪ {i} } + α (ℓ_i(L) − κ) / κ , 0, λ_max )

ℓ_i(L) = neighbours heard on L in my sector, κ = target load. M is the mean, or the W-MSR trimmed
mean (f = 1) when the report defence is on, so one outlying neighbour cannot move the price (P5).
This is dual ascent on the slot-load constraint, with the dual variable agreed by consensus. With the
DTC link up, the DTC seeds every drone in sector *s* with
λ^DTC_{s,L} = max(0, n_{s,L}/C − θ) / (1 − θ) from its global count n_{s,L} (C = capacity per
sector-layer). With the link down the drones keep agreeing among themselves.

## 3. Agreement on who moves (local mutual exclusion)

  L*_i = argmin_{L ∈ A_d ∪ {L_i}} J_i(L),  gain g_i = J_i(L_i) − J_i(L*_i)

A drone with g_i > δ announces (L*_i, g_i). It moves only if no neighbour announcing the same L* has a
larger key (g, higher priority, lower id), so at most one drone enters a layer per neighbourhood per
round, and only if the layer-transition safety check passes. A cooldown prevents oscillation.

Departures use the same terms: a drone takes the cheapest layer of its direction that has a merge
gap at the corridor junction, instead of waiting on the pad for L0/L1.

## 4. Stuck → DTC

A drone held below f_stuck · v_c for T_stuck s (not on approach, not held, not speed-capped or
overheating) that could not move asks the DTC. At its next update (link up), the DTC settles all
requests with its own cost over its global picture:

  min Σ_i w_i K_i(L_i)  s.t.  n_{s,L} < C,  L_i ∈ A_d,  transition clear

  w_i = (1 + w_pr / (1 + P_i)) · (1 + w_bat (1 − SoC_i))      priority and battery weight
  K_i(L) = w_d (T_i(L) − T_i⁰) / T_i⁰ + w_b c_i(L) / max(SoC_i, 0.05) + w_l n_{s,L} / C + w_sw |L − L_i|

T_i(L) = r_i / max(v_eff(L), 0.5) is the expected remaining flight time on L (r_i = remaining route)
and T_i⁰ = r_i / v_c. It is solved greedily in decreasing w_i: the highest priority, then the lowest
battery, chooses first, the usual heuristic for weighted assignment with capacities. If no allowed
layer is free, safe and faster, the request is denied and the drone keeps following.

## Results

IITH map, 300 drones, 240 s, seed 42, hierarchical architecture, junction merging on:

| | Before | Fixed DTC allocator only | + departure spread + V2V agreement + DTC |
|---|---|---|---|
| Airborne time L0 / L1 / L2–L5 / L6 | 41 / 43 / 1 / 15 % | 33 / 39 / 13 / 14 % | 20 / 23 / 46 / 11 % |
| Arrivals in 240 s | 181 | 183 | **246** |
| Non-emergency time below 50 % of cruise | 6.4 % | 4.8 % | **2.3 %** |
| Near misses · min separation | 1 · 7.6 m | 1 · 7.6 m | **0 · 12.8 m** |
| ADMM conflict events | 7549 | 4166 | **2189** |
| Tactical layer shifts | 58 | 39 | 23 |
| Compute time | 55 s | 65 s | 75 s |

In the full run: 52 agreed switches, 21 yields to a neighbour, 142 departures spread above the
lowest layer, 21 stuck requests (1 resolved by the DTC, 20 denied).

## Notes and limits

- The agreement runs in the hierarchical and both decentralized architectures (without the DTC
  parts when there is no DTC); the centralized architecture keeps the DTC allocator only.
- Non-cooperative, quarantined, emergency, operator-pinned and unhealthy drones do not negotiate.
- Price messages are not attacked in this model; W-MSR bounds the effect of outlying prices.
- Tactical one-layer shifts (CPA avoidance) can still cross parity; the w_dir term brings the drone
  back to its direction's layers.
- The Week 6 experiment outputs were produced before this change and have not been regenerated.
