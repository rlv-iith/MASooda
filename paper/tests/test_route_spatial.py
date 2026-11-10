"""Phase 1b: the uniform-grid spatial index must not change any result."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from config.load_config import get_config
from simulation.comm_graph import build_radius_graph
from simulation.road_network import load_road_network
from simulation.route_engine import layered_min_separation, plan_flights, simulate_routes
from simulation.schema import AgentState, AgentType
from simulation.spatial_grid import (
    UniformGrid, close_same_layer_pairs, layered_min_separation_grid, radius_adjacency,
)

ROOT = Path(__file__).resolve().parents[1]


def _cloud(n, seed, spread=400.0):
    rng = np.random.default_rng(seed)
    xy = rng.uniform(-spread, spread, size=(n, 2))
    xy[: n // 4] = rng.normal(0.0, 6.0, size=(n // 4, 2))  # a dense cluster
    layers = rng.integers(0, 3, size=n)
    return xy, layers


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_radius_adjacency_matches_brute_force(seed):
    xy, _ = _cloud(150, seed)
    agents = [AgentState(id=100 + i, type=AgentType.DELIVERY, position=np.array([x, y, 0.0]))
              for i, (x, y) in enumerate(xy)]
    ids = [a.id for a in agents]
    for radius, cell in ((40.0, 40.0), (40.0, 17.0), (95.0, 40.0)):
        assert radius_adjacency(ids, xy, radius, cell) == build_radius_graph(agents, radius).adjacency


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_safety_queries_match_brute_force(seed):
    xy, layers = _cloud(120, seed)
    for radius in (8.0, 2.0):
        diff = xy[:, None, :] - xy[None, :, :]
        dist = np.sqrt(np.einsum("ijk,ijk->ij", diff, diff))
        same = layers[:, None] == layers[None, :]
        brute = [(int(u), int(v), float(dist[u, v]))
                 for u, v in np.argwhere(np.triu(same & (dist < radius), 1))]
        assert close_same_layer_pairs(xy, layers, radius, 40.0) == brute
    assert layered_min_separation_grid(xy, layers, 30.0, 40.0, layered_min_separation) == \
        layered_min_separation(xy, layers, 30.0)
    far = np.array([[0.0, 0.0], [900.0, 50.0], [-700.0, 300.0]])  # no pair inside the first radius
    assert layered_min_separation_grid(far, np.zeros(3), 30.0, 40.0, layered_min_separation) == \
        layered_min_separation(far, np.zeros(3), 30.0)


def test_grid_within_matches_linear_scan():
    xy, _ = _cloud(200, 5)
    grid = UniformGrid(xy, 40.0)
    for q in xy[:20]:
        for r in (16.0, 45.0, 130.0):
            brute = [i for i in range(len(xy)) if np.linalg.norm(xy[i] - q) < r]
            assert grid.within(float(q[0]), float(q[1]), r) == brute


def test_engine_identical_with_and_without_spatial_index():
    """60 drones, 120 s on the IITH map: positions equal within 1e-9 and identical events."""
    net = load_road_network(ROOT / "data" / "iith_campus.geojson")
    cfg = get_config()
    flights = plan_flights(net, 60, cfg["scenario"]["type_mix"], 42, 60.0)
    runs = {}
    for spatial in (False, True):
        runs[spatial] = list(simulate_routes(net, flights, 120.0, cfg, spatial_index=spatial, exact_positions=True))
    a, b = runs[False], runs[True]
    assert len(a) == len(b) == 1201
    worst = 0.0
    for fa, fb in zip(a, b):
        pa, pb = np.asarray(fa["pos"]), np.asarray(fb["pos"])
        worst = max(worst, float(np.max(np.abs(pa - pb))))
        assert fa["status"] == fb["status"] and fa["layer"] == fb["layer"] and fa["edges"] == fb["edges"]
        assert [e["text"] for e in fa["events"]] == [e["text"] for e in fb["events"]]
        assert fa["rho"] == fb["rho"]
    assert worst <= 1e-9
    assert a[-1]["stats"] == b[-1]["stats"]
    assert max(sum(s == 1 for s in f["status"]) for f in a) >= 30  # the run really is crowded


def test_partial_ticks_keep_every_event():
    net = load_road_network(ROOT / "data" / "iith_campus.geojson")
    cfg = get_config()
    flights = plan_flights(net, 30, cfg["scenario"]["type_mix"], 7, 10.0)
    full = list(simulate_routes(net, flights, 40.0, cfg))
    sparse = list(simulate_routes(net, flights, 40.0, cfg, frame_every=5))
    assert [e["text"] for f in full for e in f["events"]] == [e["text"] for f in sparse for e in f["events"]]
    kept = [f for f in sparse if not f.get("partial")]
    assert [f["k"] for f in kept] == list(range(0, 401, 5))
    assert kept[-1]["stats"] == full[-1]["stats"]
