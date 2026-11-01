# P6 Week 2 STL Validation Results
Specification: d_min = 8.0 m, dt = 0.1 s, min_window_steps = 2

## Toy Trajectory Checks
- toy `safe`: rho_min = +4.000 m, violation = False
- toy `unsafe`: rho_min = -5.000 m, violation = True

## Engine Trajectory Check
- rho min: -0.472 m
- number of ticks with rho < 0: 100 / 601
- no NaN: True

## Live Sliding Window Check
- mean time per tick: 0.839 ms
