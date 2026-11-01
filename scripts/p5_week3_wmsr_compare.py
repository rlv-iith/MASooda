"""Compare plain averaging and W-MSR under constant-value liar reports."""

from __future__ import annotations

import csv
from pathlib import Path
import sys

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config.load_config import get_config
from resilience.consensus import run_consensus, run_wmsr_consensus
from simulation.interfaces import build_comm_graph
from simulation.scenario import make_initial_agents


OUTPUT_DIR = ROOT / "outputs"


def _error_series(
    history: list[dict[int, float]], honest_ids: list[int], true_honest_mean: float
) -> tuple[list[float], list[float]]:
    mean_errors: list[float] = []
    max_errors: list[float] = []
    for state in history:
        errors = [abs(float(state[aid]) - true_honest_mean) for aid in honest_ids]
        mean_errors.append(abs(float(np.mean([state[aid] for aid in honest_ids])) - true_honest_mean))
        max_errors.append(max(errors, default=0.0))
    return mean_errors, max_errors


def run_experiment() -> tuple[Path, Path]:
    cfg = get_config()
    seed = int(cfg.get("simulation", {}).get("random_seed", 42))
    agents = make_initial_agents(20, seed)
    k = int(cfg.get("communication", {}).get("nearest_neighbors", 6))
    graph = build_comm_graph(agents, k)
    print(f"Communication graph used: k-nearest-neighbor (k={k}, symmetric closure)")

    initial_values = {agent.id: float(agent.position[0]) for agent in agents}
    all_ids = sorted(initial_values)
    liars_counts = [int(value) for value in cfg.get("resilience", {}).get("liar_counts", [1, 2])]
    attack_cfg = cfg.get("attack", {})
    offset = float(attack_cfg.get("offset_magnitude_meters", 25.0))
    steps = int(attack_cfg.get("consensus_steps", 50))

    rows: list[dict[str, float | int | str]] = []
    summaries: list[dict[str, float | int | bool]] = []
    figure, axes = plt.subplots(1, len(liars_counts), figsize=(6 * len(liars_counts), 4), squeeze=False)

    for subplot_index, liar_count in enumerate(liars_counts):
        rng = np.random.default_rng(seed)
        liar_ids = sorted(int(aid) for aid in rng.choice(all_ids, size=liar_count, replace=False))
        honest_ids = [aid for aid in all_ids if aid not in liar_ids]
        honest_initial = [initial_values[aid] for aid in honest_ids]
        true_honest_mean = float(np.mean(honest_initial))
        honest_min, honest_max = min(honest_initial), max(honest_initial)
        liar_value = honest_max + offset
        liars = {aid: liar_value for aid in liar_ids}
        f = liar_count

        plain_history = run_consensus(initial_values, graph, liars, steps)
        wmsr_history = run_wmsr_consensus(initial_values, graph, liars, steps, f)
        plain_mean_error, plain_max_error = _error_series(plain_history, honest_ids, true_honest_mean)
        wmsr_mean_error, wmsr_max_error = _error_series(wmsr_history, honest_ids, true_honest_mean)
        wmsr_stayed_in_range = all(
            honest_min <= float(state[aid]) <= honest_max
            for state in wmsr_history
            for aid in honest_ids
        )

        for method, mean_errors, max_errors in (
            ("plain", plain_mean_error, plain_max_error),
            ("wmsr", wmsr_mean_error, wmsr_max_error),
        ):
            for step, (mean_error, max_error) in enumerate(zip(mean_errors, max_errors)):
                rows.append({
                    "liar_count": liar_count,
                    "step": step,
                    "method": method,
                    "mean_error": mean_error,
                    "max_honest_error": max_error,
                })

        summaries.append({
            "liar_count": liar_count,
            "plain_final_error": plain_mean_error[-1],
            "wmsr_final_error": wmsr_mean_error[-1],
            "plain_final_max_honest_error": plain_max_error[-1],
            "wmsr_final_max_honest_error": wmsr_max_error[-1],
            "wmsr_stayed_in_honest_range": wmsr_stayed_in_range,
        })

        ax = axes[0][subplot_index]
        time_steps = range(steps + 1)
        ax.plot(time_steps, plain_mean_error, label="Plain averaging", color="#d95f02")
        ax.plot(time_steps, wmsr_mean_error, label="W-MSR", color="#1b9e77")
        ax.set_title(f"{liar_count} liar{'s' if liar_count != 1 else ''} (f={f})")
        ax.set_xlabel("Consensus step")
        ax.set_ylabel("Honest mean error (m)")
        ax.grid(True, linestyle="--", alpha=0.5)
        ax.legend()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUTPUT_DIR / "p5_week3_wmsr_compare.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["liar_count", "step", "method", "mean_error", "max_honest_error"],
        )
        writer.writeheader()
        writer.writerows(rows)

    figure.suptitle("Plain averaging vs W-MSR on a k-nearest communication graph")
    figure.tight_layout()
    png_path = OUTPUT_DIR / "p5_week3_wmsr_compare.png"
    figure.savefig(png_path, dpi=200)
    plt.close(figure)

    print("\nFinal honest-agent error summary:")
    for summary in summaries:
        print(
            f"  liars={summary['liar_count']}: "
            f"plain mean error={summary['plain_final_error']:.4f} m, "
            f"W-MSR mean error={summary['wmsr_final_error']:.4f} m; "
            f"W-MSR stayed in honest initial range="
            f"{summary['wmsr_stayed_in_honest_range']}"
        )
        if not summary["wmsr_stayed_in_honest_range"]:
            print(
                "  WARNING: the k-NN graph is not robust enough for W-MSR in this run; "
                "honest values drifted outside their initial range."
            )
    print(f"\nSaved {csv_path}\nSaved {png_path}")
    return csv_path, png_path


if __name__ == "__main__":
    run_experiment()
