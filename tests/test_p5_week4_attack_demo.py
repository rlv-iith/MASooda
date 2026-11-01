"""Small deterministic checks for the P5 attack comparison loop."""

from __future__ import annotations

import numpy as np

from scripts.p5_week4_attack_demo import run


def test_attack_demo_modes_remain_finite_and_defence_drops_attacker_report():
    results = [
        run(mode, n_agents=15, duration=8.0, offset=25.0, attack_start=2.0)
        for mode in ("none", "undefended", "defended")
    ]

    for result in results:
        numeric_values = [
            value for key, value in result.items()
            if key != "mode" and key != "malicious_id"
        ]
        assert np.all(np.isfinite(numeric_values))

    defended = results[2]
    assert defended["reports_dropped_total"] > 0
    assert defended["honest_reports_wrongly_dropped"] == 0
