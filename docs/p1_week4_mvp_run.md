# P1 Week 4 MVP Run Summary

The real simulation command was executed with:
```bash
python main.py --scenario mvp --agents 60 --corridors 3
```

## Printed Summary

```
=== Simulation Summary (MVP) ===
Agents: 60
Duration: 180.0 s
Min Robustness: -7.937 m
Safety Violations: 879
ADMM Events: 2018
Malicious IDs: [5]
Reports Dropped: 0
Overseer Dropped: 0
```

## Generated Outputs in `outputs/mvp/`
- `metrics.json`: Run metrics, counters, and robustness summary.
- `stl_robustness.csv`: Logged STL robustness time series per tick.
- `trajectory.csv`: Full agent trajectory dataset.
- `final_frame.png`: Airspace top-down render at final simulation step.

