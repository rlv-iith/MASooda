"""True 2.5D replay of an MVP run: stacked altitude layers in 3D, side view and top-down view.

Reads the files written by ``python main.py --scenario mvp`` (trajectory.csv and
stl_robustness.csv). Nothing is re-simulated: the attacker's falsified broadcast is
recomputed with the same deterministic inject_attack() call the engine used. If the
trajectory has no "layer" column (old runs) every drone is treated as being on layer 0.

Usage (from the repo root, after running main.py):
    python scripts/mvp_visual_25d.py                       # whole run -> outputs/mvp/mvp_visual_25d.gif
    python scripts/mvp_visual_25d.py --start 50 --end 130  # only the interesting part
    python scripts/mvp_visual_25d.py --mp4                 # MP4 instead of GIF (needs ffmpeg)
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.animation import FFMpegWriter, FuncAnimation, PillowWriter
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401  (registers the 3d projection)
from mpl_toolkits.mplot3d.art3d import Line3DCollection, Poly3DCollection

from config.load_config import get_config
from resilience.attack import inject_attack
from simulation.schema import AgentState, AgentType

TYPE_STYLE = {
    "EMERGENCY": ("#E63946", "Emergency"),
    "EVTOL": ("#4CC9F0", "eVTOL"),
    "DELIVERY": ("#E9C46A", "Delivery"),
}
LAYER_COLOURS = ["#6C8EBF", "#2EC4B6", "#E63946"]  # grey-blue, teal, red
BG, PANEL, GRID, TEXT, MUTED = "#0F131A", "#171C26", "#2A3140", "#F1F5F9", "#94A3B8"
ATTACK_RED, VIOLATION = "#FF2E63", "#FF4D4D"


def load_run(run_dir: Path):
    """Return times, ids, positions (T,N,2), layers (T,N), types, plus the STL series."""
    rows_by_t: dict[float, dict[int, tuple[float, float, int]]] = defaultdict(dict)
    types: dict[int, str] = {}
    with open(run_dir / "trajectory.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            t, aid = round(float(r["t"]), 3), int(r["agent_id"])
            layer = int(float(r["layer"])) if r.get("layer") not in (None, "") else 0
            rows_by_t[t][aid] = (float(r["x"]), float(r["y"]), layer)
            types[aid] = r["type"].split(".")[-1].upper()
    times = np.array(sorted(rows_by_t))
    ids = sorted(types)
    pos = np.array([[rows_by_t[t][i][:2] for i in ids] for t in times], dtype=float)
    layers = np.array([[rows_by_t[t][i][2] for i in ids] for t in times], dtype=int)

    stl_t, stl_rho = [], []
    with open(run_dir / "stl_robustness.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            stl_t.append(float(r["t"]))
            stl_rho.append(float(r["rho"]))
    return times, ids, pos, layers, types, np.array(stl_t), np.array(stl_rho)


def style_axes(ax) -> None:
    ax.set_facecolor(PANEL)
    ax.tick_params(colors=MUTED, labelsize=8)
    for s in ax.spines.values():
        s.set_color(GRID)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", default="outputs/mvp", help="folder written by main.py")
    ap.add_argument("--out", default=None, help="output file (default <run>/mvp_visual_25d.gif or .mp4)")
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--end", type=float, default=None)
    ap.add_argument("--step", type=float, default=0.5, help="simulated seconds per frame")
    ap.add_argument("--fps", type=int, default=12)
    ap.add_argument("--mp4", action="store_true")
    ap.add_argument("--link-down", type=float, nargs=2, default=[90.0, 120.0], metavar=("START", "END"))
    args = ap.parse_args(argv)

    cfg = get_config()
    run_dir = Path(args.run)
    times, ids, pos, layers, types, stl_t, stl_rho = load_run(run_dir)
    idx_of = {aid: k for k, aid in enumerate(ids)}

    airspace = cfg.get("airspace", {})
    layer_h = float(airspace.get("layer_height_meters", 30.0))
    num_layers = max(int(airspace.get("num_layers", 3)), int(layers.max()) + 1)
    emergency_layer = int(airspace.get("emergency_layer", 2))

    d_min = float(cfg["safety"]["minimum_separation_meters"])
    corr = cfg["corridors"]
    spacing, width, count = float(corr["centerline_spacing_meters"]), float(corr["width_meters"]), int(corr["count"])
    length = float(corr["length_meters"])
    merge_zone = corr["merge_zone_x_meters"]
    attack_cfg = {**cfg["attack"], "enabled": True}
    attack_start = float(attack_cfg["start_time_seconds"])
    link_down = tuple(args.link_down)

    dt = float(times[1] - times[0])
    every = max(1, int(round(args.step / dt)))
    end = args.end if args.end is not None else float(times[-1])
    frames = [k for k in range(0, len(times), every) if args.start - 1e-9 <= times[k] <= end + 1e-9]
    lag = max(1, int(round(2.0 / dt)))  # "recent layer change" window = 2 s

    def layer_name(layer: int) -> str:
        if layer == emergency_layer:
            return f"Layer {layer} - emergency ({layer * layer_h:.0f} m)"
        return f"Layer {layer} ({layer * layer_h:.0f} m)"

    # ---------- figure layout ----------
    fig = plt.figure(figsize=(16, 9), dpi=90, facecolor=BG)
    ax3 = fig.add_axes([0.11, 0.03, 0.53, 0.87], projection="3d", facecolor=BG)
    gs = fig.add_gridspec(3, 1, height_ratios=[1, 1, 1.1], left=0.68, right=0.98, top=0.90, bottom=0.07, hspace=0.50)
    ax_side = fig.add_subplot(gs[0])
    ax_top = fig.add_subplot(gs[1])
    ax_stl = fig.add_subplot(gs[2])
    for ax in (ax_side, ax_top, ax_stl):
        style_axes(ax)

    title = fig.text(0.02, 0.955, "", color=TEXT, fontsize=13, fontweight="bold")
    banner_attack = fig.text(0.27, 0.955, "", fontsize=10.5, fontweight="bold",
                             bbox=dict(boxstyle="round,pad=0.35", fc="#222", ec="none"))
    banner_link = fig.text(0.46, 0.955, "", fontsize=10.5, fontweight="bold",
                           bbox=dict(boxstyle="round,pad=0.35", fc="#222", ec="none"))
    banner_layers = fig.text(0.76, 0.955, "", color=TEXT, fontsize=11, fontweight="bold", family="monospace",
                             bbox=dict(boxstyle="round,pad=0.35", fc="#222", ec="none"))

    y_lo, y_hi = -width, (count - 1) * spacing + width

    # ---------- static 3D scene ----------
    ax3.set_box_aspect((4, 1.3, 0.9), zoom=1.05)
    ax3.set_xlim(0, length)
    ax3.set_ylim(y_lo, y_hi)
    ax3.set_zlim(0, (num_layers - 1) * layer_h + 10)
    ax3.set_xlabel("x: along corridors (m)", color=MUTED, fontsize=8, labelpad=4)
    ax3.set_ylabel("y (m)", color=MUTED, fontsize=8, labelpad=2)
    ax3.set_zticks([layer * layer_h for layer in range(num_layers)])
    ax3.tick_params(colors=MUTED, labelsize=7)
    for axis in (ax3.xaxis, ax3.yaxis, ax3.zaxis):
        axis.set_pane_color((0.09, 0.11, 0.15, 0.0))
        axis._axinfo["grid"]["color"] = GRID
    for layer in range(num_layers):
        alt = layer * layer_h
        col = LAYER_COLOURS[min(layer, len(LAYER_COLOURS) - 1)]
        polys = []
        for c in range(count):
            yc = c * spacing
            polys.append([(0, yc - width / 2, alt), (length, yc - width / 2, alt),
                          (length, yc + width / 2, alt), (0, yc + width / 2, alt)])
        ax3.add_collection3d(Poly3DCollection(polys, facecolors=col, edgecolors=col, alpha=0.08, linewidths=0.6))
        ax3.text(-40, y_lo - 5, alt, layer_name(layer), color=col, fontsize=8, fontweight="bold",
                 ha="right", va="center")
    dyn3: list = []

    # ---------- static side view ----------
    ax_side.set_title("Side view: x vs altitude", color=TEXT, fontsize=9.5, loc="left")
    ax_side.set_xlim(0, 1600)
    ax_side.set_ylim(-0.45 * layer_h, (num_layers - 1) * layer_h + 0.45 * layer_h)
    ax_side.set_xlabel("x (m)", color=MUTED, fontsize=8)
    ax_side.set_ylabel("altitude (m)", color=MUTED, fontsize=8)
    ax_side.set_yticks([layer * layer_h for layer in range(num_layers)])
    for layer in range(num_layers):
        col = LAYER_COLOURS[min(layer, len(LAYER_COLOURS) - 1)]
        ax_side.axhline(layer * layer_h, ls=":", lw=0.9, color=col)
        ax_side.text(1595, layer * layer_h + 0.07 * layer_h, layer_name(layer), color=col, fontsize=7,
                     ha="right", va="bottom")
    ax_side.axvspan(merge_zone[0], merge_zone[1], color="#8338EC", alpha=0.10, lw=0)
    sc_side = ax_side.scatter([], [], s=16, edgecolors="none", zorder=3)
    ring_side = ax_side.scatter([], [], s=90, facecolors="none", edgecolors="white", lw=1.4, zorder=4)
    atk_side = ax_side.scatter([], [], marker="X", s=90, c=ATTACK_RED, edgecolors="white", zorder=5)

    # ---------- static top-down view ----------
    ax_top.set_title("Top-down view (colour = layer)", color=TEXT, fontsize=9.5, loc="left")
    ax_top.set_xlim(-20, length + 60)
    ax_top.set_ylim(y_lo - 8, y_hi + 32)
    ax_top.set_xlabel("x (m)", color=MUTED, fontsize=8)
    ax_top.set_ylabel("y (m)", color=MUTED, fontsize=8)
    ax_top.axvspan(merge_zone[0], merge_zone[1], color="#8338EC", alpha=0.10, lw=0)
    for c in range(count):
        yc = c * spacing
        ax_top.add_patch(Rectangle((0, yc - width / 2), length, width, fc="#232B3A", ec="#3B4559", lw=1, zorder=0))
    ax_top.legend(handles=[Line2D([], [], marker="o", ls="", mfc=LAYER_COLOURS[min(layer, len(LAYER_COLOURS) - 1)],
                                  mec="white", ms=6, label=f"layer {layer}") for layer in range(num_layers)],
                  loc="upper right", ncol=num_layers, fontsize=7, frameon=True, facecolor="#0B0F15", edgecolor=GRID,
                  labelcolor=TEXT, title="colour = layer", title_fontsize=7).get_title().set_color(MUTED)
    sc_top = ax_top.scatter([], [], s=14, edgecolors="white", linewidths=0.3, zorder=3)
    atk_top = ax_top.scatter([], [], marker="X", s=90, c=ATTACK_RED, edgecolors="white", zorder=5)

    # ---------- static STL panel ----------
    ax_stl.set_title("STL monitor: rho(t) = min distance - 8 m", color=TEXT, fontsize=9.5, loc="left")
    ax_stl.plot(stl_t, stl_rho, color="#64748B", lw=0.8)
    ax_stl.fill_between(stl_t, stl_rho, 0, where=stl_rho < 0, color=VIOLATION, alpha=0.45, lw=0,
                        label="violation (closer than 8 m)")
    ax_stl.axhline(0, color=VIOLATION, ls="--", lw=1)
    ax_stl.axvline(attack_start, color=ATTACK_RED, lw=1, ls=":")
    ax_stl.text(attack_start, ax_stl.get_ylim()[1], " attack starts", color=ATTACK_RED, fontsize=7, va="top")
    ax_stl.axvspan(*link_down, color="#F4A261", alpha=0.12, lw=0)
    ax_stl.text(sum(link_down) / 2, ax_stl.get_ylim()[0], "link down", color="#F4A261", fontsize=7,
                ha="center", va="bottom")
    ax_stl.set_xlim(times[0], times[-1])
    ax_stl.set_xlabel("time (s)", color=MUTED, fontsize=8)
    ax_stl.set_ylabel("rho (m)", color=MUTED, fontsize=8)
    ax_stl.legend(loc="upper right", fontsize=7, frameon=False, labelcolor=TEXT)
    stl_cursor = ax_stl.axvline(0, color="white", lw=1.2)
    stl_trace, = ax_stl.plot([], [], color="#2EC4B6", lw=1.6)
    stl_text = ax_stl.text(0.01, 0.04, "", transform=ax_stl.transAxes, color=TEXT, fontsize=8,
                           bbox=dict(boxstyle="round,pad=0.4", fc="#0B0F15", ec=GRID, alpha=0.9))

    type_cols = np.array([TYPE_STYLE.get(types[i], ("#AAAAAA", ""))[0] for i in ids])
    layer_cols = np.array(LAYER_COLOURS)
    total_viol = np.cumsum(stl_rho < 0)
    n_frames = len(frames)
    frame_no = {k: n for n, k in enumerate(frames)}

    legend3 = [Line2D([], [], marker="o", ls="", mfc=col, mec="white", ms=7, label=lab)
               for col, lab in TYPE_STYLE.values()]
    legend3 += [Line2D([], [], marker="X", ls="", color=ATTACK_RED, ms=9, label="attacker (true)"),
                Line2D([], [], marker="o", ls="", mfc="none", mec=ATTACK_RED, ms=9, label="fake broadcast"),
                Line2D([], [], color=VIOLATION, lw=2, label=f"same-layer pair < {d_min:.0f} m")]
    fig.legend(handles=legend3, loc="lower left", bbox_to_anchor=(0.02, 0.005), ncol=6, fontsize=8,
               frameon=False, labelcolor=TEXT)

    def draw(k: int):
        t = float(times[k])
        xy, lay = pos[k], layers[k]
        alt = lay * layer_h
        states = [AgentState(id=aid, type=AgentType[types[aid]],
                             position=[xy[j, 0], xy[j, 1], float(lay[j])], altitude_layer=int(lay[j]))
                  for j, aid in enumerate(ids)]
        atk = inject_attack(states, attack_cfg, t)
        attacker = atk.malicious[0] if atk.malicious else None

        # banners
        title.set_text(f"MASooda 2.5D  t = {t:6.1f} s")
        if attacker is not None:
            banner_attack.set_text(f"ATTACK: drone {attacker} lies")
            banner_attack.set_color("white")
            banner_attack.get_bbox_patch().set_facecolor(ATTACK_RED)
        else:
            banner_attack.set_text(f"Attack: starts at {attack_start:.0f} s")
            banner_attack.set_color(MUTED)
            banner_attack.get_bbox_patch().set_facecolor("#222")
        if link_down[0] <= t < link_down[1]:
            banner_link.set_text("LINK DOWN: cached directive")
            banner_link.set_color("black")
            banner_link.get_bbox_patch().set_facecolor("#F4A261")
        else:
            banner_link.set_text("Overseer link: up")
            banner_link.set_color(MUTED)
            banner_link.get_bbox_patch().set_facecolor("#222")
        banner_layers.set_text("  ".join(f"L{layer}: {int(np.sum(lay == layer))}" for layer in range(num_layers)))

        # 3D scene
        for art in dyn3:
            art.remove()
        dyn3.clear()
        stems = np.stack([np.stack([xy[:, 0], xy[:, 1], alt], axis=1),
                          np.stack([xy[:, 0], xy[:, 1], np.zeros(len(ids))], axis=1)], axis=1)
        dyn3.append(ax3.add_collection3d(Line3DCollection(stems, colors=type_cols, linewidths=0.4, alpha=0.35)))
        dyn3.append(ax3.scatter(xy[:, 0], xy[:, 1], alt, c=type_cols, s=22, edgecolors="white", linewidths=0.5,
                                depthshade=False))

        d = np.linalg.norm(xy[:, None, :] - xy[None, :, :], axis=-1)
        same_layer = lay[:, None] == lay[None, :]
        iu = np.triu_indices(len(ids), 1)
        close = np.where((d[iu] < d_min) & same_layer[iu])[0]
        for c in close:
            i, j = iu[0][c], iu[1][c]
            (ln,) = ax3.plot(xy[[i, j], 0], xy[[i, j], 1], alt[[i, j]], color=VIOLATION, lw=3)
            dyn3.append(ln)

        if attacker is not None:
            ai = idx_of[attacker]
            fake = np.asarray(atk.falsified[attacker][:2])
            a_alt = alt[ai]
            dyn3.append(ax3.scatter([xy[ai, 0]], [xy[ai, 1]], [a_alt], marker="X", s=130, c=ATTACK_RED,
                                    edgecolors="white", depthshade=False))
            dyn3.append(ax3.scatter([fake[0]], [fake[1]], [a_alt], marker="o", s=130, facecolors="none",
                                    edgecolors=ATTACK_RED, linewidths=2, depthshade=False))
            (ln,) = ax3.plot([xy[ai, 0], fake[0]], [xy[ai, 1], fake[1]], [a_alt, a_alt], ls="--", color=ATTACK_RED,
                             lw=1.3)
            dyn3.append(ln)
            dyn3.append(ax3.text(fake[0], fake[1], a_alt + 0.5 * layer_h, f"drone {attacker}: fake position",
                                 color=ATTACK_RED, fontsize=8, fontweight="bold", ha="center"))
        progress = frame_no[k] / max(1, n_frames - 1)
        ax3.view_init(elev=22, azim=-70 + 30 * progress)

        # side view
        sc_side.set_offsets(np.column_stack([xy[:, 0], alt]))
        sc_side.set_color(type_cols)
        recent = layers[max(0, k - lag): k + 1]
        changed = recent.min(axis=0) != recent.max(axis=0)
        ring_side.set_offsets(np.column_stack([xy[changed, 0], alt[changed]]) if changed.any() else np.empty((0, 2)))
        if attacker is not None:
            ai = idx_of[attacker]
            atk_side.set_offsets([[xy[ai, 0], alt[ai]]])
            atk_top.set_offsets([xy[ai]])
        else:
            atk_side.set_offsets(np.empty((0, 2)))
            atk_top.set_offsets(np.empty((0, 2)))

        # top-down view
        sc_top.set_offsets(xy)
        sc_top.set_color(layer_cols[np.minimum(lay, len(layer_cols) - 1)])
        sc_top.set_edgecolors("white")

        # STL panel
        m = stl_t <= t + 1e-9
        stl_cursor.set_xdata([t, t])
        stl_trace.set_data(stl_t[m], stl_rho[m])
        if m.any():
            r = float(stl_rho[m][-1])
            status = "SAFE" if r >= 0 else "VIOLATION"
            stl_text.set_text(f"rho = {r:+.2f} m -> {status}\n"
                              f"closest = {r + d_min:.2f} m  viol. ticks: {int(total_viol[m][-1])}")
            stl_text.get_bbox_patch().set_edgecolor(VIOLATION if r < 0 else "#2EC4B6")
        return []

    anim = FuncAnimation(fig, draw, frames=frames, interval=1000 / args.fps, blit=False)
    if args.mp4:
        out = Path(args.out) if args.out else run_dir / "mvp_visual_25d.mp4"
        anim.save(out, writer=FFMpegWriter(fps=args.fps, bitrate=2400))
    else:
        out = Path(args.out) if args.out else run_dir / "mvp_visual_25d.gif"
        anim.save(out, writer=PillowWriter(fps=args.fps))
    plt.close(fig)
    print(f"Saved {out} ({n_frames} frames)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
