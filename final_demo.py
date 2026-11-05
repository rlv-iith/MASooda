"""Final Full-System Integration Demo: P1-P6 Multilayer Urban Swarm Governance.

Integrates all modules across the project:
  - P1 (Simulation Engine): 2.5D double-integrator dynamics, corridor geometry, comm-graph.
  - P2 (Distributed Optimization): Consensus ADMM conflict resolution with Week 5 profiling wrapper (ADMMRecorder).
  - P3 (Local Swarm Behavior): Multi-corridor Boids flocking (alignment, cohesion, separation, corridor keeping).
  - P4 (Centralized DTC Overseer): Strategic corridor allocation, priority layers (EMERGENCY, EVTOL, DELIVERY).
  - P5 (Resilience & Security): Malicious telemetry/Byzantine attack injection defended by W-MSR resilient filtering.
  - P6 (Formal Verification): Real-time Signal Temporal Logic (STL) robustness monitoring G(separation >= d_min).

Outputs generated in outputs/:
  - outputs/final_demo.gif      : 3D animated multi-layer swarm simulation with color-coded drone types
  - outputs/final_demo.png      : Comprehensive 4-panel analytical overview dashboard
  - outputs/final_demo_log.csv  : Tick-by-tick trajectory, ADMM profiling, and safety metrics log

Run:
  python final_demo.py --num_agents 45 --duration 40 --fps 10
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass, field
import os
from pathlib import Path
import sys
import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("MPLCONFIGDIR", "/tmp/masooda-matplotlib")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation, PillowWriter
from mpl_toolkits.mplot3d.art3d import Line3DCollection

from config.load_config import get_config
from conflict_resolution.profiling import ADMMRecorder, summarize
from simulation.scenario import make_initial_agents
from simulation.schema import AgentState, AgentType, STLSpec
import simulation.engine
import simulation.overseer
import local_behavior.boids
from verification.stl_monitor import stl_monitor
from verification.metrics import compute_run_metrics


# ==============================================================================
# CONFIGURATION
# ==============================================================================
@dataclass
class SwarmDemoConfig:
    n_agents: int = 40
    duration_s: float = 30.0
    dt: float = 0.1
    seed: int = 42
    scenario: str = "corridors"  # "corridors" or "converging"
    use_overseer: bool = True
    use_admm: bool = True
    enable_attack: bool = False
    enable_defense: bool = True
    fps: int = 10
    d_safe: float = 8.0
    v_max: float = 15.0
    layers: tuple[int, ...] = (0, 1, 2)


def make_converging_agents(n: int, seed: int, arena_radius: float = 60.0) -> list[AgentState]:
    """Create heterogeneous drone fleet arranged in a circular converging pattern."""
    rng = np.random.default_rng(seed)
    angles = np.linspace(0, 2.0 * np.pi, n, endpoint=False)
    types_pool = [AgentType.EMERGENCY, AgentType.EVTOL, AgentType.DELIVERY]
    priority_map = {AgentType.EMERGENCY: 0, AgentType.EVTOL: 1, AgentType.DELIVERY: 2}

    agents: list[AgentState] = []
    for i, theta in enumerate(angles):
        agent_type = types_pool[i % len(types_pool)]
        priority = priority_map[agent_type]
        z_layer = 2 if priority == 0 else (1 if priority == 1 else 0)

        pos_x = arena_radius * np.cos(theta)
        pos_y = arena_radius * np.sin(theta)
        pos = np.array([pos_x, pos_y, float(z_layer)], dtype=float)
        dest = np.array([-pos_x, -pos_y, float(z_layer)], dtype=float)

        dir_vec = (dest - pos)[:2]
        dist = float(np.linalg.norm(dir_vec))
        unit_vec = dir_vec / max(dist, 1e-6)
        vel = np.array([unit_vec[0] * 12.0, unit_vec[1] * 12.0, 0.0], dtype=float)

        agent = AgentState(
            id=i,
            type=agent_type,
            position=pos,
            velocity=vel,
            acceleration=np.zeros(3, dtype=float),
            destination=dest,
            priority=priority,
            corridor_assignment=i % 3,
            neighbor_set=[],
            altitude_layer=z_layer,
        )
        agents.append(agent)
    return agents


# ==============================================================================
# FULL SIMULATION RUNNER
# ==============================================================================
def run_demo(cfg: SwarmDemoConfig) -> tuple[simulation.engine.SimulationResult, list[dict], dict]:
    """Execute full simulation with P1-P6 modules and P2 Week 5 profiling wrapper."""
    simulation.overseer.reset_default_overseer()
    local_behavior.boids.reset_local_behavior_cache()

    base_cfg = get_config()

    if cfg.scenario == "converging":
        agents = make_converging_agents(cfg.n_agents, cfg.seed)
    else:
        agents = make_initial_agents(cfg.n_agents, cfg.seed)

    attack_cfg = {**base_cfg.get("attack", {}), "enabled": cfg.enable_attack}
    overseer_link_cfg = {"enabled": False}

    print(f"\n[MASooda Final Demo] Starting simulation:")
    print(f"  - Agents: {cfg.n_agents} | Scenario: {cfg.scenario} | Duration: {cfg.duration_s:.1f}s")
    print(f"  - ADMM: {cfg.use_admm} | Overseer: {cfg.use_overseer} | Attack: {cfg.enable_attack} | Defense: {cfg.enable_defense}")

    # P2 Week 5 Non-invasive ADMM Profiling Wrapper
    with ADMMRecorder() as rec:
        rec.current_tag = {"scenario": cfg.scenario, "N": cfg.n_agents}
        result = simulation.engine.run_simulation(
            agents=agents,
            duration_s=cfg.duration_s,
            use_overseer=cfg.use_overseer,
            use_admm=cfg.use_admm,
            attack_config=attack_cfg,
            defended=cfg.enable_defense,
            overseer_link_config=overseer_link_cfg,
        )

    admm_summary = summarize(rec.records)
    return result, rec.records, admm_summary


# ==============================================================================
# VISUALIZER & DASHBOARD GENERATOR
# ==============================================================================
class SwarmDashboardVisualizer:
    def __init__(self, cfg: SwarmDemoConfig, result: simulation.engine.SimulationResult, admm_records: list[dict]):
        self.cfg = cfg
        self.result = result
        self.admm_records = admm_records
        self.out_dir = ROOT / "outputs"
        self.out_dir.mkdir(parents=True, exist_ok=True)

        self.times = result.times
        self.positions = result.positions  # (T, N, 3)
        self.n_steps, self.n_agents, _ = self.positions.shape

        self.type_colors = {
            AgentType.EMERGENCY: "#d93a3a",  # Red
            AgentType.EVTOL: "#2a6fdb",      # Blue
            AgentType.DELIVERY: "#e08a1e",   # Orange
        }

        # Calculate minimum distance per tick
        self.min_separations = []
        d_safe = float(cfg.d_safe)
        for t in range(self.n_steps):
            xy = self.positions[t, :, :2]
            z = self.positions[t, :, 2]
            # Same layer pairwise distance
            same_dists = []
            for i in range(self.n_agents):
                for j in range(i + 1, self.n_agents):
                    if abs(z[i] - z[j]) < 0.5:
                        same_dists.append(float(np.linalg.norm(xy[i] - xy[j])))
            self.min_separations.append(min(same_dists) if same_dists else float("inf"))

    def render_3d_state(self, ax, frame: int) -> None:
        ax.cla()
        pos_f = self.positions[frame]

        if self.cfg.scenario == "converging":
            x_min, x_max = -70.0, 70.0
            y_min, y_max = -70.0, 70.0
        else:
            cur_x = float(np.mean(pos_f[:, 0]))
            x_min, x_max = max(0.0, cur_x - 120.0), cur_x + 120.0
            y_min, y_max = -30.0, 130.0

        # Draw layer planes
        layers = self.cfg.layers
        X, Y = np.meshgrid([x_min, x_max], [y_min, y_max])
        for l in layers:
            ax.plot_surface(X, Y, np.full_like(X, float(l)), color="steelblue", alpha=0.06, shade=False)

        # Plot agent trajectories
        trail_start = max(0, frame - 20)
        for i in range(self.n_agents):
            trail = self.positions[trail_start:frame + 1, i]
            color = "#2a6fdb" if i % 3 == 1 else ("#d93a3a" if i % 3 == 0 else "#e08a1e")
            if len(trail) > 1:
                ax.plot(trail[:, 0], trail[:, 1], trail[:, 2], color=color, alpha=0.5, lw=1.2)
            ax.scatter(pos_f[i, 0], pos_f[i, 1], pos_f[i, 2], color=color, s=40, edgecolor="black", depthshade=False)

        ax.set_xlim(x_min, x_max)
        ax.set_ylim(y_min, y_max)
        ax.set_zlim(-0.5, max(layers) + 0.5)
        ax.set_xlabel("X (m)", fontsize=8)
        ax.set_ylabel("Y (m)", fontsize=8)
        ax.set_zlabel("Layer Z", fontsize=8)
        ax.set_zticks(list(layers))
        azim = -60 + 0.3 * frame
        ax.view_init(elev=24, azim=azim)

    def save_dashboard(self) -> Path:
        """Create 4-panel analytical overview dashboard."""
        fig = plt.figure(figsize=(15, 7.5))

        # Panel 1: 3D Airspace Multi-layer perspective
        ax1 = fig.add_subplot(1, 2, 1, projection="3d")
        self.render_3d_state(ax1, self.n_steps - 1)
        ax1.set_title("2.5D Multilayer Swarm Governance (P1/P3/P4)", fontsize=11, fontweight="bold")

        # Panel 2: P6 STL Safety Separation Monitoring
        ax2 = fig.add_subplot(2, 2, 2)
        valid_seps = [m if np.isfinite(m) else np.nan for m in self.min_separations]
        ax2.plot(self.times, valid_seps, color="purple", lw=1.5, label="Min Pairwise Separation (same layer)")
        ax2.axhline(self.cfg.d_safe, color="red", ls="--", lw=1.5, label=f"Safety Target $d_{{safe}}={self.cfg.d_safe}$m")
        ax2.set_xlabel("Time (s)", fontsize=9)
        ax2.set_ylabel("Separation (m)", fontsize=9)
        ax2.set_title("P6 STL Safety Distance Monitoring Over Time", fontsize=10)
        ax2.legend(loc="upper right", fontsize=8)
        ax2.grid(True, alpha=0.3)

        # Panel 3: P2 Week 5 ADMM Solver Profile (Iterations & Solve Times)
        ax3 = fig.add_subplot(2, 2, 4)
        if self.admm_records:
            iters = [r["iterations"] for r in self.admm_records]
            solve_ms = [r["solve_time_s"] * 1000.0 for r in self.admm_records]
            calls = np.arange(1, len(iters) + 1)
            ax3.plot(calls, iters, color="tab:blue", marker=".", alpha=0.7, label="Iterations per Call")
            ax3.axhline(50, color="red", ls="--", alpha=0.7, label="Max Iterations (50)")
            ax3.set_xlabel("ADMM Solver Call Index", fontsize=9)
            ax3.set_ylabel("Iterations", fontsize=9)
            ax3.set_title("P2 Week 5 ADMM Convergence Iterations Profile", fontsize=10)
            ax3.legend(loc="upper right", fontsize=8)
            ax3.grid(True, alpha=0.3)
        else:
            # Fallback to layer occupancy distribution over time
            layer_0 = np.sum(np.abs(self.positions[:, :, 2] - 0.0) < 0.5, axis=1)
            layer_1 = np.sum(np.abs(self.positions[:, :, 2] - 1.0) < 0.5, axis=1)
            layer_2 = np.sum(np.abs(self.positions[:, :, 2] - 2.0) < 0.5, axis=1)
            ax3.plot(self.times, layer_0, label="Layer 0 (Delivery)", color="#e08a1e")
            ax3.plot(self.times, layer_1, label="Layer 1 (eVTOL)", color="#2a6fdb")
            ax3.plot(self.times, layer_2, label="Layer 2 (Emergency)", color="#d93a3a")
            ax3.set_xlabel("Time (s)", fontsize=9)
            ax3.set_ylabel("Drone Count", fontsize=9)
            ax3.set_title("P4 Airspace Layer Occupancy Over Time", fontsize=10)
            ax3.legend(loc="upper right", fontsize=8)
            ax3.grid(True, alpha=0.3)

        plt.tight_layout()
        out_png = self.out_dir / "final_demo.png"
        fig.savefig(out_png, dpi=150)
        plt.close(fig)
        return out_png

    def save_gif(self) -> Path:
        """Render 3D animated multi-layer simulation GIF."""
        fig = plt.figure(figsize=(7, 6))
        ax = fig.add_subplot(111, projection="3d")
        step_interval = max(1, int(round((1.0 / self.cfg.fps) / self.cfg.dt)))
        frames = list(range(0, self.n_steps, step_interval))

        def update(f: int):
            self.render_3d_state(ax, f)
            ax.set_title(f"Tick {f}/{self.n_steps} (t={self.times[f]:.1f}s) — Swarm Governance Demo", fontsize=10)

        anim = FuncAnimation(fig, update, frames=frames, interval=int(1000 / self.cfg.fps))
        out_gif = self.out_dir / "final_demo.gif"
        anim.save(out_gif, writer=PillowWriter(fps=self.cfg.fps), dpi=80)
        plt.close(fig)
        return out_gif

    def save_telemetry_csv(self) -> Path:
        """Save detailed tick-by-tick simulation metrics."""
        csv_path = self.out_dir / "final_demo_log.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["tick", "time_s", "min_separation_m"])
            writer.writeheader()
            for t in range(self.n_steps):
                writer.writerow({
                    "tick": t,
                    "time_s": float(self.times[t]),
                    "min_separation_m": float(self.min_separations[t]),
                })
        return csv_path


# ==============================================================================
# MAIN ENTRYPOINT
# ==============================================================================
def main() -> None:
    parser = argparse.ArgumentParser(description="MASooda Full-System P1-P6 Integration Demo")
    parser.add_argument("--num_agents", type=int, default=30, help="Number of drones")
    parser.add_argument("--duration", type=float, default=25.0, help="Simulation duration (s)")
    parser.add_argument("--scenario", choices=["corridors", "converging"], default="corridors",
                        help="Airspace scenario: 'corridors' (highway) or 'converging' (circle intersection)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--fps", type=int, default=10, help="Animation FPS")
    parser.add_argument("--no_overseer", action="store_true", help="Disable global overseer")
    parser.add_argument("--no_admm", action="store_true", help="Disable ADMM conflict resolution")
    parser.add_argument("--attack", action="store_true", help="Inject cyberattack")
    parser.add_argument("--no_defense", action="store_true", help="Disable resilient defense")
    args = parser.parse_args()

    cfg = SwarmDemoConfig(
        n_agents=args.num_agents,
        duration_s=args.duration,
        seed=args.seed,
        scenario=args.scenario,
        use_overseer=not args.no_overseer,
        use_admm=not args.no_admm,
        enable_attack=args.attack,
        enable_defense=not args.no_defense,
        fps=args.fps,
    )

    result, admm_records, admm_summary = run_demo(cfg)

    # Compute official run metrics
    metrics = compute_run_metrics(result)
    stl_spec = STLSpec(name="global_min_separation", d_min=cfg.d_safe, dt=cfg.dt)
    stl_res = stl_monitor(result.positions, stl_spec)

    print("\n" + "=" * 70)
    print("FULL-SYSTEM INTEGRATION RESULTS (P1-P6)")
    print("=" * 70)
    print(f"Total Agents Simulated     : {cfg.n_agents}")
    print(f"Simulation Duration        : {cfg.duration_s:.1f} s ({len(result.times)} steps)")
    print(f"P2 ADMM Solver Calls       : {admm_summary['count']}")
    if admm_summary['count'] > 0:
        print(f"ADMM Convergence Rate      : {admm_summary['fraction_converged']*100.0:.1f}%")
        print(f"ADMM Mean Iterations       : {admm_summary['mean_iterations']:.1f}")
        print(f"ADMM Mean Solve Time       : {admm_summary['mean_solve_ms']:.2f} ms")
    print(f"P4 Overseer Directives     : {result.overseer_calls} calls, {result.stats.get('layer_changes', 0)} layer changes")
    print(f"P6 Minimum Separation      : {metrics['min_separation_m']:.2f} m (Safety threshold: {cfg.d_safe} m)")
    print(f"P6 STL Robustness Margin   : {stl_res.value:.2f} m (Violation: {stl_res.violation})")
    print(f"Throughput to Exit Zone    : {metrics['throughput_per_s']:.2f} agents/s")
    print("=" * 70 + "\n")

    print("Generating visualizations (GIF, PNG dashboard, CSV)...")
    viz = SwarmDashboardVisualizer(cfg, result, admm_records)
    png_path = viz.save_dashboard()
    csv_path = viz.save_telemetry_csv()
    gif_path = viz.save_gif()

    print(f"\nSaved Demo Outputs in outputs/:")
    print(f"  - 3D Animated GIF : {gif_path}")
    print(f"  - Analytics PNG   : {png_path}")
    print(f"  - Telemetry CSV   : {csv_path}")


if __name__ == "__main__":
    main()
