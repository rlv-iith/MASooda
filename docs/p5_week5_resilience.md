# P5 Week 5: E4 architecture comparison under attack

## Decentralized-undefended architecture

`resilience/decentralized_undefended.py` runs the fleet with local boids and
ADMM conflict handling between neighbours, but with no central overseer and no
defence. Honest agents use the raw, possibly falsified, neighbour reports
directly in their averaging-based boids terms (the plain-averaging baseline from
Week 2). Nothing is filtered (no W-MSR, no range check). Agents keep the
corridor they start with. The `overseer_link_config` argument is accepted only
for signature compatibility and is ignored.

## E4 setup

`scripts/p5_week5_e4_resilience.py --quick`: 30 agents, 90 s, seed 42. Every run
starts from a `copy.deepcopy` of the same initial agents. One agent falsifies its
position from t = 60 s (config `attack`: constant 25 m offset). Each architecture
is run with the attack off and on. Architectures: hierarchical (overseer + ADMM +
W-MSR/range-check defence), decentralized_undefended. The centralized baseline
(`simulation.centralized`) is not merged yet and was skipped.

## Results (quick run, seed 42)

| Architecture | Attack | Throughput (1/s) | Violation ticks | Post-attack violation ticks | Mean recovery (s) | Min robustness (m) | Reports dropped |
|---|---|---|---|---|---|---|---|
| hierarchical | off | 0.0 | 773 | 209 | 36.9 | -7.98 | 0 |
| hierarchical | on | 0.0 | 798 | 234 | 38.4 | -7.98 | 2360 |
| decentralized_undefended | off | 0.0 | 0 | 0 | n/a | 0.04 | 0 |
| decentralized_undefended | on | 0.0 | 0 | 0 | n/a | 0.04 | 0 |

Throughput is 0 everywhere because 90 s is too short for agents to reach the exit
zone. Plots: `outputs/p5_week5_e4_resilience.png`,
`outputs/p5_week5_e4_robustness_time.png`; data: `outputs/p5_week5_e4_resilience.csv`.

## Comparison

In this single-seed quick run the attack barely changes either architecture: the
hierarchical one gains 25 violation ticks, the undefended one gains none. The
undefended decentralized fleet keeps its separation (minimum robustness 0.04 m,
no violations) even with a lying neighbour, so a 25 m falsification on one agent
is not enough to break plain averaging at this density. The hierarchical
architecture shows violations (min robustness -7.98 m) even with the attack off,
so those come from overseer corridor re-assignment and not from the attack. The
defence works as intended (2360 reports dropped) but its benefit cannot be
shown here, because the undefended baseline has nothing to improve on. The full
run (60 agents, full duration, three seeds) is needed before drawing conclusions.
