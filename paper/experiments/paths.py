"""Folder layout shared by every script in this package.

The package is meant to sit inside the MASooda repository (``<repo>/paper``) on branch
``bms/publishable``. If it lives elsewhere, set ``MASOODA_REPO`` to the repository root.
"""
import os
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
REPO = Path(os.environ.get("MASOODA_REPO", PKG.parent)).resolve()
EXP = PKG / "experiments"
RESULTS = PKG / "results"
TABLES = RESULTS / "tables"
ESTIMATOR = RESULTS / "estimator"
DIAG = RESULTS / "diagnostics"
MANUSCRIPT = PKG / "manuscript"
RUNS = RESULTS / "runs_final.jsonl"
RUNS_SECOND = RESULTS / "runs_second_platform.jsonl"

for p in (str(REPO), str(EXP)):
    if p not in sys.path:
        sys.path.insert(0, p)
if not (REPO / "simulation" / "route_engine.py").exists():
    raise SystemExit(f"MASooda repository not found at {REPO}; set MASOODA_REPO to the repository root")
