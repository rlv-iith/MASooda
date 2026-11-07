"""Shared plotting utilities for MASooda (workflow 14.1).

Every Week 6 figure goes through this module so all plots share one style,
one colour per architecture / agent type / event, and one save path.

Plot functions take plain rows (dicts, e.g. read from ``runs.csv`` /
``summary.csv`` produced by :mod:`experiments.week6`) or arrays, never
simulation objects, so a figure can always be regenerated from saved CSVs.
Each function accepts an optional ``ax`` (to compose multi-panel figures)
and returns ``(fig, ax)``. Save with :func:`save_figure`.

Missing values (NaN, "", "nan" - "n/a" in the result files) are never drawn
as 0: bars show "n/a", lines break, and the caption says how many were
excluded.

Regenerate the style sheet::

    python -m visualization.plots --style-check
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
import warnings

import matplotlib

if __name__ == "__main__":  # pragma: no cover - CLI is headless
    matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import numpy as np

from config.load_config import get_config
from simulation.mock_data import get_mock_agent_states, get_mock_comm_graph  # noqa: F401 (re-export)
from simulation.renderer import CorridorGeometry, render_top_down
from simulation.schema import AgentState, CommunicationGraph

REPO_ROOT = Path(__file__).resolve().parent.parent

__all__ = [
    "plot_airspace",
    "apply_style",
    "save_figure",
    "arch_color",
    "type_color",
    "event_color",
    "display_label",
    "metric_label",
    "robustness_timeseries",
    "metric_bars",
    "metric_vs_param",
    "distribution_plot",
    "utilization_heatmap",
    "timeline_strip",
    "style_sheet",
]


# ---------------------------------------------------------------------------
# Existing API (unchanged)
# ---------------------------------------------------------------------------


def plot_airspace(
    agents: Sequence[AgentState] | None = None,
    corridors: Sequence[CorridorGeometry] | None = None,
    comm_graph: CommunicationGraph | None = None,
    save_path: str | Path | None = None,
    show: bool = False,
) -> plt.Figure:
    """Plot the top-down airspace map showing agents and corridors."""
    return render_top_down(
        agents=agents,
        corridors=corridors,
        comm_graph=comm_graph,
        save_path=save_path,
        show=show,
    )


# ---------------------------------------------------------------------------
# Style, colours, labels
# ---------------------------------------------------------------------------

_FALLBACK_CYCLE = ["#0072B2", "#E69F00", "#009E73", "#D55E00", "#56B4E9", "#CC79A7", "#F0E442", "#000000"]
_ARCH_ORDER = ("hierarchical", "centralized", "decentralized_undefended")
_EVENT_ORDER = ("attack", "link_down", "violation")
_HATCHES = ("", "///", "...", "xxx", "\\\\\\", "++")

# metric / parameter column -> axis label with units
METRIC_LABELS: dict[str, str] = {
    "throughput_per_s": "Throughput (agents/s)",
    "arrivals": "Arrivals (agents)",
    "safety_violation_ticks": "Safety-violation ticks (count)",
    "violation_episodes": "Violation episodes (count)",
    "mean_recovery_time_s": "Mean recovery time (s)",
    "max_recovery_time_s": "Max recovery time (s)",
    "min_robustness_m": "Min STL robustness ρ (m)",
    "min_separation_m": "Min separation (m)",
    "admm_events": "ADMM conflict events (count)",
    "admm_nonconverged": "ADMM non-converged events (count)",
    "admm_nonconverged_frac": "ADMM non-converged fraction",
    "fraction_converged": "ADMM converged fraction",
    "mean_iterations": "ADMM iterations (mean)",
    "mean_solve_ms": "ADMM solve time (ms)",
    "reports_dropped": "Reports dropped (count)",
    "overseer_failures": "Overseer failures (count)",
    "priority_compliance_rate": "Priority-compliance rate",
    "emergency_delay_s": "Emergency delay (s)",
    "merge_success_rate": "Merge success rate",
    "wall_time_s": "Wall time (s)",
    "num_agents": "Number of agents N",
    "admm_max_iterations": "ADMM iteration limit",
    "attack_offset_m": "Attack offset (m)",
    "attack_start_s": "Attack start (s)",
    "seed": "Seed",
    "architecture": "Architecture",
    "attack_enabled": "Attack",
    "link_failure": "Overseer link",
    "emergency": "Emergency agent",
}

_BOOL_LABELS = {
    "attack_enabled": ("Attack off", "Attack on"),
    "link_failure": ("Link up", "Link failure"),
    "emergency": ("No emergency", "Emergency"),
}


def _vis_cfg() -> dict:
    return get_config().get("visualization", {}) or {}


def _week6_cfg() -> dict:
    return (get_config().get("experiments", {}) or {}).get("week6", {}) or {}


def _colors() -> dict:
    return _vis_cfg().get("colors", {}) or {}


def _cycle() -> list[str]:
    return list(_colors().get("cycle") or _FALLBACK_CYCLE)


def apply_style() -> dict:
    """Apply the house style to matplotlib rcParams (idempotent); return the vis config."""
    v = _vis_cfg()
    fs = float(v.get("font_size", 10))
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": [str(v.get("font_family", "DejaVu Sans")), "DejaVu Sans"],
            "font.size": fs,
            "axes.titlesize": float(v.get("title_size", fs + 1)),
            "axes.titleweight": "bold",
            "axes.labelsize": fs,
            "xtick.labelsize": fs - 1,
            "ytick.labelsize": fs - 1,
            "legend.fontsize": fs - 1,
            "legend.frameon": True,
            "legend.framealpha": 0.9,
            "axes.grid": True,
            "grid.alpha": 0.3,
            "grid.linewidth": 0.6,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.prop_cycle": matplotlib.cycler(color=_cycle()),
            "savefig.dpi": int(v.get("dpi", 300)),
            "pdf.fonttype": 42,  # editable text in PDFs
            "lines.linewidth": 1.6,
        }
    )
    return v


def arch_color(name: Any) -> str:
    """Fixed colour of an architecture (fallback: palette by position)."""
    cmap = _colors().get("architectures", {}) or {}
    key = str(name)
    if key in cmap:
        return str(cmap[key])
    cyc = _cycle()
    if key in _ARCH_ORDER:
        return cyc[_ARCH_ORDER.index(key) % len(cyc)]
    return cyc[sum(map(ord, key)) % len(cyc)]  # stable across processes (unlike hash())


def type_color(name: Any) -> str:
    """Fixed colour of an agent type (EMERGENCY / EVTOL / DELIVERY or AgentType)."""
    key = getattr(name, "name", str(name)).upper()
    return str((_colors().get("agent_types", {}) or {}).get(key, "#555555"))


def event_color(kind: str) -> str:
    return str((_colors().get("events", {}) or {}).get(kind, "#7F7F7F"))


def _event_label(kind: str) -> str:
    labels = (_vis_cfg().get("labels", {}) or {}).get("events", {}) or {}
    return str(labels.get(kind, kind.replace("_", " ").capitalize()))


def _to_bool(v: Any) -> bool | None:
    """True/False for bools and their CSV spellings; None otherwise (numbers are not bools)."""
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true", "yes"):
            return True
        if s in ("false", "no"):
            return False
    return None


def display_label(column: str | None, value: Any) -> str:
    """Human-readable label for a group/hue value (architecture names, booleans)."""
    if column == "architecture" or str(value) in _ARCH_ORDER:
        labels = (_vis_cfg().get("labels", {}) or {}).get("architectures", {}) or {}
        return str(labels.get(str(value), str(value)))
    if column in _BOOL_LABELS:
        b = _to_bool(value)
        if b is not None:
            return _BOOL_LABELS[column][int(b)]
    if column == "num_agents":
        return f"N={_fmt_num(value)}"
    return _fmt_num(value) if _is_num(value) else str(value)


def metric_label(name: str | None) -> str:
    if name is None:
        return ""
    return METRIC_LABELS.get(name, name.replace("_", " "))


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _f(v: Any) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return float("nan")
    return x


def _finite(v: Any) -> bool:
    return math.isfinite(_f(v))


def _is_num(v: Any) -> bool:
    if isinstance(v, (bool, np.bool_)) or _to_bool(v) is not None:
        return False
    return _finite(v)


def _fmt_num(v: Any) -> str:
    x = _f(v)
    if not math.isfinite(x):
        return str(v)
    return str(int(x)) if x == int(x) else f"{x:g}"


def _key(v: Any) -> str:
    """Canonical string for matching values coming from CSV (str) or code (typed)."""
    if _is_num(v):
        return _fmt_num(v)
    b = _to_bool(v)
    if b is not None:
        return str(b)
    return str(v)


def _order(values: Iterable[Any], column: str | None) -> list[Any]:
    """Unique values in a stable, meaningful order."""
    uniq: list[Any] = []
    seen: set[str] = set()
    for v in values:
        k = _key(v)
        if k not in seen:
            seen.add(k)
            uniq.append(v)
    if column == "architecture" or all(str(u) in _ARCH_ORDER for u in uniq):
        return sorted(uniq, key=lambda u: _ARCH_ORDER.index(str(u)) if str(u) in _ARCH_ORDER else 99)
    if all(_is_num(u) for u in uniq):
        return sorted(uniq, key=_f)
    if all(_to_bool(u) is not None for u in uniq):
        return sorted(uniq, key=lambda u: int(bool(_to_bool(u))))
    return uniq


def _new_ax(ax: plt.Axes | None, size: Sequence[float] | None = None) -> tuple[plt.Figure, plt.Axes]:
    v = apply_style()
    if ax is not None:
        return ax.figure, ax
    figsize = tuple(size or v.get("figure_size", (6.4, 4.0)))
    fig = plt.figure(figsize=figsize, layout="constrained")
    return fig, fig.add_subplot()


def _caption(ax: plt.Axes, text: str) -> None:
    """Small caption under the x-axis label (seed counts, n/a notes). Part of the layout."""
    if not text:
        return
    # x in axes fraction (left-aligned with the plot), y anchored to the bottom
    # of the x-axis label so the caption never overlaps it, however tall the
    # tick labels are. Call after set_xlabel().
    ax.annotate(
        text,
        xy=(0.0, 0.0),
        xycoords=("axes fraction", ax.xaxis.label),
        xytext=(0, -3),
        textcoords="offset points",
        ha="left",
        va="top",
        fontsize=max(6.0, plt.rcParams["font.size"] - 2),
        color="#444444",
        annotation_clip=False,
    )


def _n_text(ns: Sequence[int], unit: str = "seeds") -> str:
    ns = [int(n) for n in ns if n is not None]
    if not ns:
        return ""
    lo, hi = min(ns), max(ns)
    return f"n = {lo} {unit} per point" if lo == hi else f"n = {lo}–{hi} {unit} per point"


def _mean_ci(stack: np.ndarray, level: float = 0.95) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Column-wise mean and t-based CI ignoring NaN (columns with <2 values: no band)."""
    from experiments.week6 import t_ppf

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        n = np.sum(np.isfinite(stack), axis=0)
        mean = np.nanmean(stack, axis=0)
        std = np.nanstd(stack, axis=0, ddof=1)
    half = np.full(mean.shape, np.nan)
    for k in np.unique(n[n >= 2]):
        idx = n == k
        half[idx] = t_ppf(0.5 + level / 2.0, int(k) - 1) * std[idx] / math.sqrt(int(k))
    return mean, mean - half, mean + half


# ---------------------------------------------------------------------------
# save_figure
# ---------------------------------------------------------------------------


def figures_dir() -> Path:
    return REPO_ROOT / str(_week6_cfg().get("output_dir", "outputs/week6")) / "figures"


def save_figure(
    fig: plt.Figure,
    name: str,
    out_dir: str | Path | None = None,
    provisional: bool | None = None,
    formats: Sequence[str] = ("png", "pdf"),
) -> list[Path]:
    """Save ``fig`` as ``<out_dir>/<name>.png`` (config dpi) and ``.pdf``, then close it.

    ``out_dir`` defaults to ``outputs/week6/figures``. When
    ``experiments.week6.provisional`` is true (or ``provisional=True``) a
    small footer marks the figure as pre-bug-fix. PDFs carry no creation
    date so identical figures produce identical files.
    """
    if not name or any(c in name for c in "/\\"):
        raise ValueError(f"figure name must be a plain file stem, got {name!r}")
    v = _vis_cfg()
    if provisional is None:
        provisional = bool(_week6_cfg().get("provisional", True))
    if provisional:
        fig.text(
            0.995,
            -0.005,
            str(v.get("provisional_footer", "PROVISIONAL - pre-bug-fix results")),
            ha="right",
            va="top",
            fontsize=7,
            style="italic",
            color=event_color("violation"),
            gid="provisional_footer",
        )
    out = Path(out_dir) if out_dir is not None else figures_dir()
    out.mkdir(parents=True, exist_ok=True)
    dpi = int(v.get("dpi", 300))
    paths: list[Path] = []
    for fmt in formats:
        p = out / f"{name}.{fmt}"
        meta = {"CreationDate": None} if fmt == "pdf" else ({"Software": None} if fmt == "png" else None)
        fig.savefig(p, dpi=dpi, bbox_inches="tight", pad_inches=0.08, metadata=meta)
        paths.append(p)
    plt.close(fig)
    return paths


# ---------------------------------------------------------------------------
# Plot functions
# ---------------------------------------------------------------------------


def _as_runs(data: Any) -> list[tuple[np.ndarray, np.ndarray]]:
    """Normalise one label's data to a list of (t, rho) runs.

    Accepts a single ``(t, rho)`` tuple, a mapping with ``t`` and
    ``robustness`` (e.g. a loaded ``series/*.npz``), or a list of either.
    """
    def one(d: Any) -> tuple[np.ndarray, np.ndarray]:
        if isinstance(d, Mapping) or hasattr(d, "files"):
            return np.asarray(d["t"], float), np.asarray(d["robustness"], float)
        t, r = d
        return np.asarray(t, float), np.asarray(r, float)

    if isinstance(data, list):
        return [one(d) for d in data]
    return [one(data)]


def robustness_timeseries(
    series_by_label: Mapping[str, Any],
    d_min: float,
    events: Sequence[Mapping[str, Any]] | None = None,
    ax: plt.Axes | None = None,
    title: str | None = "STL robustness over time",
    band: bool = True,
) -> tuple[plt.Figure, plt.Axes]:
    """Plot rho(t) per label with the rho = 0 threshold.

    ``series_by_label``: label -> (t, rho), npz mapping, or list of those
    (one per seed). With several seeds the mean is drawn with a 95% CI band.
    Labels that are architecture names get their fixed colour.
    ``events``: dicts ``{"kind": "attack"|"link_down"|..., "start": s, "end": s or None}``;
    windows are shaded, open-ended events drawn as a vertical line.
    """
    fig, ax = _new_ax(ax)
    ns: list[int] = []
    t_max = 0.0
    for i, (label, data) in enumerate(series_by_label.items()):
        runs = _as_runs(data)
        if not runs:
            continue
        length = min(len(t) for t, _ in runs)
        t = runs[0][0][:length]
        stack = np.vstack([r[:length] for _, r in runs])
        color = arch_color(label) if str(label) in _ARCH_ORDER else _cycle()[i % len(_cycle())]
        name = display_label(None, label)
        n = len(runs)
        ns.append(n)
        if not np.isfinite(stack).any():
            ax.plot([], [], color=color, label=f"{name} (n/a)")
            continue
        if n > 1:
            mean, lo, hi = _mean_ci(stack)
            ax.plot(t, mean, color=color, label=f"{name} (mean, n={n})")
            if band:
                ax.fill_between(t, lo, hi, color=color, alpha=0.18, linewidth=0)
        else:
            ax.plot(t, stack[0], color=color, label=name)
        t_max = max(t_max, float(np.nanmax(t)) if t.size else 0.0)

    seen: set[str] = set()
    for ev in events or []:
        kind = str(ev.get("kind", "event"))
        start = _f(ev.get("start"))
        end = _f(ev.get("end"))
        if not math.isfinite(start):
            continue
        lab = _event_label(kind) if kind not in seen else None
        seen.add(kind)
        if math.isfinite(end):
            ax.axvspan(start, end, color=event_color(kind), alpha=0.14, linewidth=0, label=lab)
        else:
            ax.axvline(start, color=event_color(kind), linestyle=":", linewidth=1.6, label=lab)

    thr = str(_colors().get("threshold", "#000000"))
    ax.axhline(0.0, color=thr, linestyle="--", linewidth=1.0, label=f"ρ = 0 (d_min = {_fmt_num(d_min)} m)")
    lo_y, hi_y = ax.get_ylim()
    if lo_y < 0:
        ax.axhspan(lo_y, 0.0, color=event_color("violation"), alpha=0.05, linewidth=0, zorder=0)
        ax.set_ylim(lo_y, hi_y)
    if t_max > 0:
        ax.set_xlim(0.0, t_max)
    ax.set_xlabel("Simulation time (s)")
    ax.set_ylabel("STL robustness ρ (m)")
    if title:
        ax.set_title(title)
    ax.legend(loc="best")
    cap = "ρ(t) = min pairwise separation − d_min"
    if any(n > 1 for n in ns):
        cap += "; line = mean, band = 95% CI across seeds"
    nt = _n_text(ns, "seeds")
    _caption(ax, f"{cap}; {nt.replace(' per point', ' per line')}" if nt else cap)
    return fig, ax


def _find(rows: Sequence[Mapping[str, Any]], **match: Any) -> list[Mapping[str, Any]]:
    want = {k: _key(v) for k, v in match.items() if k is not None}
    return [r for r in rows if all(_key(r.get(k)) == v for k, v in want.items())]


def _style_for(group: str, hue: str | None, g: Any, h: Any, gi: int, hi: int) -> tuple[str, str, float]:
    """(colour, hatch, alpha) for a bar. Architecture always drives colour."""
    if group == "architecture":
        return arch_color(g), _HATCHES[hi % len(_HATCHES)], (0.55 if hi == 0 and hue else 0.95)
    if hue == "architecture":
        return arch_color(h), "", 0.9
    if hue is None:
        return _cycle()[gi % len(_cycle())], "", 0.9
    return _cycle()[hi % len(_cycle())], "", 0.9


def metric_bars(
    summary_rows: Sequence[Mapping[str, Any]],
    metric: str,
    group: str,
    hue: str | None = None,
    runs_rows: Sequence[Mapping[str, Any]] | None = None,
    ax: plt.Axes | None = None,
    title: str | None = None,
    ylabel: str | None = None,
) -> tuple[plt.Figure, plt.Axes]:
    """Grouped bars of ``<metric>_mean`` with 95% CI error bars.

    ``summary_rows`` come from ``experiments.week6.aggregate`` (columns
    ``<metric>_mean/_ci_lo/_ci_hi/_n``). If ``runs_rows`` (runs.csv rows) is
    given, the individual seed values are overlaid as points. Missing means
    are labelled "n/a" instead of drawing a zero bar.
    """
    fig, ax = _new_ax(ax)
    groups = _order([r.get(group) for r in summary_rows], group)
    hues = _order([r.get(hue) for r in summary_rows], hue) if hue else [None]
    width = 0.8 / max(1, len(hues))
    ns: list[int] = []
    n_na = 0
    for gi, g in enumerate(groups):
        for hi, h in enumerate(hues):
            x = gi - 0.4 + width * (hi + 0.5)
            match = {group: g}
            if hue:
                match[hue] = h
            recs = _find(summary_rows, **match)
            color, hatch, alpha = _style_for(group, hue, g, h, gi, hi)
            mean = _f(recs[0].get(f"{metric}_mean")) if recs else float("nan")
            if not math.isfinite(mean):
                n_na += 1
                ax.text(x, 0.0, "n/a", ha="center", va="bottom", fontsize=8, color="#666666", rotation=90)
                continue
            ns.append(int(_f(recs[0].get(f"{metric}_n")) or 0))
            ax.bar(x, mean, width * 0.9, color=color, alpha=alpha, hatch=hatch, edgecolor="black", linewidth=0.6, zorder=2)
            lo, hi_ = _f(recs[0].get(f"{metric}_ci_lo")), _f(recs[0].get(f"{metric}_ci_hi"))
            if math.isfinite(lo) and math.isfinite(hi_):
                ax.errorbar(x, mean, yerr=[[mean - lo], [hi_ - mean]], fmt="none", ecolor="black",
                            elinewidth=1.0, capsize=3, zorder=3)
            if runs_rows is not None:
                vals = [_f(r.get(metric)) for r in _find(runs_rows, **match)]
                vals = [v for v in vals if math.isfinite(v)]
                if vals:
                    jit = np.linspace(-width * 0.25, width * 0.25, len(vals)) if len(vals) > 1 else [0.0]
                    ax.scatter(x + np.asarray(jit), vals, s=14, color="white", edgecolor="black",
                               linewidth=0.7, zorder=4)
    ax.set_xticks(range(len(groups)))
    ax.set_xticklabels([display_label(group, g) for g in groups])
    ax.set_xlabel(metric_label(group))
    ax.set_ylabel(ylabel or metric_label(metric))
    ax.axhline(0.0, color="black", linewidth=0.6)
    ax.set_title(title if title is not None else f"{metric_label(metric).split(' (')[0]} by {metric_label(group).lower()}")
    handles: list[Any] = []
    if hue and group == "architecture":
        handles = [Patch(facecolor="#BBBBBB", alpha=0.55 if i == 0 else 0.95, hatch=_HATCHES[i % len(_HATCHES)],
                         edgecolor="black", label=display_label(hue, h)) for i, h in enumerate(hues)]
    elif hue:
        handles = [Patch(facecolor=_style_for(group, hue, None, h, 0, i)[0], edgecolor="black",
                         label=display_label(hue, h)) for i, h in enumerate(hues)]
    if runs_rows is not None:
        handles.append(plt.Line2D([], [], marker="o", linestyle="none", markerfacecolor="white",
                                  markeredgecolor="black", markersize=5, label="individual seeds"))
    if handles:
        ax.legend(handles=handles, loc="best")
    cap = "Bars = mean, whiskers = 95% CI"
    nt = _n_text(ns)
    if nt:
        cap += f"; {nt.replace('per point', 'per bar')}"
    if n_na:
        cap += f"; {n_na} group(s) n/a (no observations)"
    _caption(ax, cap)
    return fig, ax


def metric_vs_param(
    summary_rows: Sequence[Mapping[str, Any]],
    x: str,
    metric: str,
    hue: str | None = None,
    ax: plt.Axes | None = None,
    title: str | None = None,
    ylabel: str | None = None,
    xlabel: str | None = None,
) -> tuple[plt.Figure, plt.Axes]:
    """``<metric>_mean`` against a numeric parameter, one line per hue, 95% CI band.

    NaN means break the line (never drawn as 0); the caption reports them.
    """
    fig, ax = _new_ax(ax)
    hues = _order([r.get(hue) for r in summary_rows], hue) if hue else [None]
    ns: list[int] = []
    n_na = 0
    xs_all: set[float] = set()
    for i, h in enumerate(hues):
        recs = _find(summary_rows, **({hue: h} if hue else {}))
        recs = sorted((r for r in recs if _finite(r.get(x))), key=lambda r: _f(r.get(x)))
        if not recs:
            continue
        xs = np.array([_f(r.get(x)) for r in recs])
        m = np.array([_f(r.get(f"{metric}_mean")) for r in recs])
        lo = np.array([_f(r.get(f"{metric}_ci_lo")) for r in recs])
        hi = np.array([_f(r.get(f"{metric}_ci_hi")) for r in recs])
        n_na += int(np.sum(~np.isfinite(m)))
        ns += [int(_f(r.get(f"{metric}_n")) or 0) for r, mm in zip(recs, m) if math.isfinite(mm)]
        xs_all.update(xs.tolist())
        color = arch_color(h) if hue == "architecture" or str(h) in _ARCH_ORDER else _cycle()[i % len(_cycle())]
        label = display_label(hue, h) if hue else metric_label(metric).split(" (")[0]
        ax.plot(xs, m, marker="o", markersize=5, color=color, label=label)
        band = np.isfinite(lo) & np.isfinite(hi)
        if band.any():
            ax.fill_between(xs, np.where(band, lo, np.nan), np.where(band, hi, np.nan),
                            color=color, alpha=0.18, linewidth=0)
    if xs_all and len(xs_all) <= 12 and all(float(v).is_integer() for v in xs_all):
        ax.set_xticks(sorted(xs_all))
    ax.set_xlabel(xlabel or metric_label(x))
    ax.set_ylabel(ylabel or metric_label(metric))
    ax.set_title(title if title is not None else f"{metric_label(metric).split(' (')[0]} vs {metric_label(x).split(' (')[0].lower()}")
    if hue or len(hues) > 1:
        ax.legend(loc="best")
    cap = "Line = mean, band = 95% CI"
    nt = _n_text(ns)
    if nt:
        cap += f"; {nt}"
    if n_na:
        cap += f"; {n_na} point(s) n/a (gap in line)"
    _caption(ax, cap)
    return fig, ax


def distribution_plot(
    rows: Sequence[Mapping[str, Any]],
    metric: str,
    group: str,
    ax: plt.Axes | None = None,
    title: str | None = None,
    ylabel: str | None = None,
) -> tuple[plt.Figure, plt.Axes]:
    """Box plot per group with every observation overlaid (strip). NaNs excluded and counted."""
    fig, ax = _new_ax(ax)
    groups = _order([r.get(group) for r in rows], group)
    data, counts, n_na = [], [], 0
    for g in groups:
        vals = [_f(r.get(metric)) for r in _find(rows, **{group: g})]
        fin = [v for v in vals if math.isfinite(v)]
        n_na += len(vals) - len(fin)
        data.append(fin)
        counts.append(len(fin))
    positions = list(range(len(groups)))
    nonempty = [i for i, d in enumerate(data) if d]
    if nonempty:
        bp = ax.boxplot([data[i] for i in nonempty], positions=[positions[i] for i in nonempty], widths=0.5,
                        patch_artist=True, showfliers=False, medianprops={"color": "black", "linewidth": 1.4})
        for patch, i in zip(bp["boxes"], nonempty):
            g = groups[i]
            c = arch_color(g) if group == "architecture" or str(g) in _ARCH_ORDER else _cycle()[i % len(_cycle())]
            patch.set_facecolor(c)
            patch.set_alpha(0.45)
            patch.set_edgecolor("black")
    rng = np.random.default_rng(0)  # deterministic jitter
    for i, d in enumerate(data):
        if not d:
            ax.text(positions[i], 0.5, "n/a", transform=ax.get_xaxis_transform(), ha="center", color="#666666")
            continue
        jit = rng.uniform(-0.12, 0.12, size=len(d))
        ax.scatter(positions[i] + jit, d, s=12, color="black", alpha=0.7, zorder=3)
    ax.set_xticks(positions)
    ax.set_xticklabels([f"{display_label(group, g)}\n(n={c})" for g, c in zip(groups, counts)])
    ax.set_xlabel(metric_label(group))
    ax.set_ylabel(ylabel or metric_label(metric))
    ax.set_title(title if title is not None else f"Distribution of {metric_label(metric).split(' (')[0].lower()}")
    cap = "Box = median and quartiles, whiskers = 1.5 IQR, dots = individual runs"
    if n_na:
        cap += f"; {n_na} n/a value(s) excluded"
    _caption(ax, cap)
    return fig, ax


def utilization_heatmap(
    matrix: Any,
    corridor_labels: Sequence[str],
    time_axis: Sequence[float],
    capacity: float,
    ax: plt.Axes | None = None,
    title: str | None = "Corridor utilization",
) -> tuple[plt.Figure, plt.Axes]:
    """Occupancy / capacity per corridor (rows) over time (columns).

    ``matrix`` has shape (n_corridors, len(time_axis)) and holds agent counts.
    Values above 1.0 exceed capacity. NaN cells are drawn grey.
    """
    fig, ax = _new_ax(ax)
    m = np.asarray(matrix, dtype=float)
    if m.ndim != 2 or m.shape[0] != len(corridor_labels) or m.shape[1] != len(time_axis):
        raise ValueError(f"matrix shape {m.shape} does not match ({len(corridor_labels)}, {len(time_axis)})")
    ratio = m / float(capacity)
    t = np.asarray(time_axis, dtype=float)
    vmax = max(1.5, float(np.nanmax(ratio)) if np.isfinite(ratio).any() else 1.5)
    cmap = plt.get_cmap("cividis").with_extremes(bad="#DDDDDD")
    dt = float(t[1] - t[0]) if t.size > 1 else 1.0
    im = ax.imshow(np.ma.masked_invalid(ratio), aspect="auto", origin="lower", cmap=cmap, vmin=0.0, vmax=vmax,
                   extent=(float(t[0]) - dt / 2, float(t[-1]) + dt / 2, -0.5, len(corridor_labels) - 0.5),
                   interpolation="nearest")
    ax.set_yticks(range(len(corridor_labels)))
    ax.set_yticklabels(list(corridor_labels))
    ax.grid(False)
    ax.set_xlabel("Simulation time (s)")
    ax.set_ylabel("Corridor")
    if title:
        ax.set_title(title)
    cb = fig.colorbar(im, ax=ax, pad=0.02)
    cb.set_label("Occupancy / capacity")
    cb.ax.axhline(1.0, color=event_color("violation"), linewidth=1.5)
    over = int(np.nansum(ratio > 1.0))
    _caption(ax, f"Capacity = {_fmt_num(capacity)} agents per corridor (red mark on colour bar); "
                 f"{over} corridor-tick(s) over capacity")
    return fig, ax


def timeline_strip(
    events: Sequence[Mapping[str, Any]],
    t_max: float,
    ax: plt.Axes | None = None,
    title: str | None = "Event timeline",
    kinds: Sequence[str] | None = None,
) -> tuple[plt.Figure, plt.Axes]:
    """Horizontal bars per event kind (attack active, DTC link down, violations).

    ``events``: dicts ``{"kind", "start", "end"}``; ``end`` None means until
    ``t_max``. The standard kinds are always shown so an absent event reads
    as "none" rather than disappearing.
    """
    fig, ax = _new_ax(ax, size=(6.4, 1.9))
    present = [str(e.get("kind")) for e in events]
    rows = list(kinds) if kinds is not None else list(_EVENT_ORDER) + [k for k in _order(present, None) if k not in _EVENT_ORDER]
    for i, kind in enumerate(rows):
        spans = []
        for e in events:
            if str(e.get("kind")) != kind:
                continue
            s = _f(e.get("start"))
            en = _f(e.get("end")) if e.get("end") is not None else float(t_max)
            if math.isfinite(s) and math.isfinite(en) and en >= s:
                spans.append((s, max(en - s, t_max * 0.002)))
        if spans:
            ax.broken_barh(spans, (i - 0.35, 0.7), facecolors=event_color(kind), alpha=0.85)
        else:
            ax.text(t_max * 0.01, i, "none", va="center", fontsize=8, color="#666666")
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([_event_label(k) for k in rows])
    ax.set_ylim(-0.6, len(rows) - 0.4)
    ax.invert_yaxis()
    ax.set_xlim(0.0, float(t_max))
    ax.set_xlabel("Simulation time (s)")
    ax.grid(axis="y", visible=False)
    if title:
        ax.set_title(title)
    return fig, ax


# ---------------------------------------------------------------------------
# Style sheet (synthetic data) for visual approval
# ---------------------------------------------------------------------------


def _synthetic(seed: int = 7) -> dict:
    """Deterministic synthetic data shaped like the real Week 6 outputs."""
    from experiments.week6 import summarize

    rng = np.random.default_rng(seed)
    t = np.round(np.arange(0, 180.1, 0.5), 3)
    series: dict[str, list] = {}
    for k, arch in enumerate(_ARCH_ORDER):
        runs = []
        for s in range(3):
            base = 6.0 - 2.0 * k + 1.5 * np.sin(t / (17 + 5 * s))
            dip = np.where(t > 60, -(4.0 + k) * np.exp(-((t - 70 - 4 * s) / 12.0) ** 2), 0.0)
            runs.append((t, base + dip + rng.normal(0, 0.4, t.size)))
        series[arch] = runs

    runs_rows, summary_bars = [], []
    for k, arch in enumerate(_ARCH_ORDER):
        for att in (False, True):
            vals = []
            for s in range(3):
                v = float("nan") if (arch == "centralized" and att and s == 0) else 40 + 25 * k + (30 if att else 0) + rng.normal(0, 8)
                vals.append(v)
                runs_rows.append({"architecture": arch, "attack_enabled": att, "seed": 42 + s, "safety_violation_ticks": v})
            st = summarize(vals)
            summary_bars.append({"architecture": arch, "attack_enabled": att,
                                 **{f"safety_violation_ticks_{k2}": v2 for k2, v2 in st.items()}})
    # one fully-missing group to exercise "n/a"
    summary_bars.append({"architecture": "decentralized_undefended", "attack_enabled": "maybe",
                         "safety_violation_ticks_mean": float("nan"), "safety_violation_ticks_n": 0})
    summary_bars = [r for r in summary_bars if r["attack_enabled"] != "maybe"]

    summary_param = []
    for k, arch in enumerate(_ARCH_ORDER[:2]):
        for n in (30, 45, 60, 75):
            vals = [0.98 - 0.003 * (n - 30) * (k + 1) + rng.normal(0, 0.01) for _ in range(3)]
            if arch == "centralized" and n == 60:
                vals = [float("nan")] * 3
            st = summarize(vals)
            summary_param.append({"architecture": arch, "num_agents": n,
                                  **{f"fraction_converged_{k2}": v2 for k2, v2 in st.items()}})

    dist_rows = [{"architecture": a, "min_robustness_m": float(rng.normal(-1.0 * k, 1.2))}
                 for k, a in enumerate(_ARCH_ORDER) for _ in range(8)]
    dist_rows.append({"architecture": "centralized", "min_robustness_m": "nan"})

    tt = np.arange(0, 180, 1.0)
    occ = np.vstack([np.clip(10 + 6 * np.sin(tt / 25 + c) + rng.normal(0, 1, tt.size), 0, None) for c in range(3)])
    occ[1] += 4
    occ[2, 50:55] = np.nan
    events = [{"kind": "attack", "start": 60.0, "end": None},
              {"kind": "link_down", "start": 90.0, "end": 120.0},
              {"kind": "violation", "start": 64.0, "end": 71.5},
              {"kind": "violation", "start": 102.0, "end": 104.0}]
    return {"t": t, "series": series, "runs_rows": runs_rows, "summary_bars": summary_bars,
            "summary_param": summary_param, "dist_rows": dist_rows, "occ": occ, "tt": tt, "events": events}


def style_sheet(out_dir: str | Path | None = None, name: str = "_style_check") -> list[Path]:
    """One page showing the palette and every plot type on synthetic data."""
    apply_style()
    d = _synthetic()
    fig = plt.figure(figsize=(14, 16), layout="constrained")
    axd = fig.subplot_mosaic([["pal", "ts"], ["bars", "param"], ["dist", "heat"], ["tl", "tl"]],
                             height_ratios=[1.0, 1.0, 1.0, 0.45])
    fig.suptitle("MASooda Week 6 figure style sheet (synthetic data)", fontsize=14, fontweight="bold")

    ax = axd["pal"]
    ax.set_axis_off()
    ax.set_title("Palette")
    blocks = [("Architectures", [(display_label("architecture", a), arch_color(a)) for a in _ARCH_ORDER]),
              ("Agent types", [(k.title() if k != "EVTOL" else "eVTOL", type_color(k)) for k in ("EMERGENCY", "EVTOL", "DELIVERY")]),
              ("Events", [(_event_label(k), event_color(k)) for k in _EVENT_ORDER])]
    y = 0.95
    for head, items in blocks:
        ax.text(0.02, y, head, fontweight="bold", transform=ax.transAxes, va="top")
        y -= 0.08
        for label, c in items:
            ax.add_patch(plt.Rectangle((0.04, y - 0.045), 0.08, 0.05, color=c, transform=ax.transAxes))
            ax.text(0.15, y - 0.02, f"{label}  {c}", transform=ax.transAxes, va="center")
            y -= 0.075
        y -= 0.03

    robustness_timeseries(d["series"], 8.0, d["events"][:2], ax=axd["ts"],
                          title="robustness_timeseries: ρ(t) by architecture")
    metric_bars(d["summary_bars"], "safety_violation_ticks", "architecture", "attack_enabled",
                runs_rows=d["runs_rows"], ax=axd["bars"], title="metric_bars: violations, attack off vs on")
    metric_vs_param(d["summary_param"], "num_agents", "fraction_converged", "architecture", ax=axd["param"],
                    title="metric_vs_param: convergence vs N")
    distribution_plot(d["dist_rows"], "min_robustness_m", "architecture", ax=axd["dist"],
                      title="distribution_plot: min robustness")
    utilization_heatmap(d["occ"], ["C0", "C1", "C2"], d["tt"], 15, ax=axd["heat"],
                        title="utilization_heatmap: occupancy / capacity")
    timeline_strip(d["events"], 180.0, ax=axd["tl"], title="timeline_strip: events")
    return save_figure(fig, name, out_dir=out_dir)


def main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - thin CLI
    ap = argparse.ArgumentParser(prog="python -m visualization.plots")
    ap.add_argument("--style-check", action="store_true", help="write outputs/week6/figures/_style_check.png/.pdf")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    if args.style_check:
        for p in style_sheet(args.out):
            print(p)
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
