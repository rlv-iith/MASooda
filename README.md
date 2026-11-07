# Urban Aerial Hierarchical Swarm Governance

Simulation and evaluation of a hierarchical traffic-management system for autonomous drones operating in crowded urban airspace.

## Project Overview

The system combines local drone-to-drone decision-making with a centralized Drone Traffic Controller (DTC). Drones exchange information to make immediate safety decisions, while the DTC manages corridor allocation, traffic priorities, and global flow.

The simulation focuses on:

- Safe separation, collision avoidance, and destination arrival
- Heterogeneous drones with different priorities, speeds, routes, and communication capabilities
- Drone-to-drone, drone-to-DTC, and DTC-to-drone communication
- Low, medium, and high traffic densities, including merging and conflicting flows
- Communication loss, faulty data, false intent, and rule violations
- Resilient behavior when the DTC is unavailable or agents provide misleading information

## Scope

The core implementation uses a bounded 2.5D urban airspace with predefined corridors, intersections, entry and exit points, and obstacles. Drones are modeled primarily by position, velocity, destination, and priority. Detailed aircraft physics, full-city modeling, complex cyberattacks, and real-world certification are outside the core scope.

 The following sequence is the implementation plan for the project.
## Timeline
- Mid-September 2026 - Project proposal approved by the Instructor
- Estimated Completion - Early November


## Individual Contributions

### Abdur Rehman and Dhadheechi

- Build the live simulation world, including agent dynamics, the communication graph, rendering, and module integration
- Formalize safety requirements as Signal Temporal Logic (STL) specifications
- Implement STL robustness monitoring
- Assemble the final dashboard and visualization

### Lalith Vishnu

- Design and implement the distributed optimization layer using Alternating Direction Method of Multipliers (ADMM)
- Resolve yielding, merging, and rerouting conflicts between agents

### Bhuvan

- Implement Boids-style local rules for alignment, cohesion, and separation
- Implement corridor and platoon merging logic
- Support autonomous formation behavior

### Tanmay

- Develop the centralized DTC node
- Implement corridor allocation and priority arbitration across drone types
- Apply global traffic rules and priority ordering

### Sampadram

- Implement fault and attack injection
- Implement W-MSR-style resilient consensus
- Maintain resilient swarm behavior in the presence of malicious or faulty agents

## Demonstration Plan

The final demonstration will use a dual-screen dashboard:

1. **Live simulation:** A top-down airspace view showing colored drone agents, corridor lanes, malicious-agent indicators, and DTC directives.
2. **Live dashboard:** STL robustness, emergency-priority compliance, and an ADMM convergence timer.

The demonstration will cover normal corridor formation, a malicious drone with a dropped DTC connection, and emergency-drone priority routing.

## Evaluation Criteria

- Minimum separation and collision avoidance
- Successful destination arrival
- Priority compliance for emergency drones
- ADMM conflict-resolution convergence
- STL robustness over time
- Behavior under communication loss and faulty or malicious information

## Repository Structure

The repository is organized around the simulation, coordination algorithms, resilience mechanisms, safety monitoring, and visualization. Keep modules independently testable and document configuration or scenario changes alongside the relevant code.

## Development Standards

- Keep commits focused and use descriptive commit messages.
- Use consistent formatting and meaningful names.
- Document public interfaces, assumptions, and scenario configuration.
- Add tests for coordination, safety, resilience, and communication-loss behavior.
- Make experiments reproducible by recording parameters, traffic density, random seeds, and observed metrics.
- Keep core simulation logic separate from rendering and dashboard code.

## Status and how to run

**Week 6 — provisional results.** All experiments E1–E6 run end to end (141 simulations); the
safety metric, attack and compliance fixes are pending, so every number is marked provisional.

### Architecture

Two tiers: a global overseer (`simulation/overseer.py`) assigns corridors and altitude layers
every 2 s; each agent runs boids-style local behaviour with corridor merging
(`local_behavior/`) and ADMM conflict mitigation in the merge zone (`conflict_resolution/`),
filters neighbour reports with W-MSR (`resilience/`), and is monitored against the STL
specification G(d_ij ≥ d_min) (`verification/`). All parameters live in
`configs/base_config.yaml`.

Three architectures share one engine and one runner (`experiments/runner.py`):

| Architecture | Overseer | Local behaviour + ADMM | Report filter |
|---|---|---|---|
| `hierarchical` | yes | yes | W-MSR + range check |
| `centralized` | one controller commands every velocity | no | no |
| `decentralized_undefended` | no | yes | no |

### Run a scenario

```bash
python main.py --architecture hierarchical --scenario mvp --agents 60 --duration 180 --out outputs/mvp --telemetry
```

Writes `metrics.json`, `run_row.csv`, `trajectory.csv`, `stl_robustness.csv`, `telemetry.csv`
and `final_frame.png` (`--gif` adds an animation).

### Dashboard

```bash
python scripts/dashboard.py --live --scenario demo
```

```bash
python scripts/dashboard.py --replay outputs/mvp --out outputs/mvp/dashboard.gif
```

Left: the airspace (agents by type, emergency highlighted, malicious agent with its falsified
"ghost" report). Right: STL robustness, emergency progress and priority compliance, ADMM events
and iterations, and an attack / link-down / violation strip. Demo script: `docs/DEMO_SCRIPT.md`.

### Reproduce everything

```bash
scripts/run_all.sh
```

≈ 17 min on a 12-core laptop (`--quick`: under a minute; Windows: `scripts\run_all.ps1`).
Details in `docs/REPRODUCIBILITY.md`; consolidated results in `outputs/week6/RESULTS.md`.

| ID | Experiment | Results |
|---|---|---|
| E1 | ADMM scaling and convergence | `outputs/week6/e1_admm_scaling/README.md` |
| E2 | Formation, merge success, throughput, utilisation | `outputs/week6/e2_formation/README.md` |
| E3 | Emergency priority compliance | `outputs/week6/e3_priority/README.md` |
| E4 | Resilience under attack, three architectures | `outputs/week6/e4_resilience/README.md` |
| E5 | STL robustness across architectures | `outputs/week6/e5_stl/README.md` |
| E6 | Graceful degradation (overseer link failure) | `outputs/week6/e6_degradation/README.md` |

### Tests

```bash
python -m pytest -q
```

### Known limitations

- The separation metric uses planar distance over all pairs, including agents on different
  altitude layers, so hierarchical runs show near-constant violations (fix pending).
- The E2 merge-success definition is under review (success rate ≈ 0 at every N).
- The E6 outage (90–120 s) changed no trajectory in these runs.
- One adversary, constant offset; 3–5 seeds per point.
- ADMM is conflict mitigation, not a safety guarantee.
