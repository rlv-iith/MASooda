# P1 Week 4 MVP Run Summary

Command (run after merging all Week 4 branches and the week4 fixes):

```bash
python main.py --scenario mvp --agents 60 --corridors 3
```

## Printed summary

```
=== Simulation Summary (MVP) ===
Agents: 60
Duration: 180.0 s
Min Robustness: -2.562 m
Safety Violations: 377
ADMM Events: 2001
Malicious IDs: [5]
Reports Dropped: 3981
Overseer Dropped: 15
```

Selected values from `metrics.json`: min separation 5.44 m, 12 violation episodes,
0 unrecovered, mean recovery 3.3 s, 56/60 arrivals, max directive staleness 31.9 s,
0 component failures. "Reports Dropped" counts falsified reports that were flagged
and corrected to the sensed range.

## Outputs in `outputs/mvp/`
- `metrics.json`: run metrics and engine counters
- `stl_robustness.csv`: STL robustness per tick
- `stl_events.csv`: violation start/end events
- `trajectory.csv`: full trajectory (git-ignored, ~10 MB)
- `final_frame.png`: top-down view at the final step
- `simulation.gif`: only with `--gif`
