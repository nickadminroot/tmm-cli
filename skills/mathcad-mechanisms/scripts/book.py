"""Small, non-evaluating notation adapter over the supplied xmcd 0.4 source.

D('V_qBX(φ)', 'diff(X_B(φ), φ)') builds Function/Derivative objects. It does
NOT evaluate Python expressions, perform OCR, or freeze calculated curves.
Underscore is a literal Mathcad subscript; square brackets are array indices.
"""
from __future__ import annotations
import ast
from copy import copy
import html
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'vendor/xmcd/src'))
from xmcd import (  # noqa: E402
    Worksheet, Symbol, LiteralSubscript, Function, Matrix, Number, Expr,
    Derivative, Integral, Range, Given, Solver, SolverKind,
    Program, If, Otherwise, Trace, LineStyle, Marker, TextStyle,
    MathRegion, ResultFormat, MatrixStyle, ResultShape, ValidationContext,
    PageSettings, validate,
)

from xmcd.document import Region  # noqa: E402

class BatchWorksheet(Worksheet):
    """Append-only bulk construction; strict final layout remains upstream.

    Worksheet.add relays out the entire document after every insertion. These
    generators never read intermediate positions, so defer that quadratic work
    to Worksheet.write/to_xml, which still performs strict layout and validation.
    Do not use this class for interactive geometry-dependent edits.
    """
    def add(self, region: Region) -> Region:
        if not isinstance(region, Region):
            raise TypeError('Worksheet accepts Region objects')
        region = copy(region)
        self.regions.append(region)
        return region


def S(name: str) -> Symbol:
    """Keep the book's Greek letters, case and literal subscripts intact."""
    if '_' in name:
        base, sub = name.split('_', 1)
        return Symbol(base, subscript=LiteralSubscript(sub))
    return Symbol(name)


def expression(source: str | int | float | Expr | list) -> Expr:
    if isinstance(source, Expr):
        return source
    if isinstance(source, (int, float)):
        return Number(source)
    if isinstance(source, list):
        return Matrix([[expression(v) for v in row] for row in source]) if source and isinstance(source[0], list) else Matrix.vector([expression(v) for v in source])
    if not isinstance(source, str):
        raise TypeError(f'Unsupported expression: {source!r}')
    try:
        return _ast(ast.parse(source, mode='eval').body)
    except Exception as exc:
        raise ValueError(f'Cannot construct Mathcad expression {source!r}: {exc}') from exc


def _ast(n: ast.AST) -> Expr:
    if isinstance(n, ast.Name):
        return S(n.id)
    if isinstance(n, ast.Constant) and type(n.value) in (int, float):
        return Number(n.value)
    if isinstance(n, (ast.List, ast.Tuple)):
        if n.elts and all(isinstance(row, (ast.List, ast.Tuple)) for row in n.elts):
            return Matrix([[_ast(v) for v in row.elts] for row in n.elts])
        return Matrix.vector([_ast(v) for v in n.elts])
    if isinstance(n, ast.BinOp):
        a, b = _ast(n.left), _ast(n.right)
        ops = {ast.Add: lambda: a+b, ast.Sub: lambda: a-b, ast.Mult: lambda: a*b,
               ast.Div: lambda: a/b, ast.Pow: lambda: a**b, ast.BitAnd: lambda: a&b,
               ast.BitOr: lambda: a|b}
        return ops[type(n.op)]()
    if isinstance(n, ast.UnaryOp):
        a = _ast(n.operand)
        if isinstance(n.op, ast.USub): return -a
        if isinstance(n.op, ast.UAdd): return a
        if isinstance(n.op, (ast.Not, ast.Invert)): return ~a
    if isinstance(n, ast.BoolOp):
        vals = [_ast(v) for v in n.values]
        r = vals[0]
        for v in vals[1:]: r = r & v if isinstance(n.op, ast.And) else r | v
        return r
    if isinstance(n, ast.Compare):
        vals = [_ast(n.left)] + [_ast(c) for c in n.comparators]
        conditions = []
        for a, op, b in zip(vals, n.ops, vals[1:]):
            ops = {ast.Eq: lambda: a.eq(b), ast.NotEq: lambda: a.ne(b),
                   ast.Lt: lambda: a<b, ast.LtE: lambda: a<=b,
                   ast.Gt: lambda: a>b, ast.GtE: lambda: a>=b}
            conditions.append(ops[type(op)]())
        r = conditions[0]
        for c in conditions[1:]: r = r & c
        return r
    if isinstance(n, ast.Subscript):
        indices = n.slice.elts if isinstance(n.slice, ast.Tuple) else [n.slice]
        items = [_ast(i) for i in indices]
        return _ast(n.value)[items[0] if len(items) == 1 else tuple(items)]
    if isinstance(n, ast.Attribute) and n.attr == 'T':
        return _ast(n.value).T
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and not n.keywords:
        name = n.func.id
        args = [_ast(a) for a in n.args]
        if name == 'sqrt': return args[0].sqrt()
        if name == 'abs': return abs(args[0])
        if name == 'vec': return Matrix.vector(args)
        if name == 'diff':
            degree = int(n.args[2].value) if len(n.args) == 3 else 1
            return Derivative(args[0], args[1], degree=degree)
        if name == 'intg': return Integral(args[0], args[1], args[2], args[3])
        if name == 'rng':
            return Range(args[0], args[1], second=args[2] if len(args) == 3 else None)
        if name == 'col': return args[0].column(args[1])
        if name == 'vectorize': return args[0].vectorize()
        solvers = {'Find': SolverKind.FIND, 'Minerr': SolverKind.MINERR,
                   'Minimize': SolverKind.MINIMIZE, 'Maximize': SolverKind.MAXIMIZE}
        if name in solvers: return Solver(solvers[name])(*args)
        return S(name)(*args)
    raise ValueError(f'Unsupported syntax: {ast.dump(n)}')


def lhs(source: str) -> Expr:
    n = ast.parse(source, mode='eval').body
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
        if not all(isinstance(a, ast.Name) for a in n.args):
            raise ValueError('Function parameters must be names')
        return Function(S(n.func.id), [S(a.id) for a in n.args])
    return expression(source)


class Book:
    """One top-to-bottom worksheet with source-page and provenance tags.

    The book's two-column print layout is an editorial montage; its right
    column can depend on the bottom of its left column. Native Mathcad must
    keep these definitions in calculation order, not a misleading two-column
    imitation. All expressions are editable, including graph traces.
    """
    def __init__(self, slug: str, title: str):
        self.slug, self.title = slug, title
        self.w = BatchWorksheet(title, author='Учебные фрагменты ТММ / ручная транскрипция',
                           origin=0, tolerance=1e-7, constraint_tolerance=1e-7,
                           font_size=10, result_format=ResultFormat(precision=6),
                           page=PageSettings(margin_left=28, margin_right=28,
                                             margin_top=28, margin_bottom=28))
        self.entries: list[dict[str, Any]] = []
        self.page_number = 0
        self.counter = 0
        self.external_functions = []
        self.text(title, heading=True)
        self.text('Числа в формулах — СИ; углы — радианы, вывод углов через deg. '
                  'Это связанный учебный фрагмент, не готовое решение произвольного варианта. '
                  'Контроли «Скан» переписаны с печати, а не получены пересчётом этого XMCD.')

    def _record(self, kind: str, **data) -> str:
        self.counter += 1
        tag = f'p{self.page_number}-{self.counter:04d}-{kind}'
        self.entries.append(dict(page=self.page_number, print_page=self.page_number-1,
                                 tag=tag, kind=kind, **data))
        return tag

    def page(self, number: int, title: str = ''):
        if not 112 <= number <= 155: raise ValueError(number)
        self.page_number = number
        self.text(f'Страница {number-1} книги · JPG {number}. {title}', heading=True)

    def text(self, text: str, heading: bool = False, provenance: str = 'scan'):
        tag = self._record('heading' if heading else 'text', text=text, provenance=provenance)
        self.w.text(text, width=520, style=TextStyle.HEADING_2 if heading else TextStyle.NORMAL, tag=tag)

    def note(self, text: str):
        self.text('Примечание к переносу: '+text, provenance='editorial')

    def D(self, name: str, value, *, why: str | None = None, height: float | None = None):
        tag = self._record('define', lhs=name, rhs=str(value), provenance='scan' if why is None else 'adapted', reason=why)
        self.w.define(lhs(name), expression(value), tag=tag, width=520, **({} if height is None else {'height': height}))
        if why: self.note(why)

    def E(self, value: str, reference: str | None = None, *, shape=None, table=False):
        tag = self._record('evaluate', expression=value, printed=reference)
        kw = {'width': 520, 'tag': tag}
        kw['result_shape'] = ResultShape(*shape) if shape else ResultShape.scalar()
        if table: kw['result_format'] = ResultFormat(precision=6, matrix_style=MatrixStyle.TABLE, table_min_rows=14)
        self.w.evaluate(expression(value), **kw)
        if reference is not None:
            self.text('Скан: '+value+' = '+reference, provenance='printed-control')

    def given(self, *constraints: str):
        tag = self._record('given', constraints=list(constraints))
        self.w.math(Given(), tag=tag)
        for c in constraints:
            self.w.math(expression(c), width=520, tag=self._record('constraint', expression=c))

    def solve(self, names: list[str], *, result='U', args: list[str] | None = None):
        """Store Find output explicitly; never substitute its printed numbers."""
        if args:
            self.D(f'{result}({",".join(args)})', f'Find({",".join(names)})')
            for j, n in enumerate(names): self.D(f'{n}({",".join(args)})', f'{result}({",".join(args)})' + (f'[{j}]' if len(names)>1 else ''))
        else:
            self.D(result, f'Find({",".join(names)})')
            for j, n in enumerate(names): self.D(n, f'{result}[{j}]' if len(names)>1 else result)

    def piece(self, name: str, cases: list[tuple[str, str]], default='0', why=None):
        p = Program(*[If(expression(cond), expression(val)) for val, cond in cases], Otherwise(expression(default)))
        tag = self._record('piecewise', lhs=name, cases=cases, default=default,
                           provenance='scan' if why is None else 'adapted', reason=why)
        self.w.define(lhs(name), p, tag=tag, width=520)
        if why: self.note(why)

    def plot(self, *pairs: tuple[str, str], caption='', polar=False, bounds=None,
             x_bounds=None, y_bounds=None, markers=False):
        """Add an editable graph and optionally fix its axis bounds.

        Classic Mathcad rounds automatic angular bounds outward: a data range
        ending at 360 degrees can be displayed as 0…400. Use ``x_bounds`` for
        ranges derived from π (for example ``(0, 360)`` or ``(0, 720)``).
        ``width`` below is only the region's pixel width and does not fix this.
        """
        if bounds is not None and (x_bounds is not None or y_bounds is not None):
            raise ValueError('Use bounds or x_bounds/y_bounds, not both')
        if bounds is None and (x_bounds is not None or y_bounds is not None):
            bounds = (x_bounds or (None, None), y_bounds or (None, None))
        styles = list(LineStyle)
        tag = self._record('polar' if polar else 'plot', traces=pairs, caption=caption)
        if caption: self.w.text(caption, width=520, tag=tag+'-caption')
        traces = [Trace(expression(x), expression(y), style=styles[i % len(styles)],
                        marker=Marker.CIRCLE if markers else Marker.NONE) for i,(x,y) in enumerate(pairs)]
        kw = dict(width=430, height=270 if not polar else 370, left=24, tag=tag,
                  x_grid=True, y_grid=True)
        if bounds:
            kw.update(x_bounds=bounds[0], y_bounds=bounds[1])
        (self.w.polar_plot if polar else self.w.plot)(*traces, **kw)

    def figure(self, ident: str, caption: str):
        """Keep a visual-reference marker without embedding an untested picture.

        The minimal skill ships the original page photographs, not cropped
        figure files. Coordinate schemes remain editable plots.
        """
        tag = self._record('figure', visual_reference='assets/scans/', caption=caption)
        self.w.text(caption + ' [визуальный эталон: assets/scans/page_*.jpg]', tag=tag, width=520)

    def reference(self, text: str):
        self.text('Скан: '+text, provenance='printed-control')

    def historical(self, text: str, reason: str):
        self.text('Исходная запись на скане: '+text, provenance='original-suspect')
        self.note(reason)

    def sample(self, variable: str, stop: str, count: int, functions: list[tuple[str,str]], spline='lspline'):
        """Same grid -> array -> spline -> function redefinition as in the book."""
        self.D('N', count)
        self.D('i', 'rng(0, N)')
        self.D('Δ'+variable, f'({stop})/N')
        self.D(f'A_{variable}[i]', f'Δ{variable}*i')
        for array, func in functions:
            self.D(f'{array}[i]', f'{func}(A_{variable}[i])')
            self.D('c'+array.removeprefix('A_').replace('_',''), f'{spline}(A_{variable}, {array})')
            self.D(f'{func}({variable})', f'interp(c{array.removeprefix("A_").replace("_", "")}, A_{variable}, {array}, {variable})')

    def derivative(self, name: str, target: str, variable='φ', degree=1):
        self.D(f'{name}({variable})', f'diff({target}({variable}), {variable}, {degree})')

    def write(self, output: Path | str | None = None):
        out = Path(output) if output else ROOT/'output'
        out.mkdir(parents=True, exist_ok=True)
        context = ValidationContext(functions=tuple(self.external_functions))
        report = self.w.check(context=context)
        record = dict(slug=self.slug, title=self.title,
                      errors=[str(d) for d in report.errors], warnings=[str(d) for d in report.warnings],
                      region_count=len(self.w.regions), native_mathcad_recalculated=False,
                      pages=sorted({e['page'] for e in self.entries if e['page']}))
        (out/(self.slug+'.validation.json')).write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        if report.errors:
            report.raise_for_errors()
        path = self.w.write(out/(self.slug+'.xmcd'), context=context)
        (out/(self.slug+'.transcription.json')).write_text(json.dumps(self.entries,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        return path


def cli(build):
    import argparse
    p = argparse.ArgumentParser(description=build.__doc__)
    p.add_argument('--out', type=Path, default=ROOT/'output')
    args = p.parse_args()
    b = build()
    print(b.write(args.out))
