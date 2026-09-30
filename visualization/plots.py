"""Shared plotting utilities for MASooda."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence
import matplotlib.pyplot as plt

from simulation.mock_data import get_mock_agent_states, get_mock_comm_graph
from simulation.renderer import render_top_down, CorridorGeometry
from simulation.schema import AgentState, CommunicationGraph


def plot_airspace(
    agents: Sequence[AgentState] | None = None,
    corridors: Sequence[CorridorGeometry] | None = None,
    comm_graph: CommunicationGraph | None = None,
    save_path: str | Path | None = None,
    show: bool = False,
) -> plt.Figure:
    """Plot the top-down airspace map showing agents and corridors."""
    return render_top_down(
        agents=agents,
        corridors=corridors,
        comm_graph=comm_graph,
        save_path=save_path,
        show=show,
    )
