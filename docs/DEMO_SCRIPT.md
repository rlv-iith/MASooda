# MASooda — 5-minute demo script

Dashboard demo scenario: `experiments.week6.demo_scenario` in `configs/base_config.yaml`
(hierarchical, N = 60, seed 42, 180 s simulated; one injected emergency agent; malicious agent
from t = 60 s; DTC/overseer link down 90–120 s). Results are **provisional (pre-bug-fix)**.
ADMM is presented as conflict *mitigation*, never as a safety guarantee.

## Pre-demo checklist (T − 15 min)

- [ ] Laptop on AC power, notifications off, display scaling 100 %, projector mirrored.
- [ ] Repository on branch `week6`; `.venv` present (`.venv/Scripts/python.exe --version` → 3.10+).
- [ ] Warm-up run (also checks the environment, ~20 s):
      `.venv/Scripts/python.exe scripts/dashboard.py --live --headless --scenario demo --duration 10`
- [ ] Fallback video opens: `outputs/week6/demo/fallback_demo.mp4` (and the 3 clips next to it).
- [ ] `outputs/week6/RESULTS.md` and the 6–8 headline figures open in a second window.
- [ ] Terminal font ≥ 16 pt, opened at the repository root.

## Launch commands (copied from the dashboard CLI)

```bash
# live demo (opens a window, redraws every visualization.dashboard_refresh_ticks ticks)
.venv/Scripts/python.exe scripts/dashboard.py --live --scenario demo
```

```bash
# fallback 1: replay the recorded demo run in the dashboard
.venv/Scripts/python.exe scripts/dashboard.py --replay outputs/week6/demo/demo_run --out outputs/week6/demo/replay.gif
```

```bash
# fallback 2: regenerate the video (simulation + render)
.venv/Scripts/python.exe scripts/week6_demo_video.py
```

On Linux/macOS replace `.venv/Scripts/python.exe` with `.venv/bin/python`.

## Timeline

Measured in dry runs (docs/DRY_RUNS.md): the live run plays 180 s of simulation in about
89 s of wall time (≈ 4 refreshes/s, ~165 ms per redraw), i.e. about 2 sim-seconds per second.
**Cue every beat on the sim time in the banner, not on the clock.** When the run ends the window
stays open on the final frame (close it to return to the terminal), and the 3:00 talk beats use
that frozen frame.

| Wall time | Sim time (banner) | On screen | Exact words | Point at |
|---|---|---|---|---|
| 0:00–0:30 | — | Title slide / terminal | "MASooda coordinates urban air traffic in two tiers: a global overseer assigns corridors and altitude layers, and agents resolve local conflicts themselves." | — |
| 0:30–0:45 | — | Run the live command | "This is the hierarchical architecture with 60 agents; everything you see is computed live." | Terminal |
| 0:45–1:00 | 0–30 s | Agents leave the entry zone | "Agents form up in three corridors. Colours are agent types; the ringed agent is the emergency vehicle." | Corridors, emergency ring |
| 1:00–1:15 | 30–60 s | Merge zone; ADMM panel starts counting | "In the merge zone neighbours negotiate with ADMM — mitigation, not a guarantee." | ADMM panel, merge zone |
| 1:15–1:30 | 60–90 s | Red X and dashed ghost appear | "At 60 seconds one delivery agent starts lying about its position: the ghost is what it reports, the X is where it is." | Ghost + X, event strip "attack" |
| 1:30–1:45 | 90–120 s | Banner "DTC link: DOWN"; directive age climbs | "Now the overseer link is cut for 30 seconds; agents keep the cached directive." | Banner, directive age |
| 1:45–2:15 | 120–180 s | Link UP; directive age resets | "The link recovers and directives refresh." | Banner, event strip |
| 2:15–2:45 | final frame | Emergency panel | "The emergency agent on the emergency layer tracks its free-flow line closely." | Emergency progress vs dotted line |
| 2:45–3:30 | final frame | STL robustness panel | "Top right is the STL robustness of 'always keep 8 metres'; below zero is a violation. In this provisional metric, agents on different altitude layers still count against each other — that is being fixed." | ρ(t) panel, 0 line |
| 3:30–4:30 | — | RESULTS.md / headline figures | "Across 141 runs: E4 compares three architectures under the same attack; E1 shows ADMM effort scaling with N; E6 shows the outage did not change trajectories in these runs." | e4_main_comparison, e1_iterations_vs_N |
| 4:30–5:00 | — | Limitations slide | "All numbers are provisional until the metric and attack fixes land; we will regenerate everything with one command." | — |

## Speaker split

| Beat | Speaker |
|---|---|
| Intro, launch, formation (0:00–1:05) | P1 (simulation, integration) |
| Merge + ADMM (1:05–1:25) | P2 (ADMM) and P3 (formation) |
| Emergency priority (1:25–1:45) | P4 (overseer, priority) |
| Attack (1:45–2:10) | P5 (attack, resilience) |
| DTC outage (2:10–3:00) | P4 + P1 |
| STL + results + limitations (3:00–5:00) | P6 (verification, dashboard) |

## When to switch to the fallback video

Switch immediately (say "let me show the recorded run of the same scenario") if:

- the live window has not appeared 20 s after the launch command,
- the window freezes for more than 5 s, or a Python traceback appears,
- the projector cannot show the matplotlib window.

Open `outputs/week6/demo/fallback_demo.mp4` and continue the script at the same sim time
(the video shows the sim time in the banner). For a shorter slot, use the clips:
`clip_formation_merge.mp4` (0–75 s), `clip_emergency_priority.mp4` (40–160 s),
`clip_attack_dtc_outage.mp4` (55–135 s).

## Likely questions

| Question | Short answer |
|---|---|
| Does ADMM guarantee no collisions? | No. It mitigates conflicts it detects in the merge zone (groups of ≤ 5 within 20 m); E1 reports its effort and convergence, not a safety proof. |
| Why is robustness negative for the hierarchical run even without an attack? | The current metric uses planar distance across *all* pairs, including agents on different altitude layers; the fix is in progress, and results are marked provisional. |
| What happens if the overseer goes down? | Agents keep the cached directive; E6 shows directives stop refreshing during 90–120 s and, in these runs, trajectories were identical to the link-up runs. |
| How do you know the comparison is fair? | Every architecture runs from identical initial conditions per (seed, N), verified by a hash recorded in each manifest. |
| How many runs / seeds? | 141 runs; 3 seeds per point (5 for E4 attack on/off); 95% t-intervals in every table. |
| Can we reproduce it? | `scripts/run_all.sh` (or `run_all.ps1`) regenerates every CSV, figure and RESULTS.md; `--quick` is a smoke version. |
| Why only one attacker? | Single-adversary scope (W-MSR with f = 1), as in the threat model. |
