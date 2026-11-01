import numpy as np

from conflict_resolution.solver import ADMMSolver
from conflict_resolution.constraints import min_pairwise_distance
from conflict_resolution.convergence import ConvergenceLogger

D = 1.0
TOL = 5e-3   # ADMM is converged to tolerance, not exactly feasible


def solve(pos, tgt, **kw):
    s = ADMMSolver(d_safe=D, **kw)
    return s.solve(np.array(pos, float), np.array(tgt, float))


def test_no_conflict_reaches_targets():
    res = solve([[0, 0], [10, 0]], [[1, 0], [9, 0]], v_max=3.0)
    assert res.converged
    assert res.n_constraints == 0
    np.testing.assert_allclose(res.positions, [[1, 0], [9, 0]], atol=1e-3)


def test_two_agent_head_on_keeps_separation():
    res = solve([[-2, 0.1], [2, -0.1]], [[2, -0.1], [-2, 0.1]], v_max=5.0)
    assert res.converged
    assert min_pairwise_distance(res.positions) >= D - TOL


def test_three_agent_merge_resolves():
    pos = [[-3, 0.5], [-3, -0.5], [0, 3]]
    tgt = [[0, 0], [0, 0], [0, 0]]
    res = solve(pos, tgt, v_max=4.0)
    assert res.converged
    assert min_pairwise_distance(res.positions) >= D - TOL


def test_speed_limit_respected():
    pos = np.array([[-3.0, 0.5], [-3.0, -0.5], [0.0, 3.0]])
    res = solve(pos, [[0, 0]] * 3, v_max=1.0, dt=1.0)
    steps = np.linalg.norm(res.positions - pos, axis=1)
    assert np.all(steps <= 1.0 + TOL)


def test_infeasible_when_agents_too_slow_to_separate():
    # Co-located agents, speed limit too small to open a 1.0 gap
    res = solve([[0, 0], [0.1, 0]], [[0, 0], [0.1, 0]], v_max=0.1, max_iters=300)
    assert min_pairwise_distance(res.positions) < D or not res.converged


def test_logger_records_conflict():
    log = ConvergenceLogger()
    s = ADMMSolver(d_safe=D, v_max=4.0, logger=log)
    s.solve(np.array([[-2, 0.1], [2, -0.1]]), np.array([[2, -0.1], [-2, 0.1]]), "head-on")
    assert len(log.records) == 1
    assert log.records[0].solve_time_ms > 0
    assert log.summary()["conflicts"] == 1


def test_two_agent_overtaking_converges_and_keeps_separation():
    # Same lane: the faster agent (0) is behind and its target passes straight through agent 1.
    pos = np.array([[0.0, 0.0], [2.0, 0.0]])
    tgt = np.array([[4.0, 0.0], [3.0, 0.0]])
    res = ADMMSolver(d_safe=D, v_max=5.0).solve(pos, tgt)
    assert res.converged
    assert res.n_constraints == 1
    assert min_pairwise_distance(res.positions) >= D - TOL
