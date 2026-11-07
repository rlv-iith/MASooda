"""Frame streaming for the live demo: limits, adaptive stride, compact frames, memory cap.

All limits come from the ``web:`` section of ``configs/base_config.yaml``.

Compact frame v2 (what ``/api/runs/<id>/frames`` returns)::

    {"v": 2, "n": seq, "k": tick, "t": seconds,
     "x": [dm], "y": [dm],            # positions as integer decimetres
     "ls": [status * 8 + layer],      # status 0 queued, 1 airborne, 2 landed, 3 crashed
     "spd": [dm/s], "prog": [per-mille],
     "rho", "link_up", "attack", "net", "dtc", "events",
     "edges": [[i, j], ...], "edges_total": int,   # evenly sampled above web.max_edges_per_frame
     "stats": {...},                  # only when changed since the previous frame (carry forward)
     # Phase 2 (present when the engine produced them):
     "admm": {window stats, "run": {cumulative incl. p95}},  "neg": {drone id: last ADMM negotiation},
     "prio": {emergency compliance; only when changed, carry forward},  "merge": {junction merging + platoons},
     "spoof": {spoofer id: reported / true / W-MSR estimate},  "trust": {receiver id: [[nbr, status]]},
     "new_flights": [flight manifest rows added mid-run; the frame width grows by these],
     # Phase 3B health:
     "h": {"soc": [int %], "bms": [0..3], "tmax": [int °C]}   # all drones, once per sim second (carry forward)
     "hsel": {drone id: full health detail}                     # only drones the page selected (?sel=)
     "reroutes": [{id, destination, route, reason}]}            # health diversions

Thinning keeps every event: a dropped frame's events (and its stats, if the next
kept frame has none) move into the next kept frame.
"""

from __future__ import annotations

import bisect
import math
import threading
from typing import Any

DEFAULT_WEB = {
    "max_fleet": 150,
    "max_duration_s": 900.0,
    "realtime_max_fleet": 150,
    "target_frames_per_sim_s": 5.0,
    "max_kb_per_sim_s": 40.0,
    "est_bytes_per_drone_frame": 22.0,
    "max_frames_in_memory": 6000,
    "max_edges_per_frame": 600,
    "poll_batch": 400,
    "spatial_index": True,
    "grid_cell_m": 40.0,
    "interactive_lead_s": 5.0,
    "watcher_timeout_s": 5.0,
}
PHASE2_KEYS = ("admm", "neg", "merge", "spoof", "trust", "new_flights", "h", "hsel", "reroutes", "console")
CARRY_KEYS = ("stats", "prio", "h", "console")   # sent only when changed / once per second; carried forward
LIST_KEYS = ("new_flights", "reroutes")  # must never be lost: concatenated into the next kept frame


def web_limits(cfg: dict[str, Any]) -> dict[str, Any]:
    """The ``web:`` config section merged over safe defaults."""
    out = dict(DEFAULT_WEB)
    out.update(cfg.get("web", {}) or {})
    return out


def choose_stride(cfg: dict[str, Any], fleet: int) -> int:
    """Ticks between streamed frames.

    Base stride gives ``target_frames_per_sim_s``; it is raised when the estimated
    stream (fleet x bytes per drone x frames per sim-second) exceeds
    ``max_kb_per_sim_s``. Deterministic: depends only on config and fleet size.
    """
    web = web_limits(cfg)
    dt = float(cfg["simulation"]["timestep_seconds"])
    ticks_per_s = 1.0 / dt
    stride = max(1, int(round(ticks_per_s / max(float(web["target_frames_per_sim_s"]), 1e-6))))
    frame_kb = max(1, int(fleet)) * float(web["est_bytes_per_drone_frame"]) / 1024.0
    budget = float(web["max_kb_per_sim_s"])
    while (ticks_per_s / stride) * frame_kb > budget and stride < ticks_per_s * 10:
        stride += 1
    return stride


def _sample_edges(edges: list, cap: int) -> list:
    if cap <= 0 or len(edges) <= cap:
        return edges
    step = len(edges) / cap
    return [edges[int(i * step)] for i in range(cap)]


def compact_frame(frame: dict[str, Any], seq: int, prev_stats: dict | None, max_edges: int,
                  prev_prio: dict | None = None) -> dict[str, Any]:
    """Engine frame (floats, verbose) -> compact v2 frame (small ints)."""
    status, layer = frame["status"], frame["layer"]
    edges = [list(e) for e in frame.get("edges", [])]
    out = {
        "v": 2, "n": int(seq), "k": int(frame.get("k", 0)), "t": float(frame["t"]),
        "x": [int(round(v * 10.0)) for v in frame["x"]],
        "y": [int(round(v * 10.0)) for v in frame["y"]],
        "ls": [int(s) * 8 + int(l) for s, l in zip(status, layer)],
        "spd": [int(round(v * 10.0)) for v in frame["speed"]],
        "prog": [int(round(v * 1000.0)) for v in frame["progress"]],
        "rho": frame.get("rho"),
        "link_up": bool(frame.get("link_up", True)),
        "attack": bool(frame.get("attack", False)),
        "net": frame.get("net"),
        "dtc": frame.get("dtc"),
        "events": list(frame.get("events", [])),
        "edges": _sample_edges(edges, max_edges),
        "edges_total": len(edges),
    }
    for key in PHASE2_KEYS:  # Phase 2 instruments, passed through when present
        if frame.get(key) is not None:
            out[key] = frame[key]
    stats = frame.get("stats")
    if stats is not None and stats != prev_stats:
        out["stats"] = stats
    prio = frame.get("prio")
    if prio is not None and prio != prev_prio:
        out["prio"] = prio
    return out


class FrameStore:
    """Thread-safe store of compact frames, addressed by sequence number ``n``."""

    def __init__(self, max_frames: int):
        self.max_frames = max(16, int(max_frames))
        self.frames: list[dict[str, Any]] = []
        self.lock = threading.Lock()
        self.thinned = 0  # frames dropped so far (events moved, never lost)

    def append(self, frame: dict[str, Any]) -> None:
        with self.lock:
            self.frames.append(frame)
            if len(self.frames) > self.max_frames:
                self._thin()

    def _thin(self) -> None:
        """Drop every other frame in the older half; move their events/stats forward."""
        half = len(self.frames) // 2
        kept: list[dict[str, Any]] = []
        carry_events: list = []
        carry_lists: dict[str, list] = {}   # injected flights and reroutes must never be lost either
        carry: dict[str, Any] = {}
        for i, f in enumerate(self.frames):
            if i < half and i % 2 == 1:
                carry_events.extend(f.get("events", []))
                for key in LIST_KEYS:
                    if f.get(key):
                        carry_lists.setdefault(key, []).extend(f[key])
                for key in CARRY_KEYS:
                    if key in f:
                        carry[key] = f[key]
                self.thinned += 1
                continue
            if carry_events or carry or carry_lists:
                f = dict(f)
                f["events"] = carry_events + list(f.get("events", []))
                for key, value in carry_lists.items():
                    f[key] = value + list(f.get(key, []))
                for key, value in carry.items():
                    if key not in f:
                        f[key] = value
                carry_events, carry_lists, carry = [], {}, {}
            kept.append(f)
        self.frames = kept

    def since(self, seq: int, limit: int) -> tuple[list[dict[str, Any]], int]:
        """Frames with ``n >= seq`` (at most ``limit``) and the total number stored."""
        with self.lock:
            ns = [f["n"] for f in self.frames]
            i = bisect.bisect_left(ns, int(seq))
            return self.frames[i:i + max(1, int(limit))], len(self.frames)

    def last_seq(self) -> int:
        with self.lock:
            return self.frames[-1]["n"] if self.frames else -1


def estimated_realtime_factor(ms_per_tick: float, dt: float) -> float:
    """Simulated seconds per wall second for a measured engine speed."""
    return math.inf if ms_per_tick <= 0 else dt * 1000.0 / ms_per_tick
