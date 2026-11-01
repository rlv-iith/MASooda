"""Tests for main CLI entrypoint."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

import main


@pytest.fixture(autouse=True)
def clean_boids_cache():
    """Clean module-level boids cache after each test to avoid state leakage."""
    yield
    try:
        import local_behavior.boids as boids
        boids._last_corridor.clear()
    except Exception:
        pass


def test_main_mvp_run(tmp_path: Path) -> None:
    """main runs an mvp scenario and produces metrics.json with min_robustness."""
    ret = main.main(["--scenario", "mvp", "--agents", "12", "--duration", "8", "--out", str(tmp_path)])
    assert ret == 0

    metrics_file = tmp_path / "metrics.json"
    assert metrics_file.exists(), "metrics.json was not created"

    with open(metrics_file, "r", encoding="utf-8") as f:
        metrics = json.load(f)

    assert "min_robustness" in metrics or "min_robustness_m" in metrics
    assert (tmp_path / "stl_robustness.csv").exists()
    assert (tmp_path / "trajectory.csv").exists()
    assert (tmp_path / "final_frame.png").exists()


def test_main_corridors_mismatch() -> None:
    """--corridors 4 exits with code 2 when config count is 3."""
    with pytest.raises(SystemExit) as exc_info:
        main.main(["--corridors", "4"])
    assert exc_info.value.code == 2

