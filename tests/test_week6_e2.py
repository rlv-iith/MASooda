"""Tests for E2 (formation / merge / utilisation columns and scripts on --quick)."""

from __future__ import annotations

import csv
import importlib.util
import math
from pathlib import Path

import numpy as np
import pytest

from experiments import week6_common
from experiments.week6 import FORMATION_COLUMNS, RUN_COLUMNS, make_spec, run_one

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_formation_columns_present_and_typed(tmp_path):
    row = run_one(make_spec(architecture="hierarchical", n_agents=8, seed=42, duration_s=2.0), tmp_path)
    for c in FORMATION_COLUMNS:
        assert c in row and c in RUN_COLUMNS
    for c in ("util_mean_c0", "util_peak_c0", "util_mean_c2"):
        assert math.isfinite(row[c]) and row[c] >= 0.0
    assert row["util_mean_c0"] <= row["util_peak_c0"]
    occ = np.load(tmp_path / row["occupancy_file"])
    assert occ["occupancy"].shape == (20, 3)
    frames = np.load(tmp_path / row["frames_file"])
    assert frames["positions"].shape[1] == 8


def test_merge_success_rate_nan_without_attempts():
    # 2 s is far too short to reach the end of the merge zone: no attempts
    row = run_one(make_spec(architecture="hierarchical", n_agents=6, seed=42, duration_s=2.0),
                  out_dir=None, save_series=False)
    assert row["merge_attempts"] == 0
    assert math.isnan(row["merge_success_rate"])
    assert row["not_reached"] == 6


@pytest.fixture()
def quick_root(tmp_path, monkeypatch):
    monkeypatch.setattr(week6_common, "week6_root", lambda quick=False: tmp_path)
    return tmp_path


def test_e2_scripts_run_end_to_end_on_quick(quick_root):
    assert _load("week6_e2_run").main(["--quick", "--workers", "1"]) == 0
    d = quick_root / "e2_formation"
    with open(d / "summary.csv", newline="", encoding="utf-8") as f:
        header = next(csv.reader(f))
    assert "merge_success_rate_mean" in header and "util_peak_c1_mean" in header
    plot = _load("week6_e2_plot")
    assert plot.main(["--quick"]) == 0
    for name in plot.FIGS:
        assert (quick_root / "figures" / f"{name}.png").is_file(), name
    readme = (d / "README.md").read_text(encoding="utf-8")
    assert "n/a" in readme  # quick runs have no merge attempts -> success rate n/a, never 0
    assert week6_common.check_readme_tables(d / "README.md") == []
