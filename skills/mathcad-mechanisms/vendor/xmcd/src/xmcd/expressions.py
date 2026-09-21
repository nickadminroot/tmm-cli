"""Composable, immutable Mathcad expressions; operators build syntax, never evaluate."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from numbers import Real
from typing import TypeAlias

from lxml import etree as ET

from .types import DefinitionKind, LiteralSubscript, OperatorKind, SolverKind, SolverMethod

ML = "http://schemas.mathsoft.com/math30"


def serialize_expression(expression):
    """Retain native metadata on unchanged immutable imported subexpressions."""
    source = getattr(expression, "_source_xml", None)
    return (
        ET.fromstring(source, ET.XMLParser(resolve_entities=False, no_network=True))
        if source is not None
        else expression.to_xml()
    )


def node(tag, *children, text=None, **attrs):
    result = ET.Element(f"{{{ML}}}{tag}", {k: str(v) for k, v in attrs.items()})
    result.text = text
    result.extend(serialize_expression(c) if isinstance(c, Expr) else c for c in children)
    return result


class Expr:
    def to_xml(self) -> ET._Element:
        raise NotImplementedError

    def __bool__(self):
        raise TypeError("Mathcad expressions have no Python truth value; use explicit comparisons")

    def __add__(self, other: ExpressionInput) -> Operator:
        return Operator(OperatorKind.ADD, self, other)

    def __radd__(self, other: ExpressionInput) -> Operator:
        return Operator(OperatorKind.ADD, other, self)

    def __sub__(self, other: ExpressionInput) -> Operator:
        return Operator(OperatorKind.SUBTRACT, self, other)

    def __rsub__(self, other: ExpressionInput) -> Operator:
        return Operator(OperatorKind.SUBTRACT, other, self)

    def __mul__(self, other: ExpressionInput) -> Operator:
        return Operator(OperatorKind.MULTIPLY, self, other)

    def __rmul__(self, other: ExpressionInput) -> Operator:
        return Operator(OperatorKind.MULTIPLY, other, self)

    def __truediv__(self, other: ExpressionInput) -> Operator:
        return Operator(OperatorKind.DIVIDE, self, other)

    def __rtruediv__(self, other: ExpressionInput) -> Operator:
        return Operator(OperatorKind.DIVIDE, other, self)

    def __pow__(self, other: ExpressionInput) -> Operator:
        return Operator(OperatorKind.POWER, self, other)

    def __rpow__(self, other: ExpressionInput) -> Operator:
        return Operator(OperatorKind.POWER, other, self)

    def __neg__(self) -> Operator:
        return Operator(OperatorKind.NEGATE, self)

    def __abs__(self) -> Operator:
        return Operator(OperatorKind.ABS, self)

    def __lt__(self, other: ExpressionInput) -> Operator:
        return Operator(OperatorKind.LESS_THAN, self, other)

    def __le__(self, other: ExpressionInput) -> Operator:
        return Operator(OperatorKind.LESS_OR_EQUAL, self, other)

    def __gt__(self, other: ExpressionInput) -> Operator:
        return Operator(OperatorKind.GREATER_THAN, self, other)

    def __ge__(self, other: ExpressionInput) -> Operator:
        return Operator(OperatorKind.GREATER_OR_EQUAL, self, other)

    def eq(self, other: ExpressionInput) -> Operator:
        return Operator(OperatorKind.EQUAL, self, other)

    def ne(self, other: ExpressionInput) -> Operator:
        return Operator(OperatorKind.NOT_EQUAL, self, other)

    def __and__(self, other: ExpressionInput) -> Operator:
        return Operator(OperatorKind.AND, self, other)

    def __or__(self, other: ExpressionInput) -> Operator:
        return Operator(OperatorKind.OR, self, other)

    def __invert__(self) -> Operator:
        return Operator(OperatorKind.NOT, self)

    def __getitem__(
        self, index: ExpressionInput | tuple[ExpressionInput, ExpressionInput]
    ) -> Operator:
        if isinstance(index, tuple):
            if len(index) != 2:
                raise ValueError("Matrix indexing requires (row, column)")
            index = Sequence(*index)
        return Operator(OperatorKind.INDEX, self, index)

    def column(self, index: ExpressionInput) -> Operator:
        return Operator(OperatorKind.COLUMN, self, index)

    def row(self, index: ExpressionInput) -> Operator:
        return Operator(OperatorKind.ROW, self, index)

    def vectorize(self) -> Operator:
        return Operator(OperatorKind.VECTORIZE, self)

    def determinant(self) -> Operator:
        return Operator(OperatorKind.DETERMINANT, self)

    def conjugate(self) -> Operator:
        return Operator(OperatorKind.CONJUGATE, self)

    def sqrt(self) -> Operator:
        return Operator(OperatorKind.SQRT, self)

    def nth_root(self, degree: ExpressionInput) -> Operator:
        return Operator(OperatorKind.NTH_ROOT, degree, self)

    def log(self, base: ExpressionInput) -> Operator:
        return Operator(OperatorKind.LOG, base, self)

    def factorial(self) -> Operator:
        return Operator(OperatorKind.FACTORIAL, self)

    def parens(self) -> Parens:
        return Parens(self)

    def __call__(self, *arguments: ExpressionInput) -> Call:
        return Call(self, *arguments)

    @property
    def T(self) -> Operator:
        return Operator(OperatorKind.TRANSPOSE, self)


ExpressionInput: TypeAlias = Expr | int | float | complex | Decimal


def expr(value: ExpressionInput) -> Expr:
    if isinstance(value, Expr):
        return value
    if isinstance(value, (Real, Decimal)):
        return Number(value)
    if isinstance(value, complex):
        return Number(value.real) + Operator(
            OperatorKind.MULTIPLY, Number(value.imag), Imaginary(1)
        )
    raise TypeError(f"Cannot convert {type(value).__name__} to a Mathcad expression")


def _coerce_fields(instance, *names):
    for name in names:
        value = getattr(instance, name)
        if value is not None:
            object.__setattr__(instance, name, expr(value))


@dataclass(frozen=True, eq=False)
class Number(Expr):
    value: int | float | Decimal

    def __post_init__(self):
        if not isinstance(self.value, (Real, Decimal)) or not math.isfinite(self.value):
            raise ValueError("Number requires a finite real value")

    def to_xml(self):
        return node(
            "real", text=str(int(self.value)) if isinstance(self.value, bool) else str(self.value)
        )


@dataclass(frozen=True, eq=False)
class Imaginary(Number):
    def to_xml(self):
        return node("imag", text=str(self.value))


@dataclass(frozen=True, eq=False)
class Symbol(Expr):
    name: str
    subscript: LiteralSubscript | None = None

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("Symbol name must be a nonempty string")
        if self.subscript is not None and not isinstance(self.subscript, LiteralSubscript):
            raise TypeError("subscript must be a LiteralSubscript")

    def to_xml(self):
        attrs = {"{http://www.w3.org/XML/1998/namespace}space": "preserve"}
        if self.subscript is not None:
            attrs["subscript"] = self.subscript.text
        return node("id", text=self.name, **attrs)


@dataclass(frozen=True, eq=False)
class String(Expr):
    value: str

    def to_xml(self):
        return node(
            "str", text=self.value, **{"{http://www.w3.org/XML/1998/namespace}space": "preserve"}
        )


@dataclass(frozen=True, eq=False)
class Placeholder(Expr):
    def to_xml(self):
        return node("placeholder")


@dataclass(frozen=True, eq=False)
class Parens(Expr):
    """Explicit visual grouping, also used automatically to preserve operator semantics."""

    value: Expr

    def __post_init__(self):
        object.__setattr__(self, "value", expr(self.value))

    def to_xml(self):
        return node("parens", self.value)


# Mathcad's equation auditor interprets visual precedence even in an XML AST.
# Fractions, radicals, absolute values and overbars already delimit their operands.
_PRECEDENCE = {
    "or": 10,
    "xor": 10,
    "and": 20,
    "not": 25,
    "equal": 30,
    "notEqual": 30,
    "lessThan": 30,
    "lessOrEqual": 30,
    "greaterThan": 30,
    "greaterOrEqual": 30,
    "plus": 40,
    "minus": 40,
    "mult": 50,
    "crossProduct": 50,
    "neg": 60,
    "pow": 70,
    "factorial": 80,
    "transpose": 80,
    "indexer": 80,
    "matcol": 80,
    "matrow": 80,
}


def _group_operand(parent, argument, index):
    precedence = _PRECEDENCE.get(parent)
    if precedence is None or (parent in {"pow", "indexer", "matcol", "matrow"} and index == 1):
        return argument
    if isinstance(argument, Number) and argument.value < 0:
        child_precedence = _PRECEDENCE["neg"]
    elif isinstance(argument, Operator):
        child_precedence = _PRECEDENCE.get(argument.name, 100)
    else:
        return argument
    if child_precedence < precedence or (
        child_precedence == precedence
        and (index > 0 or parent in {"pow", "neg", "not", "factorial", "transpose"})
    ):
        return Parens(argument)
    return argument


UNARY = frozenset(
    [
        "absval",
        "conjugate",
        "factorial",
        "neg",
        "not",
        "sqrt",
        "transpose",
        "vectorize",
        "vectorSum",
        "determinant",
    ]
)
BINARY = frozenset(
    [
        "and",
        "crossProduct",
        "div",
        "equal",
        "greaterOrEqual",
        "greaterThan",
        "indexer",
        "lessOrEqual",
        "lessThan",
        "log",
        "matrow",
        "matcol",
        "minus",
        "mult",
        "notEqual",
        "nthRoot",
        "or",
        "plus",
        "pow",
        "xor",
    ]
)


@dataclass(frozen=True, eq=False, init=False)
class Operator(Expr):
    name: OperatorKind
    arguments: tuple[Expr, ...]

    def __init__(self, name: OperatorKind, *arguments: ExpressionInput):
        if not isinstance(name, OperatorKind):
            raise TypeError("Operator name must be an OperatorKind")
        count = 1 if name in UNARY else 2 if name in BINARY else None
        if count is None or len(arguments) != count:
            raise ValueError(f"Unknown operator or wrong arity: {name} ({len(arguments)})")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "arguments", tuple(expr(a) for a in arguments))

    def to_xml(self):
        if self.name == "matrow":
            # The schema declares matrow, but classic Mathcad rejects that region.
            matrix, index = self.arguments
            return matrix.T.column(index).T.to_xml()
        return node(
            "apply",
            node(self.name),
            *(
                _group_operand(self.name, argument, index)
                for index, argument in enumerate(self.arguments)
            ),
        )


@dataclass(frozen=True, eq=False, init=False)
class Sequence(Expr):
    values: tuple[Expr, ...]

    def __init__(self, *values: ExpressionInput):
        if len(values) < 2:
            raise ValueError("A sequence requires at least two values")
        object.__setattr__(self, "values", tuple(expr(a) for a in values))

    def to_xml(self):
        return node("sequence", *self.values)


@dataclass(frozen=True, eq=False, init=False)
class Call(Expr):
    function: Expr
    arguments: tuple[Expr, ...]

    def __init__(self, function: Expr, *arguments: ExpressionInput):
        if not arguments:
            raise ValueError("Mathcad calls require at least one argument")
        object.__setattr__(self, "function", expr(function))
        object.__setattr__(self, "arguments", tuple(expr(a) for a in arguments))

    def to_xml(self):
        argument = self.arguments[0] if len(self.arguments) == 1 else Sequence(*self.arguments)
        return node("apply", self.function, argument)


@dataclass(frozen=True, eq=False)
class Given(Expr):
    """Start a solve block. Place guesses before it and constraints after it."""

    def to_xml(self):
        return Symbol("Given").to_xml()


@dataclass(frozen=True, eq=False)
class Solver(Expr):
    """Native solve terminator, called like Solver(SolverKind.FIND)(x, y).

    Keep this distinct from an ordinary function named Find: Mathcad stores
    solver options on a dedicated operator in the expression tree.
    """

    name: SolverKind = SolverKind.FIND
    method: SolverMethod | None = None

    def __post_init__(self):
        if not isinstance(self.name, SolverKind):
            raise TypeError("Solver name must be a SolverKind")
        if self.name not in {"Find", "Minerr", "Minimize", "Maximize", "Odesolve"}:
            raise ValueError("Unknown solve terminator")
        if self.method is not None and not isinstance(self.method, SolverMethod):
            raise TypeError("Solver method must be a SolverMethod")
        methods = (
            {"fixed", "adaptive", "radau", "adams/bdf (auto)"}
            if self.name == "Odesolve"
            else {"linear", "conjugate", "newton", "quadratic", "levenberg"}
        )
        if self.method is not None and self.method not in methods:
            raise ValueError(f"Unsupported method for {self.name}: {self.method}")

    def to_xml(self):
        attrs = {}
        if self.method is not None:
            attrs["method"] = self.method
            if self.name != "Odesolve":
                attrs["auto-method"] = "false"
        return node(self.name, **attrs)


@dataclass(frozen=True, eq=False, init=False)
class Matrix(Expr):
    rows: tuple[tuple[Expr, ...], ...]

    def __init__(self, rows: Iterable[Iterable[ExpressionInput]]):
        rows = tuple(tuple(expr(a) for a in row) for row in rows)
        if not rows or not rows[0] or any(len(r) != len(rows[0]) for r in rows):
            raise ValueError("Matrix must be nonempty and rectangular")
        object.__setattr__(self, "rows", rows)

    @classmethod
    def vector(cls, values: Iterable[ExpressionInput]):
        return cls([[v] for v in values])

    def to_xml(self):
        return node(
            "matrix",
            *(v for col in zip(*self.rows) for v in col),
            rows=len(self.rows),
            cols=len(self.rows[0]),
        )


@dataclass(frozen=True, eq=False)
class Range(Expr):
    start: ExpressionInput
    stop: ExpressionInput
    second: ExpressionInput | None = None

    def __post_init__(self):
        _coerce_fields(self, "start", "stop", "second")

    def to_xml(self):
        start = expr(self.start) if self.second is None else Sequence(self.start, self.second)
        return node("range", start, expr(self.stop))


@dataclass(frozen=True, eq=False)
class Function(Expr):
    name: Symbol
    parameters: Iterable[Symbol]

    def __post_init__(self):
        object.__setattr__(self, "name", expr(self.name))
        if not isinstance(self.name, Symbol):
            raise TypeError("Function name must be a Symbol")
        object.__setattr__(self, "parameters", tuple(expr(v) for v in self.parameters))
        if not self.parameters:
            raise ValueError("Function needs parameters")
        if any(not isinstance(v, Symbol) for v in self.parameters):
            raise TypeError("Function parameters must be symbols")

    def to_xml(self):
        return node("function", expr(self.name), node("boundVars", *self.parameters))

    def __call__(self, *arguments: ExpressionInput) -> Call:
        return Call(self.name, *arguments)


@dataclass(frozen=True, eq=False)
class Define(Expr):
    lhs: ExpressionInput
    rhs: ExpressionInput
    kind: DefinitionKind = DefinitionKind.NORMAL

    def __post_init__(self):
        if not isinstance(self.kind, DefinitionKind):
            raise TypeError("Definition kind must be a DefinitionKind")
        _coerce_fields(self, "lhs", "rhs")

    def to_xml(self):
        kinds = {"normal": "define", "local": "localDefine", "global": "globalDefine"}
        if self.kind not in kinds:
            raise ValueError("Definition kind must be normal, local or global")
        return node(kinds[self.kind], expr(self.lhs), expr(self.rhs))


@dataclass(frozen=True, eq=False)
class Evaluate(Expr):
    expression: ExpressionInput
    unit: ExpressionInput | None = None

    def __post_init__(self):
        _coerce_fields(self, "expression", "unit")

    def to_xml(self):
        result = node("eval", expr(self.expression))
        result.append(node("unitOverride", Placeholder() if self.unit is None else expr(self.unit)))
        return result


@dataclass(frozen=True, eq=False)
class Symbolic(Expr):
    expression: ExpressionInput
    commands: tuple[Expr, ...] = ()

    def __post_init__(self):
        _coerce_fields(self, "expression")
        if any(not isinstance(command, Expr) for command in self.commands):
            raise TypeError("Symbolic commands must be expressions (Symbol or Sequence)")
        object.__setattr__(self, "commands", tuple(self.commands))

    def to_xml(self):
        result = node("symEval", expr(self.expression))
        for command in self.commands:
            result.append(node("command", command))
        return result


@dataclass(frozen=True, eq=False)
class Derivative(Expr):
    expression: ExpressionInput
    variable: ExpressionInput
    degree: ExpressionInput = 1

    def __post_init__(self):
        _coerce_fields(self, "expression", "variable", "degree")

    def to_xml(self):
        return node(
            "apply",
            node("derivative"),
            node("lambda", node("boundVars", expr(self.variable)), expr(self.expression)),
            node("degree", expr(self.degree)),
        )


@dataclass(frozen=True, eq=False)
class Integral(Expr):
    expression: ExpressionInput
    variable: ExpressionInput
    lower: ExpressionInput | None = None
    upper: ExpressionInput | None = None
    _operator = "integral"

    def __post_init__(self):
        _coerce_fields(self, "expression", "variable", "lower", "upper")

    def to_xml(self):
        if (self.lower is None) != (self.upper is None):
            raise ValueError("Specify both bounds or neither")
        result = node(
            "apply",
            node(self._operator),
            node("lambda", node("boundVars", expr(self.variable)), expr(self.expression)),
        )
        if self.lower is not None:
            result.append(node("bounds", expr(self.lower), expr(self.upper)))
        return result


class Sum(Integral):
    _operator = "summation"


class Product(Integral):
    _operator = "product"


@dataclass(frozen=True, eq=False, init=False)
class Program(Expr):
    statements: tuple[Expr, ...]

    def __init__(self, *statements: ExpressionInput):
        if len(statements) < 2:
            raise ValueError("Native programs require at least two statements")
        object.__setattr__(self, "statements", tuple(expr(s) for s in statements))

    def to_xml(self):
        return node("program", *self.statements)


@dataclass(frozen=True, eq=False)
class If(Expr):
    condition: ExpressionInput
    value: ExpressionInput

    def __post_init__(self):
        _coerce_fields(self, "condition", "value")

    def to_xml(self):
        return node("ifThen", expr(self.condition), expr(self.value))


@dataclass(frozen=True, eq=False)
class Otherwise(Expr):
    value: ExpressionInput

    def __post_init__(self):
        _coerce_fields(self, "value")

    def to_xml(self):
        return node("otherwise", expr(self.value))


@dataclass(frozen=True, eq=False)
class For(Expr):
    variable: ExpressionInput
    values: ExpressionInput
    body: ExpressionInput

    def __post_init__(self):
        _coerce_fields(self, "variable", "values", "body")

    def to_xml(self):
        return node("for", expr(self.variable), expr(self.values), expr(self.body))


@dataclass(frozen=True, eq=False)
class While(Expr):
    condition: ExpressionInput
    body: ExpressionInput

    def __post_init__(self):
        _coerce_fields(self, "condition", "body")

    def to_xml(self):
        return node("while", expr(self.condition), expr(self.body))


@dataclass(frozen=True, eq=False)
class Return(Expr):
    value: ExpressionInput

    def __post_init__(self):
        _coerce_fields(self, "value")

    def to_xml(self):
        return node("return", expr(self.value))


@dataclass(frozen=True, eq=False)
class Break(Expr):
    def to_xml(self):
        return node("break")


@dataclass(frozen=True, eq=False)
class Continue(Expr):
    def to_xml(self):
        return node("continue")


@dataclass(frozen=True, eq=False)
class TryCatch(Expr):
    expression: ExpressionInput
    fallback: ExpressionInput

    def __post_init__(self):
        _coerce_fields(self, "expression", "fallback")

    def to_xml(self):
        return node("tryCatch", expr(self.expression), expr(self.fallback))
