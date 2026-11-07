"""SPS plot options and tick configuration module."""
import math
from matplotlib.ticker import AutoMinorLocator, MultipleLocator, NullLocator


def _validate_step(val, name):
    if val is None:
        return None
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise TypeError(f"{name} must be a positive finite number, got {val!r}")
    if not math.isfinite(val) or val <= 0:
        raise ValueError(f"{name} must be a positive finite number, got {val!r}")
    return float(val)


def _validate_minor_divisions(val):
    if isinstance(val, bool) or not isinstance(val, int):
        raise TypeError(f"minor_divisions must be an integer 0..10, got {val!r}")
    if not (0 <= val <= 10):
        raise ValueError(f"minor_divisions must be between 0 and 10, got {val!r}")
    return val


def _get_field(spec, field_name, default=None):
    if isinstance(spec, dict):
        return spec.get(field_name, default)
    return getattr(spec, field_name, default)


def configure_ticks(ax, spec):
    """Configure linear axis major steps and minor divisions safely.

    Parameters
    ----------
    ax : matplotlib.axes.Axes
        Target axes object with limits and scales already configured.
    spec : object or dict
        Specification containing x_major_step, y_major_step, and minor_divisions.
    """
    x_step = _validate_step(_get_field(spec, "x_major_step"), "x_major_step")
    y_step = _validate_step(_get_field(spec, "y_major_step"), "y_major_step")
    minor_div = _validate_minor_divisions(_get_field(spec, "minor_divisions", 0))

    axes_meta = [
        ("x", ax.xaxis, ax.get_xscale(), x_step),
        ("y", ax.yaxis, ax.get_yscale(), y_step),
    ]

    for axis_name, axis, scale, step in axes_meta:
        if scale == "log":
            if step is not None or minor_div > 0:
                raise ValueError(
                    f"Cannot apply linear tick step or minor divisions on log scale {axis_name} axis"
                )
            continue

        if step is not None:
            low, high = axis.get_view_interval()
            span = abs(high - low)
            mult = minor_div + 1
            if (span / step) * mult > 2000:
                raise ValueError(
                    f"Excessive tick density on {axis_name} axis: span={span}, step={step}, minor_divisions={minor_div}"
                )
            axis.set_major_locator(MultipleLocator(step))

        if minor_div > 0:
            axis.set_minor_locator(AutoMinorLocator(minor_div + 1))
        else:
            axis.set_minor_locator(NullLocator())
