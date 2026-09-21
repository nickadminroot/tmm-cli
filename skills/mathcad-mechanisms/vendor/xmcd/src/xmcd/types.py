"""Explicit vocabulary for identifiers, operations and presentation settings."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .expressions import Call, ExpressionInput


class Greek(StrEnum):
    ALPHA = "α"
    BETA = "β"
    GAMMA = "γ"
    DELTA = "δ"
    EPSILON = "ε"
    ZETA = "ζ"
    ETA = "η"
    THETA = "θ"
    IOTA = "ι"
    KAPPA = "κ"
    LAMBDA = "λ"
    MU = "μ"
    NU = "ν"
    XI = "ξ"
    OMICRON = "ο"
    PI = "π"
    RHO = "ρ"
    SIGMA = "σ"
    TAU = "τ"
    UPSILON = "υ"
    PHI = "φ"
    CHI = "χ"
    PSI = "ψ"
    OMEGA = "ω"
    CAPITAL_ALPHA = "Α"
    CAPITAL_BETA = "Β"
    CAPITAL_EPSILON = "Ε"
    CAPITAL_ZETA = "Ζ"
    CAPITAL_ETA = "Η"
    CAPITAL_IOTA = "Ι"
    CAPITAL_KAPPA = "Κ"
    CAPITAL_MU = "Μ"
    CAPITAL_NU = "Ν"
    CAPITAL_OMICRON = "Ο"
    CAPITAL_RHO = "Ρ"
    CAPITAL_TAU = "Τ"
    CAPITAL_CHI = "Χ"
    CAPITAL_GAMMA = "Γ"
    CAPITAL_DELTA = "Δ"
    CAPITAL_THETA = "Θ"
    CAPITAL_LAMBDA = "Λ"
    CAPITAL_XI = "Ξ"
    CAPITAL_PI = "Π"
    CAPITAL_SIGMA = "Σ"
    CAPITAL_UPSILON = "Υ"
    CAPITAL_PHI = "Φ"
    CAPITAL_PSI = "Ψ"
    CAPITAL_OMEGA = "Ω"


@dataclass(frozen=True)
class LiteralSubscript:
    text: str

    def __post_init__(self):
        if not isinstance(self.text, str) or not self.text:
            raise ValueError("A literal subscript needs nonempty text")


class DefinitionKind(StrEnum):
    NORMAL = "normal"
    LOCAL = "local"
    GLOBAL = "global"


class SolverKind(StrEnum):
    FIND = "Find"
    MINERR = "Minerr"
    MINIMIZE = "Minimize"
    MAXIMIZE = "Maximize"
    ODESOLVE = "Odesolve"


class SolverMethod(StrEnum):
    LINEAR = "linear"
    CONJUGATE = "conjugate"
    NEWTON = "newton"
    QUADRATIC = "quadratic"
    LEVENBERG = "levenberg"
    FIXED = "fixed"
    ADAPTIVE = "adaptive"
    RADAU = "radau"
    ADAMS_BDF = "adams/bdf (auto)"


class OperatorKind(StrEnum):
    ABS = "absval"
    CONJUGATE = "conjugate"
    FACTORIAL = "factorial"
    NEGATE = "neg"
    NOT = "not"
    SQRT = "sqrt"
    TRANSPOSE = "transpose"
    VECTORIZE = "vectorize"
    VECTOR_SUM = "vectorSum"
    DETERMINANT = "determinant"
    AND = "and"
    CROSS_PRODUCT = "crossProduct"
    DIVIDE = "div"
    EQUAL = "equal"
    GREATER_OR_EQUAL = "greaterOrEqual"
    GREATER_THAN = "greaterThan"
    INDEX = "indexer"
    LESS_OR_EQUAL = "lessOrEqual"
    LESS_THAN = "lessThan"
    LOG = "log"
    ROW = "matrow"
    COLUMN = "matcol"
    SUBTRACT = "minus"
    MULTIPLY = "mult"
    NOT_EQUAL = "notEqual"
    NTH_ROOT = "nthRoot"
    OR = "or"
    ADD = "plus"
    POWER = "pow"
    XOR = "xor"


class BuiltinFunction(StrEnum):
    SIN = "sin"
    COS = "cos"
    TAN = "tan"
    ASIN = "asin"
    ACOS = "acos"
    ATAN = "atan"
    EXP = "exp"
    LN = "ln"
    LOG = "log"
    LINTERP = "linterp"
    LSPLINE = "lspline"
    PSPLINE = "pspline"
    CSPLINE = "cspline"
    INTERP = "interp"
    LSOLVE = "lsolve"
    AUGMENT = "augment"
    STACK = "stack"
    ROWS = "rows"
    COLS = "cols"
    LENGTH = "length"
    ROOT = "root"
    ANGLE = "angle"
    RKFIXED = "rkfixed"
    RKADAPT = "Rkadapt"
    STRLEN = "strlen"
    MIN = "min"
    MAX = "max"
    FLOOR = "floor"
    CEIL = "ceil"

    def __call__(self, *arguments: ExpressionInput) -> Call:
        from .expressions import Call, Symbol

        return Call(Symbol(self.value), *arguments)


class MatrixStyle(StrEnum):
    AUTO = "auto"
    MATRIX = "matrix"
    TABLE = "table"


class NumberFormat(StrEnum):
    GENERAL = "general"
    DECIMAL = "decimal"
    SCIENTIFIC = "scientific"
    ENGINEERING = "engineering"
    FRACTION = "fraction"


class LineStyle(StrEnum):
    SOLID = "solid"
    DASH = "dash"
    DOT = "dot"
    DASH_DOT = "dash-dot"


class Marker(StrEnum):
    NONE = "none"
    CROSS = "cross"
    PLUS = "plus"
    SQUARE = "square"
    DIAMOND = "diamond"
    CIRCLE = "circle"
    TRIANGLE = "triangle"
    FILLED_SQUARE = "filled-square"
    FILLED_DIAMOND = "filled-diamond"
    FILLED_CIRCLE = "filled-circle"
    FILLED_TRIANGLE = "filled-triangle"


class TextStyle(StrEnum):
    NORMAL = "Normal"
    HEADING_1 = "Heading 1"
    HEADING_2 = "Heading 2"


class Orientation(StrEnum):
    PORTRAIT = "portrait"
    LANDSCAPE = "landscape"
