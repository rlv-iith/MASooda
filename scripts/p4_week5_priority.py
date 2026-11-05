"""E3: inject one emergency agent into traffic of different densities."""

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
from simulation.priority_metrics import (
    PriorityLogger, baseline_copy, inject_emergency, priority_summary,
)
from simulation.scenario import make_initial_agents
from verification.metrics import compute_run_metrics


def _run(agents, eid, duration, attack_cfg, cfg):
    reset_default_overseer()
    reset_local_behavior_cache()
    logger = PriorityLogger(eid, cfg)
    result = run_simulation(
        agents, duration_s=duration, loggers=[logger], use_overseer=True,
        use_admm=True, attack_config=attack_cfg, defended=True,
        overseer_link_config={"enabled": False},
    )
    return result, logger


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()

    cfg = get_config()
    exp = cfg.get("experiments", {})
    if args.quick:
        counts, seeds, duration = [30], [42], 60.0
    else:
        counts = exp.get("agent_counts", [30, 45, 60, 75])
        seeds = exp.get("seeds", [42, 43, 44])
        duration = float(cfg["simulation"]["duration_seconds"])
    attack_cfg = {**cfg["attack"], "enabled": False}

    rows = []
    for n in counts:
        for seed in seeds:
            agents = make_initial_agents(n, seed)
            em_agents, eid = inject_emergency(agents)
            base_agents = baseline_copy(em_agents, eid)
            initial = copy.deepcopy(em_agents)
            res_em, log_em = _run(em_agents, eid, duration, attack_cfg, cfg)
            _, log_base = _run(base_agents, eid, duration, attack_cfg, cfg)
            row = {"N": n, "seed": seed, "emergency_id": eid}
            row.update(priority_summary(log_em, log_base, initial, eid, cfg))
            row["safety_violation_ticks"] = compute_run_metrics(res_em)["safety_violation_ticks"]
            rows.append(row)
            print(f"N={n} seed={seed}: compliance={row['priority_compliance_rate']:.2f} "
                  f"em_delay={row['emergency_delay_s']:.1f} "
                  f"imposed={row['lower_priority_delay_imposed_s']:.1f}")

    out_dir = ROOT / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "p4_week5_priority.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    def mean_by_n(key):
        return [float(np.nanmean([r[key] for r in rows if r["N"] == n])) if
                not all(np.isnan([r[key] for r in rows if r["N"] == n])) else float("nan")
                for n in counts]

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
    axes[0].plot(counts, mean_by_n("priority_compliance_rate"), "o-")
    axes[0].set_ylim(0, 1.05)
    axes[0].set_xlabel("Number of agents")
    axes[0].set_ylabel("Priority compliance rate")
    axes[0].set_title("Emergency priority compliance")
    axes[1].plot(counts, mean_by_n("emergency_delay_s"), "o-", label="emergency delay")
    axes[1].plot(counts, mean_by_n("lower_priority_delay_imposed_s"), "s-",
                 label="imposed on lower priority")
    axes[1].set_xlabel("Number of agents")
    axes[1].set_ylabel("Seconds")
    axes[1].set_title("Delays")
    axes[1].legend()
    for ax in axes:
        ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(out_dir / "p4_week5_priority.png", dpi=150)
    plt.close(fig)
    print(f"Saved {csv_path}")


if __name__ == "__main__":
    main()
