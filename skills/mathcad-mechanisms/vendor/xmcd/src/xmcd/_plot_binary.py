"""Classic Mathcad graph archive writer, derived from native UI samples.

The archive stores a binary expression tree and graph formatting. It is not an
image or a worksheet template. Object references are local to each graph.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .expressions import Call, Number, Operator, Parens, Sequence, Symbol, _group_operand, expr
from .types import LiteralSubscript


def u32(value):
    return struct.pack("<I", value)


def compact_uint(value):
    """Archive integer: two leading length bits, then big-endian value bits."""
    if not 0 <= value < 1 << 30:
        raise ValueError("Mathcad archive integers must fit in 30 bits")
    size = max(1, (value.bit_length() + 9) // 8)
    return (value | ((size - 1) << (size * 8 - 2))).to_bytes(size, "big")


def class_record(*classes):
    data = b"\0" + u32(len(classes))
    for name, version, identifier in classes:
        data += bytes([len(name)]) + name.encode("ascii")
        data += u32(version) + b"\0\0" + u32(identifier)
    return data


@dataclass
class Node:
    opcode: int
    left: Node | None = None
    right: Node | None = None
    text: str | None = None
    flags: int = 0


def pair(left, right):
    return Node(0xC19F, left, right)


def placeholder(*, automatic=False):
    return Node(0xF00, flags=2 if automatic else 0)


def comma(nodes):
    result = nodes[0]
    for n in nodes[1:]:
        result = Node(0xC30A, result, n)
    return result


def expression(value):
    value = expr(value)
    if isinstance(value, Symbol):
        subscript = (
            value.subscript.text
            if isinstance(value.subscript, LiteralSubscript)
            else value.subscript
        )
        name = value.name + ("." + subscript if subscript else "")
        return Node(0xF02, text=name, flags=0x24)
    if isinstance(value, Number):
        return Node(0xF02, text=str(value.value), flags=0x34)
    if isinstance(value, Sequence):
        return comma([expression(v) for v in value.values])
    if isinstance(value, Parens):
        return Node(0x708E, right=expression(value.value))
    if isinstance(value, Call):
        arguments = comma([expression(v) for v in value.arguments])
        return Node(0xCE12, expression(value.function), Node(0x708E, right=arguments))
    if isinstance(value, Operator):
        if value.name == "minus":
            # A + (-B) uses the independently observed addition and negation nodes.
            # Explicit grouping preserves a compound right operand.
            return expression(value.arguments[0] + (-value.arguments[1]).parens())
        if value.name == "neg":
            return Node(0x4B95, right=expression(_group_operand("neg", value.arguments[0], 0)))
        codes = {"pow": 0xFC05, "div": 0xFB07, "plus": 0xC789, "mult": 0xCA06}
        if value.name in codes:
            return Node(
                codes[value.name],
                *(
                    expression(_group_operand(value.name, argument, index))
                    for index, argument in enumerate(value.arguments)
                ),
            )
    raise TypeError(
        "This graph expression is not supported yet; define a worksheet function "
        "or vector and plot its name/call instead"
    )


def axis(expressions, bounds):
    low, high = bounds
    limits = pair(
        placeholder(automatic=True) if high is None else expression(high),
        placeholder(automatic=True) if low is None else expression(low),
    )
    markers = pair(placeholder(automatic=True), placeholder(automatic=True))
    return pair(pair(limits, markers), expressions)


class TreeWriter:
    def __init__(self):
        self.identifier = 2

    def write(self, node, parent=0, side=0):
        if node is None:
            return b"\0"
        self.identifier += 1
        identifier = self.identifier
        header = compact_uint(identifier)
        header += class_record(("tree", 27, 0x32)) if identifier == 3 else b"\x32"
        flags = node.flags | side
        data = header + struct.pack("<IB", node.opcode, flags) + compact_uint(parent)
        data += self.write(node.left, identifier, 0x40)
        data += self.write(node.right, identifier, 0x80)
        if node.opcode not in {0x700D, 0xC119}:
            if node.text is None:
                data += b"\0"
            else:
                encoded = node.text.encode("utf-16le")
                size = len(encoded) // 2
                data += compact_uint(size + 1) + (b"\1" if flags & 0x10 else b"")
                data += compact_uint(size) + encoded + b"\0"
        return data


def formatting(columns, rows, traces, *, polar=False, x_grid=False, y_grid=False):
    from .plots import MARKERS

    data = class_record(("d2_graph_format", 7, 0x15), ("graphData", 0, 0x1A))
    data += u32(0) + u32(0x2006 if polar else 0x2002) + b"\0" + u32(3) + u32(1)
    data += u32(columns) + u32(rows)
    # Native defaults: linear axis, automatic grid spacing, black axes.
    axis_data = bytes.fromhex("4c 01 00 00 00 01 00 00 00 00 00 00 00 00 00 ff 00 ff 00 00")

    def axis_style(grid):
        return bytes([axis_data[0] | (2 if grid else 0)]) + axis_data[1:]

    data += b"\1" + class_record(("axisFormat", 4, 0x1C)) + axis_style(x_grid)
    data += b"\1\x1c" + axis_style(y_grid)
    if not polar:
        data += b"\1\x1c" + axis_data
    data += (b"\0\1" if polar else b"\0\0\1") + class_record(("trace2D", 3, 0x1B))
    data += bytes.fromhex("01 00 00 00 1f 01") + bytes([16])
    colors = [(255, 0, 0), (0, 0, 255), (0, 128, 0), (255, 0, 255), (0, 160, 160)]
    for i in range(16):
        trace = traces[i] if i < len(traces) else None
        rgb = (
            tuple(bytes.fromhex(trace.color.lstrip("#")))
            if trace and trace.color
            else colors[i % len(colors)]
        )
        style = trace.style if trace else "solid"
        marker = MARKERS[trace.marker] if trace else 0
        data += bytes([i, 1, 0x1B, {"solid": 1, "dash": 2, "dot": 3, "dash-dot": 4}[style], *rgb])
        data += (bytes([0x1E, marker]) if marker else b"\x1f") + b"\1"
    data += b"\1" + class_record(("NumericalFormat", 8, 0x48))
    data += struct.pack("<3H4I", 100, 105, 105, 3, 15, 10, 3)
    data += bytes(15) + u32(12) + bytes(10)
    return data


def graph_bytes(plot):
    x = comma([expression(t.x) for t in plot.traces])
    y = comma([expression(t.y) for t in plot.traces])
    y_axis = axis(y, plot.y_bounds)
    if not plot._polar:
        y_axis = pair(y_axis, axis(placeholder(automatic=True), (None, None)))
    graph = Node(0xC119, y_axis, axis(x, plot.x_bounds))
    writer = TreeWriter()
    body = writer.write(Node(0x700D, right=graph))
    data = struct.pack("<4I", 12, 1, 0x53, 10)
    data += b"\1" + class_record(
        ("eqRegion", 5, 0x34), ("docRegion", 4, 0x39), ("mcObject", 0, 0x52)
    )
    data += b"\1" + class_record(("shpBox", 0, 0x4C), ("shpRect", 0, 0x4D))
    x0, y0, x1, y1 = (
        round(v * 4 / 3)
        for v in (plot.left, plot.top, plot.left + plot.width, plot.top + plot.height)
    )
    data += struct.pack("<6i", x0, y0, x1, y1, x0, y0)
    data += struct.pack("<3IH", 0, 2, 0x110, 0) + b"\2"
    data += body + compact_uint(writer.identifier + 1)
    columns = max(1, round((plot.width - 27) / 6))
    rows = max(1, round((plot.height - 39.75) / 6))
    return data + formatting(
        columns, rows, plot.traces, polar=plot._polar, x_grid=plot.x_grid, y_grid=plot.y_grid
    )
