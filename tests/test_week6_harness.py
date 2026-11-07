"""Tests for the Week 6 experiment harness (experiments/week6.py)."""

from __future__ import annotations

import copy
import csv
import json
import math
from pathlib import Path

import numpy as np
import pytest

from config.load_config import get_config
from experiments import week6
from experiments.runner import run_experiment
from experiments.week6 import (
    NONDETERMINISTIC_COLUMNS,
    RUN_COLUMNS,
    aggregate,
    config_hash,
    config_overrides,
    expand_matrix,
    make_spec,
    read_rows,
    run_matrix,
    run_one,
    summarize,
    t_ppf,
)

GOLDEN = Path(__file__).parent / "data" / "week6_runner_golden.json"

# Tiny but real simulations: a few seconds of sim time keeps the suite fast.
TINY = dict(n_agents=6, seed=42, duration_s=2.0)


def _tiny(arch: str = "hierarchical", **kw):
    args = dict(TINY)
    args.update(kw)
    return make_spec(architecture=arch, **args)


def _comparable(row: dict) -> dict:
    """Row as CSV strings, without wall-time and output-path columns."""
    return {
        k: week6._fmt(v)
        for k, v in row.items()
        if k not in NONDETERMINISTIC_COLUMNS
    }


# --------------------------------------------------------------------------- runner


def test_runner_defaults_bit_identical_to_pre_week6_golden():
    """run_experiment's new opt-in hooks leave default behaviour unchanged.

    The golden rows were recorded from experiments/runner.py at 285920f
    (before the Week 6 hooks were added).
    """
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    for key, expected in golden.items():
        arch, att = key.split("|")
        att = att == "True"
        row = run_experiment(arch, 8, 42, duration_s=4.0, attack_enabled=att,
                             link_failure=att, attack_start_s=1.0)
        row.pop("wall_time_s")
        assert json.dumps(row, sort_keys=True) == json.dumps(expected, sort_keys=True), key


def test_runner_agent_transform_and_extra_loggers_are_used():
    calls = {"transform": 0, "log": 0}

    def transform(agents):
        calls["transform"] += 1
        return agents

    class Counter:
        def log_state(self, t, agents):
            calls["log"] += 1

    run_experiment("centralized", 4, 1, duration_s=0.5, agent_transform=transform,
                   extra_loggers=[Counter()])
    assert calls["transform"] == 1
    assert calls["log"] > 0


# --------------------------------------------------------------------------- spec hash


def test_spec_hash_is_stable_and_order_independent():
    a = make_spec(architecture="hierarchical", n_agents=60, seed=42, duration_s=180.0,
                  overrides={"admm.rho": 2.0, "admm.tolerance": 1e-3})
    b = make_spec(architecture="hierarchical", n_agents=60, seed=42, duration_s=180,
                  overrides=[("admm.tolerance", 1e-3), ("admm.rho", 2.0)])
    assert a.spec_hash() == b.spec_hash()
    assert len(a.spec_hash()) == 16
    # Literal value pins the hash across processes / Python versions.
    plain = make_spec(architecture="hierarchical", n_agents=60, seed=42, duration_s=180.0)
    assert plain.spec_hash() == make_spec(architecture="hierarchical", n_agents=60, seed=42,
                                          duration_s=180.0).spec_hash()
    assert plain.spec_hash() == "7b1f8fe8dc8170d8"


@pytest.mark.parametrize("field,value", [
    ("seed", 43), ("n_agents", 61), ("architecture", "centralized"), ("attack_enabled", True),
    ("link_failure", True), ("emergency", True), ("admm_max_iterations", 10), ("duration_s", 90.0),
])
def test_spec_hash_changes_with_any_field(field, value):
    base = dict(architecture="hierarchical", n_agents=60, seed=42, duration_s=180.0)
    changed = dict(base)
    changed[field] = value
    assert make_spec(**base).spec_hash() != make_spec(**changed).spec_hash()


# --------------------------------------------------------------------------- overrides


def test_config_overrides_restored_after_run():
    before = copy.deepcopy(get_config())
    spec = _tiny(admm_max_iterations=7, attack_enabled=True, attack_offset_m=11.0,
                 attack_start_s=0.5, overrides={"admm.rho": 3.5})
    with config_overrides(spec.config_overrides()) as cfg:
        assert cfg["admm"]["maximum_iterations"] == 7
        assert cfg["admm"]["rho"] == 3.5
        assert cfg["attack"]["offset_magnitude_meters"] == 11.0
    row = run_one(spec, out_dir=None, save_series=False)
    assert row["admm_max_iterations"] == 7
    assert row["attack_offset_m"] == 11.0
    assert get_config() == before


def test_config_overrides_restored_on_exception_and_reject_unknown_keys():
    before = copy.deepcopy(get_config())
    with pytest.raises(RuntimeError):
        with config_overrides({"admm.maximum_iterations": 3}):
            raise RuntimeError("boom")
    assert get_config() == before
    with pytest.raises(KeyError):
        with config_overrides({"admm.no_such_key": 1}):
            pass
    assert get_config() == before


# --------------------------------------------------------------------------- run_one


def test_same_seed_gives_identical_rows(tmp_path):
    spec = _tiny()
    r1 = run_one(spec, tmp_path / "a")
    r2 = run_one(spec, tmp_path / "b")
    assert list(r1) == RUN_COLUMNS
    assert _comparable(r1) == _comparable(r2)
    s1 = np.load(tmp_path / "a" / r1["series_file"])
    s2 = np.load(tmp_path / "b" / r2["series_file"])
    for k in ("t", "robustness", "violation"):
        np.testing.assert_array_equal(s1[k], s2[k])
    assert s1["violation"].dtype == bool
    np.testing.assert_array_equal(s1["violation"], s1["robustness"] < 0)


def test_identical_initial_conditions_across_architectures():
    rows = [run_one(_tiny(arch), out_dir=None, save_series=False)
            for arch in ("hierarchical", "centralized", "decentralized_undefended")]
    assert len({r["initial_conditions_hash"] for r in rows}) == 1
    ok, msg = week6.check_identical_conditions_week6(rows)
    assert ok, msg


def test_no_arrivals_reported_as_nan_not_zero():
    row = run_one(_tiny(), out_dir=None, save_series=False)
    assert row["arrivals"] == 0
    assert math.isnan(row["throughput_per_s"])
    if row["admm_events"] == 0:
        assert math.isnan(row["admm_nonconverged_frac"])
    assert math.isnan(row["attack_start_s"])  # attack disabled -> n/a


def test_emergency_run_records_emergency_columns():
    row = run_one(_tiny(emergency=True), out_dir=None, save_series=False)
    assert row["emergency"] is True
    assert row["emergency_id"] != ""
    assert 0.0 <= row["priority_compliance_rate"] <= 1.0
    assert math.isnan(row["emergency_travel_time_s"])  # 2 s is too short to arrive


# --------------------------------------------------------------------------- run_matrix


def test_resume_skips_completed_runs(tmp_path, monkeypatch):
    specs = [_tiny(seed=1), _tiny(seed=2)]
    logs: list[str] = []
    rows = run_matrix(specs, tmp_path, workers=1, log=logs.append)
    assert len(rows) == 2
    first = (tmp_path / "runs.csv").read_text(encoding="utf-8")
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    for key in ("command", "git_commit", "config_hash", "seeds", "agent_counts", "versions",
                "wall_time_s", "timestamp"):
        assert key in manifest
    assert manifest["seeds"] == [1, 2]
    assert set(manifest["versions"]) == {"python", "numpy", "matplotlib"}

    def must_not_run(*a, **k):
        raise AssertionError("completed run was re-executed")

    monkeypatch.setattr(week6, "run_one", must_not_run)
    logs.clear()
    rows2 = run_matrix(specs, tmp_path, workers=1, log=logs.append)
    assert "2 already done, 0 to run" in logs[0]
    assert (tmp_path / "runs.csv").read_text(encoding="utf-8") == first
    assert [r["spec_hash"] for r in rows2] == [s.spec_hash() for s in specs]
    monkeypatch.undo()

    # Adding one spec runs only that spec; order follows the spec list.
    specs3 = [_tiny(seed=3)] + specs
    logs.clear()
    rows3 = run_matrix(specs3, tmp_path, workers=1, log=logs.append)
    assert "2 already done, 1 to run" in logs[0]
    with open(tmp_path / "runs.csv", newline="", encoding="utf-8") as f:
        seeds = [r["seed"] for r in csv.DictReader(f)]
    assert seeds == ["3", "1", "2"]
    assert len(rows3) == 3


def test_matrix_csv_reproducible(tmp_path):
    specs = [_tiny("centralized", seed=5), _tiny("centralized", seed=6)]
    run_matrix(specs, tmp_path / "a", workers=1, log=lambda *_: None)
    run_matrix(specs, tmp_path / "b", workers=1, log=lambda *_: None)

    def load(p):
        with open(p / "runs.csv", newline="", encoding="utf-8") as f:
            return [{k: v for k, v in r.items() if k not in NONDETERMINISTIC_COLUMNS}
                    for r in csv.DictReader(f)]

    assert load(tmp_path / "a") == load(tmp_path / "b")


# --------------------------------------------------------------------------- aggregate


@pytest.mark.parametrize("df,expected", [
    (1, 12.7062047), (2, 4.3026527), (3, 3.1824463), (10, 2.2281389), (30, 2.0422725),
    (100, 1.9839715),
])
def test_t_ppf_matches_tables(df, expected):
    assert t_ppf(0.975, df) == pytest.approx(expected, abs=1e-6)


def test_aggregate_ci_math_on_hand_made_example(tmp_path):
    runs = tmp_path / "runs.csv"
    rows = [
        {"architecture": "A", "num_agents": "30", "m": "1"},
        {"architecture": "A", "num_agents": "30", "m": "2"},
        {"architecture": "A", "num_agents": "30", "m": "3"},
        {"architecture": "A", "num_agents": "30", "m": "4"},
        {"architecture": "A", "num_agents": "30", "m": "nan"},   # n/a: excluded
        {"architecture": "B", "num_agents": "30", "m": "5"},     # single value
        {"architecture": "C", "num_agents": "30", "m": "nan"},   # all n/a
    ]
    week6.write_csv(rows, runs, ["architecture", "num_agents", "m"])
    out = aggregate(runs, ["architecture", "num_agents"], ["m"], ci_level=0.95)
    a, b, c = out
    std = math.sqrt(5.0 / 3.0)                       # sample std of 1..4
    half = 3.182446305284263 * std / 2.0              # t_{0.975,3} * s / sqrt(4)
    assert a["m_mean"] == pytest.approx(2.5)
    assert a["m_std"] == pytest.approx(std)
    assert a["m_n"] == 4
    assert a["m_ci_lo"] == pytest.approx(2.5 - half, rel=1e-9)
    assert a["m_ci_hi"] == pytest.approx(2.5 + half, rel=1e-9)
    assert b["m_mean"] == 5.0 and b["m_n"] == 1 and math.isnan(b["m_std"]) and math.isnan(b["m_ci_lo"])
    assert c["m_n"] == 0 and math.isnan(c["m_mean"])
    with open(tmp_path / "summary.csv", newline="", encoding="utf-8") as f:
        header = next(csv.reader(f))
    assert header == ["architecture", "num_agents", "m_mean", "m_std", "m_n", "m_ci_lo", "m_ci_hi"]


def test_summarize_constant_values_zero_width_ci():
    s = summarize([2.0, 2.0, 2.0])
    assert s["std"] == 0.0 and s["ci_lo"] == 2.0 and s["ci_hi"] == 2.0


# --------------------------------------------------------------------------- matrices / CLI


def test_all_matrices_expand():
    cfg = get_config()
    names = cfg["experiments"]["week6"]["matrices"]
    assert {"e1", "e2", "e3", "e4", "e5", "e6"} <= set(names)
    for name in names:
        specs, used, _ = expand_matrix(name)
        assert specs, name
        assert len({s.spec_hash() for s in specs}) == len(specs)
        quick, qused, _ = expand_matrix(name, quick=True)
        q = cfg["experiments"]["week6"]["quick"]
        assert {s.n_agents for s in quick} == set(q["agent_counts"])
        assert {s.duration_s for s in quick} == {float(q["duration_s"])}
        assert len({s.seed for s in quick}) == q["n_seeds"]


def test_quick_e4_attack_starts_inside_short_run():
    specs, _, _ = expand_matrix("e4", quick=True)
    assert {s.architecture for s in specs} == {"hierarchical", "centralized", "decentralized_undefended"}
    attacked = [s for s in specs if s.attack_enabled]
    assert attacked
    for s in attacked:
        assert s.attack_start_s < s.duration_s


def test_cli_list(capsys):
    assert week6.main(["--list"]) == 0
    assert "e4:" in capsys.readouterr().out


def test_week6_config_sections_present():
    cfg = get_config()
    assert cfg["experiments"]["week6"]["provisional"] is True
    assert "visualization" in cfg


def test_rows_from_a_changed_config_are_archived_not_aggregated(tmp_path):
    spec = _tiny(seed=1)
    run_matrix([spec], tmp_path, workers=1, log=lambda *_: None)
    old = read_rows(tmp_path / "runs.csv")
    assert len(old) == 1 and old[0]["base_config_hash"] == config_hash()

    # Simulate a later change to base_config.yaml (e.g. a bug-fix parameter).
    logs: list[str] = []
    with config_overrides({"safety.minimum_separation_meters": 9.0}):
        new_base = config_hash()
        run_matrix([spec], tmp_path, workers=1, log=logs.append)
    assert any("moved 1 old row" in m for m in logs)

    rows = read_rows(tmp_path / "runs.csv")
    assert len(rows) == 1 and rows[0]["base_config_hash"] == new_base
    archived = read_rows(tmp_path / "runs_archive.csv")
    assert len(archived) == 1 and archived[0]["base_config_hash"] == old[0]["base_config_hash"]
    summary = aggregate(tmp_path / "runs.csv", ["architecture"], ["min_robustness_m"])
    assert summary[0]["min_robustness_m_n"] == 1
