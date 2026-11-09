# Week 6 Definition-of-Done audit (workflow 14.9)

Audited 2026-11-07 on branch `week6` (uncommitted working tree), without running the full test
suite. Results are provisional: the teammate's metric / attack / compliance fixes (F1) are not
merged yet.

| # | Item (14.9) | Status | Evidence |
|---|---|---|---|
| 1 | All three architectures execute successfully | done | `outputs/week6/e4_resilience/runs.csv` (57 runs, all three architectures); `run_all --quick` smoke stages exit 0 (`outputs/week6/run_all_quick.log`) |
| 2 | All required experiments have completed | done | E1–E6 folders with `runs.csv`, `summary.csv`, `manifest.json`, `README.md`; 141 runs in `outputs/week6/RESULTS.md` |
| 3 | Required plots generated (newer than their CSVs) | done | 27/27 experiment figures in `outputs/week6/figures/` newer than their folder's CSVs; + `system_overview`, `altitude_layers_side_view` |
| 4 | Dashboard runs without manual intervention | done | `outputs/week6/demo/fallback_demo.mp4` + 3 clips recorded by `scripts/week6_demo_video.py`; 3 headless dry runs exit 0 (`docs/DRY_RUNS.md`) |
| 5 | Weak experiments re-run where necessary | partial | 14 weak groups listed in `outputs/week6/*/weak_results.json` and RESULTS.md; not re-run (decision: list only) |
| 6 | Reproducibility scripts work from a clean repository | partial | clean copy (git-tracked + listed untracked files): `run_all.sh --quick` 58/58 artifacts; two quick runs → 0 differences in runs.csv; full `run_all` not run in the clean copy (≈ 17 min) |
| 7 | The report is complete | partial | Doc draft, all sections written; open: citations [CITE], team names, embedded figures, post-fix numbers |
| 8 | The final presentation is complete | partial | 15-slide deck with speaker notes; open: team names on the cover, post-fix numbers |
| 9 | Two consecutive successful dry runs | partial | dry runs 2 and 3 back to back, both pass headless (`docs/DRY_RUNS.md`); the live window on the presentation laptop is untested |
| 10 | Fallback demo video available | done | `outputs/week6/demo/fallback_demo.mp4` matches the current `demo_scenario` (`demo_manifest.json`) |

## Remaining gaps

| Gap | Owner |
|---|---|
| Merge the metric / attack / compliance fixes, set `provisional: false`, `run_all.sh --fresh`, regenerate report and slides (F1) | P6 (metrics), P5 (attack), P4 (compliance); P1 runs F1 |
| Layer-aware separation metric (hierarchical violations are an artefact) | P6 |
| E2 merge-success definition (≈ 0 at every N) | P3 |
| E6 outage scenario that actually changes directives during the outage | P4 + P1 |
| Decide on the 14 weak groups (re-run with seeds 45–46?) | experiment owners |
| Citations and team names in the report and on the cover slide | all / P6 |
| Live-window check of the dashboard on the presentation laptop | P6 |
| Decide which `outputs/week6` files to commit (proposal in the session report) | team |
| Commit the `week6` branch | P1 (user) |

## Run the full test suite yourself

```bash
.venv/Scripts/python.exe -m pytest -q
```
