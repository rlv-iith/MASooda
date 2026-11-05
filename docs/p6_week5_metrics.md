# P6 Week 5: Standardized Metrics and Multi-Architecture Comparison

## Overview

This document specifies the unified experiment evaluation framework for the MASooda air traffic simulation across all three coordination architectures (Sections 13.6, 13.7, 13.9, Experiment E5):
- **Hierarchical**: Global priority-aware overseer + local Boids + ADMM conflict resolution + resilient defense.
- **Centralized**: Purely centralized controller directly dictating corridor assignments and 2.5D velocities.
- **Decentralized (Undefended)**: Local Boids + ADMM conflict resolution without resilient defense filtering.

---

## 1. Standardized CSV Output Schema (`STANDARD_COLUMNS`)

Every simulation run produces a row matching the following 22 standardized columns:

| Column | Type | Description |
| :--- | :--- | :--- |
| `architecture` | `string` | Coordination architecture (`hierarchical`, `centralized`, `decentralized_undefended`). |
| `scenario` | `string` | Evaluation scenario identifier (`mvp`, `nominal`, `e4_e5`, or `custom`). |
| `seed` | `int` | Random seed controlling initial fleet placement and attack injection. |
| `num_agents` | `int` | Total number of agents in the simulation fleet. |
| `duration_s` | `float` | Duration of the forward simulation in seconds. |
| `attack_enabled` | `bool` | Whether GPS/state falsification attack injection is enabled. |
| `link_failure` | `bool` | Whether overseer link communication blackout window is simulated. |
| `initial_conditions_hash` | `string` | SHA-256 fingerprint verifying identical initial agent fleet states across architectures. |
| `throughput_per_s` | `float` | Rate of successful corridor arrivals per second ($N_{\text{arrivals}} / \Delta t$). |
| `arrivals` | `int` | Count of agents reaching the exit zone ($x \ge 1400\,\text{m}$). |
| `safety_violation_ticks` | `int` | Number of timesteps where minimum pairwise distance dropped below $d_{\text{min}} = 8\,\text{m}$. |
| `violation_episodes` | `int` | Total number of distinct safety violation episodes detected. |
| `mean_recovery_time_s` | `float` | Average duration (seconds) required to recover and sustain safe separation for $\ge 1.0\,\text{s}$. |
| `max_recovery_time_s` | `float` | Maximum duration (seconds) of any single recovered violation episode. |
| `min_robustness_m` | `float` | Minimum STL spatial robustness score $\rho(t) = \min_{i<j} \|p_i - p_j\| - d_{\text{min}}$ in meters. |
| `min_separation_m` | `float` | Absolute minimum distance observed between any two agents in meters ($d_{\text{min}} + \rho_{\min}$). |
| `admm_events` | `int` | Number of ADMM pairwise conflict resolution negotiation events executed. |
| `admm_nonconverged` | `int` | Count of ADMM optimization runs failing to achieve convergence within limits. |
| `reports_dropped` | `int` | Falsified neighbor state reports detected and neutralized by defense filters. |
| `overseer_calls` | `int` | Total number of periodic global overseer corridor assignment updates requested. |
| `overseer_failures` | `int` | Total number of failed or unreachable overseer update attempts (e.g., during link failure). |
| `wall_time_s` | `float` | Real execution wall-clock time of the forward simulation in seconds. |

---

## 2. Verification of Identical Initial Conditions

Fair cross-architecture comparison requires that all architectures begin from bitwise-identical initial airspace states.

- **Hash Formulation**: `initial_conditions_hash(agents)` serializes agents sorted by ID into canonical JSON containing `(id, type, priority, rounded position [6 decimals], rounded destination [6 decimals], altitude_layer, corridor_assignment)` and computes its SHA-256 digest.
- **Automated Validation**: `check_identical_conditions(rows)` groups results by `(seed, num_agents)` and asserts that all architectures share identical hash fingerprints.
- The verification status is logged and saved to `outputs/week5/identical_conditions.txt`.

---

## 3. How to Run Each Architecture via CLI

All architectures can be executed directly using the `--architecture` flag in `main.py`:

```bash
# 1. Hierarchical Architecture (Default baseline)
python main.py --scenario mvp --architecture hierarchical

# 2. Centralized Architecture
python main.py --scenario mvp --architecture centralized

# 3. Decentralized Undefended Architecture
python main.py --scenario mvp --architecture decentralized_undefended
```

When `--architecture` is omitted, `main.py` defaults to `hierarchical`, preserving exact backwards compatibility. Each run writes run metrics and a standardized row to `<out>/run_row.csv`.

---

## 4. Multi-Architecture Comparison Tool

To execute the automated comparison benchmark across all merged architectures:

```bash
# Fast validation run (30 agents, 60 seconds, seed 42)
python scripts/p6_week5_compare.py --quick

# Full experimental benchmark (60 agents, full duration, seeds 42, 43, 44)
python scripts/p6_week5_compare.py
```

Generated outputs in `outputs/week5/`:
- `comparison.csv`: All standardized metric rows.
- `identical_conditions.txt`: Pass/Fail audit log verifying initial conditions.
- `stl_robustness_by_architecture.png`: Temporal STL robustness comparison curves.
- `summary_bars.png`: Safety violation ticks, recovery times, and throughput grouped by architecture.

