"""Tests for the Week 6 shared plotting utilities (visualization/plots.py)."""

from __future__ import annotations

import math

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pytest

from config.load_config import get_config
from experiments.week6 import config_overrides, summarize
from visualization import plots
from visualization.plots import (
    arch_color,
    distribution_plot,
    display_label,
    metric_bars,
    metric_vs_param,
    plot_airspace,
    robustness_timeseries,
    save_figure,
    style_sheet,
    timeline_strip,
    type_color,
    utilization_heatmap,
)

ARCHS = ["hierarchical", "centralized", "decentralized_undefended"]


def _summary(metric, values_by_key, keys):
    rows = []
    for key, vals in values_by_key.items():
        rec = dict(zip(keys, key))
        rec.update({f"{metric}_{k}": v for k, v in summarize(vals).items()})
        rows.append(rec)
    return rows


def _footers(fig):
    return [t for t in fig.texts if t.get_gid() == "provisional_footer"]


# ----------------------------------------------------------------- style / colours


def test_colours_come_from_config_and_are_stable():
    cfg = get_config()["visualization"]["colors"]
    for a in ARCHS:
        assert arch_color(a) == cfg["architectures"][a]
    assert type_color("EMERGENCY") == cfg["agent_types"]["EMERGENCY"]
    # unknown label: deterministic fallback, same every call
    assert arch_color("something_else") == arch_color("something_else")
    assert len({arch_color(a) for a in ARCHS}) == 3


def test_display_labels():
    assert display_label("architecture", "decentralized_undefended") == "Decentralized (undefended)"
    assert display_label("attack_enabled", "True") == "Attack on"
    assert display_label("attack_enabled", False) == "Attack off"
    assert display_label("num_agents", "60") == "N=60"
    # numbers are never mistaken for booleans
    assert plots._key("1") == "1" and plots._key(1) == "1" and plots._key(True) == "True"


def test_apply_style_sets_dpi_from_config():
    plots.apply_style()
    assert plt.rcParams["savefig.dpi"] == get_config()["visualization"]["dpi"]


# ----------------------------------------------------------------- plot functions


def test_robustness_timeseries_single_and_multi_seed(tmp_path):
    t = np.arange(0, 20, 0.1)
    series = {
        "hierarchical": [(t, np.sin(t) + s) for s in range(3)],
        "centralized": (t, np.cos(t)),
        "decentralized_undefended": {"t": t, "robustness": np.full(t.size, np.nan)},  # all n/a
    }
    events = [{"kind": "attack", "start": 5.0, "end": None}, {"kind": "link_down", "start": 8.0, "end": 12.0}]
    fig, ax = robustness_timeseries(series, 8.0, events)
    labels = [h.get_label() for h in ax.get_legend().legend_handles]
    assert any("n=3" in l for l in labels)
    assert any("(n/a)" in l for l in labels)
    assert any(l.startswith("ρ = 0") for l in labels)
    assert any(len(line.get_ydata()) == 2 and line.get_ydata()[0] == 0 for line in ax.get_lines())  # threshold
    paths = save_figure(fig, "ts", out_dir=tmp_path)
    assert [p.suffix for p in paths] == [".png", ".pdf"]
    assert all(p.stat().st_size > 1000 for p in paths)


def test_metric_bars_ci_points_and_na(tmp_path):
    keys = ("architecture", "attack_enabled")
    vals = {(a, att): [10.0 + i + 5 * att + j for j in range(3)] for i, a in enumerate(ARCHS) for att in (False, True)}
    vals[("centralized", True)] = [float("nan")] * 3  # no observations -> n/a
    summary = _summary("safety_violation_ticks", vals, keys)
    runs = [{"architecture": a, "attack_enabled": str(att), "safety_violation_ticks": v}
            for (a, att), vs in vals.items() for v in vs]
    fig, ax = metric_bars(summary, "safety_violation_ticks", "architecture", "attack_enabled", runs_rows=runs)
    heights = [p.get_height() for p in ax.patches if p.get_height() != 0]
    assert len(heights) == 5  # 6 groups, one n/a
    assert all(math.isfinite(h) for h in heights)
    assert any(t.get_text() == "n/a" for t in ax.texts)
    assert len(ax.collections) >= 5  # seed points + error bars
    save_figure(fig, "bars", out_dir=tmp_path)
    assert (tmp_path / "bars.png").is_file()


def test_metric_bars_accepts_csv_strings(tmp_path):
    summary = [{"architecture": a, "m_mean": "1.5", "m_n": "3", "m_ci_lo": "1.0", "m_ci_hi": "2.0"} for a in ARCHS]
    fig, ax = metric_bars(summary, "m", "architecture")
    assert [round(p.get_height(), 3) for p in ax.patches][:3] == [1.5, 1.5, 1.5]
    plt.close(fig)


def test_metric_vs_param_breaks_line_on_nan():
    vals = {(a, n): [0.9 - 0.001 * n + 0.01 * j for j in range(3)] for a in ARCHS[:2] for n in (30, 45, 60, 75)}
    vals[("centralized", 60)] = [float("nan")] * 3
    summary = _summary("fraction_converged", vals, ("architecture", "num_agents"))
    fig, ax = metric_vs_param(summary, "num_agents", "fraction_converged", "architecture")
    ys = [line.get_ydata() for line in ax.get_lines() if line.get_label() == "Centralized"][0]
    assert np.isnan(ys[2]) and not np.any(np.asarray(ys)[np.isfinite(ys)] == 0)
    assert list(ax.get_xticks()) == [30, 45, 60, 75]
    plt.close(fig)


def test_distribution_plot_with_nan_and_empty_group(tmp_path):
    rows = [{"architecture": a, "min_robustness_m": float(i)} for i, a in enumerate(ARCHS) for _ in range(4)]
    rows += [{"architecture": "centralized", "min_robustness_m": "nan"},
             {"architecture": "extra", "min_robustness_m": ""}]
    fig, ax = distribution_plot(rows, "min_robustness_m", "architecture")
    ticks = [t.get_text() for t in ax.get_xticklabels()]
    assert "(n=4)" in ticks[0] and "(n=0)" in ticks[-1]
    save_figure(fig, "dist", out_dir=tmp_path)


def test_utilization_heatmap_with_nan_and_shape_check(tmp_path):
    t = np.arange(0, 30, 1.0)
    occ = np.vstack([np.full(t.size, 10.0), np.full(t.size, 20.0), np.full(t.size, np.nan)])
    fig, ax = utilization_heatmap(occ, ["C0", "C1", "C2"], t, 15)
    assert "30 corridor-tick(s) over capacity" in ax.texts[-1].get_text()
    save_figure(fig, "heat", out_dir=tmp_path)
    with pytest.raises(ValueError):
        utilization_heatmap(occ[:2], ["C0", "C1", "C2"], t, 15)


def test_timeline_strip_shows_absent_kinds_as_none():
    fig, ax = timeline_strip([{"kind": "attack", "start": 60, "end": None}], 180.0)
    assert [t.get_text() for t in ax.get_yticklabels()][:3] == ["Attack active", "DTC link down", "Safety violation"]
    assert sum(t.get_text() == "none" for t in ax.texts) == 2
    plt.close(fig)


# ----------------------------------------------------------------- save_figure


def test_provisional_footer_toggles(tmp_path):
    fig, _ = metric_vs_param([], "num_agents", "fraction_converged")
    save_figure(fig, "on", out_dir=tmp_path, provisional=True)
    assert len(_footers(fig)) == 1

    fig2, _ = metric_vs_param([], "num_agents", "fraction_converged")
    save_figure(fig2, "off", out_dir=tmp_path, provisional=False)
    assert not _footers(fig2)

    # default follows experiments.week6.provisional
    with config_overrides({"experiments.week6.provisional": False}):
        fig3, _ = metric_vs_param([], "num_agents", "fraction_converged")
        save_figure(fig3, "cfg_off", out_dir=tmp_path)
    assert not _footers(fig3)
    fig4, _ = metric_vs_param([], "num_agents", "fraction_converged")
    save_figure(fig4, "cfg_on", out_dir=tmp_path)
    assert len(_footers(fig4)) == bool(get_config()["experiments"]["week6"]["provisional"])


def test_save_figure_closes_and_rejects_paths(tmp_path):
    fig, _ = metric_vs_param([], "num_agents", "fraction_converged")
    save_figure(fig, "closed", out_dir=tmp_path)
    assert not plt.fignum_exists(fig.number)
    fig2, _ = metric_vs_param([], "num_agents", "fraction_converged")
    with pytest.raises(ValueError):
        save_figure(fig2, "../escape", out_dir=tmp_path)
    plt.close(fig2)


def test_pdf_output_is_deterministic(tmp_path):
    rows = [{"architecture": a, "m_mean": 1.0 + i, "m_n": 3, "m_ci_lo": 0.5 + i, "m_ci_hi": 1.5 + i}
            for i, a in enumerate(ARCHS)]
    for name in ("a", "b"):
        fig, _ = metric_bars(rows, "m", "architecture")
        save_figure(fig, name, out_dir=tmp_path, formats=("pdf",))
    assert (tmp_path / "a.pdf").read_bytes() == (tmp_path / "b.pdf").read_bytes()


# ----------------------------------------------------------------- style sheet, legacy API


def test_style_sheet_writes_png_and_pdf(tmp_path):
    paths = style_sheet(out_dir=tmp_path, name="sheet")
    assert {p.name for p in paths} == {"sheet.png", "sheet.pdf"}


def test_plot_airspace_still_works(tmp_path):
    fig = plot_airspace(save_path=tmp_path / "air.png")
    assert (tmp_path / "air.png").is_file()
    plt.close(fig)
