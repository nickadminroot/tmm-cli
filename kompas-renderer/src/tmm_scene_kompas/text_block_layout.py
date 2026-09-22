"""Deterministic COM-free layout for the immutable textBlock IR."""
from __future__ import annotations

from dataclasses import dataclass, replace
import re
from typing import Iterable, Sequence
import unicodedata

from .kompas_text import (
    TextItemPlan, TextLinePlan, TextRenderPlan, compile_latex_api5_exact,
    compile_unicode_text, estimate_plan_size,
)
from .text_block_ir import (
    BreakInline, CodeInline, DisplayMathBlock, HeadingBlock, InlineMath,
    ListItemBlock, MarkdownDocument, ParagraphBlock, StyledInline, TextInline,
)
from .text_block_parser import STANDARD_TEXT_HEIGHTS, TextBlockEntity


@dataclass(frozen=True)
class FormulaOverflowSegment:
    """One safe display-math segment that exceeds the requested width."""

    tex: str
    width: float


@dataclass(frozen=True)
class TextBlockLayoutWarning:
    code: str
    message: str
    min_formula_width: float | None = None
    overflow_segments: tuple[FormulaOverflowSegment, ...] = ()


@dataclass(frozen=True)
class TextBlockLayout:
    plan: TextRenderPlan
    width: float
    height: float
    min_width: float
    min_formula_width: float | None
    overflow: bool
    warnings: tuple[TextBlockLayoutWarning, ...]


def next_standard_height(height: float) -> float:
    """Return exactly one configured text-height step above ``height``."""
    index = STANDARD_TEXT_HEIGHTS.index(float(height))
    return STANDARD_TEXT_HEIGHTS[min(index + 1, len(STANDARD_TEXT_HEIGHTS) - 1)]


def _styled(plan: TextRenderPlan, height: float, bold: bool, italic: bool,
            source_span=None) -> list[TextItemPlan]:
    return [replace(
        item,
        height=item.height or height,
        bold=bold,
        italic=(item.italic_override
                if item.italic_override is not None
                else italic),
        source_span=source_span,
    ) for line in plan.lines for item in line.items]


def _measure(items: Sequence[TextItemPlan], height: float) -> float:
    return estimate_plan_size(TextRenderPlan([TextLinePlan(list(items), height=height)], height))[0]


def _is_punctuation(value: str) -> bool:
    """Whether ``value`` consists only of Unicode punctuation (and spaces)."""
    value = value.strip()
    return bool(value) and all(unicodedata.category(char).startswith("P") for char in value)


def _inline_atoms(nodes, height: float, base_italic: bool, bold: bool = False,
                  italic: bool = False) -> list[tuple[list[TextItemPlan] | None, bool]]:
    """Return ``(items, forced_break)`` atoms; math/code cannot be divided."""
    atoms: list[tuple[list[TextItemPlan] | None, bool, bool]] = []

    def append_nodes(children, current_bold: bool, current_italic: bool) -> None:
        for node in children:
            if isinstance(node, StyledInline):
                append_nodes(node.children, current_bold or node.bold,
                             current_italic or node.italic)
            elif isinstance(node, BreakInline):
                atoms.append((None, True, False))
            elif isinstance(node, InlineMath):
                atoms.append((_styled(compile_latex_api5_exact(node.source, height), height,
                                      current_bold, base_italic or current_italic, node.span), False, False))
            elif isinstance(node, CodeInline):
                # Code is literal: do not recursively tokenize $...$ or Markdown.
                atoms.append((_styled(compile_unicode_text(node.value, height), height,
                                      current_bold, base_italic or current_italic, node.span), False, True))
            elif isinstance(node, TextInline):
                # Greedy word wrapping only splits at whitespace; spaces remain
                # attached to their preceding word for deterministic snapshots.
                for word in re.findall(r"\S+\s*|\s+", node.value):
                    atoms.append((_styled(compile_unicode_text(word, height), height,
                                          current_bold, base_italic or current_italic, node.span),
                                  False, not word.isspace()))
            else:  # pragma: no cover - IR union exhaustiveness guard
                raise TypeError(f"Unsupported inline IR node {type(node)!r}")

    append_nodes(nodes, bold, italic)
    joined: list[tuple[list[TextItemPlan] | None, bool]] = []
    pending_prefix_punctuation: list[TextItemPlan] = []
    for items, forced_break, is_word in atoms:
        is_punctuation = (items is not None and is_word
                          and _is_punctuation("".join(item.content for item in items)))
        # Markdown may place punctuation in a separate inline node around a
        # styled word, e.g. ``**word**.`` or ``«**word**``. Keep it in the
        # adjacent word's wrap atom while retaining its own formatted
        # TextItemPlan for API5 lowering.
        if is_punctuation:
            previous_items = joined[-1][0] if joined else None
            previous_content = "".join(item.content for item in previous_items or ())
            if previous_items is not None and (not previous_content or not previous_content[-1].isspace()):
                previous_items, _previous_break = joined[-1]
                joined[-1] = ([*previous_items, *items], False)
            else:
                pending_prefix_punctuation.extend(items)
            continue
        if pending_prefix_punctuation:
            if items is not None:
                items = [*pending_prefix_punctuation, *items]
                pending_prefix_punctuation = []
            else:
                joined.append((pending_prefix_punctuation, False))
                pending_prefix_punctuation = []
        joined.append((items, forced_break))
    if pending_prefix_punctuation:
        joined.append((pending_prefix_punctuation, False))
    return joined


def _safe_breaks(tex: str) -> list[int]:
    """Offsets at contract-safe top-level display-math break points.

    Binary operators are retained at the end of the preceding segment and
    duplicated at the beginning of the continuation segment. ``\\allowbreak``
    is removed and therefore breaks after its command. The scanner deliberately tracks brace groups, escaped delimiters, and
    ``\\left``/``\\right`` pairs.  A raw ``+`` inside any of those structures is
    never a legal visual break, even when it looks top-level textually.
    """
    result: list[int] = []
    brace_depth = delimiter_depth = left_right_depth = 0
    index = 0
    while index < len(tex):
        char = tex[index]
        if char == "\\":
            command_start = index
            index += 1
            command_end = index
            while command_end < len(tex) and tex[command_end].isalpha():
                command_end += 1
            if command_end == index:
                escaped = tex[index] if index < len(tex) else ""
                if escaped in "{([":
                    delimiter_depth += 1
                elif escaped in "})]" and delimiter_depth:
                    delimiter_depth -= 1
                index += 1
                continue
            command = tex[index:command_end]
            at_top_level = not (brace_depth or delimiter_depth or left_right_depth)
            if command == "allowbreak" and at_top_level:
                result.append(command_end)
            elif command == "left":
                left_right_depth += 1
            elif command == "right" and left_right_depth:
                left_right_depth -= 1
            index = command_end
            continue
        if char == "{":
            brace_depth += 1
        elif char == "}":
            brace_depth = max(brace_depth - 1, 0)
        elif char in "([":
            delimiter_depth += 1
        elif char in ")]" and delimiter_depth:
            delimiter_depth -= 1
        elif not (brace_depth or delimiter_depth or left_right_depth):
            if char == "=":
                # Operators lead the continuation line, matching SVG/JS.
                result.append(index)
            elif char in "+-":
                # Unary signs are not binary split points.
                before = tex[:index].rstrip()
                if before and before[-1] not in "=+-*/(^{":
                    result.append(index)
        index += 1
    return result


def _split_display_math_details(
    tex: str, width: float, height: float,
) -> tuple[list[str], float, bool, tuple[FormulaOverflowSegment, ...]]:
    """Return the canonical split and explicit overflow evidence.

    Operators are duplicated at the boundary: they remain at the end of the
    preceding segment and begin the continuation segment. If no all-fitting
    path exists, every legal safe cut is retained so a single
    oversized atom is reported without swallowing its fitting neighbours.
    """
    points = _safe_breaks(tex)
    # Do not create an empty segment when an explicit ``\\allowbreak`` is
    # immediately followed by an operator. The explicit break already places
    # that operator at the start of the next segment.
    effective_points: list[int] = []
    segment_start = 0
    for point in points:
        if tex[segment_start:point].strip():
            effective_points.append(point)
            segment_start = point
    points = effective_points
    cuts = [0, *points, len(tex)]
    cuts = [cut for index, cut in enumerate(cuts) if not index or cut != cuts[index - 1]]

    def piece(start: int, end: int) -> str:
        # Operator breakpoints overlap by one source character so the
        # operator is visible at both ends of the rendered boundary.
        end_exclusive = end
        if end < len(tex) and tex[end] in "=+-":
            end_exclusive += 1
        return tex[start:end_exclusive].replace("\\allowbreak", "").strip()

    def measure(value: str) -> float:
        return _measure(_styled(compile_latex_api5_exact(value, height), height, False, False), height)

    cleaned = piece(0, len(tex))
    whole_width = measure(cleaned)
    atomic = [(piece(start, end), measure(piece(start, end)))
              for start, end in zip(cuts, cuts[1:])]
    min_width = max((item_width for _item, item_width in atomic), default=whole_width)
    best: list[tuple[int, float, list[str]] | None] = [None] * len(cuts)
    best[0] = (0, 0.0, [])
    for end in range(1, len(cuts)):
        for start in range(end):
            previous = best[start]
            if previous is None:
                continue
            value = piece(cuts[start], cuts[end])
            value_width = measure(value)
            if value_width > width:
                continue
            candidate = (previous[0] + 1, previous[1] + (width - value_width) ** 2,
                         [*previous[2], value])
            current = best[end]
            if current is None or candidate[:2] < current[:2]:
                best[end] = candidate
    selected = best[-1]
    if selected is not None:
        return selected[2], min_width, False, ()

    pieces = [item for item, _item_width in atomic]
    oversized = tuple(
        FormulaOverflowSegment(item, item_width)
        for item, item_width in atomic if item_width > width
    )
    # An all-fitting path could not exist only because at least one atomic
    # segment is oversized. Keep that invariant explicit rather than allowing
    # a bare global formula-overflow flag to hide the offending run.
    assert oversized
    return pieces, min_width, True, oversized


def split_display_math(tex: str, width: float, height: float) -> tuple[list[str], float, bool]:
    """Select safe display-math breaks by minimum lines then raggedness."""
    pieces, min_width, overflow, _oversized = _split_display_math_details(tex, width, height)
    return pieces, min_width, overflow


def _wrap(atoms: Iterable[tuple[list[TextItemPlan] | None, bool]], width: float,
          height: float) -> tuple[list[list[TextItemPlan]], bool]:
    lines: list[list[TextItemPlan]] = [[]]
    overflow = False
    for items, forced_break in atoms:
        if forced_break:
            lines.append([])
            continue
        assert items is not None
        current = lines[-1]
        if current and _measure([*current, *items], height) > width:
            lines.append(list(items))
        else:
            current.extend(items)
        if _measure(lines[-1], height) > width:
            overflow = True
    return lines, overflow


def layout_text_block(entity: TextBlockEntity, document: MarkdownDocument) -> TextBlockLayout:
    """Create the one final API5 plan; no COM interaction occurs here."""
    lines: list[TextLinePlan] = []
    warnings: list[TextBlockLayoutWarning] = []
    min_width = 0.0
    min_formula_width: float | None = None
    overflow = False
    for block in document.blocks:
        if isinstance(block, DisplayMathBlock):
            pieces, formula_width, formula_overflow, oversized_segments = _split_display_math_details(
                block.source, entity.width, entity.font_size,
            )
            min_width = max(min_width, formula_width)
            min_formula_width = max(min_formula_width or 0.0, formula_width)
            if formula_overflow:
                warnings.append(TextBlockLayoutWarning(
                    "formula-overflow",
                    "display formula contains oversized safe segment(s)",
                    formula_width,
                    oversized_segments,
                ))
                overflow = True
            for piece in pieces:
                lines.append(TextLinePlan(_styled(compile_latex_api5_exact(piece, entity.font_size), entity.font_size,
                                                  False, entity.italic, block.span), height=entity.font_size))
            continue
        if isinstance(block, HeadingBlock):
            height = next_standard_height(entity.font_size)
            atoms = _inline_atoms(block.children, height, entity.italic)
        elif isinstance(block, ListItemBlock):
            height = entity.font_size
            prefix = f"{block.number}. " if block.ordered else "- "
            indent = "  " * block.depth
            atoms = _inline_atoms((TextInline(indent + prefix, block.span), *block.children), height, entity.italic)
        elif isinstance(block, ParagraphBlock):
            height = entity.font_size
            atoms = _inline_atoms(block.children, height, entity.italic)
        else:  # pragma: no cover
            raise TypeError(f"Unsupported block IR node {type(block)!r}")
        wrapped, did_overflow = _wrap(atoms, entity.width, height)
        if did_overflow:
            warnings.append(TextBlockLayoutWarning("text-overflow", "an indivisible inline atom exceeds requested width"))
        overflow = overflow or did_overflow
        for item_line in wrapped:
            min_width = max(min_width, _measure(item_line, height))
            lines.append(TextLinePlan(item_line, height=height))
    if not lines:
        lines = [TextLinePlan([], height=entity.font_size)]
    for line in lines[:-1]:
        line.break_after = True
    plan = TextRenderPlan(lines, height=entity.font_size)
    actual_width, actual_height = estimate_plan_size(plan)
    return TextBlockLayout(plan, actual_width, actual_height, min_width, min_formula_width,
                           overflow, tuple(warnings))


def compile_text_block_plan(entity_dict: dict) -> TextBlockLayout:
    """Convenience pre-COM compilation entry point used by the renderer."""
    from .text_block_parser import parse_text_block
    entity, document = parse_text_block(entity_dict)
    return layout_text_block(entity, document)


__all__ = ["FormulaOverflowSegment", "TextBlockLayoutWarning", "TextBlockLayout", "next_standard_height", "split_display_math", "layout_text_block", "compile_text_block_plan"]
