"""Final static visuals (C3): system overview, 2.5D side view, renderer before/after.

* system_overview — corridors, entry / merge / exit zones, agents by type,
  communication-graph edges for one snapshot, the global overseer (DTC) and labels.
* altitude_layers_side_view — x vs altitude layer for one snapshot. In the
  engine the z coordinate *is the layer index* (simulation/dynamics.py sets
  p_z = altitude_layer); config airspace.layer_height_meters is only the
  nominal spacing used for labels here.
* renderer_after — simulation.renderer.render_top_down with the shared palette
  (renderer_before.png was saved before the change).

The snapshot is taken from a saved Week 6 run (frames/*.npz, N = 60, seed 42,
t closest to experiments.week6 snapshot time 60 s) when one exists, otherwise
from the initial fleet. No new simulation is run.

    python scripts/week6_static_figures.py
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch, Rectangle  # noqa: E402
import numpy as np  # noqa: E402

from config.load_config import get_config  # noqa: E402
from experiments.week6 import read_rows  # noqa: E402
from experiments.week6_common import fig_dir, week6_root  # noqa: E402
from simulation.environment import build_corridors  # noqa: E402
from simulation.schema import AgentState, AgentType  # noqa: E402
from visualization.plots import apply_style, save_figure, type_color  # noqa: E402

SNAP_T = 60.0


def snapshot_agents(n: int = 60, seed: int = 42, t_target: float = SNAP_T) -> tuple[list[AgentState], str]:
    """Fleet at ~t_target from a saved frames file, else the initial fleet."""
    root = week6_root()
    for sub in ("e2_formation", "e1_admm_scaling", "e4_resilience", "e6_degradation"):
        for r in read_rows(root / sub / "runs.csv"):
            if (int(float(r["num_agents"])) == n and int(float(r["seed"])) == seed and r.get("frames_file")
                    and r.get("attack_enabled") == "False" and r.get("emergency") == "False"
                    and (root / sub / r["frames_file"]).is_file()):
                d = np.load(root / sub / r["frames_file"])
                k = int(np.argmin(np.abs(d["t"] - t_target)))
                agents = [AgentState(id=int(i), type=AgentType[str(d["types"][j])],
                                     position=np.asarray(d["positions"][k, j], float),
                                     velocity=np.asarray(d["velocities"][k, j], float),
                                     corridor_assignment=None if int(d["corridors"][k, j]) < 0 else
                                     int(d["corridors"][k, j]), altitude_layer=int(d["layers"][k, j]))
                          for j, i in enumerate(d["ids"])]
                return agents, f"{sub} run, N={n}, seed {seed}, t = {float(d['t'][k]):.0f} s"
    from simulation.scenario import make_initial_agents

    return make_initial_agents(n, seed=seed), f"initial fleet, N={n}, seed {seed}, t = 0 s"


def system_overview(agents: list[AgentState], source: str, out: Path) -> None:
    from simulation.interfaces import build_comm_graph

    cfg = get_config()
    cc = cfg["corridors"]
    corr = build_corridors()
    graph = build_comm_graph(agents)
    by_id = {a.id: a for a in agents}
    fig, ax = plt.subplots(figsize=(13.0, 6.2), layout="constrained")
    for zone, key, col in (("Entry zone", "entry_zone_x_meters", "#2CA02C"),
                           ("Merge zone", "merge_zone_x_meters", "#FF7F0E"),
                           ("Exit zone", "exit_zone_x_meters", "#1F77B4")):
        x0, x1 = cc[key]
        ax.axvspan(x0, x1, color=col, alpha=0.10, linewidth=0)
        ax.text((x0 + x1) / 2, corr[0].y_min - 18, f"{zone}\n{x0:g}–{x1:g} m", ha="center", va="top", fontsize=8,
                color=col)
    for c in corr:
        ax.add_patch(Rectangle((c.x_min, c.y_min), c.x_max - c.x_min, c.y_max - c.y_min, facecolor="#F2F2F2",
                               edgecolor="#999999", linewidth=0.8, zorder=0))
        ax.plot([c.x_min, c.x_max], [c.y_center] * 2, color="#BBBBBB", linestyle="--", linewidth=0.7, zorder=0)
        ax.text(-20, c.y_center, f"Corridor {c.id}\n(cap. {c.capacity})", ha="right", va="center", fontsize=8)
    edges = set()
    for a in agents:
        for nb in graph.neighbors(a.id):
            if nb in by_id:
                edges.add(tuple(sorted((a.id, nb))))
    for i, j in edges:
        p, q = by_id[i].position, by_id[j].position
        ax.plot([p[0], q[0]], [p[1], q[1]], color="#7F7F7F", linewidth=0.5, alpha=0.6, zorder=1)
    for ty in ("DELIVERY", "EVTOL", "EMERGENCY"):
        pts = np.array([a.position[:2] for a in agents if a.type.name == ty])
        if len(pts):
            ax.scatter(pts[:, 0], pts[:, 1], s=70 if ty == "EMERGENCY" else 30, color=type_color(ty),
                       marker="*" if ty == "EMERGENCY" else "o", edgecolors="black", linewidths=0.4, zorder=3,
                       label=f"{ty.capitalize()} ({sum(1 for a in agents if a.type.name == ty)})")
    ax.plot([], [], color="#7F7F7F", linewidth=0.8, label=f"comm. link ({cfg['communication']['mode']}, "
                                                          f"r = {cfg['communication']['radius_meters']:g} m)")
    # overseer
    top = corr[-1].y_max
    ox, oy = cc["length_meters"] / 2, top + 55
    ax.add_patch(FancyBboxPatch((ox - 230, oy - 14), 460, 28, boxstyle="round,pad=4", facecolor="#0072B2",
                                edgecolor="black", zorder=4))
    ax.text(ox, oy, "Global overseer (DTC)\ncorridor + altitude directives every "
            f"{cfg['overseer']['update_period_seconds']:g} s", ha="center", va="center", color="white", fontsize=8,
            zorder=5)
    for c in corr:
        ax.annotate("", xy=(ox + (c.id - 1) * 250, c.y_max), xytext=(ox + (c.id - 1) * 80, oy - 16),
                    arrowprops=dict(arrowstyle="->", color="#0072B2", linestyle="--", linewidth=1.0))
    ax.text(cc["length_meters"] + 20, top + 55, "Tier 1: overseer (global)\nTier 2: boids + ADMM (local)",
            fontsize=8, va="center")
    ax.set_xlim(-140, cc["length_meters"] + 180)
    ax.set_ylim(corr[0].y_min - 60, top + 85)
    ax.set_xlabel("x (m) — along the corridors")
    ax.set_ylabel("y (m)")
    ax.grid(False)
    ax.legend(loc="upper left", fontsize=8, ncol=2)
    ax.set_title(f"MASooda system overview — {source}")
    save_figure(fig, "system_overview", out_dir=out)


def side_view(agents: list[AgentState], source: str, out: Path) -> None:
    cfg = get_config()
    n_layers = int(cfg["airspace"]["num_layers"])
    h = float(cfg["airspace"]["layer_height_meters"])
    em_layer = int(cfg["airspace"]["emergency_layer"])
    fig, ax = plt.subplots(figsize=(11.0, 4.2), layout="constrained")
    for l in range(n_layers):
        ax.axhspan(l - 0.35, l + 0.35, color="#F2F2F2", zorder=0)
        tag = " (emergency layer)" if l == em_layer else ""
        ax.text(-20, l, f"layer {l}{tag}\nnominal {l * h:g} m", ha="right", va="center", fontsize=8)
    rng = np.random.default_rng(0)
    for ty in ("DELIVERY", "EVTOL", "EMERGENCY"):
        sel = [a for a in agents if a.type.name == ty]
        if not sel:
            continue
        x = np.array([a.position[0] for a in sel])
        z = np.array([float(a.position[2]) for a in sel]) + rng.uniform(-0.15, 0.15, len(sel))
        ax.scatter(x, z, s=60 if ty == "EMERGENCY" else 26, color=type_color(ty),
                   marker="*" if ty == "EMERGENCY" else "o", edgecolors="black", linewidths=0.4, label=ty.capitalize())
    cc = cfg["corridors"]
    for key, col in (("entry_zone_x_meters", "#2CA02C"), ("merge_zone_x_meters", "#FF7F0E"),
                     ("exit_zone_x_meters", "#1F77B4")):
        ax.axvspan(*cc[key], color=col, alpha=0.08, linewidth=0)
    ax.set_yticks(range(n_layers))
    ax.set_yticklabels([str(l) for l in range(n_layers)])
    ax.set_ylim(-0.6, n_layers - 0.4)
    ax.set_xlim(-330, float(cc["length_meters"]) + 20)
    ax.set_xlabel("x (m) — along the corridors")
    ax.set_ylabel("altitude layer index (z in the engine)")
    ax.set_title(f"2.5D side view: discrete altitude layers — {source}")
    ax.legend(loc="upper right", fontsize=8)
    ax.text(0.0, -0.22, f"z is the layer index (dynamics: p_z = altitude_layer); layers are {h:g} m apart nominally "
            "(config airspace.layer_height_meters, not used by the dynamics). Vertical jitter ±0.15 for visibility.",
            transform=ax.transAxes, fontsize=7, color="#444444")
    ax.grid(axis="y", visible=False)
    save_figure(fig, "altitude_layers_side_view", out_dir=out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.parse_args(argv)
    out = fig_dir(False)
    apply_style()
    agents, source = snapshot_agents()
    system_overview(agents, source, out)
    side_view(agents, source, out)
    from simulation.renderer import render_top_down
    from simulation.scenario import make_initial_agents

    fig = render_top_down(agents=make_initial_agents(20, seed=42),
                          title="render_top_down - after (shared visualization palette)")
    fig.savefig(out / "renderer_after.png", dpi=100, facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"[static] system_overview, altitude_layers_side_view, renderer_after -> {out} ({source})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
