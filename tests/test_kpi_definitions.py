"""KPI definitions used in the paper: connectivity, layer-aware robustness, emergency timeliness, energy per class."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from simulation.route_engine import _graph_metrics
from simulation.route_priority import EmergencyTracker
from verification.metrics import robustness_series


def test_algebraic_connectivity_is_zero_for_a_disconnected_graph():
    m = _graph_metrics([1, 2, 3, 4], {1: [2], 3: [4]})
    assert m["components"] == 2 and m["algebraic_connectivity"] == 0.0
    assert m["algebraic_connectivity_giant"] == pytest.approx(2.0)
    path = _graph_metrics([1, 2, 3], {1: [2], 2: [3]})
    assert path["algebraic_connectivity"] == pytest.approx(1.0)       # path graph P3: lambda2 = 1


def test_robustness_can_use_the_layer_aware_distance():
    pos = np.array([[[0.0, 0.0, 0.0], [0.0, 0.0, 1.0]]])                 # same x, y; one layer apart
    assert robustness_series(pos, 8.0)[0] == pytest.approx(-8.0)          # horizontal-only (Week 5/6)
    assert robustness_series(pos, 8.0, layer_height_m=15.0)[0] == pytest.approx(7.0)


def test_emergency_on_time_and_ground_hold_are_reported():
    route = SimpleNamespace(length=600.0)
    flights = [SimpleNamespace(type="EMERGENCY", agent_id=1, depart_s=10.0, route=route),
               SimpleNamespace(type="EMERGENCY", agent_id=2, depart_s=10.0, route=route)]
    tr = EmergencyTracker(flights, lambda f: 12.0, 6, 15, 0.1)          # nominal 50 s
    tr.on_depart(1, 10.0)
    tr.on_land(1, 65.0)                                                  # 5 s late: on time
    tr.on_depart(2, 40.0)                                                # held 30 s on the pad
    tr.on_land(2, 95.0)                                                  # 35 s late
    snap = tr.snapshot(100.0)
    assert snap["on_time_rate"] == pytest.approx(0.5)
    assert snap["per"]["2"]["ground_hold_s"] == pytest.approx(30.0)
    assert snap["mean_ground_hold_s"] == pytest.approx(15.0)


def test_energy_per_delivery_is_split_by_mission_type():
    from web_sandbox.server import prepare_live_run
    from simulation.route_engine import simulate_routes
    p = prepare_live_run({"map": "iith", "fleet": 30, "duration_s": 150, "seed": 42})
    stats = {}
    for f in simulate_routes(p["network"], p["flights"], 150.0, config=p["config"], attack_config=p["attack"],
                             overseer_link_config=p["link"], frame_every=p["stride"], seed=42):
        stats = f.get("stats", stats)
    by = stats["energy_per_delivered_by_type_wh"]
    assert stats["energy_per_delivered_wh"] == by.get("DELIVERY")
    if "EVTOL" in by and "DELIVERY" in by:
        assert by["EVTOL"] > 10 * by["DELIVERY"]                         # why one mixed average misleads
