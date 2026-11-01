"""Consensus ADMM negotiation between conflicting agents.

Problem (per tick): each agent i wants to move to target p_i, but must
 (a) keep pairwise separation  n_ij.(x_i - x_j) >= d_safe   (convexified)
 (b) respect its speed limit   ||x_i - pos_i|| <= v_max * dt

    minimise   sum_i 0.5 * ||x_i - target_i||^2
    subject to (a) and (b)

Each agent keeps a local copy x_i and negotiates with its neighbours through
auxiliary variables z (one per constraint it appears in) and scaled duals u:

    x-update (local, closed form, parallel across agents):
        x_i = ( target_i + rho * sum_k (z_ik - u_ik) ) / (1 + rho * K_i)
    z-update (one tiny projection per constraint):
        z = Proj_C( x + u )
    u-update:
        u += x - z

2.5D extension: an optional per-agent altitude `z` can be passed to solve().
Pairs whose altitudes differ by >= layer_gap get no separation constraint.
"""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np

from .constraints import (PairConstraint, build_pair_constraints, project_pair,
                          project_ball, min_pairwise_distance)
from .convergence import ConvergenceLogger, ConflictRecord


@dataclass
class ADMMResult:
    positions: np.ndarray
    converged: bool
    iterations: int
    primal_residual: float
    dual_residual: float
    n_constraints: int
    history: list[tuple[float, float]]   # (primal, dual) per iteration


class ADMMSolver:
    def __init__(self, d_safe: float = 1.0, v_max: float = 2.0, dt: float = 1.0,
                 rho: float = 1.0, max_iters: int = 500,
                 eps_abs: float = 1e-5, eps_rel: float = 1e-4,
                 logger: ConvergenceLogger | None = None,
                 layer_gap: float = 1.0):
        self.d_safe, self.v_max, self.dt = d_safe, v_max, dt
        self.rho, self.max_iters = rho, max_iters
        self.eps_abs, self.eps_rel = eps_abs, eps_rel
        self.logger = logger
        self.layer_gap = layer_gap

    @classmethod
    def from_config(cls, cfg: dict | None = None, **kwargs) -> ADMMSolver:
        if cfg is None:
            from config.load_config import get_config
            cfg = get_config()
        safety = cfg["safety"]
        admm = cfg["admm"]
        sim = cfg["simulation"]
        params = {
            "d_safe": float(safety["minimum_separation_meters"]) * float(admm["safety_margin_factor"]),
            "v_max": float(safety["maximum_velocity_meters_per_second"]),
            "dt": float(sim["timestep_seconds"]),
            "rho": float(admm["rho"]),
            "eps_abs": float(admm["tolerance"]),
            "eps_rel": float(admm["relative_tolerance"]),
            "max_iters": int(admm["maximum_iterations"]),
        }
        params.update(kwargs)
        return cls(**params)

    def solve(self, positions: np.ndarray, targets: np.ndarray,
              scenario: str = "unnamed", z: np.ndarray | None = None) -> ADMMResult:
        positions = np.asarray(positions, dtype=float)
        targets = np.asarray(targets, dtype=float)
        layer_z = None if z is None else np.asarray(z, dtype=float)
        n, _ = positions.shape
        radius = self.v_max * self.dt
        # two agents can only collide this tick if they start within d_safe + 2*reach
        pairs: list[PairConstraint] = build_pair_constraints(
            positions, self.d_safe, activation_dist=self.d_safe + 2.0 * radius,
            z=layer_z, layer_gap=self.layer_gap)
        rho = self.rho

        if self.logger:
            self.logger.start()

        # Copies: pair constraint e gives (z_e_i, z_e_j); each agent also has a speed-ball copy.
        z_pair = [(positions[c.i].copy(), positions[c.j].copy()) for c in pairs]
        u_pair = [(np.zeros_like(positions[c.i]), np.zeros_like(positions[c.j])) for c in pairs]
        z_ball = positions.copy()
        u_ball = np.zeros_like(positions)

        K = np.ones(n)  # every agent has the ball copy
        for c in pairs:
            K[c.i] += 1
            K[c.j] += 1

        x = targets.copy()
        history: list[tuple[float, float]] = []
        converged, r_norm, s_norm, it = False, np.inf, np.inf, 0

        best_x = x.copy()
        best_r_norm = np.inf

        for it in range(1, self.max_iters + 1):
            # ---- x-update: closed form per agent ----
            acc = z_ball - u_ball
            for e, c in enumerate(pairs):
                acc[c.i] = acc[c.i] + (z_pair[e][0] - u_pair[e][0])
                acc[c.j] = acc[c.j] + (z_pair[e][1] - u_pair[e][1])
            x = (targets + rho * acc) / (1.0 + rho * K)[:, None]

            # ---- z-update: project onto each constraint set ----
            r_sq, s_sq, x_sq, z_sq, u_sq = 0.0, 0.0, 0.0, 0.0, 0.0
            for e, c in enumerate(pairs):
                a, b = project_pair(x[c.i] + u_pair[e][0], x[c.j] + u_pair[e][1], c)
                da, db = a - z_pair[e][0], b - z_pair[e][1]
                s_sq += float(da @ da + db @ db)
                z_pair[e] = (a, b)
            zb_new = np.array([project_ball(x[i] + u_ball[i], positions[i], radius)
                               for i in range(n)])
            s_sq += float(np.sum((zb_new - z_ball) ** 2))
            z_ball = zb_new

            # ---- u-update + residuals ----
            for e, c in enumerate(pairs):
                ra, rb = x[c.i] - z_pair[e][0], x[c.j] - z_pair[e][1]
                u_pair[e] = (u_pair[e][0] + ra, u_pair[e][1] + rb)
                r_sq += float(ra @ ra + rb @ rb)
                x_sq += float(x[c.i] @ x[c.i] + x[c.j] @ x[c.j])
                z_sq += float(z_pair[e][0] @ z_pair[e][0] + z_pair[e][1] @ z_pair[e][1])
            rb_ = x - z_ball
            u_ball = u_ball + rb_
            r_sq += float(np.sum(rb_ ** 2))
            x_sq += float(np.sum(x ** 2))
            z_sq += float(np.sum(z_ball ** 2))

            r_norm = np.sqrt(r_sq)
            s_norm = rho * np.sqrt(s_sq)
            history.append((r_norm, s_norm))

            if r_norm < best_r_norm:
                best_r_norm = r_norm
                best_x = x.copy()

            m = max(1, sum(K))  # total number of consensus entries
            eps_pri = np.sqrt(m) * self.eps_abs + self.eps_rel * max(np.sqrt(x_sq), np.sqrt(z_sq))
            eps_dual = np.sqrt(m) * self.eps_abs + self.eps_rel * rho * np.sqrt(
                sum(float(np.sum(uu[0] ** 2) + np.sum(uu[1] ** 2)) for uu in u_pair)
                + float(np.sum(u_ball ** 2)))
            if r_norm <= eps_pri and s_norm <= eps_dual:
                converged = True
                break

        # Use the feasible-side copy (z_ball satisfies the speed limit exactly);
        # pair constraints are satisfied to tolerance, so nudge-check in result.
        final = x if converged else best_x
        result = ADMMResult(final, converged, it, float(r_norm), float(s_norm),
                            len(pairs), history)

        if self.logger:
            self.logger.add(ConflictRecord(
                scenario=scenario, n_agents=n, n_constraints=len(pairs),
                iterations=it, converged=converged,
                solve_time_ms=self.logger.stop(),
                final_primal_residual=float(r_norm),
                final_dual_residual=float(s_norm),
                min_separation=min_pairwise_distance(final)))
        return result


if __name__ == "__main__":
    log = ConvergenceLogger()
    solver = ADMMSolver(d_safe=1.0, v_max=3.0, logger=log)

    # Three agents merging toward the same point from different lanes
    pos = np.array([[-3.0, 0.5], [-3.0, -0.5], [0.0, 3.0]])
    tgt = np.array([[0.0, 0.0], [0.0, 0.0], [0.0, 0.0]])
    res = solver.solve(pos, tgt, scenario="3-agent merge")
    print("converged:", res.converged, "iters:", res.iterations)
    print("new positions:\n", np.round(res.positions, 3))
    print("min separation:", round(min_pairwise_distance(res.positions), 3))
    print(log.summary())
