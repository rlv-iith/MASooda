"""Rebuild every number, table and figure of the manuscript from the stored results.

Steps (each can also be run on its own):
  1. make_tables.py        Tables V-VIII rows, Figs. 4-5, results/numbers.json   (needs runs_final.jsonl)
  2. fig_estimator.py      Fig. 3                                                 (needs s0_estimator.csv.gz)
  3. fig_map.py            Fig. 1                                                 (needs the repository map)
  4. cross_platform_check  results/cross_platform_check.txt
  5. make_results_tex.py   manuscript/masooda_paper.tex                           (needs case_study.json)
Add --simulate to first re-run the cheap simulations: estimator_validation.py (~4 min) and
case_study.py (~1 min). The 460 traffic runs are re-run with run_experiments (see README).
Then compile manuscript/masooda_paper.tex with pdflatex (twice) and the IEEEtran class.
"""
import runpy
import sys
import paths  # noqa: F401  (checks the repository location)

steps = ["make_tables", "fig_estimator", "fig_map", "cross_platform_check", "make_results_tex"]
if "--simulate" in sys.argv:
    steps = ["estimator_validation", "case_study"] + steps
for s in steps:
    print(f"--- {s}", flush=True)
    sys.argv = [s + ".py"]
    runpy.run_path(str(paths.EXP / f"{s}.py"), run_name="__main__")
print("done: manuscript/masooda_paper.tex")
