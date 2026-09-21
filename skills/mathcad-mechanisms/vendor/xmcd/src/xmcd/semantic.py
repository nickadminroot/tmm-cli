"""Static worksheet checks. Unknown values are never treated as proof of correctness."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import TYPE_CHECKING

from .expressions import Function, Symbol
from .layout import SCALAR, ResultShape, key, local
from .validation import ValidationError

if TYPE_CHECKING:
    from .document import Worksheet


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class Diagnostic:
    code: str
    severity: Severity
    message: str
    region: int
    tag: str
    path: str

    def __str__(self):
        label = f"region {self.region}" + (f" [{self.tag}]" if self.tag else "")
        return f"{self.code}: {label}, {self.path}: {self.message}"


@dataclass(frozen=True)
class ValidationReport:
    diagnostics: tuple[Diagnostic, ...] = ()

    @property
    def errors(self) -> tuple[Diagnostic, ...]:
        return tuple(d for d in self.diagnostics if d.severity is Severity.ERROR)

    @property
    def warnings(self) -> tuple[Diagnostic, ...]:
        return tuple(d for d in self.diagnostics if d.severity is Severity.WARNING)

    def raise_for_errors(self, *, warnings_as_errors: bool = False) -> None:
        failures = self.diagnostics if warnings_as_errors else self.errors
        if failures:
            raise WorksheetValidationError(self, failures)


class WorksheetValidationError(ValidationError):
    def __init__(self, report: ValidationReport, failures=None):
        self.report = report
        super().__init__(
            "\n".join(str(d) for d in (report.errors if failures is None else failures))
        )


@dataclass(frozen=True)
class ValidationContext:
    """Explicit declarations for names supplied by external Mathcad extensions.

    Declarations do not generate definitions or verify the installed environment.
    Every use of one is reported as externally unverified.
    """

    symbols: tuple[Symbol, ...] = ()
    functions: tuple[Function, ...] = ()

    def __post_init__(self):
        if any(not isinstance(s, Symbol) for s in self.symbols):
            raise TypeError("symbols must contain Symbol objects")
        if any(not isinstance(f, Function) for f in self.functions):
            raise TypeError("functions must contain Function objects")


@dataclass(eq=False)
class _Function:
    parameters: tuple
    body: object | None
    scope: dict


@dataclass(frozen=True)
class _Value:
    shape: ResultShape | None = None
    number: float | None = None
    function: _Function | None = None
    # SI length, mass, time, current, temperature, amount, luminous intensity.
    units: tuple[float, ...] | None = None
    text: bool = False
    external: bool = False
    interval: tuple[float, float] | None = None


_ZERO = (0,) * 7
_UNKNOWN = _Value()
_SCALAR = _Value(SCALAR, units=_ZERO)
# A deliberately explicit registry. Unknown builtins require ValidationContext.
_ARITIES = {
    **{
        n: (1, 1)
        for n in [
            "sin",
            "cos",
            "tan",
            "asin",
            "acos",
            "atan",
            "sinh",
            "cosh",
            "tanh",
            "exp",
            "ln",
            "rows",
            "cols",
            "length",
            "last",
            "strlen",
            "floor",
            "ceil",
            "Re",
            "Im",
            "norm1",
            "norm2",
            "normi",
        ]
    },
    "log": (1, 2),
    "round": (1, 2),
    "angle": (2, 2),
    "atan2": (2, 2),
    "linterp": (3, 3),
    "lspline": (2, 2),
    "pspline": (2, 2),
    "cspline": (2, 2),
    "interp": (4, 4),
    "lsolve": (2, 2),
    "root": (2, 4),
    "augment": (2, None),
    "stack": (2, None),
    "min": (1, None),
    "max": (1, None),
    "rkfixed": (5, 5),
    "Rkadapt": (5, 5),
    "Bulstoer": (5, 5),
}
_SOLVERS = {"Find", "Minerr", "Minimize", "Maximize", "Odesolve"}


def _unit(**powers):
    return tuple(powers.get(k, 0) for k in ("L", "M", "T", "I", "K", "N", "J"))


_UNITS = {
    **dict.fromkeys(("m", "mm", "cm", "km", "in", "ft"), _unit(L=1)),
    **dict.fromkeys(
        (
            "s",
            "ms",
            "hr",
        ),
        _unit(T=1),
    ),
    **dict.fromkeys(("kg", "g"), _unit(M=1)),
    "A": _unit(I=1),
    "K": _unit(K=1),
    "mol": _unit(N=1),
    "cd": _unit(J=1),
    "Hz": _unit(T=-1),
    "N": _unit(M=1, L=1, T=-2),
    "Pa": _unit(M=1, L=-1, T=-2),
    "J": _unit(M=1, L=2, T=-2),
    "W": _unit(M=1, L=2, T=-3),
    "V": _unit(M=1, L=2, T=-3, I=-1),
    "C": _unit(T=1, I=1),
    "ohm": _unit(M=1, L=2, T=-3, I=-2),
    "rad": _ZERO,
    "deg": _ZERO,
}


def _name(node):
    name, subscript = key(node)
    return name + (f"_{subscript}" if subscript else "")


def _arguments(node):
    args = list(node)[1:]
    return list(args[0]) if len(args) == 1 and local(args[0]) == "sequence" else args


class _Analyzer:
    def __init__(self, sheet, context):
        self.sheet = sheet
        self.diagnostics = []
        self.location = (0, "")
        self.active_calls = set()
        self.call_cache = {}
        self.emission_log = []
        self.diagnostic_set = set()
        self.opaque_call_epoch = 0
        self.in_solve = False
        self.scope = {(n, ""): _Value(SCALAR, units=u) for n, u in _UNITS.items()}
        self.scope.update(
            {
                (n, ""): _Value(SCALAR, number=v, units=_ZERO)
                for n, v in {
                    "π": math.pi,
                    "pi": math.pi,
                    "e": math.e,
                    "ORIGIN": sheet.origin,
                    "TOL": sheet.tolerance,
                    "CTOL": sheet.constraint_tolerance,
                }.items()
            }
        )
        for symbol in context.symbols:
            self.scope[key(symbol.to_xml())] = _Value(external=True)
        for function in context.functions:
            self.scope[key(function.name.to_xml())] = _Value(
                function=_Function(tuple(key(p.to_xml()) for p in function.parameters), None, {}),
                external=True,
            )

    def emit(self, code, message, path, *, warning=False):
        diagnostic = Diagnostic(
            code, Severity.WARNING if warning else Severity.ERROR, message, *self.location, path
        )
        self.emission_log.append(diagnostic)
        if diagnostic not in self.diagnostic_set:
            self.diagnostic_set.add(diagnostic)
            self.diagnostics.append(diagnostic)

    def run(self):
        from .document import Area, MathRegion
        from .plots import XYPlot

        def geometry(items):
            for i, item in enumerate(items, 1):
                self.location = i, item.tag
                for name in ("left", "top", "width", "height"):
                    value = getattr(item, name)
                    if value is not None and (
                        not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0
                    ):
                        self.emit("region-geometry", f"{name} must be finite and nonnegative", name)
                if isinstance(item, Area):
                    geometry(item.regions)

        geometry(self.sheet.regions)
        if self.diagnostics:
            return ValidationReport(tuple(self.diagnostics))
        self.sheet.layout(strict=False)
        regions = []

        def flatten(items, dy=0, dx=0):
            for item in items:
                if isinstance(item, Area):
                    flatten(item.regions, dy + item.top, dx + item.left)
                else:
                    regions.append((dy + item.top, dx + item.left, item))

        flatten(self.sheet.regions)
        regions.sort(key=lambda entry: entry[:2])
        # Global definitions are evaluated first, in their own spatial order.
        for index, (_, _, region) in enumerate(regions, 1):
            if isinstance(region, MathRegion) and not region.disabled:
                node = region.expression.to_xml()
                if local(node) == "globalDefine":
                    self.location = index, region.tag
                    self.visit(node, self.scope, "expression")
        i = 0
        while i < len(regions):
            _, _, region = regions[i]
            self.location = i + 1, region.tag
            if isinstance(region, MathRegion) and not region.disabled:
                node = region.expression.to_xml()
                if local(node) == "id" and node.text == "Given":
                    end = i + 1
                    while end < len(regions):
                        candidate = regions[end][2]
                        if isinstance(candidate, MathRegion) and not candidate.disabled:
                            tree = candidate.expression.to_xml()
                            if any(local(n) in _SOLVERS for n in tree.iter()):
                                break
                            if local(tree) == "id" and tree.text == "Given":
                                break
                        end += 1
                    if end == len(regions) or not any(
                        local(n) in _SOLVERS for n in regions[end][2].expression.to_xml().iter()
                    ):
                        self.emit("solve-block", "Given has no terminating solver", "expression")
                    else:
                        self.solve(regions, i, end)
                        i = end + 1
                        continue
                elif local(node) != "globalDefine":
                    self.visit(node, self.scope, "expression")
            elif isinstance(region, XYPlot):
                for j, trace in enumerate(region.traces):
                    self.visit(trace.x.to_xml(), self.scope, f"traces[{j}].x")
                    self.visit(trace.y.to_xml(), self.scope, f"traces[{j}].y")
            i += 1
        return ValidationReport(tuple(self.diagnostics))

    def solve(self, regions, start, end):
        terminal = regions[end][2].expression.to_xml()
        scope = dict(self.scope)
        if local(terminal) in {"define", "globalDefine"} and local(terminal[0]) == "function":
            scope.update({key(p): _UNKNOWN for p in terminal[0][1]})
        ode = next((n for n in terminal.iter() if local(n) == "Odesolve"), None)
        if ode is not None:
            args = _arguments(ode.getparent())
            if args and local(args[0]) == "id":
                scope[key(args[0])] = _SCALAR
            for _, _, region in regions[start + 1 : end]:
                if hasattr(region, "expression"):
                    for n in region.expression.to_xml().iter():
                        if local(n) == "derivative":
                            body = n.getparent()[1][-1]
                            if local(body) == "apply" and local(body[0]) == "id":
                                scope[key(body[0])] = _Value(
                                    function=_Function((("t", ""),), None, {})
                                )
        self.in_solve = True
        self.emit(
            "runtime-solver",
            "Solver convergence and existence of a solution require Mathcad",
            "expression",
            warning=True,
        )
        try:
            for j in range(start + 1, end + 1):
                region = regions[j][2]
                self.location = j + 1, region.tag
                if hasattr(region, "expression") and not region.disabled:
                    self.visit(region.expression.to_xml(), scope, "expression")
        finally:
            self.in_solve = False
        for _, _, region in regions[start + 1 : end + 1]:
            if hasattr(region, "expression") and not region.disabled:
                definition = region.expression.to_xml()
                if local(definition) in {"define", "globalDefine"}:
                    lhs = definition[0][0] if local(definition[0]) == "function" else definition[0]
                    if local(lhs) == "id" and key(lhs) in scope:
                        self.scope[key(lhs)] = scope[key(lhs)]

    def visit(
        self,
        node,
        scope,
        path,
        *,
        program=False,
        loop=False,
        symbolic=False,
        conditional=False,
        caught=False,
        vectorized=False,
    ):
        tag = local(node)

        def child(n, suffix, **overrides):
            options = {
                "program": program,
                "loop": loop,
                "symbolic": symbolic,
                "conditional": conditional,
                "caught": caught,
                "vectorized": vectorized,
            }
            options.update(overrides)
            return self.visit(n, scope, path + "/" + suffix, **options)

        def runtime(code, message):
            if not caught:
                self.emit(code, message, path, warning=conditional)

        if tag in {"real", "imag", "str"}:
            number = float(node.text) if tag == "real" else None
            return _Value(SCALAR, number=number, units=_ZERO, text=tag == "str")
        if tag == "id":
            value = scope.get(key(node))
            if value is None and key(node)[1] == "" and node.text in _ARITIES:
                return _Value(function=_Function((), None, {}))
            if value is None:
                if not symbolic:
                    self.emit("undefined-symbol", f"{_name(node)!r} is not defined here", path)
                return _UNKNOWN
            if value.external:
                self.emit(
                    "external-unchecked",
                    f"{_name(node)!r} relies on an external declaration",
                    path,
                    warning=True,
                )
            return value
        if tag == "placeholder":
            self.emit("placeholder", "An unfinished expression contains a placeholder", path)
            return _UNKNOWN
        if tag in {"define", "globalDefine", "localDefine"}:
            if tag == "localDefine" and not program:
                self.emit("program-context", "Local assignment requires a Program", path)
            lhs, rhs = node
            if local(lhs) == "function":
                parameters = tuple(key(p) for p in lhs[1])
                if len(set(parameters)) != len(parameters):
                    self.emit("duplicate-parameter", "Function parameters must be distinct", path)
                closure = dict(scope)
                info = _Function(parameters, rhs, closure)
                value = _Value(function=info)
                closure[key(lhs[0])] = value
                body_scope = {**closure, **dict.fromkeys(parameters, _UNKNOWN)}
                self.visit(rhs, body_scope, path + "/body", conditional=True)
                scope[key(lhs[0])] = value
                return value
            value = child(rhs, "rhs")
            if local(lhs) == "id":
                scope[key(lhs)] = value
            elif local(lhs) == "apply" and local(lhs[0]) == "indexer" and local(lhs[1]) == "id":
                indices = list(lhs[2]) if local(lhs[2]) == "sequence" else [lhs[2]]
                dims = []
                origin = scope.get(("ORIGIN", ""), _UNKNOWN).number
                for j, index in enumerate(indices):
                    v = child(index, f"index[{j}]")
                    hi = v.interval[1] if v.interval else v.number
                    lo = v.interval[0] if v.interval else v.number
                    if (
                        lo is not None
                        and origin is not None
                        and (lo < origin or not float(lo).is_integer())
                    ):
                        runtime("index-domain", "Array indices must be integers at or above ORIGIN")
                    dims.append(
                        int(hi - origin + 1) if hi is not None and origin is not None else None
                    )
                if len(dims) == 1:
                    dims.append(1)
                old = scope.get(key(lhs[1]), _UNKNOWN)
                shape = None
                if all(n is not None and n > 0 for n in dims):
                    shape = ResultShape(
                        max(dims[0], old.shape.rows if old.shape else 1),
                        max(dims[1], old.shape.columns if old.shape else 1),
                    )
                scope[key(lhs[1])] = _Value(shape, units=value.units)
            else:
                self.emit(
                    "assignment-target",
                    "Definition target must be a symbol, function or array element",
                    path,
                )
            return value
        if tag == "function":
            self.emit(
                "function-context",
                "A function signature is only valid on the left of a definition",
                path,
            )
            return _UNKNOWN
        if tag == "eval":
            value = child(node[0], "value")
            if len(node) > 1 and len(node[1]) and local(node[1][0]) != "placeholder":
                unit = child(node[1][0], "unit")
                if value.units is not None and unit.units is not None and value.units != unit.units:
                    runtime("unit-mismatch", "Requested result unit has incompatible dimensions")
            return value
        if tag == "symEval":
            child(node[0], "symbolic", symbolic=True)
            self.emit(
                "symbolic-unchecked",
                "Symbolic engine results and commands require Mathcad",
                path,
                warning=True,
            )
            return _UNKNOWN
        if tag in {"parens", "return", "otherwise"}:
            if tag != "parens" and not program:
                self.emit("program-context", f"{tag} requires a Program", path)
            return child(node[0], tag, conditional=conditional or tag == "otherwise")
        if tag in {"break", "continue"}:
            if not loop:
                self.emit("loop-context", f"{tag} requires a loop", path)
            return _UNKNOWN
        if tag == "program":
            scope = dict(scope)
            value = _UNKNOWN
            for i, statement in enumerate(node):
                value = child(statement, f"statement[{i}]", program=True)
            if any(
                local(n) in {"ifThen", "otherwise", "return", "for", "while", "break", "continue"}
                for n in node.iter()
            ):
                return _UNKNOWN
            return value
        if tag == "ifThen":
            if not program:
                self.emit("program-context", "If requires a Program", path)
            child(node[0], "condition")
            self.visit(
                node[1],
                dict(scope),
                path + "/branch",
                program=program,
                loop=loop,
                conditional=True,
                caught=caught,
            )
            for assignment in node[1].iter():
                if local(assignment) == "localDefine" and local(assignment[0]) == "id":
                    scope[key(assignment[0])] = _UNKNOWN
            return _UNKNOWN
        if tag in {"for", "while"}:
            if not program:
                self.emit("program-context", "A loop requires a Program", path)
            child(node[1] if tag == "for" else node[0], "range" if tag == "for" else "condition")
            nested = {k: replace(v, number=None) for k, v in scope.items()}
            if tag == "for":
                if local(node[0]) != "id":
                    self.emit("loop-variable", "For variable must be a Symbol", path)
                else:
                    nested[key(node[0])] = _SCALAR
            self.visit(
                node[-1],
                nested,
                path + "/body",
                program=True,
                loop=True,
                conditional=True,
                caught=caught,
            )
            for assignment in node[-1].iter():
                if local(assignment) == "localDefine" and local(assignment[0]) == "id":
                    scope[key(assignment[0])] = _UNKNOWN
            if tag == "for" and local(node[0]) == "id":
                scope[key(node[0])] = _UNKNOWN
            self.emit(
                "runtime-program",
                "Loop values and termination are not evaluated",
                path,
                warning=True,
            )
            return _UNKNOWN
        if tag == "tryCatch":
            a = child(node[0], "try", caught=True)
            b = child(node[1], "fallback", conditional=True)
            return a if a == b else _UNKNOWN
        if tag == "matrix":
            values = [child(n, f"cell[{i}]") for i, n in enumerate(node)]
            units = {v.units for v in values if v.units is not None and v.number != 0}
            if len(units) > 1:
                runtime("unit-mismatch", "Classic Mathcad matrix elements need compatible units")
            return _Value(
                ResultShape(int(node.get("rows")), int(node.get("cols"))),
                units=next(iter(units)) if len(units) == 1 else None,
            )
        if tag == "range":
            bounds = list(node[0]) if local(node[0]) == "sequence" else [node[0]]
            values = [child(n, f"bound[{i}]") for i, n in enumerate([*bounds, node[-1]])]
            numbers = [v.number for v in values]
            if all(n is not None for n in numbers):
                start, stop = numbers[0], numbers[-1]
                step = numbers[1] - start if len(numbers) == 3 else 1
                if step == 0:
                    runtime("range-step", "Range step is zero")
                elif (stop - start) / step >= 0:
                    return _Value(
                        SCALAR,
                        units=values[0].units,
                        interval=(min(start, stop), max(start, stop)),
                    )
            return _UNKNOWN
        if tag != "apply":
            self.emit("unchecked-expression", f"No semantic rule for {tag}", path, warning=True)
            return _UNKNOWN
        op = local(node[0])
        args = list(node)[1:]
        if op in {"integral", "derivative", "summation", "product"}:
            bound = args[0][0]
            if any(local(n) != "id" for n in bound):
                self.emit("bound-variable", "Calculus bound variables must be symbols", path)
            if op == "derivative" and not symbolic:
                for n in bound:
                    child(n, "evaluation-point")
            nested = {**scope, **{key(n): _SCALAR for n in bound}}
            self.visit(
                args[0][-1],
                nested,
                path + "/body",
                program=program,
                conditional=True,
                caught=caught,
                symbolic=symbolic,
            )
            for i, decoration in enumerate(args[1:]):
                for j, n in enumerate(decoration):
                    child(n, f"bound[{i},{j}]")
            self.emit(
                "runtime-calculus",
                "Numeric calculus, singularities and convergence require Mathcad",
                path,
                warning=True,
            )
            return _UNKNOWN
        if op in _SOLVERS:
            if not self.in_solve:
                if op in {"Find", "Minerr", "Odesolve"}:
                    self.emit("solve-block", f"{op} requires a preceding Given block", path)
                else:
                    self.emit(
                        "runtime-solver",
                        "Unconstrained optimization requires Mathcad",
                        path,
                        warning=True,
                    )
            solver_args = _arguments(node)
            minimum = 2 if op in {"Minimize", "Maximize", "Odesolve"} else 1
            if len(solver_args) < minimum:
                self.emit("function-arity", f"{op} requires at least {minimum} arguments", path)
            values = [child(n, f"argument[{i}]") for i, n in enumerate(_arguments(node))]
            if op == "Odesolve":
                return _Value(function=_Function((("t", ""),), None, {}))
            return _Value(
                ResultShape(len(values), 1)
                if op in {"Find", "Minerr"} and len(values) > 1
                else SCALAR
            )
        if op == "id":
            return self.call(
                node,
                scope,
                path,
                program=program,
                loop=loop,
                conditional=conditional,
                caught=caught,
                symbolic=symbolic,
            )
        if op in {"real", "imag", "str", "matrix"}:
            self.emit("not-callable", "A literal value cannot be called as a function", path)
            return _UNKNOWN
        if op == "vectorize":
            return child(args[0], "vectorized", vectorized=True)
        values = [
            _UNKNOWN if op == "indexer" and i == 1 else child(n, f"operand[{i}]")
            for i, n in enumerate(args)
        ]
        if op == "indexer":
            # Sequence is structural, not itself a value expression.
            indices = list(args[1]) if local(args[1]) == "sequence" else [args[1]]
            indices = [child(n, f"index[{i}]") for i, n in enumerate(indices)]
            origin = scope.get(("ORIGIN", ""), _UNKNOWN).number
            shape = values[0].shape
            for i, v in enumerate(indices):
                n = v.number
                if n is not None and origin is not None:
                    if n < origin or not float(n).is_integer():
                        runtime("index-domain", "Array indices must be integers at or above ORIGIN")
                    elif shape and n - origin >= (shape.rows if i == 0 else shape.columns):
                        runtime("index-bounds", f"Index {n:g} exceeds known array dimensions")
            if shape and not shape.matrix:
                runtime("matrix-required", "Indexing requires an array")
            return _Value(SCALAR, units=values[0].units)
        if op in {"matcol", "transpose", "determinant", "vectorSum"}:
            shape = values[0].shape
            if shape and not shape.matrix:
                runtime("matrix-required", f"{op} requires a matrix or vector")
            if shape and op == "determinant" and shape.rows != shape.columns:
                runtime("matrix-dimensions", "A determinant requires a square matrix")
            if shape and op == "matcol":
                index, origin = values[1].number, scope.get(("ORIGIN", ""), _UNKNOWN).number
                if (
                    index is not None
                    and origin is not None
                    and (
                        not float(index).is_integer()
                        or not origin <= index < origin + shape.columns
                    )
                ):
                    runtime("index-bounds", "Column index is outside known matrix bounds")
                return _Value(ResultShape(shape.rows, 1), units=values[0].units)
            if shape and op == "transpose":
                return _Value(ResultShape(shape.columns, shape.rows), units=values[0].units)
            return _Value(SCALAR, units=values[0].units)
        if op == "div" and values[-1].number == 0:
            runtime("division-by-zero", "Denominator is statically zero")
        if (
            op == "factorial"
            and values[0].number is not None
            and (values[0].number < 0 or not float(values[0].number).is_integer())
        ):
            runtime("factorial-domain", "Factorial requires a nonnegative integer")
        if op == "nthRoot" and values[0].number == 0:
            runtime("root-degree", "Root degree cannot be zero")
        if op == "log" and values[0].number in {0, 1}:
            runtime("log-base", "Logarithm base cannot be zero or one")
        shape = None
        shapes = [v.shape for v in values]
        if all(s is not None for s in shapes):
            matrices = [s for s in shapes if s.matrix]
            if len(matrices) == 2:
                a, b = matrices
                if (
                    op == "mult"
                    and not vectorized
                    and a.columns == b.columns == 1
                    and a.rows == b.rows
                ):
                    shape = SCALAR
                elif op == "mult" and not vectorized:
                    if a.columns != b.rows:
                        runtime(
                            "matrix-dimensions",
                            f"Cannot multiply {a.rows}x{a.columns} by {b.rows}x{b.columns}",
                        )
                    shape = ResultShape(a.rows, b.columns)
                else:
                    if (a.rows, a.columns) != (b.rows, b.columns):
                        runtime("matrix-dimensions", "Matrix operands have different dimensions")
                    shape = a
            else:
                shape = matrices[0] if matrices else SCALAR
        if op == "crossProduct":
            for v in values:
                if v.shape and (v.shape.rows != 3 or v.shape.columns != 1):
                    runtime(
                        "matrix-dimensions", "Cross product requires three-element column vectors"
                    )
            shape = ResultShape(3, 1)
        units = None
        if op in {
            "plus",
            "minus",
            "equal",
            "notEqual",
            "lessThan",
            "lessOrEqual",
            "greaterThan",
            "greaterOrEqual",
        }:
            known = {v.units for v in values if v.units is not None and v.number != 0}
            if len(known) > 1:
                runtime("unit-mismatch", "Operands have incompatible physical dimensions")
            units = next(iter(known)) if len(known) == 1 else None
        elif op in {"mult", "div"} and all(v.units is not None for v in values):
            units = tuple(
                a + (b if op == "mult" else -b) for a, b in zip(values[0].units, values[1].units)
            )
        elif len(values) == 1:
            units = values[0].units
        number = None
        if all(v.number is not None for v in values):
            ns = [v.number for v in values]
            try:
                if op == "plus":
                    number = ns[0] + ns[1]
                elif op == "minus":
                    number = ns[0] - ns[1]
                elif op == "mult":
                    number = ns[0] * ns[1]
                elif op == "div":
                    number = ns[0] / ns[1]
                elif op == "neg":
                    number = -ns[0]
                elif op == "pow":
                    number = math.pow(ns[0], ns[1])
            except (ZeroDivisionError, ValueError, OverflowError):
                pass
        if number is not None and not math.isfinite(number):
            number = None
        if op == "pow" and values[0].units is not None and values[1].number is not None:
            units = tuple(v * values[1].number for v in values[0].units)
        if op == "sqrt" and units is not None:
            units = tuple(v / 2 for v in units)
        if op == "nthRoot" and values[0].number not in (None, 0) and values[1].units is not None:
            units = tuple(v / values[0].number for v in values[1].units)
        return _Value(shape, number=number, units=units)

    def call(self, node, scope, path, **options):
        def runtime(code, message):
            if not options["caught"]:
                self.emit(code, message, path, warning=options["conditional"])

        name = key(node[0])
        args = _arguments(node)
        # root binds its second argument in the expression being solved.
        argument_scope = dict(scope)
        if name == ("root", "") and len(args) == 4 and local(args[1]) == "id":
            argument_scope[key(args[1])] = _SCALAR
        values = [
            self.visit(n, argument_scope, path + f"/argument[{i}]", **options)
            for i, n in enumerate(args)
        ]
        value = scope.get(name)
        signature = None
        if value is not None:
            if value.external:
                self.emit(
                    "external-unchecked",
                    f"{_name(node[0])!r} relies on an external function",
                    path,
                    warning=True,
                )
            if value.function:
                signature = len(value.function.parameters), len(value.function.parameters)
            elif value.shape is not None:
                self.emit("not-callable", f"{_name(node[0])!r} is a value, not a function", path)
                return _UNKNOWN
            else:
                self.emit(
                    "call-unchecked",
                    "Function-valued expression has an unknown signature",
                    path,
                    warning=True,
                )
                return _UNKNOWN
        else:
            signature = _ARITIES.get(name[0]) if name[1] == "" else None
            if signature is None:
                if not options["symbolic"]:
                    self.emit(
                        "undefined-function",
                        f"{_name(node[0])!r} is not a defined or registered function",
                        path,
                    )
                return _UNKNOWN
        low, high = signature
        if (
            len(args) < low
            or (high is not None and len(args) > high)
            or (name == ("root", "") and len(args) == 3)
        ):
            self.emit(
                "function-arity",
                f"{_name(node[0])} expects {low}..{high or 'many'} arguments; received {len(args)}",
                path,
            )
            return _UNKNOWN
        if value is not None:
            info = value.function
            if info.body is not None and any(local(n) in _SOLVERS for n in info.body.iter()):
                self.emit(
                    "runtime-solver",
                    "Parameterized solve block requires Mathcad",
                    path,
                    warning=True,
                )
                return _UNKNOWN
            if info.body is not None and name not in self.active_calls:
                cache_key = (info, tuple(values), tuple(sorted(options.items())))
                if cache_key in self.call_cache:
                    result, diagnostics = self.call_cache[cache_key]
                    for code, severity, message, suffix in diagnostics:
                        self.emit(
                            code, message, path + suffix, warning=severity is Severity.WARNING
                        )
                    return result
                start = len(self.emission_log)
                epoch = self.opaque_call_epoch
                self.active_calls.add(name)
                try:
                    result = self.visit(
                        info.body,
                        {**info.scope, **dict(zip(info.parameters, values))},
                        path + "/function-body",
                        **options,
                    )
                    # Keep a witness for each distinct failure, relocated to every
                    # call site. Repeated nested calls must not expand exponentially.
                    if self.opaque_call_epoch == epoch:
                        diagnostics = {}
                        for d in self.emission_log[start:]:
                            diagnostics.setdefault(
                                (d.code, d.severity, d.message), d.path[len(path) :]
                            )
                        self.call_cache[cache_key] = (
                            result,
                            tuple((*k, v) for k, v in diagnostics.items()),
                        )
                    return result
                finally:
                    self.active_calls.remove(name)
            self.opaque_call_epoch += 1
            self.emit(
                "call-unchecked",
                "Recursive or opaque function result requires Mathcad",
                path,
                warning=True,
            )
            return _UNKNOWN
        n = name[0]
        if n in {"augment", "stack", "lsolve"} and all(v.shape is not None for v in values):
            shapes = [v.shape for v in values]
            if any(not s.matrix for s in shapes):
                runtime("matrix-required", f"{n} requires matrix arguments")
            if n == "augment":
                if len({s.rows for s in shapes}) > 1:
                    runtime("matrix-dimensions", "augment needs equal row counts")
                return _Value(ResultShape(shapes[0].rows, sum(s.columns for s in shapes)))
            if n == "stack":
                if len({s.columns for s in shapes}) > 1:
                    runtime("matrix-dimensions", "stack needs equal column counts")
                return _Value(ResultShape(sum(s.rows for s in shapes), shapes[0].columns))
            if shapes[0].rows != shapes[0].columns or shapes[0].rows != shapes[1].rows:
                runtime(
                    "matrix-dimensions", "lsolve needs a square matrix and matching right-hand side"
                )
            self.emit(
                "runtime-solver",
                "Matrix singularity and conditioning require numeric computation",
                path,
                warning=True,
            )
            return _Value(shapes[1])
        if n in {"sin", "cos", "tan", "exp", "ln", "log"} and values[0].units not in (None, _ZERO):
            runtime("unit-mismatch", f"{n} requires a dimensionless argument")
        if n in {
            "root",
            "rkfixed",
            "Rkadapt",
            "Bulstoer",
            "linterp",
            "interp",
            "lspline",
            "pspline",
            "cspline",
        }:
            self.emit(
                "runtime-function",
                f"{n}: convergence and data constraints require Mathcad",
                path,
                warning=True,
            )
            return _UNKNOWN
        if n in {"min", "max", "norm1", "norm2", "normi"}:
            return _Value(SCALAR, units=values[0].units)
        if n in {
            "rows",
            "cols",
            "length",
            "last",
            "strlen",
            "angle",
            "min",
            "max",
            "norm1",
            "norm2",
            "normi",
        }:
            return _SCALAR
        return replace(values[0], number=None)


def check_worksheet(
    sheet: Worksheet, *, context: ValidationContext | None = None
) -> ValidationReport:
    """Return diagnostics without throwing for semantic errors; no Mathcad execution."""
    return _Analyzer(sheet, context or ValidationContext()).run()
