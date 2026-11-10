# MASooda paper: code, results and walkthrough

This folder holds everything behind the manuscript *BMS-in-the-Loop Traffic Management for Urban Drone Fleets: Chance-Constrained Energy Reserves, Pad Arbitration, and Energy-Weighted ADMM Deconfliction* (target: IEEE Access):

- the LaTeX source and figures,
- the scripts that produced every number,
- the raw results of all 460 simulation runs,
- the unit tests that check the mechanisms the paper describes.

Every number, table and figure in the manuscript can be regenerated from this folder.

The code under study is branch `bms/publishable` of the MASooda repository (head `22c5400`). The folder is meant to sit in the repository root as `paper/`. If you put it somewhere else, set `MASOODA_REPO` to the repository root.

```
paper/
  README.md                         this walkthrough
  manuscript/
    masooda_paper.tex               the manuscript (generated; tables inlined)
    masooda_paper_template.tex      the hand-written part, with %%RESULTS%% etc. placeholders
    fig_map.pdf  fig_estimator.pdf  fig_lowsoc.pdf  fig_scaling.pdf
    masooda_paper_preview.pdf       layout preview (built with a minimal stand-in class, not IEEEtran)
  experiments/
    paths.py                        folder layout used by all scripts
    paper_experiments.py            definition of the 460 runs (same file as scripts/paper_experiments.py)
    run_experiments.py              re-run the 460 traffic simulations
    estimator_validation.py         EKF validation (Table IV, Fig. 3 data)
    case_study.py                   battery-failure case study (Section VIII-F)
    analyze.py                      loader and statistics helpers (95% t-intervals, paired differences)
    make_tables.py                  Tables V-VIII, Figs. 4-5, results/numbers.json
    fig_estimator.py  fig_map.py    Figs. 3 and 1
    cross_platform_check.py         reproducibility check (Section VIII-A)
    diagnose_seed13.py              trace of the seed-13 forced landing (Sections VIII-C, IX)
    make_results_tex.py             writes the abstract, results, discussion and conclusion into the manuscript
    build_paper.py                  runs the analysis steps in order
  results/
    runs_final.jsonl                the 460 runs the paper reports (one JSON object per run)
    runs_second_platform.jsonl      runs repeated on a second machine
    rerun_after_holdshort_fix_keys.txt   the 160 runs re-executed after the hold-short fix
    numbers.json                    every aggregated value (mean, 95% CI half-width, n)
    tables/tab_s1..s4.tex           table rows as inlined in the manuscript
    estimator/s0_estimator.csv.gz   EKF validation samples (drone x second)
    estimator/s0_summary.json       Table IV values
    case_study.txt / .json          case-study event timeline and statistics
    cross_platform_check.txt        output of the reproducibility check
    diagnostics/seed13_full.txt, seed13_blind.txt
    test_report.txt                 result of the unit tests below (103 passed)
  tests/                            copies of the 9 test files that back the paper (originals in the repo's tests/)
  conftest.py                       stops pytest from collecting the copies (run the originals in <repo>/tests)
```

## 1. Checking the paper in three commands

Requirements: the repository's own dependencies plus matplotlib (scipy is optional; without it the t-quantile is computed exactly by `analyze.py`). From the repository root, on branch `bms/publishable`:

```
python -m pytest -q tests/test_drone_health.py tests/test_route_mode.py tests/test_scenario_presets.py tests/test_admm_solver.py tests/test_stl_monitor.py tests/test_wmsr.py tests/test_route_phase2.py tests/test_route_spatial.py tests/test_route_custom_drones.py
python paper/experiments/build_paper.py --simulate
pdflatex masooda_paper.tex   (twice, inside paper/manuscript, with the IEEEtran class)
```

- **The tests** take about 2 minutes. They should report 103 passed, as in `results/test_report.txt`.
- **The build** takes about 1 minute. `--simulate` re-runs the estimator validation and the case study. It then rebuilds every table, figure and `numbers.json` from `results/runs_final.jsonl` and rewrites `manuscript/masooda_paper.tex`.
  - When this folder was assembled, the rebuilt `numbers.json` matched the original analysis to a relative difference of 4e-16 (summation order only).
  - `s0_summary.json` and the case study came out identical.
- **The 460 traffic runs** are not re-run by `build_paper.py`. They took about 2.6 core-hours (21 s per run on average). To repeat them:

```
python paper/experiments/run_experiments.py --workers 4          # writes paper/results/rerun/runs.jsonl
python paper/experiments/make_tables.py paper/results/rerun/runs.jsonl
```

  `make_tables.py` with a path overwrites `results/numbers.json` and `results/tables/` with the new set. Then run `make_results_tex.py` to update the manuscript.

## 2. How the results were produced

- **Run definition.** `paper_experiments.py` defines 460 jobs. Each job is one headless `simulate_routes` call, built with `web_sandbox.server.prepare_live_run`, so it uses the same code and validation as the live demo.
  - A job key is `scenario|manager|knowledge|architecture|N<fleet>|<extra>|s<seed>`.
  - Arms with the same seed share all initial conditions (fleet, routes, departure times, SoC, faults). That is what makes the paired comparisons valid.
- **Run history** (this matters for reproducibility):
  1. All runs were started after commit `fccf49a`. That commit corrects the capacity term of the chance-constrained energy, which had overestimated energy about 29% of the time. Earlier runs were discarded.
  2. The runs were split between this workspace (Linux, Python 3.13, NumPy 2.5) and a second machine (Linux, Python 3.10, NumPy 2.2). Continuous values differ slightly between platforms, so the paper reports only workspace-platform runs, and every run was executed there.
  3. The experiments exposed a deadlock: a drone holding short at the tube edge was treated as traffic ahead and blocked its lane, which caused one forced landing. Commit `b4f9e55` fixes it. The 160 runs whose behaviour depends on hold-short were re-executed after the fix: the Rule and Full arms of the low-SoC and fault scenarios, and the whole knowledge suite. They are listed in `rerun_after_holdshort_fix_keys.txt`.
  4. `runs_final.jsonl` is the merge of all workspace runs. A later execution of the same key replaces the earlier one.
- **Reproducibility check.** `cross_platform_check.py` compares the 132 runs that exist on both machines and were not re-executed. All ten discrete metrics are identical in every run. The largest continuous differences are 1.3e-4 m in minimum separation and 0.1 Wh in energy per delivery.
- **Statistics.** `analyze.py` reports means with 95% t-intervals across seeds. Paired differences are computed per seed: arm B minus arm A for the same seed, then the t-interval of those differences.

### What one run record contains

Top-level fields:

| Field | Content |
|---|---|
| `key`, `suite`, `scenario`, `manager`, `knowledge`, `architecture`, `fleet`, `seed`, `extra` | the job |
| `flights` | number of flights, including the scripted fault drones |
| `wall_s`, `rtf` | wall time and real-time factor |
| `stats` | final run statistics (below) |
| `prio` | emergency-flight metrics: `mean_delay_s`, `on_time_rate`, `arrived`, `count`, `rate`, `mean_ground_hold_s` |
| `admm_run` | ADMM groups, convergence, iteration counts, solve-time mean and 95th percentile |
| `faults` | one entry per scripted fault drone (below) |

The `stats` metrics used in the paper:

| Metric | Meaning |
|---|---|
| `arrivals` | landed at any pad |
| `delivered` | landed at the planned destination |
| `diversions` | flights that diverted |
| `grounded_preflight` | failed the pre-flight check |
| `forced_landings` | landed in place, off any pad |
| `energy_depleted` | true SoC reached zero in flight |
| `pads_held_short` | arrivals that waited for a reserved pad |
| `near_misses` | loss-of-separation episodes |
| `safety_violation_ticks` | ticks with a separation violation |
| `min_separation_m` | minimum layer-aware separation |
| `crashes` | collisions (pairs closer than 2 m) |
| `spoofed_reports_accepted` | spoofed position reports accepted |
| `overseer_dropped` | DTC directives dropped during an outage |
| `energy_per_delivered_wh` | energy per delivered parcel |

Each `faults` entry has the drone `id`, the `fault` type and time `t_fault`, the times of CRITICAL/FAULT (`crit_t`), diversion (`divert_t`), landing on a pad (`land_t`) or forced landing (`forced_t`), and the last true and estimated SoC.

## 3. Claim-by-claim map

Section and table numbers refer to `manuscript/masooda_paper.tex`.

| Paper item | Produced by | Data | Key values |
|---|---|---|---|
| Fig. 1 campus corridor map | `fig_map.py` | repo `data/iith_campus.geojson` | 13 vertiports (V1 hospital; V8, V10, V13 depots) |
| Fig. 2 architecture | TikZ in the template | none | none |
| Tables II-III, Sections IV-VII (models, thresholds, method) | hand-written from the code on the branch; parameters from `configs/base_config.yaml` | none | checked by the tests in Section 4 |
| Table IV, Fig. 3, Section VIII-B (EKF validation) | `estimator_validation.py`, `fig_estimator.py` | `estimator/s0_*` | SoC error below 1.0% in nominal flight and below 1.3% in all fault conditions; within 3 sigma in 100% of samples; energy never overestimated in nominal flight; 9% of samples overestimated after a sudden capacity loss, never after 180 s |
| Table V, Section VIII-C (manager ablation) | `make_tables.py` (suite S1) | `runs_final.jsonl`, `numbers.json` keys `S1_*` | held short +7.7 +/- 2.2 per run (low SoC, Full vs Blind); emergency delay +0.9 +/- 0.8 s; no depletion or near miss in any run |
| Seed-13 forced landing (Sections VIII-C, IX) | `diagnose_seed13.py` | `diagnostics/seed13_*.txt` | Full: D-101 diverts at 54 s, D-40 holds short at 97.4 s, ADMM conflict 98.7-106.1 s, FAULT (under-voltage) and forced landing at 106 s. Blind: D-101 lands at V11 at 109.5 s |
| Heat-wave timing (Section VIII-C) | `make_results_tex.py` reads the `faults` entries of the heat runs | `runs_final.jsonl` | CRITICAL 59 s after the fault (56-61 s), FAULT 32 s later, diversion starts after 30 s at CRITICAL |
| Table VI, Fig. 4, Section VIII-D (BMS knowledge) | `make_tables.py` (suites S1 and S2) | keys `S2_*` | vs oracle: +6.4 +/- 1.0 grounded, -3.5 +/- 1.1 diversions, deliveries -0.2 +/- 0.7 |
| Table VII, Section VIII-E (architectures) | `make_tables.py` (suite S3) | keys `S3_*` | centralized 9.85 near misses and 1.10 collisions per run; the others none |
| Table VIII (attack and outage) | `make_tables.py` (suites S4, S6) | keys `S4_*`, `S6_d_*` | undefended accepts 193 +/- 110 spoofed reports per run, defended 0; outage drops 35 directives and changes no outcome |
| Fig. 5 (scaling) | `make_tables.py` (suite S5) | keys `S5_N*` | ADMM 95th-percentile solve time about 0.45 ms up to 200 drones; real-time factor 22.2 at 50 drones, 5.7 at 200 |
| Section VIII-F case study | `case_study.py` | `case_study.txt` | D-100 CRITICAL at 70 s and lands at 117.9 s; D-101 low-reserve divert at 144 s and lands at 172.7 s; no forced landing or near miss |
| "132 runs on a second machine" (Section VIII-A) | `cross_platform_check.py` | `cross_platform_check.txt` | 0 runs with a discrete difference |
| Abstract, Discussion, Conclusion | `make_results_tex.py` | all of the above | every value is read from the files, not typed in |

The comparison of the case study with the earlier public deployment comes from a manual audit of masooda.onrender.com, not from a script in this folder. That comparison is: three drones on one reserved pad within 7 s, and a low-reserve drone sent to the critical drone's pad.

## 4. Tests behind the method sections

The 9 test files in `tests/` contain 103 tests, all passing (`results/test_report.txt`). The ones that check specific statements in the paper:

| Paper statement | Test |
|---|---|
| Momentum-theory power, parasitic drag, air density at site elevation and temperature | `test_drone_health.py::test_power_matches_momentum_theory_and_has_a_bucket`, `::test_air_density_hot_and_high_is_thinner`, `::test_weather_controls_change_power_and_are_validated` |
| Energy balance OCV*I = P + heat, to 1e-9 | `test_drone_health.py::test_energy_is_conserved_and_soc_falls_monotonically` |
| Weakest-cell usable energy | `test_drone_health.py::test_weakest_cell_limits_usable_energy` |
| BMS categories, thresholds and hysteresis (Table III); fault models | `::test_low_charge_status_levels_with_hysteresis`, `::test_faults_raise_the_right_bms_status`, `::test_capacity_loss_and_motor_degradation`, `::test_overheating_fault_heat_comes_out_of_the_cells`, `::test_sensor_fault_lands_in_place_and_frames_stay_deterministic` |
| EKF tracks SoC; the chance-constrained energy stays conservative; capacity loss is learnt; the oracle arm reads the true state; sensor noise is per drone | `::test_ekf_tracks_soc_and_decisions_stay_conservative`, `::test_ekf_learns_a_sudden_capacity_loss`, `::test_estimator_off_is_the_oracle_and_noise_is_per_drone` |
| Feasibility test: energy, voltage sag, lift, cruise-power range; pre-flight grounding | `::test_lift_and_voltage_sag_checks`, `::test_range_uses_cruise_power_not_momentary_speed`, `::test_preflight_check_grounds_an_empty_drone`, `::test_overweight_drone_is_grounded_on_lift_not_energy` |
| Onboard responses and DTC health rule (low-reserve diversion; CRITICAL gets right of way and lands) | `::test_low_reserve_diverts_and_nobody_runs_dry`, `::test_critical_fault_gets_right_of_way_and_lands` |
| Energy-margin ADMM weights: bounded, rising as the margin shrinks, class weight with a full pack (Proposition 1 (i)-(ii)) | `::test_admm_weight_rises_as_the_energy_margin_shrinks` |
| Same seed gives the same run; paired arms share initial conditions | `::test_same_seed_same_trace_and_random_fleet_ranges`, `test_route_phase2.py::test_phase2_frames_are_deterministic`, `::test_architectures_share_initial_conditions_and_differ_in_control`, `test_route_spatial.py::test_engine_identical_with_and_without_spatial_index` |
| Consensus ADMM: separation, speed limit, convergence; solve-time profiling | `test_admm_solver.py` (7 tests), `test_route_phase2.py::test_admm_probe_p95_equals_profiling_summarize` |
| Corridor tube, geofence and layer-aware separation; emergency layer; DTC outage; crash counting; campus map | `test_route_mode.py` (14 tests) |
| Trusted-range check and W-MSR | `test_wmsr.py` (5 tests), `test_route_mode.py::test_spoofing_reports_filtered_or_accepted`, `test_route_phase2.py::test_spoofer_estimate_trims_outlier_and_falls_back_to_median` |
| STL robustness rho(t) | `test_stl_monitor.py` (15 tests), including `::test_rho_formula_matches_bruteforce` |
| Emergency delay and on-time definitions | `test_route_phase2.py::test_emergency_tracker_definitions` |
| Fault drones injected as scripted custom rows; battery-failure preset timeline | `test_route_custom_drones.py`, `test_scenario_presets.py::test_battery_failure_preset_follows_its_timeline` |

**Not covered by a dedicated unit test:** the details of endurance-ordered pad arbitration, meaning the ordering by tau, the 15 s swap threshold, the 150 m activation and the 60 m hold-short point. These are exercised by the battery-failure preset test and the case study, and measured in the experiments (the held-short counts in Table V and the seed-13 trace), but no test asserts them directly.

## 5. Caveats a reviewer should know

- **Simulation only.** All results come from simulation. The battery, power and thermal models are not calibrated against real hardware.
- **Seed 13.** Health-aware arbitration shows no measurable benefit, and in seed 13 it causes a forced landing. Neither this nor the heat-wave limitation has been fixed. Fixing either changes the code and needs the affected runs re-executed.
- **Week 6.** Earlier Week 6 experiments (E1-E6) are not part of the paper.
- **Branch not public yet.** Branch `bms/publishable` is not pushed. The public demo at masooda.onrender.com still runs the earlier version.
- **Preview layout.** `masooda_paper_preview.pdf` was built with a stand-in document class, so its fonts and spacing are not IEEE's.
