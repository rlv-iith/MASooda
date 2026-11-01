"""Command line interface for MASooda multi-agent simulation scenarios."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Sequence

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from config.load_config import get_config
from simulation.engine import run_simulation
from simulation.logger import TrajectoryLogger
from simulation.overseer import reset_default_overseer
from simulation.renderer import animate_simulation, render_top_down
from simulation.scenario import make_initial_agents
from simulation.schema import AgentState
from verification.live_monitor import LiveSTLMonitor


def main(argv: Sequence[str] | None = None) -> int:
    cfg = get_config()
    default_agents = int(cfg.get("simulation", {}).get("num_agents", 60))
    default_duration = float(cfg.get("simulation", {}).get("duration_seconds", 180.0))
    default_seed = int(cfg.get("simulation", {}).get("random_seed", 42))

    parser = argparse.ArgumentParser(description="MASooda Urban Air Traffic Simulation")
    parser.add_argument(
        "--scenario",
        choices=["mvp", "nominal"],
        default="mvp",
        help="Simulation scenario (default: mvp)",
    )
    parser.add_argument(
        "--agents",
        type=int,
        default=default_agents,
        help=f"Number of agents (default: {default_agents})",
    )
    parser.add_argument(
        "--corridors",
        type=int,
        default=3,
        help="Number of corridors (default: 3)",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=default_duration,
        help=f"Simulation duration in seconds (default: {default_duration})",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=default_seed,
        help=f"Random seed (default: {default_seed})",
    )
    parser.add_argument(
        "--out",
        type=str,
        default="outputs/mvp",
        help="Output directory (default: outputs/mvp)",
    )
    parser.add_argument(
        "--gif",
        action="store_true",
        default=False,
        help="Generate animation GIF (default: False)",
    )

    args = parser.parse_args(argv)

    # 2. Corridors validation
    config_corridors = int(cfg.get("corridors", {}).get("count", 3))
    if args.corridors != config_corridors:
        sys.stderr.write(
            f"Error: --corridors ({args.corridors}) does not match config corridors.count ({config_corridors})\n"
        )
        sys.exit(2)

    # 3. Reset state before run
    reset_default_overseer()
    try:
        import local_behavior.boids as boids
        if hasattr(boids, "reset_local_behavior_cache"):
            boids.reset_local_behavior_cache()
        if hasattr(boids, "_last_corridor"):
            boids._last_corridor.clear()
    except Exception:
        pass

    # 4. Scenario settings
    if args.scenario == "nominal":
        attack_config = {**cfg.get("attack", {}), "enabled": False}
        defended = True
        overseer_link_config = {"enabled": False}
    else:  # mvp
        attack_config = {**cfg.get("attack", {}), "enabled": True}
        defended = True
        overseer_link_config = {
            "enabled": True,
            "down_start_seconds": 90.0,
            "down_end_seconds": 120.0,
        }

    # 5. Build agents and run simulation
    agents = make_initial_agents(n=args.agents, seed=args.seed)
    monitor = LiveSTLMonitor()
    traj = TrajectoryLogger()

    result = run_simulation(
        agents,
        duration_s=args.duration,
        loggers=[traj, monitor],
        use_overseer=True,
        use_admm=True,
        attack_config=attack_config,
        defended=defended,
        overseer_link_config=overseer_link_config,
    )

    # 6. Metrics
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    metrics_dict: dict[str, Any] = {}
    try:
        from verification.metrics import compute_run_metrics, write_metrics
        metrics_dict = compute_run_metrics(result, monitor, traj)
        metrics_dict.update(result.stats)
        metrics_dict["overseer_calls"] = result.overseer_calls
        metrics_dict["overseer_failures"] = result.overseer_failures
        write_metrics(metrics_dict, out_dir / "metrics.json")
    except Exception:
        metrics_dict = {
            "min_robustness": float(monitor.min_robustness()),
            "safety_violation_ticks": int(monitor.violation_count()),
            "overseer_calls": int(result.overseer_calls),
            "overseer_failures": int(result.overseer_failures),
        }
        metrics_dict.update(result.stats)
        with open(out_dir / "metrics.json", "w", encoding="utf-8") as f:
            json.dump(metrics_dict, f, indent=2, default=str)

    # 7. Save outputs
    monitor.to_csv(out_dir / "stl_robustness.csv")
    if hasattr(traj, "to_csv"):
        traj.to_csv(out_dir / "trajectory.csv")

    # Final-frame PNG
    final_positions = result.positions[-1]
    final_velocities = result.velocities[-1] if len(result.velocities) > 0 else np.zeros((len(agents), 3))
    final_agents = [
        AgentState(
            id=orig.id,
            type=orig.type,
            position=final_positions[i].copy(),
            velocity=final_velocities[i].copy(),
            acceleration=np.zeros(3),
            destination=orig.destination.copy(),
            priority=orig.priority,
            corridor_assignment=orig.corridor_assignment,
            neighbor_set=list(orig.neighbor_set),
            altitude_layer=orig.altitude_layer,
        )
        for i, orig in enumerate(agents)
    ]
    render_top_down(agents=final_agents, save_path=out_dir / "final_frame.png")
    plt.close("all")

    # GIF only if requested
    if args.gif:
        animate_simulation(result, save_path=out_dir / "simulation.gif")
        plt.close("all")

    # 8. Print summary
    min_rob = metrics_dict.get("min_robustness", metrics_dict.get("min_robustness_m", float("nan")))
    violations = metrics_dict.get("safety_violation_ticks", 0)
    admm_events = result.stats.get("admm_events", 0)
    malicious_ids = result.stats.get("malicious_ids", [])
    reports_dropped = result.stats.get("reports_dropped", 0)
    overseer_dropped = result.stats.get("overseer_dropped", 0)

    summary_lines = [
        f"=== Simulation Summary ({args.scenario.upper()}) ===",
        f"Agents: {len(agents)}",
        f"Duration: {args.duration:.1f} s",
        f"Min Robustness: {min_rob:.3f} m" if isinstance(min_rob, (int, float)) else f"Min Robustness: {min_rob}",
        f"Safety Violations: {violations}",
        f"ADMM Events: {admm_events}",
        f"Malicious IDs: {malicious_ids}",
        f"Reports Dropped: {reports_dropped}",
        f"Overseer Dropped: {overseer_dropped}",
    ]
    summary_text = "\n".join(summary_lines)
    print(summary_text)

    return 0


if __name__ == "__main__":
    sys.exit(main())

