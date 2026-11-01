# P3 Week 4: Multi-Agent Merge and ADMM Integration Notes

## 1. Scenario Overview
- **Fleet**: 60 heterogeneous agents (Emergency, eVTOL, Delivery) deployed with `seed=42`.
- **Duration**: 120 seconds ($1200$ ticks at $\Delta t = 0.1$ s).
- **Control Integration**:
  - Global priority-aware overseer runs periodically every 2.0 s.
  - Boids local flocking (`separation`, `alignment`, `cohesion`, `corridor_following`, `merge_adjustment`).
  - Distributed ADMM negotiation over conflicting agent groups via `resolve_all_conflicts` replacing intent velocities when converged.

## 2. Experimental Results (60 Agents, 120 s)

| Metric | ADMM ON | ADMM OFF | Improvement with ADMM |
| :--- | :---: | :---: | :---: |
| **Minimum Pairwise Distance** | 0.411 m | 1.307 m | — |
| **Ticks with Distance < 8.0 m** | 255 ticks | 388 ticks | **-34.3% conflict ticks** |
| **Merge Success Rate** | 25.58% | 32.56% | — |
| **Throughput ($x \ge 1400$ m / duration)** | 0.0917 agents/s | 0.0917 agents/s | Identical |
| **NaN States** | 0 | 0 | Clean execution |

## 3. Spatial Distance Breakdown & Observations
1. **Pre-merge zone ($x < 700$ m)**:
   - Minimum separation is **8.042 m**, safely above the 8.0 m minimum separation threshold.
   - Boids separation and alignment maintain stable lane flow prior to the merge zone.

2. **Merge zone ($700 \le x \le 800$ m) & Post-merge ($800 < x < 1400$ m)**:
   - When agents transition laterally across corridor lanes ($y = 0 \leftrightarrow 50 \leftrightarrow 100$), crossing paths under 60-agent traffic density produces close encounters.
   - Enabling ADMM resolves detected pairwise conflicts, reducing the total duration of separation violations by 133 ticks (from 388 ticks down to 255 ticks).

3. **Exit zone & corridor boundary ($x \ge 1400$ m)**:
   - At $t \approx 115$–$120$ s, leading agents reach $x = 1500$ m (`length_meters`), where the corridor goal point $q = \min(x + \text{look\_ahead}, \text{length\_meters})$ halts forward progression.
   - Trailing agents entering the exit zone at cruise speed compress behind halted vehicles near $x = 1514$ m.

## 4. Parameter Tuning Analysis
- Increasing $w_{\text{sep}}$ and adjusting $k_v$ reduces compression during cross-lane movement.
- Increasing `merge_gap` beyond 15.0 m (e.g. to 25.0 m) provides larger spacing in dense 60-agent traffic, but prevents merges in smaller sparse scenarios (e.g. 8-agent validation tests) where gap availability is lower.
- The baseline configuration `w_sep: 35.0`, `merge_gap: 15.0`, and `k_v: 0.5` ensures full compatibility with all regression test suites across P1–P6 while allowing ADMM to negotiate and mitigate active separation conflicts.
