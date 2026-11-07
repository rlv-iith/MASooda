"""Week 6 experiment harness shared by E1-E6 and scripts/run_all.

Every Week 6 experiment goes through the same code path:

    RunSpec  ->  run_one()  ->  run_matrix()  ->  runs.csv + manifest.json
                                              ->  aggregate() -> summary.csv

``run_one`` wraps :func:`experiments.runner.run_experiment`, so the row schema
(``STANDARD_COLUMNS``), the initial-conditions hash and all metric definitions
(``verification.metrics``) are the existing ones; this module only adds extra
columns, config overrides, resumable parallel execution and summary
statistics.

CLI::

    python -m experiments.week6 --matrix e4 [--quick] [--workers N]
    python -m experiments.week6 --list
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import csv
import dataclasses
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
from typing import Any, Iterable, Iterator, Sequence

import numpy as np

from config.load_config import get_config
from experiments.runner import (
    STANDARD_COLUMNS,
    check_identical_conditions,
    run_experiment,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

# Extra columns appended after STANDARD_COLUMNS in every Week 6 runs.csv.
EXTRA_COLUMNS = [
    "spec_hash",
    "config_hash",
    "base_config_hash",
    "emergency",
    "attack_start_s",
    "attack_offset_m",
    "admm_max_iterations",
    "admm_nonconverged_frac",
    "emergency_id",
    "priority_compliance_rate",
    "emergency_travel_time_s",
    "emergency_delay_s",
    "series_file",
]


def _corridor_ids() -> list[int]:
    return list(range(int(get_config()["corridors"]["count"])))


# Week 6 B1-B4 per-run columns (always collected; NaN = "n/a").
ADMM_COLUMNS = [
    "admm_solver_calls",
    "admm_iter_mean",
    "admm_iter_p95",
    "admm_iter_max",
    "admm_converged_frac",
    "admm_solve_ms_mean",
    "admm_solve_ms_p95",
    "admm_time_per_tick_ms",
    "admm_max_group_size",
]
FORMATION_COLUMNS = (
    ["merge_attempts", "merge_success", "merge_failed", "not_reached", "merge_success_rate"]
    + [f"util_mean_c{c}" for c in _corridor_ids()]
    + [f"util_peak_c{c}" for c in _corridor_ids()]
    + ["ticks_over_capacity"]
)
STATS_COLUMNS = [
    "emergency_control",
    "emergency_nominal_time_s",
    "overseer_dropped",
    "max_directive_staleness_s",
    "component_failures",
    "layer_changes",
    "attack_active_ticks",
    "post_attack_violation_ticks",
    "calls_file",
    "telemetry_file",
    "occupancy_file",
    "arrivals_file",
    "frames_file",
]
RUN_COLUMNS =STANDARD_COLUMNS + EXTRA_COLUMNS + ADMM_COLUMNS + FORMATION_COLUMNS + STATS_COLUMNS

# Columns that legitimately differ between identical runs.
NONDETERMINISTIC_COLUMNS = ("wall_time_s",)

# RunSpec convenience fields -> dotted config key they override.
_OVERRIDE_FIELDS = {
    "attack_offset_m": "attack.offset_magnitude_meters",
    "admm_max_iterations": "admm.maximum_iterations",
}

# Config sections that do not influence a simulation run (excluded from the
# config hash so that adding matrices or plot settings does not invalidate
# results).
_NON_SIM_SECTIONS = ("experiments", "visualization")


# ---------------------------------------------------------------------------
# Config overrides
# ---------------------------------------------------------------------------


def _set_dotted(cfg: dict, key: str, value: Any) -> None:
    parts = key.split(".")
    node = cfg
    for p in parts[:-1]:
        if p not in node or not isinstance(node[p], dict):
            raise KeyError(f"config override path '{key}' does not exist")
        node = node[p]
    if parts[-1] not in node:
        raise KeyError(f"config override key '{key}' does not exist")
    node[parts[-1]] = value


@contextlib.contextmanager
def config_overrides(overrides: dict[str, Any] | None) -> Iterator[dict]:
    """Temporarily apply dotted-key overrides to the shared config.

    The cached config dict returned by ``get_config()`` is mutated in place
    (every module reads it at call time) and fully restored on exit, even if
    the body raises. Only existing keys may be overridden.
    """
    cfg = get_config()
    if not overrides:
        yield cfg
        return
    saved = copy.deepcopy(cfg)
    try:
        for k, v in overrides.items():
            _set_dotted(cfg, k, v)
        yield cfg
    finally:
        cfg.clear()
        cfg.update(saved)
        # Derived caches built from the overridden values must not leak.
        from local_behavior.boids import reset_local_behavior_cache

        reset_local_behavior_cache()


def config_hash(cfg: dict | None = None) -> str:
    """sha256 (16 hex) of the simulation-relevant config sections."""
    cfg = get_config() if cfg is None else cfg
    sim = {k: v for k, v in cfg.items() if k not in _NON_SIM_SECTIONS}
    payload = json.dumps(sim, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def week6_config(cfg: dict | None = None) -> dict:
    cfg = get_config() if cfg is None else cfg
    return cfg.get("experiments", {}).get("week6", {}) or {}


# ---------------------------------------------------------------------------
# RunSpec
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class RunSpec:
    """One simulation run. ``None`` for an optional field means config default."""

    architecture: str
    n_agents: int
    seed: int
    duration_s: float
    attack_enabled: bool = False
    link_failure: bool = False
    scenario: str = "custom"
    attack_start_s: float | None = None
    attack_offset_m: float | None = None
    admm_max_iterations: int | None = None
    emergency: bool = False
    # Extra dotted-key overrides, as a sorted tuple of (key, value) pairs.
    overrides: tuple = ()
    # E3 paired control: inject the emergency, then keep that agent as an
    # ordinary DELIVERY agent (priority_metrics.baseline_copy).
    emergency_control: bool = False

    def config_overrides(self) -> dict[str, Any]:
        out: dict[str, Any] = {k: v for k, v in self.overrides}
        for field, key in _OVERRIDE_FIELDS.items():
            val = getattr(self, field)
            if val is not None:
                out[key] = val
        return out

    def canonical(self) -> dict:
        d = dataclasses.asdict(self)
        d["overrides"] = [list(p) for p in sorted(self.overrides)]
        d["n_agents"] = int(d["n_agents"])
        d["seed"] = int(d["seed"])
        d["duration_s"] = float(d["duration_s"])
        for k in ("attack_start_s", "attack_offset_m"):
            if d[k] is not None:
                d[k] = float(d[k])
        if d["admm_max_iterations"] is not None:
            d["admm_max_iterations"] = int(d["admm_max_iterations"])
        # Fields added after the first Week 6 runs are omitted at their
        # default so earlier spec hashes stay valid.
        for k, default in _LATE_FIELD_DEFAULTS.items():
            if d[k] == default:
                del d[k]
        return d

    def spec_hash(self) -> str:
        """Stable 16-hex hash of the spec (independent of process / dict order)."""
        payload = json.dumps(self.canonical(), sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def label(self) -> str:
        bits = [self.architecture, f"N={self.n_agents}", f"seed={self.seed}"]
        if self.attack_enabled:
            bits.append("attack")
        if self.link_failure:
            bits.append("linkfail")
        if self.emergency:
            bits.append("emergency-control" if self.emergency_control else "emergency")
        if self.admm_max_iterations is not None:
            bits.append(f"iters={self.admm_max_iterations}")
        if self.attack_offset_m is not None:
            bits.append(f"offset={self.attack_offset_m:g}")
        return " ".join(bits)


_LATE_FIELD_DEFAULTS = {"emergency_control": False}


def make_spec(**kw: Any) -> RunSpec:
    """Build a RunSpec, normalising ``overrides`` (dict or pairs) to a tuple."""
    ov = kw.pop("overrides", None) or ()
    if isinstance(ov, dict):
        ov = ov.items()
    kw["overrides"] = tuple(sorted((str(k), v) for k, v in ov))
    return RunSpec(**kw)


# ---------------------------------------------------------------------------
# run_one
# ---------------------------------------------------------------------------


def _nan_if(cond: bool, value: float) -> float:
    return float("nan") if cond else float(value)


class SnapshotLogger:
    """Logger keeping a compact copy of the fleet every ``period_s`` of sim time.

    Saved as ``frames/<spec_hash>.npz`` so position-based figures (formation
    snapshot, emergency track) can be drawn later without re-simulating.
    """

    def __init__(self, period_s: float = 1.0) -> None:
        self.period_s = float(period_s)
        self._next = 0.0
        self.t: list[float] = []
        self.pos: list[np.ndarray] = []
        self.vel: list[np.ndarray] = []
        self.layer: list[np.ndarray] = []
        self.corridor: list[np.ndarray] = []
        self.ids: list[int] = []
        self.types: list[str] = []

    def log_state(self, t: float, agents: Sequence[Any]) -> None:
        if t + 1e-9 < self._next:
            return
        self._next = t + self.period_s
        if not self.ids:
            self.ids = [int(a.id) for a in agents]
            self.types = [getattr(a.type, "name", str(a.type)) for a in agents]
        self.t.append(float(t))
        self.pos.append(np.array([a.position for a in agents], dtype=float))
        self.vel.append(np.array([a.velocity for a in agents], dtype=float))
        self.layer.append(np.array([int(getattr(a, "altitude_layer", 0)) for a in agents], dtype=int))
        self.corridor.append(np.array(
            [-1 if a.corridor_assignment is None else int(a.corridor_assignment) for a in agents], dtype=int))

    def save(self, path: str | Path) -> None:
        np.savez_compressed(
            path,
            t=np.asarray(self.t, dtype=float),
            positions=np.asarray(self.pos, dtype=np.float32),
            velocities=np.asarray(self.vel, dtype=np.float32),
            layers=np.asarray(self.layer, dtype=np.int8),
            corridors=np.asarray(self.corridor, dtype=np.int8),
            ids=np.asarray(self.ids, dtype=int),
            types=np.asarray(self.types),
        )


def _admm_summary(records: Sequence[dict], admm_time_s: float, n_ticks: int) -> dict[str, float]:
    """Per-run ADMM columns from ADMMRecorder records (NaN when no solver call)."""
    from conflict_resolution.profiling import summarize as admm_summarize

    nan = float("nan")
    if not records:
        return {c: (0 if c == "admm_solver_calls" else nan) for c in ADMM_COLUMNS}
    s = admm_summarize(list(records))
    return {
        "admm_solver_calls": int(s["count"]),
        "admm_iter_mean": float(s["mean_iterations"]),
        "admm_iter_p95": float(s["p95_iterations"]),
        "admm_iter_max": float(s["max_iterations"]),
        "admm_converged_frac": float(s["fraction_converged"]),
        "admm_solve_ms_mean": float(s["mean_solve_ms"]),
        "admm_solve_ms_p95": float(s["p95_solve_ms"]),
        "admm_time_per_tick_ms": (1000.0 * float(admm_time_s) / n_ticks) if n_ticks > 0 else nan,
        "admm_max_group_size": int(max(int(r["group_size"]) for r in records)),
    }


def _formation_summary(logger: Any, cfg: dict) -> dict[str, Any]:
    from local_behavior.formation_metrics import corridor_utilization, merge_outcomes

    m = merge_outcomes(logger, cfg)
    u = corridor_utilization(logger, capacity=float(cfg["corridors"]["capacity"]))
    out: dict[str, Any] = {
        "merge_attempts": int(m["merge_attempts"]),
        "merge_success": int(m["merge_success"]),
        "merge_failed": int(m["merge_failed"]),
        "not_reached": int(m["not_reached"]),
        "merge_success_rate": float(m["merge_success_rate"]),  # NaN if 0 attempts
        "ticks_over_capacity": int(u.get("ticks_over_capacity", 0)),
    }
    for c in _corridor_ids():
        out[f"util_mean_c{c}"] = float(u.get(f"util_c{c}", float("nan")))
        out[f"util_peak_c{c}"] = float(u.get(f"peak_c{c}", float("nan")))
    return out


def run_one(spec: RunSpec, out_dir: str | Path | None = None, save_series: bool = True) -> dict:
    """Run one spec; return a row with every column in RUN_COLUMNS.

    Besides the standard metrics, every run records (without changing the
    simulation): each ADMM solver call (ADMMRecorder), formation / merge /
    corridor utilisation (FormationLogger), per-tick telemetry
    (TelemetryRecorder) and the engine stats. With ``save_series`` the
    per-run files go to ``out_dir/{series,calls,telemetry,occupancy,arrivals}``.

    Quantities that were not observed in the run (no arrivals, no ADMM solver
    call, no merge attempt, emergency agent never arrived) are NaN, never a
    measured 0.
    """
    from conflict_resolution.profiling import ADMMRecorder
    from local_behavior.formation_metrics import FormationLogger
    from simulation.priority_metrics import PriorityLogger, baseline_copy, inject_emergency, nominal_time
    from simulation.telemetry import TelemetryRecorder

    emergency_state: dict[str, Any] = {}
    formation = FormationLogger()
    frames = SnapshotLogger(float(week6_config().get("snapshot_period_s", 1.0)))
    extra_loggers: list = [formation, frames]
    transform = None
    if spec.emergency:

        def transform(agents):  # noqa: E306
            new_agents, eid = inject_emergency(agents)
            if spec.emergency_control:
                new_agents = baseline_copy(new_agents, eid)
            emergency_state["id"] = eid
            emergency_state["agent"] = next(a for a in new_agents if a.id == eid)
            emergency_state["logger"] = PriorityLogger(eid)
            extra_loggers.append(emergency_state["logger"])
            return new_agents

    telemetry = TelemetryRecorder()
    stats: dict[str, Any] = {}

    # Hash of the config *before* this spec's overrides: identifies which
    # version of base_config.yaml produced the row (see run_matrix archiving).
    base_hash = config_hash()
    with config_overrides(spec.config_overrides()) as cfg:
        chash = config_hash(cfg)
        with ADMMRecorder() as admm_rec:
            row, (times, rho) = run_experiment(
                spec.architecture,
                spec.n_agents,
                spec.seed,
                duration_s=spec.duration_s,
                attack_enabled=spec.attack_enabled,
                link_failure=spec.link_failure,
                scenario=spec.scenario,
                return_series=True,
                attack_start_s=spec.attack_start_s,
                agent_transform=transform,
                extra_loggers=extra_loggers,
                extra_stats=stats,
                telemetry=telemetry,
            )
        admm_records = list(admm_rec.records)
        attack_offset = float(cfg["attack"]["offset_magnitude_meters"])
        admm_iters = int(cfg["admm"]["maximum_iterations"])
        attack_start = (
            float(spec.attack_start_s)
            if spec.attack_start_s is not None
            else float(cfg["attack"]["start_time_seconds"])
        )
        nominal = nominal_time(emergency_state["agent"], cfg) if spec.emergency else float("nan")
        formation_cols = _formation_summary(formation, cfg)
        capacity = float(cfg["corridors"]["capacity"])

    row = dict(row)
    # Rule 10: no arrivals -> throughput is "n/a", not a measured 0.
    row["throughput_per_s"] = _nan_if(row["arrivals"] == 0, row["throughput_per_s"])

    times = np.asarray(times, dtype=float)
    rho = np.asarray(rho, dtype=float)
    nan = float("nan")
    if spec.attack_enabled:
        post_attack: Any = int(np.sum((times >= attack_start) & (rho < 0.0)))
    else:
        post_attack = nan

    sh = spec.spec_hash()
    extra: dict[str, Any] = {
        "spec_hash": sh,
        "config_hash": chash,
        "base_config_hash": base_hash,
        "emergency": bool(spec.emergency),
        "attack_start_s": attack_start if spec.attack_enabled else nan,
        "attack_offset_m": attack_offset if spec.attack_enabled else nan,
        "admm_max_iterations": admm_iters,
        "admm_nonconverged_frac": (
            float(row["admm_nonconverged"]) / row["admm_events"] if row["admm_events"] > 0 else nan
        ),
        "emergency_id": emergency_state.get("id", ""),
        "priority_compliance_rate": nan,
        "emergency_travel_time_s": nan,
        "emergency_delay_s": nan,
        "series_file": "",
        "emergency_control": bool(spec.emergency_control),
        "emergency_nominal_time_s": nominal,
        "overseer_dropped": int(stats.get("overseer_dropped", 0)),
        "max_directive_staleness_s": float(stats.get("max_directive_staleness_s", nan)),
        "component_failures": int(stats.get("component_failures", 0)),
        "layer_changes": int(stats.get("layer_changes", 0)),
        "attack_active_ticks": int(stats.get("attack_active_ticks", 0)),
        "post_attack_violation_ticks": post_attack,
        "calls_file": "",
        "telemetry_file": "",
        "occupancy_file": "",
        "arrivals_file": "",
        "frames_file": "",
    }
    extra.update(_admm_summary(admm_records, float(stats.get("admm_time_s", 0.0)), int(stats.get("n_ticks", 0))))
    extra.update(formation_cols)
    arrival_times: dict[int, float] = {}
    if spec.emergency:
        lg = emergency_state["logger"]
        eid = emergency_state["id"]
        arrival_times = lg.arrival_times
        travel = float(arrival_times.get(eid, nan))
        extra["priority_compliance_rate"] = float(lg.compliance_rate)
        extra["emergency_travel_time_s"] = travel
        extra["emergency_delay_s"] = travel - nominal if math.isfinite(travel) else nan

    if save_series and out_dir is not None:
        od = Path(out_dir)
        for sub in ("series", "calls", "telemetry", "occupancy"):
            (od / sub).mkdir(parents=True, exist_ok=True)
        np.savez_compressed(od / "series" / f"{sh}.npz", t=times, robustness=rho, violation=rho < 0.0)
        extra["series_file"] = f"series/{sh}.npz"
        np.savez_compressed(
            od / "calls" / f"{sh}.npz",
            iterations=np.asarray([r["iterations"] for r in admm_records], dtype=int),
            converged=np.asarray([r["converged"] for r in admm_records], dtype=bool),
            solve_ms=np.asarray([1000.0 * r["solve_time_s"] for r in admm_records], dtype=float),
            group_size=np.asarray([r["group_size"] for r in admm_records], dtype=int),
        )
        extra["calls_file"] = f"calls/{sh}.npz"
        telemetry.to_csv(od / "telemetry" / f"{sh}.csv")
        extra["telemetry_file"] = f"telemetry/{sh}.csv"
        cids = _corridor_ids()
        occ = np.asarray(
            [[info["corridor_occupancy"].get(c, 0) for c in cids] for _, info in telemetry.ticks], dtype=int
        ).reshape(len(telemetry.ticks), len(cids))
        np.savez_compressed(
            od / "occupancy" / f"{sh}.npz",
            t=np.asarray([t for t, _ in telemetry.ticks], dtype=float),
            occupancy=occ,
            corridor_ids=np.asarray(cids, dtype=int),
            capacity=capacity,
        )
        extra["occupancy_file"] = f"occupancy/{sh}.npz"
        (od / "frames").mkdir(parents=True, exist_ok=True)
        frames.save(od / "frames" / f"{sh}.npz")
        extra["frames_file"] = f"frames/{sh}.npz"
        if spec.emergency:
            (od / "arrivals").mkdir(parents=True, exist_ok=True)
            with open(od / "arrivals" / f"{sh}.json", "w", encoding="utf-8", newline="\n") as f:
                json.dump({str(k): v for k, v in arrival_times.items()}, f, sort_keys=True)
            extra["arrivals_file"] = f"arrivals/{sh}.json"

    row.update(extra)
    return {c: row[c] for c in RUN_COLUMNS}


def _worker(args: tuple) -> tuple[int, dict | None, str, float]:
    idx, spec, out_dir, save_series = args
    t0 = time.perf_counter()
    try:
        row = run_one(spec, out_dir, save_series=save_series)
        return idx, row, "", time.perf_counter() - t0
    except Exception as exc:  # reported in manifest, run retried on resume
        return idx, None, f"{type(exc).__name__}: {exc}", time.perf_counter() - t0


# ---------------------------------------------------------------------------
# CSV / manifest helpers
# ---------------------------------------------------------------------------


def _fmt(v: Any) -> str:
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    return str(v)


def read_rows(path: str | Path) -> list[dict[str, str]]:
    p = Path(path)
    if not p.is_file():
        return []
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(rows: Sequence[dict], path: str | Path, columns: Sequence[str]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(columns), lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({c: _fmt(r.get(c, "")) for c in columns})


def _append_row(row: dict, path: Path) -> None:
    new = not path.is_file()
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=RUN_COLUMNS, lineterminator="\n")
        if new:
            w.writeheader()
        w.writerow({c: _fmt(row.get(c, "")) for c in RUN_COLUMNS})


def _archive_rows(rows: Sequence[dict], path: Path) -> None:
    """Append rows to ``runs_archive.csv`` (kept for reference, never aggregated)."""
    new = not path.is_file()
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=RUN_COLUMNS, lineterminator="\n", extrasaction="ignore")
        if new:
            w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in RUN_COLUMNS})


def git_commit() -> str:
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, timeout=10
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        return f"{sha}{'-dirty' if dirty else ''}" if sha else "unknown"
    except Exception:
        return "unknown"


def _versions() -> dict:
    out = {"python": platform.python_version(), "numpy": np.__version__}
    try:
        import matplotlib

        out["matplotlib"] = matplotlib.__version__
    except Exception:
        out["matplotlib"] = "not installed"
    return out


def write_manifest(csv_path: str | Path, info: dict) -> Path:
    """Write ``manifest.json`` next to ``csv_path`` (rule 9 fields + ``info``)."""
    csv_path = Path(csv_path)
    manifest = {
        "csv": csv_path.name,
        "command": " ".join([Path(sys.executable).name] + sys.argv),
        "git_commit": git_commit(),
        "config_hash": config_hash(),
        "versions": _versions(),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    manifest.update(info)
    path = csv_path.parent / "manifest.json"
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, indent=2, sort_keys=True, default=str)
        f.write("\n")
    return path


def _fmt_eta(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m{s:02d}s" if h else f"{m}m{s:02d}s"


# ---------------------------------------------------------------------------
# run_matrix
# ---------------------------------------------------------------------------


def run_matrix(
    specs: Sequence[RunSpec],
    out_dir: str | Path,
    workers: int | None = None,
    resume: bool = True,
    save_series: bool = True,
    manifest_info: dict | None = None,
    log=print,
    max_runs: int | None = None,
) -> list[dict]:
    """Run ``specs`` (in a process pool when workers > 1), resumably.

    ``max_runs`` caps how many pending specs this call executes (the rest
    stay pending for the next, resumed call).

    A spec is skipped when ``runs.csv`` already holds a row with the same
    spec hash *and* the same config hash. New rows are appended as they finish
    (crash-safe); at the end runs.csv is rewritten in spec order so the file is
    reproducible regardless of completion order. Returns the rows for
    ``specs`` in spec order (as CSV strings for resumed rows, typed for new).

    Rows produced under a different base config (``base_config_hash`` differs
    from the current ``config_hash()``, e.g. after a bug fix changed a
    parameter, or rows written before the column existed) are moved to
    ``runs_archive.csv`` so runs.csv, and every summary built from it, only
    ever holds results from the current configuration.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    runs_csv = out_dir / "runs.csv"
    workers = max(1, int(workers or os.cpu_count() or 1))

    existing = read_rows(runs_csv) if resume else []
    if not resume and runs_csv.exists():
        runs_csv.unlink()
    current_base = config_hash()
    stale = [r for r in existing if r.get("base_config_hash") != current_base]
    if stale:
        existing = [r for r in existing if r.get("base_config_hash") == current_base]
        _archive_rows(stale, out_dir / "runs_archive.csv")
        log(f"[week6] config changed: moved {len(stale)} old row(s) to runs_archive.csv")
    done_keys = {(r.get("spec_hash"), r.get("config_hash")) for r in existing}

    pending: list[tuple[int, RunSpec]] = []
    keys: list[tuple[str, str]] = []
    for i, s in enumerate(specs):
        with config_overrides(s.config_overrides()) as cfg:
            chash = config_hash(cfg)
        key = (s.spec_hash(), chash)
        keys.append(key)
        if key not in done_keys:
            pending.append((i, s))
    skipped = len(specs) - len(pending)
    deferred = 0
    if max_runs is not None and len(pending) > max_runs:
        deferred = len(pending) - int(max_runs)
        pending = pending[: int(max_runs)]
    log(f"[week6] {len(specs)} runs, {skipped} already done, {len(pending)} to run"
        + (f" ({deferred} deferred by max_runs)" if deferred else "") + f", workers={workers}")

    t_start = time.perf_counter()
    new_rows: dict[int, dict] = {}
    failures: list[dict] = []
    per_run_wall: list[dict] = []
    jobs = [(i, s, str(out_dir), save_series) for i, s in pending]

    def _handle(res: tuple) -> None:
        idx, row, err, dt = res
        spec = specs[idx]
        if row is None:
            failures.append({"spec": spec.canonical(), "error": err})
            log(f"[week6] FAILED {spec.label()}: {err}")
        else:
            new_rows[idx] = row
            _append_row(row, runs_csv)
        per_run_wall.append({"label": spec.label(), "wall_s": round(dt, 3)})
        done = len(new_rows) + len(failures)
        elapsed = time.perf_counter() - t_start
        eta = elapsed / done * (len(jobs) - done) if done else 0.0
        log(f"[week6] {done}/{len(jobs)} {spec.label()} {dt:.1f}s  elapsed {_fmt_eta(elapsed)}  ETA {_fmt_eta(eta)}")

    if workers == 1 or len(jobs) <= 1:
        for j in jobs:
            _handle(_worker(j))
    else:
        from concurrent.futures import ProcessPoolExecutor, as_completed

        with ProcessPoolExecutor(max_workers=min(workers, len(jobs))) as pool:
            futs = [pool.submit(_worker, j) for j in jobs]
            for fut in as_completed(futs):
                _handle(fut.result())
    total_wall = time.perf_counter() - t_start

    # Canonical rewrite: this matrix's rows in spec order, then unrelated old rows.
    by_key = {(r.get("spec_hash"), r.get("config_hash")): r for r in existing}
    ordered: list[dict] = []
    for i, key in enumerate(keys):
        if i in new_rows:
            ordered.append(new_rows[i])
        elif key in by_key:
            ordered.append(by_key[key])
    wanted = set(keys)
    others = [r for r in existing if (r.get("spec_hash"), r.get("config_hash")) not in wanted]
    write_csv(ordered + others, runs_csv, RUN_COLUMNS)

    ok, msg = check_identical_conditions_week6(ordered)
    if not ok:
        log(f"[week6] WARNING: {msg}")

    info = {
        "seeds": sorted({int(s.seed) for s in specs}),
        "agent_counts": sorted({int(s.n_agents) for s in specs}),
        "architectures": sorted({s.architecture for s in specs}),
        "n_specs": len(specs),
        "n_skipped_resume": skipped,
        "n_deferred_max_runs": deferred,
        "n_archived_stale": len(stale),
        "base_config_hash": current_base,
        "n_run": len(new_rows),
        "failures": failures,
        "identical_initial_conditions": {"ok": ok, "message": msg},
        "wall_time_s": round(total_wall, 3),
        "per_run_wall_time_s": per_run_wall,
        "workers": workers,
    }
    info.update(manifest_info or {})
    write_manifest(runs_csv, info)
    return ordered


def check_identical_conditions_week6(rows: Sequence[dict]) -> tuple[bool, str]:
    """``check_identical_conditions`` per emergency flag.

    Emergency injection changes the simulated fleet (and therefore its hash),
    so emergency and non-emergency runs are checked separately.
    """
    groups: dict[str, list[dict]] = {}
    for r in rows:
        rr = dict(r)
        rr["seed"] = int(rr["seed"])
        rr["num_agents"] = int(rr["num_agents"])
        key = f"{r.get('emergency', False)}/control={r.get('emergency_control', False)}"
        groups.setdefault(key, []).append(rr)
    msgs = []
    for flag, grp in sorted(groups.items()):
        ok, msg = check_identical_conditions(grp)
        if not ok:
            return False, f"emergency={flag}: {msg}"
        msgs.append(msg)
    return True, msgs[0] if msgs else "no rows"


# ---------------------------------------------------------------------------
# aggregate
# ---------------------------------------------------------------------------


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the regularized incomplete beta (Lentz)."""
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 500):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-15:
            break
    return h


def _betainc(a: float, b: float, x: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    front = math.exp(lbeta + a * math.log(x) + b * math.log1p(-x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def t_cdf(t: float, df: float) -> float:
    """Student-t CDF."""
    x = df / (df + t * t)
    tail = 0.5 * _betainc(df / 2.0, 0.5, x)
    return 1.0 - tail if t >= 0 else tail


def t_ppf(q: float, df: float) -> float:
    """Student-t quantile by bisection on :func:`t_cdf` (0.5 < q < 1 handled symmetric)."""
    if not 0.0 < q < 1.0:
        raise ValueError("q must be in (0, 1)")
    if q < 0.5:
        return -t_ppf(1.0 - q, df)
    lo, hi = 0.0, 1.0
    while t_cdf(hi, df) < q:
        hi *= 2.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if t_cdf(mid, df) < q:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-12:
            break
    return 0.5 * (lo + hi)


def _to_float(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


def summarize(values: Iterable[Any], ci_level: float = 0.95) -> dict[str, float]:
    """mean, sample std, n (finite values only) and t-based CI of the mean."""
    xs = [x for x in (_to_float(v) for v in values) if math.isfinite(x)]
    n = len(xs)
    nan = float("nan")
    if n == 0:
        return {"mean": nan, "std": nan, "n": 0, "ci_lo": nan, "ci_hi": nan}
    mean = math.fsum(xs) / n
    if n < 2:
        return {"mean": mean, "std": nan, "n": 1, "ci_lo": nan, "ci_hi": nan}
    var = math.fsum((x - mean) ** 2 for x in xs) / (n - 1)
    std = math.sqrt(var)
    half = t_ppf(0.5 + ci_level / 2.0, n - 1) * std / math.sqrt(n)
    return {"mean": mean, "std": std, "n": n, "ci_lo": mean - half, "ci_hi": mean + half}


def aggregate(
    runs_csv: str | Path,
    group_by: Sequence[str],
    metrics: Sequence[str],
    out_csv: str | Path | None = None,
    ci_level: float | None = None,
) -> list[dict]:
    """Group runs.csv rows and summarise each metric (no pandas).

    Output columns: the group_by columns, then for each metric
    ``<m>_mean, <m>_std, <m>_n, <m>_ci_lo, <m>_ci_hi``. Non-finite values
    (NaN = "n/a", inf) are excluded and reflected in ``<m>_n``. Writes
    ``summary.csv`` next to runs_csv unless ``out_csv`` is given.
    """
    if ci_level is None:
        ci_level = float(week6_config().get("ci_level", 0.95))
    rows = read_rows(runs_csv)
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        groups.setdefault(tuple(r.get(g, "") for g in group_by), []).append(r)

    def _sort_key(k: tuple) -> tuple:
        out = []
        for v in k:
            f = _to_float(v)
            out.append((0, f, "") if math.isfinite(f) else (1, 0.0, str(v)))
        return tuple(out)

    summary: list[dict] = []
    for key in sorted(groups, key=_sort_key):
        rec: dict[str, Any] = dict(zip(group_by, key))
        for m in metrics:
            s = summarize((r.get(m) for r in groups[key]), ci_level)
            for stat, val in s.items():
                rec[f"{m}_{stat}"] = val
        summary.append(rec)

    columns = list(group_by) + [f"{m}_{s}" for m in metrics for s in ("mean", "std", "n", "ci_lo", "ci_hi")]
    out = Path(out_csv) if out_csv is not None else Path(runs_csv).parent / "summary.csv"
    write_csv(summary, out, columns)
    return summary


# ---------------------------------------------------------------------------
# Matrices (config: experiments.week6.matrices)
# ---------------------------------------------------------------------------


def _as_list(v: Any) -> list:
    return list(v) if isinstance(v, (list, tuple)) else [v]


def expand_matrix(name: str, quick: bool = False, cfg: dict | None = None) -> tuple[list[RunSpec], dict, dict]:
    """Expand ``experiments.week6.matrices.<name>`` into RunSpecs.

    Returns (specs, matrix_section_as_used, matrix_raw). ``null`` lists fall
    back to ``experiments.seeds`` / ``experiments.agent_counts`` /
    ``experiments.architectures``; ``duration_s: null`` falls back to
    ``simulation.duration_seconds``. ``quick`` applies
    ``experiments.week6.quick``.
    """
    cfg = get_config() if cfg is None else cfg
    exp = cfg.get("experiments", {})
    w6 = week6_config(cfg)
    matrices = w6.get("matrices", {}) or {}
    if name not in matrices:
        raise KeyError(f"unknown matrix '{name}'; available: {sorted(matrices)}")
    raw = matrices[name] or {}
    m = copy.deepcopy(raw)

    m["architectures"] = _as_list(m.get("architectures") or exp.get("architectures"))
    m["agent_counts"] = _as_list(m.get("agent_counts") or exp.get("agent_counts"))
    m["seeds"] = _as_list(m.get("seeds") or exp.get("seeds"))
    if m.get("duration_s") is None:
        m["duration_s"] = float(cfg["simulation"]["duration_seconds"])
    for k in ("attack_enabled", "link_failure", "emergency", "emergency_control"):
        m[k] = _as_list(m.get(k, False))
    if m.get("attack_offset_m") == "sweep":
        m["attack_offset_m"] = list(cfg["attack"]["sweep_offsets_meters"])
    for k in ("attack_start_s", "attack_offset_m", "admm_max_iterations"):
        m[k] = _as_list(m.get(k)) if m.get(k) is not None else [None]
    m.setdefault("scenario", name)
    m.setdefault("output_subdir", name)
    m.setdefault("overrides", {})

    if quick:
        q = w6.get("quick", {}) or {}
        m["seeds"] = m["seeds"][: int(q.get("n_seeds", 1))]
        if q.get("agent_counts") is not None:
            m["agent_counts"] = _as_list(q["agent_counts"])
        if q.get("duration_s") is not None:
            m["duration_s"] = float(q["duration_s"])
        if q.get("attack_start_s") is not None and any(m["attack_enabled"]):
            m["attack_start_s"] = [float(q["attack_start_s"])]
        if q.get("admm_max_iterations") is not None and m["admm_max_iterations"] != [None]:
            m["admm_max_iterations"] = m["admm_max_iterations"][:1]
        if q.get("attack_offset_m") is not None and m["attack_offset_m"] != [None]:
            m["attack_offset_m"] = m["attack_offset_m"][:1]

    # A value equal to the config default is stored as None, so e.g. the
    # N=60 / limit=50 runs of e1_iter are the very same specs as in e1.
    default_iters = cfg["admm"]["maximum_iterations"]
    default_offset = cfg["attack"]["offset_magnitude_meters"]
    specs: list[RunSpec] = []
    for n in m["agent_counts"]:
        for arch in m["architectures"]:
            for att in m["attack_enabled"]:
                for lf in m["link_failure"]:
                    for em, em_ctrl in [(e, c) for e in m["emergency"] for c in m["emergency_control"]]:
                        if em_ctrl and not em:
                            continue
                        for a_start in m["attack_start_s"]:
                            for a_off in m["attack_offset_m"]:
                                for iters in m["admm_max_iterations"]:
                                    for seed in m["seeds"]:
                                        specs.append(
                                            make_spec(
                                                architecture=str(arch),
                                                n_agents=int(n),
                                                seed=int(seed),
                                                duration_s=float(m["duration_s"]),
                                                attack_enabled=bool(att),
                                                link_failure=bool(lf),
                                                scenario=str(m["scenario"]),
                                                attack_start_s=a_start if att else None,
                                                attack_offset_m=_none_if_default(a_off, default_offset) if att else None,
                                                admm_max_iterations=_none_if_default(iters, default_iters),
                                                emergency=bool(em),
                                                emergency_control=bool(em_ctrl),
                                                overrides=m["overrides"],
                                            )
                                        )
    # Drop duplicates created by attack-only axes on non-attack rows.
    seen: set[str] = set()
    unique = []
    for s in specs:
        h = s.spec_hash()
        if h not in seen:
            seen.add(h)
            unique.append(s)
    return unique, m, raw


def _none_if_default(value: Any, default: Any) -> Any:
    if value is None:
        return None
    try:
        return None if float(value) == float(default) else value
    except (TypeError, ValueError):
        return value


def default_out_dir(matrix: dict, quick: bool, cfg: dict | None = None) -> Path:
    w6 = week6_config(cfg)
    base = REPO_ROOT / str(w6.get("output_dir", "outputs/week6"))
    if quick:
        base = base / str(w6.get("quick", {}).get("subdir", "_quick"))
    return base / str(matrix["output_subdir"])


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m experiments.week6", description=__doc__.split("\n\n")[0])
    ap.add_argument("--matrix", help="matrix name under experiments.week6.matrices")
    ap.add_argument("--quick", action="store_true", help="smoke test: 1 seed, few agents, short duration")
    ap.add_argument("--workers", type=int, default=None, help="process count (default: os.cpu_count())")
    ap.add_argument("--out", default=None, help="output directory (default: from config)")
    ap.add_argument("--no-resume", action="store_true", help="discard existing runs.csv")
    ap.add_argument("--no-series", action="store_true", help="do not save per-run time series")
    ap.add_argument("--list", action="store_true", help="list matrices and exit")
    args = ap.parse_args(argv)

    w6 = week6_config()
    if args.list or not args.matrix:
        for name in sorted(w6.get("matrices", {}) or {}):
            specs, _, _ = expand_matrix(name)
            qspecs, _, _ = expand_matrix(name, quick=True)
            print(f"{name}: {len(specs)} runs ({len(qspecs)} with --quick)")
        return 0 if args.list else 2

    specs, used, raw = expand_matrix(args.matrix, quick=args.quick)
    out_dir = Path(args.out) if args.out else default_out_dir(used, args.quick)
    t0 = time.perf_counter()
    rows = run_matrix(
        specs,
        out_dir,
        workers=args.workers,
        resume=not args.no_resume,
        save_series=not args.no_series,
        manifest_info={
            "matrix": args.matrix,
            "quick": bool(args.quick),
            "config_section": {f"experiments.week6.matrices.{args.matrix}": raw},
            "config_section_resolved": used,
            "provisional": bool(w6.get("provisional", True)),
        },
    )
    group_by = used.get("group_by") or w6.get("default_group_by", ["architecture", "num_agents"])
    metrics = used.get("metrics") or w6.get("default_metrics", ["min_robustness_m"])
    summary = aggregate(out_dir / "runs.csv", group_by, metrics)
    # One manifest per folder: runs.csv and summary.csv share it.
    man_path = out_dir / "manifest.json"
    man = json.loads(man_path.read_text(encoding="utf-8"))
    man["summary_csv"] = {"file": "summary.csv", "group_by": list(group_by), "metrics": list(metrics), "groups": len(summary)}
    man["wall_time_s_total"] = round(time.perf_counter() - t0, 3)
    with open(man_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(man, f, indent=2, sort_keys=True, default=str)
        f.write("\n")
    print(f"[week6] wrote {out_dir / 'runs.csv'} ({len(rows)} rows), summary.csv, manifest.json")
    return 1 if man.get("failures") else 0


if __name__ == "__main__":
    raise SystemExit(main())
