"""Tests for sps.plot_options.configure_ticks."""
import math
from types import SimpleNamespace
import pytest
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from sps.plot_options import configure_ticks


def _create_test_ax(xdata=(1.0, 5.0), ydata=(2.0, 8.0), xlim=(0.0, 10.0), ylim=(0.0, 10.0)):
    fig = Figure()
    FigureCanvasAgg(fig)
    ax = fig.add_subplot(111)
    ax.plot(xdata, ydata)
    ax.set_xlim(xlim)
    ax.set_ylim(ylim)
    return ax


def test_major_step_minor_counts_and_signed_reversed_limits():
    ax = _create_test_ax(xlim=(10.0, 0.0), ylim=(-5.0, 5.0))
    spec = SimpleNamespace(x_major_step=2.0, y_major_step=2.5, minor_divisions=3)
    configure_ticks(ax, spec)
    ax.figure.canvas.draw()
    assert 2.0 in ax.get_xticks()
    assert len(ax.xaxis.get_minorticklocs()) > 0
    assert len(ax.yaxis.get_minorticklocs()) > 0
    assert ax.get_xlim() == (10.0, 0.0)
    assert ax.get_ylim() == (-5.0, 5.0)


@pytest.mark.parametrize("bad_step", [0, 0.0, -1.0, float("nan"), float("inf"), True, False])
def test_zero_bool_nan_step_rejection(bad_step):
    ax = _create_test_ax()
    with pytest.raises((ValueError, TypeError)):
        configure_ticks(ax, SimpleNamespace(x_major_step=bad_step))


def test_log_rejection():
    ax = _create_test_ax(xlim=(1.0, 100.0))
    ax.set_xscale("log")
    with pytest.raises(ValueError, match="log scale x axis"):
        configure_ticks(ax, SimpleNamespace(x_major_step=10.0))
    with pytest.raises(ValueError, match="log scale x axis"):
        configure_ticks(ax, SimpleNamespace(minor_divisions=2))


def test_excessive_density_rejection():
    ax = _create_test_ax(xlim=(0.0, 1000.0))
    with pytest.raises(ValueError, match="Excessive tick density"):
        configure_ticks(ax, SimpleNamespace(x_major_step=0.1, minor_divisions=5))


def test_unchanged_data_and_limits():
    ax = _create_test_ax(xdata=[1.0, 2.0, 3.0], ydata=[4.0, 5.0, 6.0], xlim=(-1.0, 5.0), ylim=(0.0, 10.0))
    line = ax.lines[0]
    orig_x = list(line.get_xdata())
    orig_y = list(line.get_ydata())
    configure_ticks(ax, SimpleNamespace(x_major_step=1.0, minor_divisions=0))
    assert list(line.get_xdata()) == orig_x
    assert list(line.get_ydata()) == orig_y
    assert ax.get_xlim() == (-1.0, 5.0)
    assert ax.get_ylim() == (0.0, 10.0)
