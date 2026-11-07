"""P4 emergency-priority compliance in road-corridor (route) mode.

Route-mode equivalents of ``simulation/priority_metrics.py`` (that module
assumes straight corridors with an exit line at ``corridors.exit_zone_x_meters``,
which the road network does not have). The definitions are kept:

* nominal time = free-flow travel time = route length / cruise speed.
  Route mode flies each type at its own cruise speed (emergencies at
  ``1.2 x v_cruise``), so the type's own speed is used here (agreed deviation:
  with the shared ``v_cruise`` an emergency could show a negative delay).
* delay = actual travel time - nominal time, where travel time runs from the
  *scheduled* departure to landing, so ground holds count as delay.
* compliance check (same rule as ``PriorityLogger``): at every DTC update the
  emergency's airspace cell is under capacity. A corridor in the abstract
  engine corresponds to a (sector, layer) cell here.

Extra route-mode observations per emergency drone:

* forced to yield: ground holds, tactical altitude shifts where the emergency
  was the drone that moved, DTC layer changes deferred by the safety gate;
* left its reserved layer: airborne ticks below/above ``airspace.emergency_layer``.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable


class EmergencyTracker:
    def __init__(self, flights: Iterable[Any], cruise_speed: Callable[[Any], float],
                 emergency_layer: int, capacity: int, dt: float):
        self.emergency_layer = int(emergency_layer)
        self.capacity = int(capacity)
        self.dt = float(dt)
        self.per: dict[int, dict[str, Any]] = {}
        self.cruise_speed = cruise_speed
        for f in flights:
            self.add(f)
        self.checks = 0
        self.compliant = 0

    def add(self, f: Any) -> None:
        """Track a flight if it is an emergency (initial fleet or injected mid-run)."""
        if getattr(f.type, "value", f.type) != "EMERGENCY":
            return
        speed = float(self.cruise_speed(f))
        self.per[f.agent_id] = {
            "depart_s": float(f.depart_s), "nominal_s": round(f.route.length / speed, 2),
            "took_off_s": None, "landed_s": None, "travel_s": None, "delay_s": None,
            "holds": 0, "shifts": 0, "gated": 0, "off_layer_ticks": 0, "airborne_ticks": 0,
            "checks": 0, "compliant": 0,
        }

    def __contains__(self, aid: int) -> bool:
        return aid in self.per

    # ------------------------------------------------------------------ hooks
    def on_hold(self, aid: int) -> None:
        if aid in self.per:
            self.per[aid]["holds"] += 1

    def on_depart(self, aid: int, t: float) -> None:
        if aid in self.per:
            self.per[aid]["took_off_s"] = float(t)

    def on_shift(self, mover: int) -> None:
        if mover in self.per:
            self.per[mover]["shifts"] += 1

    def on_gate(self, aid: int) -> None:
        if aid in self.per:
            self.per[aid]["gated"] += 1

    def on_land(self, aid: int, t: float) -> None:
        p = self.per.get(aid)
        if p is None:
            return
        p["landed_s"] = float(t)
        p["travel_s"] = round(float(t) - p["depart_s"], 2)
        p["delay_s"] = round(p["travel_s"] - p["nominal_s"], 2)

    def on_tick(self, airborne: Iterable[Any]) -> None:
        for a in airborne:
            p = self.per.get(a.id)
            if p is None:
                continue
            p["airborne_ticks"] += 1
            if int(a.altitude_layer) != self.emergency_layer:
                p["off_layer_ticks"] += 1

    def on_dtc_update(self, airborne: list[Any], cell_of: Callable[[Any], tuple[int, int]]) -> None:
        """Compliance check at a DTC update: the emergency's (sector, layer) cell load <= capacity."""
        mine = [a for a in airborne if a.id in self.per]
        if not mine:
            return
        load: dict[tuple[int, int], int] = {}
        for a in airborne:
            c = cell_of(a)
            load[c] = load.get(c, 0) + 1
        for a in mine:
            p = self.per[a.id]
            p["checks"] += 1
            self.checks += 1
            if load[cell_of(a)] <= self.capacity:
                p["compliant"] += 1
                self.compliant += 1

    # ------------------------------------------------------------------ output
    def snapshot(self, t: float) -> dict[str, Any]:
        per = {}
        delays = []
        for aid, p in self.per.items():
            if p["delay_s"] is not None:
                delays.append(p["delay_s"])
            per[str(aid)] = {  # delay_s stays None until landing; the UI shows elapsed vs nominal meanwhile
                "nominal_s": p["nominal_s"], "delay_s": p["delay_s"], "travel_s": p["travel_s"],
                "yields": p["holds"] + p["shifts"] + p["gated"],
                "holds": p["holds"], "shifts": p["shifts"], "gated": p["gated"],
                "off_layer_s": round(p["off_layer_ticks"] * self.dt, 1),
                "on_layer": round(1.0 - p["off_layer_ticks"] / p["airborne_ticks"], 3) if p["airborne_ticks"] else None,
                "compliance": round(p["compliant"] / p["checks"], 3) if p["checks"] else None,
            }
        return {
            "count": len(self.per),
            "rate": (self.compliant / self.checks) if self.checks else None,
            "checks": self.checks,
            "mean_delay_s": round(sum(delays) / len(delays), 2) if delays else None,
            "arrived": len(delays),
            "yields": sum(v["yields"] for v in per.values()),
            "per": per,
        }
