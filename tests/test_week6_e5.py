"""Tests for E5: STL summary from hand-made series and the missing-combination listing."""

from __future__ import annotations

import csv
import importlib.util
import math
from pathlib import Path

import numpy as np
import pytest

from experiments.week6 import config_hash, write_csv

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


B = _load("week6_e5_build")


def test_series_stats_hand_made():
    t = np.arange(10) * 0.1
    rho = np.array([3.0, 2.0, 1.0, -1.0, -2.0, 0.5, 1.0, 2.0, 3.0, 4.0])
    s = B.series_stats(t, rho)
    assert s["min_robustness_m"] == -2.0
    assert s["violation_fraction"] == pytest.approx(0.2)
    assert s["p5_robustness_m"] == pytest.approx(np.percentile(rho, 5.0))
    empty = B.series_stats(t, np.full(10, np.inf))
    assert math.isnan(empty["min_robustness_m"]) and math.isnan(empty["violation_fraction"])


def _fake_source(root: Path, folder: str, rows: list[dict]) -> None:
    d = root / folder
    (d / "series").mkdir(parents=True)
    out = []
    for i, r in enumerate(rows):
        f = f"series/s{i}.npz"
        np.savez_compressed(d / f, t=np.arange(4) * 0.1, robustness=np.asarray(r.pop("rho"), float))
        out.append({"base_config_hash": config_hash(), "series_file": f, "spec_hash": f"h{folder}{i}",
                    "attack_enabled": "False", "link_failure": "False", "emergency": "False",
                    "emergency_control": "False", "admm_max_iterations": "50", "attack_offset_m": "nan",
                    "violation_episodes": "0", "mean_recovery_time_s": "nan", "max_recovery_time_s": "nan", **r})
    write_csv(out, d / "runs.csv", list(out[0].keys()))


def test_collect_and_missing_combination_listing(tmp_path):
    _fake_source(tmp_path, "e4_resilience", [
        {"architecture": "centralized", "num_agents": "60", "seed": "42", "rho": [1, 2, 3, 4]},
        {"architecture": "decentralized_undefended", "num_agents": "60", "seed": "42", "rho": [1, -1, 1, 1],
         "violation_episodes": "1"},
        {"architecture": "centralized", "num_agents": "30", "seed": "42", "attack_enabled": "True",
         "attack_offset_m": "25", "rho": [1, 1, 1, 1]},  # attack run: not nominal
    ])
    _fake_source(tmp_path, "e1_admm_scaling", [
        {"architecture": "hierarchical", "num_agents": "30", "seed": "42", "rho": [5, 5, 5, 5]},
        {"architecture": "hierarchical", "num_agents": "30", "seed": "43", "admm_max_iterations": "5",
         "rho": [5, 5, 5, 5]},
    ])
    rows = B.collect(tmp_path)
    assert len(rows) == 5
    conds = sorted(r["condition"] for r in rows)
    assert conds == ["ADMM limit 5", "attack 25 m", "nominal", "nominal", "nominal"]
    missing = B.missing_combinations(rows, [30, 60])
    assert missing == [("centralized", 30), ("decentralized_undefended", 30)]
    dec = next(r for r in rows if r["architecture"] == "decentralized_undefended")
    assert dec["violation_fraction"] == 0.25 and dec["min_robustness_m"] == -1.0


def test_stale_rows_are_ignored(tmp_path):
    _fake_source(tmp_path, "e2_formation", [
        {"architecture": "hierarchical", "num_agents": "30", "seed": "42", "rho": [1, 1, 1, 1],
         "base_config_hash": "old"},
    ])
    assert B.collect(tmp_path) == []


def test_pooled_nominal_dedupes_identical_runs():
    rows = [
        {"architecture": "hierarchical", "num_agents": 30, "seed": 42, "source": "e1_admm_scaling",
         "condition": "nominal"},
        {"architecture": "hierarchical", "num_agents": 30, "seed": 42, "source": "e2_formation",
         "condition": "nominal"},
        {"architecture": "hierarchical", "num_agents": 30, "seed": 43, "source": "e2_formation",
         "condition": "nominal"},
        {"architecture": "hierarchical", "num_agents": 30, "seed": 44, "source": "e2_formation",
         "condition": "emergency"},
    ]
    pooled = B.pooled_nominal(rows)
    assert [(r["seed"], r["source"]) for r in pooled] == [(42, "e1_admm_scaling"), (43, "e2_formation")]
