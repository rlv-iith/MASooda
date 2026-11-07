"""MASooda dual-panel dashboard CLI (see visualization/dashboard.py).

Examples::

    # replay a run written by main.py --telemetry
    python main.py --scenario mvp --telemetry --out outputs/mvp
    python scripts/dashboard.py --replay outputs/mvp --out outputs/mvp/dashboard.gif

    # simulate and record offline
    python scripts/dashboard.py --record outputs/week6/demo/preview.gif --scenario mvp --agents 60 --duration 30

    # live window (refresh every visualization.dashboard_refresh_ticks ticks)
    python scripts/dashboard.py --live --scenario demo
"""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from visualization.dashboard import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
