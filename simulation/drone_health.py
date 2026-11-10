"""Drone health model: power, battery (Rint), BMS, temperatures, link and GNSS quality.

Phase 3B. Equations, default parameters and references: ``docs/DRONE_HEALTH_MODEL.md``.
All parameters come from ``drone_health:`` in ``configs/base_config.yaml``.
Deterministic: per-drone randomness (initial SoC/SoH of random-fleet drones, cell
imbalance, GNSS jitter, link shadowing) is drawn from ``numpy.random.default_rng``
seeded with ``(seed, drone id)``.

The model is vectorised over drones (NumPy arrays indexed by the order drones were
added) so 500 drones cost a few hundred microseconds per tick. The route engine
(``simulation.route_engine``) calls ``step`` every tick and ``bms`` every
``bms_period_s``; it owns the onboard responses that need routes (divert, land).
"""

from __future__ import annotations

import math
from typing import Any, Iterable

import numpy as np

G = 9.81
R_DRY_AIR = 287.05
NORMAL, WARNING, CRITICAL, FAULT = 0, 1, 2, 3
STATUS_NAMES = ("NORMAL", "WARNING", "CRITICAL", "FAULT")
CODES = ("UNDER_VOLTAGE", "OVER_TEMP", "CELL_IMBALANCE", "OVER_CURRENT", "SENSOR_FAULT")
# BMS check categories -> fault code (both temperatures report OVER_TEMP)
CATS = ("charge", "pack_temp", "motor_temp", "imbalance", "current", "sensor")
CAT_CODE = {"charge": "UNDER_VOLTAGE", "pack_temp": "OVER_TEMP", "motor_temp": "OVER_TEMP",
            "imbalance": "CELL_IMBALANCE", "current": "OVER_CURRENT", "sensor": "SENSOR_FAULT"}
FAULT_TYPES = ("capacity_loss", "cell_failure", "overheating", "motor_degradation", "gnss_degradation")


def air_density(ambient_c: float, elevation_m: float) -> float:
    p = 101325.0 * (1.0 - 2.25577e-5 * elevation_m) ** 5.25588
    return p / (R_DRY_AIR * (ambient_c + 273.15))


class HealthModel:
    def __init__(self, cfg: dict[str, Any], seed: int, dtc_xy: tuple[float, float]):
        h = cfg["drone_health"]
        self.h = h
        self.seed = int(seed)
        self.th = h["thresholds"]
        self.resp = h["responses"]
        self.faults_cfg = h["faults"]
        self.t_amb = float(h["ambient_c"])
        self.rho = air_density(self.t_amb, float(h["site_elevation_m"]))
        self.wind = np.asarray(h.get("wind_mps", [0.0, 0.0]), dtype=float)
        self.v_climb = float(h["v_climb_mps"])
        self.soc_min = float(h["soc_min_pct"]) / 100.0
        self.alpha_r = float(h["alpha_r_per_k"])
        self.dtc_xy = np.asarray(dtc_xy, dtype=float)
        tab = np.asarray(h["ocv_cell_v"], dtype=float)
        self._ocv_s, self._ocv_v = tab[:, 0] / 100.0, tab[:, 1]
        grid = np.linspace(0.0, 1.0, 1001)
        vals = np.interp(grid, self._ocv_s, self._ocv_v)
        self._F_grid = grid
        self._F = np.concatenate([[0.0], np.cumsum((vals[1:] + vals[:-1]) / 2.0 * np.diff(grid))])  # ∫ OCV dSoC
        rng = np.random.default_rng([self.seed, 7919])
        self._phase = rng.uniform(0.0, 2.0 * math.pi, 3)
        self.ids: list[int] = []
        self.index: dict[int, int] = {}
        self.types: list[str] = []
        self.cells: list[tuple[np.ndarray, np.ndarray]] = []   # per drone: (SoC offset, R factor) per cell
        self.fault_plan: dict[int, dict[str, Any]] = {}          # drone id -> {"type", "t_s"}
        self.applied_faults: dict[int, list[str]] = {}
        self._cat_level = {c: np.zeros(0, dtype=np.int8) for c in CATS}
        cols = ("m", "A", "FM", "eta", "cda", "avion", "ns", "vnom", "qnom", "rpack", "imax", "cp", "hp0", "hp1",
                "cm", "hm0", "hm1", "p_hover_ref", "soc", "soh", "qeff", "tp", "tm", "i", "v", "p", "ocv",
                "e_out", "e_load", "e_heat", "climb_until", "mh", "q_fault", "hdop_extra", "hdop_jit", "sensor",
                "tmax_p", "tmax_m", "rssi", "loss", "hdop", "min_cell", "imb", "status", "overheat_t",
                "deliverable", "rmul", "speed")
        self.a = {c: np.zeros(0) for c in cols}

    # ------------------------------------------------------------------ setup
    def _ocv_cell(self, soc: np.ndarray) -> np.ndarray:
        return np.interp(soc, self._ocv_s, self._ocv_v)

    def _hover_mech(self, m, A, FM) -> np.ndarray:
        T = m * G
        return T * np.sqrt(T / (2.0 * self.rho * A)) / FM

    def add(self, aid: int, typ: str, overrides: dict[str, Any] | None, custom: bool) -> None:
        """Register one drone. ``overrides``: battery_wh, soc_init_pct, soh_pct, payload_kg, fault."""
        p = self.h["types"][typ]
        o = overrides or {}
        rng = np.random.default_rng([self.seed, 104729, int(aid)])
        if custom:
            soc = (o.get("soc_init_pct") or 100.0) / 100.0
            soh = (o.get("soh_pct") or 100.0) / 100.0
        else:
            lo, hi = self.h["random_fleet_soc_pct"]
            soc = float(rng.uniform(lo, hi)) / 100.0
            lo, hi = self.h["random_fleet_soh_pct"]
            soh = float(rng.uniform(lo, hi)) / 100.0
        cap_wh = float(o.get("battery_wh") or p["capacity_wh"])
        payload = float(p["payload_kg"] if o.get("payload_kg") is None else o["payload_kg"])
        ns = int(p["cells_series"])
        qnom = cap_wh / float(p["v_nominal"])
        m = float(p["mass_kg"]) + payload
        A = int(p["rotors"]) * math.pi * (float(p["rotor_diameter_m"]) / 2.0) ** 2
        delta = rng.normal(0.0, float(self.h["cell_soc_sigma_pct"]) / 100.0, ns)
        eps = rng.normal(0.0, float(self.h["cell_r_sigma"]), ns)
        p_hover_ref = float(self._hover_mech(np.array(m), np.array(A), np.array(float(p["figure_of_merit"]))))
        row = {
            "m": m, "A": A, "FM": float(p["figure_of_merit"]), "eta": float(p["eta_prop"]), "cda": float(p["cda_m2"]),
            "avion": float(p["avionics_w"]), "ns": ns, "vnom": float(p["v_nominal"]), "qnom": qnom,
            "rpack": float(p["r_pack_ohm"]) * (cap_wh / float(p["capacity_wh"])) ** -1.0,  # bigger pack, lower R
            "imax": float(p["c_max"]) * qnom, "cp": float(p["pack_c_j_per_k"]) * cap_wh / float(p["capacity_wh"]),
            "hp0": float(p["pack_ha0"]), "hp1": float(p["pack_ha1"]), "cm": float(p["motor_c_j_per_k"]),
            "hm0": float(p["motor_ha0"]), "hm1": float(p["motor_ha1"]), "p_hover_ref": p_hover_ref / float(p["eta_prop"]),
            "soc": soc, "soh": soh, "qeff": qnom * soh, "tp": self.t_amb, "tm": self.t_amb, "i": 0.0, "v": 0.0,
            "p": 0.0, "ocv": 0.0, "e_out": 0.0, "e_load": 0.0, "e_heat": 0.0, "climb_until": -1.0, "mh": 1.0,
            "q_fault": 0.0, "hdop_extra": 0.0, "hdop_jit": float(rng.uniform(-0.15, 0.15)), "sensor": 0.0,
            "tmax_p": self.t_amb, "tmax_m": self.t_amb, "rssi": np.nan, "loss": np.nan,
            "hdop": float(self.h["gnss"]["hdop0"]), "min_cell": np.nan, "imb": 0.0, "status": 0.0,
            "overheat_t": 0.0, "deliverable": 1.0, "rmul": float(np.mean(1.0 + eps)), "speed": 0.0,
        }
        for k, v in row.items():
            self.a[k] = np.append(self.a[k], v)
        for c in CATS:
            self._cat_level[c] = np.append(self._cat_level[c], np.int8(0))
        self.index[int(aid)] = len(self.ids)
        self.ids.append(int(aid))
        self.types.append(typ)
        self.cells.append((delta, eps))
        if o.get("fault"):
            self.fault_plan[int(aid)] = dict(o["fault"])
        self._update_ocv(np.array([len(self.ids) - 1]))
        self.bms(np.array([len(self.ids) - 1]), initial=True)

    def _update_ocv(self, k: np.ndarray) -> None:
        a = self.a
        a["ocv"][k] = a["ns"][k] * self._ocv_cell(a["soc"][k])
        a["v"][k] = a["ocv"][k] - a["i"][k] * self._r(k)

    def _r(self, k: np.ndarray) -> np.ndarray:
        a = self.a
        cold = np.maximum(0.0, 25.0 - a["tp"][k])
        return a["rpack"][k] * a["rmul"][k] * (1.0 + 0.5 * (1.0 - a["soh"][k])) * (1.0 + self.alpha_r * cold)

    # ------------------------------------------------------------------ physics
    def power(self, k: np.ndarray, airspeed: np.ndarray, climbing: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
        """(electrical power W, mechanical power W) at the given airspeeds."""
        a = self.a
        T = a["m"][k] * G
        vh = np.sqrt(T / (2.0 * self.rho * a["A"][k]))
        v = np.asarray(airspeed, dtype=float)
        vi = np.sqrt(np.maximum(0.0, -v * v / 2.0 + np.sqrt(v ** 4 / 4.0 + vh ** 4)))
        pm = T * vi / a["FM"][k] + 0.5 * self.rho * a["cda"][k] * v ** 3
        if climbing is not None:
            pm = pm + np.where(climbing, T * self.v_climb, 0.0)
        pe = pm / (a["eta"][k] * a["mh"][k]) + a["avion"][k]
        return pe, pm

    def step(self, t: float, dt: float, k_air: np.ndarray, vel_air: np.ndarray, k_pad: np.ndarray,
             k_idle: np.ndarray) -> None:
        """Advance airborne drones (``vel_air`` ground velocity, (n, 2)), drones powered on a pad
        (avionics only) and idle drones (cooling only)."""
        a = self.a
        self._faults(t)
        if len(k_air):
            air = np.linalg.norm(np.asarray(vel_air, float).reshape(-1, 2) - self.wind, axis=1)
            climbing = a["climb_until"][k_air] > t
            pe, pm = self.power(k_air, air, climbing)
            self._discharge(k_air, pe, pm, air, dt)
            a["speed"][k_air] = air
        if len(k_pad):
            pe = a["avion"][k_pad]
            self._discharge(k_pad, pe, np.zeros(len(k_pad)), np.zeros(len(k_pad)), dt)
            a["speed"][k_pad] = 0.0
        if len(k_idle):  # landed / not yet powered: cool toward ambient, no draw
            a["i"][k_idle] = 0.0
            a["p"][k_idle] = 0.0
            a["speed"][k_idle] = 0.0
            for T_, C_, h0 in (("tp", "cp", "hp0"), ("tm", "cm", "hm0")):
                a[T_][k_idle] += dt / a[C_][k_idle] * (-a[h0][k_idle] * (a[T_][k_idle] - self.t_amb))
            self._update_ocv(k_idle)

    def _discharge(self, k: np.ndarray, pe: np.ndarray, pm: np.ndarray, air: np.ndarray, dt: float) -> None:
        a = self.a
        ocv = a["ns"][k] * self._ocv_cell(a["soc"][k])
        R = self._r(k)
        disc = ocv * ocv - 4.0 * R * pe
        ok = disc >= 0.0
        I = np.where(ok, (ocv - np.sqrt(np.maximum(disc, 0.0))) / (2.0 * R), ocv / (2.0 * R))  # max-power point
        p_del = np.where(ok, pe, ocv * I - I * I * R)
        a["deliverable"][k] = ok.astype(float)
        a["i"][k], a["ocv"][k], a["p"][k] = I, ocv, p_del
        a["v"][k] = ocv - I * R
        # an internal fault (overheating) dissipates q_fault inside the pack: that heat is stored
        # chemical energy, so it drains charge as a parallel current q_fault / OCV
        i_fault = a["q_fault"][k] / np.maximum(ocv, 1e-6)
        a["soc"][k] = np.maximum(0.0, a["soc"][k] - (I + i_fault) * dt / (3600.0 * a["qeff"][k]))
        a["e_out"][k] += (ocv * I + a["q_fault"][k]) * dt / 3600.0
        a["e_load"][k] += p_del * dt / 3600.0
        a["e_heat"][k] += (I * I * R + a["q_fault"][k]) * dt / 3600.0
        hp = a["hp0"][k] + a["hp1"][k] * np.sqrt(air)
        a["tp"][k] += dt / a["cp"][k] * (I * I * R + a["q_fault"][k] - hp * (a["tp"][k] - self.t_amb))
        motor_loss = pm / (a["eta"][k] * a["mh"][k]) - pm
        hm = a["hm0"][k] + a["hm1"][k] * np.sqrt(air)
        a["tm"][k] += dt / a["cm"][k] * (motor_loss - hm * (a["tm"][k] - self.t_amb))
        a["tmax_p"][k] = np.maximum(a["tmax_p"][k], a["tp"][k])
        a["tmax_m"][k] = np.maximum(a["tmax_m"][k], a["tm"][k])

    def start_climb(self, aid: int, t: float, layers_up: int, layer_height_m: float) -> None:
        if layers_up > 0 and aid in self.index:
            self.a["climb_until"][self.index[aid]] = t + layers_up * layer_height_m / self.v_climb

    # ------------------------------------------------------------------ faults
    def _faults(self, t: float) -> None:
        for aid, plan in list(self.fault_plan.items()):
            if t + 1e-9 < float(plan["t_s"]):
                continue
            self.fault_plan.pop(aid)
            self.inject(aid, plan["type"])

    def inject(self, aid: int, ftype: str) -> None:
        """Apply a fault now (scheduled from the drone form; later also from scripts / the DTC console)."""
        if ftype not in FAULT_TYPES:
            raise ValueError(f"unknown fault type {ftype!r}")
        k = self.index[aid]
        a, fc = self.a, self.faults_cfg
        if ftype == "capacity_loss":
            a["qeff"][k] *= 1.0 - float(fc["capacity_loss_frac"])
        elif ftype == "cell_failure":
            delta, eps = self.cells[k]
            j = int(np.argmin(delta))
            delta[j] -= float(fc["cell_failure_soc_drop_pct"]) / 100.0
            eps[j] = float(fc["cell_failure_r_factor"]) - 1.0
            a["rmul"][k] = float(np.mean(1.0 + eps))
        elif ftype == "overheating":
            a["q_fault"][k] = float(fc["overheating_heat_frac_hover"]) * a["p_hover_ref"][k]
        elif ftype == "motor_degradation":
            a["mh"][k] = float(fc["motor_degradation_health"])
        elif ftype == "gnss_degradation":
            a["hdop_extra"][k] = float(fc["gnss_degradation_hdop"])
            a["sensor"][k] = 1.0
        self.applied_faults.setdefault(aid, []).append(ftype)

    # ------------------------------------------------------------------ BMS
    def _level(self, cat: str, k: np.ndarray, relax: float) -> np.ndarray:
        """Raw level per category; ``relax`` = 1 shifts thresholds by the hysteresis toward 'healthier'."""
        a, th = self.a, self.th
        hs, hc, hm = float(th["hysteresis_soc_pct"]) * relax, float(th["hysteresis_c"]) * relax, float(th["hysteresis_mv"]) * relax
        lev = np.zeros(len(k), dtype=np.int8)
        if cat == "charge":
            soc = a["soc"][k] * 100.0
            lev = np.where(soc < float(th["soc_warning_pct"]) + hs, 1, 0)
            lev = np.where(soc < float(th["soc_critical_pct"]) + hs, 2, lev)
            lev = np.where(a["min_cell"][k] < float(th["cell_fault_v"]), 3, lev)
        elif cat == "pack_temp":
            T = a["tp"][k] + hc
            lev = np.select([T > th["pack_fault_c"], T > th["pack_critical_c"], T > th["pack_warning_c"]], [3, 2, 1], 0)
        elif cat == "motor_temp":
            T = a["tm"][k] + hc
            lev = np.select([T > th["motor_critical_c"], T > th["motor_warning_c"]], [2, 1], 0)
        elif cat == "imbalance":
            m = a["imb"][k] + hm
            lev = np.select([m > th["imbalance_critical_mv"], m > th["imbalance_warning_mv"]], [2, 1], 0)
        elif cat == "current":
            frac = a["i"][k] / a["imax"][k] + 0.05 * relax
            lev = np.select([a["deliverable"][k] < 0.5, frac > 1.0, frac > float(th["current_warning_frac"])], [3, 2, 1], 0)
        elif cat == "sensor":
            lev = np.where(a["sensor"][k] > 0.5, 3, 0)
        return np.asarray(lev, dtype=np.int8)

    def bms(self, k: np.ndarray, initial: bool = False) -> list[tuple[int, int, int, list[str]]]:
        """Cell voltages, imbalance, per-category levels with hysteresis, status.

        Returns status changes as (drone id, old status, new status, active codes).
        """
        a = self.a
        changes = []
        if not len(k):
            return changes
        for kk in k:  # cell voltages (vectorised per drone; up to 108 cells)
            delta, eps = self.cells[kk]
            r_cell = self._r(np.array([kk]))[0] / a["ns"][kk] / a["rmul"][kk]
            vc = self._ocv_cell(np.clip(a["soc"][kk] + delta, 0.0, 1.0)) - a["i"][kk] * r_cell * (1.0 + eps)
            a["min_cell"][kk] = float(vc.min())
            a["imb"][kk] = float((vc.max() - vc.min()) * 1000.0)
        new_status = np.zeros(len(k), dtype=np.int8)
        for c in CATS:
            raw = self._level(c, k, 0.0)
            prev = self._cat_level[c][k]
            relaxed = self._level(c, k, 1.0)
            lev = np.where(raw >= prev, raw, np.minimum(prev, relaxed)) if not initial else raw
            self._cat_level[c][k] = lev
            new_status = np.maximum(new_status, lev)
        old = a["status"][k].astype(int)
        a["status"][k] = new_status
        for idx, (o, n) in enumerate(zip(old.tolist(), new_status.tolist())):
            if o != n and not initial:
                changes.append((self.ids[int(k[idx])], o, n, self.codes(int(k[idx]))))
        return changes

    def codes(self, kk: int) -> list[str]:
        out = []
        for c in CATS:
            if self._cat_level[c][kk] >= 1 and CAT_CODE[c] not in out:
                out.append(CAT_CODE[c])
        return out

    def cat_level(self, aid: int, cat: str) -> int:
        return int(self._cat_level[cat][self.index[aid]])

    # ------------------------------------------------------------------ link + GNSS
    def link_gnss(self, k: np.ndarray, xy: np.ndarray, link_up: bool, dtc_enabled: bool,
                  spoofers_xy: np.ndarray, t: float) -> None:
        a, L, G_ = self.a, self.h["link"], self.h["gnss"]
        if not len(k):
            return
        xy = np.asarray(xy, float).reshape(-1, 2)
        if dtc_enabled and link_up:
            d = np.maximum(1.0, np.linalg.norm(xy - self.dtc_xy, axis=1))
            ph = self._phase
            shadow = float(L["shadowing_sigma_db"]) * (np.sin(xy[:, 0] / 61.0 + ph[0]) + np.sin(xy[:, 1] / 47.0 + ph[1])
                                                      + np.sin((xy[:, 0] + xy[:, 1]) / 83.0 + ph[2])) / math.sqrt(1.5)
            rssi = float(L["p_tx_dbm"]) - float(L["pl0_db"]) - 10.0 * float(L["path_loss_exponent"]) * np.log10(d) + shadow
            a["rssi"][k] = rssi
            a["loss"][k] = 1.0 / (1.0 + np.exp((rssi - float(L["rssi50_dbm"])) / float(L["loss_slope_db"])))
        else:
            a["rssi"][k] = np.nan
            a["loss"][k] = 1.0 if dtc_enabled else np.nan
        hdop = float(G_["hdop0"]) + a["hdop_jit"][k] * (1.0 + 0.5 * np.sin(t / 7.0 + k)) + a["hdop_extra"][k]
        if len(spoofers_xy):
            sp = np.asarray(spoofers_xy, float).reshape(-1, 2)
            dmin = np.min(np.linalg.norm(xy[:, None, :] - sp[None, :, :], axis=2), axis=1)
            r = float(G_["spoof_radius_m"])
            hdop = hdop + float(G_["spoof_hdop_gain"]) * np.clip(1.0 - dmin / r, 0.0, 1.0)
        a["hdop"][k] = hdop

    # ------------------------------------------------------------------ queries
    def _usable_wh(self, kk: int, soc: float) -> float:
        """Energy the pack can deliver from ``soc`` until its WEAKEST cell reaches ``soc_min``.

        Cells in series carry the same charge, so every cell gives up the same SoC span
        (weakest cell SoC - soc_min); each cell contributes the integral of its own OCV over that span.
        With identical cells this is ``qeff * ns * (F(soc) - F(soc_min))``.
        """
        delta, _ = self.cells[kk]
        s = np.clip(soc + delta, 0.0, 1.0)
        span = max(0.0, float(s.min()) - self.soc_min)
        if span <= 0.0:
            return 0.0
        F = lambda x: np.interp(x, self._F_grid, self._F)  # noqa: E731
        return float(self.a["qeff"][kk] * np.sum(F(s) - F(s - span)))

    def e_rem_wh(self, aid: int) -> float:
        """Usable energy left (Wh), limited by the weakest cell."""
        kk = self.index[aid]
        return self._usable_wh(kk, float(self.a["soc"][kk]))

    def _pack_at(self, kk: int, soc: float, power_w: float) -> tuple[bool, float, float]:
        """(power deliverable, pack current A, weakest cell voltage V) at ``soc`` while drawing ``power_w``."""
        a = self.a
        delta, eps = self.cells[kk]
        ocv_cells = self._ocv_cell(np.clip(soc + delta, 0.0, 1.0))
        ocv = float(ocv_cells.sum())
        R = float(self._r(np.array([kk]))[0])
        disc = ocv * ocv - 4.0 * R * power_w
        if disc < 0.0:
            return False, ocv / (2.0 * R), float("nan")
        I = (ocv - math.sqrt(disc)) / (2.0 * R)
        r_cell = R / a["ns"][kk] / a["rmul"][kk]
        v_min = float((ocv_cells - I * r_cell * (1.0 + eps)).min())
        return True, I, v_min

    def climb_power_w(self, aid: int) -> float:
        """Electrical power while climbing out of a hover (the highest steady draw of a mission)."""
        k = np.array([self.index[aid]])
        return float(self.power(k, np.array([0.0]), np.array([True]))[0][0])

    def lift_ok(self, aid: int) -> tuple[bool, str]:
        """Can the full pack lift this mass? Hover + climb current must stay within the pack's C-rating."""
        kk = self.index[aid]
        p = self.climb_power_w(aid)
        ok, I, _ = self._pack_at(kk, float(self.a["soc"][kk]), p)
        imax = float(self.a["imax"][kk])
        if ok and I <= imax:
            return True, ""
        return False, (f"over maximum take-off mass: climb needs {p:.0f} W "
                       f"({'more than the pack can deliver' if not ok else f'{I:.0f} A > {imax:.0f} A limit'}) "
                       f"at {self.a['m'][kk]:.1f} kg")

    def sag_ok(self, aid: int, energy_wh: float, climb: bool = False) -> tuple[bool, float]:
        """After spending ``energy_wh``, can the weakest cell still carry the load above ``cell_fault_v``?

        The load is a climb out of a hover (``climb=True``: a take-off) or the landing hover (in flight).

        Returns (ok, weakest cell voltage at that point). The energy check alone misses a cell with
        high resistance that hits the cut-off voltage under load long before its charge runs out.
        """
        kk = self.index[aid]
        a = self.a
        soc_end = float(a["soc"][kk]) - energy_wh / max(1e-9, float(a["qeff"][kk] * a["vnom"][kk]))
        p = self.climb_power_w(aid) if climb else float(self.power(np.array([kk]), np.array([0.0]))[0][0])
        ok, _, v_min = self._pack_at(kk, max(0.0, soc_end), p)
        margin = float(self.resp.get("sag_margin_v", 0.05))
        return bool(ok and v_min >= float(self.th["cell_fault_v"]) + margin), v_min

    def feasible(self, aid: int, distance_m: float, cruise_mps: float, climb: bool = False,
                 check_sag: bool = True) -> tuple[bool, float, float, str]:
        """(ok, energy needed Wh, usable energy Wh, reason) for flying ``distance_m`` and landing.

        ``climb``: the mission starts with a climb (pre-flight); ``check_sag=False``: energy only.
        """
        need = self.energy_needed_wh(aid, distance_m, cruise_mps)
        e_rem = self.e_rem_wh(aid)
        if need > e_rem:
            return False, need, e_rem, f"energy {e_rem:.0f} Wh < {need:.0f} Wh needed"
        if not check_sag:
            return True, need, e_rem, ""
        ok, v_min = self.sag_ok(aid, need, climb)
        if not ok:
            return False, need, e_rem, (f"weakest cell would sag to {v_min:.2f} V under {'climb' if climb else 'hover'} load "
                                        f"(cut-off {float(self.th['cell_fault_v']):.2f} V)")
        return True, need, e_rem, ""

    def energy_needed_wh(self, aid: int, distance_m: float, cruise_mps: float) -> float:
        """Energy to fly ``distance_m`` at cruise plus the landing hover, with the reserve margin."""
        k = np.array([self.index[aid]])
        p_cruise = float(self.power(k, np.array([cruise_mps]))[0][0])
        p_hover = float(self.power(k, np.array([0.0]))[0][0])
        t_fly = distance_m / max(cruise_mps, 0.5)
        return (p_cruise * t_fly / 3600.0) * (1.0 + float(self.resp["reserve_margin"])) \
            + p_hover * float(self.resp["landing_time_s"]) / 3600.0

    def status(self, aid: int) -> int:
        return int(self.a["status"][self.index[aid]])

    def soc(self, aid: int) -> float:
        return float(self.a["soc"][self.index[aid]])

    def overheating(self, aid: int) -> bool:
        kk = self.index[aid]
        return bool(self._cat_level["pack_temp"][kk] >= 1 or self._cat_level["motor_temp"][kk] >= 1)

    def compact(self, ids: Iterable[int]) -> dict[str, list[int]]:
        """Per drone (frame order): SoC int %, BMS status code, max(pack, motor) temperature int °C."""
        k = np.array([self.index[i] for i in ids], dtype=int)
        a = self.a
        return {"soc": np.rint(a["soc"][k] * 100.0).astype(int).tolist(),
                "bms": a["status"][k].astype(int).tolist(),
                "tmax": np.rint(np.maximum(a["tp"][k], a["tm"][k])).astype(int).tolist()}

    def detail(self, aid: int, ground_speed: float, cruise_mps: float) -> dict[str, Any]:
        a, kk = self.a, self.index[aid]
        delta, eps = self.cells[kk]
        r_cell = self._r(np.array([kk]))[0] / a["ns"][kk] / a["rmul"][kk]
        vc = self._ocv_cell(np.clip(a["soc"][kk] + delta, 0.0, 1.0)) - a["i"][kk] * r_cell * (1.0 + eps)
        p = float(a["p"][kk])
        e_rem = self.e_rem_wh(aid)
        t_left = e_rem * 3600.0 / p if p > a["avion"][kk] * 1.01 else None
        p_cruise = float(self.power(np.array([kk]), np.array([max(cruise_mps, 0.5)]))[0][0])
        range_m = e_rem * 3600.0 / p_cruise * max(cruise_mps, 0.5) if t_left is not None else None
        fin = lambda x, d=2: None if not np.isfinite(x) else round(float(x), d)  # noqa: E731
        hd = float(a["hdop"][kk])
        return {
            "soc": fin(a["soc"][kk] * 100, 1), "soh": fin(a["soh"][kk] * 100, 1),
            "capacity_wh": fin(a["qeff"][kk] * a["vnom"][kk], 0), "v": fin(a["v"][kk], 2), "ocv": fin(a["ocv"][kk], 2),
            "i": fin(a["i"][kk], 2), "p": fin(p, 0), "e_rem_wh": fin(e_rem, 1),
            "time_left_s": None if t_left is None else round(t_left, 0),
            "range_left_m": None if range_m is None else round(range_m, 0),   # at cruise power and speed
            "cells_mv": np.rint(vc * 1000.0).astype(int).tolist(), "imbalance_mv": fin(a["imb"][kk], 0),
            "min_cell_v": fin(a["min_cell"][kk], 3), "i_max": fin(a["imax"][kk], 1),
            "t_pack": fin(a["tp"][kk], 1), "t_motor": fin(a["tm"][kk], 1),
            "t_pack_max": fin(a["tmax_p"][kk], 1), "t_motor_max": fin(a["tmax_m"][kk], 1),
            "status": STATUS_NAMES[int(a["status"][kk])], "codes": self.codes(kk),
            "rssi_dbm": fin(a["rssi"][kk], 1), "packet_loss": fin(a["loss"][kk], 3),
            "hdop": fin(hd, 2), "fix": "GOOD" if hd < 2 else "DEGRADED" if hd < 5 else "POOR",
            "motor_health": fin(a["mh"][kk], 2), "energy_used_wh": fin(a["e_out"][kk], 1),
            "faults": list(self.applied_faults.get(aid, [])),
            "pending_fault": self.fault_plan.get(aid),
        }

    def set_soc(self, aid: int, soc: float) -> None:
        """Battery swap (or the end of a charge): the pack is replaced / topped up."""
        k = self.index[aid]
        self.a["soc"][k] = float(np.clip(soc, 0.0, 1.0))
        self._update_ocv(np.array([k]))

    def charge(self, aid: int, dt: float, c_rate: float, target: float) -> None:
        """Constant-current charge at ``c_rate`` (1/h) up to ``target`` SoC (charging pad)."""
        k = self.index[aid]
        self.a["soc"][k] = float(min(target, self.a["soc"][k] + c_rate * dt / 3600.0))
        self._update_ocv(np.array([k]))

    def energy_used_wh(self, aid: int) -> float:
        return float(self.a["e_out"][self.index[aid]])

    def max_temps(self) -> tuple[float | None, float | None]:
        if not self.ids:
            return None, None
        return float(self.a["tmax_p"].max()), float(self.a["tmax_m"].max())
