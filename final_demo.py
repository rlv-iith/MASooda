"""Final Full-System Integration Demo: P1-P6 Multilayer Urban Swarm Governance.

Integrates all modules across the project:
  - P1 (Simulation Engine): 2.5D double-integrator dynamics, corridor geometry, comm-graph.
  - P2 (Distributed Optimization): Consensus ADMM conflict resolution (x-y negotiation per layer).
  - P3 (Local Swarm Behavior): Boids-style navigation (goal seeking + velocity steering).
  - P4 (Centralized DTC Overseer): Corridor allocation and priority management (EMERGENCY, EVTOL, DELIVERY).
  - P5 (Resilience & Security): Fault/attack injection and status monitoring.
  - P6 (Formal Verification): STL safety specification robustness monitoring G(separation >= d_min).

Outputs generated in outputs/:
  - outputs/final_demo.gif      : 3D animated multi-layer swarm simulation with color-coded drone types
  - outputs/final_demo.png      : 4-panel comprehensive analytics dashboard
  - outputs/final_demo_log.csv  : Complete tick-by-tick trajectory and safety metrics log

Run:
  uv run python final_demo.py
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
import numpy as np

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation, PillowWriter
from mpl_toolkits.mplot3d.art3d import Line3DCollection

from config.load_config import get_config
from conflict_resolution.adapter import resolve_conflict_event
from simulation.schema import (
    AgentState,
    AgentType,
    GlobalStateSnapshot,
    STLSpec,
)
from simulation.interfaces import (
    build_comm_graph,
    inject_attack,
    overseer_update,
    step_dynamics,
    update_local_behavior,
)
from verification.stl_monitor import stl_monitor


# ==============================================================================
# CONFIGURATION & PARAMETERS (Easily Editable)
# ==============================================================================
@dataclass
class SwarmDemoConfig:
    n_agents: int = 15            # Number of heterogeneous drones
    ticks: int = 60               # Duration of simulation
    dt: float = 0.1               # Simulation timestep (seconds)
    random_seed: int = 42

    # Kinematics & Physical Bounds
    arena_radius: float = 25.0    # Initial swarm perimeter radius (meters)
    arena_limit: float = 30.0     # Visual boundary limit [-30, 30]
    v_cruise: float = 12.0        # Cruise speed (m/s)
    v_max: float = 15.0           # Maximum physical velocity clamp (m/s)
    a_max: float = 4.0            # Maximum acceleration (m/s^2)
    d_safe: float = 8.0           # Minimum safe separation (meters)

    # Airspace Layers (2.5D Discrete Layers z in [-2, 2])
    layers: tuple[int, ...] = (-2, -1, 0, 1, 2)


# ==============================================================================
# FULL-SYSTEM MULTI-AGENT SWARM SIMULATOR
# ==============================================================================
class FullSystemSwarmDemo:
    def __init__(self, cfg: SwarmDemoConfig):
        self.cfg = cfg
        self.rng = np.random.default_rng(cfg.random_seed)
        self.output_dir = Path(__file__).resolve().parent / "outputs"
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self._init_agents()

    def _init_agents(self) -> None:
        """Create heterogeneous drone fleet (EMERGENCY, EVTOL, DELIVERY) arranged in converging routes."""
        n = self.cfg.n_agents
        angles = np.linspace(0, 2.0 * np.pi, n, endpoint=False)
        self.agents: list[AgentState] = []

        types_pool = [AgentType.EMERGENCY, AgentType.EVTOL, AgentType.DELIVERY]

        for i, theta in enumerate(angles):
            # Heterogeneous agent types & priorities
            agent_type = types_pool[i % len(types_pool)]
            priority = 0 if agent_type == AgentType.EMERGENCY else (1 if agent_type == AgentType.EVTOL else 2)

            # Circular converging start positions
            pos_x = self.cfg.arena_radius * np.cos(theta)
            pos_y = self.cfg.arena_radius * np.sin(theta)
            # Assign altitude layer based on priority (Emergency on top layer, delivery lower)
            z_layer = 1 if priority == 0 else (0 if priority == 1 else -1)
            pos = np.array([pos_x, pos_y, float(z_layer)], dtype=float)

            # Destination antipodal through center
            dest = np.array([-pos_x, -pos_y, float(z_layer)], dtype=float)

            # Initial velocity heading toward destination
            unit_to_goal = (dest - pos)[:2] / np.linalg.norm((dest - pos)[:2])
            vel = np.array([unit_to_goal[0] * self.cfg.v_cruise, unit_to_goal[1] * self.cfg.v_cruise, 0.0], dtype=float)

            agent = AgentState(
                id=i,
                type=agent_type,
                position=pos,
                velocity=vel,
                destination=dest,
                priority=priority,
                altitude_layer=z_layer,
            )
            self.agents.append(agent)

        # Telemetry History
        self.history_positions: list[np.ndarray] = [np.array([a.position.copy() for a in self.agents])]
        self.history_min_distances: list[float] = []
        self.history_admm_converged: list[bool] = []
        self.log_records: list[dict] = []

    def step(self, t_idx: int) -> None:
        """One tick of full-system hierarchy: P4 Overseer -> P3 Local -> P5 Security -> P2 ADMM -> P1 Dynamics."""
        sim_time = t_idx * self.cfg.dt

        # 1. P4 Global Overseer Directive
        snapshot = GlobalStateSnapshot(
            timestamp=sim_time,
            corridor_occupancy={0: 5, 1: 5, 2: 5},
            agent_ids=[a.id for a in self.agents],
            agent_types={a.id: a.type for a in self.agents},
            agent_priorities={a.id: a.priority for a in self.agents},
        )
        directive = overseer_update(snapshot)

        # 2. P1 Dynamic Communication Graph
        comm_graph = build_comm_graph(self.agents)

        # 3. P3 Local Behavior / Desired Waypoint Velocities
        desired_velocities: list[np.ndarray] = []
        for i, agent in enumerate(self.agents):
            neighbors = [self.agents[nid] for nid in comm_graph.neighbors(agent.id) if nid < len(self.agents)]
            desired_vel = update_local_behavior(agent, neighbors, directive)
            desired_velocities.append(desired_vel)

        # 4. P5 Fault & Cyberattack Injection
        attack_cfg = get_config().get("attack", {})
        attack_state = inject_attack(self.agents, attack_cfg, sim_time)

        # 5. P2 Consensus ADMM Distributed Deconfliction
        conflict_event = resolve_conflict_event(self.agents, priorities={a.id: a.priority for a in self.agents})
        self.history_admm_converged.append(conflict_event.converged)

        # 6. P1 2.5D Double-Integrator Dynamics Integration
        stepped_agents: list[AgentState] = []
        for agent in self.agents:
            resolved_vel = conflict_event.resolution.get(agent.id, agent.velocity)
            # Control input pushes velocity toward resolved deconflicted velocity
            control_acc = (resolved_vel - agent.velocity) / self.cfg.dt
            new_state = step_dynamics(
                agent_state=agent,
                control_input=control_acc,
                dt=self.cfg.dt,
                max_velocity=self.cfg.v_max,
                max_acceleration=self.cfg.a_max,
            )
            stepped_agents.append(new_state)
        self.agents = stepped_agents

        # Record minimum pairwise distance at this tick
        positions_xy = np.array([a.position[:2] for a in self.agents])
        n = len(self.agents)
        min_dist = min(
            float(np.linalg.norm(positions_xy[i] - positions_xy[j]))
            for i in range(n) for j in range(i + 1, n)
        )
        self.history_min_distances.append(min_dist)
        current_positions = np.array([a.position.copy() for a in self.agents])
        self.history_positions.append(current_positions)

        self.log_records.append({
            "tick": t_idx,
            "sim_time": sim_time,
            "min_separation_m": min_dist,
            "admm_converged": conflict_event.converged,
            "malicious_count": len(attack_state.malicious),
        })

    def run(self) -> None:
        """Run complete multi-agent simulation."""
        print(f"Running full-system swarm governance simulation: {self.cfg.n_agents} drones, {self.cfg.ticks} ticks...")
        for t in range(self.cfg.ticks):
            self.step(t)

        self.history_positions = np.array(self.history_positions)  # (T+1, N, 3)

        # Save CSV telemetry
        csv_path = self.output_dir / "final_demo_log.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["tick", "sim_time", "min_separation_m", "admm_converged", "malicious_count"])
            writer.writeheader()
            writer.writerows(self.log_records)

        # 7. P6 Signal Temporal Logic (STL) Robustness Verification
        stl_spec = STLSpec(name="global_min_separation", d_min=self.cfg.d_safe, dt=self.cfg.dt)
        stl_result = stl_monitor(self.history_positions, stl_spec)

        print("\n" + "=" * 75)
        print("FULL-SYSTEM INTEGRATION RESULTS (P1-P6)")
        print("=" * 75)
        print(f"ADMM Convergence Rate       : {100.0 * np.mean(self.history_admm_converged):.1f}%")
        print(f"Lowest Recorded Separation  : {min(self.history_min_distances):.3f} m (Safety Target: {self.cfg.d_safe} m)")
        print(f"STL Safety Specification    : G(d_ij >= {self.cfg.d_safe} m)")
        print(f"STL Robustness Margin       : {stl_result.value:.3f} m (Violation: {stl_result.violation})")
        print("=" * 75 + "\n")


# ==============================================================================
# VISUALIZATION & ANIMATION RENDERER
# ==============================================================================
class SwarmVisualizer:
    def __init__(self, sim: FullSystemSwarmDemo):
        self.sim = sim
        self.cfg = sim.cfg
        self.type_colors = {
            AgentType.EMERGENCY: "#d93a3a",  # Red
            AgentType.EVTOL: "#2a6fdb",      # Blue
            AgentType.DELIVERY: "#e08a1e",   # Amber / Orange
        }

    def render_3d_state(self, ax, frame: int) -> None:
        ax.cla()
        arena = self.cfg.arena_limit
        # Draw altitude layer planes
        for l in self.cfg.layers:
            X, Y = np.meshgrid([-arena, arena], [-arena, arena])
            ax.plot_surface(X, Y, np.full_like(X, l), color="gray", alpha=0.06, shade=False)

        P = self.sim.history_positions
        for i, agent in enumerate(self.sim.agents):
            color = self.type_colors.get(agent.type, "#2a6fdb")
            # Past trajectory trail
            trail = P[:frame + 1, i]
            if len(trail) > 1:
                ax.plot(trail[:, 0], trail[:, 1], trail[:, 2], color=color, alpha=0.6, lw=1.5)
            # Current agent position
            ax.scatter(trail[-1, 0], trail[-1, 1], trail[-1, 2], color=color, s=70, edgecolor="k")

        ax.set_xlim(-arena, arena)
        ax.set_ylim(-arena, arena)
        ax.set_zlim(min(self.cfg.layers) - 0.5, max(self.cfg.layers) + 0.5)
        ax.set_xlabel("X (m)")
        ax.set_ylabel("Y (m)")
        ax.set_zlabel("Layer Z")
        ax.set_zticks(list(self.cfg.layers))
        ax.view_init(elev=26, azim=-55 + 0.4 * frame)

    def save_dashboard(self) -> Path:
        """Create a 4-panel analytical overview dashboard."""
        fig = plt.figure(figsize=(15, 7.5))

        # 1. 3D Airspace Overview
        ax1 = fig.add_subplot(1, 2, 1, projection="3d")
        self.render_3d_state(ax1, self.cfg.ticks)
        ax1.set_title("2.5D Multilayer Airspace Simulation (P1/P2/P3)", fontsize=11, fontweight="bold")

        # 2. Separation Margin over Time
        ax2 = fig.add_subplot(2, 2, 2)
        sim_times = [r["sim_time"] for r in self.sim.log_records]
        ax2.plot(sim_times, self.sim.history_min_distances, color="#6b3ba7", lw=1.8, label="Pairwise Separation (m)")
        ax2.axhline(self.cfg.d_safe, color="black", ls="--", lw=1.5, label=f"Safety Buffer ({self.cfg.d_safe} m)")
        ax2.set_xlabel("Time (s)")
        ax2.set_ylabel("Separation (m)")
        ax2.set_title("P6 STL Safety Margin Monitoring Over Time", fontsize=10)
        ax2.legend(loc="upper right", fontsize=8)
        ax2.grid(True, alpha=0.3)

        # 3. Fleet Composition & ADMM Convergence
        ax3 = fig.add_subplot(2, 2, 4)
        conv_rates = [100.0 if c else 0.0 for c in self.sim.history_admm_converged]
        ax3.plot(sim_times, conv_rates, color="#2e9e5b", lw=1.6, label="ADMM Converged (%)")
        ax3.set_xlabel("Time (s)")
        ax3.set_ylabel("Convergence (%)")
        ax3.set_title("P2 ADMM Solver Convergence Status", fontsize=10)
        ax3.set_ylim(-10, 110)
        ax3.grid(True, alpha=0.3)
        ax3.legend(loc="lower right", fontsize=8)

        plt.tight_layout()
        out_png = self.sim.output_dir / "final_demo.png"
        plt.savefig(out_png, dpi=140)
        plt.close(fig)
        return out_png

    def save_gif(self) -> Path:
        """Render 3D animated GIF."""
        fig = plt.figure(figsize=(7, 6))
        ax = fig.add_subplot(111, projection="3d")
        frames = list(range(0, self.cfg.ticks + 1, 2))

        def update(f: int):
            self.render_3d_state(ax, f)
            ax.set_title(f"Tick {f}/{self.cfg.ticks} - Swarm Governance Demo", fontsize=10)

        anim = FuncAnimation(fig, update, frames=frames, interval=100)
        out_gif = self.sim.output_dir / "final_demo.gif"
        anim.save(out_gif, writer=PillowWriter(fps=10), dpi=75)
        plt.close(fig)
        return out_gif


# ==============================================================================
# MAIN SCRIPT ENTRYPOINT
# ==============================================================================
def main() -> None:
    cfg = SwarmDemoConfig()
    sim = FullSystemSwarmDemo(cfg)
    sim.run()

    viz = SwarmVisualizer(sim)
    png_path = viz.save_dashboard()
    gif_path = viz.save_gif()

    print(f"Generated Outputs in outputs/:")
    print(f"  - PNG Dashboard : {png_path}")
    print(f"  - Animated GIF  : {gif_path}")
    print(f"  - Telemetry CSV : {sim.output_dir / 'final_demo_log.csv'}")


if __name__ == "__main__":
    main()
