"""Generates the Week-1 toy CSV trajectories (analytically known robustness)."""
import csv
from pathlib import Path
import numpy as np

DT, T_END = 0.1, 20.0


def _write(path, traj):
    ts = np.round(np.arange(0, T_END + 1e-9, DT), 6)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t", "agent_id", "x", "y"])
        for t in ts:
            for a, fn in traj.items():
                x, y = fn(t)
                w.writerow([f"{t:.1f}", a, f"{x:.4f}", f"{y:.4f}"])


def generate(out_dir="data/stl"):
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    # SAFE: 4 agents on parallel lanes 12 m apart, 10 m/s -> rho = 12 - 8 = +4 m always.
    safe = {a: (lambda t, a=a: (10.0 * t, 12.0 * a)) for a in range(4)}
    _write(out / "safe_trajectory.csv", safe)
    # UNSAFE: agents 0,1 head-on in lanes 3 m apart, pass at t=10 s -> rho = 3 - 8 = -5 m.
    unsafe = {
        0: lambda t: (-100.0 + 10.0 * t, 0.0),
        1: lambda t: (100.0 - 10.0 * t, 3.0),
        2: lambda t: (10.0 * t, 60.0),
        3: lambda t: (10.0 * t, 80.0),
    }
    _write(out / "unsafe_trajectory.csv", unsafe)


if __name__ == "__main__":
    generate()
    print("written data/stl/safe_trajectory.csv, unsafe_trajectory.csv")
