"""Final Full-System Integration Demo: P1-P6 Multilayer Urban Swarm Governance.

Mission & Architecture Objectives:
  Each drone is an autonomous aerial vehicle with a designated urban mission:
    - EMERGENCY (Red, Priority 0): Urgent medical/organ transport to hospital hubs (top priority layer).
    - EVTOL (Blue, Priority 1): Scheduled passenger air-taxi transit between vertiports (mid layers).
    - DELIVERY (Orange, Priority 2): Commercial cargo/package delivery to logistics drop zones (lower layers).

Airspace Hierarchy:
  - 2.5D Multi-Layer Airspace: Discrete vertical layers (e.g., 5 to 7 layers) with continuous (x, y) motion.
  - P4 Global Overseer: Coordinates dynamic corridor assignment and strategic altitude layer management.
  - P3 Local Behavior: Reynolds Boids navigation toward designated mission targets.
  - P2 Consensus ADMM: Resolves conflicting flight paths in real-time when trajectories intersect.
  - P2 Week 5 Profiling (ADMMRecorder): Measures iterations, solve times, and convergence metrics.
  - P5 Resilience: Detects and mitigates Byzantine cyberattacks using W-MSR consensus filtering.
  - P6 Formal Verification: Signal Temporal Logic (STL) continuously verifies the G(separation >= d_safe) safety contract.

Data Persistence:
  - SQLite Database : outputs/final_demo.db (simulation_runs, tick_records, admm_records)
  - Telemetry CSV   : outputs/final_demo_log.csv
  - ADMM Calls CSV  : outputs/final_demo_admm.csv
  - Animated 3D GIF : outputs/final_demo.gif
  - Analytics PNG   : outputs/final_demo.png
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
import sqlite3
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
    n_agents: int = 60
    duration_s: float = 30.0
    dt: float = 0.1
    seed: int = 42
    scenario: str = "converging"  # "converging" (intersecting mission hub) or "corridors"
    num_layers: int = 5           # Discrete altitude layers (e.g. 5 or 7)
    use_overseer: bool = True
    use_admm: bool = True
    enable_attack: bool = False
    enable_defense: bool = True
    fps: int = 10
    d_safe: float = 8.0
    v_max: float = 15.0

    @property
    def layers(self) -> list[int]:
        half = self.num_layers // 2
        return list(range(-half, half + 1)) if self.num_layers % 2 == 1 else list(range(self.num_layers))


# ==============================================================================
# MISSION OBJECTIVES & AGENT INITIALIZATION
# ==============================================================================
def create_mission_agents(cfg: SwarmDemoConfig) -> list[AgentState]:
    """Assign explicit urban mission destinations and initial positions to drones."""
    rng = np.random.default_rng(cfg.seed)
    n = cfg.n_agents
    layers_list = cfg.layers
    types_pool = [AgentType.EMERGENCY, AgentType.EVTOL, AgentType.DELIVERY]

    agents: list[AgentState] = []

    if cfg.scenario == "converging":
        # Multi-layer intersecting flight corridors converging through a central interchange
        angles = np.linspace(0, 2.0 * np.pi, n, endpoint=False)
        radius = 80.0

        for i, theta in enumerate(angles):
            # 1. Vehicle category and priority
            agent_type = types_pool[i % len(types_pool)]
            if agent_type == AgentType.EMERGENCY:
                priority = 0
                z_layer = layers_list[-1]  # Top layer for Emergency
            elif agent_type == AgentType.EVTOL:
                priority = 1
                z_layer = layers_list[len(layers_list) // 2]  # Mid layer for Air-Taxis
            else:
                priority = 2
                # Distribute delivery drones across lower layers to create realistic density
                low_layers = layers_list[:max(1, len(layers_list) // 2)]
                z_layer = int(rng.choice(low_layers))

            # 2. Mission origin and destination (crossing through central airspace)
            pos_x = radius * np.cos(theta) + float(rng.uniform(-3.0, 3.0))
            pos_y = radius * np.sin(theta) + float(rng.uniform(-3.0, 3.0))
            pos = np.array([pos_x, pos_y, float(z_layer)], dtype=float)

            dest_x = -radius * np.cos(theta) + float(rng.uniform(-5.0, 5.0))
            dest_y = -radius * np.sin(theta) + float(rng.uniform(-5.0, 5.0))
            dest = np.array([dest_x, dest_y, float(z_layer)], dtype=float)

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

    else:
        # Highway Corridors scenario
        from simulation.scenario import make_initial_agents
        agents = make_initial_agents(n, seed=cfg.seed)
        # Map altitude layers across configured layers
        for a in agents:
            if a.priority == 0:
                a.altitude_layer = layers_list[-1]
            elif a.priority == 1:
                a.altitude_layer = layers_list[len(layers_list) // 2]
            else:
                a.altitude_layer = layers_list[0]
            a.position[2] = float(a.altitude_layer)

    return agents


# ==============================================================================
# FULL-SYSTEM MULTI-AGENT SWARM SIMULATOR
# ==============================================================================
def run_simulation_with_profiling(cfg: SwarmDemoConfig) -> tuple[simulation.engine.SimulationResult, list[dict], dict]:
    """Execute forward simulation, activating ADMM conflict resolution and recording profiler stats."""
    simulation.overseer.reset_default_overseer()
    local_behavior.boids.reset_local_behavior_cache()

    base_cfg = get_config()
    # In converging scenario, activate ADMM deconfliction across entire interchange
    if cfg.scenario == "converging":
        base_cfg["admm"]["merge_zone_only"] = False
    else:
        base_cfg["admm"]["merge_zone_only"] = True

    agents = create_mission_agents(cfg)
    attack_cfg = {**base_cfg.get("attack", {}), "enabled": cfg.enable_attack}
    overseer_link_cfg = {"enabled": False}

    print("\n" + "=" * 75)
    print("MASOODA URBAN AIR TRAFFIC FULL-SYSTEM SIMULATION (P1-P6)")
    print("=" * 75)
    print(f"Fleet Size           : {cfg.n_agents} drones")
    print(f"Airspace Layers      : {cfg.num_layers} discrete altitude layers {cfg.layers}")
    print(f"Airspace Scenario    : {cfg.scenario.upper()} mission routes")
    print(f"Simulation Duration  : {cfg.duration_s:.1f} s ({int(cfg.duration_s / cfg.dt)} ticks)")
    print(f"Subsystems Active    : ADMM={cfg.use_admm}, Overseer={cfg.use_overseer}, Defense={cfg.enable_defense}")
    print("=" * 75)

    # Execute simulation wrapped inside P2 Week 5 ADMMRecorder
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
# DATA PERSISTENCE (SQLite Database & CSVs)
# ==============================================================================
class SwarmDataPersistence:
    def __init__(self, out_dir: Path):
        self.out_dir = out_dir
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.out_dir / "final_demo.db"
        self._init_sqlite()

    def _init_sqlite(self) -> None:
        """Initialize SQLite database tables."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS simulation_runs (
                run_id TEXT PRIMARY KEY,
                timestamp TEXT,
                scenario TEXT,
                n_agents INTEGER,
                num_layers INTEGER,
                duration_s REAL,
                total_admm_calls INTEGER,
                admm_convergence_rate REAL,
                admm_mean_iters REAL,
                admm_mean_solve_ms REAL,
                min_separation_m REAL,
                stl_robustness_margin_m REAL,
                stl_violation BOOLEAN
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS tick_records (
                run_id TEXT,
                tick INTEGER,
                time_s REAL,
                min_same_layer_sep_m REAL,
                PRIMARY KEY (run_id, tick)
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS admm_records (
                record_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT,
                scenario TEXT,
                group_size INTEGER,
                iterations INTEGER,
                converged BOOLEAN,
                solve_time_ms REAL
            )
        """)

        conn.commit()
        conn.close()

    def save_all(
        self,
        run_id: str,
        cfg: SwarmDemoConfig,
        result: simulation.engine.SimulationResult,
        admm_records: list[dict],
        admm_summary: dict,
        min_seps: list[float],
        stl_val: float,
        stl_violation: bool,
    ) -> tuple[Path, Path, Path]:
        """Save telemetry and profiler metrics to SQLite DB and CSVs."""
        timestamp_now = datetime.now().isoformat()

        # 1. Save to SQLite
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        finite_seps = [s for s in min_seps if np.isfinite(s)]
        lowest_sep = min(finite_seps) if finite_seps else float("inf")

        cur.execute("""
            INSERT OR REPLACE INTO simulation_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            run_id,
            timestamp_now,
            cfg.scenario,
            cfg.n_agents,
            cfg.num_layers,
            cfg.duration_s,
            int(admm_summary.get("count", 0)),
            float(admm_summary.get("fraction_converged", 0.0)),
            float(admm_summary.get("mean_iterations", 0.0)),
            float(admm_summary.get("mean_solve_ms", 0.0)),
            float(lowest_sep),
            float(stl_val),
            bool(stl_violation),
        ))

        # Insert tick records
        tick_data = [
            (run_id, t, float(result.times[t]), float(min_seps[t]))
            for t in range(len(min_seps))
        ]
        cur.executemany("INSERT OR REPLACE INTO tick_records VALUES (?, ?, ?, ?)", tick_data)

        # Insert ADMM records
        for r in admm_records:
            cur.execute("""
                INSERT INTO admm_records (run_id, scenario, group_size, iterations, converged, solve_time_ms)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                run_id,
                cfg.scenario,
                int(r["group_size"]),
                int(r["iterations"]),
                bool(r["converged"]),
                float(r["solve_time_s"] * 1000.0),
            ))

        conn.commit()
        conn.close()

        # 2. Save Telemetry CSV
        csv_telemetry = self.out_dir / "final_demo_log.csv"
        with open(csv_telemetry, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["tick", "time_s", "min_separation_m"])
            writer.writeheader()
            for t in range(len(min_seps)):
                writer.writerow({
                    "tick": t,
                    "time_s": float(result.times[t]),
                    "min_separation_m": float(min_seps[t]),
                })

        # 3. Save ADMM Solver CSV
        csv_admm = self.out_dir / "final_demo_admm.csv"
        if admm_records:
            with open(csv_admm, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["N", "scenario", "group_size", "iterations", "converged", "solve_time_s"])
                writer.writeheader()
                for r in admm_records:
                    writer.writerow({
                        "N": r.get("N", cfg.n_agents),
                        "scenario": r.get("scenario", cfg.scenario),
                        "group_size": r["group_size"],
                        "iterations": r["iterations"],
                        "converged": r["converged"],
                        "solve_time_s": r["solve_time_s"],
                    })

        return self.db_path, csv_telemetry, csv_admm


# ==============================================================================
# VISUALIZER (3D Animation GIF & 4-Panel Analytics PNG)
# ==============================================================================
class SwarmVisualizer:
    def __init__(
        self,
        cfg: SwarmDemoConfig,
        result: simulation.engine.SimulationResult,
        admm_records: list[dict],
        min_seps: list[float],
        out_dir: Path,
    ):
        self.cfg = cfg
        self.result = result
        self.admm_records = admm_records
        self.min_seps = min_seps
        self.out_dir = out_dir

        self.times = result.times
        self.positions = result.positions  # (T, N, 3)
        self.n_steps, self.n_agents, _ = self.positions.shape

        self.type_colors = {
            AgentType.EMERGENCY: "#d93a3a",  # Red
            AgentType.EVTOL: "#2a6fdb",      # Blue
            AgentType.DELIVERY: "#e08a1e",   # Amber
        }

    def render_3d_state(self, ax, frame: int) -> None:
        ax.cla()
        pos_f = self.positions[frame]

        if self.cfg.scenario == "converging":
            x_min, x_max = -90.0, 90.0
            y_min, y_max = -90.0, 90.0
        else:
            cur_x = float(np.mean(pos_f[:, 0]))
            x_min, x_max = max(0.0, cur_x - 130.0), cur_x + 130.0
            y_min, y_max = -30.0, 130.0

        # Draw layer planes
        layers = self.cfg.layers
        X, Y = np.meshgrid([x_min, x_max], [y_min, y_max])
        for l in layers:
            ax.plot_surface(X, Y, np.full_like(X, float(l)), color="steelblue", alpha=0.05, shade=False)

        # Plot agent trajectories with type colors
        trail_start = max(0, frame - 18)
        for i in range(self.n_agents):
            color = "#d93a3a" if i % 3 == 0 else ("#2a6fdb" if i % 3 == 1 else "#e08a1e")
            trail = self.positions[trail_start:frame + 1, i]
            if len(trail) > 1:
                ax.plot(trail[:, 0], trail[:, 1], trail[:, 2], color=color, alpha=0.5, lw=1.2)
            ax.scatter(pos_f[i, 0], pos_f[i, 1], pos_f[i, 2], color=color, s=35, edgecolor="black", depthshade=False)

        ax.set_xlim(x_min, x_max)
        ax.set_ylim(y_min, y_max)
        ax.set_zlim(min(layers) - 0.6, max(layers) + 0.6)
        ax.set_xlabel("X (m)", fontsize=8)
        ax.set_ylabel("Y (m)", fontsize=8)
        ax.set_zlabel("Layer Z", fontsize=8)
        ax.set_zticks(list(layers))
        azim = -60 + 0.35 * frame
        ax.view_init(elev=22, azim=azim)

    def save_dashboard(self) -> Path:
        """Create 4-panel analytical overview dashboard."""
        fig = plt.figure(figsize=(15, 7.5))

        # Panel 1: 3D Airspace Multi-layer perspective
        ax1 = fig.add_subplot(1, 2, 1, projection="3d")
        self.render_3d_state(ax1, self.n_steps - 1)
        ax1.set_title(f"2.5D Multilayer Airspace ({self.cfg.num_layers} Layers, N={self.n_agents})", fontsize=11, fontweight="bold")

        # Panel 2: P6 STL Safety Separation Monitoring
        ax2 = fig.add_subplot(2, 2, 2)
        valid_seps = [m if np.isfinite(m) else np.nan for m in self.min_seps]
        ax2.plot(self.times, valid_seps, color="purple", lw=1.5, label="Min Pairwise Separation (Same Layer)")
        ax2.axhline(self.cfg.d_safe, color="red", ls="--", lw=1.5, label=f"Safety Target $d_{{safe}}={self.cfg.d_safe}$ m")
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
            ax3.scatter(calls, iters, c=solve_ms, cmap="viridis", s=25, alpha=0.8, label="ADMM Calls")
            ax3.axhline(50, color="red", ls="--", alpha=0.7, label="Max Iterations (50)")
            cbar = plt.colorbar(ax3.collections[0], ax=ax3, pad=0.02)
            cbar.set_label("Solve Time (ms)", fontsize=8)
            ax3.set_xlabel("ADMM Solver Call Index", fontsize=9)
            ax3.set_ylabel("Iterations to Converge", fontsize=9)
            ax3.set_title("P2 Week 5 ADMM Convergence Profile Across Calls", fontsize=10)
            ax3.legend(loc="upper right", fontsize=8)
            ax3.grid(True, alpha=0.3)
        else:
            # Fallback layer occupancy
            layer_counts = {l: np.sum(np.abs(self.positions[:, :, 2] - float(l)) < 0.5, axis=1) for l in self.cfg.layers}
            for l, counts in layer_counts.items():
                ax3.plot(self.times, counts, label=f"Layer z={l}")
            ax3.set_xlabel("Time (s)", fontsize=9)
            ax3.set_ylabel("Drones per Layer", fontsize=9)
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
            ax.set_title(f"Tick {f}/{self.n_steps} (t={self.times[f]:.1f}s) — P1-P6 Swarm Governance", fontsize=10)

        anim = FuncAnimation(fig, update, frames=frames, interval=int(1000 / self.cfg.fps))
        out_gif = self.out_dir / "final_demo.gif"
        anim.save(out_gif, writer=PillowWriter(fps=self.cfg.fps), dpi=80)
        plt.close(fig)
        return out_gif


# ==============================================================================
# MAIN ENTRYPOINT
# ==============================================================================
def main() -> None:
    parser = argparse.ArgumentParser(description="MASooda Full-System P1-P6 Integration Demo with DB & CSV")
    parser.add_argument("--num_agents", type=int, default=60, help="Number of drones (e.g. 40, 60, 80)")
    parser.add_argument("--num_layers", type=int, default=5, help="Number of discrete altitude layers (e.g. 5, 7)")
    parser.add_argument("--duration", type=float, default=25.0, help="Simulation duration (s)")
    parser.add_argument("--scenario", choices=["converging", "corridors"], default="converging",
                        help="Airspace scenario: 'converging' (mission interchange) or 'corridors' (highway)")
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
        num_layers=args.num_layers,
        use_overseer=not args.no_overseer,
        use_admm=not args.no_admm,
        enable_attack=args.attack,
        enable_defense=not args.no_defense,
        fps=args.fps,
    )

    run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{cfg.scenario}_n{cfg.n_agents}_l{cfg.num_layers}"

    # 1. Run full simulation
    result, admm_records, admm_summary = run_simulation_with_profiling(cfg)

    # 2. Compute pairwise separations per tick (same layer)
    n_steps, n_agents, _ = result.positions.shape
    min_seps = []
    for t in range(n_steps):
        xy = result.positions[t, :, :2]
        z = result.positions[t, :, 2]
        same_dists = []
        for i in range(n_agents):
            for j in range(i + 1, n_agents):
                if abs(z[i] - z[j]) < 0.5:
                    same_dists.append(float(np.linalg.norm(xy[i] - xy[j])))
        min_seps.append(min(same_dists) if same_dists else float("inf"))

    # 3. Formal Verification
    stl_spec = STLSpec(name="global_min_separation", d_min=cfg.d_safe, dt=cfg.dt)
    stl_res = stl_monitor(result.positions, stl_spec)

    print("\n" + "=" * 75)
    print("DEMO EXPERIMENTAL RESULTS")
    print("=" * 75)
    print(f"Total Drones Simulated       : {cfg.n_agents}")
    print(f"Altitude Layers              : {cfg.num_layers} layers {cfg.layers}")
    print(f"Total ADMM Deconflictions    : {admm_summary['count']} solver calls")
    if admm_summary['count'] > 0:
        print(f"ADMM Convergence Rate        : {admm_summary['fraction_converged']*100.0:.1f}%")
        print(f"ADMM Mean Iterations         : {admm_summary['mean_iterations']:.1f}")
        print(f"ADMM Mean Solve Time         : {admm_summary['mean_solve_ms']:.2f} ms (p95: {admm_summary['p95_solve_ms']:.2f} ms)")
    print(f"Lowest Recorded Separation   : {min([s for s in min_seps if np.isfinite(s)]):.2f} m (Target: {cfg.d_safe} m)")
    print(f"P6 STL Robustness Margin     : {stl_res.value:.2f} m (Violation: {stl_res.violation})")
    print("=" * 75 + "\n")

    # 4. Save to SQLite DB and CSVs
    out_dir = ROOT / "outputs"
    persistence = SwarmDataPersistence(out_dir)
    db_path, csv_log, csv_admm = persistence.save_all(
        run_id, cfg, result, admm_records, admm_summary, min_seps, stl_res.value, stl_res.violation
    )

    # 5. Visualizations
    print("Rendering 3D GIF animation and analytical dashboard...")
    viz = SwarmVisualizer(cfg, result, admm_records, min_seps, out_dir)
    png_path = viz.save_dashboard()
    gif_path = viz.save_gif()

    print("\n" + "=" * 75)
    print("PERSISTED ARTIFACTS IN outputs/:")
    print("=" * 75)
    print(f"  - SQLite Database : {db_path} (tables: simulation_runs, tick_records, admm_records)")
    print(f"  - Telemetry CSV   : {csv_log}")
    print(f"  - ADMM Calls CSV  : {csv_admm}")
    print(f"  - 3D Animated GIF : {gif_path}")
    print(f"  - Analytics PNG   : {png_path}")
    print("=" * 75 + "\n")


if __name__ == "__main__":
    main()
