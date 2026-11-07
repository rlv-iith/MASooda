"""Tests for E4: paired attack effect, post-attack column, scripts on --quick."""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import numpy as np
import pytest

from experiments import week6_common
from experiments.week6 import expand_matrix, make_spec, run_one

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _r(arch, seed, on, viol, offset="25.0", post="nan", rec="nan"):
    return {"architecture": arch, "num_agents": "60", "seed": str(seed), "attack_enabled": str(on),
            "attack_offset_m": offset if on else "nan", "safety_violation_ticks": str(viol),
            "post_attack_violation_ticks": post, "mean_recovery_time_s": rec}


def test_paired_effect_math_on_hand_made_example():
    plot = _load("week6_e4_plot")
    runs = [
        _r("hierarchical", 42, False, 2), _r("hierarchical", 42, True, 7, post="5"),
        _r("hierarchical", 43, False, 0), _r("hierarchical", 43, True, 0, post="0"),
        _r("hierarchical", 43, True, 9, offset="50.0"),         # non-default offset: not paired
        _r("centralized", 42, True, 4),                          # no attack-off partner: dropped
        _r("centralized", 43, False, 1, rec="2.0"), _r("centralized", 43, True, 3, rec="nan"),
    ]
    eff = plot.paired_effects(runs, ["safety_violation_ticks", "post_attack_violation_ticks_on",
                                     "mean_recovery_time_s"], 25.0)
    assert [(e["architecture"], e["seed"]) for e in eff] == [("centralized", 43), ("hierarchical", 42),
                                                             ("hierarchical", 43)]
    assert [e["safety_violation_ticks"] for e in eff] == [2.0, 5.0, 0.0]
    assert eff[1]["post_attack_violation_ticks_on"] == 5.0
    assert math.isnan(eff[0]["mean_recovery_time_s"])  # NaN on one side -> NaN, never 0


def test_effect_verdict():
    plot = _load("week6_e4_plot")
    row = {"m_mean": "2.0", "m_ci_lo": "0.5", "m_ci_hi": "3.5"}
    assert plot.effect_verdict(row, ["m"]) == "measurable"
    assert plot.effect_verdict({"m_mean": "0.0", "m_ci_lo": "-1", "m_ci_hi": "1"}, ["m"]) == "none"
    assert plot.effect_verdict({"m_mean": "nan"}, ["m"]) == "n/a"


def test_post_attack_violation_ticks_matches_series(tmp_path):
    spec = make_spec(architecture="decentralized_undefended", n_agents=10, seed=42, duration_s=3.0,
                     attack_enabled=True, attack_start_s=1.0)
    row = run_one(spec, tmp_path)
    s = np.load(tmp_path / row["series_file"])
    assert row["post_attack_violation_ticks"] == int(np.sum((s["t"] >= 1.0) & (s["robustness"] < 0)))
    off = run_one(make_spec(architecture="centralized", n_agents=6, seed=42, duration_s=1.0), None, False)
    assert math.isnan(off["post_attack_violation_ticks"])  # undefined without an attack


def test_e4_offset_shares_default_offset_runs():
    e4, _, _ = expand_matrix("e4")
    off, _, _ = expand_matrix("e4_offset")
    shared = {s.spec_hash() for s in e4} & {s.spec_hash() for s in off}
    assert len(shared) == 9  # 3 architectures x seeds 42-44 at the default offset
    assert len(e4) == 30 and len(off) == 36


@pytest.fixture()
def quick_root(tmp_path, monkeypatch):
    monkeypatch.setattr(week6_common, "week6_root", lambda quick=False: tmp_path)
    return tmp_path


def test_e4_scripts_run_end_to_end_on_quick(quick_root):
    assert _load("week6_e4_run").main(["--quick", "--workers", "1", "--only", "e4"]) == 0
    plot = _load("week6_e4_plot")
    assert plot.main(["--quick"]) == 0
    for name in plot.FIGS:
        assert (quick_root / "figures" / f"{name}.png").is_file(), name
    d = quick_root / "e4_resilience"
    assert (d / "attack_effect.csv").is_file()
    readme = (d / "README.md").read_text(encoding="utf-8")
    assert "measurable effect" in readme
    assert week6_common.check_readme_tables(d / "README.md") == []
