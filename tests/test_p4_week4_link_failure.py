import math

from scripts.p4_week4_link_failure import run


def test_short_link_failure_keeps_cached_directive():
    rows = run({
        "enabled": True,
        "down_start_seconds": 4.0,
        "down_end_seconds": 8.0,
    }, duration=12.0, n_agents=15)

    staleness = [row["staleness"] for row in rows]
    assert max(staleness) >= 4.0
    assert any(
        row["t"] >= 10.0 and row["staleness"] < 2.1
        for row in rows
    )
    assert all(math.isfinite(row["staleness"]) for row in rows)
    assert all(
        math.isfinite(row["min_distance"])
        for row in rows
    )
