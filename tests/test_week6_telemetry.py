"""Tests for the opt-in per-tick telemetry channel (simulation/telemetry.py)."""

from __future__ import annotations

import copy
import csv
import math

import numpy as np
import pytest

from conflict_resolution.solver import ADMMSolver
from experiments.runner import ARCHITECTURES, get_runner
from local_behavior.boids import reset_local_behavior_cache
from simulation.engine import run_simulation
from simulation.overseer import reset_default_overseer
from simulation.scenario import make_initial_agents
from simulation.telemetry import INFO_KEYS, TelemetryRecorder

ATTACK = {"enabled": True, "start_time_seconds": 1.0}
LINK = {"enabled": True, "down_start_seconds": 0.5, "down_end_seconds": 1.5}


def _reset():
    reset_default_overseer()
    reset_local_behavior_cache()


def _conflict_fleet(n: int = 8):
    """Agents packed inside the merge zone on one layer, so ADMM fires every tick."""
    agents = make_initial_agents(n, seed=1)
    for k, a in enumerate(agents):
        a.position = np.array([710.0 + 6.0 * k, 3.0 * (k % 2), 0.0])
        a.velocity = np.array([12.0, 0.0, 0.0])
        a.altitude_layer = 0
        a.corridor_assignment = None
    return agents


def _strip_timing(stats: dict) -> dict:
    return {k: v for k, v in stats.items() if k != "admm_time_s"}


def _run(arch: str, agents, duration_s: float, telemetry=None, **kw):
    _reset()
    runner = get_runner(arch)
    if telemetry is None:
        return runner(copy.deepcopy(agents), duration_s=duration_s, **kw)
    return runner(copy.deepcopy(agents), duration_s=duration_s, telemetry=telemetry, **kw)


# --------------------------------------------------------------------------- bit-identical


def test_telemetry_does_not_change_60_agent_20s_trajectory():
    """60 agents, 20 s, hierarchical, attack + link drop: identical with/without telemetry."""
    agents = make_initial_agents(60, seed=42)
    attack = {"enabled": True, "start_time_seconds": 10.0}
    link = {"enabled": True, "down_start_seconds": 5.0, "down_end_seconds": 15.0}

    _reset()
    plain = run_simulation(copy.deepcopy(agents), duration_s=20.0, attack_config=attack,
                           overseer_link_config=link)
    _reset()
    rec = TelemetryRecorder()
    with_tel = run_simulation(copy.deepcopy(agents), duration_s=20.0, attack_config=attack,
                              overseer_link_config=link, telemetry=rec)

    np.testing.assert_array_equal(plain.positions, with_tel.positions)
    np.testing.assert_array_equal(plain.velocities, with_tel.velocities)
    np.testing.assert_array_equal(plain.times, with_tel.times)
    assert _strip_timing(plain.stats) == _strip_timing(with_tel.stats)
    assert (plain.overseer_calls, plain.overseer_failures) == (with_tel.overseer_calls, with_tel.overseer_failures)
    assert len(rec) == len(plain.times) - 1


@pytest.mark.parametrize("arch", ["centralized", "decentralized_undefended"])
def test_telemetry_does_not_change_other_architectures(arch):
    agents = _conflict_fleet()
    plain = _run(arch, agents, 2.0, attack_config=ATTACK, overseer_link_config=LINK)
    with_tel = _run(arch, agents, 2.0, telemetry=TelemetryRecorder(), attack_config=ATTACK,
                    overseer_link_config=LINK)
    np.testing.assert_array_equal(plain.positions, with_tel.positions)
    assert _strip_timing(plain.stats) == _strip_timing(with_tel.stats)


def test_solver_is_unpatched_after_telemetry_run():
    original = ADMMSolver.solve
    _run("hierarchical", _conflict_fleet(), 0.5, telemetry=TelemetryRecorder())
    assert ADMMSolver.solve is original


# --------------------------------------------------------------------------- ADMM counts


@pytest.mark.parametrize("arch", ["hierarchical", "decentralized_undefended"])
def test_admm_counts_per_tick_sum_to_stats(arch):
    rec = TelemetryRecorder()
    result = _run(arch, _conflict_fleet(), 2.0, telemetry=rec)
    assert result.stats["admm_events"] > 0
    assert rec.total("admm_events_tick") == result.stats["admm_events"]
    assert rec.total("admm_nonconverged_tick") == result.stats["admm_nonconverged"]
    assert rec.total("admm_converged_tick") == result.stats["admm_events"] - result.stats["admm_nonconverged"]
    for _, info in rec.ticks:
        # iterations/timings exist only for groups that reached the solver
        assert len(info["admm_iterations"]) == len(info["admm_solve_ms"]) <= info["admm_events_tick"]
        assert all(i >= 1 for i in info["admm_iterations"])
        assert all(ms >= 0.0 for ms in info["admm_solve_ms"])


# --------------------------------------------------------------------------- all architectures


@pytest.mark.parametrize("arch", ARCHITECTURES)
def test_telemetry_works_for_all_architectures(arch):
    rec = TelemetryRecorder()
    agents = _conflict_fleet()
    result = _run(arch, agents, 2.0, telemetry=rec, attack_config=ATTACK, overseer_link_config=LINK)

    assert len(rec) == len(result.times) - 1
    np.testing.assert_allclose([t for t, _ in rec.ticks], result.times[1:])
    for t, info in rec.ticks:
        assert set(info) == set(INFO_KEYS)
        assert sum(info["layer_counts"].values()) == len(agents)
        assert sum(info["corridor_occupancy"].values()) <= len(agents)
    infos = [info for _, info in rec.ticks]
    # attack starts at 1.0 s: inactive before, active after
    assert not infos[0]["attack_active"] and infos[-1]["attack_active"]
    assert infos[-1]["malicious_ids"] == result.stats["malicious_ids"]
    assert sum(i["attack_active"] for i in infos) == result.stats["attack_active_ticks"]

    links = [info["overseer_link_up"] for info in infos]
    if arch == "decentralized_undefended":
        assert all(v is None for v in links)
        assert all(math.isnan(i["directive_age_s"]) for i in infos)
    else:
        assert False in links and True in links  # link down 0.5-1.5 s
        assert all(i["directive_age_s"] >= 0.0 for i in infos)
    if arch == "centralized":
        assert rec.total("admm_events_tick") == 0


def test_emergency_ids_reported():
    from simulation.priority_metrics import inject_emergency

    agents, eid = inject_emergency(make_initial_agents(6, seed=3))
    rec = TelemetryRecorder()
    _run("hierarchical", agents, 0.3, telemetry=rec)
    assert all(info["emergency_ids"] == [eid] for _, info in rec.ticks)


# --------------------------------------------------------------------------- CSV


def test_recorder_writes_expected_columns(tmp_path):
    rec = TelemetryRecorder()
    result = _run("hierarchical", _conflict_fleet(), 1.0, telemetry=rec, attack_config=ATTACK,
                  overseer_link_config=LINK)
    path = rec.to_csv(tmp_path / "telemetry.csv")
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        header = reader.fieldnames
    assert header == TelemetryRecorder.BASE_COLUMNS + ["occ_c0", "occ_c1", "occ_c2", "layer_0"]
    assert len(rows) == len(result.times) - 1
    assert sum(int(r["admm_events_tick"]) for r in rows) == result.stats["admm_events"]
    first = rows[0]
    assert first["overseer_link_up"] in ("True", "False")
    n_calls = int(first["admm_solver_calls"])
    assert len(first["admm_iterations"].split(";")) == n_calls
    assert float(first["admm_iterations_max"]) == max(int(x) for x in first["admm_iterations"].split(";"))


def test_recorder_csv_no_solver_calls_is_nan(tmp_path):
    rec = TelemetryRecorder()
    _run("centralized", make_initial_agents(4, seed=2), 0.3, telemetry=rec)
    with open(rec.to_csv(tmp_path / "t.csv"), newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert all(r["admm_iterations_mean"] == "nan" and r["admm_iterations"] == "" for r in rows)
    assert all(r["admm_events_tick"] == "0" for r in rows)


# --------------------------------------------------------------------------- main.py


def test_main_telemetry_flag_writes_csv(tmp_path):
    import main

    out = tmp_path / "run"
    assert main.main(["--scenario", "nominal", "--agents", "4", "--duration", "0.5",
                      "--out", str(out), "--telemetry"]) == 0
    with open(out / "telemetry.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 5


def test_main_without_flag_writes_no_telemetry(tmp_path):
    import main

    out = tmp_path / "run"
    assert main.main(["--scenario", "nominal", "--agents", "4", "--duration", "0.5",
                      "--out", str(out)]) == 0
    assert not (out / "telemetry.csv").exists()
