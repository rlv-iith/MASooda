"""One-command Week 6 pipeline (workflow 14.8). Does NOT run pytest.

Stages (each timed and logged to outputs/week6/run_all.log):

1. env        Python / numpy / matplotlib / yaml versions, ffmpeg availability
2. smoke      main.py short run for the three architectures
3. run_eN     E1-E6 run scripts (resume on unless --fresh)
4. plot_eN    E1-E6 plot scripts, static figures
5. summary    scripts/week6_summary.py -> outputs/week6/RESULTS.md
6. video      dashboard record of the demo scenario (skip with --skip-video)

At the end every expected artifact is listed as present / missing; the exit
code is non-zero if any is missing or any stage failed.

    python scripts/run_all.py [--quick] [--only e1,e4] [--skip-video] [--workers N] [--fresh]
"""

from __future__ import annotations

import argparse
import dataclasses
from pathlib import Path
import platform
import subprocess
import sys
import time
from typing import Callable, Sequence

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EXPERIMENTS = ["e1", "e2", "e3", "e4", "e5", "e6"]
SUBDIRS = {"e1": "e1_admm_scaling", "e2": "e2_formation", "e3": "e3_priority", "e4": "e4_resilience",
           "e5": "e5_stl", "e6": "e6_degradation"}
FIGURES = {
    "e1": ["e1_iterations_vs_N", "e1_solve_time_vs_N", "e1_convergence_rate_vs_N", "e1_time_per_tick_vs_N",
           "e1_convergence_vs_iteration_limit", "e1_iterations_distribution"],
    "e2": ["e2_merge_success_vs_N", "e2_throughput_vs_N", "e2_utilization_vs_N", "e2_utilization_heatmap_N60",
           "e2_formation_snapshot_N60"],
    "e3": ["e3_compliance_vs_N", "e3_emergency_delay_vs_N", "e3_imposed_delay_vs_N", "e3_emergency_track_N60"],
    "e4": ["e4_main_comparison", "e4_attack_effect", "e4_robustness_timeseries", "e4_offset_sensitivity"],
    "e5": ["e5_robustness_distribution", "e5_violation_fraction_vs_N", "e5_recovery_time", "e5_robustness_heatmap"],
    "e6": ["e6_violations_normal_vs_failure", "e6_throughput_normal_vs_failure", "e6_directive_age_timeline",
           "e6_degradation_score"],
}


@dataclasses.dataclass
class Stage:
    name: str
    cmd: Sequence[str] | Callable[[], int]
    artifacts: Sequence[Path] = ()
    experiment: str | None = None   # e1..e6, or None for always-on stages
    video: bool = False


def week6_root(quick: bool) -> Path:
    from experiments.week6_common import week6_root as _root

    return _root(quick)


def build_stages(quick: bool = False, workers: int | None = None, fresh: bool = False) -> list[Stage]:
    py = sys.executable
    root = week6_root(quick)
    figs = root / "figures"
    q = ["--quick"] if quick else []
    w = ["--workers", str(workers)] if workers else []
    f = ["--fresh"] if fresh else []
    smoke_dur = "2" if quick else "10"
    stages: list[Stage] = [Stage("env", env_check)]
    for arch in ("hierarchical", "centralized", "decentralized_undefended"):
        out = root / "run_all_smoke" / arch
        stages.append(Stage(f"smoke_{arch}", [py, "main.py", "--architecture", arch, "--scenario", "mvp",
                                              "--agents", "12", "--duration", smoke_dur, "--out", str(out),
                                              "--telemetry"],
                            [out / "run_row.csv", out / "telemetry.csv"]))
    for e in ("e1", "e2", "e3", "e4", "e6"):
        d = root / SUBDIRS[e]
        stages.append(Stage(f"run_{e}", [py, f"scripts/week6_{e}_run.py", *q, *w, *f],
                            [d / "runs.csv", d / "summary.csv", d / "manifest.json"], experiment=e))
    stages.append(Stage("run_e5", [py, "scripts/week6_e5_build.py", *q, "--run-missing", *w],
                        [root / "e5_stl" / "stl_runs.csv", root / "e5_stl" / "stl_summary.csv"], experiment="e5"))
    for e in EXPERIMENTS:
        stages.append(Stage(f"plot_{e}", [py, f"scripts/week6_{e}_plot.py", *q],
                            [root / SUBDIRS[e] / "README.md"] + [figs / f"{n}.png" for n in FIGURES[e]],
                            experiment=e))
    if not quick:
        stages.append(Stage("static_figures", [py, "scripts/week6_static_figures.py"],
                            [figs / "system_overview.png", figs / "altitude_layers_side_view.png"]))
    stages.append(Stage("summary", [py, "scripts/week6_summary.py", *q], [root / "RESULTS.md"]))
    demo = root / "demo"
    if quick:
        vcmd = [py, "scripts/dashboard.py", "--record", str(demo / "fallback_demo.gif"), "--scenario", "demo",
                "--agents", "12", "--duration", "10", "--stride", "10"]
        vart = [demo / "fallback_demo.gif"]
    else:
        vcmd = [py, "scripts/week6_demo_video.py"]
        vart = [demo / "fallback_demo.mp4"]
    stages.append(Stage("video", vcmd, vart, video=True))
    return stages


def select_stages(stages: Sequence[Stage], only: Sequence[str] | None = None, skip_video: bool = False) -> list[Stage]:
    """--only keeps the always-on stages plus the chosen experiments' run/plot stages."""
    only_set = {o.strip().lower() for o in (only or []) if o.strip()}
    bad = only_set - set(EXPERIMENTS)
    if bad:
        raise ValueError(f"unknown experiment(s) in --only: {sorted(bad)}")
    out = []
    for s in stages:
        if s.video and skip_video:
            continue
        if only_set and s.experiment is not None and s.experiment not in only_set:
            continue
        out.append(s)
    return out


def env_check() -> int:
    import matplotlib
    import numpy
    import yaml
    from matplotlib import animation

    print(f"python {platform.python_version()} ({sys.executable})")
    print(f"numpy {numpy.__version__}, matplotlib {matplotlib.__version__}, pyyaml {yaml.__version__}")
    print(f"ffmpeg available: {animation.writers.is_available('ffmpeg')}")
    print(f"platform: {platform.platform()}")
    if sys.version_info < (3, 10):
        print("ERROR: Python >= 3.10 required")
        return 1
    return 0


def run_stages(stages: Sequence[Stage], log_path: Path, cwd: Path = ROOT, echo=print) -> list[dict]:
    """Run stages in order (continue after a failure); log output and timing."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    results = []
    with open(log_path, "a", encoding="utf-8", newline="\n") as log:
        log.write(f"\n===== run_all {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
        for s in stages:
            t0 = time.perf_counter()
            log.write(f"\n--- stage {s.name} ---\n")
            log.flush()
            if callable(s.cmd):
                import contextlib
                import io

                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    try:
                        rc = int(s.cmd() or 0)
                    except Exception as exc:  # noqa: BLE001 - a stage failure is reported, not raised
                        print(f"stage raised {type(exc).__name__}: {exc}")
                        rc = 1
                log.write(buf.getvalue())
            else:
                log.write("$ " + " ".join(str(c) for c in s.cmd) + "\n")
                log.flush()
                proc = subprocess.run(list(map(str, s.cmd)), cwd=cwd, stdout=subprocess.PIPE,
                                      stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
                lines = [ln for ln in proc.stdout.splitlines() if not ln.startswith("[STL]")]
                log.write("\n".join(lines) + "\n")
                rc = proc.returncode
            dt = time.perf_counter() - t0
            log.write(f"--- {s.name}: exit {rc}, {dt:.1f} s ---\n")
            log.flush()
            results.append({"stage": s.name, "exit": rc, "seconds": round(dt, 1)})
            echo(f"[run_all] {s.name:<32} exit {rc}  {dt:7.1f} s")
    return results


def check_artifacts(stages: Sequence[Stage]) -> list[tuple[Path, bool]]:
    seen, out = set(), []
    for s in stages:
        for a in s.artifacts:
            if a not in seen:
                seen.add(a)
                out.append((Path(a), Path(a).is_file()))
    return out


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--quick", action="store_true", help="smoke version (< 5 min), outputs under outputs/week6/_quick")
    ap.add_argument("--only", default="", help="comma-separated experiments, e.g. e1,e4")
    ap.add_argument("--skip-video", action="store_true")
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--fresh", action="store_true", help="re-run every simulation (no resume)")
    args = ap.parse_args(argv)

    stages = select_stages(build_stages(args.quick, args.workers, args.fresh),
                           only=args.only.split(",") if args.only else None, skip_video=args.skip_video)
    log_path = week6_root(False) / ("run_all_quick.log" if args.quick else "run_all.log")
    t0 = time.perf_counter()
    results = run_stages(stages, log_path)
    arts = check_artifacts(stages)
    missing = [p for p, ok in arts if not ok]
    failed = [r for r in results if r["exit"] != 0]
    with open(log_path, "a", encoding="utf-8", newline="\n") as log:
        log.write("\n--- artifacts ---\n")
        for p, ok in arts:
            log.write(f"{'present' if ok else 'MISSING'}  {p.relative_to(ROOT) if p.is_relative_to(ROOT) else p}\n")
        log.write(f"--- total {time.perf_counter() - t0:.1f} s; failed stages: {[r['stage'] for r in failed]}; "
                  f"missing artifacts: {len(missing)} ---\n")
    print(f"[run_all] total {time.perf_counter() - t0:.1f} s; {len(arts) - len(missing)}/{len(arts)} artifacts present;"
          f" failed stages: {[r['stage'] for r in failed] or 'none'}; log: {log_path}")
    for p in missing:
        print(f"[run_all] MISSING {p}")
    return 1 if (missing or failed) else 0


if __name__ == "__main__":
    raise SystemExit(main())
