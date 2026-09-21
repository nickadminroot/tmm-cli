"""Worksheet composition and serialization to classic Mathcad XML 3.0.3.

Coordinates and dimensions use points, relative to the worksheet's content area.
Serialization does not evaluate expressions or require an installed Mathcad.
"""

from __future__ import annotations

import base64
import math
from copy import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .semantic import ValidationContext, ValidationReport

from lxml import etree as ET

from .expressions import ExpressionInput, serialize_expression
from .layout import LayoutError, ResultShape, ShapeContext, math_metrics
from .types import MatrixStyle, NumberFormat, Orientation, TextStyle

WS = "http://schemas.mathsoft.com/worksheet30"
ML = "http://schemas.mathsoft.com/math30"
NS = {"ws": WS, "ml": ML}


def element(tag: str, /, parent=None, text: str | None = None, **attrs):
    attributes = {k.replace("_", "-"): str(v) for k, v in attrs.items()}
    node = ET.Element(f"{{{WS}}}{tag}", attributes)
    node.text = text
    if parent is not None:
        parent.append(node)
    return node


class Expression(Protocol):
    def to_xml(self) -> ET._Element: ...


@dataclass
class SerializationContext:
    """Per-write identifiers: reusing a region does not duplicate IDs."""

    region_id: int = 0
    binaries: list[bytes] = field(default_factory=list)

    def next_region(self) -> int:
        self.region_id += 1
        return self.region_id

    def binary(self, data: bytes) -> int:
        self.binaries.append(data)
        return len(self.binaries)


@dataclass(kw_only=True)
class Region:
    left: float = 0
    top: float | None = None
    width: float = 400
    height: float | None = None
    tag: str = ""
    border: bool = False
    _auto_top: bool = field(init=False, repr=False)
    _auto_height: bool = field(init=False, repr=False)
    _axis: float | None = field(default=None, init=False, repr=False)

    def __post_init__(self):
        self._auto_top = self.top is None
        self._auto_height = self.height is None
        for name in ("left", "top", "width", "height"):
            value = getattr(self, name)
            if value is not None and (not math.isfinite(value) or value < 0):
                raise ValueError(f"{name} must be finite and nonnegative")

    def content_xml(self, context: SerializationContext) -> ET._Element:
        raise NotImplementedError

    def to_xml(self, context: SerializationContext | None = None) -> ET._Element:
        if self.height is None or self.top is None:
            resolved = copy(self)
            _place(resolved, ShapeContext(), 10, 0)
            return resolved.to_xml(context)
        context = context if context is not None else SerializationContext()
        node = element(
            "region",
            region_id=context.next_region(),
            left=self.left,
            top=self.top,
            width=self.width,
            height=self.height,
            align_x=self.left,
            align_y=self.top + min(self.height, 12),
            tag=self.tag,
            show_border=str(self.border).lower(),
            is_protected="false",
        )
        node.append(self.content_xml(context))
        return node


@dataclass(frozen=True)
class ResultFormat:
    precision: int = 6
    notation: NumberFormat = NumberFormat.GENERAL
    matrix_style: MatrixStyle = MatrixStyle.MATRIX
    table_min_rows: int = 20

    def __post_init__(self):
        if not isinstance(self.notation, NumberFormat):
            raise TypeError("notation must be a NumberFormat")
        if not isinstance(self.matrix_style, MatrixStyle):
            raise TypeError("matrix_style must be a MatrixStyle")
        if type(self.table_min_rows) is not int or self.table_min_rows < 1:
            raise ValueError("table_min_rows must be a positive integer")
        if not isinstance(self.precision, int) or not 0 <= self.precision <= 17:
            raise ValueError("Mathcad precision must be an integer from 0 to 17")

    def to_xml(self, name="resultFormat"):
        node = element(name)
        element(self.notation, node, precision=self.precision)
        element("matrix", node, display_style=self.matrix_style)
        return node


@dataclass
class MathRegion(Region):
    expression: Expression
    result_format: ResultFormat | None = None
    disabled: bool = False
    result_shape: ResultShape | None = None

    def __post_init__(self):
        super().__post_init__()
        if not callable(getattr(self.expression, "to_xml", None)):
            raise TypeError("MathRegion requires an expression object")

    def to_xml(self, context=None):
        node = super().to_xml(context)
        # Mathcad positions a formula by its mathematical axis. Tall matrices,
        # programs and result tables extend both above and below that axis.
        if self.top is not None and self.height is not None:
            node.set(
                "align-y",
                str(self.top + (self._axis if self._axis is not None else self.height / 2)),
            )
        return node

    def content_xml(self, context):
        node = element("math", disable_calc=str(self.disabled).lower())
        node.append(serialize_expression(self.expression))
        if self.result_format is not None:
            node.append(self.result_format.to_xml())
        return node


@dataclass
class TextRegion(Region):
    text: str
    style: TextStyle = TextStyle.NORMAL

    def __post_init__(self):
        super().__post_init__()
        if not isinstance(self.style, TextStyle):
            raise TypeError("style must be a TextStyle")

    def content_xml(self, context):
        node = element("text", use_page_width="false", lock_width="true")
        for line in self.text.split("\n"):
            element("p", node, text=line, style=self.style)
        return node


@dataclass
class PageBreak(Region):
    def content_xml(self, context):
        return element("pageBreak")


@dataclass
class Area(Region):
    name: str
    regions: list[Region] = field(default_factory=list)
    collapsed: bool = False

    def content_xml(self, context):
        node = element(
            "area",
            name=self.name,
            is_collapsed=str(self.collapsed).lower(),
            top_lock_id=context.next_region(),
            bottom_lock_id=context.next_region(),
            show_name="true",
        )

        def translate(child):
            for attr, offset in (
                ("left", self.left),
                ("align-x", self.left),
                ("top", self.top),
                ("align-y", self.top),
            ):
                child.set(attr, str(float(child.get(attr)) + offset))
            nested = child.find("ws:area", NS)
            if nested is not None and nested.get("is-collapsed") == "false":
                for descendant in nested:
                    translate(descendant)

        for region in self.regions:
            child = region.to_xml(context)
            # Expanded areas use worksheet coordinates; collapsed ones use local coordinates.
            if not self.collapsed:
                translate(child)
            node.append(child)
        return node


def _place(region, context, size, cursor, default_format=None, strict=True):
    from .layout import measure
    from .plots import XYPlot

    if region._auto_top:
        region.top = cursor
    if isinstance(region, Area):
        region.regions = [copy(child) for child in region.regions]
        end = size * 2
        for child in region.regions:
            _place(child, context, size, end, default_format, strict)
            end = max(end, child.top + child.height + getattr(child, "_flow_extra", 0) + 12)
        if region._auto_height:
            region.height = end + size * 2
    elif isinstance(region, MathRegion):
        if region._auto_height:
            fmt = region.result_format or default_format or ResultFormat()
            try:
                metrics = math_metrics(
                    region.expression,
                    context,
                    size,
                    region.result_shape,
                    fmt.matrix_style == "table",
                    fmt.table_min_rows,
                )
            except LayoutError:
                if strict:
                    raise
                # A later global declaration can supply the shape before serialization.
                region.height, region._axis = 28, 14
            else:
                region.height = metrics.height + 12
                region._axis = metrics.above + 6
        context.declare(region.expression.to_xml())
    elif isinstance(region, TextRegion) and region._auto_height:
        text_size = size + {"Heading 1": 4, "Heading 2": 2}.get(region.style, 0)
        chars = max(1, int(region.width / (text_size * 0.65)))
        lines = sum(
            max(1, math.ceil(len(line.expandtabs(4)) / chars)) for line in region.text.split("\n")
        )
        region.height = lines * text_size * 1.8 + 8
    elif isinstance(region, XYPlot):
        # Reserve labels separately from the actual plot's requested drawing height.
        if region._auto_height:
            region.height = max(220, region.width * 0.65)
        label_height = max(measure(t.x.to_xml(), size).height for t in region.traces)
        region._flow_extra = label_height + size * 2 + 12
    elif region._auto_height:
        region.height = 8 if isinstance(region, PageBreak) else 28


@dataclass(frozen=True)
class PageSettings:
    paper_code: int = 9  # Windows DMPAPER_A4
    orientation: Orientation = Orientation.PORTRAIT
    margin_left: float = 36
    margin_right: float = 36
    margin_top: float = 36
    margin_bottom: float = 36

    def __post_init__(self):
        if not isinstance(self.orientation, Orientation):
            raise TypeError("orientation must be an Orientation")
        for value in (self.margin_left, self.margin_right, self.margin_top, self.margin_bottom):
            if not math.isfinite(value) or value < 0:
                raise ValueError("Page margins must be finite and nonnegative")


@dataclass
class Worksheet:
    title: str = ""
    regions: list[Region] = field(default_factory=list)
    author: str = ""
    origin: int = 0
    tolerance: float = 1e-3
    constraint_tolerance: float = 1e-3
    page: PageSettings = field(default_factory=PageSettings)
    result_format: ResultFormat = field(default_factory=ResultFormat)
    font_size: float = 10
    _cursor: float = field(default=0, init=False, repr=False)

    def __post_init__(self):
        initial, self.regions = self.regions, []
        if not isinstance(self.origin, int):
            raise TypeError("origin must be an integer")
        if not 0 <= self.tolerance <= 1 or not 0 <= self.constraint_tolerance <= 1:
            raise ValueError("Mathcad tolerances must be between 0 and 1")
        if not math.isfinite(self.font_size) or self.font_size <= 0:
            raise ValueError("font_size must be positive and finite")
        for region in initial:
            self.add(region)

    def layout(self, *, strict=True):
        context = ShapeContext(self.origin)
        for region in self.regions:
            if isinstance(region, MathRegion):
                xml = region.expression.to_xml()
                if xml.tag.endswith("}globalDefine"):
                    context.declare(xml)
        cursor = 12
        for region in self.regions:
            _place(region, context, self.font_size, cursor, self.result_format, strict)
            cursor = max(
                cursor, region.top + region.height + getattr(region, "_flow_extra", 0) + 12
            )
        self._cursor = cursor

    def add(self, region: Region) -> Region:
        if not isinstance(region, Region):
            raise TypeError("Worksheet accepts Region objects")
        region = copy(region)
        self.regions.append(region)
        try:
            self.layout(strict=False)
        except Exception:
            self.regions.pop()
            raise
        return region

    def math(self, expression: Expression, **layout) -> MathRegion:
        return self.add(MathRegion(expression, **layout))

    def text(self, text: str, **layout) -> TextRegion:
        return self.add(TextRegion(text, **layout))

    def define(self, lhs: ExpressionInput, rhs: ExpressionInput, **layout) -> MathRegion:
        from .expressions import Define

        return self.math(Define(lhs, rhs), **layout)

    def evaluate(
        self, expression: ExpressionInput, *, unit: ExpressionInput | None = None, **layout
    ) -> MathRegion:
        from .expressions import Evaluate

        return self.math(Evaluate(expression, unit=unit), **layout)

    def plot(self, *traces, **layout):
        from .plots import XYPlot

        return self.add(XYPlot(traces, **layout))

    def polar_plot(self, *traces, **layout):
        from .plots import PolarPlot

        return self.add(PolarPlot(traces, **layout))

    def _settings(self):
        settings = element("settings")
        presentation = element("presentation", settings)
        text_styles = element("textStyles", element("textRendering", presentation))
        for name, size, weight in (
            ("Normal", self.font_size, "normal"),
            ("Heading 1", self.font_size + 4, "bold"),
            ("Heading 2", self.font_size + 2, "bold"),
        ):
            style = element("textStyle", text_styles, name=name)
            element("blockAttr", style, text_align="left", margin_left="0", margin_right="0")
            element(
                "inlineAttr",
                style,
                font_family="Arial",
                font_size=size,
                font_weight=weight,
                font_style="normal",
                font_charset="0",
            )
        rendering = element("mathRendering", presentation, equation_color="#000000")
        element(
            "operators",
            rendering,
            multiplication="narrow-dot",
            derivative="derivative",
            literal_subscript="large",
            definition="colon-equal",
            global_definition="triple-equal",
            local_definition="left-arrow",
            equality="bold-equal",
            symbolic_evaluation="right-arrow",
        )
        math_styles = element("mathStyles", rendering)
        for name in (
            "Variables",
            "Constants",
            *(f"User {i}" for i in range(1, 8)),
            "Math Text Font",
        ):
            element(
                "mathStyle",
                math_styles,
                name=name,
                font_family="Times New Roman",
                font_size=self.font_size,
                font_weight="normal",
                font_style="normal",
                font_charset="0",
            )
        element("dimensionNames", rendering)
        element("symbolics", rendering)
        rendering.append(self.result_format.to_xml("results"))
        page = element(
            "pageModel",
            presentation,
            paper_code=self.page.paper_code,
            orientation=self.page.orientation,
        )
        element(
            "margins",
            page,
            left=self.page.margin_left,
            right=self.page.margin_right,
            top=self.page.margin_top,
            bottom=self.page.margin_bottom,
        )
        element(
            "colorModel",
            presentation,
            background_color="#ffffff",
            default_highlight_color="#ffff80",
        )
        element("language", presentation, math="en", UI="en")
        calculation = element("calculation", settings)
        element(
            "builtInVariables",
            calculation,
            array_origin=self.origin,
            convergence_tolerance=self.tolerance,
            constraint_tolerance=self.constraint_tolerance,
        )
        element(
            "calculationBehavior", calculation, automatic_recalculation="true", exact_boolean="true"
        )
        element("currentUnitSystem", element("units", calculation), name="si")
        editor = element("editor", settings)
        element("ruler", editor, ruler_unit="in")
        element("grid", editor, granularity_x="6", granularity_y="6")
        element(
            "fileFormat",
            settings,
            save_numeric_results="true",
            exclude_large_results="false",
            image_type="none",
            screen_dpi="96",
        )
        element("handbook", element("miscellaneous", settings))
        return settings

    def to_xml(self) -> ET._Element:
        self.layout()
        root = ET.Element(
            f"{{{WS}}}worksheet", version="3.0.3", nsmap={None: WS, "ws": WS, "ml": ML}
        )
        metadata = element("metadata", root)
        element("generator", metadata, text="xmcd Python library")
        user = element("userData", metadata)
        element("title", user, text=self.title)
        element("author", user, text=self.author)
        root.append(self._settings())
        regions = element("regions", root)
        context = SerializationContext()
        regions.extend(region.to_xml(context) for region in self.regions)
        if context.binaries:
            binaries = element("binaryContent", root)
            for index, data in enumerate(context.binaries, 1):
                element(
                    "item", binaries, text=base64.b64encode(data).decode("ascii"), item_id=index
                )
        return root

    def to_bytes(self) -> bytes:
        return ET.tostring(self.to_xml(), encoding="UTF-8", xml_declaration=True, pretty_print=True)

    @classmethod
    def read(cls, source: str | Path | bytes):
        """Load editable regions while preserving unsupported original XML."""
        from .reader import read_worksheet

        return read_worksheet(source)

    def check(self, *, context: ValidationContext | None = None) -> ValidationReport:
        """Collect static diagnostics without raising for semantic errors."""
        from .semantic import check_worksheet

        return check_worksheet(self, context=context)

    def _validated_bytes(self, context, warnings_as_errors, schema):
        from .validation import validate

        report = self.check(context=context)
        report.raise_for_errors(warnings_as_errors=warnings_as_errors)
        data = self.to_bytes()
        validate(data, schema=schema)
        return data, report

    def validate(
        self,
        *,
        context: ValidationContext | None = None,
        warnings_as_errors: bool = False,
        schema: str | Path | None = None,
    ) -> ValidationReport:
        """Raise on static errors, layout or XML errors; return remaining warnings."""
        return self._validated_bytes(context, warnings_as_errors, schema)[1]

    def write(
        self,
        path: str | Path,
        *,
        context: ValidationContext | None = None,
        warnings_as_errors: bool = False,
        schema: str | Path | None = None,
    ) -> Path:
        """Validate before opening the destination, preserving it on validation failure."""
        data, _ = self._validated_bytes(context, warnings_as_errors, schema)
        path = Path(path)
        path.write_bytes(data)
        return path
