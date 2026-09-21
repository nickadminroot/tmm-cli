"""Conservative expression geometry and result shapes, without executing Mathcad."""

from __future__ import annotations

import math
from dataclasses import dataclass


def local(node):
    return node.tag.rsplit("}", 1)[-1]


def key(node):
    return node.text or "", node.get("subscript", "")


class LayoutError(ValueError):
    """An automatic result size cannot be determined without computation."""


@dataclass(frozen=True)
class ResultShape:
    rows: int = 1
    columns: int = 1
    matrix: bool = True

    def __post_init__(self):
        if any(type(n) is not int or n < 1 for n in (self.rows, self.columns)):
            raise ValueError("Result dimensions must be positive integers")

    @classmethod
    def scalar(cls):
        return cls(matrix=False)


SCALAR = ResultShape.scalar()


@dataclass(frozen=True)
class Metrics:
    width: float
    above: float
    below: float

    @property
    def height(self):
        return self.above + self.below


def join(parts, gap=0):
    return Metrics(
        sum(p.width for p in parts) + gap * max(0, len(parts) - 1),
        max((p.above for p in parts), default=0),
        max((p.below for p in parts), default=0),
    )


def measure(node, size=10):
    """Measure the serialized expression, including the serializer's grouping."""
    tag = local(node)
    atom = Metrics(max(1, len(node.text or "")) * size * 0.65, size, size * 0.5)
    if tag in {"id", "real", "imag", "str", "placeholder"}:
        if node.get("subscript"):
            return Metrics(atom.width + len(node.get("subscript")) * size * 0.55, atom.above, size)
        return atom
    if tag == "matrix":
        rows, cols = int(node.get("rows")), int(node.get("cols"))
        cells = [measure(n, size) for n in node]
        heights = [max(cells[c * rows + r].height for c in range(cols)) for r in range(rows)]
        height = sum(heights) + (rows - 1) * size * 0.4 + size
        width = sum(max(cells[c * rows + r].width for r in range(rows)) for c in range(cols))
        return Metrics(width + (cols + 1) * size, height / 2, height / 2)
    if tag == "apply" and len(node):
        op, args = local(node[0]), list(node)[1:]
        if op == "div":
            a, b = [measure(n, size) for n in args]
            return Metrics(
                max(a.width, b.width) + size * 0.6, a.height + size * 0.4, b.height + size * 0.4
            )
        if op in {"pow", "indexer", "matcol"}:
            a, b = measure(args[0], size), measure(args[1], size * 0.8)
            return Metrics(
                a.width + b.width + size * 0.3,
                a.above + b.height * 0.9 if op != "indexer" else a.above,
                a.below + b.height * 0.9 if op == "indexer" else a.below,
            )
        if op in {"derivative", "integral", "summation", "product"}:
            body = measure(args[0][-1], size)  # lambda body
            decorations = [measure(n, size * 0.85) for n in args[1:]]
            bound = max((p.height for p in decorations), default=size)
            return Metrics(
                body.width + size * 3 + sum(p.width for p in decorations),
                max(body.above, size * 1.6 + bound * 0.65),
                max(body.below, size * 1.6 + bound * 0.65),
            )
        parts = [measure(n, size) for n in args]
        base = join(parts, size * 0.8)
        if op in {"sqrt", "nthRoot", "vectorize", "conjugate"}:
            return Metrics(base.width + size, base.above + size * 0.65, base.below + size * 0.2)
        if op in {"transpose", "factorial"}:
            return Metrics(base.width + size, base.above + size * 0.8, base.below)
        return Metrics(base.width + size * max(1, len(args)), base.above, base.below)
    if tag == "program":
        lines = [measure(n, size) for n in node]
        h = sum(p.height for p in lines) + size * 0.6 * len(lines)
        return Metrics(max(p.width for p in lines) + size, h / 2, h / 2)
    if tag in {"ifThen", "otherwise", "for", "while", "return", "tryCatch"}:
        parts = [measure(n, size) for n in node]
        m = join(parts, size)
        return Metrics(m.width + size * 4, m.above, m.below)
    m = join([measure(n, size) for n in node], size * 0.7)
    if tag == "parens":
        return Metrics(m.width + size, m.above + size * 0.2, m.below + size * 0.2)
    return m if len(node) else atom


class ShapeContext:
    """Track declarations and dimensions; never run user expressions or solvers."""

    def __init__(self, origin=0):
        self.origin = origin
        self.definitions = {}
        self.functions = {}
        self.shapes = {}
        self.ranges = {}

    def number(self, node, seen=frozenset()):
        tag = local(node)
        if tag == "real":
            return float(node.text)
        if tag == "id":
            k = key(node)
            if k in seen:
                return None
            if k in self.definitions:
                return self.number(self.definitions[k], seen | {k})
            return {"π": math.pi, "pi": math.pi, "ORIGIN": self.origin}.get(k[0])
        if tag == "parens":
            return self.number(node[0], seen)
        if tag == "apply":
            values = [self.number(n, seen) for n in list(node)[1:]]
            if any(v is None for v in values):
                return None
            op = local(node[0])
            try:
                if op == "neg":
                    return -values[0]
                a, b = values
                if op == "plus":
                    return a + b
                if op == "minus":
                    return a - b
                if op == "mult":
                    return a * b
                if op == "div":
                    return a / b
            except (ValueError, ZeroDivisionError):
                return None
        return None

    def declare(self, node):
        if local(node) not in {"define", "globalDefine"}:
            return
        lhs, rhs = node
        if local(lhs) == "id":
            # Resolve before assignment: a := a + 1 uses the preceding a.
            self.shapes[key(lhs)] = self.infer(rhs)
            self.definitions[key(lhs)] = rhs
            if local(rhs) == "range":
                shape = self.infer(rhs)
                self.ranges[key(lhs)] = shape.rows if shape is not None else None
            else:
                self.ranges.pop(key(lhs), None)
        elif local(lhs) == "function":
            self.functions[key(lhs[0])] = (list(lhs[1]), rhs)
        elif local(lhs) == "apply" and local(lhs[0]) == "indexer" and local(lhs[1]) == "id":
            indexes = list(lhs[2]) if local(lhs[2]) == "sequence" else [lhs[2]]
            sizes = []
            for n in indexes:
                target = self.definitions.get(key(n), n) if local(n) == "id" else n
                if local(target) == "range":
                    target = target[-1]
                value = self.number(target)
                if value is None:
                    return
                sizes.append(int(value) - self.origin + 1)
            if len(sizes) == 1:
                sizes.append(1)
            old = self.shapes.get(key(lhs[1]))
            if old:
                sizes = [max(sizes[0], old.rows), max(sizes[1], old.columns)]
            if min(sizes) > 0:
                self.shapes[key(lhs[1])] = ResultShape(*sizes)

    def range_result(self, node):
        """Find free range variables: repeated scalar evaluations form a result table.

        Numeric integrals/sums and bracketed root bind their own variables. A
        derivative instead evaluates at the outer variable's range of points.
        """
        if not self.ranges and local(node) != "range" and node.find(".//{*}range") is None:
            return False, None
        found = {}

        def visit(n, bound=frozenset()):
            tag = local(n)
            if tag == "id":
                name = key(n)
                if name not in bound and name in self.ranges:
                    found[name] = self.ranges[name]
                return
            if tag == "range":
                shape = self.infer(n)
                found[id(n)] = shape.rows if shape is not None else None
                return
            if tag == "apply" and len(n):
                op = local(n[0])
                if op in {"integral", "summation", "product"}:
                    variables = frozenset(key(v) for v in n[1][0])
                    visit(n[1][-1], bound | variables)
                    for decoration in list(n)[2:]:
                        visit(decoration, bound)
                    return
                if op == "id":
                    args = list(n[1]) if local(n[1]) == "sequence" else [n[1]]
                    if n[0].text == "root" and len(args) == 4 and local(args[1]) == "id":
                        visit(args[0], bound | {key(args[1])})
                        for arg in args[2:]:
                            visit(arg, bound)
                        return
                    # The callee is a function name, not a range argument.
                    for arg in args:
                        visit(arg, bound)
                    return
            for part in n:
                visit(part, bound)

        visit(node)
        counts = [count for count in found.values() if count is not None]
        return bool(found), math.prod(counts) if counts else None

    def infer(self, node, bindings=None, seen=frozenset()):
        bindings = {} if bindings is None else bindings
        tag = local(node)
        if tag in {"real", "imag", "str", "placeholder"}:
            return SCALAR
        if tag == "id":
            k = key(node)
            if k in bindings:
                return bindings[k]
            if k in self.shapes:
                return self.shapes[k]
            if k[0] in {
                "π",
                "pi",
                "e",
                "i",
                "j",
                "deg",
                "rad",
                "m",
                "mm",
                "s",
                "kg",
                "N",
                "Pa",
                "ORIGIN",
                "TOL",
                "CTOL",
            }:
                return SCALAR
            return None
        if tag == "matrix":
            return ResultShape(int(node.get("rows")), int(node.get("cols")))
        if tag in {"parens", "eval", "symEval", "return", "otherwise"}:
            return self.infer(node[0], bindings, seen)
        if tag == "program":
            if any(local(part) in {"for", "while"} for part in node.iter()):
                # A loop can grow an array; dimensions require a caller-supplied shape.
                return None
            bindings = dict(bindings)
            for statement in node:
                if local(statement) == "localDefine" and local(statement[0]) == "id":
                    bindings[key(statement[0])] = self.infer(statement[1], bindings, seen)
            candidates = [self.infer(node[-1], bindings, seen)]
            for statement in node:
                if local(statement) == "ifThen":
                    candidates.append(self.infer(statement[1], bindings, seen))
                for returned in statement.iter():
                    if local(returned) == "return":
                        candidates.append(self.infer(returned[0], bindings, seen))
            if any(shape is None for shape in candidates):
                return None
            return ResultShape(
                max(s.rows for s in candidates),
                max(s.columns for s in candidates),
                any(s.matrix for s in candidates),
            )
        if tag == "ifThen":
            return self.infer(node[1], bindings, seen)
        if tag == "tryCatch":
            a, b = [self.infer(n, bindings, seen) for n in node]
            return a if a == b else None
        if tag == "range":
            first = node[0][0] if local(node[0]) == "sequence" else node[0]
            start, stop = self.number(first), self.number(node[-1])
            second = self.number(node[0][1]) if local(node[0]) == "sequence" else None
            if start is None or stop is None:
                return None
            step = 1 if second is None else second - start
            if step == 0 or (stop - start) / step < 0:
                return None
            return ResultShape(math.floor((stop - start) / step + 1e-9) + 1, 1)
        if tag != "apply":
            return None
        op = local(node[0])
        args = list(node)[1:]
        if op in {"Find", "Minerr"}:
            return SCALAR if local(args[0]) != "sequence" else ResultShape(len(args[0]), 1)
        if op in {"Minimize", "Maximize"}:
            return SCALAR
        if op == "Odesolve":
            return SCALAR
        if op in {"derivative", "integral", "summation", "product"}:
            local_bindings = {**bindings, **{key(v): SCALAR for v in args[0][0]}}
            return self.infer(args[0][-1], local_bindings, seen) or SCALAR
        if op == "indexer":
            return SCALAR
        if op in {
            "equal",
            "notEqual",
            "lessThan",
            "lessOrEqual",
            "greaterThan",
            "greaterOrEqual",
            "determinant",
            "vectorSum",
        }:
            return SCALAR
        if op == "id":
            name = node[0].text
            k = key(node[0])
            args = list(args[0]) if local(args[0]) == "sequence" else args
            shapes = [self.infer(a, bindings, seen) for a in args]
            definition = self.definitions.get(k)
            if (
                definition is not None
                and local(definition) == "apply"
                and local(definition[0]) == "Odesolve"
            ):
                return SCALAR
            if k in self.functions and k not in seen:
                params, body = self.functions[k]
                return self.infer(
                    body, {**bindings, **{key(p): s for p, s in zip(params, shapes)}}, seen | {k}
                )
            if name in {
                "rows",
                "cols",
                "length",
                "last",
                "root",
                "angle",
                "strlen",
                "linterp",
                "interp",
                "min",
                "max",
                "mean",
                "norm1",
                "norm2",
                "normi",
            }:
                return SCALAR
            if name in {"rkfixed", "Rkadapt", "Bulstoer"} and len(args) >= 4:
                steps = self.number(args[3])
                initial = shapes[0]
                if steps is not None and initial:
                    return ResultShape(int(steps) + 1, initial.rows + 1)
            if name == "lsolve" and len(shapes) > 1:
                return shapes[1]
            if name in {"augment", "stack"} and all(shapes):
                return (
                    ResultShape(max(s.rows for s in shapes), sum(s.columns for s in shapes))
                    if name == "augment"
                    else ResultShape(sum(s.rows for s in shapes), max(s.columns for s in shapes))
                )
            if name in {
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
                "log",
                "abs",
                "floor",
                "ceil",
                "round",
                "Re",
                "Im",
            }:
                return shapes[0]
            return None
        shapes = [self.infer(a, bindings, seen) for a in args]
        if op == "transpose" and shapes[0]:
            return ResultShape(shapes[0].columns, shapes[0].rows)
        if op == "matcol" and shapes[0]:
            return ResultShape(shapes[0].rows, 1)
        if op in {"absval", "sqrt", "nthRoot", "log", "neg", "factorial", "conjugate"}:
            return shapes[-1]
        if op == "crossProduct":
            return ResultShape(3, 1)
        if op == "vectorize":
            # Vectorization preserves the largest operand's matrix shape.
            operands = list(args[0])[1:] if local(args[0]) == "apply" else args
            values = [self.infer(a, bindings, seen) for a in operands]
            if all(values):
                return max(values, key=lambda s: s.rows * s.columns)
        if all(shapes):
            matrices = [s for s in shapes if s.matrix]
            if op == "mult" and len(matrices) == 2:
                return ResultShape(matrices[0].rows, matrices[1].columns)
            return max(shapes, key=lambda s: s.rows * s.columns)
        return None


def result_metrics(shape, size, table=False, table_min_rows=20):
    if not shape.matrix:
        return Metrics(size * 10, size, size * 0.5)
    # Include table header / scroll bar and enough line height for formatted numbers.
    rows = max(shape.rows, table_min_rows) if table else shape.rows
    height = (rows + (2 if table else 0)) * size * 1.8 + size
    return Metrics(shape.columns * size * 9 + size * 2, height / 2, height / 2)


def math_metrics(expression, context, size, shape=None, table=False, table_min_rows=20):
    node = expression.to_xml()
    metrics = measure(node, size)
    if local(node) == "symEval":
        raise LayoutError("Symbolic result geometry is unknown; provide an explicit height")
    if local(node) == "eval":
        range_table, range_rows = context.range_result(node[0])
        inferred = shape if shape is not None else context.infer(node[0])
        table = table or range_table
        if range_table:
            # Even g(k) := 7 produces one value for each range point when evaluated.
            inferred = ResultShape(
                max(range_rows or 1, inferred.rows if inferred is not None else 1),
                inferred.columns if inferred is not None else 1,
            )
        if inferred is None and table:
            inferred = ResultShape(table_min_rows, 1)
        if inferred is None:
            raise LayoutError(
                "Result shape is unknown; provide result_shape=ResultShape(...) "
                "(or ResultShape.scalar()), or an explicit height"
            )
        metrics = join([metrics, result_metrics(inferred, size, table, table_min_rows)], size)
    return metrics
