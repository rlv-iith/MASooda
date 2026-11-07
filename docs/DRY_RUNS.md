# Demo dry runs

Commands from `docs/DEMO_SCRIPT.md`, run **headless** on the dev laptop (i5-12500H, Windows 11,
Python 3.14) on 2026-11-07. Headless mode draws every frame to an off-screen canvas, so refresh
rates match a live window closely but no window is shown. Issues column = lines matching
warning / traceback / error in the command output.

| Run | Time | Step | Exit | Wall (s) | Refreshes / s | Issues |
|---|---|---|---|---|---|---|
| 1 | 01:09 | warm-up (10 s sim) | 0 | 8 | 2.98 | 0 |
| 1 | 01:09 | live demo (180 s sim) | 0 | 90 | 4.05 | 0 |
| 1 | 01:11 | replay → GIF (fallback 1) | 0 | 97 | — | 0 |
| 2 | 01:15 | warm-up | 0 | 7 | 3.80 | 0 |
| 2 | 01:15 | live demo | 0 | 92 | 3.97 | 0 |
| 2 | 01:17 | replay → GIF | 0 | 104 | — | 0 |
| 3 | 01:18 | warm-up | 0 | 7 | 3.62 | 0 |
| 3 | 01:19 | live demo | 0 | 99 | 3.67 | 0 |
| 3 | 01:20 | replay → GIF | 0 | 119 | — | 0 |

## Beat timing (dry run 1)

180 s of simulation took 89 s of wall time (≈ 2 sim-s per s). The first script draft allowed
135 s of wall time for the live part (0:45–3:00), so the run would have ended about 45 s early.

## Issues found in dry run 1 and fixes applied

1. **Timeline too slow for the live run.** Fixed in `docs/DEMO_SCRIPT.md`: beats are cued on the
   sim time in the banner, with wall times re-measured (live part 0:45–2:15), and the 2:15–3:30
   talk beats use the final frame.
2. **Window would close when the simulation ends** (the program exited right after the last
   refresh). Fixed in `visualization/dashboard.py`: `--live` without `--headless` keeps the final
   frame on screen until the window is closed. Not testable headless; check it once on the
   presentation laptop.

Dry runs 2 and 3 were run back to back after the fixes; both passed (exit 0, no issues).

## Fallback video

`outputs/week6/demo/fallback_demo.mp4` (+ 3 clips) was recorded from the same
`experiments.week6.demo_scenario` as the current config (checked: `demo_manifest.json` equals the
config section), so no re-recording is needed.

## Run it live on the presentation laptop

```bash
.venv/Scripts/python.exe scripts/dashboard.py --live --scenario demo
```

(Linux/macOS: `.venv/bin/python`.) Variation between runs (90–99 s for the live part) comes from
the laptop's load; keep other programs closed.
