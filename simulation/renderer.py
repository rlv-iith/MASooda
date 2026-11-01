"""Minimal top-down renderer for the 2.5D urban airspace.

Shows:
- Predefined flight corridors (lanes, centerlines, boundaries).
- Agents with positions, velocities, categories, and altitude-layer assignments.
- Inter-agent communication links.
- High-contrast visual styling suitable for technical presentations and reports.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence
import matplotlib
# Use Agg backend if non-interactive
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np

from config.load_config import get_config
from .mock_data import get_mock_agent_states, get_mock_comm_graph
from .schema import AgentState, AgentType, CommunicationGraph


from .environment import CorridorGeometry, build_corridors


DEFAULT_CORRIDORS: list[CorridorGeometry] = build_corridors()

TYPE_STYLES = {
    AgentType.EMERGENCY: {"color": "#E63946", "marker": "*", "label": "Emergency (P0)", "size": 150},
    AgentType.EVTOL: {"color": "#457B9D", "marker": "o", "label": "eVTOL (P1)", "size": 90},
    AgentType.DELIVERY: {"color": "#E9C46A", "marker": "s", "label": "Delivery (P2)", "size": 80},
}

LAYER_COLORS = {
    0: "#2A9D8F",  # Layer 0: Sea Green
    1: "#F4A261",  # Layer 1: Coral
    2: "#9D4EDD",  # Layer 2: Purple
}


def render_top_down(
    agents: Sequence[AgentState] | None = None,
    corridors: Sequence[CorridorGeometry] | None = None,
    comm_graph: CommunicationGraph | None = None,
    save_path: str | Path | None = None,
    show: bool = False,
    title: str = "MASooda 2.5D Urban Airspace (Top-Down View)",
) -> plt.Figure:
    """Render top-down 2.5D airspace showing corridors and static agents.

    Parameters
    ----------
    agents : Sequence[AgentState], optional
        List of agents to render. Defaults to 10 mock agents.
    corridors : Sequence[CorridorGeometry], optional
        Predefined corridors. Defaults to 3 parallel corridors.
    comm_graph : CommunicationGraph, optional
        Communication graph to show network edges.
    save_path : str or Path, optional
        Filepath where the figure should be saved as PNG.
    show : bool, default False
        Whether to invoke plt.show().

    Returns
    -------
    plt.Figure
        The rendered matplotlib figure object.
    """
    if agents is None:
        agents = get_mock_agent_states()
    if corridors is None:
        corridors = DEFAULT_CORRIDORS
    if comm_graph is None:
        comm_graph = get_mock_comm_graph()

    fig, ax = plt.subplots(figsize=(12, 7), dpi=150)
    fig.patch.set_facecolor("#12161F")
    ax.set_facecolor("#1A202C")

    # 1. Draw corridors
    for corridor in corridors:
        rect = patches.Rectangle(
            (corridor.x_min, corridor.y_min),
            corridor.x_max - corridor.x_min,
            corridor.width,
            linewidth=1.2,
            edgecolor="#4A5568",
            facecolor="#2D3748",
            alpha=0.45,
            linestyle="--",
            zorder=1,
        )
        ax.add_patch(rect)

        # Centerline
        ax.plot(
            [corridor.x_min, corridor.x_max],
            [corridor.y_center, corridor.y_center],
            color="#718096",
            linestyle=":",
            linewidth=1.0,
            alpha=0.7,
            zorder=2,
        )

        # Corridor label
        ax.text(
            corridor.x_min + 3,
            corridor.y_max - 3,
            f"{corridor.name} [Cap: {corridor.capacity}]",
            color="#A0AEC0",
            fontsize=8.5,
            fontweight="bold",
            zorder=3,
        )

    # 2. Draw communication links
    agent_pos_map = {a.id: a.position[:2] for a in agents}
    drawn_edges = set()
    for agent_id, neighbors in comm_graph.adjacency.items():
        if agent_id not in agent_pos_map:
            continue
        p1 = agent_pos_map[agent_id]
        for n_id in neighbors:
            if n_id in agent_pos_map:
                edge_key = tuple(sorted((agent_id, n_id)))
                if edge_key not in drawn_edges:
                    drawn_edges.add(edge_key)
                    p2 = agent_pos_map[n_id]
                    ax.plot(
                        [p1[0], p2[0]],
                        [p1[1], p2[1]],
                        color="#63B3ED",
                        linestyle="-",
                        linewidth=0.8,
                        alpha=0.35,
                        zorder=2,
                    )

    # 3. Draw agents
    type_handles = {}
    for agent in agents:
        x, y = float(agent.position[0]), float(agent.position[1])
        vx, vy = float(agent.velocity[0]), float(agent.velocity[1])
        layer = int(agent.altitude_layer)
        layer_color = LAYER_COLORS.get(layer, "#CBD5E0")
        style = TYPE_STYLES.get(agent.type, {"color": "#E2E8F0", "marker": "o", "label": str(agent.type), "size": 80})

        # Draw layer halo
        ax.scatter(
            [x],
            [y],
            s=style["size"] * 1.6,
            facecolors="none",
            edgecolors=layer_color,
            linewidths=2.0,
            zorder=4,
            alpha=0.9,
        )

        # Draw agent marker
        sc = ax.scatter(
            [x],
            [y],
            s=style["size"],
            color=style["color"],
            marker=style["marker"],
            zorder=5,
            edgecolors="#FFFFFF",
            linewidths=0.5,
        )
        if style["label"] not in type_handles:
            type_handles[style["label"]] = sc

        # Velocity vector
        if np.hypot(vx, vy) > 0.1:
            ax.arrow(
                x,
                y,
                vx * 1.2,
                vy * 1.2,
                head_width=1.8,
                head_length=2.5,
                fc=style["color"],
                ec=style["color"],
                alpha=0.8,
                zorder=4,
                length_includes_head=True,
            )

        # Agent ID and Altitude Layer badge
        ax.annotate(
            f"A{agent.id} [L{layer}]",
            xy=(x, y),
            xytext=(0, 9),
            textcoords="offset points",
            ha="center",
            va="bottom",
            color="#F7FAFC",
            fontsize=8,
            fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.2", facecolor="#2D3748", edgecolor=layer_color, alpha=0.8, lw=0.8),
            zorder=6,
        )

    # Airspace bounds and cosmetics
    x_lo = min(c.x_min for c in corridors)
    x_hi = max(c.x_max for c in corridors)
    y_lo = min(c.y_min for c in corridors)
    y_hi = max(c.y_max for c in corridors)
    ax.set_xlim(x_lo - 0.05 * (x_hi - x_lo), x_hi + 0.05 * (x_hi - x_lo))
    ax.set_ylim(y_lo - 20.0, y_hi + 20.0)
    ax.set_xlabel("X Position (meters)", color="#E2E8F0", fontsize=10, fontweight="normal")
    ax.set_ylabel("Y Position (meters)", color="#E2E8F0", fontsize=10, fontweight="normal")
    ax.set_title(title, color="#F7FAFC", fontsize=12, fontweight="bold", pad=12)

    ax.tick_params(colors="#A0AEC0", labelsize=8.5)
    for spine in ax.spines.values():
        spine.set_color("#4A5568")

    ax.grid(True, linestyle="--", alpha=0.15, color="#A0AEC0")

    # Custom layer badges in legend
    layer_proxies = [
        patches.Patch(facecolor=color, edgecolor="#FFFFFF", label=f"Altitude Layer {lvl}")
        for lvl, color in LAYER_COLORS.items()
    ]
    ax.legend(
        handles=list(type_handles.values()) + layer_proxies,
        labels=list(type_handles.keys()) + [f"Layer {lvl}" for lvl in LAYER_COLORS],
        loc="upper right",
        facecolor="#1A202C",
        edgecolor="#4A5568",
        labelcolor="#E2E8F0",
        fontsize=8,
        framealpha=0.9,
    )

    plt.tight_layout()

    if save_path is not None:
        p = Path(save_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(p, facecolor=fig.get_facecolor(), edgecolor="none")

    if show:
        plt.show()

    return fig


def animate_simulation(
    result: Any,
    save_path: str | Path,
    every_n_ticks: int = 5,
) -> None:
    """Animate a simulation result and save as GIF.

    Parameters
    ----------
    result : Any
        The simulation trajectory history with times, positions, and agent_ids.
    save_path : str or Path
        Destination file path for the output GIF.
    every_n_ticks : int, default 5
        Interval between rendered frames.
    """
    import matplotlib.animation as animation

    corridors = DEFAULT_CORRIDORS
    fig, ax = plt.subplots(figsize=(12, 7), dpi=100)
    fig.patch.set_facecolor("#12161F")
    ax.set_facecolor("#1A202C")

    # Draw corridors
    for corridor in corridors:
        rect = patches.Rectangle(
            (corridor.x_min, corridor.y_min),
            corridor.x_max - corridor.x_min,
            corridor.width,
            linewidth=1.2,
            edgecolor="#4A5568",
            facecolor="#2D3748",
            alpha=0.45,
            linestyle="--",
            zorder=1,
        )
        ax.add_patch(rect)

        # Centerline
        ax.plot(
            [corridor.x_min, corridor.x_max],
            [corridor.y_center, corridor.y_center],
            color="#718096",
            linestyle=":",
            linewidth=1.0,
            alpha=0.7,
            zorder=2,
        )

        # Label
        ax.text(
            corridor.x_min + 5,
            corridor.y_max - 4,
            f"{corridor.name} [Cap: {corridor.capacity}]",
            color="#A0AEC0",
            fontsize=8.5,
            fontweight="bold",
            zorder=3,
        )

    # Airspace bounds and cosmetics
    x_lo = min(c.x_min for c in corridors)
    x_hi = max(c.x_max for c in corridors)
    y_lo = min(c.y_min for c in corridors)
    y_hi = max(c.y_max for c in corridors)
    ax.set_xlim(x_lo - 20.0, x_hi + 20.0)
    ax.set_ylim(y_lo - 20.0, y_hi + 20.0)
    ax.set_xlabel("X Position (meters)", color="#E2E8F0", fontsize=10)
    ax.set_ylabel("Y Position (meters)", color="#E2E8F0", fontsize=10)
    ax.tick_params(colors="#A0AEC0", labelsize=8.5)
    for spine in ax.spines.values():
        spine.set_color("#4A5568")
    ax.grid(True, linestyle="--", alpha=0.15, color="#A0AEC0")

    time_text = ax.text(
        0.02,
        0.95,
        "",
        transform=ax.transAxes,
        color="#F7FAFC",
        fontsize=10,
        fontweight="bold",
        bbox=dict(boxstyle="round,pad=0.3", facecolor="#2D3748", edgecolor="#4A5568", alpha=0.85),
        zorder=7,
    )

    # Initial scatter for agents
    colors = ["#E63946" if aid % 3 == 0 else "#457B9D" if aid % 3 == 1 else "#E9C46A" for aid in result.agent_ids]
    init_xy = result.positions[0, :, :2] if len(result.positions) > 0 else np.empty((0, 2))
    sc = ax.scatter(
        init_xy[:, 0] if len(init_xy) > 0 else [],
        init_xy[:, 1] if len(init_xy) > 0 else [],
        s=40,
        c=colors,
        edgecolors="#FFFFFF",
        linewidths=0.5,
        zorder=5,
    )

    step_interval = max(1, every_n_ticks)
    frame_indices = list(range(0, len(result.times), step_interval))
    if (len(result.times) - 1) not in frame_indices and len(result.times) > 0:
        frame_indices.append(len(result.times) - 1)

    def update(frame_idx: int):
        pos_xy = result.positions[frame_idx, :, :2]
        sc.set_offsets(pos_xy)
        t = result.times[frame_idx]
        time_text.set_text(f"t = {t:.1f} s | Active: {pos_xy.shape[0]}")
        return [sc, time_text]

    plt.tight_layout()

    anim = animation.FuncAnimation(
        fig,
        update,
        frames=frame_indices,
        blit=True,
    )

    p = Path(save_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    writer = animation.PillowWriter(fps=10)
    anim.save(str(p), writer=writer)
    plt.close(fig)


if __name__ == "__main__":
    output_path = Path(__file__).resolve().parent.parent / "airspace_topdown.png"
    render_top_down(save_path=output_path)
    print(f"Top-down airspace render saved to {output_path}")
