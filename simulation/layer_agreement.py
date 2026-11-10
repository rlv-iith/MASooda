"""Layer agreement: drones negotiate altitude layers over V2V; the DTC prices layers and settles stuck drones.

Why: with one cruise layer per direction, every drone of that direction queues behind the
drone ahead (car-following gap d_0 + h v) while the layers above stay empty.

Decision variable
-----------------
A drone's *slot* is (sector s, direction lane d, layer L). The lane follows from the route
(keep-left, one lane per direction fits in the tube), so the free choice is the layer.
Semicircular rule: eastbound drones use even layers, westbound odd layers, never the
emergency layer:  A_d = {L : L != L_emg, L mod 2 = d}.

1. Local cost (computed onboard from V2V reports, all terms dimensionless)
-------------------------------------------------------------------------
    J_i(L) = w_f phi_i(L) + w_p lam_i(L) + w_e c_i(L) + w_s [L != L_i] + w_dir [L not in A_d]

    phi_i(L) = 1 - v_eff/v_c,  v_eff = min(v_c, max(0, (g_i(L) - d_0) / h))
               the speed the engine's car-following law would allow behind the nearest
               same-direction drone ahead on L in my tube (g = gap); 1 if a drone comes head-on.
    lam_i(L) = congestion price of (my sector, L), agreed with neighbours (2).
    c_i(L)   = max(0, L - L_i) * H / H_ref * (1 + k_b (1 - SoC_i))
               climbing costs energy, more so when the battery is low.

2. Price agreement (consensus-based dual ascent on the slot load)
-----------------------------------------------------------------
    lam_i(L) <- clip( M{ lam_j(L) : j in N_i(s) U {i} } + alpha (l_i(L) - k) / k , 0, lam_max )

    l_i(L) = neighbours I hear on L in my sector, k = target load, M = mean, or the W-MSR
    trimmed mean (f = 1) when the report defence is on, so one lying neighbour cannot move
    the price. When the DTC link is up the DTC seeds every drone in sector s with
    lam^DTC_{s,L} = max(0, n_{s,L}/C - theta) / (1 - theta), from its global count n_{s,L}
    (C = capacity per sector-layer).

3. Agreement on who moves (local mutual exclusion)
-------------------------------------------------
    L*_i = argmin_{L in A_d U {L_i}} J_i(L),  gain g_i = J_i(L_i) - J_i(L*_i)
    A drone with g_i > delta announces (L*_i, g_i). It moves only if no neighbour announcing
    the same L* has a larger key (g, higher priority, lower id) -- at most one mover per
    target layer per neighbourhood and round -- and the layer-transition safety check
    passes. A cooldown stops oscillation.

4. Stuck -> DTC
---------------
    A drone held below f_stuck v_c for T_stuck s (not on approach, not held or capped)
    that did not move asks the DTC. At its next update (link up) the DTC settles all
    requests with its own cost, using its global picture:

        min  sum_i w_i K_i(L_i)   s.t.  n_{s,L} < C,  L_i in A_d,  transition clear
        w_i    = (1 + w_pr / (1 + P_i)) (1 + w_bat (1 - SoC_i))      priority, battery
        K_i(L) = w_d (T_i(L) - T_i^0) / T_i^0                        expected delay
               + w_b c_i(L) / max(SoC_i, 0.05)                       climb energy vs charge
               + w_l n_{s,L} / C + w_sw |L - L_i|                    load, switching
        T_i(L) = r_i / max(v_eff(L), 0.5) is the expected remaining flight time on L
        (r_i remaining route), T_i^0 = r_i / v_c.

    Solved greedily in decreasing w_i (highest priority / lowest battery chooses first),
    the usual heuristic for weighted assignment with capacities. No feasible layer ->
    denied, the drone keeps following.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence

import numpy as np

from resilience.wmsr import wmsr_scalar

DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "period_s": 1.0,           # one negotiation round per second
    "w_follow": 1.0,
    "w_price": 0.6,
    "w_climb": 0.15,
    "w_switch": 0.25,
    "w_direction": 0.5,        # cost of staying on a wrong-parity layer (after a tactical shift)
    "battery_k": 1.0,
    "climb_ref_m": 30.0,       # H_ref: one layer
    "gain_threshold": 0.15,    # delta
    "cooldown_s": 8.0,
    "alpha": 0.3,
    "target_load": 2,          # k: drones per layer within V2V range before the price rises
    "price_max": 2.0,
    "dtc_theta": 0.6,
    "stuck_speed_frac": 0.6,
    "stuck_time_s": 4.0,
    "approach_m": 60.0,        # no layer changes this close to the destination pad
    "request_ttl_s": 10.0,
    "dtc_w_delay": 1.0,
    "dtc_w_priority": 1.0,
    "dtc_w_battery": 0.5,
    "dtc_w_climb": 0.3,
    "dtc_w_load": 0.5,
    "dtc_w_switch": 0.1,
    "dtc_lookahead_m": 80.0,
}


def settings(cfg: dict[str, Any]) -> dict[str, Any]:
    out = dict(DEFAULTS)
    out.update(cfg.get("layer_agreement", {}) or {})
    return out


def direction_layers(direction: int, num_layers: int, emergency_layer: int, parity: bool = True) -> list[int]:
    """Allowed cruise layers for a direction (0 eastbound, 1 westbound)."""
    normal = [L for L in range(num_layers) if L != emergency_layer] or [0]
    if not parity:
        return normal
    own = [L for L in normal if L % 2 == direction % 2]
    return own or normal


def follow_penalty(gap: float, v_c: float, d_0: float, h: float) -> float:
    """phi = 1 - v_eff / v_c under the car-following law v = (gap - d_0) / h."""
    if not np.isfinite(gap):
        return 0.0
    v_eff = min(v_c, max(0.0, (gap - d_0) / h))
    return 1.0 - v_eff / max(v_c, 1e-6)


def climb_cost(cur: int, target: int, layer_h: float, ref_m: float, soc: float, k_b: float) -> float:
    return max(0, target - cur) * layer_h / ref_m * (1.0 + k_b * (1.0 - soc))


def departure_layer(allowed: Sequence[int], blocked: Iterable[int], load: dict[int, int], capacity: int,
                    soc: float, layer_h: float, s: dict[str, Any]) -> int:
    """Departure layer: the cheapest unblocked allowed layer (sector load + climb from the ground).

    ``blocked`` = layers with traffic at the corridor junction (no merge gap). If all are
    blocked the lowest allowed layer is returned and the engine holds the drone on the pad.
    """
    blocked = set(blocked)
    base = min(allowed)

    def cost(L: int) -> float:
        return (s["w_price"] * load.get(L, 0) / max(capacity, 1)
                + s["w_climb"] * climb_cost(base, L, layer_h, s["climb_ref_m"], soc, s["battery_k"]))
    free = [L for L in allowed if L not in blocked]
    return min(free, key=lambda L: (cost(L), L)) if free else base


@dataclass
class AgreementStats:
    rounds: int = 0
    switches: int = 0          # drones that moved by V2V agreement
    yields: int = 0            # wanted to move but a neighbour with a larger gain won the layer
    blocked: int = 0           # won the layer but the transition safety check failed
    stuck_requests: int = 0
    dtc_resolved: int = 0
    dtc_denied: int = 0
    requests_expired: int = 0  # DTC link down past the request TTL

    def as_dict(self) -> dict[str, int]:
        return dict(self.__dict__)


@dataclass
class LayerAgreement:
    """State of the protocol across rounds (prices, cooldowns, stuck timers, DTC requests)."""

    num_layers: int
    emergency_layer: int
    layer_h: float
    d_min: float
    d_0: float
    h_gap: float
    half_w: float
    capacity: int
    s: dict[str, Any]
    lam: dict[int, np.ndarray] = field(default_factory=dict)       # drone -> price per layer
    lam_sector: dict[int, int] = field(default_factory=dict)       # drone -> sector its prices refer to
    cooldown: dict[int, float] = field(default_factory=dict)
    stuck_since: dict[int, float] = field(default_factory=dict)
    requests: dict[int, float] = field(default_factory=dict)       # drone -> time asked
    stats: AgreementStats = field(default_factory=AgreementStats)
    last_cost: dict[int, dict[int, float]] = field(default_factory=dict)   # for the UI / debugging

    # ------------------------------------------------------------------ helpers
    def allowed(self, direction: int) -> list[int]:
        return direction_layers(direction, self.num_layers, self.emergency_layer, bool(self.s.get("direction_parity", True)))

    def _prices(self, i: int, sector: int) -> np.ndarray:
        if i not in self.lam or self.lam_sector.get(i) != sector:
            self.lam[i] = np.zeros(self.num_layers)
            self.lam_sector[i] = sector
        return self.lam[i]

    def _gap(self, p: np.ndarray, tan: np.ndarray, layer: int, others: Iterable[Any]) -> float:
        """Along-track gap to the nearest drone ahead on ``layer`` in my tube (inf if none); 0 if head-on."""
        left = np.array([-tan[1], tan[0]])
        best = np.inf
        for o in others:
            if int(o.altitude_layer) != layer:
                continue
            rel = np.asarray(o.position[:2], float) - p
            along = float(rel @ tan)
            if along <= 0.0 or abs(float(rel @ left)) > self.half_w:
                continue
            if float(np.asarray(o.velocity[:2]) @ tan) < 0.0:
                return 0.0          # opposing traffic in my tube on that layer
            best = min(best, along)
        return best

    # ------------------------------------------------------------------ DTC side
    def dtc_seed_prices(self, loads: dict[tuple[int, int], int], members: dict[int, list[int]]) -> None:
        """DTC broadcast: lam^DTC_{s,L} from its global count n_{s,L}, overriding the drones' estimates."""
        th = float(self.s["dtc_theta"])
        for sid, ids in members.items():
            vec = np.array([max(0.0, loads.get((sid, L), 0) / self.capacity - th) / (1.0 - th)
                            for L in range(self.num_layers)])
            vec = np.minimum(vec, float(self.s["price_max"]))
            for i in ids:
                self.lam[i] = vec.copy()
                self.lam_sector[i] = sid

    def dtc_resolve(self, t: float, ctx: "RoundContext") -> list[tuple[int, int, int, str]]:
        """Settle stuck requests with the DTC cost. Returns [(drone, from, to, text)] applied moves."""
        s = self.s
        moves: list[tuple[int, int, int, str]] = []
        if not self.requests:
            return moves
        loads: dict[tuple[int, int], int] = {}
        for a in ctx.visible:
            k = (ctx.sector_of(a), int(a.altitude_layer))
            loads[k] = loads.get(k, 0) + 1

        def weight(i: int) -> float:
            return ((1.0 + s["dtc_w_priority"] / (1.0 + ctx.priority(i)))
                    * (1.0 + s["dtc_w_battery"] * (1.0 - ctx.soc(i))))
        order = sorted((i for i in self.requests if i in ctx.by_air), key=lambda i: (-weight(i), i))
        for i in order:
            a = ctx.by_air[i]
            cur, sid = int(a.altitude_layer), ctx.sector_of(a)
            p, tan, rem, v_c, soc = a.position[:2], ctx.tangent(i), ctx.remaining(i), ctx.cruise(i), ctx.soc(i)
            t0 = rem / max(v_c, 1e-6)
            near = [o for o in ctx.visible if o.id != i
                    and float(np.linalg.norm(np.asarray(o.position[:2]) - p)) < float(s["dtc_lookahead_m"])]

            def exp_time(L: int) -> float:
                v_eff = v_c * (1.0 - follow_penalty(self._gap(p, tan, L, near), v_c, self.d_0, self.h_gap))
                return rem / max(v_eff, 0.5)
            t_cur = exp_time(cur)
            best, best_k, best_t = None, np.inf, t_cur
            for L in self.allowed(ctx.direction(i)):
                if L == cur or loads.get((sid, L), 0) >= self.capacity:
                    continue
                if not ctx.transition_clear(a, L):
                    continue
                tL = exp_time(L)
                k = (s["dtc_w_delay"] * (tL - t0) / max(t0, 1e-6)
                     + s["dtc_w_climb"] * climb_cost(cur, L, self.layer_h, s["climb_ref_m"], soc, s["battery_k"]) / max(soc, 0.05)
                     + s["dtc_w_load"] * loads.get((sid, L), 0) / self.capacity
                     + s["dtc_w_switch"] * abs(L - cur))
                if k < best_k:
                    best, best_k, best_t = L, k, tL
            del self.requests[i]
            if best is None or best_t >= t_cur - 1e-6:
                self.stats.dtc_denied += 1
                self.cooldown[i] = t + float(s["request_ttl_s"])
                moves.append((i, cur, cur, f"DTC: no better layer free for stuck D-{i} (sector S{sid}) — keeps following"))
                continue
            loads[(sid, cur)] = loads.get((sid, cur), 1) - 1
            loads[(sid, best)] = loads.get((sid, best), 0) + 1
            self.stats.dtc_resolved += 1
            self.cooldown[i] = t + float(s["cooldown_s"])
            self.stuck_since.pop(i, None)
            moves.append((i, cur, best, f"DTC resolved stuck D-{i}: L{cur}→L{best} — expected time "
                                         f"{t_cur:.0f}→{best_t:.0f} s (priority P{ctx.priority(i)}, SoC {soc * 100:.0f}%)"))
        return moves

    # ------------------------------------------------------------------ drone side
    def round(self, t: float, ctx: "RoundContext") -> tuple[list[tuple[int, int, int, str]], list[tuple[int, str]]]:
        """One V2V negotiation round. Returns (moves [(drone, from, to, text)], requests [(drone, text)])."""
        s = self.s
        self.stats.rounds += 1
        for i in [k for k in self.lam if k not in ctx.by_air]:   # landed / gone
            self.forget(i)
        H, ref, k_b = self.layer_h, float(s["climb_ref_m"]), float(s["battery_k"])
        kappa, alpha, lam_max = max(float(s["target_load"]), 1e-6), float(s["alpha"]), float(s["price_max"])
        part = [i for i in ctx.participants if i in ctx.by_air]
        sector = {i: ctx.sector_of(ctx.by_air[i]) for i in part}

        # (2) price consensus: synchronous (Jacobi) update from last round's neighbour prices
        old = {i: self._prices(i, sector[i]).copy() for i in part}
        for i in part:
            hear = [j for j in ctx.adj.get(i, []) if j in ctx.heard]
            mates = [j for j in hear if j in old and sector.get(j) == sector[i]]
            load = np.zeros(self.num_layers)
            for j in hear:
                o = ctx.heard[j]
                if ctx.sector_of(o) == sector[i]:
                    load[int(o.altitude_layer)] += 1
            new = np.empty(self.num_layers)
            for L in range(self.num_layers):
                vals = [float(old[j][L]) for j in mates]
                base = (wmsr_scalar(float(old[i][L]), vals, 1) if ctx.defended and len(vals) > 2
                        else (float(old[i][L]) + sum(vals)) / (1 + len(vals)))
                new[L] = base + alpha * (load[L] - kappa) / kappa
            self.lam[i] = np.clip(new, 0.0, lam_max)

        # (1) + (3) local costs, intents, arbitration
        intents: dict[int, tuple[int, float, tuple]] = {}
        costs: dict[int, dict[int, float]] = {}
        for i in part:
            a = ctx.by_air[i]
            cur, d = int(a.altitude_layer), ctx.direction(i)
            if ctx.remaining(i) < float(s["approach_m"]) or self.cooldown.get(i, -1e9) > t:
                continue
            allowed = self.allowed(d)
            p, tan, v_c, soc = a.position[:2], ctx.tangent(i), ctx.cruise(i), ctx.soc(i)
            hear = [ctx.heard[j] for j in ctx.adj.get(i, []) if j in ctx.heard]
            J = {}
            for L in sorted(set(allowed) | {cur}):
                if L == self.emergency_layer and cur != L:
                    continue
                J[L] = (s["w_follow"] * follow_penalty(self._gap(p, tan, L, hear), v_c, self.d_0, self.h_gap)
                        + s["w_price"] * float(self.lam[i][L])
                        + s["w_climb"] * climb_cost(cur, L, H, ref, soc, k_b)
                        + s["w_switch"] * (L != cur)
                        + s["w_direction"] * (L not in allowed))
            costs[i] = J
            best = min(J, key=lambda L: (J[L], L))
            gain = J[cur] - J[best]
            if best != cur and gain > float(s["gain_threshold"]):
                intents[i] = (best, gain, (round(gain, 9), -ctx.priority(i), -i))
        self.last_cost = costs

        moves: list[tuple[int, int, int, str]] = []
        moved: set[int] = set()
        for i, (L, gain, key) in sorted(intents.items()):
            rivals = [j for j in ctx.adj.get(i, []) if j in intents and intents[j][0] == L]
            if any(intents[j][2] > key for j in rivals):
                self.stats.yields += 1
                continue
            a = ctx.by_air[i]
            if not ctx.transition_clear(a, L):
                self.stats.blocked += 1
                continue
            cur = int(a.altitude_layer)
            J = costs[i]
            self.cooldown[i] = t + float(s["cooldown_s"])
            self.stuck_since.pop(i, None)
            self.requests.pop(i, None)
            self.stats.switches += 1
            moved.add(i)
            moves.append((i, cur, L, f"V2V layer agreement: L{cur}→L{L} (cost {J[cur]:.2f}→{J[L]:.2f}, "
                                     f"{len([j for j in ctx.adj.get(i, []) if j in intents])} neighbour intent(s))"))

        # (4) stuck detection -> DTC request
        reqs: list[tuple[int, str]] = []
        for i in part:
            if i in moved:
                continue
            a = ctx.by_air[i]
            v, v_c = float(np.linalg.norm(a.velocity[:2])), ctx.cruise(i)
            slow = (v < float(s["stuck_speed_frac"]) * v_c and ctx.remaining(i) >= float(s["approach_m"])
                    and not ctx.constrained(i))
            if not slow:
                self.stuck_since.pop(i, None)
                continue
            since = self.stuck_since.setdefault(i, t)
            if (t - since >= float(s["stuck_time_s"]) and i not in self.requests
                    and self.cooldown.get(i, -1e9) <= t and ctx.dtc_enabled):
                self.requests[i] = t
                self.stats.stuck_requests += 1
                reqs.append((i, f"D-{i} stuck at {v:.1f} m/s for {t - since:.0f} s on L{int(a.altitude_layer)} "
                                f"— asks the DTC for a layer"))
        for i, t_req in list(self.requests.items()):
            if i not in ctx.by_air:
                del self.requests[i]
            elif t - t_req > float(s["request_ttl_s"]):
                del self.requests[i]
                self.stats.requests_expired += 1
        return moves, reqs

    def forget(self, i: int) -> None:
        for d in (self.lam, self.lam_sector, self.cooldown, self.stuck_since, self.requests, self.last_cost):
            d.pop(i, None)


@dataclass
class RoundContext:
    """What one round may read: the engine supplies these from its state each round."""

    by_air: dict[int, Any]                      # true airborne states (own state, safety checks)
    heard: dict[int, Any]                       # what drones hear over V2V (reported, quarantined -> true)
    visible: list[Any]                          # what the DTC sees (cooperative, not quarantined)
    adj: dict[int, list[int]]                   # V2V communication graph
    participants: list[int]                     # drones that negotiate this round
    sector_of: Callable[[Any], int]
    tangent: Callable[[int], np.ndarray]
    remaining: Callable[[int], float]
    cruise: Callable[[int], float]
    soc: Callable[[int], float]
    priority: Callable[[int], int]
    direction: Callable[[int], int]
    constrained: Callable[[int], bool]          # held / speed-capped / overheating: slow on purpose
    transition_clear: Callable[[Any, int], bool]
    defended: bool = True
    dtc_enabled: bool = True
