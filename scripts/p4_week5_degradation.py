"""E6: graceful degradation when the overseer link drops."""

from __future__ import annotations

import argparse
import copy
import csv
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("MPLCONFIGDIR", "/tmp/masooda-matplotlib")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from config.load_config import get_config
from local_behavior.boids import reset_local_behavior_cache
from simulation.engine import run_simulation
from simulation.overseer import reset_default_overseer
from simulation.scenario import make_initial_agents
from verification.metrics import compute_run_metrics, graceful_degradation_score


def _run(agents, duration, attack_cfg, link_cfg):
    reset_default_overseer()
    reset_local_behavior_cache()
    result = run_simulation(
        agents, duration_s=duration, use_overseer=True, use_admm=True,
        attack_config=attack_cfg, defended=True, overseer_link_config=link_cfg,
    )
    return result, compute_run_metrics(result)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()

    cfg = get_config()
    seeds = cfg.get("experiments", {}).get("seeds", [42, 43, 44])
    lf = cfg["overseer"]["link_failure"]
    if args.quick:
        n_agents, duration, seeds = 30, 60.0, [42]
        down = (20.0, 40.0)
    else:
        n_agents = 60
        duration = float(cfg["simulation"]["duration_seconds"])
        down = (float(lf["down_start_seconds"]), float(lf["down_end_seconds"]))
    attack_cfg = {**cfg["attack"], "enabled": False}
    failure_link = {"enabled": True, "down_start_seconds": down[0], "down_end_seconds": down[1]}

    rows = []
    for seed in seeds:
        base = make_initial_agents(n_agents, seed)
        res_n, m_n = _run(copy.deepcopy(base), duration, attack_cfg, {"enabled": False})
        res_f, m_f = _run(copy.deepcopy(base), duration, attack_cfg, failure_link)
        v_n, v_f = m_n["safety_violation_ticks"], m_f["safety_violation_ticks"]
        row = {
            "seed": seed,
            "violations_normal": v_n,
            "violations_failure": v_f,
            "graceful_degradation_score": graceful_degradation_score(v_f, v_n),
            "throughput_normal": m_n["throughput_per_s"],
            "throughput_failure": m_f["throughput_per_s"],
            "overseer_failures": res_f.overseer_failures,
            "max_directive_staleness_s": res_f.stats.get("max_directive_staleness_s", 0.0),
        }
        rows.append(row)
        print(row)

    out_dir = ROOT / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "p4_week5_degradation.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    x = np.arange(len(rows))
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.bar(x - 0.2, [r["violations_normal"] for r in rows], 0.4, label="normal")
    ax.bar(x + 0.2, [r["violations_failure"] for r in rows], 0.4, label="link failure")
    ax.set_xticks(x, [f"seed {r['seed']}" for r in rows])
    ax.set_ylabel("Safety violation ticks")
    ax.set_title("Violations with and without overseer link failure")
    ax.legend()
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(out_dir / "p4_week5_degradation.png", dpi=150)
    plt.close(fig)
    print(f"Saved {csv_path}")


if __name__ == "__main__":
    main()
