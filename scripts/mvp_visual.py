"""Labelled MVP visualisation: airspace overview, attacker close-up and live STL panel.

Reads the files written by ``python main.py --scenario mvp`` (trajectory.csv and
stl_robustness.csv) and replays the run. Nothing is re-simulated: the falsified
broadcast of the malicious drone is recomputed with the same deterministic
inject_attack() call the engine used, and the defence check (reported range vs
sensed range) is recomputed from the true positions.

Usage (from the repo root, after running main.py):
    python scripts/mvp_visual.py                       # whole run -> outputs/mvp/mvp_visual.gif
    python scripts/mvp_visual.py --start 50 --end 130  # only the interesting part
    python scripts/mvp_visual.py --mp4                 # MP4 instead of GIF (needs ffmpeg)
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
from matplotlib.patches import Circle, Rectangle

from config.load_config import get_config
from resilience.attack import inject_attack
from simulation.schema import AgentState, AgentType

TYPE_STYLE = {
    "EMERGENCY": ("#E63946", "Emergency"),
    "EVTOL": ("#4CC9F0", "eVTOL"),
    "DELIVERY": ("#E9C46A", "Delivery"),
}
BG, PANEL, GRID, TEXT, MUTED = "#0F131A", "#171C26", "#2A3140", "#F1F5F9", "#94A3B8"
ATTACK_RED, CAUGHT_GREEN, FOOLED_ORANGE, VIOLATION = "#FF2E63", "#2EC4B6", "#FF9F1C", "#FF4D4D"


def load_run(run_dir: Path):
    """Return times, ids, positions (T,N,2), types, plus the STL series."""
    rows_by_t: dict[float, dict[int, tuple[float, float]]] = defaultdict(dict)
    types: dict[int, str] = {}
    with open(run_dir / "trajectory.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            t, aid = round(float(r["t"]), 3), int(r["agent_id"])
            rows_by_t[t][aid] = (float(r["x"]), float(r["y"]))
            types[aid] = r["type"].split(".")[-1].upper()
    times = np.array(sorted(rows_by_t))
    ids = sorted(types)
    pos = np.array([[rows_by_t[t][i] for i in ids] for t in times], dtype=float)

    stl_t, stl_rho = [], []
    with open(run_dir / "stl_robustness.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            stl_t.append(float(r["t"]))
            stl_rho.append(float(r["rho"]))
    return times, ids, pos, types, np.array(stl_t), np.array(stl_rho)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", default="outputs/mvp", help="folder written by main.py")
    ap.add_argument("--out", default=None, help="output file (default <run>/mvp_visual.gif or .mp4)")
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--end", type=float, default=None)
    ap.add_argument("--step", type=float, default=0.5, help="simulated seconds per frame")
    ap.add_argument("--fps", type=int, default=12)
    ap.add_argument("--mp4", action="store_true")
    ap.add_argument("--link-down", type=float, nargs=2, default=[90.0, 120.0], metavar=("START", "END"))
    args = ap.parse_args(argv)

    cfg = get_config()
    run_dir = Path(args.run)
    times, ids, pos, types, stl_t, stl_rho = load_run(run_dir)
    idx_of = {aid: k for k, aid in enumerate(ids)}

    d_min = float(cfg["safety"]["minimum_separation_meters"])
    comm_r = float(cfg["communication"]["radius_meters"])
    tol = float(cfg["resilience"].get("range_tolerance_meters", 3.0))
    corr = cfg["corridors"]
    spacing, width, count = float(corr["centerline_spacing_meters"]), float(corr["width_meters"]), int(corr["count"])
    length = float(corr["length_meters"])
    merge_zone, entry_zone, exit_zone = corr["merge_zone_x_meters"], corr["entry_zone_x_meters"], corr["exit_zone_x_meters"]
    attack_cfg = {**cfg["attack"], "enabled": True}
    attack_start = float(attack_cfg["start_time_seconds"])
    link_down = tuple(args.link_down)

    dt = float(times[1] - times[0])
    every = max(1, int(round(args.step / dt)))
    end = args.end if args.end is not None else float(times[-1])
    frames = [k for k in range(0, len(times), every) if args.start - 1e-9 <= times[k] <= end + 1e-9]

    # ---------- figure layout ----------
    fig = plt.figure(figsize=(16, 9), dpi=90, facecolor=BG)
    gs = fig.add_gridspec(2, 2, height_ratios=[1.15, 1], width_ratios=[1, 1.25], hspace=0.28, wspace=0.12,
                          left=0.05, right=0.98, top=0.90, bottom=0.07)
    ax_map = fig.add_subplot(gs[0, :])
    ax_zoom = fig.add_subplot(gs[1, 0])
    ax_stl = fig.add_subplot(gs[1, 1])
    for ax in (ax_map, ax_zoom, ax_stl):
        ax.set_facecolor(PANEL)
        ax.tick_params(colors=MUTED, labelsize=8)
        for s in ax.spines.values():
            s.set_color(GRID)

    title = fig.text(0.05, 0.955, "", color=TEXT, fontsize=15, fontweight="bold")
    banner_attack = fig.text(0.40, 0.955, "", fontsize=11, fontweight="bold",
                             bbox=dict(boxstyle="round,pad=0.35", fc="#222", ec="none"))
    banner_link = fig.text(0.72, 0.955, "", fontsize=11, fontweight="bold",
                           bbox=dict(boxstyle="round,pad=0.35", fc="#222", ec="none"))

    # ---------- static map elements ----------
    y_lo, y_hi = -width, (count - 1) * spacing + width
    ax_map.set_xlim(-20, length + 120)
    ax_map.set_ylim(y_lo - 8, y_hi + 8)
    ax_map.set_xlabel("x: along the corridors (m)", color=MUTED, fontsize=9)
    ax_map.set_ylabel("y (m)", color=MUTED, fontsize=9)
    for zone, label, col in ((entry_zone, "ENTRY", "#3A86FF"), (merge_zone, "MERGE ZONE\n(ADMM active)", "#8338EC"),
                             (exit_zone, "EXIT", "#06D6A0")):
        ax_map.axvspan(zone[0], zone[1], color=col, alpha=0.10, lw=0)
        ax_map.text((zone[0] + zone[1]) / 2, y_hi + 4, label, color=col, ha="center", va="bottom", fontsize=8,
                     fontweight="bold")
    for c in range(count):
        yc = c * spacing
        ax_map.add_patch(Rectangle((0, yc - width / 2), length, width, fc="#232B3A", ec="#3B4559", lw=1, zorder=0))
        ax_map.plot([0, length], [yc, yc], ls=":", lw=0.8, color="#4B5568", zorder=0)
        ax_map.text(4, yc + width / 2 - 1.5, f"Corridor {c}", color=MUTED, fontsize=8, ha="left", va="top")

    legend_items = [Line2D([], [], marker="o", ls="", mfc=col, mec="white", ms=8, label=lab)
                    for col, lab in TYPE_STYLE.values()]
    legend_items += [
        Line2D([], [], marker="X", ls="", color=ATTACK_RED, ms=10, label="Drone 5 (attacker) true position"),
        Line2D([], [], marker="o", ls="", mfc="none", mec=ATTACK_RED, ms=10, label="Drone 5 fake broadcast"),
        Line2D([], [], color=VIOLATION, lw=2, label=f"Pair closer than {d_min:.0f} m"),
        Line2D([], [], marker="x", ls="", color="#CBD5E1", ms=7, label="Outside its corridor"),
    ]
    ax_map.legend(handles=legend_items, loc="upper center", bbox_to_anchor=(0.5, -0.13), ncol=8, fontsize=8,
                  frameon=False, labelcolor=TEXT)

    sc_map = ax_map.scatter([], [], s=34, edgecolors="white", linewidths=0.5, zorder=3)
    out_mark = ax_map.scatter([], [], marker="x", s=55, c="#CBD5E1", linewidths=1.2, zorder=4)
    atk_true_map = ax_map.scatter([], [], marker="X", s=140, c=ATTACK_RED, edgecolors="white", zorder=6)
    atk_fake_map = ax_map.scatter([], [], marker="o", s=140, facecolors="none", edgecolors=ATTACK_RED, lw=2, zorder=6)
    atk_line_map, = ax_map.plot([], [], ls="--", color=ATTACK_RED, lw=1.3, zorder=5)
    viol_lines = []
    map_stats = ax_map.text(0.995, 0.03, "", transform=ax_map.transAxes, ha="right", va="bottom", fontsize=9,
                            color=TEXT, bbox=dict(boxstyle="round,pad=0.4", fc="#0B0F15", ec=GRID, alpha=0.9))
    zoom_box = Rectangle((0, 0), 1, 1, fill=False, ec="white", lw=1, ls="--", zorder=7)
    ax_map.add_patch(zoom_box)

    # ---------- static STL panel ----------
    ax_stl.set_title("STL safety monitor:  rho(t) = min distance between any two drones - 8 m",
                     color=TEXT, fontsize=10, loc="left")
    ax_stl.plot(stl_t, stl_rho, color="#64748B", lw=0.8)
    ax_stl.fill_between(stl_t, stl_rho, 0, where=stl_rho < 0, color=VIOLATION, alpha=0.45, lw=0,
                        label="violation (closer than 8 m)")
    ax_stl.axhline(0, color=VIOLATION, ls="--", lw=1)
    ax_stl.axvline(attack_start, color=ATTACK_RED, lw=1, ls=":")
    ax_stl.text(attack_start, ax_stl.get_ylim()[1], " attack starts", color=ATTACK_RED, fontsize=8, va="top")
    ax_stl.axvspan(*link_down, color="#F4A261", alpha=0.12, lw=0)
    ax_stl.text(sum(link_down) / 2, ax_stl.get_ylim()[0], "overseer link down", color="#F4A261", fontsize=8,
                ha="center", va="bottom")
    ax_stl.set_xlim(times[0], times[-1])
    ax_stl.set_xlabel("time (s)", color=MUTED, fontsize=9)
    ax_stl.set_ylabel("rho (m)", color=MUTED, fontsize=9)
    ax_stl.legend(loc="upper right", fontsize=8, frameon=False, labelcolor=TEXT)
    stl_cursor = ax_stl.axvline(0, color="white", lw=1.2)
    stl_trace, = ax_stl.plot([], [], color="#2EC4B6", lw=1.6)
    stl_text = ax_stl.text(0.01, 0.04, "", transform=ax_stl.transAxes, color=TEXT, fontsize=9,
                           bbox=dict(boxstyle="round,pad=0.4", fc="#0B0F15", ec=GRID, alpha=0.9))

    type_cols = np.array([TYPE_STYLE.get(types[i], ("#AAAAAA", ""))[0] for i in ids])
    centres = np.array([c * spacing for c in range(count)])
    total_viol = np.cumsum(stl_rho < 0)

    def draw(k: int):
        t = float(times[k])
        xy = pos[k]
        states = [AgentState(id=aid, type=AgentType[types[aid]], position=[xy[j, 0], xy[j, 1], 0.0])
                  for j, aid in enumerate(ids)]
        atk = inject_attack(states, attack_cfg, t)
        attacker = atk.malicious[0] if atk.malicious else None
        attacker_id = attacker if attacker is not None else (5 if 5 in idx_of else ids[0])
        a_xy = xy[idx_of[attacker_id]]

        # header banners
        title.set_text(f"MASooda MVP replay   t = {t:6.1f} s")
        if attacker is not None:
            banner_attack.set_text(f"ATTACK ACTIVE: drone {attacker} lies about its position")
            banner_attack.set_color("white")
            banner_attack.get_bbox_patch().set_facecolor(ATTACK_RED)
        else:
            banner_attack.set_text(f"Attack: not started (begins at {attack_start:.0f} s)")
            banner_attack.set_color(MUTED)
            banner_attack.get_bbox_patch().set_facecolor("#222")
        if link_down[0] <= t < link_down[1]:
            banner_link.set_text("OVERSEER LINK DOWN: drones use last directive")
            banner_link.set_color("black")
            banner_link.get_bbox_patch().set_facecolor("#F4A261")
        else:
            banner_link.set_text("Overseer link: up")
            banner_link.set_color(MUTED)
            banner_link.get_bbox_patch().set_facecolor("#222")

        # main map
        sc_map.set_offsets(xy)
        sc_map.set_color(type_cols)
        sc_map.set_edgecolors("white")
        outside = np.min(np.abs(xy[:, 1:2] - centres[None, :]), axis=1) > width / 2
        out_mark.set_offsets(xy[outside] if outside.any() else np.empty((0, 2)))
        atk_true_map.set_offsets([a_xy])
        if attacker is not None:
            fake = np.asarray(atk.falsified[attacker][:2])
            atk_fake_map.set_offsets([fake])
            atk_line_map.set_data([a_xy[0], fake[0]], [a_xy[1], fake[1]])
        else:
            atk_fake_map.set_offsets(np.empty((0, 2)))
            atk_line_map.set_data([], [])

        for ln in viol_lines:
            ln.remove()
        viol_lines.clear()
        d = np.linalg.norm(xy[:, None, :] - xy[None, :, :], axis=-1)
        iu = np.triu_indices(len(ids), 1)
        close = np.where(d[iu] < d_min)[0]
        for c in close:
            i, j = iu[0][c], iu[1][c]
            (ln,) = ax_map.plot(xy[[i, j], 0], xy[[i, j], 1], color=VIOLATION, lw=2.2, zorder=5)
            viol_lines.append(ln)
            viol_lines.append(ax_map.text(xy[i, 0], xy[i, 1] + 4, f"{d[i, j]:.1f} m", color=VIOLATION, fontsize=7,
                                          ha="center", zorder=6))
        arrived = int(np.sum(pos[: k + 1, :, 0].max(axis=0) >= exit_zone[0]))
        map_stats.set_text(f"pairs < {d_min:.0f} m now: {len(close)}    drones outside corridor: {int(outside.sum())}"
                           f"    arrived: {arrived}/{len(ids)}")

        # zoom around the attacker
        ax_zoom.cla()
        ax_zoom.set_facecolor(PANEL)
        for s in ax_zoom.spines.values():
            s.set_color(GRID)
        ax_zoom.tick_params(colors=MUTED, labelsize=8)
        half = comm_r + 20
        cx, cy = a_xy
        ax_zoom.set_xlim(cx - half, cx + half)
        ax_zoom.set_ylim(cy - half * 0.75, cy + half * 0.75)
        ax_zoom.set_aspect("equal", adjustable="box")
        zoom_box.set_bounds(cx - half, cy - half * 0.75, 2 * half, 1.5 * half)
        for c in range(count):
            yc = c * spacing
            ax_zoom.add_patch(Rectangle((cx - 2 * half, yc - width / 2), 4 * half, width, fc="#232B3A", ec="#3B4559",
                                        lw=1, zorder=0))
        ax_zoom.add_patch(Circle(a_xy, comm_r, fill=False, ec="#64748B", ls=":", lw=1))
        ax_zoom.text(cx, cy + comm_r + 2, f"drone {attacker_id}'s radio range ({comm_r:.0f} m)", color=MUTED,
                     fontsize=7, ha="center")

        near = [j for j in range(len(ids)) if ids[j] != attacker_id and d[idx_of[attacker_id], j] <= comm_r]
        in_view = [j for j in range(len(ids)) if abs(xy[j, 0] - cx) < half and abs(xy[j, 1] - cy) < half]
        ax_zoom.scatter(xy[in_view, 0], xy[in_view, 1], s=70, c=type_cols[in_view], edgecolors="white", lw=0.6,
                        zorder=3)
        caught = fooled = 0
        if attacker is not None:
            fake = np.asarray(atk.falsified[attacker][:2])
            for j in near:
                sensed = float(np.linalg.norm(xy[j] - a_xy))
                claimed = float(np.linalg.norm(xy[j] - fake))
                if abs(claimed - sensed) > tol:
                    caught += 1
                    ax_zoom.scatter(*xy[j], s=260, facecolors="none", edgecolors=CAUGHT_GREEN, lw=2.2, zorder=4)
                else:
                    fooled += 1
                    ax_zoom.scatter(*xy[j], s=260, facecolors="none", edgecolors=FOOLED_ORANGE, lw=2.2, zorder=4)
                ax_zoom.plot([xy[j, 0], fake[0]], [xy[j, 1], fake[1]], color=ATTACK_RED, lw=0.6, alpha=0.5, zorder=2)
            ax_zoom.scatter(*fake, s=320, facecolors="none", edgecolors=ATTACK_RED, lw=2.5, zorder=5)
            ax_zoom.annotate("fake position\n(what drone 5 broadcasts)", fake, xytext=(-10, 14), textcoords="offset points", ha="right",
                             color=ATTACK_RED, fontsize=8, fontweight="bold")
            ax_zoom.annotate("", xy=fake, xytext=a_xy,
                             arrowprops=dict(arrowstyle="->", color=ATTACK_RED, lw=1.5, ls="--"))
            lie = float(np.linalg.norm(fake - a_xy))
            ax_zoom.text((a_xy[0] + fake[0]) / 2, (a_xy[1] + fake[1]) / 2 - 3, f"lie: {lie:.0f} m", color=ATTACK_RED,
                         fontsize=8, ha="center", va="top", fontweight="bold")
        ax_zoom.scatter(*a_xy, marker="X", s=260, c=ATTACK_RED, edgecolors="white", lw=1, zorder=6)
        ax_zoom.annotate(f"drone {attacker_id}\n(true position)", a_xy, xytext=(10, -22), textcoords="offset points",
                         color="white", fontsize=8, fontweight="bold")
        for j in in_view:
            if ids[j] != attacker_id:
                ax_zoom.text(xy[j, 0], xy[j, 1] - 4.5, str(ids[j]), color=MUTED, fontsize=7, ha="center", va="top",
                             clip_on=True)
        if attacker is None:
            sub = (f"Close-up of drone {attacker_id}: honest until t = {attack_start:.0f} s")
        else:
            sub = (f"Defence: {caught} of {len(near)} neighbours caught the lie  "
                   f"(sensed distance does not match the broadcast)")
        ax_zoom.set_title(sub, color=TEXT, fontsize=9.5, loc="left")
        zl = [Line2D([], [], marker="o", ls="", mfc="none", mec=CAUGHT_GREEN, mew=2, ms=11,
                     label="neighbour flagged the lie, uses sensed distance"),
              Line2D([], [], marker="o", ls="", mfc="none", mec=FOOLED_ORANGE, mew=2, ms=11,
                     label="neighbour did not flag it (mismatch under 3 m)")]
        ax_zoom.legend(handles=zl, loc="lower left", fontsize=7, frameon=False, labelcolor=TEXT)

        # STL panel
        m = stl_t <= t + 1e-9
        stl_cursor.set_xdata([t, t])
        stl_trace.set_data(stl_t[m], stl_rho[m])
        if m.any():
            r = float(stl_rho[m][-1])
            status = "SAFE" if r >= 0 else "VIOLATION"
            stl_text.set_text(f"rho = {r:+.2f} m  ->  {status}\n"
                              f"closest pair = {r + d_min:.2f} m   violation ticks so far: {int(total_viol[m][-1])}")
            stl_text.get_bbox_patch().set_edgecolor(VIOLATION if r < 0 else CAUGHT_GREEN)
        return []

    anim = FuncAnimation(fig, draw, frames=frames, interval=1000 / args.fps, blit=False)
    if args.mp4:
        out = Path(args.out) if args.out else run_dir / "mvp_visual.mp4"
        anim.save(out, writer=FFMpegWriter(fps=args.fps, bitrate=2400))
    else:
        out = Path(args.out) if args.out else run_dir / "mvp_visual.gif"
        anim.save(out, writer=PillowWriter(fps=args.fps))
    plt.close(fig)
    print(f"Saved {out}  ({len(frames)} frames)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
