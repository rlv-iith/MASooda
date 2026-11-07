"""Tests for E3 (priority, paired control) and E6 (graceful degradation)."""

from __future__ import annotations

import csv
import importlib.util
import json
import math
from pathlib import Path

import numpy as np
import pytest

from experiments import week6_common
from experiments.week6 import expand_matrix, make_spec, run_one
from simulation.priority_metrics import inject_emergency
from simulation.scenario import make_initial_agents

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_e3_matrix_pairs_every_emergency_run_with_a_control():
    specs, _, _ = expand_matrix("e3")
    em = {(s.n_agents, s.seed) for s in specs if s.emergency and not s.emergency_control}
    ctrl = {(s.n_agents, s.seed) for s in specs if s.emergency and s.emergency_control}
    assert em == ctrl and len(em) == 12 and len(specs) == 24


def test_control_run_uses_same_agent_as_delivery(tmp_path):
    em = run_one(make_spec(architecture="hierarchical", n_agents=8, seed=3, duration_s=1.0, emergency=True), tmp_path)
    ctrl = run_one(make_spec(architecture="hierarchical", n_agents=8, seed=3, duration_s=1.0, emergency=True,
                             emergency_control=True), tmp_path)
    _, eid = inject_emergency(make_initial_agents(8, seed=3))
    assert em["emergency_id"] == ctrl["emergency_id"] == eid
    assert em["initial_conditions_hash"] != ctrl["initial_conditions_hash"]  # only the agent type differs
    fe, fc = np.load(tmp_path / em["frames_file"]), np.load(tmp_path / ctrl["frames_file"])
    i = int(np.where(fe["ids"] == eid)[0][0])
    assert str(fe["types"][i]) == "EMERGENCY" and str(fc["types"][i]) == "DELIVERY"
    np.testing.assert_array_equal(fe["positions"][0], fc["positions"][0])
    assert json.loads((tmp_path / em["arrivals_file"]).read_text())  # arrival times saved


def test_e3_columns_present():
    row = run_one(make_spec(architecture="hierarchical", n_agents=6, seed=1, duration_s=0.5, emergency=True),
                  out_dir=None, save_series=False)
    for c in ("priority_compliance_rate", "emergency_delay_s", "emergency_nominal_time_s", "emergency_control"):
        assert c in row
    assert math.isnan(row["emergency_delay_s"])  # did not arrive in 0.5 s -> n/a, not 0


def test_e6_columns_present():
    row = run_one(make_spec(architecture="hierarchical", n_agents=6, seed=1, duration_s=0.5, link_failure=True),
                  out_dir=None, save_series=False)
    for c in ("overseer_failures", "overseer_dropped", "max_directive_staleness_s"):
        assert c in row


def test_directive_refresh_detection():
    rm = _load("week6_e6_run")
    t = np.arange(0, 10, 1.0)
    stale = np.array([0, 1, 0, 1, 2, 3, 4, 5, 0, 1], dtype=float)  # no reset inside [3, 8)
    assert rm.directive_refresh(t, stale, 3.0, 8.0) == (5.0, False)
    assert rm.directive_refresh(t, stale, 1.0, 4.0)[1] is True
    assert rm.directive_refresh(t, stale, 20.0, 30.0)[1] is None


@pytest.fixture()
def quick_root(tmp_path, monkeypatch):
    monkeypatch.setattr(week6_common, "week6_root", lambda quick=False: tmp_path)
    return tmp_path


def test_e3_scripts_run_end_to_end_on_quick(quick_root):
    assert _load("week6_e3_run").main(["--quick", "--workers", "1"]) == 0
    d = quick_root / "e3_priority"
    with open(d / "pairs.csv", newline="", encoding="utf-8") as f:
        pairs = list(csv.DictReader(f))
    assert len(pairs) == 1 and pairs[0]["emergency_spec_hash"] != pairs[0]["control_spec_hash"]
    plot = _load("week6_e3_plot")
    assert plot.main(["--quick"]) == 0
    for name in plot.FIGS:
        assert (quick_root / "figures" / f"{name}.png").is_file(), name
    assert week6_common.check_readme_tables(d / "README.md") == []


def test_e6_scripts_run_end_to_end_on_quick(quick_root):
    assert _load("week6_e6_run").main(["--quick", "--workers", "1"]) == 0
    d = quick_root / "e6_degradation"
    with open(d / "degradation.csv", newline="", encoding="utf-8") as f:
        deg = list(csv.DictReader(f))
    assert len(deg) == 1
    plot = _load("week6_e6_plot")
    assert plot.main(["--quick"]) == 0
    for name in plot.FIGS:
        assert (quick_root / "figures" / f"{name}.png").is_file(), name
    readme = (d / "README.md").read_text(encoding="utf-8")
    assert "Outage behaviour" in readme
    assert week6_common.check_readme_tables(d / "README.md") == []
