"""Re-run the 460 traffic simulations of Section VIII (suites S1-S6, 20 paired seeds).

Thin wrapper around paper_experiments.py (the same file as scripts/paper_experiments.py on the branch).
Output goes to results/rerun/runs.jsonl and is resumable;
use several workers (the full set took about 2.6 core-hours: 21 s per run on average, 47 s at most). To analyse a fresh run set, point the analysis at it:
    python run_experiments.py --workers 4
    python make_tables.py results/rerun/runs.jsonl
Options are passed through: --seeds N, --only S2 (one suite or a key substring), --shard i/n, --list.
"""
import sys
import paths
import paper_experiments as pe

if __name__ == "__main__":
    if "--out" not in sys.argv:
        sys.argv += ["--out", str(paths.RESULTS / "rerun")]
    pe.main()
