"""Stable semantic and layout snapshots for the textBlock conformance corpus."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .text_block_ir import (
    BreakInline, CodeInline, DisplayMathBlock, HeadingBlock, InlineMath,
    ListItemBlock, ParagraphBlock, StyledInline, TextInline,
)
from .text_block_layout import _safe_breaks, _split_display_math_details, layout_text_block
from .text_block_parser import TextBlockCompileError, parse_text_block


def _span(span) -> dict[str, int] | None:
    if span is None:
        return None
    return {"start": span.start.offset, "end": span.end.offset}


def _inline(node) -> dict[str, Any]:
    result: dict[str, Any] = {"span": _span(node.span)}
    if isinstance(node, TextInline):
        return {"type": "text", "value": node.value, **result}
    if isinstance(node, InlineMath):
        return {"type": "inlineMath", "source": node.source, **result}
    if isinstance(node, CodeInline):
        return {"type": "code", "value": node.value, **result}
    if isinstance(node, BreakInline):
        return {"type": "break", **result}
    if isinstance(node, StyledInline):
        return {
            "type": "styled", "bold": node.bold, "italic": node.italic,
            "children": [_inline(child) for child in node.children], **result,
        }
    raise TypeError(type(node))


def semantic_ir_snapshot(document) -> list[dict[str, Any]]:
    """Serialize every semantic node and its source span without COM state."""
    blocks = []
    for block in document.blocks:
        if isinstance(block, DisplayMathBlock):
            blocks.append({"type": "displayMath", "source": block.source,
                           "span": _span(block.span)})
        elif isinstance(block, HeadingBlock):
            blocks.append({"type": "heading", "level": block.level,
                           "children": [_inline(node) for node in block.children],
                           "span": _span(block.span)})
        elif isinstance(block, ParagraphBlock):
            blocks.append({"type": "paragraph",
                           "children": [_inline(node) for node in block.children],
                           "span": _span(block.span)})
        elif isinstance(block, ListItemBlock):
            blocks.append({"type": "listItem", "ordered": block.ordered,
                           "number": block.number, "depth": block.depth,
                           "children": [_inline(node) for node in block.children],
                           "span": _span(block.span)})
        else:  # pragma: no cover - IR exhaustiveness guard
            raise TypeError(type(block))
    return blocks


def _visual_lines_snapshot(layout) -> list[dict[str, Any]]:
    return [
        {
            "height": line.height,
            "breakAfter": line.break_after,
            "runs": [
                {
                    "font": item.font.name,
                    "content": item.content,
                    "kind": item.kind,
                    "height": item.height,
                    "bold": item.bold,
                    "italic": item.italic,
                    "underline": item.underline,
                    "sourceSpan": _span(item.source_span),
                }
                for item in line.items
            ],
        }
        for line in layout.plan.lines
    ]


def _formula_splits_snapshot(document, entity) -> list[dict[str, Any]]:
    splits = []
    for block in document.blocks:
        if not isinstance(block, DisplayMathBlock):
            continue
        pieces, min_width, overflow, oversized = _split_display_math_details(
            block.source, entity.width, entity.font_size,
        )
        splits.append({
            "sourceSpan": _span(block.span),
            "safeBreakOffsets": _safe_breaks(block.source),
            "pieces": pieces,
            "minFormulaWidth": min_width,
            "overflow": overflow,
            "overflowSegments": [asdict(segment) for segment in oversized],
        })
    return splits


def conformance_snapshot(entity: dict[str, Any]) -> dict[str, Any]:
    """Compile an entity into a JSON-compatible canonical conformance record."""
    try:
        validated, document = parse_text_block(entity)
        layout = layout_text_block(validated, document)
    except TextBlockCompileError as exc:
        return {
            "outcome": "error",
            "error": {
                "code": exc.code,
                "tokenKind": exc.token_kind,
                "sourceSpan": _span(exc.source_span),
            },
        }
    return {
        "outcome": "success",
        "semanticIr": semantic_ir_snapshot(document),
        "visualLines": _visual_lines_snapshot(layout),
        "formulaSplits": _formula_splits_snapshot(document, validated),
        "overflow": {
            "value": layout.overflow,
            "minWidth": layout.min_width,
            "minFormulaWidth": layout.min_formula_width,
            "warnings": [
                {
                    "code": warning.code,
                    "minFormulaWidth": warning.min_formula_width,
                    "overflowSegments": [asdict(segment) for segment in warning.overflow_segments],
                }
                for warning in layout.warnings
            ],
        },
    }


__all__ = ["conformance_snapshot", "semantic_ir_snapshot"]
