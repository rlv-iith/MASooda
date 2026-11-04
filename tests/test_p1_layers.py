"""P1 tests for 2.5D layer handling in the simulation loop."""

from __future__ import annotations

import numpy as np
import pytest

from simulation.engine import run_simulation
from simulation.logger import TrajectoryLogger
from simulation.schema import AgentState, AgentType, OverseerDirective


@pytest.fixture(autouse=True)
def clean_boids_cache():
    yield
    try:
        import local_behavior.boids as boids
        boids._last_corridor.clear()
    except Exception:
        pass


def make_pair(layer0: int, layer1: int) -> list[AgentState]:
    agents = []
    for i, (y, layer) in enumerate([(0.0, layer0), (5.0, layer1)]):
        agents.append(
            AgentState(
                id=i,
                type=AgentType.DELIVERY,
                position=np.array([50.0, y, float(layer)]),
                velocity=np.array([5.0, 0.0, 0.0]),
                destination=np.array([1500.0, y, float(layer)]),
                corridor_assignment=0,
                altitude_layer=layer,
            )
        )
    return agents


def max_abs_vy(result, idx: int = 0) -> float:
    return float(np.max(np.abs(result.velocities[:, idx, 1])))


def test_different_layers_do_not_interact() -> None:
    result = run_simulation(make_pair(0, 1), duration_s=2.0, use_overseer=False, use_admm=False)
    assert max_abs_vy(result) < 1e-6


def test_same_layer_agents_push_apart() -> None:
    result = run_simulation(make_pair(0, 0), duration_s=2.0, use_overseer=False, use_admm=False)
    assert max_abs_vy(result) > 1e-3


def test_directive_altitude_map_is_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_overseer(snapshot):
        return OverseerDirective(
            corridor_map={0: 0, 1: 0},
            priority_table={},
            altitude_map={0: 1},
            timestamp=snapshot.timestamp,
        )

    monkeypatch.setattr("simulation.interfaces.overseer_update", fake_overseer)
    monkeypatch.setattr("simulation.engine.overseer_update", fake_overseer)

    result = run_simulation(make_pair(0, 0), duration_s=3.0, use_overseer=True, use_admm=False)

    assert result.positions[-1, 0, 2] == 1.0
    assert result.stats["layer_changes"] >= 1
    assert result.stats["layer_counts_final"] == {1: 1, 0: 1}


def test_logger_rows_have_layer() -> None:
    logger = TrajectoryLogger()
    run_simulation(make_pair(0, 1), duration_s=0.5, loggers=[logger], use_overseer=False, use_admm=False)
    assert all("layer" in row for row in logger.rows)
    assert {row["layer"] for row in logger.rows} == {0, 1}
