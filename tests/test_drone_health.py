"""Phase 3B: drone health model (power, battery, BMS, temperatures) and onboard responses."""

from __future__ import annotations

import copy
import math

import numpy as np
import pytest

from config.load_config import get_config
from simulation.drone_health import CRITICAL, FAULT, NORMAL, WARNING, HealthModel, air_density


def _model(**over):
    cfg = copy.deepcopy(get_config())
    cfg["drone_health"].update(over)
    return HealthModel(cfg, seed=42, dtc_xy=(0.0, 0.0)), cfg


def _fly(hm, aid, seconds, speed=10.0, dt=0.1, t0=0.0, bms_every=5):
    k = np.array([hm.index[aid]])
    events = []
    for n in range(int(round(seconds / dt))):
        t = t0 + n * dt
        hm.step(t, dt, k, np.array([[speed, 0.0]]), np.array([], int), np.array([], int))
        if n % bms_every == 0:
            events += hm.bms(k)
    return events


def test_air_density_hot_and_high_is_thinner():
    assert air_density(15.0, 0.0) == pytest.approx(1.225, abs=0.002)
    assert air_density(42.0, 542.0) < air_density(35.0, 542.0) < air_density(15.0, 542.0)


def test_power_matches_momentum_theory_and_has_a_bucket():
    hm, cfg = _model()
    hm.add(1, "DELIVERY", None, custom=True)
    p = cfg["drone_health"]["types"]["DELIVERY"]
    T = (p["mass_kg"] + p["payload_kg"]) * 9.81
    A = p["rotors"] * math.pi * (p["rotor_diameter_m"] / 2) ** 2
    hover = T * math.sqrt(T / (2 * hm.rho * A)) / p["figure_of_merit"] / p["eta_prop"] + p["avionics_w"]
    k = np.array([0])
    pe0 = float(hm.power(k, np.array([0.0]))[0][0])
    assert pe0 == pytest.approx(hover, rel=1e-9)
    pe = hm.power(np.zeros(4, int), np.array([5.0, 10.8, 20.0, 30.0]))[0]
    assert pe[1] < pe0 and pe[3] > pe[1]                      # forward flight is cheaper, then drag dominates
    climb = float(hm.power(k, np.array([0.0]), np.array([True]))[0][0])
    assert climb - pe0 == pytest.approx(T * cfg["drone_health"]["v_climb_mps"] / p["eta_prop"], rel=1e-9)


def test_energy_is_conserved_and_soc_falls_monotonically():
    hm, _ = _model()
    hm.add(1, "EVTOL", {"soc_init_pct": 90.0}, custom=True)
    k = np.array([0])
    socs, p_int, i_int = [], 0.0, 0.0
    for n in range(1200):
        hm.step(n * 0.1, 0.1, k, np.array([[12.0, 0.0]]), np.array([], int), np.array([], int))
        socs.append(float(hm.a["soc"][0]))
        p_int += float(hm.a["p"][0]) * 0.1 / 3600.0
        i_int += float(hm.a["i"][0]) * 0.1 / 3600.0
    a = hm.a
    assert a["e_load"][0] == pytest.approx(p_int, rel=1e-9)                # integrated power = load energy
    assert a["e_out"][0] == pytest.approx(a["e_load"][0] + a["e_heat"][0], rel=1e-9)   # OCV·I = P + I²R
    assert all(b <= a_ for a_, b in zip(socs, socs[1:])) and socs[-1] < socs[0]
    # charge drawn (Ah) matches the SoC drop: ∫ I dt = ΔSoC · Q_eff
    assert (0.9 - socs[-1]) * a["qeff"][0] == pytest.approx(i_int, rel=1e-9)


def test_hover_and_pad_hold_still_drain():
    hm, _ = _model()
    hm.add(1, "DELIVERY", None, custom=True)
    hm.add(2, "DELIVERY", None, custom=True)
    for n in range(600):   # 60 s: drone 1 hovers, drone 2 waits powered on its pad
        hm.step(n * 0.1, 0.1, np.array([0]), np.array([[0.0, 0.0]]), np.array([1]), np.array([], int))
    hover_wh = float(hm.a["e_load"][0])
    assert hover_wh == pytest.approx(float(hm.power(np.array([0]), np.array([0.0]))[0][0]) * 60 / 3600, rel=0.01)
    assert hm.a["soc"][0] < 1.0 and hm.a["soc"][1] < 1.0
    assert hm.a["e_load"][1] == pytest.approx(25.0 * 60 / 3600, rel=0.01)   # pad: avionics only


def test_low_charge_status_levels_with_hysteresis():
    hm, cfg = _model()
    hm.add(1, "DELIVERY", {"soc_init_pct": 31.0}, custom=True)
    assert hm.status(1) == NORMAL
    ev = _fly(hm, 1, 420.0)      # ~1.06 kW for 7 min ≈ 25 % of 500 Wh
    statuses = [e[2] for e in ev]
    assert statuses[:2] == [WARNING, CRITICAL] and "UNDER_VOLTAGE" in ev[0][3]
    assert all(b >= a for a, b in zip(statuses, statuses[1:]))      # no flicker back down while draining


@pytest.mark.parametrize("fault,expect_code,level", [
    ("cell_failure", "CELL_IMBALANCE", CRITICAL),
    ("overheating", "OVER_TEMP", WARNING),
    ("gnss_degradation", "SENSOR_FAULT", FAULT),
])
def test_faults_raise_the_right_bms_status(fault, expect_code, level):
    hm, _ = _model()
    hm.add(1, "DELIVERY", {"fault": {"type": fault, "t_s": 5.0}}, custom=True)
    ev = _fly(hm, 1, 120.0)
    hit = [e for e in ev if e[2] >= level]
    assert hit and expect_code in hit[0][3]
    assert fault in hm.applied_faults[1]


def test_capacity_loss_and_motor_degradation():
    hm, _ = _model()
    hm.add(1, "DELIVERY", None, custom=True)
    hm.add(2, "DELIVERY", None, custom=True)
    e0 = hm.e_rem_wh(1)
    hm.inject(1, "capacity_loss")
    assert hm.e_rem_wh(1) == pytest.approx(0.7 * e0, rel=1e-6)
    p_before = float(hm.power(np.array([1]), np.array([10.0]))[0][0])
    hm.inject(2, "motor_degradation")
    assert float(hm.power(np.array([1]), np.array([10.0]))[0][0]) > p_before
    with pytest.raises(ValueError):
        hm.inject(1, "meteor")


def test_weakest_cell_limits_usable_energy():
    hm, cfg = _model()
    hm.add(1, "DELIVERY", {"soc_init_pct": 80.0}, custom=True)
    e0 = hm.e_rem_wh(1)
    hm.inject(1, "cell_failure")
    drop = cfg["drone_health"]["faults"]["cell_failure_soc_drop_pct"] / 100.0
    cap_wh = float(hm.a["qeff"][0] * hm.a["vnom"][0])
    # a series string stops when its weakest cell is empty: the lost span is the whole pack's
    assert hm.e_rem_wh(1) < e0 - 0.8 * drop * cap_wh


def test_overheating_fault_heat_comes_out_of_the_cells():
    hm, _ = _model()
    hm.add(1, "DELIVERY", None, custom=True)
    hm.add(2, "DELIVERY", None, custom=True)
    hm.inject(2, "overheating")
    for n in range(300):   # 30 s side by side at the same speed
        hm.step(n * 0.1, 0.1, np.array([0, 1]), np.array([[10.0, 0.0], [10.0, 0.0]]),
                np.array([], int), np.array([], int))
    a = hm.a
    assert a["soc"][1] < a["soc"][0]
    assert a["e_out"][1] == pytest.approx(a["e_load"][1] + a["e_heat"][1], rel=1e-9)
    assert a["e_out"][1] - a["e_out"][0] == pytest.approx(a["q_fault"][1] * 30.0 / 3600.0, rel=0.05)


def test_range_uses_cruise_power_not_momentary_speed():
    hm, _ = _model()
    hm.add(1, "DELIVERY", None, custom=True)
    _fly(hm, 1, 2.0)
    slow = hm.detail(1, 0.8, 12.0)["range_left_m"]
    fast = hm.detail(1, 14.0, 12.0)["range_left_m"]
    assert slow == fast and slow > 5000


def test_lift_and_voltage_sag_checks():
    hm, _ = _model()
    hm.add(1, "DELIVERY", {"payload_kg": 100.0}, custom=True)
    hm.add(2, "DELIVERY", None, custom=True)
    ok, why = hm.lift_ok(1)
    assert not ok and "maximum take-off mass" in why
    assert hm.lift_ok(2)[0]
    hm.add(3, "DELIVERY", {"soc_init_pct": 40.0}, custom=True)
    assert hm.feasible(3, 500.0, 12.0, climb=True)[0]
    hm.inject(3, "cell_failure")
    ok, need, e_rem, why = hm.feasible(3, 500.0, 12.0, climb=True)
    assert need <= e_rem and not ok and "sag" in why   # enough energy, but the weak cell hits cut-off


def _fleet(n, over=None, **h):
    hm, _ = _model(**h)
    for j in range(n):
        hm.add(j, "DELIVERY", dict(over or {}, soc_init_pct=70.0), custom=True)
    return hm


def _cruise(hm, seconds, ids=None, dt=0.1):
    k = np.arange(len(hm.ids)) if ids is None else np.asarray(ids)
    for n in range(int(round(seconds / dt))):
        hm.step(n * dt, dt, k, np.tile([[11.0, 0.0]], (len(k), 1)), np.array([], int), np.array([], int))


def test_ekf_tracks_soc_and_decisions_stay_conservative():
    hm = _fleet(6)
    _cruise(hm, 180.0)
    a = hm.a
    err = a["soc_hat"] - a["soc"]
    assert np.all(np.abs(err) < 3.0 * np.sqrt(a["P11"]))            # calibrated within 3 sigma
    assert np.all(np.abs(err) < 0.01)                                # and within 1 % SoC
    over = [hm.e_rem_bms_wh(j) - hm.e_rem_wh(j) for j in range(6)]
    assert max(over) < 0.03 * 500.0                                  # decisions never lean on optimism


def test_estimator_off_is_the_oracle_and_noise_is_per_drone():
    off = _fleet(2, estimator={"enabled": False})
    _cruise(off, 30.0)
    assert np.array_equal(off.a["soc_hat"], off.a["soc"])
    one, two = _fleet(1), _fleet(3)
    _cruise(one, 60.0)
    _cruise(two, 60.0)
    assert one.a["soc_hat"][0] == two.a["soc_hat"][0]                # other drones do not change its noise


def test_ekf_learns_a_sudden_capacity_loss():
    hm = _fleet(3, over={"fault": {"type": "capacity_loss", "t_s": 30.0}})
    _cruise(hm, 210.0)                                               # 3 min after the fault
    q_hat = 1.0 / hm.a["qinv_hat"]
    assert np.all(np.abs(q_hat / hm.a["qeff"] - 1.0) < 0.15)       # 30 % loss, now known within 15 %


def test_same_seed_same_trace_and_random_fleet_ranges():
    traces = []
    for _ in range(2):
        hm, cfg = _model()
        for i in range(20):
            hm.add(i, "DELIVERY", None, custom=False)
        _fly(hm, 3, 30.0)
        traces.append((hm.a["soc"].tolist(), hm.a["soh"].tolist(), hm.a["tp"].tolist(), hm.cells[3][0].tolist()))
    assert traces[0] == traces[1]
    soc0 = np.array(traces[0][0])
    lo, hi = cfg["drone_health"]["random_fleet_soc_pct"]
    assert soc0.min() >= lo / 100 - 0.01 and soc0.max() <= hi / 100


def test_link_quality_falls_with_distance_and_outage():
    hm, _ = _model()
    for i in range(3):
        hm.add(i, "DELIVERY", None, custom=True)
    k = np.arange(3)
    hm.link_gnss(k, np.array([[10.0, 0.0], [400.0, 0.0], [2000.0, 0.0]]), True, True, np.empty((0, 2)), 0.0)
    loss = hm.a["loss"][:3]
    assert loss[0] < loss[2] and hm.a["rssi"][0] > hm.a["rssi"][2]
    hm.link_gnss(k, np.zeros((3, 2)), False, True, np.array([[0.0, 0.0]]), 0.0)
    assert np.all(hm.a["loss"][:3] == 1.0) and np.all(np.isnan(hm.a["rssi"][:3]))
    assert np.all(hm.a["hdop"][:3] > 3.0)          # spoofer on top of the drones


# ----------------------------------------------------------------------------- engine responses
def _run(drones, fleet=0, duration=120.0):
    from simulation.route_engine import simulate_routes
    from web_sandbox.server import prepare_live_run
    p = prepare_live_run({"map": "iith", "fleet": fleet, "duration_s": duration, "seed": 42, "drones": drones})
    items = list(simulate_routes(p["network"], p["flights"], duration, config=p["config"], attack_config=p["attack"],
                                 overseer_link_config=p["link"], frame_every=p["stride"], seed=42))
    return p, items


def _events(items, kind=None):
    return [e for f in items for e in f["events"] if kind is None or e["kind"] == kind]


def test_preflight_check_grounds_an_empty_drone():
    _, items = _run([{"type": "DELIVERY", "origin": "V8", "destination": "V1", "soc_init_pct": 8}], duration=20.0)
    last = [f for f in items if not f.get("partial")][-1]
    assert last["status"] == [0] and last["stats"]["grounded_preflight"] == 1
    assert any("pre-flight check failed" in e["text"] for e in _events(items, "preflight"))


def test_overweight_drone_is_grounded_on_lift_not_energy():
    _, items = _run([{"type": "DELIVERY", "origin": "V2", "destination": "V9", "payload_kg": 100}], duration=10.0)
    texts = [e["text"] for e in _events(items, "preflight")]
    assert texts and "maximum take-off mass" in texts[0]


def test_low_reserve_diverts_and_nobody_runs_dry():
    # 24 % of 500 Wh with the reserve margin cannot reach V1 from V8 (1.65 km) but can reach a nearer pad
    _, items = _run([{"type": "DELIVERY", "origin": "V8", "destination": "V1", "soc_init_pct": 24, "soh_pct": 60}],
                    duration=200.0)
    last = [f for f in items if not f.get("partial")][-1]
    st = last["stats"]
    assert st["energy_depleted"] == 0
    if st["grounded_preflight"] == 0:   # departed: it must have diverted (it cannot make V1)
        assert st["diversions"] + st["forced_landings"] >= 1


def test_critical_fault_gets_right_of_way_and_lands():
    _, items = _run([{"type": "EVTOL", "origin": "V2", "destination": "V9", "depart_s": 1,
                      "fault": {"type": "cell_failure", "t_s": 15}}], fleet=20, duration=150.0)
    texts = [e["text"] for e in _events(items)]
    assert any("BMS CRITICAL (CELL_IMBALANCE)" in t for t in texts)
    assert any("right of way to land" in t for t in texts)
    assert any("DIVERTING" in t or "continuing to" in t for t in texts)
    last = [f for f in items if not f.get("partial")][-1]
    assert last["stats"]["energy_depleted"] == 0 and last["stats"]["crashes"] == 0


def test_admm_weight_rises_as_the_energy_margin_shrinks():
    from simulation.route_engine import simulate_routes
    from web_sandbox.server import prepare_live_run
    drones = [{"type": "DELIVERY", "origin": "V8", "destination": "V1", "soc_init_pct": 30, "depart_s": 1},
              {"type": "DELIVERY", "origin": "V8", "destination": "V1", "soc_init_pct": 100, "depart_s": 8}]
    p = prepare_live_run({"map": "iith", "fleet": 0, "duration_s": 60, "seed": 42, "drones": drones})
    ids = [f.agent_id for f in p["flights"]]
    items = list(simulate_routes(p["network"], p["flights"], 60.0, config=p["config"], attack_config=p["attack"],
                                 overseer_link_config=p["link"], frame_every=p["stride"], seed=42,
                                 health_detail_ids=lambda: ids))
    w = [(f["hsel"][str(ids[0])]["admm_weight"], f["hsel"][str(ids[1])]["admm_weight"])
         for f in items if not f.get("partial") and "hsel" in f and f["t"] > 20.0]
    assert w and all(lo >= hi for lo, hi in w) and max(lo for lo, _ in w) > 1.0   # low SoC weighs more
    assert all(hi == 1.0 for _, hi in w)                                           # full pack: class weight


def test_sensor_fault_lands_in_place_and_frames_stay_deterministic():
    drones = [{"type": "DELIVERY", "origin": "V13", "destination": "V4", "depart_s": 1,
               "fault": {"type": "gnss_degradation", "t_s": 20}}]
    _, a = _run(drones, fleet=10, duration=60.0)
    _, b = _run(drones, fleet=10, duration=60.0)
    strip = lambda items: [{k: v for k, v in f.items() if k != "admm"} for f in items if not f.get("partial")]  # noqa: E731
    assert strip(a) == strip(b)
    last = [f for f in a if not f.get("partial")][-1]
    assert 4 in last["status"] and last["stats"]["forced_landings"] == 1
    h = [f["h"] for f in a if not f.get("partial") and "h" in f]
    assert h and len(h[-1]["soc"]) == len(last["x"])


def test_weather_controls_change_power_and_are_validated():
    from web_sandbox.server import prepare_live_run
    hover = {}
    for t in (15.0, 42.0):
        p = prepare_live_run({"map": "iith", "fleet": 1, "duration_s": 10,
                              "config": {"drone_health": {"ambient_c": t, "wind_mps": [4.0, 0.0]}}})
        hm = HealthModel(p["config"], 1, (0.0, 0.0))
        hm.add(1, "DELIVERY", None, custom=True)
        hover[t] = float(hm.power(np.array([0]), np.array([0.0]))[0][0])
        assert hm.t_amb == t and list(hm.wind) == [4.0, 0.0]
    assert hover[42.0] > hover[15.0]
    for bad in ({"ambient_c": 70}, {"wind_mps": [20.0, 0.0]}, {"wind_mps": "calm"}):
        with pytest.raises(ValueError, match="weather|wind_mps"):
            prepare_live_run({"map": "iith", "fleet": 1, "config": {"drone_health": bad}})


def test_weather_profile_changes_ambient_and_wind_over_time():
    from web_sandbox.server import prepare_live_run
    prof = [[0, 45, 4.0, 0.0], [100, 48.33, 0.0, 0.0], [150, 50, 2.5, 0.0], [200, 40, 5.0, 0.0], [300, 20, 2.0, 0.0]]
    p = prepare_live_run({"map": "iith", "fleet": 1, "duration_s": 10,
                          "config": {"drone_health": {"ambient_c": 45.0, "wind_mps": [4.0, 0.0], "weather_profile": prof}}})
    hm = HealthModel(p["config"], 1, (0.0, 0.0))
    hm.add(1, "DELIVERY", None, custom=True)
    assert hm.t_amb == 45.0 and list(hm.wind) == [4.0, 0.0]
    e = np.zeros(0, dtype=int)
    hm.step(150.0, 0.1, e, np.zeros((0, 2)), e, np.array([0]))
    assert hm.t_amb == pytest.approx(50.0) and list(hm.wind) == pytest.approx([2.5, 0.0])
    rho_hot = hm.rho
    hm.step(400.0, 0.1, e, np.zeros((0, 2)), e, np.array([0]))      # held at the last point
    assert hm.t_amb == pytest.approx(20.0) and list(hm.wind) == pytest.approx([2.0, 0.0]) and hm.rho > rho_hot
    for bad in ([[0, 45, 0, 0]], [[0, 45, 0, 0], [0, 50, 0, 0]], [[0, 45, 0, 0], [10, 70, 0, 0]],
                [[0, 45, 0, 0], [10, 40, 20.0, 0]], "hot"):
        with pytest.raises(ValueError, match="weather"):
            prepare_live_run({"map": "iith", "fleet": 1,
                              "config": {"drone_health": {"weather_profile": bad}}})
