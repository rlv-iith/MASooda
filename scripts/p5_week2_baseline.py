"""Week 2 baseline: Demonstrating vulnerability of plain averaging to position falsification (P5).

Evaluates:
- Part A: Neighbor centroid distortion caused by a falsifying agent under varying attack offsets.
- Part B: Network-wide consensus distortion on honest agents in the liar's component vs another component.
"""

from __future__ import annotations

import csv
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np

from config.load_config import get_config
from resilience.attack import apply_attack, inject_attack
from resilience.consensus import run_consensus
from simulation.mock_data import get_mock_agent_states, get_mock_comm_graph

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "outputs"


def run_baseline() -> None:
    cfg = get_config()
    attack_cfg = cfg["attack"]
    start_time = float(attack_cfg["start_time_seconds"])
    sweep_offsets = [float(x) for x in attack_cfg["sweep_offsets_meters"]]
    consensus_steps = int(attack_cfg["consensus_steps"])

    states = get_mock_agent_states()
    graph = get_mock_comm_graph()

    malicious_id = 2
    neighbors_of_attacker = graph.neighbors(malicious_id)
    honest_comp1 = [0, 1, 3, 4, 5]
    honest_comp2 = [6, 7, 8, 9]

    # Part A: Neighbor Centroid Error
    part_a_errors: list[float] = []
    for offset in sweep_offsets:
        cur_cfg = {
            **attack_cfg,
            "enabled": True,
            "malicious_ids": [malicious_id],
            "offset_magnitude_meters": offset,
        }
        attack_state = inject_attack(states, cur_cfg, start_time)
        reported_states = apply_attack(states, attack_state)

        true_pos = {a.id: a.position[:2] for a in states}
        reported_pos = {a.id: a.position[:2] for a in reported_states}

        centroid_errors: list[float] = []
        for nid in neighbors_of_attacker:
            nbr_ids = graph.neighbors(nid)
            true_centroid = np.mean([true_pos[k] for k in nbr_ids], axis=0)
            rep_centroid = np.mean([reported_pos[k] for k in nbr_ids], axis=0)
            err = float(np.linalg.norm(rep_centroid - true_centroid))
            centroid_errors.append(err)

        part_a_errors.append(float(np.mean(centroid_errors)))

    # Part B: Iterative Consensus Distortion
    initial_values = {a.id: float(a.position[0]) for a in states}
    no_liar_hist = run_consensus(initial_values, graph, liars={}, steps=consensus_steps)
    no_liar_final = no_liar_hist[-1]

    part_b_comp1_errors: list[float] = []
    part_b_comp2_errors: list[float] = []

    for offset in sweep_offsets:
        liar_val = initial_values[malicious_id] + offset
        liar_hist = run_consensus(
            initial_values,
            graph,
            liars={malicious_id: liar_val},
            steps=consensus_steps,
        )
        liar_final = liar_hist[-1]

        err_comp1 = float(np.mean([abs(liar_final[i] - no_liar_final[i]) for i in honest_comp1]))
        err_comp2 = float(np.mean([abs(liar_final[i] - no_liar_final[i]) for i in honest_comp2]))

        part_b_comp1_errors.append(err_comp1)
        part_b_comp2_errors.append(err_comp2)

    # Save CSV
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUTPUT_DIR / "p5_week2_baseline.csv"
    with open(csv_path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "offset_meters",
            "part_a_centroid_error_meters",
            "part_b_comp1_error_meters",
            "part_b_comp2_error_meters",
        ])
        for off, err_a, err_b1, err_b2 in zip(
            sweep_offsets, part_a_errors, part_b_comp1_errors, part_b_comp2_errors
        ):
            writer.writerow([off, err_a, err_b1, err_b2])

    # Print Table
    print("\n" + "=" * 80)
    print("MASooda P5 Week 2 Baseline: Plain Averaging Vulnerability")
    print("=" * 80)
    header = f"{'Offset (m)':<12} | {'Part A: Centroid Err (m)':<26} | {'Part B: Comp 1 Err':<20} | {'Part B: Comp 2 Err':<20}"
    print(header)
    print("-" * len(header))
    for off, err_a, err_b1, err_b2 in zip(
        sweep_offsets, part_a_errors, part_b_comp1_errors, part_b_comp2_errors
    ):
        print(f"{off:<12.1f} | {err_a:<26.4f} | {err_b1:<20.4f} | {err_b2:<20.4f}")
    print("=" * 80 + "\n")

    # Plot figure
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4.5))

    # Subplot 1: Part A
    ax1.plot(sweep_offsets, part_a_errors, "o-", color="#2a6fdb", linewidth=2, label="Neighbor Centroid Error")
    ax1.set_xlabel("Attack Offset $\\Delta$ (m)")
    ax1.set_ylabel("Mean Centroid Error (m)")
    ax1.set_title("Part A: Local Centroid Distortion")
    ax1.grid(True, linestyle="--", alpha=0.6)
    ax1.legend()

    # Subplot 2: Part B
    ax2.plot(sweep_offsets, part_b_comp1_errors, "s-", color="#d93a3a", linewidth=2, label="Comp 1 (Honest 0,1,3,4,5)")
    ax2.plot(sweep_offsets, part_b_comp2_errors, "^--", color="#2e9e5b", linewidth=2, label="Comp 2 (Agents 6-9)")
    ax2.set_xlabel("Attack Offset $\\Delta$ (m)")
    ax2.set_ylabel("Mean Error vs No-Liar Consensus")
    ax2.set_title(f"Part B: Iterative Consensus Distortion ({consensus_steps} steps)")
    ax2.grid(True, linestyle="--", alpha=0.6)
    ax2.legend()

    plt.tight_layout()
    png_path = OUTPUT_DIR / "p5_week2_baseline.png"
    plt.savefig(png_path, dpi=300)
    plt.close()
    print(f"Saved results to:\n- {csv_path}\n- {png_path}")


if __name__ == "__main__":
    run_baseline()
