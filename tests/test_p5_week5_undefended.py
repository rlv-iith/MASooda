"""Tiny checks for the decentralized-undefended architecture."""

from __future__ import annotations

import copy

import numpy as np

from config.load_config import get_config
from local_behavior.boids import reset_local_behavior_cache
from resilience.decentralized_undefended import run_decentralized_undefended
from simulation.overseer import reset_default_overseer
from simulation.scenario import make_initial_agents


def _run(base, attack_cfg=None, link_cfg=None):
    reset_default_overseer()
    reset_local_behavior_cache()
    return run_decentralized_undefended(
        copy.deepcopy(base), duration_s=6.0, attack_config=attack_cfg,
        overseer_link_config=link_cfg,
    )


def _attack(enabled=True):
    return {**get_config()["attack"], "enabled": enabled, "start_time_seconds": 1.0}


def test_finishes_without_overseer():
    result = _run(make_initial_agents(10, 42))
    assert np.all(np.isfinite(result.positions))
    assert result.overseer_calls == 0


def test_attack_active_and_nothing_dropped():
    result = _run(make_initial_agents(10, 42), _attack())
    assert result.stats["attack_active_ticks"] > 0
    assert result.stats["reports_dropped"] == 0


def test_deterministic():
    base = make_initial_agents(10, 42)
    a = _run(base, _attack())
    b = _run(base, _attack())
    assert np.array_equal(a.positions, b.positions)


def test_link_config_ignored():
    link = {"enabled": True, "down_start_seconds": 1, "down_end_seconds": 2}
    result = _run(make_initial_agents(10, 42), link_cfg=link)
    assert result.overseer_calls == 0
