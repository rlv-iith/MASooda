"""Record the fallback demo video and three short clips from the demo scenario (C2).

Simulates experiments.week6.demo_scenario once into outputs/week6/demo/demo_run
(trajectory / telemetry / STL CSVs), then renders from those files:

* fallback_demo.mp4 (GIF if ffmpeg is missing) — the full scenario
* clip_formation_merge, clip_emergency_priority, clip_attack_dtc_outage — the
  windows in demo_scenario.clips

    python scripts/week6_demo_video.py [--reuse] [--skip-full]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import matplotlib  # noqa: E402

matplotlib.use("Agg")

from config.load_config import get_config  # noqa: E402
from experiments.week6_common import week6_root  # noqa: E402
from visualization import dashboard as dash  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--reuse", action="store_true", help="reuse demo_run/ if it exists (no new simulation)")
    ap.add_argument("--skip-full", action="store_true", help="only render the clips")
    args = ap.parse_args(argv)
    cfg = get_config()
    demo = cfg["experiments"]["week6"]["demo_scenario"]
    out = week6_root(False) / "demo"
    run_dir = out / "demo_run"
    t0 = time.perf_counter()
    if not (args.reuse and (run_dir / "trajectory.csv").is_file()):
        dash.simulate(str(demo["architecture"]), "demo", int(demo["n_agents"]), int(demo["seed"]),
                      float(demo["duration_s"]), run_dir=run_dir)
    t_sim = time.perf_counter() - t0
    data = dash.load_replay(run_dir)
    stride = int(dash._dash_cfg().get("frame_stride_ticks", 5))
    made = {}
    if not args.skip_full:
        p = dash.record(data, out / "fallback_demo.mp4", dash.frame_indices(data, stride))
        made["fallback_demo"] = str(p.relative_to(ROOT))
    for name, (a, b) in (demo.get("clips") or {}).items():
        p = dash.record(data, out / f"clip_{name}.mp4", dash.frame_indices(data, stride, float(a), float(b)))
        made[f"clip_{name}"] = str(p.relative_to(ROOT))
    for t_snap in (30.0, 75.0, 105.0):
        k = min(range(len(data.t)), key=lambda i: abs(data.t[i] - t_snap))
        dash.render_frame(data, k, out / f"demo_frame_t{int(t_snap)}.png")
    with open(out / "demo_manifest.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump({"demo_scenario": demo, "outputs": made, "simulate_s": round(t_sim, 1),
                   "total_s": round(time.perf_counter() - t0, 1), "frames_stride_ticks": stride,
                   "fps": int(dash._dash_cfg().get("fps", 10))}, f, indent=2)
    print(f"[demo] {made} in {time.perf_counter() - t0:.0f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
