"""Opt-in per-tick telemetry for the simulation loops (Week 6 dashboard).

Loggers only receive ``(t, agents)``. Runners that are given a ``telemetry``
object additionally call ``telemetry.on_tick(t, info)`` after every tick,
where ``info`` is built by :func:`build_tick_info` and holds ADMM, attack,
overseer-link and airspace-occupancy status for that tick. Passing
``telemetry=None`` (the default) leaves the simulation untouched.

ADMM iteration counts and solve times come from
:class:`conflict_resolution.profiling.ADMMRecorder` (the solver itself is not
modified); they are only available for groups that reached the solver.
"""

from __future__ import annotations

import contextlib
import csv
import math
from pathlib import Path
from typing import Any, Iterator, Sequence

from simulation.environment import corridor_occupancy

INFO_KEYS = (
    "admm_events_tick",
    "admm_converged_tick",
    "admm_nonconverged_tick",
    "admm_iterations",
    "admm_solve_ms",
    "attack_active",
    "malicious_ids",
    "overseer_link_up",
    "directive_age_s",
    "corridor_occupancy",
    "layer_counts",
    "emergency_ids",
)


@contextlib.contextmanager
def admm_solver_records(enabled: bool) -> Iterator[list[dict]]:
    """Yield a list that collects ADMM solver-call records while enabled.

    When ``enabled`` is False nothing is patched and the list stays empty.
    """
    if not enabled:
        yield []
        return
    from conflict_resolution.profiling import ADMMRecorder

    with ADMMRecorder() as rec:
        yield rec.records


def _is_emergency(agent: Any) -> bool:
    t = getattr(agent, "type", None)
    name = getattr(t, "name", None) or getattr(t, "value", None) or str(t)
    return str(name).upper().endswith("EMERGENCY")


def build_tick_info(
    agents: Sequence[Any],
    corridors: Sequence[Any],
    *,
    admm_events_tick: int = 0,
    admm_nonconverged_tick: int = 0,
    admm_records: Sequence[dict] = (),
    malicious_ids: Sequence[int] = (),
    overseer_link_up: bool | None = None,
    directive_age_s: float = float("nan"),
) -> dict[str, Any]:
    """Assemble the ``info`` dict passed to ``telemetry.on_tick``.

    ``overseer_link_up`` is None for architectures without an overseer;
    ``directive_age_s`` is NaN while no directive has been received.
    """
    layer_counts: dict[int, int] = {}
    for a in agents:
        layer = int(getattr(a, "altitude_layer", 0))
        layer_counts[layer] = layer_counts.get(layer, 0) + 1
    return {
        "admm_events_tick": int(admm_events_tick),
        "admm_converged_tick": int(admm_events_tick) - int(admm_nonconverged_tick),
        "admm_nonconverged_tick": int(admm_nonconverged_tick),
        "admm_iterations": [int(r["iterations"]) for r in admm_records],
        "admm_solve_ms": [float(r["solve_time_s"]) * 1000.0 for r in admm_records],
        "attack_active": bool(malicious_ids),
        "malicious_ids": sorted(int(i) for i in malicious_ids),
        "overseer_link_up": overseer_link_up,
        "directive_age_s": float(directive_age_s),
        "corridor_occupancy": dict(sorted(corridor_occupancy(agents, corridors).items())),
        "layer_counts": dict(sorted(layer_counts.items())),
        "emergency_ids": sorted(int(a.id) for a in agents if _is_emergency(a)),
    }


def _join(values: Sequence[Any], fmt=str) -> str:
    return ";".join(fmt(v) for v in values)


class TelemetryRecorder:
    """Store per-tick telemetry and write it as ``telemetry.csv``.

    One row per tick. List fields are ``;``-joined; corridor occupancy and
    layer counts become one column per corridor id / layer (``occ_c<id>``,
    ``layer_<l>``). ADMM iteration/solve-time summaries are NaN ("n/a") on
    ticks with no solver call.
    """

    BASE_COLUMNS = [
        "t",
        "admm_events_tick",
        "admm_converged_tick",
        "admm_nonconverged_tick",
        "admm_solver_calls",
        "admm_iterations",
        "admm_iterations_mean",
        "admm_iterations_max",
        "admm_solve_ms",
        "admm_solve_ms_max",
        "attack_active",
        "malicious_ids",
        "overseer_link_up",
        "directive_age_s",
        "emergency_ids",
    ]

    def __init__(self) -> None:
        self.ticks: list[tuple[float, dict]] = []

    def on_tick(self, t: float, info: dict) -> None:
        self.ticks.append((float(t), info))

    def __len__(self) -> int:
        return len(self.ticks)

    # ------------------------------------------------------------------ totals
    def total(self, key: str) -> int:
        return int(sum(info[key] for _, info in self.ticks))

    # ------------------------------------------------------------------ rows
    def _extra_columns(self) -> tuple[list, list]:
        corr: set = set()
        layers: set = set()
        for _, info in self.ticks:
            corr.update(info["corridor_occupancy"])
            layers.update(info["layer_counts"])
        return sorted(corr), sorted(layers)

    @property
    def columns(self) -> list[str]:
        corr, layers = self._extra_columns()
        return self.BASE_COLUMNS + [f"occ_c{c}" for c in corr] + [f"layer_{l}" for l in layers]

    def rows(self) -> list[dict[str, Any]]:
        corr, layers = self._extra_columns()
        nan = float("nan")
        out = []
        for t, info in self.ticks:
            iters = info["admm_iterations"]
            ms = info["admm_solve_ms"]
            link = info["overseer_link_up"]
            row = {
                "t": t,
                "admm_events_tick": info["admm_events_tick"],
                "admm_converged_tick": info["admm_converged_tick"],
                "admm_nonconverged_tick": info["admm_nonconverged_tick"],
                "admm_solver_calls": len(iters),
                "admm_iterations": _join(iters),
                "admm_iterations_mean": (sum(iters) / len(iters)) if iters else nan,
                "admm_iterations_max": max(iters) if iters else nan,
                "admm_solve_ms": _join(ms, lambda v: f"{v:.4f}"),
                "admm_solve_ms_max": max(ms) if ms else nan,
                "attack_active": bool(info["attack_active"]),
                "malicious_ids": _join(info["malicious_ids"]),
                "overseer_link_up": "" if link is None else bool(link),
                "directive_age_s": info["directive_age_s"],
                "emergency_ids": _join(info["emergency_ids"]),
            }
            for c in corr:
                row[f"occ_c{c}"] = info["corridor_occupancy"].get(c, 0)
            for l in layers:
                row[f"layer_{l}"] = info["layer_counts"].get(l, 0)
            out.append(row)
        return out

    def to_csv(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        cols = self.columns
        with open(p, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
            w.writeheader()
            for r in self.rows():
                w.writerow({k: (repr(v) if isinstance(v, float) and not math.isnan(v) else
                                ("nan" if isinstance(v, float) else v)) for k, v in r.items()})
        return p
