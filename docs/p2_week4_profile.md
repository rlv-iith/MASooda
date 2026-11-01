# P2 Week 4 profile

- Scenario: 30, 45, 60, and 75 agents; all placed in the merge zone with velocity `[12, 0, 0]`; 20 calls per size.
- Before vectorization at 60 agents, mean resolution time was 109.9 ms/tick (max 143.1 ms).
- After vectorization at 60 agents, mean resolution time was 101.1 ms/tick (max 103.5 ms), about 8% faster.
- At 60 agents, detection mean fell from 0.627 ms to 0.234 ms across a separate 100-call comparison (about 63% faster).
- The profiler writes per-size mean/max resolution and detection times, group count, convergence fraction, and iteration field to `outputs/p2_week4_profile.csv`.
- ADMM iteration count is recorded as unavailable (`NaN`): `resolve_all_conflicts` returns events without solver iteration metadata.
- The accompanying bar chart is `outputs/p2_week4_profile.png`.
- Validation: five-seed detector equivalence and the 60-agent one-second bound passed; full suite passed: 161 tests.
