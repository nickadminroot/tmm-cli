"""API5 text parameter construction for KOMPAS-3D.

Pure COM-helper module — constructs ``ko_TextItemParam``,
``ko_TextLineParam``, ``ko_TextParam`` and calls
``doc2d.ksTextEx()`` to create formatted text.

All pywin32 / COM imports are guarded — this module can be imported on
any platform.
"""

from __future__ import annotations

import math
from typing import Any, Optional, Sequence

# ─── Guarded pywin32 imports ───────────────────────────────────────────────

try:
    import pythoncom
except ImportError:  # pragma: no cover - host-dependent
    pythoncom = None  # type: ignore[assignment]

try:
    from win32com.client import Dispatch, gencache
except ImportError:  # pragma: no cover - host-dependent
    Dispatch = None  # type: ignore[assignment]
    gencache = None  # type: ignore[assignment]

from tmm_scene_kompas.kompas_text import (
    FontRole,
    TextItemPlan,
    TextLinePlan,
    TextRenderPlan,
    estimate_plan_size,
)

# ─── Dynamic array type constant ───────────────────────────────────────────

TEXT_ITEM_ARR = 4

# API5 typography bit-vector flags.  The OFF flags are required because the
# formatter carries style state between adjacent TextItemParam values (and can
# retain it from an earlier text object); a zero bit vector does not reset it.
_STYLE_ITALIC_ON = 0x40
_STYLE_ITALIC_OFF = 0x80
_STYLE_BOLD_ON = 0x100
_STYLE_BOLD_OFF = 0x200
_STYLE_UNDERLINE_ON = 0x400
_STYLE_UNDERLINE_OFF = 0x800


# ─── Helpers ────────────────────────────────────────────────────────────────


def _style_bits(
    plan_item: TextItemPlan,
    style_state: Optional[list[Optional[bool]]] = None,
    repeat_styles: bool = False,
) -> int:
    """Encode per-run typography and update the optional formatter state."""
    desired = [bool(plan_item.italic), bool(plan_item.bold), bool(plan_item.underline)]
    on_bits = (_STYLE_ITALIC_ON, _STYLE_BOLD_ON, _STYLE_UNDERLINE_ON)
    off_bits = (_STYLE_ITALIC_OFF, _STYLE_BOLD_OFF, _STYLE_UNDERLINE_OFF)
    if repeat_styles:
        return sum(
            on_bits[index] if value else off_bits[index]
            for index, value in enumerate(desired)
        )
    if style_state is None:
        return ((_STYLE_BOLD_ON if desired[1] else 0) |
                (_STYLE_ITALIC_ON if desired[0] else 0) |
                (_STYLE_UNDERLINE_ON if desired[2] else 0))
    bits = 0
    for index, value in enumerate(desired):
        if style_state[index] is None or value != style_state[index]:
            bits |= on_bits[index] if value else off_bits[index]
    style_state[:] = desired
    return bits


def _new_item_param(
    kompas5,
    const,
    plan_item: TextItemPlan,
    height: float = 0.0,
    style_state: Optional[list[Optional[bool]]] = None,
    repeat_styles: bool = False,
):
    """Create a single ``ko_TextItemParam`` from a ``TextItemPlan``.

    Resolves *kind* to the correct KOMPAS item type, ``iSNumb`` (on the
    item), and ``bitVector`` (on the font).

    Script-base items use ``const.SUM_TYPE`` as the item type.  If
    ``SUM_TYPE`` is not present in the constants, raises ``RuntimeError``.

    Upper/lower/end script items get ``type=0`` with ``bitVector``
    ``0x8``/``0x9``/``0x10``.  Fraction items keep ``item_type``
    (1/2/3) and ``bitVector=0``.  Plain items keep ``item_type`` (0)
    and ``bitVector=0``.
    """
    # ── Map FontRole to font name ──────────────────────────────────────
    if plan_item.font == FontRole.SYMBOL:
        font_name = "Symbol type A"
    else:
        font_name = "GOST type A"

    # ── Resolve type, iSNumb, bitVector from kind ──────────────────────
    kind = plan_item.kind
    # API5 lesson 15: composite kinds are font.bitVector flags.  The
    # TextItemParam.type field remains 0 for ordinary strings, scripts,
    # fractions and deviations.  Using the flags as `type` was the cause of
    # the earlier empty/flattened production probe.
    #
    # The same bit vector also carries the per-run typography flags.  The
    # generated API5 ksTextItemFont does not expose Bold/Italic/Underline
    # properties on the verified installation; setting those dynamic
    # attributes is therefore a no-op.  These are the documented font flags
    # and must be ORed with the structural flags below.
    if kind == "script_base":
        numeric_type = 0
        i_s_numb = 0
        bit_vector = 0x7
    elif kind == "script_upper":
        numeric_type = 0
        i_s_numb = 0
        bit_vector = 0x8
    elif kind == "script_lower":
        numeric_type = 0
        i_s_numb = 0
        bit_vector = 0x9
    elif kind == "script_end":
        numeric_type = 0
        i_s_numb = 0
        bit_vector = 0x10
    elif kind == "updn_base":
        numeric_type = 0
        i_s_numb = 0
        bit_vector = 0x7
    elif kind == "updn_upper":
        numeric_type = 0
        i_s_numb = 0
        bit_vector = 0x8
    elif kind == "updn_lower":
        numeric_type = 0
        i_s_numb = 0
        bit_vector = 0x9
    elif kind == "updn_end":
        numeric_type = 0
        i_s_numb = 0
        bit_vector = 0x10
    elif kind in ("fraction_num", "fraction_den", "fraction_end"):
        numeric_type = 0
        i_s_numb = 0
        bit_vector = {"fraction_num": 0x1,
                      "fraction_den": 0x2,
                      "fraction_end": 0x3}[kind]
    elif kind == "special":
        numeric_type = 0x11
        i_s_numb = plan_item.i_s_numb
        bit_vector = 0x11
    elif kind == "special_end":
        numeric_type = 0
        i_s_numb = 0
        bit_vector = 0x12
    else:
        # Plain / unknown
        numeric_type = plan_item.item_type if plan_item.item_type else 0
        i_s_numb = plan_item.i_s_numb
        bit_vector = plan_item.bit_vector

    # ── Build param ────────────────────────────────────────────────────
    item = kompas5.GetParamStruct(const.ko_TextItemParam)
    item.Init()
    item.s = plan_item.content
    item.type = numeric_type
    item.iSNumb = i_s_numb

    font = item.GetItemFont()
    font.fontName = font_name
    if height > 0.0:
        font.height = height
    font.ksu = 1
    font.color = 0
    font.bitVector = bit_vector | _style_bits(
        plan_item, style_state, repeat_styles=repeat_styles,
    )
    item.SetItemFont(font)

    return item


def _new_line_param(kompas5, const, items: Sequence[TextItemPlan],
                    height: float = 0.0, break_after: bool = False,
                    style_state: Optional[list[Optional[bool]]] = None,
                    repeat_styles: bool = False,
                    break_style: Optional[TextItemPlan] = None):
    """Build a ``ko_TextLineParam`` from ``TextItemPlan`` items.

    Uses ``GetTextItemArr()`` / ``SetTextItemArr()`` with the
    ``TEXT_ITEM_ARR=4`` constant.

    Returns the populated line parameter struct.
    """
    line = kompas5.GetParamStruct(const.ko_TextLineParam)
    arr = line.GetTextItemArr()
    arr.ksClearArray()

    for plan_item in items:
        item = _new_item_param(
            kompas5,
            const,
            plan_item, height=plan_item.height or height,
            style_state=style_state,
            repeat_styles=repeat_styles,
        )
        arr.ksAddArrayItem(-1, item)

    # KOMPAS flattens a TextLineParam array by itself. The stage-1 live probe
    # established that @/ is the required in-object line separator.
    if break_after:
        source_style = break_style if repeat_styles else None
        marker = TextItemPlan(
            0,
            FontRole.GOST_TYPE_A,
            "@/",
            height=height,
            bold=source_style.bold if source_style is not None else False,
            italic=source_style.italic if source_style is not None else False,
            underline=source_style.underline if source_style is not None else False,
        )
        arr.ksAddArrayItem(-1, _new_item_param(
            kompas5, const, marker,
            height=height,
            style_state=style_state,
            repeat_styles=repeat_styles,
        ))
    line.SetTextItemArr(arr)
    return line


def _new_text_param(
    kompas5,
    const,
    x: float,
    y: float,
    height: float,
    lines: Sequence[TextLinePlan],
    width: float = 160.0,
    angle: float = 0.0,
    track_styles: bool = False,
    repeat_styles: bool = False,
):
    """Build a full ``ko_TextParam`` with paragraph and text lines.

    Creates a ``ko_ParagraphParam`` for positioning and sets the
    text-line array via ``GetTextLineArr()`` / ``SetTextLineArr()``.

    Returns the populated text parameter struct, ready for
    ``doc2d.ksTextEx(text_param, 0)``.
    """
    text_param = kompas5.GetParamStruct(const.ko_TextParam)
    text_param.Init()

    para = kompas5.GetParamStruct(const.ko_ParagraphParam)
    para.Init()
    para.x = float(x)
    para.y = float(y)
    para.height = float(height)
    para.ang = float(angle)
    para.width = float(width)
    para.hFormat = 0
    para.vFormat = 0
    text_param.SetParagraphParam(para)

    lines_arr = text_param.GetTextLineArr()
    lines_arr.ksClearArray()
    # Start unknown: API5 style state can leak from a previous text object, so
    # the first run must explicitly turn every non-requested style off.
    style_state = [None, None, None] if track_styles and not repeat_styles else None

    for line_index, line_plan in enumerate(lines):
        break_style = None
        if repeat_styles and line_plan.break_after:
            if line_index + 1 < len(lines) and lines[line_index + 1].items:
                break_style = lines[line_index + 1].items[0]
            elif line_plan.items:
                break_style = line_plan.items[-1]
        line = _new_line_param(
            kompas5, const, line_plan.items,
            height=line_plan.height or height,
            break_after=line_plan.break_after,
            style_state=style_state,
            repeat_styles=repeat_styles,
            break_style=break_style,
        )
        lines_arr.ksAddArrayItem(-1, line)

    text_param.SetTextLineArr(lines_arr)

    return text_param


def add_api5_text_plan(
    doc2d,
    kompas5,
    const,
    plan: TextRenderPlan,
    center_x: float,
    center_y: float,
    entity_id: str = "<unknown>",
    angle: float = 0.0,
) -> int:
    """Render a ``TextRenderPlan`` via ``doc2d.ksTextEx()`` centred at
    ``(center_x, center_y)``.

    Uses ``estimate_plan_size`` to compute the bottom-left offset from
    the requested centre point.

    Raises ``RuntimeError`` with *entity_id* on failure (zero reference).

    Returns the non-zero KOMPAS reference on success.
    """
    w, h = estimate_plan_size(plan)
    x = float(center_x) - w / 2.0
    y = float(center_y) - h / 2.0

    text_param = _new_text_param(
        kompas5,
        const,
        x=x,
        y=y,
        height=plan.height,
        lines=plan.lines,
        width=max(w + 2.0, 10.0),
        angle=angle,
    )

    ref = doc2d.ksTextEx(text_param, 0)
    if not ref:
        raise RuntimeError(
            f"ksTextEx returned zero reference for entity {entity_id}"
        )
    return int(ref)


def _gabarit_xywh(doc2d, kompas5, const, reference: int) -> tuple[float, float, float, float] | None:
    """Read a non-degenerate API5 gabarit using the verified rect path.

    A missing method, failed return, malformed rectangle, or non-finite value
    is not measurement evidence.  Returning ``None`` makes top-left lowering
    fail rather than silently accepting an unprovable placement.
    """
    get_gabarit = getattr(doc2d, "ksGetObjGabaritRect", None)
    if not hasattr(const, "ko_RectParam") or not callable(get_gabarit):
        return None
    try:
        rect = kompas5.GetParamStruct(const.ko_RectParam)
        status = get_gabarit(int(reference), rect)
        if not status:
            return None
        bottom = rect.GetpBot()
        top = rect.GetpTop()

        def coordinate(point, lower: str, upper: str) -> float:
            value = getattr(point, lower, None)
            if value is None:
                value = getattr(point, upper)
            return float(value)

        left = coordinate(bottom, "x", "X")
        bottom_y = coordinate(bottom, "y", "Y")
        right = coordinate(top, "x", "X")
        top_y = coordinate(top, "y", "Y")
    except Exception:
        return None
    result = (left, bottom_y, right - left, top_y - bottom_y)
    if (not all(math.isfinite(value) for value in result) or
            result[2] <= 0.0 or result[3] <= 0.0):
        return None
    return result


def add_api5_text_block_plan(doc2d, kompas5, const, plan: TextRenderPlan,
                             top_left_x: float, top_left_y: float, width: float,
                             entity_id: str = "<unknown>") -> int:
    """Create exactly one ksTextEx and correct its retained reference to top-left.

    The correction is intentionally post-create: the live stage-1 probe proved
    ``ksGetObjGabaritRect`` + ``ksMoveObj`` retains the same reference and
    reaches the requested multiline Y-up top-left exactly.
    """
    text_param = _new_text_param(
        kompas5, const, float(top_left_x), float(top_left_y),
        plan.height, plan.lines, width=float(width),
        repeat_styles=True,
    )
    reference = doc2d.ksTextEx(text_param, 0)
    if not reference:
        raise RuntimeError(f"ksTextEx returned zero reference for entity {entity_id}")
    reference = int(reference)
    bounds = _gabarit_xywh(doc2d, kompas5, const, reference)
    if bounds is None:
        raise RuntimeError(f"Unable to measure API5 gabarit for textBlock {entity_id}")
    left, bottom, _actual_width, actual_height = bounds
    move = getattr(doc2d, "ksMoveObj", None)
    if not callable(move):
        raise RuntimeError(f"API5 cannot correct top-left for textBlock {entity_id}")
    moved = move(reference, float(top_left_x - left),
                 float(top_left_y - (bottom + actual_height)))
    if not moved:
        raise RuntimeError(f"ksMoveObj failed while correcting textBlock {entity_id}")
    corrected = _gabarit_xywh(doc2d, kompas5, const, reference)
    if corrected is None:
        raise RuntimeError(f"Unable to verify corrected top-left for textBlock {entity_id}")
    corrected_left, corrected_bottom, _corrected_width, corrected_height = corrected
    if (abs(corrected_left - top_left_x) > 1e-6 or
            abs((corrected_bottom + corrected_height) - top_left_y) > 1e-6):
        raise RuntimeError(f"API5 top-left correction did not converge for textBlock {entity_id}")
    return reference


__all__ = [
    "TEXT_ITEM_ARR",
    "_new_item_param",
    "_new_line_param",
    "_new_text_param",
    "add_api5_text_plan",
    "add_api5_text_block_plan",
]
