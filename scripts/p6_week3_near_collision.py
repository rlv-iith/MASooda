"""P6 Week 3 Near-Collision Validation: evaluate safe and unsafe crossing encounters."""

from __future__ import annotations

import csv
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from verification.near_collision import run_near_collision


def main() -> None:
    print("Running near-collision scenarios...")
    duration_s = 10.0

    # 1. Run safe encounter (closest gap = 20 m)
    print("Simulating safe case (lateral gap: 20 m)...")
    mon_safe = run_near_collision(closest_gap_m=20.0, duration_s=duration_s)
    print(f"Safe case: min rho = {mon_safe.min_robustness():+.2f} m, violations = {mon_safe.violation_count()}")

    # 2. Run unsafe encounter (closest gap = 3 m)
    print("Simulating unsafe case (lateral gap: 3 m)...")
    mon_unsafe = run_near_collision(closest_gap_m=3.0, duration_s=duration_s)
    print(f"Unsafe case: min rho = {mon_unsafe.min_robustness():+.2f} m, violations = {mon_unsafe.violation_count()}")

    out_dir = Path("outputs")
    out_dir.mkdir(parents=True, exist_ok=True)

    # 3. Export CSV
    csv_path = out_dir / "p6_week3_near_collision.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["t", "rho_safe", "rho_unsafe", "violation_safe", "violation_unsafe"])
        for r_s, r_u in zip(mon_safe.history, mon_unsafe.history):
            writer.writerow([
                r_s["t"],
                r_s["rho"],
                r_u["rho"],
                r_s["violation"],
                r_u["violation"],
            ])
    print(f"Saved CSV data to {csv_path}")

    # 4. Create and save comparison plot
    t_axis = np.array([r["t"] for r in mon_safe.history], dtype=float)
    rho_safe = np.array([r["rho"] for r in mon_safe.history], dtype=float)
    rho_unsafe = np.array([r["rho"] for r in mon_unsafe.history], dtype=float)

    fig, ax = plt.subplots(figsize=(10, 5), dpi=150)
    fig.patch.set_facecolor("#12161F")
    ax.set_facecolor("#1A202C")

    ax.plot(t_axis, rho_safe, color="#2A9D8F", linewidth=2.0, label="Safe Encounter (gap = 20 m)")
    ax.plot(t_axis, rho_unsafe, color="#F4A261", linewidth=2.0, label="Near-Collision (gap = 3 m)")
    ax.axhline(0.0, color="#E63946", linestyle="--", linewidth=1.2, label="Safety Threshold (d_min = 8 m)")

    # Shade the violation region where rho < 0
    ax.fill_between(
        t_axis,
        rho_unsafe,
        0.0,
        where=(rho_unsafe < 0.0),
        color="#E63946",
        alpha=0.35,
        label="Violation Region (rho < 0)",
        interpolate=True,
    )

    ax.set_title("P6 STL Minimum Separation Robustness: Controlled Near-Collision", color="#F7FAFC", fontsize=11.5, fontweight="bold", pad=12)
    ax.set_xlabel("Time (seconds)", color="#E2E8F0", fontsize=9.5)
    ax.set_ylabel("Instantaneous Robustness rho(t) (meters)", color="#E2E8F0", fontsize=9.5)
    ax.tick_params(colors="#A0AEC0", labelsize=8.5)
    for spine in ax.spines.values():
        spine.set_color("#4A5568")
    ax.grid(True, linestyle="--", alpha=0.2, color="#A0AEC0")
    ax.legend(facecolor="#1A202C", edgecolor="#4A5568", labelcolor="#E2E8F0", fontsize=8.5, loc="upper right")
    plt.tight_layout()

    png_path = out_dir / "p6_week3_near_collision.png"
    fig.savefig(png_path, facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close(fig)
    print(f"Saved plot to {png_path}")


if __name__ == "__main__":
    main()

