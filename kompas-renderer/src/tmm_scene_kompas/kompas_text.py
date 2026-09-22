"""COM‑free AST for mathematical LaTeX‑style text used in KOMPAS drawings.

Provides a parser and data model that convert a small subset of LaTeX
into an abstract syntax tree (AST).  The AST nodes are plain dataclasses
with no COM, clipboard, or XML dependencies.
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass, replace
from typing import Optional


# ─── AST Node types ──────────────────────────────────────────────────────────


@dataclass
class Node:
    """Base class for all AST nodes."""
    pass


@dataclass
class Text(Node):
    """A run of plain text."""
    value: str


@dataclass
class Sequence(Node):
    """An ordered sequence of child nodes."""
    parts: list[Node]


@dataclass
class Fraction(Node):
    """A fraction with numerator and denominator."""
    numerator: Node
    denominator: Node


@dataclass
class Decorated(Node):
    """A decorated node (overline or underline)."""
    kind: str  # "overline" or "underline"
    body: Node


@dataclass
class Radical(Node):
    """A square-root radical rendered by the API5 user-symbol 98."""
    body: Node


@dataclass
class StyledNode(Node):
    """A local TeX style override such as upright ``\\mathrm`` text."""
    body: Node
    italic: bool | None = None


@dataclass
class UnderOver(Node):
    """A base with optional above and below content."""
    base: Node
    above: Optional[Node] = None
    below: Optional[Node] = None


@dataclass
class Script(Node):
    """A base with optional superscript and subscript."""
    base: Node
    superscript: Optional[Node] = None
    subscript: Optional[Node] = None


# ─── LaTeX command map ──────────────────────────────────────────────────────


LATEX_COMMANDS: dict[str, str] = {
    ",": "",
    ";": " ",
    "!": "",
    ":": " ",
    "prime": "′",
    "circ": "°",
    "ldots": "…",
    "cdots": "⋯",
    "dots": "…",
    "alpha": "α",
    "beta": "β",
    "gamma": "γ",
    "delta": "δ",
    "epsilon": "ε",
    "varepsilon": "ε",
    "zeta": "ζ",
    "eta": "η",
    "theta": "θ",
    "vartheta": "ϑ",
    "iota": "ι",
    "kappa": "κ",
    "lambda": "λ",
    "mu": "μ",
    "nu": "ν",
    "xi": "ξ",
    "pi": "π",
    "varpi": "ϖ",
    "rho": "ρ",
    "varrho": "ϱ",
    "sigma": "σ",
    "varsigma": "ς",
    "tau": "τ",
    "upsilon": "υ",
    "phi": "φ",
    "varphi": "ϕ",
    "chi": "χ",
    "psi": "ψ",
    "omega": "ω",
    "Gamma": "Γ",
    "Delta": "Δ",
    "Theta": "Θ",
    "Lambda": "Λ",
    "Xi": "Ξ",
    "Pi": "Π",
    "Sigma": "Σ",
    "Upsilon": "Υ",
    "Phi": "Φ",
    "Psi": "Ψ",
    "Omega": "Ω",
    "cdot": "·",
    "times": "×",
    "triangle": "△",
    "sim": "∼",
    "pm": "±",
    "mp": "∓",
    "leq": "≤",
    "geq": "≥",
    "neq": "≠",
    "approx": "≈",
    "to": "->",
    "rightarrow": "->",
    "leftarrow": "←",
    "leftrightarrow": "↔",
    "degree": "°",
    "parallel": "||",
    "quad": " ",
    "qquad": "  ",
    "sum": "∑",
    "int": "∫",
    "angle": "∠",
    "Rightarrow": "=>",
    "GostPhi": "Φ",
    "GostVarphi": "φ",
    "GostMu": "μ",
    "GostOmega": "ω",
    "GostEpsilon": "ε",
    "GostSum": "∑",
    "GostAngle": "∠",
    "GostCdot": "·",
    "GostDeg": "°",
    "GostPrime": "′",
    "GostRightarrow": "=>",
}

# Commands that are handled specially in parse_command (not via LATEX_COMMANDS).
_SPECIAL_COMMANDS = frozenset(
    {
        "left",
        "right",
        "perp",
        "GostPerp",
        "frac",
        "dfrac",
        "sqrt",
        "allowbreak",
        "overline",
        "widehat",
        "bar",
        "vec",
        "vct",
        "V",
        "underline",
        "underbar",
        "uvec",
        "DirV",
        "duvec",
        "KnownV",
        "qvec",
        "UnknownV",
        "supsp",
        "Sup",
        "underset",
        "overset",
        "text",
        "mathrm",
        "operatorname",
        " ",
    }
)

PRIME_CHARS: frozenset[str] = frozenset({"′", "'"})

_KNOWN_COMMANDS: frozenset[str] = frozenset(
    list(LATEX_COMMANDS.keys()) + list(_SPECIAL_COMMANDS)
)


# ─── LatexParser ────────────────────────────────────────────────────────────


class LatexParser:
    """Recursive‑descent parser for the LaTeX subset.

    Creates an AST using the node types defined above.  Raises
    ``ValueError`` on unknown commands and unclosed groups, with
    the source position included in the message.
    """

    def __init__(self, source: str) -> None:
        self.source = source
        self.pos = 0

    def parse(self) -> Node:
        """Parse the entire source string and return the root node."""
        result = self.parse_sequence(stop_chars="")
        self.skip_space()
        if self.pos != len(self.source):
            raise ValueError(
                f"Unexpected trailing input at position {self.pos}"
            )
        return result

    def parse_sequence(self, stop_chars: str) -> Node:
        """Parse a sequence of atoms until a stop character or EOF."""
        parts: list[Node] = []
        while self.pos < len(self.source):
            ch = self.source[self.pos]
            if stop_chars and ch in stop_chars:
                break
            parts.append(self.parse_atom())
        return self.compact(parts)

    def parse_atom(self) -> Node:
        """Parse an atom (primary with optional subscript/superscript)."""
        base = self.parse_primary()
        superscript: Optional[Node] = None
        subscript: Optional[Node] = None
        while self.pos < len(self.source):
            ch = self.source[self.pos]
            if ch == "^":
                self.pos += 1
                superscript = self.parse_script_arg()
                continue
            if ch == "_":
                self.pos += 1
                subscript = self.parse_script_arg()
                continue
            break
        if superscript is None and subscript is None:
            return base
        return Script(base=base, superscript=superscript, subscript=subscript)

    def parse_primary(self) -> Node:
        """Parse a primary expression: group, command, or single character."""
        if self.pos >= len(self.source):
            return Text("")

        ch = self.source[self.pos]
        if ch == "}":
            raise ValueError(f"Unexpected closing group at position {self.pos}")

        if ch == "{":
            group_start = self.pos
            self.pos += 1
            node = self.parse_sequence(stop_chars="}")
            if self.pos >= len(self.source) or self.source[self.pos] != "}":
                raise ValueError(
                    f"Unclosed group starting at position {group_start}"
                )
            self.pos += 1
            return node

        if ch == "\\":
            return self.parse_command()

        self.pos += 1
        if ch == "⊥":
            return Text(ch)
        return Text(ch)

    def parse_command(self) -> Node:
        """Parse a backslash command."""
        self.pos += 1  # consume backslash
        if self.pos >= len(self.source):
            return Text("\\")

        ch = self.source[self.pos]
        if not ch.isalpha():
            self.pos += 1
            if ch in "[]":
                return Text("")
            return Text(LATEX_COMMANDS.get(ch, ch))

        # Read alphabetic command name
        start = self.pos
        while self.pos < len(self.source) and self.source[self.pos].isalpha():
            self.pos += 1
        name = self.source[start:self.pos]

        if name not in _KNOWN_COMMANDS:
            raise ValueError(
                f"Unknown command '\\{name}' at position {start - 1}"
            )

        # --- Special commands ---

        if name in ("left", "right", "allowbreak"):
            return Text("")

        if name in ("perp", "GostPerp"):
            return Text("⊥")

        if name in ("frac", "dfrac"):
            numerator = self.parse_required_group()
            denominator = self.parse_required_group()
            return Fraction(numerator=numerator, denominator=denominator)

        if name == "sqrt":
            return Radical(self.parse_required_group())

        if name == "vec":
            # In TeX math mode, \\vec is a math accent and accepts either
            # a braced group or the next single atom (for example,
            # ``\\vec F_{42}`` and ``\\vec \\Phi_{5}``).
            return Decorated(
                kind="overline",
                body=self.parse_decoration_argument(allow_bare=True),
            )

        if name in ("overline", "widehat", "bar", "vct", "V"):
            # KOMPAS API5 exposes an editable overline special (95), but no
            # corresponding hat accent.  Keep widehat as the nearest editable
            # decorated representation; the shared metrics contract treats
            # both as the same conservative decorated formula class.
            return Decorated(
                kind="overline", body=self.parse_decoration_argument(allow_bare=True)
            )

        if name in ("underline", "underbar"):
            return Decorated(
                kind="underline", body=self.parse_decoration_argument(allow_bare=True)
            )

        if name in ("uvec", "DirV"):
            body = self.parse_required_group()
            below = self.parse_required_group()
            return UnderOver(
                base=Decorated(
                    kind="underline",
                    body=Decorated(kind="overline", body=body),
                ),
                below=below,
            )

        if name in ("duvec", "KnownV"):
            body = self.parse_required_group()
            below = self.parse_required_group()
            return UnderOver(
                base=Decorated(
                    kind="underline",
                    body=Decorated(
                        kind="underline",
                        body=Decorated(kind="overline", body=body),
                    ),
                ),
                below=below,
            )

        if name in ("qvec", "UnknownV"):
            return UnderOver(
                base=Decorated(
                    kind="overline", body=self.parse_required_group()
                ),
                below=Text("??"),
            )

        if name in ("supsp", "Sup"):
            return Script(
                base=Text(""), superscript=self.parse_required_group()
            )

        if name == "underset":
            below = self.parse_required_group()
            base = self.parse_required_group()
            return UnderOver(base=base, below=below)

        if name == "overset":
            above = self.parse_required_group()
            base = self.parse_required_group()
            return UnderOver(base=base, above=above)

        if name == "mathrm":
            # KOMPAS does not expose a reliable local upright modifier inside
            # an API5 script control string. Treat ``\mathrm`` as transparent
            # rather than claiming to preserve its typography.
            return self.parse_decoration_argument(allow_bare=True)

        if name == "text":
            # ``\text`` is prose embedded in a formula, not an upright style
            # request. Let the textBlock entity's inherited italic flag apply.
            return StyledNode(
                self.parse_decoration_argument(allow_bare=True), italic=None,
            )

        if name == "operatorname":
            return StyledNode(
                self.parse_decoration_argument(allow_bare=True), italic=False,
            )

        if name == " ":
            return Text(" ")

        # Named LaTeX command from the mapping
        return Text(LATEX_COMMANDS[name])

    def parse_required_group(self) -> Node:
        """Parse a required group ``{...}``, raising on missing ``{``."""
        self.skip_space()
        if self.pos >= len(self.source) or self.source[self.pos] != "{":
            raise ValueError(
                f"Expected '{{' at position {self.pos}"
            )
        return self.parse_primary()

    def parse_decoration_argument(self, allow_bare: bool = False) -> Node:
        """Parse a decoration argument.

        ``\\vec`` follows TeX math-accent syntax and may decorate either a
        braced group or the next single atom. Other decorations retain their
        stricter braced-group syntax.
        """
        self.skip_space()
        if self.pos < len(self.source) and self.source[self.pos] == "{":
            return self.parse_primary()
        if allow_bare and self.pos < len(self.source):
            return self.parse_primary()
        raise ValueError(f"Expected '{{' at position {self.pos}")

    def parse_script_arg(self) -> Node:
        """Parse a subscript/superscript argument (single char or group)."""
        self.skip_space()
        if self.pos >= len(self.source):
            return Text("")
        return self.parse_primary()

    def skip_space(self) -> None:
        """Skip whitespace characters."""
        while (
            self.pos < len(self.source)
            and self.source[self.pos] in " \r\n\t"
        ):
            self.pos += 1

    # ─── Helper: compact / merge ────────────────────────────────────────

    @staticmethod
    def compact(parts: list[Node]) -> Node:
        """Merge adjacent text nodes and attach floating scripts."""
        compacted: list[Node] = []
        text_buffer: list[str] = []

        def flush_text() -> None:
            if text_buffer:
                compacted.append(Text("".join(text_buffer)))
                text_buffer.clear()

        for part in parts:
            if isinstance(part, Text):
                text_buffer.append(part.value)
            elif (
                    floating_script := LatexParser.floating_script(part)
            ) is not None:
                flush_text()
                if compacted:
                    sup, sub = floating_script
                    compacted[-1] = Script(
                        base=compacted[-1],
                        superscript=sup,
                        subscript=sub,
                    )
                else:
                    compacted.append(part)
            elif isinstance(part, Sequence):
                flush_text()
                compacted.extend(part.parts)
            else:
                flush_text()
                compacted.append(part)

        flush_text()

        if not compacted:
            return Text("")
        if len(compacted) == 1:
            return compacted[0]
        return Sequence(compacted)

    @staticmethod
    def floating_script(
        node: Node,
    ) -> Optional[tuple[Optional[Node], Optional[Node]]]:
        """Detect a floating script (base ``Text("")``).

        Returns ``(superscript, subscript)`` or ``None``.
        """
        if not isinstance(node, Script):
            return None
        if isinstance(node.base, Text) and node.base.value == "":
            return node.superscript, node.subscript
        inner = node.base
        if (
            isinstance(inner, Script)
            and isinstance(inner.base, Text)
            and inner.base.value == ""
            and node.superscript is None
        ):
            return inner.superscript, node.subscript
        return None


# ─── FontRole ──────────────────────────────────────────────────────────────


class FontRole(enum.Enum):
    """Font role for a text item: GOST type A or Symbol (for Greek).

    Both fonts use ``type=0`` in the KOMPAS API but refer to different
    typefaces.  The enum values are internal discriminators only.
    """
    GOST_TYPE_A = 0
    SYMBOL = 1


# ─── Text rendering plan types ───────────────────────────────────────────────


@dataclass
class TextItemPlan:
    """A single formatted text item in a KOMPAS text line.

    *item_type* is the KOMPAS text-item kind (resolved in the adapter for
    script-base items, where ``const.SUM_TYPE`` is used).
    ``0`` plain/script, ``1`` fraction numerator, ``2`` fraction denominator,
    ``3`` fraction end.

    *kind* carries the semantic role: ``"plain"``, ``"script_base"``,
    ``"script_upper"``, ``"script_lower"``, ``"script_end"``,
    ``"fraction_num"``, ``"fraction_den"``, ``"fraction_end"``.

    The adapter resolves *kind* to the correct KOMPAS type, *bit_vector*
    (on the font) and *i_s_numb* (on the item).
    """
    item_type: int
    font: FontRole
    content: str
    bit_vector: int = 0
    i_s_numb: int = 0
    kind: str = "plain"
    # textBlock uses item-specific standard heights and local Markdown styles.
    # Existing text compilation leaves these as ``None``/False, preserving the
    # established API5 lowering byte-for-byte for ordinary text entities.
    height: Optional[float] = None
    bold: bool = False
    italic: bool = False
    # TeX local style override, applied after the entity-level text style.
    italic_override: bool | None = None
    underline: bool = False
    source_span: object | None = None


@dataclass
class TextLinePlan:
    """A single line of formatted text items.

    ``break_after`` emits the API5 ``@/`` paragraph marker.  The capability
    probe established that line arrays alone are flattened by KOMPAS.
    """
    items: list[TextItemPlan]
    height: Optional[float] = None
    break_after: bool = False


@dataclass
class TextRenderPlan:
    """Full rendering plan for one or more lines of formatted text."""
    lines: list[TextLinePlan]
    height: float = 5.0


_TEXT_HEIGHT_STEPS = (1.8, 2.5, 3.5, 5.0, 7.0, 10.0, 14.0, 20.0, 28.0, 40.0)


def _previous_text_height(height: float) -> float:
    """Return the preceding GOST height step for structural annotations."""
    value = float(height)
    for candidate in reversed(_TEXT_HEIGHT_STEPS):
        if candidate < value - 1e-9:
            return candidate
    return value


# ─── Symbol font mapping ─────────────────────────────────────────────────────

# Unicode Greek → KOMPAS Symbol type A slot.
# This is intentionally kept in sync with the paperclip converter's
# GOST_OUTPUT_TRANSLATION table: the value is the ASCII codepoint placed in
# a Symbol type A run, not a second semantic Greek character.
_GREEK_TO_SYMBOL: dict[str, str] = {
    # Uppercase Greek
    '\u0391': 'A',   # Α Alpha
    '\u0392': 'B',   # Β Beta
    '\u0393': 'G',   # Γ Gamma
    '\u0394': 'D',   # Δ Delta
    '\u0395': 'E',   # Ε Epsilon
    '\u0396': 'Z',   # Ζ Zeta
    '\u0397': 'H',   # Η Eta
    '\u0398': 'Q',   # Θ Theta
    '\u0399': 'I',   # Ι Iota
    '\u039A': 'K',   # Κ Kappa
    '\u039B': 'L',   # Λ Lambda
    '\u039C': 'M',   # Μ Mu
    '\u039D': 'N',   # Ν Nu
    '\u039E': 'X',   # Ξ Xi
    '\u039F': 'O',   # Ο Omicron
    '\u03A0': 'P',   # Π Pi
    '\u03A1': 'R',   # Ρ Rho
    '\u03A3': 'S',   # Σ Sigma
    '\u03A4': 'T',   # Τ Tau
    '\u03A5': 'U',   # Υ Upsilon
    '\u03A6': 'F',   # Φ Phi
    '\u03A7': 'C',   # Χ Chi
    '\u03A8': 'Y',   # Ψ Psi
    '\u03A9': 'W',   # Ω Omega
    # Variant uppercase
    '\u03D1': 'J',   # ϑ Theta symbol
    # Lowercase Greek
    '\u03B1': 'a',   # α alpha
    '\u03B2': 'b',   # β beta
    '\u03B3': 'g',   # γ gamma
    '\u03B4': 'd',   # δ delta
    '\u03B5': 'e',   # ε epsilon
    '\u03B6': 'z',   # ζ zeta
    '\u03B7': 'h',   # η eta
    '\u03B8': 'q',   # θ theta
    '\u03B9': 'i',   # ι iota
    '\u03BA': 'k',   # κ kappa
    '\u03BB': 'l',   # λ lambda
    '\u03BC': 'm',   # μ mu
    '\u03BD': 'n',   # ν nu
    '\u03BE': 'x',   # ξ xi
    '\u03BF': 'o',   # ο omicron
    '\u03C0': 'p',   # π pi
    '\u03C1': 'r',   # ρ rho
    '\u03C2': 'V',   # ς final sigma (Compass paperclip mapping)
    '\u03C3': 's',   # σ sigma
    '\u03C4': 't',   # τ tau
    '\u03C5': 'u',   # υ upsilon
    '\u03C6': 'f',   # φ phi
    '\u03C7': 'c',   # χ chi
    '\u03C8': 'y',   # ψ psi
    '\u03C9': 'w',   # ω omega
    # Variant lowercase
    '\u03D5': 'f',   # ϕ phi symbol (same paperclip slot as φ)
    '\u03D6': 'v',   # ϖ pi symbol
    '\u03F0': 'k',   # ϰ kappa symbol
    '\u03F1': 'R',   # ϱ rho symbol (Compass paperclip mapping)
    '\u03F5': 'e',   # ϵ lunate epsilon
    # Compass paperclip GOST_OUTPUT_TRANSLATION mappings.
    '∑': 'S',
    '∠': '\u00ee',
    '→': '->',
    '⇒': '=>',
    # Unicode equivalent of the LaTeX ``\\parallel`` command.
    '∥': '||',
}

_GREEK_CHARS: frozenset[str] = frozenset(_GREEK_TO_SYMBOL.keys())
_GOST_MAPPED_MATH: frozenset[str] = frozenset({'∑', '∠', '→', '⇒', '∥'})
_SYMBOL_MAPPED_MATH: frozenset[str] = frozenset({'∑', '∠'})

# KOMPAS does not support Unicode dash glyphs in editable text.  Keep the
# source text unchanged for parsing, but lower them to the ASCII hyphen-minus
# at every rendering boundary.
_KOMPAS_TEXT_REPLACEMENTS: dict[str, str] = {
    '\u2013': '-',  # – EN DASH
    '\u2014': '-',  # — EM DASH
}


def normalize_kompas_text(text: str) -> str:
    """Replace Unicode characters that KOMPAS cannot render reliably."""
    return text.translate(str.maketrans(_KOMPAS_TEXT_REPLACEMENTS))


def normalize_math_whitespace(source: str) -> str:
    """Turn control whitespace inside a TeX expression into ordinary spaces.

    Markdown paragraph breaks are handled before this boundary by the text
    block parser. This helper applies only to formula source and prevents its
    internal CR/LF/tab characters from reaching API5 text items.
    """
    return re.sub(r"[\r\n\t]+", " ", source)


# Unicode superscript codepoints → regular ASCII.
_UNICODE_SUP_TO_REG: dict[str, str] = {
    '\u00B2': '2',   # ²
    '\u00B3': '3',   # ³
    '\u00B9': '1',   # ¹
    '\u2070': '0',   # ⁰
    '\u2071': 'i',   # ⁱ
    '\u2074': '4',   # ⁴
    '\u2075': '5',   # ⁵
    '\u2076': '6',   # ⁶
    '\u2077': '7',   # ⁷
    '\u2078': '8',   # ⁸
    '\u2079': '9',   # ⁹
    '\u207A': '+',   # ⁺
    '\u207B': '-',   # ⁻
    '\u207C': '=',   # ⁼
    '\u207D': '(',   # ⁽
    '\u207E': ')',   # ⁾
    '\u207F': 'n',   # ⁿ
}

_UNICODE_SUP_CHARS: frozenset[str] = frozenset(_UNICODE_SUP_TO_REG.keys())

# Unicode subscript codepoints → regular ASCII.
_UNICODE_SUB_TO_REG: dict[str, str] = {
    '\u2080': '0',   # ₀
    '\u2081': '1',   # ₁
    '\u2082': '2',   # ₂
    '\u2083': '3',   # ₃
    '\u2084': '4',   # ₄
    '\u2085': '5',   # ₅
    '\u2086': '6',   # ₆
    '\u2087': '7',   # ₇
    '\u2088': '8',   # ₈
    '\u2089': '9',   # ₉
    '\u208A': '+',   # ₊
    '\u208B': '-',   # ₋
    '\u208C': '=',   # ₌
    '\u208D': '(',   # ₍
    '\u208E': ')',   # ₎
}

# Subscript Latin letters U+2090–U+209C
for _cp in range(0x2090, 0x209D):
    _ch = chr(_cp)
    _regular_map: dict[str, str] = {
        '\u2090': 'a',   # ₐ
        '\u2091': 'e',   # ₑ
        '\u2092': 'o',   # ₒ
        '\u2093': 'x',   # ₓ
        '\u2094': '\u0259',  # ₔ schwa — not a regular ASCII char, skip
    }
    if _ch in _regular_map:
        _UNICODE_SUB_TO_REG[_ch] = _regular_map[_ch]

# Also add subscript h, k, l, m, n, p, s, t (U+2095–U+209C)
for _cp in range(0x2095, 0x209D):
    # h k l m n p s t at these positions
    _idx = _cp - 0x2095
    _letters = ('h', 'k', 'l', 'm', 'n', 'p', 's', 't')
    if _idx < len(_letters):
        _UNICODE_SUB_TO_REG[chr(_cp)] = _letters[_idx]

del _cp, _ch, _regular_map, _idx, _letters

_UNICODE_SUB_CHARS: frozenset[str] = frozenset(_UNICODE_SUB_TO_REG.keys())

# Mathematical Unicode characters which are not reliably present in the
# GOST type A font.  Emit these through KOMPAS' Symbol type A escape.
_MATH_SYMBOL_CHARS: frozenset[str] = frozenset(
    "∀∂∃∅∇∑∏√∞∝∠∧∨∩∪⊂⊃⊆⊇∈∉∋≡≈≠≤≥±∓×÷·⋅−→←↔⇒⇔⊥∥′″ℏℓℝℕℤℚℂ△∼"
)


def contains_math_unicode(text: str) -> bool:
    """Whether *text* needs the API5 rich-text path.

    Ordinary Unicode labels (including Cyrillic) remain on the API7 path.
    """
    return any(
        ch in _GREEK_CHARS or ch in _UNICODE_SUP_CHARS
        or ch in _UNICODE_SUB_CHARS or ch == "\u00b0"
        or ch in _MATH_SYMBOL_CHARS
        for ch in text
    )


# ─── High‑level parsing functions ──────────────────────────────────────────


def parse_latex_string(source: str) -> Node:
    """Parse a single LaTeX string into an AST node.

    This is a convenience wrapper that calls ``LatexParser(source).parse()``.
    """
    return LatexParser(source).parse()


def parse_latex_document(source: str) -> list[Node]:
    """Parse a multi‑line LaTeX document into a list of AST nodes.

    Lines are separated by ``\\\\`` (double backslash).
    The document is normalised before parsing: display math markers
    (``$$``, ``\\[``, ``\\]``, ``$``) are removed.
    """
    source = normalize_latex_source(source)
    lines = [line.strip() for line in split_latex_lines(source)]
    nodes = [LatexParser(line).parse() for line in lines if line]
    return nodes or [Text("")]


def normalize_latex_source(source: str) -> str:
    """Normalize a LaTeX source string for KOMPAS consumption."""
    source = normalize_kompas_text(source).strip()
    source = re.sub(r"\\\]\s*\\\[", lambda _: "\\\\", source)
    source = re.sub(r"\$\$\s*\$\$", lambda _: "\\\\", source)
    source = source.replace("\\[", " ").replace("\\]", " ")
    source = source.replace("$$", " ").replace("$", " ")
    return " ".join(source.split())


def split_latex_lines(source: str) -> list[str]:
    """Split source into lines at ``\\\\`` (double backslash)."""
    lines: list[str] = []
    current: list[str] = []
    i = 0
    while i < len(source):
        if source.startswith("\\\\", i):
            lines.append("".join(current))
            current.clear()
            i += 2
            continue
        current.append(source[i])
        i += 1
    lines.append("".join(current))
    return lines


# ─── Plain text helpers ─────────────────────────────────────────────────────


def plain_text(node: Node) -> str:
    """Convert an AST node to a plain text representation."""
    if isinstance(node, Text):
        return node.value
    if isinstance(node, Sequence):
        return "".join(plain_text(part) for part in node.parts)
    if isinstance(node, Fraction):
        return f"{plain_text(node.numerator)}/{plain_text(node.denominator)}"
    if isinstance(node, Decorated):
        return plain_text(node.body)
    if isinstance(node, Radical):
        return "√" + plain_text(node.body)
    if isinstance(node, StyledNode):
        return plain_text(node.body)
    if isinstance(node, UnderOver):
        pieces = [plain_text(node.base)]
        if node.above is not None:
            pieces.append("^(" + plain_text(node.above) + ")")
        if node.below is not None:
            pieces.append("_(" + plain_text(node.below) + ")")
        return "".join(pieces)
    if isinstance(node, Script):
        pieces = [plain_text(node.base)]
        prime_count = count_primes(node.superscript)
        if prime_count:
            pieces.append("'" * prime_count)
        elif node.superscript is not None:
            pieces.append("^(" + plain_text(node.superscript) + ")")
        if node.subscript is not None:
            pieces.append("_(" + plain_text(node.subscript) + ")")
        return "".join(pieces)
    raise TypeError(f"Unsupported node type: {type(node)!r}")


def count_primes(node: Optional[Node]) -> int:
    """Count consecutive prime characters in a node."""
    if node is None:
        return 0
    text = plain_node_text(node)
    if text and all(ch in PRIME_CHARS for ch in text):
        return len(text)
    return 0


def plain_node_text(node: Node) -> str:
    """Extract plain text from a node (ignores non‑text structure)."""
    if isinstance(node, Text):
        return node.value
    if isinstance(node, Sequence):
        return "".join(plain_node_text(part) for part in node.parts)
    if isinstance(node, Decorated):
        return plain_node_text(node.body)
    if isinstance(node, Radical):
        return plain_node_text(node.body)
    if isinstance(node, StyledNode):
        return plain_node_text(node.body)
    return ""


# ─── Compile: Unicode text → TextRenderPlan ─────────────────────────────────


def compile_unicode_text(text: str, height: float = 5.0) -> TextRenderPlan:
    """Compile plain Unicode text (no LaTeX markup) to a KOMPAS render plan.

    Greek letters are mapped to Symbol font ASCII slots;
    Unicode superscript/subscript codepoints become structural Script items
    (type8/type9); the degree symbol ``°`` compiles to the API5 special
    sequence ``&01``.

    Raises ``ValueError`` for unsupported codepoints.
    """
    items: list[TextItemPlan] = _compile_plain_text(text)
    lines = [TextLinePlan(items=items)] if items else [TextLinePlan(items=[])]
    return TextRenderPlan(lines=lines, height=height)


def compile_latex(
    source: str | Node, height: float = 5.0
) -> TextRenderPlan:
    """Parse LaTeX (or accept an AST node) and compile to a KOMPAS render plan.

    Parameters
    ----------
    source : str | Node
        A LaTeX string or an already-parsed AST ``Node``.
    height : float
        Font height in mm (default 5.0).
    """
    if isinstance(source, str):
        node = parse_latex_string(source)
    else:
        node = source
    items = _compile_node(node)
    lines = [TextLinePlan(items=items)] if items else [TextLinePlan(items=[])]
    return TextRenderPlan(lines=lines, height=height)


def compile_kompas_control_string(source: str | Node) -> str:
    """Lower one parsed expression to KOMPAS ``IText.Str`` control syntax.

    This is the string-valued counterpart of the existing API5 item plan.  It
    deliberately shares the same parser and recursive lowering primitives;
    table cells assign the result to an existing native ``IText`` instead of
    constructing ``ITextLine``/``ITextItem`` objects.  The returned dollar
    pairs are KOMPAS control delimiters (for example ``l$;1$``), not raw
    Markdown/LaTeX delimiters.
    """
    if isinstance(source, str):
        source = normalize_kompas_text(source)
        node = parse_latex_string(source)
    else:
        node = source
    return _compile_control_node(node)


def compile_latex_api5_exact(
    source: str | Node, height: float = 5.0
) -> TextRenderPlan:
    """Compile LaTeX for the exact one-DrawingText API5 representation.

    Superscript/subscript uses KOMPAS control syntax (``$up;down$``), while
    centered above/below text uses the API5 S_BASE/S_UPPER/S_LOWER bit-vector
    sequence.  Both stay inside one ``ksTextEx`` DrawingText.
    """
    if isinstance(source, str):
        # Display-math source may retain Markdown's internal line breaks.
        # Normalize them only after block parsing, so visible paragraph breaks
        # outside math remain real text-block line breaks.
        source = normalize_math_whitespace(source)
        # A Unicode-only expression can use the structural script compiler;
        # keeping this branch before parsing prevents ²/₃ from becoming
        # unsupported literal glyphs in a GOST text run.
        if (contains_math_unicode(source)
                and not any(ch in source for ch in r"\\{}^_")):
            return compile_unicode_text(source, height=height)
        node = parse_latex_string(source)
    else:
        node = source

    def plain_item(content: str) -> TextItemPlan:
        return TextItemPlan(item_type=0, kind="plain",
                            font=FontRole.GOST_TYPE_A, content=content)

    def compile_items(current: Node) -> list[TextItemPlan]:
        """Lower every top-level AST part without nesting control domains.

        KOMPAS control strings use ``$...$`` both for scripts and fractions.
        Flattening a complete Sequence into one string therefore makes a
        denominator such as ``l_{BC}`` terminate ``$d...;...$`` early and can
        leave all following text in the lower-index state.  Structural
        fractions and under/over groups must remain separate item sequences,
        even when they occur in the middle of a formula.
        """
        if isinstance(current, Text):
            return _compile_plain_text(current.value)
        if isinstance(current, Sequence):
            result: list[TextItemPlan] = []
            for part in current.parts:
                result.extend(compile_items(part))
            return result
        if isinstance(current, Script):
            # Keep the balanced control string for scripts. KOMPAS expands it
            # into its native sub/superscript modifier items; splitting the
            # control string across TextItemParam values breaks that state.
            return [plain_item(_compile_control_node(current))]

        if isinstance(current, StyledNode):
            return [replace(item, italic_override=current.italic)
                    for item in compile_items(current.body)]

        if isinstance(current, Radical):
            return [TextItemPlan(
                0, FontRole.GOST_TYPE_A, _compile_control_node(current.body),
                kind="special", i_s_numb=98,
            ), TextItemPlan(
                0, FontRole.GOST_TYPE_A, "", kind="special_end",
            )]

        if isinstance(current, UnderOver):
            result = [TextItemPlan(
                0, FontRole.GOST_TYPE_A,
                _compile_control_node(current.base), kind="updn_base",
            )]
            annotation_height = _previous_text_height(height)
            if current.above is not None:
                result.append(TextItemPlan(
                    0, FontRole.GOST_TYPE_A,
                    _compile_control_node(current.above), kind="updn_upper",
                    height=annotation_height,
                ))
            if current.below is not None:
                result.append(TextItemPlan(
                    0, FontRole.GOST_TYPE_A,
                    _compile_control_node(current.below), kind="updn_lower",
                    height=annotation_height,
                ))
            result.append(TextItemPlan(
                0, FontRole.GOST_TYPE_A, "", kind="updn_end",
            ))
            return result
        if isinstance(current, Fraction):
            return [
                TextItemPlan(
                    0, FontRole.GOST_TYPE_A,
                    _compile_control_node(current.numerator),
                    kind="fraction_num",
                ),
                TextItemPlan(
                    0, FontRole.GOST_TYPE_A,
                    _compile_control_node(current.denominator),
                    kind="fraction_den",
                ),
                TextItemPlan(
                    0, FontRole.GOST_TYPE_A, "", kind="fraction_end",
                ),
            ]
        if isinstance(current, Decorated):
            return _compile_node(current).copy()
        raise TypeError(f"Unsupported exact API5 node: {type(current)!r}")

    return TextRenderPlan([TextLinePlan(compile_items(node))], height)


def _visible_control_text(content: str) -> str:
    """Reduce KOMPAS control syntax to visible glyphs for sizing.

    Control strings can be much longer than the text they render. Counting
    their raw length moves centred API5 text far to the left, especially for
    ``\\Phi``/``\\vec`` because of embedded Symbol-font and overline escapes.
    """
    visible = str(content)
    visible = visible.replace("&01", "X")
    visible = re.sub(r"\^\([^)]*\)\+\d+~", "X", visible)
    visible = re.sub(r"@\+\d+~", "", visible)
    visible = visible.replace("$d", "")
    visible = re.sub(r"[$;()]", "", visible)
    return visible


def estimate_plan_size(
    plan: TextRenderPlan, char_width_factor: float = 0.7
) -> tuple[float, float]:
    """Estimate rendered width and height of a render plan.

    Returns ``(width_mm, height_mm)``.
    """
    total_width = 0.0
    total_height = 0.0
    for line in plan.lines:
        line_height = line.height or plan.height
        line_width = 0.0
        for item in line.items:
            visible = _visible_control_text(item.content)
            item_height = item.height or line_height
            line_height = max(line_height, item_height)
            line_width += max(len(visible), 1) * item_height * char_width_factor
        total_width = max(total_width, line_width)
        total_height += line_height * 1.4  # calibrated conservative leading
    return total_width, total_height or plan.height * 1.4


# ─── Internal compilation helpers ────────────────────────────────────────────


def _compile_node(node: Node) -> list[TextItemPlan]:
    """Recursively compile an AST node to a list of text items."""
    if isinstance(node, Text):
        return _compile_plain_text(node.value)
    if isinstance(node, Sequence):
        items: list[TextItemPlan] = []
        for part in node.parts:
            items.extend(_compile_node(part))
        return items
    if isinstance(node, Script):
        items: list[TextItemPlan] = []
        base_items = _compile_node(node.base)
        # Mark the last base item as script_base
        if base_items:
            last = base_items[-1]
            base_items[-1] = TextItemPlan(
                item_type=0,
                kind="script_base",
                font=last.font,
                content=last.content,
            )
        items.extend(base_items)
        if node.superscript is not None:
            items.extend(
                _compile_script_content(node.superscript, kind="script_upper")
            )
        if node.subscript is not None:
            items.extend(
                _compile_script_content(node.subscript, kind="script_lower")
            )
        # Empty terminator after scripts
        if node.superscript is not None or node.subscript is not None:
            items.append(
                TextItemPlan(
                    item_type=0, kind="script_end",
                    font=FontRole.GOST_TYPE_A, content="",
                )
            )
        return items
    if isinstance(node, Radical):
        return [TextItemPlan(
            item_type=17, kind="special", font=FontRole.GOST_TYPE_A,
            content=_compile_control_node(node.body), i_s_numb=98,
        ), TextItemPlan(
            item_type=18, kind="special_end", font=FontRole.GOST_TYPE_A, content="",
        )]
    if isinstance(node, StyledNode):
        return [replace(item, italic_override=node.italic) for item in _compile_node(node.body)]
    if isinstance(node, Fraction):
        numerator_text = _plain_text_strip(node.numerator)
        denominator_text = _plain_text_strip(node.denominator)
        return [
            TextItemPlan(
                item_type=1, kind="fraction_num",
                font=FontRole.GOST_TYPE_A,
                content=numerator_text,
            ),
            TextItemPlan(
                item_type=2, kind="fraction_den",
                font=FontRole.GOST_TYPE_A,
                content=denominator_text,
            ),
            TextItemPlan(
                item_type=3, kind="fraction_end",
                font=FontRole.GOST_TYPE_A, content="",
            ),
        ]
    if isinstance(node, Decorated):
        symbol_number = {"overline": 95, "underline": 96}.get(node.kind)
        if symbol_number is None:
            raise ValueError(f"Unsupported decoration: {node.kind!r}")
        return [
            TextItemPlan(item_type=17, kind="special",
                         font=FontRole.GOST_TYPE_A,
                         content=_compile_control_node(node.body),
                         i_s_numb=symbol_number),
            TextItemPlan(item_type=18, kind="special_end",
                         font=FontRole.GOST_TYPE_A, content=""),
        ]
    if isinstance(node, UnderOver):
        return _compile_node(node.base)
    raise TypeError(f"Unsupported node type: {type(node)!r}")


def _compile_script_content(
    node: Node, kind: str
) -> list[TextItemPlan]:
    """Compile a script (superscript/subscript) AST node into items.

    For simple ``Text`` nodes the content is mapped through the
    appropriate font; for complex nodes the plain-text representation
    is used.
    """
    font = FontRole.GOST_TYPE_A
    content = ""
    italic_override = None
    if isinstance(node, Text):
        content = _convert_text_content(node.value)
        font = _detect_font_for_text(node.value)
    elif isinstance(node, StyledNode):
        content = _convert_text_content(plain_text(node.body))
        font = _detect_font_for_text(content)
        italic_override = node.italic
    else:
        content = _convert_text_content(plain_text(node))
        font = _detect_font_for_text(content)
    return [TextItemPlan(item_type=0, kind=kind, font=font, content=content,
                         italic_override=italic_override)]


def _compile_plain_text(text: str) -> list[TextItemPlan]:
    """Compile plain Unicode text into a list of text items.

    Detects Greek characters (→Symbol font), Unicode superscript/subscript
    codepoints (→structural Script), degree (→&01), and groups consecutive
    characters of the same category into items.
    """
    text = normalize_kompas_text(text)
    if not text:
        return [
            TextItemPlan(item_type=0, kind="plain",
                         font=FontRole.GOST_TYPE_A, content="")
        ]

    items: list[TextItemPlan] = []
    plain_buffer: list[str] = []
    greek_buffer: list[str] = []
    sup_buffer: list[str] = []
    sub_buffer: list[str] = []
    has_script = False

    def _flush_plain() -> None:
        nonlocal plain_buffer
        if plain_buffer:
            content = _convert_text_content("".join(plain_buffer))
            items.append(
                TextItemPlan(item_type=0, kind="plain",
                             font=FontRole.GOST_TYPE_A, content=content)
            )
            plain_buffer = []

    def _flush_greek() -> None:
        nonlocal greek_buffer
        if greek_buffer:
            content = _convert_text_content("".join(greek_buffer))
            items.append(
                TextItemPlan(item_type=0, kind="plain",
                             font=FontRole.SYMBOL, content=content)
            )
            greek_buffer = []

    def _mark_base_as_script_base() -> None:
        """Change the last plain/painted item to script_base."""
        if items and items[-1].kind == "plain":
            last = items[-1]
            items[-1] = TextItemPlan(
                item_type=0, kind="script_base",
                font=last.font, content=last.content,
            )

    def _flush_scripts() -> None:
        nonlocal sup_buffer, sub_buffer, has_script
        if sup_buffer:
            _flush_plain()
            _flush_greek()
            _mark_base_as_script_base()
            content = "".join(
                _UNICODE_SUP_TO_REG.get(ch, ch) for ch in sup_buffer
            )
            items.append(
                TextItemPlan(item_type=0, kind="script_upper",
                             font=FontRole.GOST_TYPE_A, content=content)
            )
            sup_buffer = []
        if sub_buffer:
            _flush_plain()
            _flush_greek()
            _mark_base_as_script_base()
            content = "".join(
                _UNICODE_SUB_TO_REG.get(ch, ch) for ch in sub_buffer
            )
            items.append(
                TextItemPlan(item_type=0, kind="script_lower",
                             font=FontRole.GOST_TYPE_A, content=content)
            )
            sub_buffer = []
        if has_script:
            items.append(
                TextItemPlan(item_type=0, kind="script_end",
                             font=FontRole.GOST_TYPE_A, content="")
            )
            has_script = False

    for ch in text:
        if ch == "\u00B0" or ch in _MATH_SYMBOL_CHARS:
            _flush_plain()
            _flush_greek()
            _flush_scripts()
            if ch == "\u00B0":
                content = "&01"
                font = FontRole.GOST_TYPE_A
            elif ch in _GOST_MAPPED_MATH:
                # Exact final output slots from the paperclip converter.
                content = _GREEK_TO_SYMBOL[ch]
                font = (FontRole.SYMBOL if ch in _SYMBOL_MAPPED_MATH
                        else FontRole.GOST_TYPE_A)
            else:
                # No paperclip mapping: preserve the Unicode glyph.
                content = ch
                font = FontRole.GOST_TYPE_A
            items.append(
                TextItemPlan(
                    item_type=0, kind="plain", font=font, content=content
                )
            )
        elif ch in _GREEK_CHARS:
            if plain_buffer or sup_buffer or sub_buffer:
                _flush_plain()
                _flush_scripts()
            greek_buffer.append(ch)
        elif ch in _UNICODE_SUP_CHARS:
            _flush_plain()
            _flush_greek()
            sup_buffer.append(ch)
            has_script = True
        elif ch in _UNICODE_SUB_CHARS:
            _flush_plain()
            _flush_greek()
            sub_buffer.append(ch)
            has_script = True
        else:
            if greek_buffer:
                _flush_greek()
            if sup_buffer or sub_buffer:
                _flush_scripts()
            plain_buffer.append(ch)

    _flush_plain()
    _flush_greek()
    _flush_scripts()

    if not items:
        items.append(
            TextItemPlan(item_type=0, kind="plain",
                         font=FontRole.GOST_TYPE_A, content="")
        )
    return items


def _detect_font_for_text(text: str) -> FontRole:
    """Return ``SYMBOL`` if any character is a Greek letter, else ``GOST_TYPE_A``."""
    for ch in text:
        if ch in _GREEK_CHARS:
            return FontRole.SYMBOL
    return FontRole.GOST_TYPE_A


def _convert_text_content(text: str) -> str:
    """Replace Greek Unicode characters with Symbol font ASCII slots
    and degree symbol with the API5 special sequence ``&01``.
    """
    result: list[str] = []
    for ch in text:
        if ch in _GREEK_TO_SYMBOL:
            result.append(_GREEK_TO_SYMBOL[ch])
        elif ch in _GOST_MAPPED_MATH:
            result.append(_GREEK_TO_SYMBOL[ch])
        elif ch in _MATH_SYMBOL_CHARS:
            # No equivalent in the paperclip converter: preserve Unicode.
            result.append(ch)
        elif ch == "\u00B0":
            result.append("&01")
        elif ord(ch) < 32 or (0x7F <= ord(ch) <= 0x9F):
            raise ValueError(f"Unsupported codepoint: U+{ord(ch):04X} {ch!r}")
        else:
            result.append(ch)
    return "".join(result)


def _compile_script_argument(node: Node) -> str:
    """Compile a script argument without opening a nested KOMPAS control domain.

    KOMPAS uses ``$upper;lower$`` for scripts, but the delimiters cannot be
    nested.  TeX labels such as ``M_{\\Phi_{3}}`` therefore must not compile
    the inner ``\\Phi_{3}`` as another ``$...$`` expression: KOMPAS otherwise
    leaves the tail (notably ``;3$``) as literal text.  Flattening the inner
    script keeps all visible glyphs in the outer index and is the only safe
    one-object representation available through this control syntax.
    """
    if isinstance(node, Script):
        parts = [_compile_script_argument(node.base)]
        if node.superscript is not None:
            parts.append(_compile_script_argument(node.superscript))
        if node.subscript is not None:
            parts.append(_compile_script_argument(node.subscript))
        return "".join(parts)
    if isinstance(node, Sequence):
        return "".join(_compile_script_argument(part) for part in node.parts)
    return _compile_control_node(node)


def _compile_control_node(node: Node) -> str:
    """Compile a nested node into KOMPAS control syntax for a text special."""
    if isinstance(node, Text):
        result: list[str] = []
        for ch in node.value:
            if ch in _GREEK_TO_SYMBOL:
                # Match the paperclip converter exactly: put the mapped ASCII
                # slot (Φ -> F, φ -> f, ...) into a Symbol type A run.
                slot = _GREEK_TO_SYMBOL[ch]
                result.append(f"^(Symbol type A)+{ord(slot)}~")
            elif ch in _GOST_MAPPED_MATH:
                result.append(_GREEK_TO_SYMBOL[ch])
            elif ch in _MATH_SYMBOL_CHARS:
                result.append(ch)
            else:
                result.append(_convert_text_content(ch))
        return "".join(result)
    if isinstance(node, Sequence):
        return "".join(_compile_control_node(part) for part in node.parts)
    if isinstance(node, StyledNode):
        return _compile_control_node(node.body)
    if isinstance(node, Radical):
        return f"@+98~$({_compile_control_node(node.body)})$"
    if isinstance(node, Fraction):
        return "$d" + _compile_control_node(node.numerator) + ";" + _compile_control_node(node.denominator) + "$"
    if isinstance(node, Script):
        # A script argument may itself be scripted in TeX.  KOMPAS does not
        # support nested `$...$` domains, so flatten only the argument while
        # keeping this (outermost) script delimiter pair intact.
        upper = "" if node.superscript is None else _compile_script_argument(node.superscript)
        lower = "" if node.subscript is None else _compile_script_argument(node.subscript)
        return _compile_control_node(node.base) + f"${upper};{lower}$"
    if isinstance(node, Decorated):
        symbol_number = {"overline": 95, "underline": 96}.get(node.kind)
        if symbol_number is None:
            raise ValueError(f"Unsupported decoration: {node.kind!r}")
        return f"@+{symbol_number}~$({_compile_control_node(node.body)})$"
    if isinstance(node, UnderOver):
        # API5's S_BASE/S_UPPER/S_LOWER sequence is item-oriented and can only
        # be emitted structurally when UnderOver is the complete item. Nested
        # annotations remain in this one editable item as readable controls;
        # crucially, none of the engineering source is dropped.
        result = _compile_control_node(node.base)
        if node.above is not None:
            result += "^(" + _compile_control_node(node.above) + ")"
        if node.below is not None:
            result += "_(" + _compile_control_node(node.below) + ")"
        return result
    raise TypeError(f"Unsupported nested control node: {type(node)!r}")


def _plain_text_strip(node: Node) -> str:
    """Like ``plain_text()`` but collapses whitespace and removes
    structural markers."""
    raw = plain_text(node)
    return raw.strip() if raw else ""


__all__ = [
    "Node",
    "Text",
    "Sequence",
    "Fraction",
    "Decorated",
    "Radical",
    "StyledNode",
    "UnderOver",
    "Script",
    "FontRole",
    "TextItemPlan",
    "TextLinePlan",
    "TextRenderPlan",
    "LatexParser",
    "parse_latex_string",
    "parse_latex_document",
    "compile_latex",
    "compile_kompas_control_string",
    "compile_latex_api5_exact",
    "compile_unicode_text",
    "contains_math_unicode",
    "normalize_kompas_text",
    "normalize_math_whitespace",
    "estimate_plan_size",
    "plain_text",
    "count_primes",
    "plain_node_text",
    "LATEX_COMMANDS",
]
