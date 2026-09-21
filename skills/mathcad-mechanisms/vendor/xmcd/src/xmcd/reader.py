"""Read classic XMCD as editable objects while preserving original XML extensions."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from lxml import etree as ET

from . import expressions as e
from .document import (
    NS,
    Area,
    MathRegion,
    PageBreak,
    PageSettings,
    Region,
    ResultFormat,
    SerializationContext,
    TextRegion,
    Worksheet,
    _place,
    element,
)
from .layout import LayoutError, ShapeContext, local
from .types import (
    DefinitionKind,
    LiteralSubscript,
    MatrixStyle,
    NumberFormat,
    OperatorKind,
    Orientation,
    SolverKind,
    SolverMethod,
    TextStyle,
)
from .validation import parse_xml, validate


@dataclass(frozen=True, eq=False)
class OpaqueExpression(e.Expr):
    """An unsupported expression retained as XML, without claiming editable semantics."""

    xml: bytes

    def to_xml(self):
        return parse_xml(self.xml)


@dataclass
class OpaqueRegion(Region):
    """Unsupported region (including imported binary graphs), preserved in its document."""

    xml: bytes

    @property
    def kind(self):
        node = parse_xml(self.xml)
        return local(node[0]) if len(node) else "unknown"

    def content_xml(self, context):
        return deepcopy(parse_xml(self.xml)[0])


def read_expression(node) -> e.Expr:
    expression = _read_expression(node)
    source = deepcopy(node)
    for cached in list(source.iter()):
        if local(cached) in {"result", "symResult"} and cached.getparent() is not None:
            cached.getparent().remove(cached)
        for name in ("error", "warning", "error-id", "warning-id"):
            cached.attrib.pop(name, None)
    object.__setattr__(expression, "_source_xml", ET.tostring(source, with_tail=False))
    return expression


def _read_expression(node) -> e.Expr:
    """Parse supported syntax; retain other syntax as OpaqueExpression."""

    def read(n):
        return read_expression(n)

    def opaque():
        return OpaqueExpression(ET.tostring(node, with_tail=False))

    tag = local(node)
    try:
        if tag == "real":
            return e.Number(Decimal(node.text))
        if tag == "imag":
            return e.Imaginary(Decimal(node.text))
        if tag == "str":
            return e.String(node.text or "")
        if tag == "id":
            return e.Symbol(
                node.text,
                LiteralSubscript(node.get("subscript")) if node.get("subscript") else None,
            )
        if tag == "placeholder":
            return e.Placeholder()
        if tag == "parens":
            return e.Parens(read(node[0]))
        if tag == "sequence":
            return e.Sequence(*(read(n) for n in node))
        if tag == "matrix":
            rows, cols = int(node.get("rows")), int(node.get("cols"))
            if len(node) != rows * cols:
                return opaque()
            return e.Matrix([[read(node[c * rows + r]) for c in range(cols)] for r in range(rows)])
        if tag == "function":
            return e.Function(read(node[0]), [read(n) for n in node[1]])
        if tag in {"define", "globalDefine", "localDefine"}:
            return e.Define(
                read(node[0]),
                read(node[1]),
                kind={
                    "define": DefinitionKind.NORMAL,
                    "globalDefine": DefinitionKind.GLOBAL,
                    "localDefine": DefinitionKind.LOCAL,
                }[tag],
            )
        if tag == "eval":
            unit = node.find("ml:unitOverride", NS)
            return e.Evaluate(
                read(node[0]),
                read(unit[0])
                if unit is not None and len(unit) and local(unit[0]) != "placeholder"
                else None,
            )
        if tag == "symEval":
            return e.Symbolic(
                read(node[0]), tuple(read(n[0]) for n in node if local(n) == "command" and len(n))
            )
        if tag == "range":
            if local(node[0]) == "sequence":
                return e.Range(read(node[0][0]), read(node[1]), second=read(node[0][1]))
            return e.Range(read(node[0]), read(node[1]))
        if tag == "program":
            return e.Program(*(read(n) for n in node))
        constructors = {
            "ifThen": e.If,
            "otherwise": e.Otherwise,
            "for": e.For,
            "while": e.While,
            "return": e.Return,
            "break": e.Break,
            "continue": e.Continue,
            "tryCatch": e.TryCatch,
        }
        if tag in constructors:
            return constructors[tag](*(read(n) for n in node))
        if tag in {s.value for s in SolverKind}:
            method = node.get("method")
            return e.Solver(SolverKind(tag), SolverMethod(method) if method else None)
        if tag == "apply":
            op = local(node[0])
            args = list(node)[1:]
            if op in {v.value for v in OperatorKind}:
                return e.Operator(OperatorKind(op), *(read(n) for n in args))
            if op in {"integral", "derivative", "summation", "product"}:
                if len(args[0][0]) != 1:
                    return opaque()
                body, variable = read(args[0][-1]), read(args[0][0][0])
                if op == "derivative":
                    return e.Derivative(body, variable, read(args[1][0]) if len(args) > 1 else 1)
                constructor = {"integral": e.Integral, "summation": e.Sum, "product": e.Product}[op]
                return (
                    constructor(body, variable, *(read(n) for n in args[1]))
                    if len(args) > 1
                    else constructor(body, variable)
                )
            arguments = list(args[0]) if len(args) == 1 and local(args[0]) == "sequence" else args
            if op == "id" or op in {s.value for s in SolverKind}:
                return e.Call(read(node[0]), *(read(n) for n in arguments))
    except (ValueError, TypeError, IndexError, KeyError, ArithmeticError):
        return opaque()
    return opaque()


def _format(node):
    if node is None:
        return None
    number = next((n for n in node if local(n) in {v.value for v in NumberFormat}), None)
    matrix = node.find("ws:matrix", NS)
    try:
        return ResultFormat(
            precision=int(number.get("precision", "6")) if number is not None else 6,
            notation=NumberFormat(local(number)) if number is not None else NumberFormat.GENERAL,
            matrix_style=MatrixStyle(matrix.get("display-style", "auto"))
            if matrix is not None
            else MatrixStyle.AUTO,
        )
    except ValueError:
        return None


def _stamp(region):
    basic = (
        region.left,
        region.top,
        region.width,
        region.height,
        region.tag,
        region.border,
        region._axis,
    )
    if isinstance(region, MathRegion):
        return basic + (
            ET.tostring(e.serialize_expression(region.expression)),
            region.result_format,
            region.disabled,
        )
    if isinstance(region, TextRegion):
        return basic + (region.text, region.style)
    if isinstance(region, Area):
        return basic + (region.name, region.collapsed)
    return basic + (region.xml if isinstance(region, OpaqueRegion) else None,)


def _patch_settings(source, before, after):
    """Update only model-owned properties that the caller changed."""
    for name, value in after.attrib.items():
        if before.get(name) != value:
            source.set(name, value)
    if before.text != after.text:
        source.text = after.text
    number_tags = {v.value for v in NumberFormat}
    old_number = next((n for n in before if local(n) in number_tags), None)
    new_number = next((n for n in after if local(n) in number_tags), None)
    if old_number is not None and new_number is not None and old_number.tag != new_number.tag:
        target = next((n for n in source if n.tag == old_number.tag), None)
        if target is not None:
            source.replace(target, deepcopy(new_number))
    for new in after:
        match = lambda n, new=new: n.tag == new.tag and n.get("name") == new.get("name")
        old = next((n for n in before if match(n)), None)
        if old is None:
            continue
        target = next((n for n in source if match(n)), None)
        if target is None:
            if ET.tostring(old) != ET.tostring(new):
                source.append(deepcopy(new))
        else:
            _patch_settings(target, old, new)


def _xml_state(node):
    """Compare XML content independent of namespace prefix placement."""
    return (node.tag, dict(node.attrib), node.text, node.tail, tuple(map(_xml_state, node)))


class LoadedWorksheet(Worksheet):
    """Worksheet retaining original document settings, XML and binary attachments."""

    def _read_regions(self, parent, dx=0, dy=0):
        result = []
        for node in parent:
            if local(node) != "region":
                continue
            options = {
                name: float(node.get(name, "0")) for name in ("left", "top", "width", "height")
            }
            options["left"] -= dx
            options["top"] -= dy
            options.update(tag=node.get("tag", ""), border=node.get("show-border") == "true")
            contents = [n for n in node if local(n) not in {"rendering", "renderingInfo"}]
            content = contents[0] if contents else None
            kind = local(content) if content is not None else ""
            if kind == "math" and len(content):
                region = MathRegion(
                    read_expression(content[0]),
                    result_format=_format(content.find("ws:resultFormat", NS)),
                    disabled=content.get("disable-calc") == "true",
                    **options,
                )
            elif kind == "text" and all(local(n) == "p" and not len(n) for n in content):
                styles = {n.get("style", "Normal") for n in content}
                if len(styles) == 1 and next(iter(styles)) in {s.value for s in TextStyle}:
                    region = TextRegion(
                        "\n".join(n.text or "" for n in content),
                        style=TextStyle(next(iter(styles))),
                        **options,
                    )
                else:
                    region = OpaqueRegion(ET.tostring(node, with_tail=False), **options)
            elif kind == "area":
                collapsed = content.get("is-collapsed") == "true"
                children = self._read_regions(
                    content,
                    0 if collapsed else float(node.get("left")),
                    0 if collapsed else float(node.get("top")),
                )
                region = Area(content.get("name", ""), children, collapsed, **options)
            elif kind == "pageBreak":
                region = PageBreak(**options)
            else:
                region = OpaqueRegion(ET.tostring(node, with_tail=False), **options)
            region._axis = float(node.get("align-y", node.get("top", "0"))) - float(
                node.get("top", "0")
            )
            self._sources[id(region)] = (deepcopy(node), _stamp(region))
            result.append(region)
        return result

    def layout(self, *, strict=True):
        # Imported coordinates and bounds are explicit until reflow is requested.
        # Area child identity must stay stable for source-node association.
        context = ShapeContext(self.origin)

        def globals_(regions):
            for region in regions:
                if isinstance(region, Area):
                    globals_(region.regions)
                elif isinstance(region, MathRegion):
                    node = region.expression.to_xml()
                    if local(node) == "globalDefine":
                        context.declare(node)

        globals_(self.regions)

        def place(regions, start):
            cursor = start
            for region in regions:
                if isinstance(region, Area):
                    if region._auto_top:
                        region.top = cursor
                    bottom = place(region.regions, self.font_size * 2)
                    if region._auto_height:
                        region.height = bottom + self.font_size * 2
                else:
                    _place(region, context, self.font_size, cursor, self.result_format, strict)
                cursor = max(
                    cursor, region.top + region.height + getattr(region, "_flow_extra", 0) + 12
                )
            return cursor

        self._cursor = place(self.regions, 12)

    def check(self, *, context=None):
        from .semantic import Diagnostic, Severity, ValidationReport

        report = super().check(context=context)
        warnings = []

        def inspect(regions):
            for index, region in enumerate(regions, 1):
                if isinstance(region, Area):
                    inspect(region.regions)
                elif isinstance(region, OpaqueRegion):
                    warnings.append(
                        Diagnostic(
                            "opaque-region",
                            Severity.WARNING,
                            "Imported content is preserved but cannot be semantically checked",
                            index,
                            region.tag,
                            "content",
                        )
                    )

        inspect(self.regions)
        return ValidationReport(report.diagnostics + tuple(warnings))

    def reflow(self):
        """Arrange regions vertically; keep existing bounds for opaque/unknown content."""
        context = ShapeContext(self.origin)

        def arrange(regions, start):
            cursor = start
            for region in regions:
                region._auto_top = True
                region.top = cursor
                if isinstance(region, Area):
                    bottom = arrange(region.regions, self.font_size * 2)
                    region.height = bottom + self.font_size * 2
                elif not isinstance(region, OpaqueRegion):
                    old = (region.height, region._axis)
                    region._auto_height = True
                    try:
                        _place(region, context, self.font_size, cursor, self.result_format)
                    except LayoutError:
                        region._auto_height = False
                        region.height, region._axis = old
                        if isinstance(region, MathRegion):
                            context.declare(region.expression.to_xml())
                cursor = region.top + region.height + getattr(region, "_flow_extra", 0) + 12
            return cursor

        self._cursor = arrange(self.regions, 12)
        return self

    def to_xml(self):
        self.layout()
        root = deepcopy(self._source_root)
        _patch_settings(root.find("ws:settings", NS), self._settings_before, self._settings())
        for field, value in (("title", self.title), ("author", self.author)):
            if value != self._metadata_before[field]:
                user = root.find("ws:metadata/ws:userData", NS)
                if user is None:
                    metadata = root.find("ws:metadata", NS)
                    if metadata is None:
                        metadata = element("metadata", root)
                    user = element("userData", metadata)
                node = user.find("ws:" + field, NS)
                if node is None:
                    node = element(field, user)
                node.text = value
        ids = [int(n.get("region-id")) for n in root.findall(".//ws:region", NS)]
        ids += [
            int(n.get(a))
            for n in root.findall(".//ws:area", NS)
            for a in ("top-lock-id", "bottom-lock-id")
            if n.get(a)
        ]
        binary = root.find("ws:binaryContent", NS)
        binary_max = (
            max((int(n.get("item-id")) for n in binary), default=0) if binary is not None else 0
        )
        context = SerializationContext(region_id=max(ids, default=0), binaries=[b""] * binary_max)
        changed_math = _xml_state(self._settings_before) != _xml_state(self._settings())

        def regions_xml(regions, dx=0, dy=0):
            nonlocal changed_math
            nodes = []
            for region in regions:
                original = self._sources.get(id(region))
                if original is None:
                    node = region.to_xml(context)

                    def translate(n):
                        for name, delta in (
                            ("left", dx),
                            ("align-x", dx),
                            ("top", dy),
                            ("align-y", dy),
                        ):
                            n.set(name, str(float(n.get(name)) + delta))
                        area = n.find("ws:area", NS)
                        if area is not None and area.get("is-collapsed") != "true":
                            for child in area.findall("ws:region", NS):
                                translate(child)

                    translate(node)
                    changed_math = True
                    nodes.append(node)
                    continue
                source, before = original
                node = deepcopy(source)
                after = _stamp(region)
                left, top = region.left + dx, region.top + dy
                if left != float(source.get("left", "0")) or top != float(source.get("top", "0")):
                    changed_math = True
                for attr, value in (
                    ("left", left),
                    ("top", top),
                    ("width", region.width),
                    ("height", region.height),
                ):
                    if float(node.get(attr, "0")) != value:
                        node.set(attr, str(value))
                if left != float(source.get("left", "0")):
                    node.set(
                        "align-x",
                        str(
                            float(source.get("align-x", "0"))
                            + left
                            - float(source.get("left", "0"))
                        ),
                    )
                axis = top + region._axis if region._axis is not None else top + region.height / 2
                if top != float(source.get("top", "0")) or region._axis != before[6]:
                    node.set("align-y", str(axis))
                if region.tag != before[4]:
                    node.set("tag", region.tag)
                if region.border != before[5]:
                    node.set("show-border", str(region.border).lower())
                if isinstance(region, MathRegion):
                    math = node.find("ws:math", NS)
                    if after[7] != before[7]:
                        math.replace(math[0], e.serialize_expression(region.expression))
                        changed_math = True
                    if region.disabled != before[9]:
                        math.set("disable-calc", str(region.disabled).lower())
                        changed_math = True
                    if region.result_format != before[8]:
                        old = math.find("ws:resultFormat", NS)
                        if region.result_format is None:
                            if old is not None:
                                math.remove(old)
                        elif old is None or before[8] is None:
                            if old is not None:
                                math.remove(old)
                            math.append(region.result_format.to_xml())
                        else:
                            previous = before[8].to_xml()
                            updated = region.result_format.to_xml()
                            if before[8].notation != region.result_format.notation:
                                number = next(
                                    (n for n in old if local(n) in {v.value for v in NumberFormat}),
                                    None,
                                )
                                replacement = next(
                                    n
                                    for n in updated
                                    if local(n) == region.result_format.notation.value
                                )
                                if number is not None:
                                    old.replace(number, deepcopy(replacement))
                            _patch_settings(old, previous, updated)
                elif isinstance(region, TextRegion) and after[7:] != before[7:]:
                    text = node.find("ws:text", NS)
                    paragraphs = list(text)
                    text[:] = []
                    for index, line in enumerate(region.text.split("\n")):
                        paragraph = deepcopy(paragraphs[min(index, len(paragraphs) - 1)])
                        paragraph.text = line
                        if region.style != before[8]:
                            paragraph.set("style", region.style.value)
                        text.append(paragraph)
                elif isinstance(region, Area):
                    area = node.find("ws:area", NS)
                    if region.name != before[7]:
                        area.set("name", region.name)
                    if region.collapsed != before[8]:
                        area.set("is-collapsed", str(region.collapsed).lower())
                    children = regions_xml(
                        region.regions,
                        0 if region.collapsed else left,
                        0 if region.collapsed else top,
                    )
                    if [n.get("region-id") for n in area if local(n) == "region"] != [
                        n.get("region-id") for n in children
                    ]:
                        changed_math = True
                    for child in list(area):
                        if local(child) == "region":
                            area.remove(child)
                    area.extend(children)
                elif isinstance(region, OpaqueRegion) and region.xml != before[7]:
                    raise ValueError(
                        "Replace an opaque region with a supported Region to edit its content"
                    )
                nodes.append(node)
            return nodes

        container = root.find("ws:regions", NS)
        original_ids = [n.get("region-id") for n in container if local(n) == "region"]
        nodes = regions_xml(self.regions)
        if original_ids != [n.get("region-id") for n in nodes]:
            changed_math = True
        for node in list(container):
            if local(node) == "region":
                container.remove(node)
        container.extend(nodes)
        if changed_math:
            # Results are caches: changing a definition invalidates dependent results.
            for node in list(root.iter()):
                if local(node) in {"result", "symResult", "rendering", "renderingInfo"}:
                    parent = node.getparent()
                    if parent is not None:
                        parent.remove(node)
                for name in ("error", "warning", "error-id", "warning-id"):
                    node.attrib.pop(name, None)
        if len(context.binaries) > binary_max:
            import base64

            if binary is None:
                binary = element("binaryContent", root)
            for i, data in enumerate(context.binaries[binary_max:], binary_max + 1):
                element("item", binary, item_id=i, text=base64.b64encode(data).decode("ascii"))
        return root

    def to_bytes(self):
        root = self.to_xml()
        if _xml_state(root) == _xml_state(self._source_root):
            return self._source_bytes
        return ET.tostring(root, encoding="UTF-8", xml_declaration=True, pretty_print=True)


def read_worksheet(source: str | Path | bytes) -> LoadedWorksheet:
    data = source if isinstance(source, bytes) else Path(source).read_bytes()
    validate(data)
    root = parse_xml(data)
    w = LoadedWorksheet()
    w._source_root = root
    w._source_bytes = data
    w._sources = {}

    def text(path, default=""):
        node = root.find(path, NS)
        return node.text or default if node is not None else default

    w.title = text("ws:metadata/ws:userData/ws:title")
    w.author = text("ws:metadata/ws:userData/ws:author")
    w._metadata_before = {"title": w.title, "author": w.author}
    builtins = root.find("ws:settings/ws:calculation/ws:builtInVariables", NS)
    if builtins is not None:
        w.origin = int(builtins.get("array-origin", "0"))
        w.tolerance = float(builtins.get("convergence-tolerance", "0.001"))
        w.constraint_tolerance = float(builtins.get("constraint-tolerance", "0.001"))
    style = root.find("ws:settings/ws:presentation/ws:mathRendering/ws:mathStyles/ws:mathStyle", NS)
    if style is not None:
        w.font_size = float(style.get("font-size", "10"))
    w.result_format = (
        _format(root.find("ws:settings/ws:presentation/ws:mathRendering/ws:results", NS))
        or ResultFormat()
    )
    page = root.find("ws:settings/ws:presentation/ws:pageModel", NS)
    if page is not None:
        margins = page.find("ws:margins", NS)
        w.page = PageSettings(
            paper_code=int(page.get("paper-code", "9")),
            orientation=Orientation(page.get("orientation", "portrait")),
            **{
                f"margin_{n}": float(margins.get(n, "36"))
                for n in ("left", "right", "top", "bottom")
            }
            if margins is not None
            else {},
        )
    w._settings_before = w._settings()
    w.regions = w._read_regions(root.find("ws:regions", NS))
    return w
