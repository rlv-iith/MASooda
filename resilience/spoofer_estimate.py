"""P5 route-mode estimate of a spoofer's true position (live demo).

``resilience.defense.defend_neighbor_reports`` (unchanged) runs on every
receiving drone. For a report whose range disagrees with the sensed range it
keeps a *corrected* position: the reported bearing at the sensed range. Its
``wmsr_estimate`` is the receiver's own-position consensus, not an estimate of
the spoofer.

This module fuses what all receivers corrected one spoofer to, using the
project's W-MSR filter (``resilience.wmsr.wmsr_vector``): the anchor is the
coordinate-wise median of the corrections, and up to ``f`` extreme corrections
on each side of it are trimmed before averaging. With ``<= 2f`` corrections
W-MSR returns the median, as in ``wmsr.py``.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np

from resilience.wmsr import wmsr_vector


def estimate_spoofer_position(corrections: Sequence[Sequence[float]], f: int = 1) -> np.ndarray | None:
    """W-MSR fusion of receivers' corrected positions for one spoofer (2D)."""
    pts = [np.asarray(c, dtype=float)[:2] for c in corrections]
    if not pts:
        return None
    anchor = np.median(np.stack(pts), axis=0)
    return wmsr_vector(anchor, pts, int(f))


def report_status(reported_ids: Sequence[int], dropped_ids: Sequence[int], checked_ids: Sequence[int]) -> list[list]:
    """Trust status of each neighbour report seen by one receiver.

    ``kept``: range-consistent; ``corrected``: range mismatch, report dropped and
    replaced by the range-consistent position; ``unverified``: no range
    measurement for that neighbour, report used as received.
    """
    dropped, checked = set(dropped_ids), set(checked_ids)
    return [[int(r), "corrected" if r in dropped else ("kept" if r in checked else "unverified")]
            for r in reported_ids]
