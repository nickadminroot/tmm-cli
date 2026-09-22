"""Immutable, source-mapped intermediate representation for ``textBlock``."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple, Union


@dataclass(frozen=True)
class SourcePosition:
    offset: int
    line: int
    column: int


@dataclass(frozen=True)
class SourceSpan:
    start: SourcePosition
    end: SourcePosition


@dataclass(frozen=True)
class TextInline:
    value: str
    span: SourceSpan


@dataclass(frozen=True)
class InlineMath:
    source: str
    span: SourceSpan


@dataclass(frozen=True)
class CodeInline:
    value: str
    span: SourceSpan


@dataclass(frozen=True)
class BreakInline:
    span: SourceSpan


@dataclass(frozen=True)
class StyledInline:
    children: Tuple['Inline', ...]
    bold: bool = False
    italic: bool = False
    span: SourceSpan | None = None


Inline = Union[TextInline, InlineMath, CodeInline, BreakInline, StyledInline]


@dataclass(frozen=True)
class HeadingBlock:
    level: int
    children: Tuple[Inline, ...]
    span: SourceSpan


@dataclass(frozen=True)
class ParagraphBlock:
    children: Tuple[Inline, ...]
    span: SourceSpan


@dataclass(frozen=True)
class ListItemBlock:
    children: Tuple[Inline, ...]
    ordered: bool
    number: int | None
    depth: int
    span: SourceSpan


@dataclass(frozen=True)
class DisplayMathBlock:
    source: str
    span: SourceSpan


Block = Union[HeadingBlock, ParagraphBlock, ListItemBlock, DisplayMathBlock]


@dataclass(frozen=True)
class MarkdownDocument:
    blocks: Tuple[Block, ...]
    source: str


__all__ = [name for name in globals() if name.endswith(('Position', 'Span', 'Inline', 'Block', 'Document')) or name in {'Inline', 'Block'}]
