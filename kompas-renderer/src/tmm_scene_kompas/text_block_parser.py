"""Strict Markdown-to-IR parser for one KOMPAS ``textBlock``.

``markdown-it-py`` is deliberately used only as a tokenizer.  Rendering and
layout are kept out of this module so malformed/unsupported input always fails
before a COM object is requested.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Iterable

from markdown_it import MarkdownIt
from mdit_py_plugins.dollarmath import dollarmath_plugin

from .kompas_text import parse_latex_string
from .text_block_ir import (
    BreakInline, CodeInline, DisplayMathBlock, HeadingBlock, Inline,
    InlineMath, ListItemBlock, MarkdownDocument, ParagraphBlock,
    SourcePosition, SourceSpan, StyledInline, TextInline,
)

STANDARD_TEXT_HEIGHTS = (1.8, 2.5, 3.5, 5.0, 7.0, 10.0, 14.0, 20.0, 28.0, 40.0)


class TextBlockCompileError(ValueError):
    """A deterministic, source-mapped error raised before COM work."""

    def __init__(self, entity_id: str, source_span: SourceSpan, code: str,
                 message: str, token_kind: str = "entity") -> None:
        self.entity_id = entity_id
        self.source_span = source_span
        self.code = code
        self.token_kind = token_kind
        super().__init__(f"textBlock {entity_id!r} {code} at "
                         f"{source_span.start.line}:{source_span.start.column}: {message}")


@dataclass(frozen=True)
class TextBlockEntity:
    entity_id: str
    text: str
    position: tuple[float, float]
    font_size: float
    width: float
    italic: bool = False


def _line_starts(source: str) -> list[int]:
    return [0] + [index + 1 for index, char in enumerate(source) if char == "\n"]


def _span(source: str, start: int, end: int) -> SourceSpan:
    starts = _line_starts(source)
    def position(offset: int) -> SourcePosition:
        line_index = 0
        for index, line_start in enumerate(starts):
            if line_start > offset:
                break
            line_index = index
        return SourcePosition(offset, line_index + 1, offset - starts[line_index] + 1)
    return SourceSpan(position(start), position(end))


def _line_offset(source: str, line: int) -> int:
    if line <= 0:
        return 0
    starts = _line_starts(source)
    return starts[min(line, len(starts) - 1)]


def _whole_span(source: str) -> SourceSpan:
    return _span(source, 0, len(source))


def validate_text_block_entity(entity: dict[str, Any]) -> TextBlockEntity:
    """Validate the v1 entity contract without initializing COM."""
    entity_id = entity.get("id")
    fallback_id = str(entity_id) if entity_id is not None else "<unknown>"
    span = _whole_span(str(entity.get("text", "")))
    for field in ("id", "text", "position", "fontSize", "width"):
        if field not in entity:
            raise TextBlockCompileError(fallback_id, span, "missing-required-field",
                                        f"missing required field {field!r}")
    if not isinstance(entity_id, str) or not entity_id:
        raise TextBlockCompileError(fallback_id, span, "invalid-text-block", "id must be a non-empty string")
    if not isinstance(entity["text"], str):
        raise TextBlockCompileError(entity_id, span, "invalid-text-block", "text must be a string")
    position = entity["position"]
    if not isinstance(position, (list, tuple)) or len(position) != 2:
        raise TextBlockCompileError(entity_id, span, "invalid-text-block", "position must contain two numbers")
    values = (*position, entity["fontSize"], entity["width"])
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in values):
        raise TextBlockCompileError(entity_id, span, "non-finite-value", "position, fontSize and width must be finite numbers")
    font_size = float(entity["fontSize"])
    width = float(entity["width"])
    if width <= 0:
        raise TextBlockCompileError(entity_id, span, "invalid-text-block", "width must be positive")
    if not any(math.isclose(font_size, allowed, abs_tol=1e-9) for allowed in STANDARD_TEXT_HEIGHTS):
        raise TextBlockCompileError(entity_id, span, "unsupported-font-size",
                                    f"fontSize {font_size:g} is not a standard text height")
    if not isinstance(entity.get("italic", False), bool):
        raise TextBlockCompileError(entity_id, span, "invalid-text-block", "italic must be boolean")
    return TextBlockEntity(entity_id, entity["text"], (float(position[0]), float(position[1])), font_size, width,
                           bool(entity.get("italic", False)))


def _first_unclosed_dollar(source: str) -> int | None:
    """Find an unescaped math delimiter outside CommonMark code spans.

    ``markdown-it`` correctly leaves unmatched delimiters as text, but the
    textBlock contract rejects them.  This small lexical check deliberately
    follows the relevant CommonMark rule for inline code: a backtick run is
    literal through the next run of the same length.  In particular, ``$`` in
    ````code $x$```` must never become a malformed-math diagnostic.
    """
    index = 0
    open_at: int | None = None
    while index < len(source):
        if source[index] == "\\":
            index += 2
            continue
        if source[index] == "`":
            run_end = index
            while run_end < len(source) and source[run_end] == "`":
                run_end += 1
            marker = source[index:run_end]
            close = source.find(marker, run_end)
            if close >= 0:
                index = close + len(marker)
                continue
            # An unmatched code delimiter is ordinary text under CommonMark.
            index = run_end
            continue
        if source[index] == "$":
            # Display delimiters are consumed as pairs here; markdown-it
            # handles their actual block placement.
            if source.startswith("$$", index):
                close = source.find("$$", index + 2)
                if close < 0:
                    return index
                index = close + 2
                continue
            if open_at is None:
                open_at = index
            else:
                open_at = None
        index += 1
    return open_at


def _tex_error_span(source: str, math_span: SourceSpan, tex: str,
                    exc: ValueError, tex_offset: int) -> SourceSpan:
    """Map the parser's strict byte offset to a one-character source span."""
    # Keep existing command diagnostics scoped to their math token.  Brace
    # errors are structural and need the stricter one-character location.
    if "group" not in str(exc):
        return math_span
    match = re.search(r"position (\d+)", str(exc))
    if match is None:
        return math_span
    position = min(int(match.group(1)), len(tex))
    offset = min(tex_offset + position, len(source))
    return _span(source, offset, min(offset + 1, len(source)))


def _raise_invalid_tex(entity_id: str, source: str, math_span: SourceSpan,
                       tex: str, tex_offset: int, exc: ValueError,
                       token_kind: str) -> None:
    raise TextBlockCompileError(
        entity_id,
        _tex_error_span(source, math_span, tex, exc, tex_offset),
        "invalid-tex",
        str(exc),
        token_kind,
    ) from exc


def _raise_unsupported(entity_id: str, source: str, offset: int, kind: str) -> None:
    raise TextBlockCompileError(entity_id, _span(source, offset, min(offset + 1, len(source))),
                                "unsupported-markdown-token", f"unsupported Markdown token {kind}", kind)


def _inline_nodes(entity_id: str, source: str, token, base_offset: int) -> tuple[Inline, ...]:
    children = token.children or ()
    result: list[Inline] = []
    styles: list[tuple[bool, bool, int]] = []
    cursor = base_offset

    def locate(value: str) -> int:
        nonlocal cursor
        found = source.find(value, cursor)
        if found < 0:
            found = cursor
        cursor = found + len(value)
        return found

    def append(node: Inline) -> None:
        if styles:
            bold = any(style[0] for style in styles)
            italic = any(style[1] for style in styles)
            result.append(StyledInline((node,), bold=bold, italic=italic, span=getattr(node, "span", None)))
        else:
            result.append(node)

    for child in children:
        kind = child.type
        if kind == "text":
            start = locate(child.content)
            append(TextInline(child.content, _span(source, start, start + len(child.content))))
        elif kind in ("softbreak", "hardbreak"):
            append(BreakInline(_span(source, cursor, cursor)))
        elif kind == "code_inline":
            marker = child.markup or "`"
            start = source.find(marker, cursor)
            start = cursor if start < 0 else start
            end = source.find(marker, start + len(marker))
            end = start + len(marker) + len(child.content) if end < 0 else end + len(marker)
            cursor = end
            append(CodeInline(child.content, _span(source, start, end)))
        elif kind == "math_inline":
            start = source.find("$", cursor)
            start = cursor if start < 0 else start
            end = start + len(child.content) + 2
            cursor = end
            math_span = _span(source, start, end)
            try:
                parse_latex_string(child.content)
            except ValueError as exc:
                _raise_invalid_tex(entity_id, source, math_span, child.content,
                                   start + 1, exc, "math_inline")
            append(InlineMath(child.content, math_span))
        elif kind in ("strong_open", "em_open"):
            styles.append((kind == "strong_open", kind == "em_open", cursor))
        elif kind in ("strong_close", "em_close"):
            if styles:
                styles.pop()
        elif kind == "link_open" or kind == "link_close":
            # URL is intentionally absent from the IR; its label children are emitted.
            continue
        elif kind == "image":
            _raise_unsupported(entity_id, source, cursor, "image")
        elif kind == "html_inline":
            _raise_unsupported(entity_id, source, cursor, "html")
        else:
            _raise_unsupported(entity_id, source, cursor, kind)
    return tuple(result)


def parse_text_block_markdown(entity: TextBlockEntity) -> MarkdownDocument:
    """Tokenize supported Markdown and return immutable source-mapped IR."""
    source = entity.text
    unclosed = _first_unclosed_dollar(source)
    if unclosed is not None:
        raise TextBlockCompileError(entity.entity_id, _span(source, unclosed, unclosed + 1),
                                    "malformed-math-delimiter", "unclosed '$' delimiter", "math_inline")
    raw_html = re.search(r"</?[A-Za-z][^>]*>", source)
    if raw_html:
        _raise_unsupported(entity.entity_id, source, raw_html.start(), "html")
    image = re.search(r"!\[[^\]]*\]\([^)]*\)", source)
    if image:
        _raise_unsupported(entity.entity_id, source, image.start(), "image")
    # CommonMark intentionally does not enable GFM tables. Reject the common
    # table spelling rather than silently laying it out as paragraph text.
    if re.search(r"(?m)^\s*\|.*\|\s*\n\s*\|?\s*:?-{3,}", source):
        _raise_unsupported(entity.entity_id, source, source.find("|"), "table")

    md = MarkdownIt("commonmark", {"breaks": True, "html": False, "linkify": False, "typographer": False})
    md.use(dollarmath_plugin)
    tokens = md.parse(source)
    blocks = []
    list_stack: list[tuple[bool, int, int]] = [] # ordered, next number, depth
    item_stack: list[tuple[bool, int | None, int, int]] = []
    for token_index, token in enumerate(tokens):
        kind = token.type
        if kind == "blockquote_open":
            _raise_unsupported(entity.entity_id, source, _line_offset(source, token.map[0]), "blockquote")
        if kind == "hr":
            _raise_unsupported(entity.entity_id, source, _line_offset(source, token.map[0]), "hr")
        if kind in {"fence", "code_block", "html_block"}:
            _raise_unsupported(entity.entity_id, source, _line_offset(source, token.map[0]), "html" if kind == "html_block" else kind)
        if kind == "bullet_list_open":
            list_stack.append((False, 0, len(list_stack)))
        elif kind == "ordered_list_open":
            start = int((token.attrs or {}).get("start", 1))
            list_stack.append((True, start, len(list_stack)))
        elif kind in {"bullet_list_close", "ordered_list_close"}:
            list_stack.pop()
        elif kind == "list_item_open":
            ordered, number, depth = list_stack[-1]
            item_stack.append((ordered, number if ordered else None, depth, _line_offset(source, token.map[0])))
            if ordered:
                list_stack[-1] = (ordered, number + 1, depth)
        elif kind == "list_item_close":
            item_stack.pop()
        elif kind == "math_block":
            offset = _line_offset(source, token.map[0])
            content_start = source.find(token.content.strip(), offset)
            content_start = offset if content_start < 0 else content_start
            math_span = _span(source, content_start, content_start + len(token.content.strip()))
            tex = token.content.strip()
            try:
                parse_latex_string(tex)
            except ValueError as exc:
                _raise_invalid_tex(entity.entity_id, source, math_span, tex,
                                   content_start, exc, "math_block")
            blocks.append(DisplayMathBlock(tex, math_span))
        elif kind == "inline":
            offset = _line_offset(source, token.map[0] if token.map else 0)
            content_start = source.find(token.content, offset)
            content_start = offset if content_start < 0 else content_start
            nodes = _inline_nodes(entity.entity_id, source, token, content_start)
            block_span = _span(source, content_start, content_start + len(token.content))
            previous = tokens[token_index - 1] if token_index else None
            if previous is not None and previous.type == "heading_open":
                blocks.append(HeadingBlock(int(previous.tag[1:]), nodes, block_span))
            elif item_stack:
                ordered, number, depth, start = item_stack[-1]
                blocks.append(ListItemBlock(nodes, ordered, number, depth, _span(source, start, block_span.end.offset)))
            else:
                blocks.append(ParagraphBlock(nodes, block_span))
    return MarkdownDocument(tuple(blocks), source)


def parse_text_block(entity: dict[str, Any]) -> tuple[TextBlockEntity, MarkdownDocument]:
    validated = validate_text_block_entity(entity)
    return validated, parse_text_block_markdown(validated)


__all__ = ["STANDARD_TEXT_HEIGHTS", "TextBlockCompileError", "TextBlockEntity", "validate_text_block_entity", "parse_text_block_markdown", "parse_text_block"]
