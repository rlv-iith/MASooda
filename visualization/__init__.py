"""MASooda visualization package.

Submodules are imported lazily so ``python -m visualization.plots`` runs
cleanly; ``from visualization import plot_airspace`` keeps working.
"""

from __future__ import annotations

__all__ = ["plot_airspace"]


def __getattr__(name: str):
    if name == "plot_airspace":
        from .plots import plot_airspace

        return plot_airspace
    raise AttributeError(f"module 'visualization' has no attribute {name!r}")
