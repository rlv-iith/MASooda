"""Week 2 ADMM solver iteration sweep (P2).

Evaluates the performance, convergence rate, primal residuals, and runtime
of consensus ADMM across different maximum iteration limits on 50 synthetic conflict scenarios.
"""

from __future__ import annotations

import csv
from pathlib import Path
import time
import matplotlib.pyplot as plt
import numpy as np

from config.load_config import get_config
from conflict_resolution.solver import ADMMSolver

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "outputs"


def generate_test_cases(
    num_cases: int = 50,
    seed: int = 42,
    dt: float = 0.1,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Generate reproducible conflict scenarios with 2 to 5 agents heading toward group center."""
    rng = np.random.default_rng(seed)
    cases: list[tuple[np.ndarray, np.ndarray]] = []

    for _ in range(num_cases):
        n = int(rng.integers(2, 6))
        d = float(rng.uniform(10.0, 14.0))
        theta0 = float(rng.uniform(0.0, 2.0 * np.pi))
        if n == 2:
            R = d / 2.0
        else:
            R = d / (2.0 * np.sin(np.pi / n))

        angles = [theta0 + 2.0 * np.pi * i / n for i in range(n)]
        positions = np.array([[R * np.cos(a), R * np.sin(a)] for a in angles], dtype=float)
        center = np.mean(positions, axis=0)

        speeds = rng.uniform(5.0, 15.0, size=n)
        velocities = np.zeros_like(positions)
        for i in range(n):
            diff = center - positions[i]
            dist = np.linalg.norm(diff)
            velocities[i] = speeds[i] * diff / dist if dist > 0.0 else np.zeros(2)

        targets = positions + velocities * dt
        cases.append((positions, targets))

    return cases


def run_sweep() -> None:
    cfg = get_config()
    seed = int(cfg["simulation"]["random_seed"])
    dt = float(cfg["simulation"]["timestep_seconds"])
    sweep_values = [int(v) for v in cfg["admm"]["iteration_sweep"]]

    cases = generate_test_cases(num_cases=50, seed=seed, dt=dt)

    results: list[dict[str, float]] = []

    for max_it in sweep_values:
        solver = ADMMSolver.from_config(max_iters=max_it)
        conv_flags: list[bool] = []
        actual_iters: list[int] = []
        primal_residuals: list[float] = []
        solve_times_ms: list[float] = []

        for positions, targets in cases:
            t0 = time.perf_counter()
            res = solver.solve(positions, targets)
            solve_time = (time.perf_counter() - t0) * 1000.0

            conv_flags.append(res.converged)
            actual_iters.append(res.iterations)
            primal_residuals.append(res.primal_residual)
            solve_times_ms.append(solve_time)

        pct_conv = 100.0 * float(np.mean(conv_flags))
        mean_it = float(np.mean(actual_iters))
        mean_pri = float(np.mean(primal_residuals))
        mean_time = float(np.mean(solve_times_ms))

        results.append({
            "max_iterations": max_it,
            "percent_converged": pct_conv,
            "mean_iterations": mean_it,
            "mean_primal_residual": mean_pri,
            "mean_solve_time_ms": mean_time,
        })

    # Save CSV
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUTPUT_DIR / "p2_week2_iteration_sweep.csv"
    with open(csv_path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "max_iterations",
            "percent_converged",
            "mean_iterations",
            "mean_primal_residual",
            "mean_solve_time_ms",
        ])
        writer.writeheader()
        writer.writerows(results)

    # Print Table
    print("\n" + "=" * 90)
    print("MASooda P2 Week 2: ADMM Iteration Sweep (50 Conflict Test Cases)")
    print("=" * 90)
    header = (
        f"{'Max Iters':<12} | {'Percent Converged (%)':<23} | "
        f"{'Mean Iterations':<17} | {'Mean Primal Res':<17} | {'Solve Time (ms)':<15}"
    )
    print(header)
    print("-" * len(header))
    for r in results:
        print(
            f"{int(r['max_iterations']):<12} | "
            f"{r['percent_converged']:<23.1f} | "
            f"{r['mean_iterations']:<17.2f} | "
            f"{r['mean_primal_residual']:<17.6e} | "
            f"{r['mean_solve_time_ms']:<15.3f}"
        )
    print("=" * 90 + "\n")

    # Save Plot
    fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(11, 8))

    max_iters = [r["max_iterations"] for r in results]
    pcts = [r["percent_converged"] for r in results]
    mean_its = [r["mean_iterations"] for r in results]
    mean_pris = [r["mean_primal_residual"] for r in results]
    mean_times = [r["mean_solve_time_ms"] for r in results]

    # Panel 1: Convergence Rate
    ax1.plot(max_iters, pcts, "o-", color="#2a6fdb", linewidth=2)
    ax1.set_xlabel("Max Iterations")
    ax1.set_ylabel("Convergence Rate (%)")
    ax1.set_title("Convergence Rate vs Iteration Limit")
    ax1.grid(True, linestyle="--", alpha=0.6)
    ax1.set_ylim(-5, 105)

    # Panel 2: Mean Iterations
    ax2.plot(max_iters, mean_its, "s-", color="#e08a1e", linewidth=2)
    ax2.set_xlabel("Max Iterations")
    ax2.set_ylabel("Mean Iterations Executed")
    ax2.set_title("Actual Iterations vs Iteration Limit")
    ax2.grid(True, linestyle="--", alpha=0.6)

    # Panel 3: Primal Residual
    ax3.plot(max_iters, mean_pris, "^-", color="#d93a3a", linewidth=2)
    ax3.set_xlabel("Max Iterations")
    ax3.set_ylabel("Mean Primal Residual")
    ax3.set_title("Mean Primal Residual vs Iteration Limit")
    ax3.grid(True, linestyle="--", alpha=0.6)

    # Panel 4: Solve Time
    ax4.plot(max_iters, mean_times, "d-", color="#2e9e5b", linewidth=2)
    ax4.set_xlabel("Max Iterations")
    ax4.set_ylabel("Mean Solve Time (ms)")
    ax4.set_title("Solve Time (ms) vs Iteration Limit")
    ax4.grid(True, linestyle="--", alpha=0.6)

    plt.tight_layout()
    png_path = OUTPUT_DIR / "p2_week2_iteration_sweep.png"
    plt.savefig(png_path, dpi=300)
    plt.close()
    print(f"Saved results to:\n- {csv_path}\n- {png_path}\n")


if __name__ == "__main__":
    run_sweep()
