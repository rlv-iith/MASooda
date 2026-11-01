"""Unit tests for the minimal top-down airspace renderer."""

from pathlib import Path
import matplotlib.pyplot as plt

from simulation.renderer import render_top_down
from simulation.mock_data import get_mock_agent_states


def test_render_top_down_creates_figure() -> None:
    """Renderer returns a valid matplotlib figure with axes and artists."""
    fig = render_top_down()
    assert isinstance(fig, plt.Figure)
    assert len(fig.axes) > 0
    plt.close(fig)


def test_render_top_down_saves_file(tmp_path: Path) -> None:
    """Renderer writes a PNG image to the specified path."""
    out_file = tmp_path / "test_render.png"
    fig = render_top_down(save_path=out_file)
    assert out_file.is_file()
    assert out_file.stat().st_size > 0
    plt.close(fig)
