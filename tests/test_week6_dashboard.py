"""Tests for the dual-panel dashboard (headless): record, replay and live modes."""

from __future__ import annotations

import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import numpy as np
import pytest

from visualization import dashboard as dash


@pytest.fixture(scope="module")
def run5(tmp_path_factory):
    """A 5-second mvp run (attack from 1 s so the ghost is exercised) saved as replay files."""
    d = tmp_path_factory.mktemp("run5")
    from config.load_config import get_config

    cfg = get_config()
    old = cfg["attack"]["start_time_seconds"]
    cfg["attack"]["start_time_seconds"] = 1.0
    try:
        dash.simulate("hierarchical", "mvp", 12, 42, 5.0, run_dir=d)
    finally:
        cfg["attack"]["start_time_seconds"] = old
    return d


def test_simulate_writes_replay_files(run5):
    for f in ("trajectory.csv", "telemetry.csv", "stl_robustness.csv", "run_info.json"):
        assert (run5 / f).is_file(), f


def test_load_replay_aligns_series(run5):
    data = dash.load_replay(run5)
    assert len(data) == 51  # t = 0 .. 5 s at dt = 0.1
    n = len(data.ids)
    for name in ("rho", "link_up", "directive_age", "attack_active", "admm_conv", "admm_nonconv", "admm_iters",
                 "compliance", "malicious_ids"):
        assert len(getattr(data, name)) == len(data), name
    assert data.pos[0].shape == (n, 2)
    assert data.attack_cfg and data.attack_cfg["enabled"]
    assert any(data.attack_active) and any(data.malicious_ids)
    assert math.isnan(data.link_up[0])  # no telemetry at t = 0


def test_renders_three_frames_in_replay_mode(run5, tmp_path):
    data = dash.load_replay(run5)
    out = dash.record(data, tmp_path / "replay.gif", frames=[0, 25, 50], fps=5)
    assert out.is_file() and out.stat().st_size > 1000
    from PIL import Image

    with Image.open(out) as im:
        assert im.n_frames == 3


def test_ghost_drawn_for_malicious_agent(run5):
    data = dash.load_replay(run5)
    k = next(i for i, m in enumerate(data.malicious_ids) if m)
    d = dash.Dashboard(data)
    d.update(k)
    assert len(d.mal.get_offsets()) == 1 and len(d.ghost.get_offsets()) == 1
    true_p, ghost_p = d.mal.get_offsets()[0], d.ghost.get_offsets()[0]
    assert np.linalg.norm(np.asarray(ghost_p) - np.asarray(true_p)) > 1.0
    import matplotlib.pyplot as plt

    plt.close(d.fig)


def test_record_mode_cli_three_frames(tmp_path):
    out = tmp_path / "rec.gif"
    assert dash.main(["--record", str(out), "--scenario", "nominal", "--agents", "8", "--duration", "1.0",
                      "--stride", "5", "--run-dir", str(tmp_path / "run"), "--frame-png", "0.5"]) == 0
    from PIL import Image

    with Image.open(out) as im:
        assert im.n_frames == 3  # t = 0, 0.5, 1.0
    assert (tmp_path / "rec_t0.png").is_file() or list(tmp_path.glob("rec_t*.png"))


def test_replay_of_main_telemetry_output(tmp_path):
    import main

    out = tmp_path / "mvp"
    assert main.main(["--scenario", "mvp", "--agents", "6", "--duration", "1.0", "--out", str(out),
                      "--telemetry"]) == 0
    data = dash.load_replay(out)
    assert data.architecture == "hierarchical" and len(data) == 11
    assert dash.main(["--replay", str(out), "--out", str(tmp_path / "r.gif"), "--stride", "5"]) == 0
    assert (tmp_path / "r.gif").is_file()


def test_live_mode_headless_refreshes():
    stats = dash.run_live("hierarchical", "nominal", 6, 1, 1.0, show=False)
    assert stats["refreshes"] >= 2 and stats["draw_ms_mean"] > 0


def test_record_10_second_smoke(tmp_path):
    out = tmp_path / "ten.gif"
    assert dash.main(["--record", str(out), "--scenario", "demo", "--agents", "10", "--duration", "10",
                      "--stride", "10", "--run-dir", str(tmp_path / "run10")]) == 0
    from PIL import Image

    with Image.open(out) as im:
        assert im.n_frames == 11
    info = (tmp_path / "run10" / "run_info.json").read_text(encoding="utf-8")
    assert '"inject_emergency": true' in info
