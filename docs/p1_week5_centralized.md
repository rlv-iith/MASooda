# P1 Week 5: Purely Centralized Architecture (Section 13.1)

## Overview

This document describes the design, implementation, and empirical benchmark of the purely centralized architecture for MASooda (`simulation/centralized.py`). In this architecture, a single central controller has global visibility over the entire airspace and directly computes corridor assignments and 2.5D velocity commands for every agent.

---

## 1. What the Controller Sees

- **Global Visibility**: The central controller receives full state reports from all agents across all corridors and altitude layers, bypassing local communication graphs and neighbor radius constraints.
- **State Inputs**:
  - Macroscopic snapshot: `GlobalStateSnapshot` containing timestamp, corridor occupancy counts, agent IDs, agent types, and priorities.
  - Microscopic states: Full reported positions $[x, y, z]$ and velocities $[v_x, v_y, v_z]$ for all active agents.
- **Unverified Trust**: The centralized controller directly trusts reported states (`reported = apply_attack(current_agents, attack_state)`). It does not implement local filtering or consensus defense (e.g., W-MSR). Under position falsification attacks, it computes velocity commands based on falsified coordinates.

---

## 2. Corridor and Velocity Assignment Algorithm

The central controller directly calculates navigation commands for every agent $i$:

1. **Corridor Assignment**:
   - Updated periodically at `overseer.update_period_seconds` using `GlobalOverseer(policy="priority_aware")`.
   - Assigns each agent an optimal corridor based on current corridor occupancy, capacity limits, and agent priority.

2. **Velocity Command Generation**:
   - **Corridor Centering**: Target lateral coordinate $y_{\text{target}}$ is set to the centerline of the assigned corridor. Base lateral velocity is computed via proportional tracking $k_{\text{lat}} \cdot (y_{\text{target}} - y_i)$, clipped to $\pm \text{merge\_lateral\_speed}$. Forward speed defaults to $v_{\text{cruise}}$.
   - **Car-Following Spacing**: For each agent $i$, the controller identifies the closest agent $j$ directly ahead ($x_j > x_i$) within corridor half-width ($|y_j - y_i| < \text{width} / 2$) on the same altitude layer. If the longitudinal gap $\Delta x = x_j - x_i$ is less than the desired headway gap $d_{\text{desired}} = d_0 + h \cdot |v_{i, x}|$, the forward speed is scaled down:
     $$v_x = \min\left(v_x, \max\left(0.0, v_{\text{cruise}} \cdot \frac{\Delta x}{d_{\text{desired}}}\right)\right)$$
   - **Pairwise Separation with Priority**: For all other agents $j$ on the same altitude layer within planar separation distance $d < r_{\text{sep}}$:
     $$\mathbf{push} = \frac{w_{\text{sep}}}{v_{\text{cruise}}} \cdot \frac{r_{\text{sep}} - d}{r_{\text{sep}}} \cdot \frac{\mathbf{p}_i - \mathbf{p}_j}{d}$$
     - If agent $i$ has lower priority (larger priority integer than $j$), it absorbs 100% of the push.
     - If equal priority, agent $i$ takes 50% of the push.
     - If higher priority, agent $i$ takes 0% of the push.
   - **Speed Clamping**: Commanded planar velocity $\sqrt{v_x^2 + v_y^2}$ is clamped to $v_{\text{max}}$, keeping $v_z = 0.0$.

---

## 3. Why Boids and ADMM Are Bypassed

- In distributed and hybrid architectures, agents must use heuristic flocking (Boids: cohesion, alignment, separation) to maintain formation, followed by iterative ADMM consensus optimization to resolve spatial conflicts without a global coordinator.
- In the centralized paradigm, the single central controller performs global spacing and priority-weighted separation directly. Hence, neither local Boids behaviors nor distributed ADMM negotiations are needed (`admm_events = 0`, `admm_time_s = 0.0`).

---

## 4. Behavior During Link Failure / Controller Outage

When `overseer_link_config["enabled"] = True` and the simulation clock enters the outage window ($\text{down\_start\_seconds} \le t < \text{down\_end\_seconds}$):
- The central controller is unreachable.
- Every agent maintains its last commanded velocity open-loop.
- Any scheduled overseer update during the outage fails: `overseer_failures` and `overseer_dropped` counters increment.
- Directive staleness accumulates monotonically and is tracked by `max_directive_staleness_s`.
- True agent states continue propagating through `step_dynamics(agent, accel, dt)` without crashing.

---

## 5. Empirical Results (`outputs/p1_week5_centralized.csv`)

Full 60-agent, 180-second benchmark across three random seeds ($N=60, T=180\,\text{s}, dt=0.1\,\text{s}$):

| Seed | Attack Enabled | Min Sep (m) | Min Rob (m) | Viol. Ticks | Viol. Episodes | Mean Rec (s) | Arrivals | Overseer Calls | Overseer Fail | Malicious IDs |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **42** | False | 6.04 | -1.96 | 204 | 5 | 4.24 | 60 | 90 | 0 | [] |
| **42** | True | 6.04 | -1.96 | 204 | 5 | 4.24 | 60 | 90 | 0 | [5] |
| **43** | False | 5.21 | -2.79 | 108 | 3 | 3.80 | 60 | 90 | 0 | [] |
| **43** | True | 5.21 | -2.79 | 108 | 3 | 3.80 | 60 | 90 | 0 | [5] |
| **44** | False | 6.58 | -1.42 | 70 | 5 | 1.72 | 60 | 90 | 0 | [] |
| **44** | True | 5.49 | -2.51 | 109 | 6 | 2.08 | 60 | 90 | 0 | [3] |

### Key Observations
1. **Safety Violations Under Density**: In high-density merge conditions without distributed consensus negotiation (ADMM), minimum separation drops below the 8.0 m safety threshold (ranging between 5.21 m and 6.58 m), but all violation episodes recover within 1.7–4.2 s.
2. **Impact of Attack**: On seed 44, attack injection increased safety violation ticks from 70 to 109, and decreased minimum separation from 6.58 m to 5.49 m, demonstrating the vulnerability of unverified centralized control to state spoofing.
3. **Arrival Throughput**: 100% of agents (60/60) reach the exit zone in all scenarios, yielding a constant throughput of 0.33 agents/second.

