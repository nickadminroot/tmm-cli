"""Editable native XY graphs, including parametric curves and hodographs."""

import re
from dataclasses import dataclass, field

from .document import Region, element
from .expressions import ExpressionInput, expr
from .types import LineStyle, Marker

MARKERS = {
    "none": 0,
    "cross": 1,
    "plus": 2,
    "square": 3,
    "diamond": 4,
    "circle": 5,
    "triangle": 6,
    "filled-square": 7,
    "filled-diamond": 8,
    "filled-circle": 9,
    "filled-triangle": 10,
}


@dataclass(frozen=True)
class Trace:
    x: ExpressionInput
    y: ExpressionInput
    color: str | None = None
    style: LineStyle = LineStyle.SOLID
    marker: Marker = Marker.NONE

    def __post_init__(self):
        object.__setattr__(self, "x", expr(self.x))
        object.__setattr__(self, "y", expr(self.y))
        if self.color is not None and not re.fullmatch(r"#[0-9a-fA-F]{6}", self.color):
            raise ValueError("Trace color must be #RRGGBB")
        if not isinstance(self.style, LineStyle):
            raise TypeError("style must be a LineStyle")
        if not isinstance(self.marker, Marker):
            raise TypeError("marker must be a Marker")


@dataclass
class XYPlot(Region):
    _polar = False
    traces: tuple[Trace, ...]
    width: float = field(default=320, kw_only=True)
    height: float | None = field(default=None, kw_only=True)
    x_bounds: tuple[float | None, float | None] = (None, None)
    y_bounds: tuple[float | None, float | None] = (None, None)
    x_grid: bool = False
    y_grid: bool = False

    def __post_init__(self):
        super().__post_init__()
        self.traces = tuple(self.traces)
        if not self.traces or any(not isinstance(t, Trace) for t in self.traces):
            raise ValueError("A graph needs Trace objects")
        if len(self.traces) > 16:
            raise ValueError("Classic Mathcad XY graphs support up to 16 traces")
        for bounds in (self.x_bounds, self.y_bounds):
            if len(bounds) != 2:
                raise ValueError("Axis bounds must be (minimum, maximum)")
            for b in bounds:
                if b is not None:
                    expr(b)
            if all(b is not None for b in bounds) and bounds[0] >= bounds[1]:
                raise ValueError("Axis maximum must exceed minimum")

    def content_xml(self, context):
        from ._plot_binary import graph_bytes

        return element("plot", disable_calc="false", item_idref=context.binary(graph_bytes(self)))


class PolarPlot(XYPlot):
    """Native polar graph: Trace(angle in radians, radius)."""

    _polar = True
