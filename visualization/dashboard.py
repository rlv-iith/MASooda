"""Dual-panel MASooda dashboard (workflow 14.1 / 14.6).

Left: the airspace — corridors with entry / merge / exit zones, agents coloured
by type, the emergency agent highlighted, the malicious agent marked with its
falsified (reported) position drawn as a ghost; a banner with sim time,
architecture, DTC (overseer) link UP/DOWN and directive age.

Right, on one shared time axis: STL robustness ρ(t) with the 0 line; emergency
agent progress and priority compliance; ADMM events (converged / non-converged,
cumulative) with mean iterations per tick; an event strip (attack, link down,
violation).

Modes (scripts/dashboard.py):

* ``--replay RUN_DIR``   render from trajectory.csv + telemetry.csv +
  stl_robustness.csv (written by ``main.py --telemetry`` or by ``--record``)
* ``--record OUT.gif|.mp4``  simulate, save the replay files, render offline
* ``--live``             simulate and update the figure while it runs

All numbers come from the simulation outputs: robustness from the STL monitor,
compliance from ``simulation.priority_metrics.PriorityLogger``, ADMM and link
status from ``simulation.telemetry``; the ghost position is recomputed with
``resilience.attack.inject_attack`` (a pure function). Nothing here changes a
simulation. Settings: config ``visualization.dashboard``.
"""

from __future__ import annotations

import argparse
import copy
import csv
import dataclasses
import json
import math
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from typing import Any, Sequence

import matplotlib
import numpy as np

from config.load_config import get_config

REPO_ROOT = Path(__file__).resolve().parent.parent


def _dash_cfg() -> dict:
    v = get_config().get("visualization", {}) or {}
    d = dict(v.get("dashboard", {}) or {})
    d.setdefault("refresh_ticks", int(v.get("dashboard_refresh_ticks", 5)))
    return d


# --------------------------------------------------------------------------- data


@dataclasses.dataclass
class RunData:
    """Everything the dashboard draws, indexed by tick k (t[k])."""

    architecture: str
    scenario: str
    t: list = dataclasses.field(default_factory=list)            # (T,)
    ids: list = dataclasses.field(default_factory=list)          # (N,)
    types: list = dataclasses.field(default_factory=list)        # (N,) names
    pos: list = dataclasses.field(default_factory=list)          # T x (N, 2)
    layer: list = dataclasses.field(default_factory=list)        # T x (N,)
    corridor: list = dataclasses.field(default_factory=list)     # T x (N,) (-1 = none)
    rho: list = dataclasses.field(default_factory=list)          # (T,)
    link_up: list = dataclasses.field(default_factory=list)      # (T,) 1 / 0 / nan
    directive_age: list = dataclasses.field(default_factory=list)
    attack_active: list = dataclasses.field(default_factory=list)
    admm_conv: list = dataclasses.field(default_factory=list)    # per tick
    admm_nonconv: list = dataclasses.field(default_factory=list)
    admm_iters: list = dataclasses.field(default_factory=list)   # mean per tick (nan if none)
    compliance: list = dataclasses.field(default_factory=list)   # running PriorityLogger rate
    malicious_ids: list = dataclasses.field(default_factory=list)  # per tick list
    emergency_ids: list = dataclasses.field(default_factory=list)
    attack_cfg: dict | None = None
    d_min: float = 8.0

    def __len__(self) -> int:
        return len(self.t)


class _ComplianceTracker:
    """Running compliance rate of the emergency agent(s) via PriorityLogger (as-is)."""

    def __init__(self, emergency_ids: Sequence[int]):
        from simulation.priority_metrics import PriorityLogger

        self.loggers = [PriorityLogger(int(e)) for e in emergency_ids]

    def update(self, t: float, agents: Sequence[Any]) -> float:
        for lg in self.loggers:
            lg.log_state(t, agents)
        checks = sum(lg.checks for lg in self.loggers)
        return sum(lg.compliant for lg in self.loggers) / checks if checks else float("nan")


def _agents_ns(ids, pos, corr) -> list[SimpleNamespace]:
    return [SimpleNamespace(id=int(i), position=np.array([p[0], p[1], 0.0]),
                            corridor_assignment=None if c < 0 else int(c)) for i, p, c in zip(ids, pos, corr)]


def _f(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


def load_replay(run_dir: str | Path) -> RunData:
    """Load a run written by ``main.py --telemetry`` or by :func:`simulate`."""
    run_dir = Path(run_dir)
    cfg = get_config()
    info: dict[str, Any] = {}
    if (run_dir / "run_info.json").is_file():
        info = json.loads((run_dir / "run_info.json").read_text(encoding="utf-8"))
    else:
        if (run_dir / "metrics.json").is_file():
            info["architecture"] = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8")).get(
                "architecture", "hierarchical")
        if (run_dir / "run_row.csv").is_file():
            with open(run_dir / "run_row.csv", newline="", encoding="utf-8") as f:
                rr = next(csv.DictReader(f))
            info["scenario"] = rr.get("scenario", "")
            if rr.get("attack_enabled") == "True":
                info["attack_cfg"] = {**cfg.get("attack", {}), "enabled": True}
    data = RunData(architecture=str(info.get("architecture", "hierarchical")),
                   scenario=str(info.get("scenario", "")), attack_cfg=info.get("attack_cfg"),
                   d_min=float(cfg["safety"]["minimum_separation_meters"]))

    # trajectory.csv: t, agent_id, x, y, vx, vy, corridor, type, layer
    frames: dict[float, list[dict]] = {}
    with open(run_dir / "trajectory.csv", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            frames.setdefault(round(float(r["t"]), 6), []).append(r)
    times = sorted(frames)
    first = frames[times[0]]
    data.ids = [int(r["agent_id"]) for r in first]
    data.types = [str(r["type"]).split(".")[-1].upper() for r in first]
    order = {aid: i for i, aid in enumerate(data.ids)}
    for t in times:
        rows = sorted(frames[t], key=lambda r: order[int(r["agent_id"])])
        data.t.append(t)
        data.pos.append(np.array([[float(r["x"]), float(r["y"])] for r in rows]))
        data.layer.append(np.array([int(float(r["layer"])) for r in rows]))
        data.corridor.append(np.array([-1 if r["corridor"] in ("", "None") else int(float(r["corridor"]))
                                       for r in rows]))

    rho_by_t: dict[float, float] = {}
    if (run_dir / "stl_robustness.csv").is_file():
        with open(run_dir / "stl_robustness.csv", newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                rho_by_t[round(float(r["t"]), 6)] = _f(r["rho"])
    tel_by_t: dict[float, dict] = {}
    if (run_dir / "telemetry.csv").is_file():
        with open(run_dir / "telemetry.csv", newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                tel_by_t[round(float(r["t"]), 6)] = r
    data.emergency_ids = [int(i) for i, ty in zip(data.ids, data.types) if ty == "EMERGENCY"]
    tracker = _ComplianceTracker(data.emergency_ids)
    for k, t in enumerate(times):
        data.rho.append(rho_by_t.get(t, float("nan")))
        tel = tel_by_t.get(t)
        if tel is None:  # t = 0 has no telemetry row
            data.link_up.append(float("nan"))
            data.directive_age.append(float("nan"))
            data.attack_active.append(False)
            data.admm_conv.append(0)
            data.admm_nonconv.append(0)
            data.admm_iters.append(float("nan"))
            data.malicious_ids.append([])
        else:
            lu = tel["overseer_link_up"]
            data.link_up.append(1.0 if lu == "True" else (0.0 if lu == "False" else float("nan")))
            data.directive_age.append(_f(tel["directive_age_s"]))
            data.attack_active.append(tel["attack_active"] == "True")
            data.admm_conv.append(int(tel["admm_converged_tick"]))
            data.admm_nonconv.append(int(tel["admm_nonconverged_tick"]))
            data.admm_iters.append(_f(tel["admm_iterations_mean"]))
            data.malicious_ids.append([int(x) for x in tel["malicious_ids"].split(";") if x])
        data.compliance.append(tracker.update(t, _agents_ns(data.ids, data.pos[k], data.corridor[k])))
    return data


# --------------------------------------------------------------------------- simulation


def scenario_settings(scenario: str, cfg: dict | None = None) -> dict:
    """Attack / link / emergency settings for 'nominal', 'mvp' (as in main.py) or 'demo'."""
    cfg = cfg or get_config()
    attack = dict(cfg.get("attack", {}))
    if scenario == "nominal":
        return {"attack_cfg": {**attack, "enabled": False}, "link_cfg": {"enabled": False}, "inject_emergency": False}
    if scenario == "mvp":
        lf = cfg["overseer"]["link_failure"]
        return {"attack_cfg": {**attack, "enabled": True},
                "link_cfg": {"enabled": True, "down_start_seconds": float(lf["down_start_seconds"]),
                             "down_end_seconds": float(lf["down_end_seconds"])},
                "inject_emergency": False}
    if scenario == "demo":
        demo = cfg["experiments"]["week6"]["demo_scenario"]
        return {"attack_cfg": {**attack, "enabled": True, "start_time_seconds": float(demo["attack_start_s"]),
                               "offset_magnitude_meters": float(demo.get("attack_offset_m",
                                                                         attack["offset_magnitude_meters"]))},
                "link_cfg": {"enabled": True, "down_start_seconds": float(demo["link_down_s"][0]),
                             "down_end_seconds": float(demo["link_down_s"][1])},
                "inject_emergency": bool(demo.get("inject_emergency", True))}
    raise ValueError(f"unknown scenario {scenario!r}")


class _LiveFeed:
    """Logger + telemetry sink that appends to a RunData and refreshes a live dashboard."""

    def __init__(self, data: RunData, dash: "Dashboard | None", refresh_ticks: int, on_refresh=None):
        self.data = data
        self.dash = dash
        self.refresh = max(1, int(refresh_ticks))
        self.on_refresh = on_refresh
        self.tracker: _ComplianceTracker | None = None
        self.d_min = data.d_min
        self.refresh_times: list[float] = []

    def log_state(self, t: float, agents: Sequence[Any]) -> None:
        d = self.data
        if not d.ids:
            d.ids = [int(a.id) for a in agents]
            d.types = [getattr(a.type, "name", str(a.type)).upper() for a in agents]
            d.emergency_ids = [int(a.id) for a in agents if getattr(a.type, "name", "") == "EMERGENCY"]
            self.tracker = _ComplianceTracker(d.emergency_ids)
        p = np.array([[float(a.position[0]), float(a.position[1])] for a in agents])
        d.t.append(float(t))
        d.pos.append(p)
        d.layer.append(np.array([int(a.altitude_layer) for a in agents]))
        d.corridor.append(np.array([-1 if a.corridor_assignment is None else int(a.corridor_assignment)
                                    for a in agents]))
        diff = p[:, None, :] - p[None, :, :]
        dist = np.sqrt((diff ** 2).sum(-1))
        np.fill_diagonal(dist, np.inf)
        d.rho.append(float(dist.min()) - self.d_min if len(p) > 1 else float("inf"))
        d.compliance.append(self.tracker.update(t, agents) if self.tracker else float("nan"))
        if len(d.t) == 1:  # t = 0: no telemetry yet
            d.link_up.append(float("nan"))
            d.directive_age.append(float("nan"))
            d.attack_active.append(False)
            d.admm_conv.append(0)
            d.admm_nonconv.append(0)
            d.admm_iters.append(float("nan"))
            d.malicious_ids.append([])

    def on_tick(self, t: float, info: dict) -> None:
        d = self.data
        lu = info["overseer_link_up"]
        d.link_up.append(float("nan") if lu is None else (1.0 if lu else 0.0))
        d.directive_age.append(float(info["directive_age_s"]))
        d.attack_active.append(bool(info["attack_active"]))
        d.admm_conv.append(int(info["admm_converged_tick"]))
        d.admm_nonconv.append(int(info["admm_nonconverged_tick"]))
        it = info["admm_iterations"]
        d.admm_iters.append(float(np.mean(it)) if it else float("nan"))
        d.malicious_ids.append(list(info["malicious_ids"]))
        k = len(d.t) - 1
        if self.dash is not None and k % self.refresh == 0:
            t0 = time.perf_counter()
            self.dash.update(k)
            if self.on_refresh is not None:
                self.on_refresh()
            self.refresh_times.append(time.perf_counter() - t0)


def simulate(architecture: str, scenario: str, n_agents: int, seed: int, duration_s: float,
             run_dir: str | Path | None = None, live_feed: _LiveFeed | None = None) -> RunData | Path:
    """Run one simulation; save trajectory/telemetry/STL CSVs + run_info.json to ``run_dir``.

    With ``live_feed`` the feed receives every tick (live mode). Returns the
    run directory (or the live RunData when no run_dir is given).
    """
    from experiments.runner import get_runner
    from local_behavior.boids import reset_local_behavior_cache
    from simulation.logger import TrajectoryLogger
    from simulation.overseer import reset_default_overseer
    from simulation.scenario import make_initial_agents
    from simulation.telemetry import TelemetryRecorder
    from verification.live_monitor import LiveSTLMonitor

    reset_default_overseer()
    reset_local_behavior_cache()
    s = scenario_settings(scenario)
    agents = make_initial_agents(n_agents, seed=seed)
    if s["inject_emergency"]:
        from simulation.priority_metrics import inject_emergency

        agents, _ = inject_emergency(agents)
    traj = TrajectoryLogger()
    monitor = LiveSTLMonitor(console_every_seconds=1e9)
    rec = TelemetryRecorder()

    class _Tee:
        def on_tick(self, t, info):
            rec.on_tick(t, info)
            if live_feed is not None:
                live_feed.on_tick(t, info)

    loggers = [traj, monitor] + ([live_feed] if live_feed is not None else [])
    get_runner(architecture)(agents, duration_s=duration_s, loggers=loggers, attack_config=s["attack_cfg"],
                             overseer_link_config=s["link_cfg"], telemetry=_Tee())
    if run_dir is None:
        return live_feed.data if live_feed is not None else Path(".")
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    traj.to_csv(run_dir / "trajectory.csv")
    monitor.to_csv(run_dir / "stl_robustness.csv")
    rec.to_csv(run_dir / "telemetry.csv")
    with open(run_dir / "run_info.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump({"architecture": architecture, "scenario": scenario, "n_agents": n_agents, "seed": seed,
                   "duration_s": duration_s, "attack_cfg": s["attack_cfg"] if s["attack_cfg"].get("enabled") else None,
                   "link_cfg": s["link_cfg"], "inject_emergency": s["inject_emergency"]}, f, indent=2, default=str)
    return run_dir


# --------------------------------------------------------------------------- figure


class Dashboard:
    """The dual-panel figure. ``update(k)`` redraws tick k using artist updates only."""

    def __init__(self, data: RunData, t_max: float | None = None, live: bool = False):
        import matplotlib.pyplot as plt
        from matplotlib.collections import LineCollection
        from matplotlib.gridspec import GridSpec
        from matplotlib.patches import Rectangle

        from simulation.environment import build_corridors
        from visualization.plots import apply_style, display_label, event_color, type_color

        self.data = data
        self.live = live
        cfg = get_config()
        dc = _dash_cfg()
        apply_style()
        self._type_color = type_color
        self.t_max = float(t_max if t_max is not None else (data.t[-1] if data.t else 1.0))
        self.fig = plt.figure(figsize=tuple(dc.get("figure_size", (15.0, 8.0))), dpi=int(dc.get("dpi", 100)))
        gs = GridSpec(4, 2, figure=self.fig, width_ratios=[1.45, 1.0], height_ratios=[2.0, 1.4, 1.4, 0.75],
                      left=0.05, right=0.96, top=0.88, bottom=0.07, wspace=0.16, hspace=0.32)
        ax = self.ax_map = self.fig.add_subplot(gs[:, 0])
        self.ax_rho = self.fig.add_subplot(gs[0, 1])
        self.ax_em = self.fig.add_subplot(gs[1, 1], sharex=self.ax_rho)
        self.ax_admm = self.fig.add_subplot(gs[2, 1], sharex=self.ax_rho)
        self.ax_ev = self.fig.add_subplot(gs[3, 1], sharex=self.ax_rho)

        # ---- airspace
        corr = build_corridors()
        cc = cfg["corridors"]
        length = float(cc["length_meters"])
        for zone, key, col in (("entry", "entry_zone_x_meters", "#2CA02C"), ("merge", "merge_zone_x_meters", "#FF7F0E"),
                               ("exit", "exit_zone_x_meters", "#1F77B4")):
            x0, x1 = cc[key]
            ax.axvspan(x0, x1, color=col, alpha=0.10, linewidth=0)
            ax.text((x0 + x1) / 2, corr[-1].y_max + 14, f"{zone} zone", ha="center", fontsize=8, color=col)
        for c in corr:
            ax.add_patch(Rectangle((c.x_min, c.y_min), c.x_max - c.x_min, c.y_max - c.y_min, facecolor="#F2F2F2",
                                   edgecolor="#AAAAAA", linewidth=0.8, zorder=0))
            ax.plot([c.x_min, c.x_max], [c.y_center] * 2, color="#CCCCCC", linestyle="--", linewidth=0.7, zorder=0)
            ax.text(-15, c.y_center, f"C{c.id}", ha="right", va="center", fontsize=8, color="#555555")
        ax.set_xlim(-45, length + 25)
        ax.set_ylim(corr[0].y_min - 25, corr[-1].y_max + 25)
        ax.set_aspect("auto")
        ax.set_xlabel("x (m) — along the corridors")
        ax.set_ylabel("y (m)")
        ax.grid(False)
        n = len(data.ids)
        colors = [type_color(ty) for ty in data.types]
        p0 = data.pos[0] if data.pos else np.zeros((n, 2))
        self.sc = ax.scatter(p0[:, 0], p0[:, 1], s=26, c=colors, edgecolors="black", linewidths=0.4, zorder=3)
        self.em_ring = ax.scatter([], [], s=190, facecolors="none", edgecolors=type_color("EMERGENCY"),
                                  linewidths=2.2, zorder=4)
        self.mal = ax.scatter([], [], s=90, marker="X", color=event_color("attack"), zorder=5)
        self.ghost = ax.scatter([], [], s=70, facecolors="none", edgecolors=event_color("attack"),
                                linestyles="--", linewidths=1.4, zorder=5)
        self.ghost_lines = LineCollection([], colors=event_color("attack"), linestyles="dotted", linewidths=1.2,
                                          zorder=4)
        ax.add_collection(self.ghost_lines)
        from matplotlib.lines import Line2D

        handles = [Line2D([], [], marker="o", linestyle="none", markerfacecolor=type_color(ty), markeredgecolor="black",
                          label=ty.capitalize()) for ty in ("EMERGENCY", "EVTOL", "DELIVERY")]
        handles += [Line2D([], [], marker="o", linestyle="none", markerfacecolor="none", markersize=11,
                           markeredgecolor=type_color("EMERGENCY"), markeredgewidth=2, label="emergency (highlighted)"),
                    Line2D([], [], marker="X", linestyle="none", color=event_color("attack"), label="malicious (true)"),
                    Line2D([], [], marker="o", linestyle="none", markerfacecolor="none",
                           markeredgecolor=event_color("attack"), label="falsified report (ghost)")]
        ax.legend(handles=handles, loc="lower right", fontsize=7, ncol=2, framealpha=0.9)
        self.layer_txt = ax.text(0.01, 0.99, "", transform=ax.transAxes, va="top", fontsize=8,
                                 bbox=dict(facecolor="white", alpha=0.8, edgecolor="#CCCCCC"))

        # ---- banner
        self.banner = self.fig.text(0.05, 0.955, "", fontsize=13, fontweight="bold", va="center")
        self.link_txt = self.fig.text(0.62, 0.955, "", fontsize=13, fontweight="bold", va="center",
                                      bbox=dict(boxstyle="round,pad=0.3", facecolor="#2CA02C", edgecolor="none"),
                                      color="white")
        self.age_txt = self.fig.text(0.78, 0.955, "", fontsize=11, va="center")
        self.sub_txt = self.fig.text(0.05, 0.915, "", fontsize=9, color="#444444", va="center")
        self._display_label = display_label

        # ---- right panels
        thr = "#000000"
        r = self.ax_rho
        r.axhline(0.0, color=thr, linestyle="--", linewidth=1.0)
        self.rho_line, = r.plot([], [], color="#0072B2", linewidth=1.3)
        r.set_ylabel("ρ (m)")
        r.set_title(f"STL robustness  ρ(t) = min d_ij − d_min  (d_min = {data.d_min:g} m)", fontsize=9, loc="left")
        finite = np.array([x for x in data.rho if math.isfinite(x)])
        if finite.size and not live:
            r.set_ylim(min(-1.0, finite.min() - 1.0), finite.max() + 1.0)
        else:
            r.set_ylim(-5.0, 30.0)

        e = self.ax_em
        e.set_ylabel("x (m)")
        e.set_title("Emergency agent: progress (solid) vs free-flow (dotted); compliance", fontsize=9, loc="left")
        self.em_lines = []
        self.em_nominal = []
        v = float(cfg["local_behavior"]["v_cruise"])
        self._v = v
        for i, eid in enumerate(data.emergency_ids[:3]):
            ln, = e.plot([], [], color=type_color("EMERGENCY"), linewidth=1.5 - 0.4 * i, label=f"agent {eid}")
            nl, = e.plot([], [], color=type_color("EMERGENCY"), linewidth=0.8, linestyle=":")
            self.em_lines.append((eid, ln))
            self.em_nominal.append((eid, nl))
        e.set_ylim(0, length)
        self.comp_txt = e.text(0.01, 0.95, "", transform=e.transAxes, va="top", fontsize=8,
                               bbox=dict(facecolor="white", alpha=0.85, edgecolor="#CCCCCC"))
        if not data.emergency_ids:
            e.text(0.5, 0.5, "no emergency agent in this run", transform=e.transAxes, ha="center", color="#666666")

        a = self.ax_admm
        self.admm_conv_line, = a.plot([], [], color="#009E73", linewidth=1.4, label="converged (cum.)")
        self.admm_non_line, = a.plot([], [], color="#D55E00", linewidth=1.4, label="non-converged (cum.)")
        a.set_ylabel("events")
        a.set_title("ADMM conflict events (cumulative) and mean iterations per tick", fontsize=9, loc="left")
        self.ax_it = a.twinx()
        self.it_pts = self.ax_it.scatter([], [], s=6, color="#555555", label="mean iterations / tick")
        self.ax_it.set_ylabel("iterations", fontsize=8)
        self.ax_it.grid(False)
        a.legend(loc="upper left", fontsize=7)
        tot_c = int(np.sum(data.admm_conv)) if not live else 10
        tot_n = int(np.sum(data.admm_nonconv)) if not live else 0
        a.set_ylim(0, max(5, tot_c, tot_n) * 1.1)
        its = [x for x in data.admm_iters if math.isfinite(x)]
        self.ax_it.set_ylim(0, (max(its) * 1.15) if its and not live else 60)

        ev = self.ax_ev
        self.ev_img = ev.imshow(np.zeros((3, 2)), aspect="auto", interpolation="nearest",
                                extent=(0, self.t_max, 2.5, -0.5),
                                cmap=matplotlib.colors.ListedColormap(["#FFFFFF", event_color("attack"),
                                                                       event_color("link_down"),
                                                                       event_color("violation")]),
                                vmin=0, vmax=3)
        ev.set_yticks([0, 1, 2])
        ev.set_yticklabels(["attack", "link down", "violation"], fontsize=8)
        ev.set_xlabel("Simulation time (s)")
        ev.grid(False)
        for axx in (self.ax_rho, self.ax_em, self.ax_admm):
            axx.tick_params(labelbottom=False)
        self.ax_rho.set_xlim(0, self.t_max)
        self.cursors = [axx.axvline(0, color="#999999", linewidth=0.8) for axx in
                        (self.ax_rho, self.ax_em, self.ax_admm, self.ax_ev)]
        self.fps_txt = self.fig.text(0.96, 0.015, "", ha="right", fontsize=7, color="#888888")
        if bool((get_config().get("experiments", {}).get("week6", {}) or {}).get("provisional", True)):
            self.fig.text(0.05, 0.015, str((get_config().get("visualization", {}) or {}).get(
                "provisional_footer", "PROVISIONAL - pre-bug-fix results")), fontsize=7, style="italic",
                color=event_color("violation"))

    # ------------------------------------------------------------------ update
    def update(self, k: int) -> list:
        d = self.data
        k = max(0, min(int(k), len(d) - 1))
        t = np.asarray(d.t[: k + 1])
        tk = float(t[-1])
        pos = d.pos[k]
        self.sc.set_offsets(pos)
        em_idx = [d.ids.index(e) for e in d.emergency_ids]
        self.em_ring.set_offsets(pos[em_idx] if em_idx else np.empty((0, 2)))

        mal = d.malicious_ids[k] if k < len(d.malicious_ids) else []
        if mal and d.attack_cfg:
            from resilience.attack import inject_attack

            agents = [SimpleNamespace(id=i, position=np.array([p[0], p[1], 0.0]),
                                      type=SimpleNamespace(name=ty), velocity=np.zeros(3))
                      for i, p, ty in zip(d.ids, pos, d.types)]
            for a, ty in zip(agents, d.types):
                from simulation.schema import AgentType

                a.type = AgentType[ty]
            st = inject_attack(agents, d.attack_cfg, tk)
            true_p = np.array([pos[d.ids.index(m)] for m in mal if m in d.ids])
            ghost_p = np.array([np.asarray(st.falsified[m])[:2] for m in mal if m in st.falsified])
            self.mal.set_offsets(true_p if len(true_p) else np.empty((0, 2)))
            self.ghost.set_offsets(ghost_p if len(ghost_p) else np.empty((0, 2)))
            self.ghost_lines.set_segments([[tp, gp] for tp, gp in zip(true_p, ghost_p)])
        elif mal:
            self.mal.set_offsets(np.array([pos[d.ids.index(m)] for m in mal if m in d.ids]))
            self.ghost.set_offsets(np.empty((0, 2)))
            self.ghost_lines.set_segments([])
        else:
            self.mal.set_offsets(np.empty((0, 2)))
            self.ghost.set_offsets(np.empty((0, 2)))
            self.ghost_lines.set_segments([])
        layers = d.layer[k]
        self.layer_txt.set_text("altitude layers: " + ", ".join(
            f"L{l}: {int(np.sum(layers == l))}" for l in sorted(set(layers.tolist()))))

        arch = self._display_label("architecture", d.architecture)
        self.banner.set_text(f"t = {tk:6.1f} s   |   {arch}   |   scenario: {d.scenario or 'n/a'}")
        lu = d.link_up[k]
        if math.isnan(lu):
            self.link_txt.set_text(" DTC link: n/a ")
            self.link_txt.get_bbox_patch().set_facecolor("#7F7F7F")
        elif lu > 0.5:
            self.link_txt.set_text(" DTC link: UP ")
            self.link_txt.get_bbox_patch().set_facecolor("#2CA02C")
        else:
            self.link_txt.set_text(" DTC link: DOWN ")
            self.link_txt.get_bbox_patch().set_facecolor("#B2182B")
        age = d.directive_age[k]
        self.age_txt.set_text(f"directive age: {'n/a' if math.isnan(age) else f'{age:.1f} s'}")
        rho_k = d.rho[k]
        self.sub_txt.set_text(f"N = {len(d.ids)}   ρ = {rho_k:+.2f} m   "
                              f"{'VIOLATION' if rho_k < 0 else 'safe'}   "
                              f"{'attack active: agent ' + ','.join(map(str, mal)) if mal else 'no attack active'}")

        self.rho_line.set_data(t, np.asarray(d.rho[: k + 1]))
        for (eid, ln), (_, nl) in zip(self.em_lines, self.em_nominal):
            j = d.ids.index(eid)
            xs = np.array([p[j, 0] for p in d.pos[: k + 1]])
            ln.set_data(t, xs)
            nl.set_data(t, xs[0] + self._v * (t - t[0]))
        comp = d.compliance[k]
        self.comp_txt.set_text(f"priority compliance so far: {'n/a' if math.isnan(comp) else f'{comp:.2f}'}")
        cc = np.cumsum(d.admm_conv[: k + 1])
        cn = np.cumsum(d.admm_nonconv[: k + 1])
        self.admm_conv_line.set_data(t, cc)
        self.admm_non_line.set_data(t, cn)
        it = np.asarray(d.admm_iters[: k + 1], dtype=float)
        m = np.isfinite(it)
        self.it_pts.set_offsets(np.column_stack([t[m], it[m]]) if m.any() else np.empty((0, 2)))
        img = np.zeros((3, k + 1))
        img[0] = np.where(np.asarray(d.attack_active[: k + 1]), 1, 0)
        img[1] = np.where(np.asarray(d.link_up[: k + 1]) == 0.0, 2, 0)
        img[2] = np.where(np.asarray(d.rho[: k + 1]) < 0, 3, 0)
        self.ev_img.set_data(img)
        self.ev_img.set_extent((0, max(tk, 1e-6), 2.5, -0.5))
        for c in self.cursors:
            c.set_xdata([tk, tk])
        if self.live:
            self._rescale_live(cc, cn, it)
        return [self.sc, self.em_ring, self.mal, self.ghost, self.ghost_lines, self.banner, self.link_txt,
                self.age_txt, self.rho_line, self.admm_conv_line, self.admm_non_line, self.it_pts, self.ev_img]

    def _rescale_live(self, cc, cn, it) -> None:
        rho = np.asarray([x for x in self.data.rho if math.isfinite(x)])
        if rho.size:
            lo, hi = self.ax_rho.get_ylim()
            if rho.min() < lo or rho.max() > hi:
                self.ax_rho.set_ylim(min(lo, rho.min() - 1), max(hi, rho.max() + 1))
        top = max(cc[-1] if len(cc) else 0, cn[-1] if len(cn) else 0)
        if top > self.ax_admm.get_ylim()[1]:
            self.ax_admm.set_ylim(0, top * 1.5)
        fin = it[np.isfinite(it)]
        if fin.size and fin.max() > self.ax_it.get_ylim()[1]:
            self.ax_it.set_ylim(0, fin.max() * 1.3)

    def set_fps(self, fps: float) -> None:
        self.fps_txt.set_text(f"{fps:.1f} fps")


def frame_indices(data: RunData, stride_ticks: int, t_start: float = 0.0, t_end: float | None = None) -> list[int]:
    t = np.asarray(data.t)
    t_end = float(t[-1]) if t_end is None else float(t_end)
    ks = [k for k in range(0, len(t), max(1, int(stride_ticks))) if t_start - 1e-9 <= t[k] <= t_end + 1e-9]
    if ks and ks[-1] != len(t) - 1 and t[-1] <= t_end + 1e-9:
        ks.append(len(t) - 1)
    return ks


def record(data: RunData, out_path: str | Path, frames: Sequence[int] | None = None, fps: int | None = None) -> Path:
    """Render frames to GIF (Pillow) or MP4 (ffmpeg) depending on the extension."""
    import matplotlib.pyplot as plt
    from matplotlib import animation

    dc = _dash_cfg()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    frames = list(frames if frames is not None else frame_indices(data, int(dc.get("frame_stride_ticks", 5))))
    fps = int(fps or dc.get("fps", 10))
    t_lo, t_hi = data.t[frames[0]], data.t[frames[-1]]
    dash = Dashboard(data, t_max=data.t[-1])
    dash.ax_rho.set_xlim(t_lo, max(t_hi, t_lo + 1e-6))
    if out_path.suffix.lower() == ".mp4":
        if not animation.writers.is_available("ffmpeg"):
            out_path = out_path.with_suffix(".gif")
            writer = animation.PillowWriter(fps=fps)
        else:
            writer = animation.FFMpegWriter(fps=fps, bitrate=2400)
    else:
        writer = animation.PillowWriter(fps=fps)
    with writer.saving(dash.fig, str(out_path), dpi=int(dc.get("dpi", 100))):
        for k in frames:
            dash.update(k)
            writer.grab_frame()
    plt.close(dash.fig)
    return out_path


def render_frame(data: RunData, k: int, out_png: str | Path) -> Path:
    import matplotlib.pyplot as plt

    dash = Dashboard(data)
    dash.update(k)
    dash.fig.savefig(out_png, dpi=int(_dash_cfg().get("dpi", 100)))
    plt.close(dash.fig)
    return Path(out_png)


def run_live(architecture: str, scenario: str, n_agents: int, seed: int, duration_s: float,
             show: bool = True, run_dir: str | Path | None = None) -> dict:
    """Simulate with a live-updating dashboard; return measured refresh statistics."""
    import matplotlib.pyplot as plt

    dc = _dash_cfg()
    cfg = get_config()
    s = scenario_settings(scenario)
    data = RunData(architecture=architecture, scenario=scenario,
                   attack_cfg=s["attack_cfg"] if s["attack_cfg"].get("enabled") else None,
                   d_min=float(cfg["safety"]["minimum_separation_meters"]))
    holder: dict[str, Any] = {}

    class _LazyDash:
        """Create the figure on the first refresh, once agent ids/types are known."""

        def update(self, k):
            if "dash" not in holder:
                holder["dash"] = Dashboard(data, t_max=duration_s, live=True)
                if show:
                    plt.show(block=False)
            holder["dash"].update(k)

    def _flush():
        fig = holder["dash"].fig
        if show:
            fig.canvas.draw_idle()
            plt.pause(0.001)
        else:
            fig.canvas.draw()
        if len(feed.refresh_times) >= 2:
            recent = feed.refresh_times[-10:]
            holder["dash"].set_fps(1.0 / max(1e-6, float(np.mean(recent))))

    feed = _LiveFeed(data, _LazyDash(), int(dc.get("refresh_ticks", 5)), on_refresh=_flush)
    t0 = time.perf_counter()
    simulate(architecture, scenario, n_agents, seed, duration_s, run_dir=run_dir, live_feed=feed)
    wall = time.perf_counter() - t0
    n_ref = len(feed.refresh_times)
    stats = {"refreshes": n_ref, "wall_s": wall, "sim_s": duration_s,
             "refreshes_per_wall_s": n_ref / wall if wall > 0 else float("nan"),
             "draw_ms_mean": 1000.0 * float(np.mean(feed.refresh_times)) if n_ref else float("nan"),
             "draw_only_fps": 1.0 / float(np.mean(feed.refresh_times)) if n_ref else float("nan")}
    if "dash" in holder and not show:
        plt.close(holder["dash"].fig)
    elif "dash" in holder:
        # keep the final frame on screen until the presenter closes the window
        holder["dash"].fig.canvas.draw_idle()
        plt.show(block=True)
    return stats


# --------------------------------------------------------------------------- CLI


def main(argv: Sequence[str] | None = None) -> int:
    cfg = get_config()
    sim = cfg["simulation"]
    ap = argparse.ArgumentParser(prog="python scripts/dashboard.py", description=__doc__.split("\n\n")[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--replay", metavar="RUN_DIR", help="render a saved run (main.py --telemetry output)")
    mode.add_argument("--record", metavar="OUT", help="simulate, then render to OUT (.gif or .mp4)")
    mode.add_argument("--live", action="store_true", help="simulate with a live-updating window")
    ap.add_argument("--architecture", default="hierarchical",
                    choices=["hierarchical", "centralized", "decentralized_undefended"])
    ap.add_argument("--scenario", default="mvp", choices=["nominal", "mvp", "demo"])
    ap.add_argument("--agents", type=int, default=int(sim["num_agents"]))
    ap.add_argument("--seed", type=int, default=int(sim["random_seed"]))
    ap.add_argument("--duration", type=float, default=float(sim["duration_seconds"]))
    ap.add_argument("--run-dir", default=None, help="where --record/--live save the replay files")
    ap.add_argument("--out", default=None, help="--replay: output .gif/.mp4 (default <RUN_DIR>/dashboard.gif)")
    ap.add_argument("--t-start", type=float, default=0.0, help="first sim time to render")
    ap.add_argument("--t-end", type=float, default=None, help="last sim time to render")
    ap.add_argument("--stride", type=int, default=None, help="ticks per rendered frame")
    ap.add_argument("--fps", type=int, default=None)
    ap.add_argument("--frame-png", type=float, default=None, help="also save the frame nearest this sim time as PNG")
    ap.add_argument("--headless", action="store_true", help="--live without a window (measures refresh rate)")
    args = ap.parse_args(argv)

    if args.scenario == "demo":
        demo = cfg["experiments"]["week6"]["demo_scenario"]
        if args.agents == int(sim["num_agents"]):
            args.agents = int(demo["n_agents"])
        if args.seed == int(sim["random_seed"]):
            args.seed = int(demo["seed"])
        if args.duration == float(sim["duration_seconds"]):
            args.duration = float(demo["duration_s"])
        args.architecture = str(demo.get("architecture", args.architecture))

    if args.live:
        if args.headless:
            matplotlib.use("Agg")
        stats = run_live(args.architecture, args.scenario, args.agents, args.seed, args.duration,
                         show=not args.headless, run_dir=args.run_dir)
        print(json.dumps(stats, indent=2))
        return 0

    matplotlib.use("Agg")
    stride = args.stride or int(_dash_cfg().get("frame_stride_ticks", 5))
    if args.record:
        run_dir = Path(args.run_dir) if args.run_dir else Path(args.record).with_suffix("").parent / (
            Path(args.record).stem + "_run")
        simulate(args.architecture, args.scenario, args.agents, args.seed, args.duration, run_dir=run_dir)
        data = load_replay(run_dir)
        out = Path(args.record)
    else:
        run_dir = Path(args.replay)
        data = load_replay(run_dir)
        out = Path(args.out) if args.out else run_dir / "dashboard.gif"
    frames = frame_indices(data, stride, args.t_start, args.t_end)
    path = record(data, out, frames, fps=args.fps)
    print(f"[dashboard] {len(frames)} frames -> {path}")
    if args.frame_png is not None:
        k = int(np.argmin(np.abs(np.asarray(data.t) - args.frame_png)))
        png = render_frame(data, k, path.with_name(path.stem + f"_t{int(round(data.t[k]))}.png"))
        print(f"[dashboard] frame t={data.t[k]:.1f} s -> {png}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
