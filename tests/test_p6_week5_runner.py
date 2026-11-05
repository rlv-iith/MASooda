"""Unit tests for P6 Week 5 experiment runner and multi-architecture validation."""

from __future__ import annotations

from pathlib import Path
import pytest

from experiments.runner import (
    ARCHITECTURES,
    STANDARD_COLUMNS,
    check_identical_conditions,
    get_runner,
    initial_conditions_hash,
    run_experiment,
    write_rows,
)
import main
from simulation.overseer import reset_default_overseer
from simulation.scenario import make_initial_agents


@pytest.fixture(autouse=True)
def clean_state():
    """Reset overseer and boids caches before and after each test."""
    reset_default_overseer()
    try:
        from local_behavior.boids import reset_local_behavior_cache
        reset_local_behavior_cache()
    except Exception:
        pass
    yield
    reset_default_overseer()
    try:
        from local_behavior.boids import reset_local_behavior_cache
        reset_local_behavior_cache()
    except Exception:
        pass


def test_run_experiment_hierarchical_returns_standard_columns():
    """run_experiment on hierarchical architecture returns exactly STANDARD_COLUMNS."""
    row = run_experiment("hierarchical", n_agents=10, seed=42, duration_s=3.0)
    assert list(row.keys()) == STANDARD_COLUMNS
    assert row["architecture"] == "hierarchical"
    assert row["num_agents"] == 10
    assert row["seed"] == 42
    assert row["duration_s"] == 3.0


def test_initial_conditions_hash():
    """initial_conditions_hash is deterministic for identical (n, seed) and distinct for different seeds."""
    agents1 = make_initial_agents(10, seed=42)
    agents2 = make_initial_agents(10, seed=42)
    agents3 = make_initial_agents(10, seed=43)

    h1 = initial_conditions_hash(agents1)
    h2 = initial_conditions_hash(agents2)
    h3 = initial_conditions_hash(agents3)

    assert h1 == h2
    assert h1 != h3
    assert len(h1) == 64


def test_get_runner_bogus():
    """get_runner raises ValueError for unknown architecture name."""
    with pytest.raises(ValueError):
        get_runner("bogus")


def test_check_identical_conditions_detects_mismatch():
    """check_identical_conditions flags hash divergence for same (seed, num_agents)."""
    valid_rows = [
        {"seed": 42, "num_agents": 10, "initial_conditions_hash": "hash_a"},
        {"seed": 42, "num_agents": 10, "initial_conditions_hash": "hash_a"},
        {"seed": 43, "num_agents": 10, "initial_conditions_hash": "hash_b"},
    ]
    ok, msg = check_identical_conditions(valid_rows)
    assert ok is True

    divergent_rows = [
        {"seed": 42, "num_agents": 10, "initial_conditions_hash": "hash_a"},
        {"seed": 42, "num_agents": 10, "initial_conditions_hash": "hash_x"},
    ]
    ok, msg = check_identical_conditions(divergent_rows)
    assert ok is False
    assert "Mismatch" in msg


def test_write_rows_creates_csv_with_standard_columns(tmp_path: Path):
    """write_rows writes a valid CSV whose header matches STANDARD_COLUMNS."""
    csv_path = tmp_path / "sub" / "output.csv"
    dummy_row = {col: 0 for col in STANDARD_COLUMNS}
    write_rows([dummy_row], csv_path)

    assert csv_path.exists()
    with open(csv_path, "r", encoding="utf-8") as f:
        header = f.readline().strip().split(",")
    assert header == STANDARD_COLUMNS


def test_main_cli_nominal_creates_run_row(tmp_path: Path):
    """main CLI with --scenario nominal generates run_row.csv with STANDARD_COLUMNS."""
    ret = main.main([
        "--scenario", "nominal",
        "--agents", "10",
        "--duration", "2",
        "--out", str(tmp_path),
    ])
    assert ret == 0
    row_file = tmp_path / "run_row.csv"
    assert row_file.exists()

    with open(row_file, "r", encoding="utf-8") as f:
        header = f.readline().strip().split(",")
    assert header == STANDARD_COLUMNS


def test_centralized_runner_if_available():
    """If simulation.centralized is present, verify run_experiment returns STANDARD_COLUMNS."""
    pytest.importorskip("simulation.centralized")
    row = run_experiment("centralized", n_agents=10, seed=42, duration_s=2.0)
    assert list(row.keys()) == STANDARD_COLUMNS


def test_decentralized_undefended_runner_if_available():
    """If resilience.decentralized_undefended is present, verify run_experiment returns STANDARD_COLUMNS."""
    pytest.importorskip("resilience.decentralized_undefended")
    row = run_experiment("decentralized_undefended", n_agents=10, seed=42, duration_s=2.0)
    assert list(row.keys()) == STANDARD_COLUMNS

