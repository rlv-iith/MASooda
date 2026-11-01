"""Compare no attack, undefended attack, and defended attack simulations."""

from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("MPLCONFIGDIR", "/tmp/masooda-matplotlib")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from config.load_config import get_config
from local_behavior.boids import _last_corridor
from resilience.attack import apply_attack, inject_attack
from resilience.defense import defend_neighbor_reports
from simulation.environment import build_corridors, corridor_occupancy
from simulation.interfaces import build_comm_graph, step_dynamics, update_local_behavior
from simulation.overseer import real_overseer_update, reset_default_overseer
from simulation.scenario import make_initial_agents
from simulation.schema import GlobalStateSnapshot
from verification.live_monitor import LiveSTLMonitor


def run(
    mode: str,
    n_agents: int = 60,
    duration: float = 120.0,
    offset: float = 25.0,
    attack_start: float = 60.0,
) -> dict:
    """Run one deterministic simulation without using the simulation engine."""
    if mode not in {"none", "undefended", "defended"}:
        raise ValueError("mode must be 'none', 'undefended', or 'defended'")

    cfg = get_config()
    reset_default_overseer()
    _last_corridor.clear()
    agents = make_initial_agents(n_agents, seed=42)
    dt = float(cfg["simulation"]["timestep_seconds"])
    tau_v = float(cfg["control"]["velocity_time_constant_seconds"])
    period = float(cfg.get("overseer", {}).get("update_period_seconds", 2.0))
    period_steps = max(1, int(round(period / dt)))
    attack_cfg = {
        **cfg["attack"],
        "enabled": mode != "none",
        "offset_magnitude_meters": float(offset),
        "start_time_seconds": float(attack_start),
    }

    # The attack module chooses deterministically from the same initial fleet.
    selection_cfg = {**attack_cfg, "enabled": True}
    selection = inject_attack(agents, selection_cfg, attack_start)
    malicious_id = selection.malicious[0] if selection.malicious else None

    corridors = build_corridors(cfg)
    monitor = LiveSTLMonitor()
    monitor.log_state(0.0, agents)
    cached_directive = None
    dropped_total = 0
    honest_dropped = 0
    neighbor_report_errors: list[float] = []
    n_steps = int(round(duration / dt))

    for step_idx in range(n_steps):
        t = round(step_idx * dt, 8)
        if step_idx % period_steps == 0:
            snapshot = GlobalStateSnapshot(
                timestamp=t,
                corridor_occupancy=corridor_occupancy(agents, corridors),
                agent_ids=[a.id for a in agents],
                agent_types={a.id: a.type for a in agents},
                agent_priorities={a.id: a.priority for a in agents},
            )
            cached_directive = real_overseer_update(snapshot)
            if cached_directive is not None:
                for agent in agents:
                    if agent.id in cached_directive.corridor_map:
                        agent.corridor_assignment = cached_directive.corridor_map[agent.id]

        graph = build_comm_graph(agents)
        true_by_id = {a.id: a for a in agents}
        attack_state = inject_attack(agents, attack_cfg, t)
        reported_by_id = {
            a.id: a for a in apply_attack(agents, attack_state)
        }
        active_malicious = set(attack_state.malicious)

        if malicious_id is not None and malicious_id in true_by_id:
            for receiver_id, receiver in true_by_id.items():
                if receiver_id == malicious_id or malicious_id not in graph.neighbors(receiver_id):
                    continue
                error = np.linalg.norm(
                    reported_by_id[malicious_id].position[:2]
                    - true_by_id[malicious_id].position[:2]
                )
                neighbor_report_errors.append(float(error))

        next_agents = []
        for agent in agents:
            neighbor_ids = graph.neighbors(agent.id)
            true_nbrs = [true_by_id[nid] for nid in neighbor_ids if nid in true_by_id]
            reported_nbrs = [reported_by_id[nid] for nid in neighbor_ids if nid in reported_by_id]

            if agent.id in active_malicious:
                behavior_neighbors = true_nbrs
            elif mode == "undefended":
                behavior_neighbors = reported_nbrs
            elif mode == "defended":
                defense = defend_neighbor_reports(agent, reported_nbrs, true_nbrs)
                behavior_neighbors = defense.kept
                dropped_total += len(defense.dropped_ids)
                honest_dropped += sum(nid not in active_malicious for nid in defense.dropped_ids)
            else:
                behavior_neighbors = reported_nbrs

            v_des = update_local_behavior(agent, behavior_neighbors, cached_directive)
            accel = (v_des - agent.velocity) / tau_v
            updated = step_dynamics(agent, accel, dt)
            updated.neighbor_set = list(neighbor_ids)
            next_agents.append(updated)

        agents = next_agents
        monitor.log_state(round(t + dt, 8), agents)

    after_50 = [record["rho"] for record in monitor.history if record["t"] >= 50.0]
    return {
        "mode": mode,
        "offset": float(offset),
        "malicious_id": malicious_id,
        "min_robustness": monitor.min_robustness(),
        "min_robustness_after_50": min(after_50) if after_50 else monitor.min_robustness(),
        "violation_ticks": monitor.violation_count(),
        "reports_dropped_total": dropped_total,
        "honest_reports_wrongly_dropped": honest_dropped,
        "mean_report_error_seen_by_malicious_neighbors": (
            float(np.mean(neighbor_report_errors)) if neighbor_report_errors else 0.0
        ),
    }


def main() -> None:
    out_dir = ROOT / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = [
        run(mode, offset=offset)
        for offset in (10.0, 25.0, 50.0)
        for mode in ("none", "undefended", "defended")
    ]
    csv_path = out_dir / "p5_week4_attack_demo.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    modes = ("none", "undefended", "defended")
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    offset_25 = [next(r for r in rows if r["offset"] == 25.0 and r["mode"] == mode)
                 for mode in modes]
    axes[0].bar(modes, [r["min_robustness_after_50"] for r in offset_25], color=["#548235", "#c0504d", "#4472c4"])
    axes[0].axhline(0.0, color="black", linewidth=0.8)
    axes[0].set_title("Minimum robustness after 50 s (25 m offset)")
    axes[0].set_ylabel("STL robustness (m)")
    axes[0].grid(axis="y", alpha=0.25)

    x = np.arange(3)
    width = 0.24
    for i, mode in enumerate(modes):
        values = [next(r["violation_ticks"] for r in rows
                       if r["offset"] == offset and r["mode"] == mode)
                  for offset in (10.0, 25.0, 50.0)]
        axes[1].bar(x + (i - 1) * width, values, width, label=mode)
    axes[1].set_xticks(x, ["10 m", "25 m", "50 m"])
    axes[1].set_title("Violation ticks by attack offset")
    axes[1].set_xlabel("Offset")
    axes[1].set_ylabel("Violation ticks")
    axes[1].legend(title="Mode")
    axes[1].grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(out_dir / "p5_week4_attack_demo.png", dpi=160)
    plt.close(fig)
    print(f"Saved {csv_path} and outputs/p5_week4_attack_demo.png")


if __name__ == "__main__":
    main()
