"""P6 Week 3 Live Sim: Stream full simulation trajectories through the live STL monitor."""

from __future__ import annotations

from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from simulation.engine import run_simulation
from simulation.scenario import make_initial_agents
from simulation.schema import AgentState, AgentType
from verification.live_monitor import LiveSTLMonitor


def main() -> None:
    print("Generating 30 initial agents...")
    agents = make_initial_agents(30)

    print("Running simulation for 60.0 seconds...")
    result = run_simulation(agents, duration_s=60.0)

    # Replay trajectory tick by tick into LiveSTLMonitor.
    # Note: Once P1's loggers= parameter is on main, the same monitor can be passed straight
    # into run_simulation instead.
    monitor = LiveSTLMonitor()
    n_ticks = len(result.times)
    n_agents = len(result.agent_ids)

    print(f"Streaming {n_ticks} ticks through LiveSTLMonitor...")
    for k in range(n_ticks):
        t_k = float(result.times[k])
        those_agents = [
            AgentState(
                id=result.agent_ids[i],
                type=AgentType.DELIVERY,
                position=result.positions[k, i],
            )
            for i in range(n_agents)
        ]
        monitor.log_state(t_k, those_agents)

    # Metrics
    num_ticks = len(monitor.history)
    viol_count = monitor.violation_count()
    min_rho = monitor.min_robustness()
    worst_entry = min(monitor.history, key=lambda r: r["rho"])

    print("\n--- Live STL Monitoring Results ---")
    print(f"number of ticks: {num_ticks}")
    print(f"violation count: {viol_count}")
    print(f"min robustness: {min_rho:+.3f} m")
    print(
        f"worst tick: time = {worst_entry['t']:.2f} s, "
        f"worst pair = {worst_entry['worst_pair']}, "
        f"rho = {worst_entry['rho']:+.3f} m"
    )

    out_dir = Path("outputs")
    out_dir.mkdir(parents=True, exist_ok=True)

    # Save CSV
    csv_path = out_dir / "p6_week3_live_sim.csv"
    monitor.to_csv(csv_path)
    print(f"\nSaved live monitoring CSV to {csv_path}")

    # Save plot of rho(t) over time
    t_axis = np.array([r["t"] for r in monitor.history], dtype=float)
    rho_axis = np.array([r["rho"] for r in monitor.history], dtype=float)

    fig, ax = plt.subplots(figsize=(10, 4.5), dpi=150)
    fig.patch.set_facecolor("#12161F")
    ax.set_facecolor("#1A202C")

    ax.plot(t_axis, rho_axis, color="#2A9D8F", linewidth=1.5, label="Instantaneous rho(t)")
    ax.axhline(0.0, color="#E63946", linestyle="--", linewidth=1.2, label="Safety Threshold (0 m)")

    ax.set_title("Live STL Monitor: Full 30-Agent Simulation Trajectory", color="#F7FAFC", fontsize=11, fontweight="bold", pad=12)
    ax.set_xlabel("Simulation Time (seconds)", color="#E2E8F0", fontsize=9.5)
    ax.set_ylabel("Robustness rho(t) (meters)", color="#E2E8F0", fontsize=9.5)
    ax.tick_params(colors="#A0AEC0", labelsize=8.5)
    for spine in ax.spines.values():
        spine.set_color("#4A5568")
    ax.grid(True, linestyle="--", alpha=0.2, color="#A0AEC0")
    ax.legend(facecolor="#1A202C", edgecolor="#4A5568", labelcolor="#E2E8F0", fontsize=8.5, loc="upper right")
    plt.tight_layout()

    png_path = out_dir / "p6_week3_live_sim.png"
    fig.savefig(png_path, facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close(fig)
    print(f"Saved plot to {png_path}")


if __name__ == "__main__":
    main()

