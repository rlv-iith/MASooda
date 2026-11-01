import numpy as np
import pytest
from simulation.schema import STLSpec
from verification import *
from verification.toy_trajectories import generate

SPEC = STLSpec(d_min=8.0, min_window_steps=2)


@pytest.fixture(scope="module", autouse=True)
def _csv(tmp_path_factory):
    generate("data/stl")


# ---------- Week 1: safe / unsafe classification ----------
def test_safe_trajectory_is_safe():
    r = stl_monitor(load_trajectory_csv("data/stl/safe_trajectory.csv"), SPEC)
    assert r.status == "OK" and not r.violation
    assert r.value == pytest.approx(4.0, abs=1e-6)


def test_unsafe_trajectory_is_flagged():
    r = stl_monitor(load_trajectory_csv("data/stl/unsafe_trajectory.csv"), SPEC)
    assert r.violation and r.value == pytest.approx(-5.0, abs=1e-6)
    assert r.worst_pair == (0, 1)
    assert r.worst_step == 100            # t = 10 s


def test_boundary_exactly_dmin_is_not_violation():
    w = np.array([[[0, 0], [8, 0]]] * 3, float)
    r = stl_monitor(w, SPEC)
    assert r.value == pytest.approx(0.0) and not r.violation


# ---------- failure behaviour (spec 4.8 / risk register) ----------
def test_startup_returns_neutral_not_violation():
    w = np.array([[[0, 0], [1, 0]]], float)      # 1 sample, agents 1 m apart
    r = stl_monitor(w, SPEC)
    assert r.status == "INSUFFICIENT_HISTORY" and not r.violation and r.value == 0.0


def test_nan_is_flagged_as_invalid_not_violation():
    w = np.full((3, 3, 2), np.nan)
    r = stl_monitor(w, SPEC)
    assert r.status == "INVALID_DATA" and not r.violation


def test_single_agent_no_crash():
    r = stl_monitor(np.zeros((5, 1, 2)), SPEC)
    assert r.status == "NOT_ENOUGH_AGENTS" and not r.violation


def test_garbage_input_no_crash():
    assert stl_monitor("abc", SPEC).status == "INVALID_DATA"
    assert stl_monitor(np.zeros(4), SPEC).status == "INVALID_DATA"


# ---------- Week 2: formula checks ----------
def test_rho_formula_matches_bruteforce():
    rng = np.random.default_rng(0)
    p = rng.uniform(0, 50, (20, 2))
    brute = min(np.linalg.norm(p[i] - p[j]) for i in range(20) for j in range(i + 1, 20)) - 8.0
    assert instantaneous_robustness(p, 8.0) == pytest.approx(brute)


def test_G_is_min_over_time():
    w = np.array([[[0, 0], [20, 0]], [[0, 0], [5, 0]], [[0, 0], [30, 0]]], float)
    assert stl_monitor(w, SPEC).value == pytest.approx(-3.0)


def test_sign_convention_pos_safe_neg_violation():
    assert stl_monitor(np.array([[[0, 0], [10, 0]]] * 2, float), SPEC).value > 0
    assert stl_monitor(np.array([[[0, 0], [6, 0]]] * 2, float), SPEC).value < 0


def test_sliding_monitor_matches_batch():
    traj = load_trajectory_csv("data/stl/unsafe_trajectory.csv")
    m = SlidingSTLMonitor(SPEC, window_steps=len(traj))
    last = None
    for snap in traj:
        last = m.update(snap)
    assert last.value == pytest.approx(stl_monitor(traj, SPEC).value)
    assert m.update(traj[0]).status == "OK"


def test_sliding_monitor_startup_neutral():
    m = SlidingSTLMonitor(SPEC, window_steps=5)
    assert m.update(np.array([[0, 0], [1, 0]], float)).status == "INSUFFICIENT_HISTORY"


def test_3d_positions_supported():
    w = np.array([[[0, 0, 0], [0, 0, 6]]] * 2, float)
    assert stl_monitor(w, SPEC).value == pytest.approx(-2.0)


def test_liveness_optional():
    w = np.array([[[0, 0]], [[50, 0]], [[99, 0]]], float)
    assert liveness_robustness(w, np.array([[100, 0]]), radius=5.0) == pytest.approx(4.0)
    assert liveness_robustness(w[:2], np.array([[100, 0]]), radius=5.0) < 0


def test_spec_loaded_from_config():
    spec = load_spec_from_config()
    assert spec.d_min == 8.0 and spec.dt == 0.1
