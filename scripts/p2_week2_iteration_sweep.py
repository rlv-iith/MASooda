"""Iteration sweep script for ADMM conflict resolution (P2 Week 2).

Generates 50 test cases, solves each across admm.iteration_sweep limits,
and outputs performance metrics (CSV, plot, console table).
"""
from __future__ import annotations

import csv
from pathlib import Path
import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from config.load_config import get_config
from conflict_resolution.solver import ADMMSolver


def generate_test_cases(n_cases: int, seed: int):
    rng = np.random.default_rng(seed)
    cases = []
    for _ in range(n_cases):
        n = rng.integers(2, 6)  # 2 to 5 agents inclusive
        d = rng.uniform(10.0, 14.0)
        radius = d / (2.0 * np.sin(np.pi / n))

        angles = np.linspace(0, 2.0 * np.pi, n, endpoint=False)
        pos_x = radius * np.cos(angles)
        pos_y = radius * np.sin(angles)
        positions = np.column_stack((pos_x, pos_y))

        speeds = rng.uniform(5.0, 15.0, size=n)
        # Point toward circle center (0, 0): unit vector is -positions / radius
        unit_to_center = -np.column_stack((np.cos(angles), np.sin(angles)))
        velocities = unit_to_center * speeds[:, None]

        cases.append((positions, velocities))
    return cases


def run_sweep():
    cfg = get_config()
    seed = int(cfg["simulation"]["random_seed"])
    dt = float(cfg["simulation"]["timestep_seconds"])
    sweep_values = [int(v) for v in cfg["admm"]["iteration_sweep"]]

    cases = generate_test_cases(50, seed)

    results = []
    for it_limit in sweep_values:
        solver = ADMMSolver.from_config()
        solver.max_iters = it_limit

        converged_list = []
        iterations_list = []
        residuals_list = []
        times_ms = []

        for positions, velocities in cases:
            targets = positions + velocities * dt
            t0 = time.perf_counter()
            res = solver.solve(positions, targets)
            solve_time = (time.perf_counter() - t0) * 1000.0

            converged_list.append(res.converged)
            iterations_list.append(res.iterations)
            residuals_list.append(res.primal_residual)
            times_ms.append(solve_time)

        pct_converged = 100.0 * float(np.mean(converged_list))
        mean_iters = float(np.mean(iterations_list))
        mean_residual = float(np.mean(residuals_list))
        mean_time = float(np.mean(times_ms))

        results.append({
            "iteration_limit": it_limit,
            "percent_converged": pct_converged,
            "mean_iterations": mean_iters,
            "mean_primal_residual": mean_residual,
            "mean_solve_time_ms": mean_time,
        })

    # Save to outputs/
    output_dir = Path("outputs")
    output_dir.mkdir(parents=True, exist_ok=True)

    csv_path = output_dir / "p2_week2_iteration_sweep.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "iteration_limit",
            "percent_converged",
            "mean_iterations",
            "mean_primal_residual",
            "mean_solve_time_ms",
        ])
        writer.writeheader()
        writer.writerows(results)

    # Plot
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4))
    it_limits = [r["iteration_limit"] for r in results]
    pct_conv = [r["percent_converged"] for r in results]
    mean_res = [r["mean_primal_residual"] for r in results]

    ax1.plot(it_limits, pct_conv, marker="o", color="tab:blue")
    ax1.set_xlabel("Iteration Limit")
    ax1.set_ylabel("Convergence (%)")
    ax1.set_title("Convergence Rate vs Iteration Limit")
    ax1.grid(True)

    ax2.plot(it_limits, mean_res, marker="s", color="tab:orange")
    ax2.set_xlabel("Iteration Limit")
    ax2.set_ylabel("Mean Primal Residual")
    ax2.set_title("Mean Primal Residual vs Iteration Limit")
    ax2.grid(True)

    plt.tight_layout()
    png_path = output_dir / "p2_week2_iteration_sweep.png"
    plt.savefig(png_path)
    plt.close()

    # Print table
    header = f"{'Limit':>6} | {'Converged (%)':>14} | {'Mean Iters':>10} | {'Mean Primal Res':>16} | {'Mean Time (ms)':>15}"
    print(header)
    print("-" * len(header))
    for r in results:
        print(f"{r['iteration_limit']:>6} | {r['percent_converged']:>14.1f} | {r['mean_iterations']:>10.2f} | {r['mean_primal_residual']:>16.6f} | {r['mean_solve_time_ms']:>15.2f}")


if __name__ == "__main__":
    run_sweep()
