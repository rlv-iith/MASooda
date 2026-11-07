# MASooda — Week 6 Prompt Pack

Copy-paste these prompts **one at a time, in order**, into the same Claude conversation.
Wait for each one to finish (and check its "report back") before sending the next.

Workflow reference: `workflow.pdf` §14 (Week 6), §14.8 (reproducibility), §14.9 (Definition of Done), Tables 10–11 (experiments E1–E6 and metrics).

| Phase | Prompts | What you get |
|---|---|---|
| 0. Setup | 0 | Branch, conventions, environment check |
| A. Shared infrastructure | A1–A3 | Experiment harness, plotting library, per-tick telemetry |
| B. Final experiments + plots | B1–B6 | E1–E6 CSVs, figures, auto-generated results tables |
| C. Dashboard + visualization | C1–C3 | Dual-panel live dashboard, recorded fallback video |
| D. Reproducibility | D1–D2 | `run_all.sh` / `run_all.ps1`, clean-clone check, README |
| E. Report + slides + demo | E1–E5 | Report, deck, demo script, dry-run logs |
| F. After the bug fixes land | F1–F2 | Regenerate everything, final DoD audit |

> **About the bug fixes:** another teammate is fixing the separation metric, attack/defence path, priority-compliance definition and outage behaviour. Everything below is built so those fixes flow through automatically: experiments call the existing metric functions instead of re-implementing them, and every figure is regenerated from CSVs by one command. Until Prompt F1, figures are stamped **PROVISIONAL**.

---

## Prompt 0 — Session setup and standing rules

```
We are starting Week 6 of MASooda (workflow.pdf §14). The repo is the MASooda folder on my computer. Read §14, §14.8, §14.9 and Tables 10–11 of the workflow PDF again before starting.

STANDING RULES — apply these to every Week 6 prompt I send after this one:

Environment
1. Edit code directly in my MASooda folder via the device shell. My machine has Python 3.10 with numpy, pyyaml, matplotlib; no pytest, no network, and each shell call times out at ~180 s.
2. Run the test suite and any long simulation in your cloud workspace: stage the current repo files there, run, then copy result files (CSVs, PNGs, PDFs, manifests, GIF/MP4) back into my folder with the commit-files tool. Re-stage changed files before every workspace run so you never test stale code.
3. The workspace has 2 CPUs. A 60-agent 180 s hierarchical run takes ~55 s; centralized ~15 s; decentralized ~45 s. Plan batches accordingly, run them in the background inside one turn and poll; never leave a job running after your reply ends.
4. All code must stay Python 3.10 compatible (the repo says >=3.10).

Scope
5. Do NOT modify the bug-fix areas owned by my teammate: verification/metrics.py, verification/stl_monitor.py, verification/live_monitor.py, resilience/defense.py, resilience/attack.py, resilience/wmsr.py, simulation/priority_metrics.py (definitions), simulation/overseer_link.py, conflict_resolution/detection.py, conflict_resolution/solver.py. Consume their public functions so their fixes propagate. If one of them blocks you, stop and tell me instead of patching it.
6. Changes to simulation/engine.py, main.py or experiments/runner.py must be additive and opt-in: default behaviour must stay bit-identical, proven by a test.
7. No hard-coded parameters (workflow §5). Simulation parameters come from configs/base_config.yaml. Add new visualization-only settings under a `visualization:` section and Week 6 experiment matrices under `experiments.week6:`.

Outputs
8. Everything Week 6 writes goes under outputs/week6/: one subfolder per experiment (e1_admm_scaling, e2_formation, e3_priority, e4_resilience, e5_stl, e6_degradation), figures in outputs/week6/figures/ as PNG (300 dpi) + PDF.
9. Every CSV gets a sibling manifest.json: command, git commit, resolved config hash and the config section used, seeds, agent counts, Python/numpy/matplotlib versions, wall time, timestamp.
10. Same seed and config must reproduce the same CSV (excluding wall-time columns). Never report a run with no conflicts/arrivals as a measured 0 — write NaN and say "n/a".
11. While `experiments.week6.provisional: true` in the config, every figure carries a small "PROVISIONAL — pre-bug-fix" footer.

Git and quality
12. Work on a branch named `week6`. Never push. Commit only when I say "commit", with clear messages.
13. Keep each file's existing line endings when editing; new files use LF. Don't mass-reformat.
14. Every new module gets pytest tests. The full suite must pass before you report done.
15. Describe ADMM as conflict mitigation, not a safety guarantee; never overstate results.

Report back after each prompt with: what you built, files created/changed, commands to run it, test results (count passed), key numbers if any, and anything blocked or that needs my decision. Keep it short.

TASK FOR THIS PROMPT:
a) Run `git status` and `git branch`. Note that 32 files show line-ending-only changes; don't touch them, just tell me how you'll handle branching around them and ask me if a decision is needed.
b) Create the `week6` branch from main (or tell me why not).
c) Stage the repo to the workspace and run the full pytest suite to record the baseline count.
d) Add the empty `visualization:` and `experiments.week6:` config sections (with `provisional: true`) and create the outputs/week6/ folder layout.
e) Report the baseline and wait for my next prompt.
```

---

## Phase A — Shared infrastructure

### Prompt A1 — Week 6 experiment harness (P1)

```
Standing rules from Prompt 0 apply.

Build one experiment harness that all Week 6 experiments use, so E1–E6 and run_all share the same code path.

Create experiments/week6.py (reuse experiments/runner.py: run_experiment, build_run_row, initial_conditions_hash, STANDARD_COLUMNS, check_identical_conditions — extend, don't duplicate):
1. A RunSpec dataclass: architecture, n_agents, seed, duration_s, attack_enabled, link_failure, scenario, plus optional overrides (attack offset, ADMM max iterations, emergency injection flag). Overrides must be applied through a config-override mechanism that restores the original config after the run.
2. run_one(spec, out_dir, save_series=True) -> dict: runs the simulation, returns the STANDARD_COLUMNS row plus any extra columns, and optionally saves a per-run time series (t, robustness via verification.metrics.robustness_series, violation flag) as a compressed .npz or CSV under out_dir/series/.
3. run_matrix(specs, out_dir, workers=os.cpu_count(), resume=True): runs specs in a process pool, skips runs whose result already exists (keyed by a stable spec hash), appends rows to out_dir/runs.csv, writes manifest.json (rule 9), and logs progress with ETA.
4. aggregate(runs_csv, group_by, metrics) -> DataFrame-free summary (plain csv/dicts, no pandas unless already installed on both machines — check first): mean, std, n, and 95% CI (t-distribution) per group. Write summary.csv.
5. A CLI: `python -m experiments.week6 --matrix <name> [--quick]` that reads matrices from config `experiments.week6.matrices` (define placeholders for e1..e6 now; later prompts fill them). `--quick` shrinks to 1 seed, fewer agents, short duration for smoke tests.

Tests (tests/test_week6_harness.py): spec hashing is stable; resume skips completed runs; same seed gives identical rows (ignore wall time); identical initial-conditions hash across architectures for the same (seed, N); aggregate CI math on a hand-made example; config overrides are restored after a run.

Smoke-run `--quick` for one tiny matrix in the workspace and report runtime per run type so later prompts can budget.
```

### Prompt A2 — Shared plotting library (P1, §14.1)

```
Standing rules from Prompt 0 apply.

Implement the shared plotting utilities in visualization/plots.py (workflow §14.1). Keep the existing plot_airspace function working.

Requirements:
1. A single house style: apply_style() setting fonts, sizes, grid, and a fixed colour per architecture (hierarchical / centralized / decentralized_undefended) and per agent type (EMERGENCY / EVTOL / DELIVERY), read from config `visualization:` (add the keys). Colour-blind-safe palette; same colours in every figure.
2. save_figure(fig, name): writes outputs/week6/figures/<name>.png (dpi from config) and .pdf, adds the PROVISIONAL footer when experiments.week6.provisional is true, closes the figure, returns paths.
3. Plot functions that take plain rows/arrays (not simulation objects), each with axis labels including units, title, legend, seed count "n=…" in the caption area:
   - robustness_timeseries(series_by_label, d_min, events=None): ρ(t) lines with ρ=0 threshold, shaded windows for attack start / overseer outage, optional mean ± CI band across seeds.
   - metric_bars(summary_rows, metric, group, hue): grouped bars with 95% CI error bars and individual seed points overlaid.
   - metric_vs_param(summary_rows, x, metric, hue): line + CI band (e.g. convergence vs N, vs iteration limit).
   - distribution_plot(rows, metric, group): box/strip plot.
   - utilization_heatmap(matrix, corridor_labels, time_axis, capacity).
   - timeline_strip(events, t_max): horizontal bars for attack active, link down, violations.
4. Handle NaN/n-a values gracefully (skip with a note, never plot as 0).
5. matplotlib only (Agg-safe), no seaborn.

Tests (tests/test_week6_plots.py): every function produces a figure from synthetic data without error, files are written, NaNs don't crash, provisional footer toggles.

Then generate a one-page "style sheet" figure using synthetic data (outputs/week6/figures/_style_check.png) and send it to me so I can approve the look before the experiments use it.
```

### Prompt A3 — Per-tick telemetry hook for dashboard and experiments (P1)

```
Standing rules from Prompt 0 apply.

The dashboard (§14.6) must show live STL robustness, priority-compliance information and ADMM convergence information. Loggers today only receive (t, agents), so ADMM and overseer status per tick aren't observable.

Add an opt-in telemetry channel to simulation/engine.py run_simulation (and pass-through in simulation/centralized.py and resilience/decentralized_undefended.py if they call run_simulation or have their own loop):
1. New optional argument `telemetry=None`. When provided, after each tick call telemetry.on_tick(t, info) where info is a small dict: admm_events_tick, admm_converged_tick, admm_nonconverged_tick, admm_iterations (list) and admm_solve_ms (list) for that tick if available, attack_active, malicious_ids, overseer_link_up, directive_age_s, corridor_occupancy, layer_counts, emergency_ids. Get ADMM iterations/timings from the event objects or by using conflict_resolution/profiling.ADMMRecorder — do not edit solver.py or detection.py.
2. Provide simulation/telemetry.py with a TelemetryRecorder class that stores these per tick and can write telemetry.csv.
3. When telemetry is None, behaviour and outputs must be bit-identical to today. Write a test that runs 60 agents for 20 s with and without telemetry and asserts identical positions arrays.
4. Wire an optional --telemetry flag into main.py that writes outputs/<out>/telemetry.csv.

Tests: identical-trajectory test above; recorder writes expected columns; ADMM counts per tick sum to result.stats["admm_events"]; works for all three architectures.
```

---

## Phase B — Final experiments and plots

> Each experiment has two scripts: a **run** script that writes CSVs, and a **plot** script that reads only CSVs. Re-plotting never re-simulates.

### Prompt B1 — E1: ADMM scaling and convergence (P2, §14.2)

```
Standing rules from Prompt 0 apply.

Finalize experiment E1 (workflow Table 10, §13.2, §14.2). The Week 5 attempt (scripts/p2_week5_admm_scaling.py) never saved its CSV, so treat it as reference code only.

Matrix (put it in config experiments.week6.matrices.e1):
- Part A, scaling: hierarchical, no attack, no link failure, N ∈ {30, 45, 60, 75}, seeds {42, 43, 44}, full duration.
- Part B, iteration limit: N = 60, seeds {42, 43, 44}, admm.maximum_iterations ∈ config admm.iteration_sweep ([5, 10, 20, 50, 100]).

Measure per run (use ADMMRecorder / A3 telemetry): solver calls, events, mean/p95/max iterations, fraction converged, mean/p95 solve time (ms), ADMM time per tick (ms), largest conflict group size, plus the standard columns. Save per-call records to calls.csv for distributions.

Write scripts/week6_e1_run.py (uses experiments/week6.run_matrix) and scripts/week6_e1_plot.py producing:
- e1_iterations_vs_N, e1_solve_time_vs_N, e1_convergence_rate_vs_N, e1_time_per_tick_vs_N (metric_vs_param with CI);
- e1_convergence_vs_iteration_limit (fraction converged and mean iterations vs limit);
- e1_iterations_distribution (per-call box plot by N).

Also write outputs/week6/e1_admm_scaling/README.md with the table of results (auto-generated from summary.csv, not typed by hand), method, hardware note, and 3–5 bullet observations that only state what the numbers show. Flag any "weak or inconsistent" result (high variance across seeds, n/a rows) and re-run it with 2 extra seeds if needed (§14.2 "re-run weak experiments"). Send me the figures.
```

### Prompt B2 — E2: formation, merge success, throughput, utilization (P3, §14.3)

```
Standing rules from Prompt 0 apply.

Finalize experiment E2 (Table 10, §13.3, §14.3). Only the 30-agent quick row of the Week 5 sweep was saved; the N=45–75 rows in docs/p3_week5_formation.md are not backed by any CSV, so regenerate everything from scratch and do not reuse those numbers.

Matrix: hierarchical, no attack, N ∈ {30, 45, 60, 75}, seeds {42, 43, 44}, full duration (agents need >125 s to reach the exit).

Use local_behavior/formation_metrics.py (FormationLogger, merge_outcomes, corridor_utilization) through the A1 harness. Per run record: merge attempts / success / failed / not_reached, merge success rate (NaN when no attempts), throughput, arrivals, mean and peak utilization per corridor, ticks over capacity, plus the standard columns. Save per-tick corridor occupancy for heatmaps.

Write scripts/week6_e2_run.py and scripts/week6_e2_plot.py producing:
- e2_merge_success_vs_N (with CI);
- e2_throughput_vs_N;
- e2_utilization_vs_N (per corridor, capacity line at 1.0);
- e2_utilization_heatmap_N60 (corridor × time, seed 42);
- e2_formation_snapshot_N60 (top-down frame at the merge zone at a representative time, using the renderer).

Write outputs/week6/e2_formation/README.md (auto-generated table + method + observations). Then update docs/p3_week5_formation.md: replace its results table with a pointer to the new auto-generated table and a one-line note that the earlier table was not reproducible. Send me the figures.
```

### Prompt B3 — E3 priority and E6 graceful degradation (P4, §14.4)

```
Standing rules from Prompt 0 apply.

Finalize E3 and E6 (Table 10, §13.4, §14.4). Use simulation/priority_metrics.py (inject_emergency, baseline_copy, PriorityLogger, priority_summary) as-is — its compliance definition is being revised by my teammate, so don't redefine it; just call it.

E3 matrix: hierarchical, no attack, N ∈ {30, 45, 60, 75}, seeds {42, 43, 44}, each run paired with its control run (same agent as ordinary DELIVERY). Record compliance rate, emergency delay vs nominal, time saved vs control, delay imposed on lower-priority traffic, violation ticks.
E6 matrix: hierarchical, N = 60, seeds {42, 43, 44}, link failure off vs on (window from config overseer.link_failure). Record violations, throughput, graceful-degradation score (verification.metrics.graceful_degradation_score), overseer failures/dropped, max directive staleness, and per-tick directive age from A3 telemetry.

Scripts: scripts/week6_e3_run.py, week6_e3_plot.py, week6_e6_run.py, week6_e6_plot.py. Figures:
- e3_compliance_vs_N; e3_emergency_delay_vs_N (with control comparison); e3_imposed_delay_vs_N;
- e3_emergency_track_N60 (emergency agent's x(t) vs control, seed 42);
- e6_violations_normal_vs_failure (bars + CI); e6_throughput_normal_vs_failure; e6_directive_age_timeline (with outage window shaded); e6_degradation_score.

Verify the link-failure experiment actually exercises the outage (§14.4 "verify the link-failure experiment"): show from telemetry that directives are not refreshed during the window and the cached directive is used. If the outage still has no effect on trajectories, say so clearly in the README rather than hiding it. Auto-generated READMEs in outputs/week6/e3_priority/ and e6_degradation/. Send me the figures.
```

### Prompt B4 — E4: three-architecture resilience comparison (P5, §14.5)

```
Standing rules from Prompt 0 apply.

Finalize E4 (Table 10, §13.7, §14.5): compare hierarchical, centralized and decentralized_undefended under the same attack.

Matrix:
- Main: 3 architectures × attack {off, on} × seeds {42, 43, 44, 45, 46}, N = 60, full duration, attack start 60 s (config). Verify identical initial conditions per (seed, N) with check_identical_conditions and save the verdict.
- Sensitivity: attack on, offsets from config attack.sweep_offsets_meters, 3 architectures, seeds {42, 43, 44}.

Measure (Table 11): throughput, safety-violation count, recovery time (mean/max), STL robustness (min and time series), post-attack violation ticks, reports dropped. Attack-effect = on minus off, paired by seed.

Scripts: scripts/week6_e4_run.py, week6_e4_plot.py. Figures:
- e4_main_comparison: 2×2 panel (throughput, violations, recovery time, min robustness) grouped by architecture, attack off vs on, CI + seed points;
- e4_attack_effect (paired on−off differences per architecture);
- e4_robustness_timeseries (mean ρ(t) per architecture with attack start line, attack on);
- e4_offset_sensitivity (violations and min robustness vs offset per architecture).

README in outputs/week6/e4_resilience/ with the auto-generated table and observations. If the attack has no measurable effect on some architecture, state that plainly — don't spin it. Send me the figures.
```

### Prompt B5 — E5: STL robustness across all architectures (P6, §13.6)

```
Standing rules from Prompt 0 apply.

Finalize E5 (Table 10): STL robustness for all evaluated architectures over the same scenarios as E1–E4. Don't re-simulate: build E5 from the saved per-run series and rows of B1–B4 (and run only the missing combinations, e.g. centralized and decentralized nominal at N ∈ {30, 45, 60, 75} if not already covered).

Produce in outputs/week6/e5_stl/:
- stl_summary.csv: per (scenario, architecture, N): min robustness, 5th-percentile robustness, fraction of ticks violating, violation episodes, mean/max recovery time, with CI across seeds.
- Figures: e5_robustness_distribution (box per architecture per scenario), e5_violation_fraction_vs_N (per architecture), e5_recovery_time (bars + CI), e5_robustness_heatmap (scenario × architecture, colour = median min robustness).
- README with auto-generated tables and the exact STL spec used (G(d_ij ≥ d_min), d_min from config) and note which separation definition the current verification code implements.

All robustness values must come from verification.metrics / verification.stl_monitor so the upcoming metric fix changes them automatically. Send me the figures.
```

### Prompt B6 — Consolidated results page (all, feeds the report)

```
Standing rules from Prompt 0 apply.

Create scripts/week6_summary.py that reads every outputs/week6/*/summary.csv and manifest.json and generates outputs/week6/RESULTS.md:
1. Header: git commit, config hash, date, provisional flag, total runs, total wall time.
2. One section per experiment E1–E6: objective (from Table 10), setup (from manifest), the results table (auto-generated), embedded figure links, and the auto-observations from each README.
3. A "Headline figures" list (6–8 figures we'll use in the report and slides) — propose the selection.
4. A "Weak results" section listing anything with n < 3 seeds, n/a values, CI width larger than the mean, or inconsistent direction across seeds.
5. A cross-check section: for each experiment, confirm that numbers in its README match its summary.csv (fail loudly if not).

Run it, send me RESULTS.md, and list which experiments you recommend re-running (§14.2–14.5 "re-run weak experiments").
```

---

## Phase C — Dashboard and visualization

### Prompt C1 — Dual-panel live dashboard (P1 + P6, §14.1 and §14.6)

```
Standing rules from Prompt 0 apply.

Build the final dashboard: a dual-panel view with the simulation on the left and live metrics on the right (§14.1, §14.6). Reuse simulation/renderer.py drawing code and the ideas in scripts/mvp_visual.py / mvp_visual_25d.py, but make a clean module.

Create visualization/dashboard.py and scripts/dashboard.py.

Left panel — simulation view:
- the three corridors with entry / merge / exit zones; agents coloured by type (EMERGENCY / EVTOL / DELIVERY) and marked by altitude layer (marker or label), short trails;
- emergency agent highlighted; malicious agent marked, with its falsified broadcast shown as a ghost and a line to the true position while the attack is active;
- top banner: sim time, architecture, scenario, DTC/overseer link UP/DOWN, directive age.

Right panel — metrics (stacked, shared time axis, scrolling window):
1. STL robustness ρ(t) with ρ=0 threshold, red shading during violations;
2. priority compliance: emergency agent's compliance status and progress vs nominal;
3. ADMM convergence: events per tick, converged vs non-converged, mean iterations and solve time (from A3 telemetry);
4. event timeline strip: attack active, link down, violations.

Modes:
- `--live`: runs the simulation and updates the figure as it goes (attach as a logger + telemetry consumer; update every k ticks from config visualization.dashboard_refresh_ticks).
- `--record <file.mp4|.gif>`: same frames rendered offline, deterministic (use ffmpeg if present, else GIF via Pillow).
- `--replay <run_dir>`: replay from saved trajectory.csv + telemetry.csv + stl_robustness.csv without re-simulating.
Options: --architecture, --scenario {nominal, mvp, emergency, demo}, --agents, --seed, --duration, --speed.

Add a `demo` scenario preset (config experiments.week6.demo_scenario) designed to show, in ~3 minutes of sim time: normal corridor formation, a merge, the emergency agent getting priority, the malicious agent from t=60 s, and the DTC link drop. Keep it deterministic.

Tests: dashboard renders a few frames headless for each mode with a short run; replay of a saved run matches live frame count. Then record a 30-second preview GIF, send it to me, and wait for feedback on layout before polishing.
```

### Prompt C2 — Dashboard polish, stability and performance (P6, §14.9 "runs without manual intervention")

```
Standing rules from Prompt 0 apply.

Using my feedback on the preview, finalize the dashboard:
1. Apply the layout changes I asked for.
2. Performance: the live mode must keep up at 60 agents. Measure frames/s, use blitting or artist updates instead of redrawing, decimate trails, and skip frames if behind. Report the achieved fps on the workspace and the expected speed on my laptop.
3. Stability: a full 180 s demo run in --live (headless backend) and --record must finish with zero exceptions; wrap optional panels so a missing telemetry field shows "n/a" instead of crashing; Ctrl+C closes cleanly and still saves what was recorded.
4. Readability for a projector: font sizes, high-contrast colours, legend that explains every marker, units on every axis.
5. Record the fallback video: outputs/week6/demo/fallback_demo.mp4 (and a GIF if ffmpeg is unavailable), full demo scenario, plus 3 short clips (formation+merge, emergency priority, attack+DTC outage).
6. Add a pytest smoke test that runs the dashboard in record mode for 10 s of sim time.

Copy the videos to my folder and send me the main one.
```

### Prompt C3 — Final visualization pass (P1, §14.1 "finalize the simulation visualization")

```
Standing rules from Prompt 0 apply.

Finalize the static visualizations used outside the dashboard:
1. Update simulation/renderer.py render_top_down and animate_simulation to use the shared style (A2) — same colours and legend as the dashboard — without changing their public signatures (existing tests must pass).
2. Make main.py's final_frame.png and optional --gif use the new style.
3. Produce one clean "system overview" figure for the report: corridors, zones, agent types, comm-graph edges for a snapshot, overseer icon, with labels (outputs/week6/figures/system_overview).
4. Produce a 2.5D side view figure showing altitude layers, labelled as layer index or metres consistently with what the code actually uses (check the config and engine; say which you used).

Send me the figures.
```

---

## Phase D — Reproducibility

### Prompt D1 — One-command reproduction: run_all (P1, §14.8)

```
Standing rules from Prompt 0 apply.

Write the reproducibility entry point required by §14.8: `scripts/run_all.sh` must reproduce all required experiment outputs and headline plots from a clean repository without manual intervention. I'm on Windows, so also provide `scripts/run_all.ps1`. Both should be thin wrappers around `scripts/run_all.py` so the logic lives in one place.

run_all.py stages (each skippable with flags, each timed and logged to outputs/week6/run_all.log):
1. environment check (Python version, required packages, prints versions);
2. pytest (if available; otherwise warn and continue);
3. main.py MVP smoke run for all three architectures;
4. E1–E6 run scripts (respecting resume), then E1–E6 plot scripts;
5. week6_summary.py → RESULTS.md;
6. dashboard --record of the demo scenario → fallback video;
7. final report: list of every expected artifact with ✓/✗ and total runtime; non-zero exit code if anything is missing.

Flags: --quick (1 seed, small N, short duration — under 5 minutes total), --only e1,e4, --skip-tests, --skip-video, --workers N, --fresh (ignore resume cache).

Also add a `run_all` section to the README. Test: run `--quick` end to end in the workspace and report runtime; estimate full runtime on 2 CPUs and on a typical 4–8 core laptop.
```

### Prompt D2 — Clean-clone check and documentation (P1, §14.1 "verify execution from a clean repository")

```
Standing rules from Prompt 0 apply.

Verify that a fresh clone works:
1. In the workspace, create a clean copy of the week6 branch containing only git-tracked files (no outputs/, no caches), install from pyproject with whatever is available offline, and run `scripts/run_all.sh --quick`. Fix anything that depends on untracked files, absolute paths, the current working directory, Windows-only or Linux-only behaviour, or a missing output folder.
2. Determinism check: run the quick matrix twice and diff the CSVs (ignoring wall-time columns); they must match exactly. Report any non-determinism and its cause.
3. Make sure .gitignore keeps large/generated files out of git but the headline figures and summary CSVs are committed (ask me if you're unsure what to commit).
4. Write docs/REPRODUCIBILITY.md: requirements, install (uv and pip), one-command run (Linux/macOS and Windows), expected runtime, where every output lands, how to change seeds/agent counts, how to regenerate figures only.
5. Rewrite README.md's outdated "Week 1 status" section into a current "Status and how to run" section: architecture summary, the three architectures, main.py usage, dashboard usage, run_all, experiments E1–E6 with links to their READMEs, and a short "Known limitations" list (mention that fixes to the separation metric and attack/defence path are in progress, without details).

Report the clean-clone result.
```

---

## Phase E — Report, slides, demo

### Prompt E1 — Report outline and figure plan (P6 + all, §14.6)

```
Standing rules from Prompt 0 apply.

Start the final report as a document I can export to Word/PDF. (If our course requires LaTeX or a specific template, ask me before starting.)

First create the outline only, with these sections and a 1–2 line intent for each:
1. Abstract
2. Introduction and problem statement (urban air traffic, why hierarchical)
3. Related work (boids, ADMM, W-MSR resilient consensus, STL robustness, UTM) — leave citation placeholders, I'll supply references
4. System architecture (two tiers, data model, interfaces, dependency graph from the workflow)
5. Methods: dynamics; communication graph; local behaviour and corridor merge; ADMM conflict resolution; global overseer and priority arbitration; attack model and W-MSR; STL monitoring
6. Baseline architectures (centralized, decentralized-undefended)
7. Experimental setup (config table §5.1, matrix Table 10, metrics Table 11, seeds, hardware)
8. Results E1–E6 (one subsection each)
9. Discussion (trade-offs, what worked, what didn't)
10. Limitations and threats to validity
11. Conclusion and future work
12. Team contributions (P1–P6 table)
Appendix: reproducibility (run_all), parameters.

Then map each figure from RESULTS.md's headline list and each table to a section. Show me the outline and figure plan before writing prose.
```

### Prompt E2 — Write the full report draft (P6 + all, §14.6 "first complete report")

```
Standing rules from Prompt 0 apply.

Write the full first draft of the report into the document from E1, section by section.

Rules for the writing:
- Source of truth for every number is outputs/week6/RESULTS.md and the experiment summary.csv files. Quote numbers with their CI and seed count; never type a number that isn't in those files.
- Methods sections must match the code as it actually is: read the module for each method (local_behavior/boids.py, conflict_resolution/*, simulation/overseer.py, resilience/*, verification/*) and write equations from the code, with config values.
- Describe ADMM as mitigation, W-MSR within its stated assumptions, and say where results are provisional pending the metric fix.
- Insert figures from outputs/week6/figures with numbered captions that state scenario, N, seeds and units.
- Limitations: corridor kinematic abstraction, sampled-time STL, single attack type, items from the teammate's bug-fix list once merged.
- Keep it to roughly 12–18 pages equivalent.

After writing, do a consistency pass: list every number in the report and confirm it against RESULTS.md; list any section that still has placeholders. Send me the link.
```

### Prompt E3 — Final presentation slides (P6, §14.6)

```
Standing rules from Prompt 0 apply.

Create the final presentation deck (~14–16 slides, ~15 minutes) from the report and RESULTS.md:
1. Title + team
2. Problem: urban air traffic at scale
3. Our approach: two-tier hierarchy (architecture diagram)
4. Local tier: boids + corridor merge
5. Conflict resolution: ADMM at merge points
6. Global overseer: corridors, priorities, link failure
7. Resilience: attack model + W-MSR
8. Verification: STL robustness monitor
9. Experimental setup (3 architectures, identical conditions, E1–E6)
10–14. One results slide per key finding (headline figures, one message per slide in the title)
15. Live demo (what the audience will see)
16. Limitations, conclusion and future work

Each slide: a one-sentence takeaway title, minimal text, the figure where relevant, speaker notes with what to say (~1 min each). Use the same colour scheme as the figures. Mark slides whose numbers are provisional. Send me the deck.
```

### Prompt E4 — Demo script (P6, §14.6 "write the final demo script")

```
Standing rules from Prompt 0 apply.

Write docs/DEMO_SCRIPT.md for the live demo (target 5 minutes), using the dashboard demo scenario:
1. Pre-demo checklist (laptop, power, display mirroring, Python env, exact commands pre-typed, fallback video open in a second window, run_all outputs present).
2. Timeline table: wall-clock time | sim time | what's on screen | what the presenter says (word-for-word lines) | what to point at.
   Beats: normal formation → corridor merge with ADMM → emergency agent gets priority → malicious agent appears at t=60 s and the defence response → DTC link drops and agents use cached directives → STL panel and closing summary.
3. Who speaks when (P1–P6 split).
4. Failure handling: exact triggers for switching to the fallback video (crash, frame rate below X, projector issue), and the line to say when switching.
5. Likely audience questions with short answers (why hierarchical, why ADMM not MPC, what if more than one attacker, real-world scale, safety guarantees).
6. Exact commands to launch each part, copied from the dashboard CLI.
```

### Prompt E5 — Dry runs and fallback (P6, §14.6 and §14.9)

```
Standing rules from Prompt 0 apply.

Run the demo dry runs. §14.9 requires the demo to succeed in two consecutive dry runs and a fallback video to exist.

1. Dry run 1: run the exact commands from docs/DEMO_SCRIPT.md (headless in the workspace, and give me the command to run it live on my laptop). Time every beat against the script. Record: start/end times, fps, any warning or exception, whether each beat appeared at the scripted sim time.
2. Fix anything that went wrong (timing drift, unreadable panel, beat happening at the wrong moment), then do dry run 2 and dry run 3 back-to-back; both must pass.
3. Log results in docs/DRY_RUNS.md (table per run + issues fixed).
4. Confirm the fallback video matches the current dashboard and demo scenario; re-record if not.
5. Give me a short checklist for the in-person rehearsal I'll do on my laptop with the team.
```

---

## Phase F — After the bug fixes are merged

### Prompt F1 — Regenerate everything on the fixed code

```
Standing rules from Prompt 0 apply.

My teammate's bug fixes are now merged into main (branch/commit: <FILL IN>). Bring week6 up to date and regenerate all results:
1. Merge main into week6; resolve conflicts, preferring their versions inside their files (rule 5) and keeping our additive hooks. Run the full test suite.
2. Read their changes and list what changed in metric definitions, attack/defence, compliance and outage behaviour. Update the methods text in the report accordingly.
3. Set experiments.week6.provisional to false and run `scripts/run_all.sh --fresh` (full, not quick).
4. Regenerate RESULTS.md, all figures and the fallback video.
5. Produce a before/after table: each headline number pre-fix vs post-fix, and flag every report sentence and slide whose claim changed direction.
6. Update the report, slides and demo script with the new numbers and figures; re-run the number-consistency check from E2.
Report what changed and anything that now needs a team decision.
```

### Prompt F2 — Final Week 6 Definition-of-Done audit (§14.9)

```
Standing rules from Prompt 0 apply.

Audit the project against workflow §14.9 and §14.1–14.6, item by item, with evidence (file path, command, or output) for each:
- All three architectures execute successfully (run them).
- All required experiments E1–E6 completed (check summaries, seed counts, no unexpected n/a).
- Required plots generated (list them, check none is stale vs its CSV by timestamp/hash).
- Dashboard runs without manual intervention (run record mode for the full demo).
- Weak experiments re-run where necessary.
- run_all works from a clean repository (repeat D2 quickly).
- Report complete (no placeholders, numbers consistent).
- Presentation complete.
- Demo succeeded in two consecutive dry runs (DRY_RUNS.md).
- Fallback video available.
Plus per-owner items from §14.1–14.6.

Output a checklist table (✓ / ✗ / partial + evidence), a list of remaining gaps with owner and estimated effort, and the exact final commit list. Don't commit until I say so.
```

---

### Tips

- If a prompt runs long or gets cut off, send **"continue from where you stopped"**.
- If you want a stage done differently, reply with the change before sending the next prompt; later prompts build on earlier outputs.
- B1–B5 can be run in any order after Phase A, but B6 needs all of them. C1 needs A2 + A3. D1 needs B and C. E2 onward needs B6.
