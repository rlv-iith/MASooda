# MASooda — STL Specification (P6, Week 1 → finalized Week 2)

## 1. Core safety specification (live-monitored)

    φ_safe  =  G ( d_ij(t) ≥ d_min )      for all agent pairs i ≠ j

* `d_ij(t) = ‖p_i(t) − p_j(t)‖₂` (global Cartesian, metres)
* `d_min = 8 m` (read from `configs/base_config.yaml`, never hard-coded)
* Evaluated every tick (STL monitoring period 0.1 s) over a sliding window.

## 2. Quantitative (robustness) semantics

Instantaneous margin:

    ρ(t) = min_{i≠j} ( ‖p_i(t) − p_j(t)‖ − d_min )

Over a window [t₀, t₁] the `G` operator takes the worst case in time:

    ρ(φ_safe, window) = min_{t ∈ window} ρ(t)

| Value | Meaning |
|---|---|
| ρ > 0 | satisfied; ρ is the spare distance (m) before violation |
| ρ = 0 | exactly on the boundary (**not** a violation) |
| ρ < 0 | violated; the closest pair is |ρ| m too close |

`STLRobustness.violation = (ρ < 0)`. Metrics derived from this (Week 5): *safety-violation count* = ticks with ρ < 0; *recovery time* = time until ρ > 0 and stays > 0 for ≥ 1 s.

## 3. Interface

    stl_monitor(trajectory_window, spec) -> STLRobustness

* `trajectory_window`: array `(T, N, D)` (T samples, N agents, D = 2 or 3).
* Synchronous, read-only, no side effects.
* Extra (additive) fields on `STLRobustness`: `status`, `worst_step`, `worst_pair`.

### Failure behaviour

| Situation | Returned | Violation? |
|---|---|---|
| fewer than `min_window_steps` samples (start-up) | value 0.0, `INSUFFICIENT_HISTORY` | No |
| fewer than 2 agents | value 0.0, `NOT_ENOUGH_AGENTS` | No |
| NaN / inf / malformed input | value 0.0, `INVALID_DATA` | No (data fault, not a safety verdict; log it via the exception/fallback counter) |

## 4. Optional liveness specification (documented only; not core)

    φ_live = F ( agent i reaches destination_i )      ρ = min_i max_t ( r − ‖p_i(t) − dest_i‖ )

Implemented as `liveness_robustness()` but not wired into the live loop (optional extension).

## 5. Assumptions
* Positions fed to the monitor are the **true** simulator positions (ground truth), not the falsified broadcasts — safety is judged on reality, otherwise an attacker could hide a collision.
* Fixed agent set inside a window (agents are not added/removed mid-window).
