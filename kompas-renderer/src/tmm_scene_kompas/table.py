"""Validation and layout plan for the native ``table`` scene entity.

The plan is consumed by :func:`tmm_scene_kompas.render.add_table`, which creates
one editable KOMPAS ``IDrawingTable``/``ITable`` object. Column widths and row
heights become native cell formats, merged cells use ``ITableRange.CombineCells``,
and values are written through each cell's ``IText`` object. This module keeps
the JSON contract, validation, and deterministic table geometry independent
from the live COM operation.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any, Iterator, Sequence

from markdown_it import MarkdownIt
from mdit_py_plugins.dollarmath import dollarmath_plugin

from .kompas_text import Text, compile_kompas_control_string, parse_latex_string
from .text_block_ir import SourcePosition, SourceSpan


_TABLE_CELL_MARKDOWN = MarkdownIt(
    "commonmark",
    {"breaks": True, "html": True, "linkify": False, "typographer": False},
)
_TABLE_CELL_MARKDOWN.use(dollarmath_plugin)


class TableCellCompileError(ValueError):
    """A source-mapped strict table-cell inline diagnostic."""

    def __init__(
        self,
        entity_id: str,
        source_span: SourceSpan,
        code: str,
        message: str,
        token_kind: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.entity_id = entity_id
        self.source_span = source_span
        self.code = code
        self.token_kind = token_kind
        self.details = details
        super().__init__(
            f"table cell {entity_id!r} {code} at "
            f"{source_span.start.line}:{source_span.start.column}: {message}"
        )


def _cell_span(source: str, start: int, end: int) -> SourceSpan:
    start = max(0, min(len(source), start))
    end = max(start, min(len(source), end))
    line_start = source.rfind("\n", 0, start) + 1
    end_line_start = source.rfind("\n", 0, end) + 1
    return SourceSpan(
        SourcePosition(start, source.count("\n", 0, start) + 1, start - line_start + 1),
        SourcePosition(end, source.count("\n", 0, end) + 1, end - end_line_start + 1),
    )


def _cell_error(
    entity_id: str,
    source: str,
    start: int,
    end: int,
    code: str,
    token_kind: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> TableCellCompileError:
    return TableCellCompileError(
        entity_id, _cell_span(source, start, end), code, message, token_kind, details
    )


def _is_escaped(source: str, index: int) -> bool:
    slashes = 0
    index -= 1
    while index >= 0 and source[index] == "\\":
        slashes += 1
        index -= 1
    return slashes % 2 == 1


def _unescaped_index(source: str, value: str, start: int = 0) -> int:
    index = source.find(value, start)
    while index >= 0 and _is_escaped(source, index):
        index = source.find(value, index + 1)
    return index


def _display_end(source: str, start: int) -> int:
    close = _unescaped_index(source, "$$", start + 2)
    return close + 2 if close >= 0 else min(len(source), start + 2)


def _math_delimiter_issue(source: str) -> tuple[str, int, int, str] | None:
    """Return the first display/unclosed inline delimiter issue."""
    open_at = -1
    index = 0
    while index < len(source):
        if source[index] == "`":
            marker_end = index
            while marker_end < len(source) and source[marker_end] == "`":
                marker_end += 1
            marker = source[index:marker_end]
            close = source.find(marker, marker_end)
            if close >= 0:
                index = close + len(marker)
                continue
        if source[index] != "$" or _is_escaped(source, index):
            index += 1
            continue
        if source.startswith("$$", index) and not _is_escaped(source, index + 1):
            return "table-cell-display-math", index, _display_end(source, index), "math_display"
        open_at = index if open_at < 0 else -1
        index += 1
    if open_at >= 0:
        return "malformed-table-cell-math", open_at, open_at + 1, "math_inline"
    return None


def _consume_text(source: str, start: int, value: str) -> int:
    """Advance over Markdown text, accounting for escaped punctuation."""
    cursor = start
    for character in value:
        if cursor < len(source) and source[cursor] == character:
            cursor += 1
            continue
        if (
            cursor + 1 < len(source)
            and source[cursor] == "\\"
            and source[cursor + 1] == character
        ):
            cursor += 2
            continue
        found = source.find(character, cursor)
        if found < 0:
            return cursor
        cursor = found + 1
    return cursor


def _unsupported_cell_token_kind(token: Any) -> str:
    if token.type in {"em_open", "em_close"}:
        return "emphasis"
    if token.type in {"strong_open", "strong_close"}:
        return "strong"
    if token.type == "code_inline":
        return "code"
    if token.type in {"link_open", "link_close"}:
        return "link"
    if token.type == "image":
        return "image"
    if token.type == "html_inline":
        return "html"
    if token.type in {"softbreak", "hardbreak"}:
        return "line_break"
    return token.type


def _token_start(source: str, tokens: Sequence[Any], index: int) -> int:
    """Recover a source offset from markdown-it-py's inline token stream."""
    cursor = 0
    for prior in tokens[:index]:
        if prior.type == "math_inline":
            opening = _unescaped_index(source, "$", cursor)
            close = _unescaped_index(source, "$", opening + 1) if opening >= 0 else -1
            cursor = close + 1 if close >= 0 else cursor
        elif prior.type in {"softbreak", "hardbreak"}:
            found = source.find("\n", cursor)
            cursor = found + 1 if found >= 0 else cursor
        elif prior.markup:
            found = _unescaped_index(source, prior.markup, cursor)
            if found >= 0:
                cursor = found + len(prior.markup)
        elif prior.type == "text" and prior.content:
            cursor = _consume_text(source, cursor, prior.content)
    token = tokens[index]
    if token.type == "html_inline":
        marker = "<"
    elif token.type == "image":
        marker = "!["
    elif token.type == "link_open":
        marker = "![" if source[cursor:cursor + 2] == "![" else "["
    elif token.type in {"softbreak", "hardbreak"}:
        marker = "\n"
    else:
        marker = token.markup or ""
    if marker == "\n":
        found = source.find(marker, cursor)
    else:
        found = _unescaped_index(source, marker, cursor) if marker else -1
    return found if found >= 0 else max(0, min(len(source), cursor))


def _build_cell_runs(source: str, tokens: Sequence[Any]) -> tuple["TableCellInlineRun", ...]:
    """Build JS-corpus-compatible text/math runs and source spans."""
    runs: list[TableCellInlineRun] = []
    cursor = 0
    text_value: list[str] = []
    text_start: int | None = None

    def flush_text(end: int) -> None:
        nonlocal text_start, text_value
        if text_start is not None and (text_value or end > text_start):
            runs.append(TableCellInlineRun(
                "text", "".join(text_value), _cell_span(source, text_start, end)
            ))
        text_start = None
        text_value = []

    for token in tokens:
        if token.type == "text":
            if text_start is None:
                text_start = cursor
            text_value.append(token.content)
            cursor = _consume_text(source, cursor, token.content)
            continue
        if token.type != "math_inline":
            continue
        start = _unescaped_index(source, "$", cursor)
        if start < 0:
            start = cursor
        close = _unescaped_index(source, "$", start + 1)
        end = close + 1 if close >= 0 else min(len(source), start + 1)
        flush_text(start)
        runs.append(TableCellInlineRun(
            "math", token.content, _cell_span(source, start, end)
        ))
        cursor = end
    flush_text(len(source))
    return tuple(runs)


@dataclass(frozen=True)
class TableCellInlineRun:
    kind: str
    value: str
    source_span: SourceSpan


@dataclass(frozen=True)
class TableCellInlinePlan:
    source: str
    font_size: float
    italic: bool
    runs: tuple[TableCellInlineRun, ...]
    control_string: str


def compile_table_cell_inline_plan(
    text: str,
    font_size: float = 5.0,
    italic: bool = True,
    *,
    entity_id: str = "<table-cell>",
) -> TableCellInlinePlan:
    """Compile strict one-line Markdown + inline TeX for native ``IText``.

    Only plain Markdown text and one or more ``$...$`` inline math fragments
    are accepted.  The Markdown tokenizer and existing ``kompas_text`` AST
    lowering are shared with textBlock; the returned ``control_string`` is
    safe to assign to an existing cell ``IText.Str``.  No native text items
    are created here or by the production table writer.
    """
    if not isinstance(text, str):
        raise TypeError("table-cell text must be a string")
    if isinstance(font_size, bool) or not isinstance(font_size, (int, float)):
        raise TypeError("table-cell font_size must be a number")
    font_size = float(font_size)
    if not math.isfinite(font_size) or font_size <= 0:
        raise ValueError("table-cell font_size must be finite and greater than zero")
    if not isinstance(italic, bool):
        raise TypeError("table-cell italic must be boolean")
    newline = re.search(r"[\r\n]", text)
    if newline:
        raise _cell_error(
            entity_id, text, newline.start(), newline.end(),
            "unsupported-table-cell-markdown", "line_break",
            "Table-cell content must be a single line",
        )

    tokens = _TABLE_CELL_MARKDOWN.parseInline(text, {})[0].children or []
    for index, token in enumerate(tokens):
        if token.type in {"text", "math_inline"}:
            continue
        kind = _unsupported_cell_token_kind(token)
        start = _token_start(text, tokens, index)
        raise _cell_error(
            entity_id, text, start,
            min(len(text), start + max(1, len(token.markup or ""))),
            "unsupported-table-cell-markdown", kind,
            f"Markdown {kind} is not supported in a table cell",
        )

    issue = _math_delimiter_issue(text)
    if issue:
        code, start, end, kind = issue
        message = (
            "Display math is not supported in a table cell"
            if code == "table-cell-display-math"
            else "Inline math delimiter is malformed"
        )
        raise _cell_error(entity_id, text, start, end, code, kind, message)

    runs = _build_cell_runs(text, tokens)
    control_parts: list[str] = []
    for run in runs:
        try:
            node = Text(run.value) if run.kind == "text" else parse_latex_string(run.value)
            # Parse and lower with the existing AST path before COM is touched,
            # so unsupported primitives fail closed instead of becoming raw TeX.
            control_parts.append(compile_kompas_control_string(node))
        except ValueError as exc:
            if run.kind == "math":
                raise _cell_error(
                    entity_id, text, run.source_span.start.offset,
                    run.source_span.end.offset, "malformed-table-cell-math",
                    "math_inline", "Inline table-cell math is not valid TeX",
                    {"code": "invalid-tex", "message": str(exc)},
                ) from exc
            raise _cell_error(
                entity_id, text, run.source_span.start.offset,
                run.source_span.end.offset, "unsupported-table-cell-control",
                "text", "Plain table-cell text cannot be represented safely in KOMPAS control syntax",
                {"message": str(exc)},
            ) from exc
        except (TypeError, RuntimeError) as exc:
            raise _cell_error(
                entity_id, text, run.source_span.start.offset,
                run.source_span.end.offset, "unsupported-table-cell-control",
                run.kind, "Table-cell content has no supported KOMPAS control lowering",
                {"message": str(exc)},
            ) from exc

    return TableCellInlinePlan(
        source=text,
        font_size=font_size,
        italic=italic,
        runs=runs,
        control_string="".join(control_parts),
    )


class TableCompileError(ValueError):
    """Raised when one table entity does not satisfy the v2 table contract."""

    def __init__(self, entity_id: str, message: str) -> None:
        super().__init__(f"table {entity_id!r}: {message}")
        self.entity_id = entity_id


@dataclass(frozen=True)
class TableCell:
    row: int
    column: int
    row_span: int
    column_span: int
    text: str
    font_size: float
    italic: bool
    inline_plan: TableCellInlinePlan
    layer: str


@dataclass(frozen=True)
class TablePlan:
    entity_id: str
    position: tuple[float, float]
    column_widths: tuple[float, ...]
    row_heights: tuple[float, ...]
    cells: tuple[TableCell, ...]
    border_layer: str
    border_style: str
    grid_layer: str
    grid_style: str

    @property
    def width(self) -> float:
        return sum(self.column_widths)

    @property
    def height(self) -> float:
        return sum(self.row_heights)

    def column_x(self, column: int) -> float:
        return self.position[0] + sum(self.column_widths[:column])

    def row_top(self, row: int) -> float:
        return self.position[1] - sum(self.row_heights[:row])

    def cell_center(self, cell: TableCell) -> tuple[float, float]:
        left = self.column_x(cell.column)
        top = self.row_top(cell.row)
        width = sum(self.column_widths[cell.column:cell.column + cell.column_span])
        height = sum(self.row_heights[cell.row:cell.row + cell.row_span])
        return left + width / 2.0, top - height / 2.0

    def internal_vertical_segments(self) -> Iterator[tuple[float, float, float]]:
        """Yield x, y-low, y-high segments not hidden by a column span."""
        for boundary in range(1, len(self.column_widths)):
            x = self.column_x(boundary)
            for row in range(len(self.row_heights)):
                blocked = any(
                    cell.row <= row < cell.row + cell.row_span
                    and cell.column < boundary < cell.column + cell.column_span
                    for cell in self.cells
                )
                if not blocked:
                    yield x, self.row_top(row + 1), self.row_top(row)

    def internal_horizontal_segments(self) -> Iterator[tuple[float, float, float]]:
        """Yield y, x-left, x-right segments not hidden by a row span."""
        for boundary in range(1, len(self.row_heights)):
            y = self.row_top(boundary)
            for column in range(len(self.column_widths)):
                blocked = any(
                    cell.column <= column < cell.column + cell.column_span
                    and cell.row < boundary < cell.row + cell.row_span
                    for cell in self.cells
                )
                if not blocked:
                    yield y, self.column_x(column), self.column_x(column + 1)


def _entity_id(entity: Any) -> str:
    if not isinstance(entity, dict):
        raise TableCompileError("<unknown>", "entity must be an object")
    entity_id = entity.get("id", "<unknown>")
    if not isinstance(entity_id, str) or not entity_id:
        raise TableCompileError("<unknown>", "id must be a non-empty string")
    return entity_id


def _finite_number(value: Any, label: str, entity_id: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TableCompileError(entity_id, f"{label} must be a number")
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0.0):
        condition = "a finite number greater than zero" if positive else "finite"
        raise TableCompileError(entity_id, f"{label} must be {condition}")
    return result


def _positive_sizes(value: Any, label: str, entity_id: str) -> tuple[float, ...]:
    if not isinstance(value, list) or not value:
        raise TableCompileError(entity_id, f"{label} must be a non-empty array")
    return tuple(
        _finite_number(item, f"{label}[{index}]", entity_id, positive=True)
        for index, item in enumerate(value)
    )


def _index(value: Any, label: str, entity_id: str, *, default: int | None = None) -> int:
    if value is None and default is not None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TableCompileError(entity_id, f"{label} must be a non-negative integer")
    return value


def _string(value: Any, label: str, entity_id: str, *, default: str | None = None) -> str:
    if value is None and default is not None:
        return default
    if not isinstance(value, str):
        raise TableCompileError(entity_id, f"{label} must be a string")
    return value


def compile_table_plan(entity: dict[str, Any]) -> TablePlan:
    """Validate and lower one ``table`` entity into a deterministic plan.

    ``position`` is the y-up top-left corner.  Grid dimensions are explicit in
    millimetres.  A cell occupies an anchor row/column and may merge adjacent
    slots through ``rowSpan``/``colSpan``; unoccupied slots are intentionally
    blank.  The table border uses ``layer``/``style`` while inner grid lines
    use the optional ``gridLayer``/``gridStyle`` (thin solid by default).
    """
    entity_id = _entity_id(entity)
    if entity.get("type") != "table":
        raise TableCompileError(entity_id, "type must be 'table'")
    position = entity.get("position")
    if not isinstance(position, (list, tuple)) or len(position) != 2:
        raise TableCompileError(entity_id, "position must be a [x, y] point")
    point = (
        _finite_number(position[0], "position[0]", entity_id),
        _finite_number(position[1], "position[1]", entity_id),
    )
    column_widths = _positive_sizes(entity.get("columnWidths"), "columnWidths", entity_id)
    row_heights = _positive_sizes(entity.get("rowHeights"), "rowHeights", entity_id)
    default_font_size = _finite_number(entity.get("fontSize", 5.0), "fontSize", entity_id, positive=True)
    default_italic = entity.get("italic", False)
    if not isinstance(default_italic, bool):
        raise TableCompileError(entity_id, "italic must be boolean")

    border_layer = _string(entity.get("layer"), "layer", entity_id, default="fixed")
    border_style = _string(entity.get("style"), "style", entity_id, default="solid")
    grid_layer = _string(entity.get("gridLayer"), "gridLayer", entity_id, default="thin")
    grid_style = _string(entity.get("gridStyle"), "gridStyle", entity_id, default="solid")

    cells_value = entity.get("cells")
    if not isinstance(cells_value, list):
        raise TableCompileError(entity_id, "cells must be an array")

    occupied: set[tuple[int, int]] = set()
    cells: list[TableCell] = []
    for index, value in enumerate(cells_value):
        label = f"cells[{index}]"
        if not isinstance(value, dict):
            raise TableCompileError(entity_id, f"{label} must be an object")
        row = _index(value.get("row"), f"{label}.row", entity_id)
        column = _index(value.get("column"), f"{label}.column", entity_id)
        row_span = _index(value.get("rowSpan"), f"{label}.rowSpan", entity_id, default=1)
        column_span = _index(value.get("colSpan"), f"{label}.colSpan", entity_id, default=1)
        if row_span == 0 or column_span == 0:
            raise TableCompileError(entity_id, f"{label} spans must be greater than zero")
        if row + row_span > len(row_heights) or column + column_span > len(column_widths):
            raise TableCompileError(entity_id, f"{label} span exceeds the table bounds")
        text = _string(value.get("text"), f"{label}.text", entity_id)
        font_size = _finite_number(value.get("fontSize", default_font_size), f"{label}.fontSize", entity_id, positive=True)
        italic = value.get("italic", default_italic)
        if not isinstance(italic, bool):
            raise TableCompileError(entity_id, f"{label}.italic must be boolean")
        if "latex" in value:
            raise TableCompileError(
                entity_id,
                f"{label}.latex is a removed legacy field; use {label}.text with inline $...$",
            )
        try:
            inline_plan = compile_table_cell_inline_plan(
                text, font_size, italic, entity_id=f"{entity_id}.{label}"
            )
        except TableCellCompileError as exc:
            raise TableCompileError(entity_id, str(exc)) from exc
        text_layer = _string(value.get("layer"), f"{label}.layer", entity_id, default="label")

        footprint = {
            (r, c)
            for r in range(row, row + row_span)
            for c in range(column, column + column_span)
        }
        if occupied.intersection(footprint):
            raise TableCompileError(entity_id, f"{label} overlaps another cell")
        occupied.update(footprint)
        cells.append(TableCell(
            row=row, column=column, row_span=row_span, column_span=column_span,
            text=text, font_size=font_size, italic=italic,
            inline_plan=inline_plan, layer=text_layer,
        ))

    return TablePlan(
        entity_id=entity_id, position=point, column_widths=column_widths,
        row_heights=row_heights, cells=tuple(cells), border_layer=border_layer,
        border_style=border_style, grid_layer=grid_layer, grid_style=grid_style,
    )


def table_requires_api5(_plan: TablePlan) -> bool:
    """Native DrawingTables own their cell text and never need API5 binding."""
    return False


__all__ = [
    "TableCell", "TableCellCompileError", "TableCellInlinePlan",
    "TableCellInlineRun", "TableCompileError", "TablePlan",
    "compile_table_cell_inline_plan", "compile_table_plan", "table_requires_api5",
]
