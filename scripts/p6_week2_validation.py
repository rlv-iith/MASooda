"""P6 Week 2 Validation: STL monitoring on toy and live simulation trajectories."""

from __future__ import annotations

import time
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from config.load_config import get_config
from simulation.engine import run_simulation
from simulation.scenario import make_initial_agents
from verification.from_engine import window_from_result
from verification.stl_monitor import (
    SlidingSTLMonitor,
    load_spec_from_config,
    load_trajectory_csv,
    robustness_series,
    stl_monitor,
)


def main() -> None:
    cfg = get_config()
    spec = load_spec_from_config(cfg)
    output_lines: list[str] = [
        "# P6 Week 2 STL Validation Results",
        f"Specification: d_min = {spec.d_min} m, dt = {spec.dt} s, min_window_steps = {spec.min_window_steps}",
        "",
    ]

    print("=== P6 Week 2 STL Validation ===")
    print(f"Spec: d_min = {spec.d_min} m, dt = {spec.dt} s, min_window_steps = {spec.min_window_steps}")

    # 1. Toy check
    print("\n--- Toy Trajectory Checks ---")
    output_lines.append("## Toy Trajectory Checks")
    for name in ["safe", "unsafe"]:
        csv_path = Path("data") / "stl" / f"{name}_trajectory.csv"
        traj = load_trajectory_csv(csv_path)
        res = stl_monitor(traj, spec)
        line = f"toy `{name}`: rho_min = {res.value:+.3f} m, violation = {res.violation}"
        print(line)
        output_lines.append(f"- {line}")

    # 2. Engine check
    print("\n--- Engine Trajectory Check (60 agents, 60.0 s) ---")
    output_lines.append("\n## Engine Trajectory Check")
    agents = make_initial_agents(60)
    result = run_simulation(agents, duration_s=60.0)
    window = window_from_result(result)
    rho = robustness_series(window, spec.d_min)

    rho_min = float(np.min(rho))
    violating_ticks = int(np.sum(rho < 0))
    no_nan = bool(np.all(np.isfinite(window)))

    print(f"rho min: {rho_min:+.3f} m")
    print(f"number of ticks with rho < 0: {violating_ticks} / {len(rho)}")
    print(f"no NaN: {no_nan}")

    output_lines.append(f"- rho min: {rho_min:+.3f} m")
    output_lines.append(f"- number of ticks with rho < 0: {violating_ticks} / {len(rho)}")
    output_lines.append(f"- no NaN: {no_nan}")

    # 3. Live check
    print("\n--- Live Sliding Window Check ---")
    output_lines.append("\n## Live Sliding Window Check")
    window_steps = int(cfg.get("stl", {}).get("window_steps", 10))
    sliding_monitor = SlidingSTLMonitor(spec, window_steps=window_steps)

    t0 = time.perf_counter()
    for tick_snapshot in window:
        sliding_monitor.update(tick_snapshot)
    elapsed_total = time.perf_counter() - t0
    per_tick_ms = (elapsed_total / len(window)) * 1000.0

    live_line = f"mean time per tick: {per_tick_ms:.3f} ms"
    print(live_line)
    output_lines.append(f"- {live_line}")

    # 4. Save plot and validation report
    out_dir = Path("outputs")
    out_dir.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(10, 4.5), dpi=150)
    fig.patch.set_facecolor("#12161F")
    ax.set_facecolor("#1A202C")

    t_axis = np.arange(len(rho)) * spec.dt
    ax.plot(t_axis, rho, color="#2A9D8F", linewidth=1.5, label="rho(t)")
    ax.axhline(0, color="#E63946", linestyle="--", linewidth=1.2, label="Safety Threshold (0 m)")

    ax.set_title("MASooda STL Minimum Separation Robustness (60 agents, 60s)", color="#F7FAFC", fontsize=11, fontweight="bold")
    ax.set_xlabel("Simulation Time (s)", color="#E2E8F0", fontsize=9.5)
    ax.set_ylabel("Robustness rho(t) (m)", color="#E2E8F0", fontsize=9.5)
    ax.tick_params(colors="#A0AEC0", labelsize=8.5)
    for spine in ax.spines.values():
        spine.set_color("#4A5568")
    ax.grid(True, linestyle="--", alpha=0.2, color="#A0AEC0")
    ax.legend(facecolor="#1A202C", edgecolor="#4A5568", labelcolor="#E2E8F0", fontsize=8.5)
    plt.tight_layout()

    plot_path = out_dir / "p6_week2_robustness.png"
    fig.savefig(plot_path, facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close(fig)
    print(f"\nPlot saved to {plot_path}")

    md_path = out_dir / "p6_week2_validation.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(output_lines) + "\n")
    print(f"Validation report saved to {md_path}")


if __name__ == "__main__":
    main()

