"""Tests for E1 (ADMM scaling): per-run ADMM columns, iteration-limit override, shared
runs between matrices, and the run/plot scripts on --quick."""

from __future__ import annotations

import csv
import importlib.util
import math
from pathlib import Path

import numpy as np
import pytest

from experiments import week6_common
from experiments.week6 import ADMM_COLUMNS, expand_matrix, make_spec, run_one

ROOT = Path(__file__).resolve().parent.parent

# Conflicts everywhere (not only in the merge zone) so a short run makes solver calls.
CONFLICTS = {"admm.merge_zone_only": False, "admm.detection_radius_meters": 60.0}


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_admm_columns_filled_when_solver_calls_happen(tmp_path):
    row = run_one(make_spec(architecture="hierarchical", n_agents=10, seed=42, duration_s=1.0,
                            overrides=CONFLICTS), tmp_path)
    assert row["admm_solver_calls"] > 0
    for c in ADMM_COLUMNS:
        assert math.isfinite(float(row[c])), c
    assert 0.0 <= row["admm_converged_frac"] <= 1.0
    assert row["admm_iter_mean"] <= row["admm_iter_p95"] <= row["admm_iter_max"]
    calls = np.load(tmp_path / row["calls_file"])
    assert len(calls["iterations"]) == row["admm_solver_calls"]
    assert row["admm_max_group_size"] == int(calls["group_size"].max())


def test_admm_columns_nan_without_solver_calls():
    row = run_one(make_spec(architecture="hierarchical", n_agents=6, seed=42, duration_s=1.0),
                  out_dir=None, save_series=False)
    assert row["admm_solver_calls"] == 0
    for c in ADMM_COLUMNS:
        if c != "admm_solver_calls":
            assert math.isnan(float(row[c])), c


def test_centralized_has_no_admm_calls():
    row = run_one(make_spec(architecture="centralized", n_agents=6, seed=42, duration_s=1.0,
                            overrides=CONFLICTS), out_dir=None, save_series=False)
    assert row["admm_solver_calls"] == 0 and math.isnan(row["admm_iter_mean"])


def test_iteration_limit_override_reaches_solver(tmp_path):
    row = run_one(make_spec(architecture="hierarchical", n_agents=10, seed=42, duration_s=1.0,
                            admm_max_iterations=3, overrides=CONFLICTS), tmp_path)
    assert row["admm_max_iterations"] == 3
    calls = np.load(tmp_path / row["calls_file"])
    assert len(calls["iterations"]) > 0
    assert int(calls["iterations"].max()) <= 3
    assert row["admm_iter_max"] <= 3


def test_e1_and_e1_iter_share_the_n60_default_limit_runs():
    e1, used1, _ = expand_matrix("e1")
    it, used2, _ = expand_matrix("e1_iter")
    assert used1["output_subdir"] == used2["output_subdir"]
    shared = {s.spec_hash() for s in e1} & {s.spec_hash() for s in it}
    assert len(shared) == len(used1["seeds"]) == 3
    shared_specs = [s for s in it if s.spec_hash() in shared]
    assert all(s.n_agents == 60 and s.admm_max_iterations is None for s in shared_specs)
    assert len({s.spec_hash() for s in e1} | {s.spec_hash() for s in it}) == 24


@pytest.fixture()
def quick_root(tmp_path, monkeypatch):
    monkeypatch.setattr(week6_common, "week6_root", lambda quick=False: tmp_path)
    return tmp_path


def test_e1_scripts_run_end_to_end_on_quick(quick_root):
    run = _load("week6_e1_run")
    plot = _load("week6_e1_plot")
    monkey_root = quick_root
    assert run.main(["--quick", "--workers", "1"]) == 0
    d = monkey_root / "e1_admm_scaling"
    for f in ("runs.csv", "summary.csv", "calls.csv", "weak_results.json", "manifest.json"):
        assert (d / f).is_file(), f
    with open(d / "summary.csv", newline="", encoding="utf-8") as f:
        summary = list(csv.DictReader(f))
    assert {r["admm_max_iterations"] for r in summary} == {"5", "10", "20", "50", "100"}
    assert plot.main(["--quick"]) == 0
    for name in plot.FIGS:
        assert (monkey_root / "figures" / f"{name}.png").is_file(), name
        assert (monkey_root / "figures" / f"{name}.pdf").is_file(), name
    readme = (d / "README.md").read_text(encoding="utf-8")
    assert "admm.max_group_size" in readme and "admm.merge_zone_only" in readme
    assert week6_common.check_readme_tables(d / "README.md") == []
