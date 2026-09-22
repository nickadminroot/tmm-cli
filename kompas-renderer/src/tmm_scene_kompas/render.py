"""KOMPAS API7 consumer for tmm-scene JSON.

Reads the universal Scene JSON document written by the renderer pipeline
(``format: 'tmm-scene'``) and creates a ``.cdw`` drawing through the
verified API7 type library.

Lowered entities: line, circle, arc, text, textBlock, table, polygon, smoothCurve (as polyline approximation). Tables create native editable KOMPAS ``IDrawingTable`` objects. Filled polygons
marked with ``role: 'arrowhead'`` are converted to native leader arrows
through the API5 fallback; ordinary triangular polygons remain closed
polylines.

All pywin32 / COM imports are guarded — this module can be imported on
any platform.  KOMPAS is only touched at call time (``build_drawing``).
"""

from __future__ import annotations

import math
import os
import re
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

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

# ─── COM GUIDs ──────────────────────────────────────────────────────────────

API7_GUID = "{69AC2981-37C0-4379-84FD-5DD2F3C0A520}"
CONST_GUID = "{75C9F5D0-B5B8-4526-8681-9903C567D2ED}"
API5_GUID = "{0422828C-F174-495E-AC5D-D31014DBBE87}"

# Dynamic array type constants from LDefin2D.py / SDK docs.
POLYLINE_ARR = 7
POINT_ARR = 2


# ─── Import from sibling modules ─────────────────────────────────────────────

from tmm_scene_kompas.kompas_text import (
    compile_latex_api5_exact,
    compile_unicode_text,
    contains_math_unicode,
    normalize_kompas_text,
)
from tmm_scene_kompas.text_block_layout import compile_text_block_plan
from tmm_scene_kompas.text_block_parser import validate_text_block_entity
from tmm_scene_kompas.table import (
    TableCellInlinePlan,
    TablePlan,
    compile_table_plan,
    table_requires_api5,
)


# ─── KOMPAS bootstrap (verified) ────────────────────────────────────────────


def _qi(module, obj, interface_name: str):
    """Cast a pywin32 COM object to a generated API7 interface."""
    iface = getattr(module, interface_name)
    return iface(obj._oleobj_.QueryInterface(iface.CLSID, pythoncom.IID_IDispatch))


def _ensure_pythoncom() -> None:
    if pythoncom is None or Dispatch is None or gencache is None:
        raise RuntimeError(
            "pywin32 / pythoncom are not available; this script must run on "
            "a Windows host with a working pywin32 install."
        )


class _ComApartment:
    """One balanced COM initialization owned by one render operation."""

    def __init__(self) -> None:
        self._initialized = False

    def __enter__(self):
        _ensure_pythoncom()
        # CoInitialize increments the current thread's apartment count even
        # when a caller has already initialized it.  This matching
        # CoUninitialize therefore releases only our own increment.
        pythoncom.CoInitialize()
        self._initialized = True
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        if self._initialized:
            pythoncom.CoUninitialize()
            self._initialized = False


def connect_kompas(visible: bool = True, hide_messages: bool = True):
    """Connect inside an apartment initialized by the caller.

    ``draw_scene_document`` owns that lifecycle through ``_ComApartment``.
    Keeping this bootstrap side-effect-free prevents a direct connection from
    leaking an unmatched COM initialization into caller-owned code.
    """
    _ensure_pythoncom()
    module7 = gencache.EnsureModule(API7_GUID, 0, 1, 0)
    const = gencache.EnsureModule(CONST_GUID, 0, 1, 0).constants
    raw = Dispatch("KOMPAS.Application.7")
    api7 = module7.IKompasAPIObject(
        raw._oleobj_.QueryInterface(
            module7.IKompasAPIObject.CLSID, pythoncom.IID_IDispatch
        )
    )
    app = api7.Application
    app.Visible = bool(visible)
    if hide_messages and hasattr(const, "ksHideMessageNo") and hasattr(app, "HideMessage"):
        try:
            app.HideMessage = const.ksHideMessageNo
        except Exception:
            pass
    return module7, const, api7, app


def open_active_view(module7, doc):
    doc2d = _qi(module7, doc, "IKompasDocument2D")
    mgr = doc2d.ViewsAndLayersManager
    view = mgr.Views.ActiveView
    container = _qi(module7, view, "IDrawingContainer")
    return doc2d, view, container


# ─── API5 fallback for textless leader arrows ───────────────────────────────


class Api5Context:
    """Lazily-initialized API5 context for textless leader arrows.

    Separate from API7 helpers because API5 and API7 use different COM
    dispatch objects.  Created once per ``build_drawing`` call.
    Uses the verified API5 ``ksLeaderParam`` + ``ksDocument2D.ksLeader()``
    pattern with real dynamic arrays.
    """

    def __init__(self) -> None:
        self._kompas = None
        self._const = None
        self._module7 = None
        # API5 exposes only ActiveDocument2D.  The API7 application's active
        # document and both API5/API7 document references are captured at bind
        # time and rechecked before each rich-text operation.
        self._expected_doc2d = None
        self._api7_app = None
        self._expected_document_reference = None

    def _ensure(self) -> None:
        if self._kompas is not None:
            return
        _ensure_pythoncom()
        try:
            module5 = gencache.EnsureModule(API5_GUID, 0, 1, 0)
            const5 = gencache.EnsureModule(CONST_GUID, 0, 1, 0).constants
            module7 = gencache.EnsureModule(API7_GUID, 0, 1, 0)
            raw5 = Dispatch("KOMPAS.Application.5")
            # Cast raw Dispatch to the generated API5 KompasObject interface
            self._kompas = module5.KompasObject(
                raw5._oleobj_.QueryInterface(
                    module5.KompasObject.CLSID, pythoncom.IID_IDispatch
                )
            )
            self._const = const5
            self._module7 = module7
        except Exception:
            self._kompas = None
            self._const = None
            self._module7 = None

    @property
    def available(self) -> bool:
        return self._kompas is not None

    @staticmethod
    def _same_document(left, right) -> bool:
        if left is right:
            return True
        try:
            if left == right:
                return True
        except Exception:
            pass
        try:
            return left._oleobj_ == right._oleobj_
        except Exception:
            return False

    @staticmethod
    def _document_reference(document):
        """Return KOMPAS' document reference, or ``None`` when unavailable."""
        try:
            reference = getattr(document, "Reference", None)
            if reference is None:
                reference = getattr(document, "reference", None)
            if reference is None:
                return None
            return int(reference)
        except (TypeError, ValueError):
            return None

    def bind_active_document(self, api7_app, api7_document) -> None:
        """Prove that API5's active drawing is the API7-created drawing.

    KOMPAS exposes the same non-zero document reference through API7
    ``IKompasDocument.Reference`` and API5 ``ksDocument2D.reference``.  It is
    stronger than comparing pywin32 wrapper identity, which is not stable
    across separately dispatched type libraries.
    """
        self._ensure()
        if not self.available:
            raise RuntimeError("API5 is not available to bind the active drawing document")
        expected_reference = self._document_reference(api7_document)
        active_api7 = getattr(api7_app, "ActiveDocument", None)
        active_reference = self._document_reference(active_api7)
        doc2d = self._kompas.ActiveDocument2D()
        api5_reference = self._document_reference(doc2d)
        if (expected_reference is None or expected_reference <= 0 or
                active_reference != expected_reference or
                api5_reference != expected_reference):
            raise RuntimeError("API5 active document does not match the API7-created drawing")
        self._expected_doc2d = doc2d
        self._api7_app = api7_app
        self._expected_document_reference = expected_reference

    def _active_document(self, entity_id: str):
        doc2d = self._kompas.ActiveDocument2D()
        if doc2d is None:
            raise RuntimeError(f"No active API5 document for text entity {entity_id}")
        expected_reference = getattr(self, "_expected_document_reference", None)
        if expected_reference is not None:
            active_api7 = getattr(self._api7_app, "ActiveDocument", None)
            if (self._document_reference(active_api7) != expected_reference or
                    self._document_reference(doc2d) != expected_reference):
                raise RuntimeError(f"Active KOMPAS document changed before text entity {entity_id}")
        else:
            expected = getattr(self, "_expected_doc2d", None)
            if expected is None:
                # Unit-injected contexts have no cross-API evidence.  They are
                # test seams only; production rendering always binds eagerly.
                self._expected_doc2d = doc2d
            elif not self._same_document(expected, doc2d):
                raise RuntimeError(f"Active API5 document changed before text entity {entity_id}")
        return doc2d

    def add_leader_arrow(
        self,
        base_x: float,
        base_y: float,
        tip_x: float,
        tip_y: float,
    ) -> bool:
        if not self.available:
            return False
        try:
            kompas = self._kompas
            const = self._const
            doc2d = kompas.ActiveDocument2D()
            if doc2d is None:
                return False

            leader = kompas.GetParamStruct(const.ko_LeaderParam)
            leader.Init()
            leader.arrowType = int(
                getattr(const, 'ksLeaderArrow', 2)
            )
            leader.signType = 0
            leader.dirX = 1
            leader.x = float(base_x)
            leader.y = float(base_y)
            leader.around = 0
            leader.cText0 = 0
            leader.cText1 = 0
            leader.cText2 = 0
            leader.cText3 = 0

            branches = kompas.GetDynamicArray(POLYLINE_ARR)
            branch = kompas.GetDynamicArray(POINT_ARR)
            branches.ksClearArray()
            branch.ksClearArray()

            tip = api5_math_point(kompas, const, tip_x, tip_y)
            branch.ksAddArrayItem(-1, tip)
            branches.ksAddArrayItem(-1, branch)
            leader.SetpPolyline(branches)

            ref = doc2d.ksLeader(leader)
            if ref:
                self._disable_clear_background(ref)
            return bool(ref)
        except Exception:
            return False

    def _disable_clear_background(self, reference) -> bool:
        try:
            obj = self._kompas.TransferReference(int(reference), 0)
            return disable_clear_background(self._module7, obj)
        except Exception:
            return False

    def add_text_plan(
        self,
        plan: 'TextRenderPlan',
        center_x: float,
        center_y: float,
        entity_id: str = "<unknown>",
        angle: float = 0.0,
    ) -> None:
        """Add a ``TextRenderPlan`` centred at ``(center_x, center_y)``
        via API5 ``ksTextEx``.

        Raises ``RuntimeError`` with *entity_id* on failure.
        Requires ``self.available``.
        """
        if not self.available:
            raise RuntimeError(
                f"API5 is not available for text entity {entity_id}"
            )
        try:
            doc2d = self._active_document(entity_id)
            from tmm_scene_kompas.api5_text import add_api5_text_plan as _add_api5
            _add_api5(
                doc2d, self._kompas, self._const, plan,
                center_x=center_x, center_y=center_y,
                entity_id=entity_id, angle=angle,
            )
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(
                f"API5 text failed for entity {entity_id}: {exc}"
            ) from exc

    def apply_text_style_overrides(self, reference: int, source_text: str,
                                   entity_id: str = "<unknown>",
                                   block_italic: bool = False) -> None:
        """Reassert the textBlock italic contract after API5 expansion.

        API5 accepts the balanced ``$upper;lower$`` control string, but KOMPAS
        may reset typography on the expanded sub/superscript items.  API7
        exposes those items after creation, so reapply the block-level italic
        flag to every item.  For non-italic blocks, preserve the historical
        upright handling of explicit ``\\text``/``\\operatorname`` runs.
        """
        if self._module7 is None or self._api7_app is None:
            return
        targets = [match.group(1) or match.group(2) for match in re.finditer(
            r"\\(?:text|operatorname)\s*(?:\{([^{}]*)\}|([A-Za-z]))",
            str(source_text),
        )]
        targets = [target for target in targets if target]
        try:
            document = self._api7_app.ActiveDocument
            document2d = _qi(self._module7, document, "IKompasDocument2D")
            view = document2d.ViewsAndLayersManager.Views.ActiveView
            container = _qi(self._module7, view, "IDrawingContainer")
            drawing_text = None
            for index in range(int(container.DrawingTexts.Count)):
                candidate = container.DrawingTexts.Item(index)
                if int(getattr(candidate, "Reference", -1)) == int(reference):
                    drawing_text = _qi(self._module7, candidate, "IText")
                    break
            if drawing_text is None:
                raise RuntimeError("created DrawingText was not found through API7")
            used: set[int] = set()
            entries = []
            for line_index, line in enumerate(drawing_text.TextLines):
                for item_index, item in enumerate(line.TextItems):
                    text = str(getattr(item, "Str", ""))
                    match_index = next((index for index, target in enumerate(targets)
                                        if index not in used and text == target), None)
                    font = _qi(self._module7, item, "ITextFont")
                    current = bool(font.Italic)
                    desired = bool(block_italic)
                    if not block_italic:
                        desired = False if match_index is not None else current
                    if match_index is not None:
                        used.add(match_index)
                    entries.append((line_index, item_index, item, font,
                                    current, desired))
            for line_index, item_index, item, font, current, desired in entries:
                if desired == current:
                    continue
                font.Italic = desired
                if not item.Update():
                    raise RuntimeError(
                        f"ITextItem.Update failed at line {line_index}, item {item_index}"
                    )
        except Exception as exc:
            raise RuntimeError(
                f"API7 text style update failed for textBlock {entity_id}: {exc}"
            ) from exc

    def add_text_block_plan(self, plan: 'TextRenderPlan', top_left_x: float,
                            top_left_y: float, width: float,
                            entity_id: str = "<unknown>",
                            source_text: str | None = None,
                            italic: bool = False) -> int:
        """Lower one precompiled textBlock as exactly one retained ksTextEx."""
        if not self.available:
            raise RuntimeError(f"API5 is not available for textBlock {entity_id}")
        try:
            doc2d = self._active_document(entity_id)
            from tmm_scene_kompas.api5_text import add_api5_text_block_plan
            reference = add_api5_text_block_plan(
                doc2d, self._kompas, self._const, plan,
                top_left_x, top_left_y, width, entity_id,
            )
            if source_text:
                self.apply_text_style_overrides(
                    reference, source_text, entity_id, block_italic=italic,
                )
            return reference
        except Exception as exc:
            raise RuntimeError(f"API5 textBlock failed for entity {entity_id}: {exc}") from exc


def disable_clear_background(module7, obj) -> bool:
    candidates = [obj]
    if module7 is not None and hasattr(obj, '_oleobj_'):
        try:
            candidates.append(_qi(module7, obj, 'IDrawingObject1'))
        except Exception:
            pass

    for candidate in candidates:
        changed = False
        if hasattr(candidate, 'TransparentBackground'):
            candidate.TransparentBackground = False
            changed = True
        if hasattr(candidate, 'AutoTransparentBackground'):
            candidate.AutoTransparentBackground = False
            changed = True
        if changed:
            _update(candidate)
            return True
    return False


def api5_math_point(kompas, const, x, y):
    point = kompas.GetParamStruct(const.ko_MathPointParam)
    point.Init()
    point.x = float(x)
    point.y = float(y)
    return point


# ─── Style mapping (verified constants) ────────────────────────────────────

# Style constant names in preference order.
_THICK_NAMES = ("ksCSThick",)
_THIN_NAMES = ("ksCSThin",)
_THIN_FOR_HATCH_NAMES = ("ksCSThinForHatch", "ksCSThin")
_DASHED_NAMES = ("ksCSDashed",)
_DASHDOT_NAMES = ("ksCSNormalDashDot", "ksCSISO10DashDot")
_NORMAL_NAMES = ("ksCSNormal",)


def _lookup_const(const, names: Tuple[str, ...], fallback: int) -> int:
    for name in names:
        val = getattr(const, name, None)
        if val is not None:
            return int(val)
    return fallback


def resolve_style_for_layer(const, layer: str, style: str) -> int:
    """Map (layer, style) to a verified KOMPAS line style constant.

    Pure helper — only reads attributes from *const*, no COM calls.
    Dashed always resolves to ksCSDashed (4) regardless of layer.
    """
    normal = _lookup_const(const, _NORMAL_NAMES, 1)
    if layer == "hatch":
        return _lookup_const(const, _THIN_FOR_HATCH_NAMES, normal)
    if layer == "fixed":
        if style == "dashed":
            return _lookup_const(const, _DASHED_NAMES, normal)
        if style in {"dashdot", "dotted"}:
            return _lookup_const(const, _DASHDOT_NAMES, normal)
        return _lookup_const(const, _THICK_NAMES, normal)
    # thin, dimension, label, filled, and any other layer
    if style == "dashed":
        return _lookup_const(const, _DASHED_NAMES, normal)
    if style in {"dashdot", "dotted"}:
        return _lookup_const(const, _DASHDOT_NAMES, normal)
    return _lookup_const(const, _THIN_NAMES, normal)


def compute_leader_base_and_tip(
    tip: Tuple[float, float],
    base: Tuple[float, float],
    offset: Tuple[float, float] = (0.0, 0.0),
) -> Tuple[float, float, float, float]:
    """Return (base_x, base_y, tip_x, tip_y) with offset applied.

    Pure helper — no COM dependency.
    """
    return (
        float(base[0] + offset[0]),
        float(base[1] + offset[1]),
        float(tip[0] + offset[0]),
        float(tip[1] + offset[1]),
    )


def is_arrowhead_polygon(entity: Dict[str, Any]) -> bool:
    role = entity.get('role')
    if role == 'arrowhead':
        return True
    metadata = entity.get('metadata')
    return bool(isinstance(metadata, dict) and metadata.get('role') == 'arrowhead')


def offset_point(point: Sequence[float], offset: Tuple[float, float]) -> Tuple[float, float]:
    return float(point[0] + offset[0]), float(point[1] + offset[1])


def offset_entity(entity: Dict[str, Any], offset: Tuple[float, float]) -> Dict[str, Any]:
    ctype = entity.get('type')
    result = dict(entity)
    if ctype == 'line':
        result['from'] = list(offset_point(entity['from'], offset))
        result['to'] = list(offset_point(entity['to'], offset))
    elif ctype == 'circle':
        result['center'] = list(offset_point(entity['center'], offset))
    elif ctype == 'arc':
        result['center'] = list(offset_point(entity['center'], offset))
    elif ctype in ('text', 'textBlock', 'table'):
        result['position'] = list(offset_point(entity['position'], offset))
    elif ctype == 'polygon':
        result['points'] = [list(offset_point(point, offset)) for point in entity.get('points', [])]
    elif ctype == 'smoothCurve':
        result['points'] = [list(offset_point(point, offset)) for point in entity.get('points', [])]
    return result


def leader_arrow_base_and_tip_from_polygon(
    points: Sequence[Sequence[float]],
    length: float = 0.5,
) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    if len(points) < 3:
        raise ValueError('leader arrow polygon requires at least 3 points')
    apex = points[0]
    left = points[1]
    right = points[2]
    mid_x = (left[0] + right[0]) / 2.0
    mid_y = (left[1] + right[1]) / 2.0
    dx = apex[0] - mid_x
    dy = apex[1] - mid_y
    dist = math.hypot(dx, dy)
    if dist <= 0:
        base = (float(apex[0]), float(apex[1]))
    else:
        base = (
            float(apex[0] - (dx / dist) * length),
            float(apex[1] - (dy / dist) * length),
        )
    tip = (float(apex[0]), float(apex[1]))
    return base, tip


# ─── Catmull-Rom spline helpers ──────────────────────────────────────────────


def catmull_rom_point(
    p0: Tuple[float, float],
    p1: Tuple[float, float],
    p2: Tuple[float, float],
    p3: Tuple[float, float],
    t: float,
    alpha: float = 0.5,
) -> Tuple[float, float]:
    """Compute one point on a centripetal Catmull-Rom spline segment.

    p0..p3: 4 consecutive control points (x,y tuples)
    t: interpolation parameter [0..1] along the segment between p1 and p2
    alpha: 0.5 = centripetal (default), 0.0 = uniform, 1.0 = chordal
    Returns (x, y) tuple of the interpolated point.
    """

    def _chord(a, b) -> float:
        d = math.hypot(b[0] - a[0], b[1] - a[1])
        if d == 0.0:
            return 0.0
        return d ** alpha

    t0 = 0.0
    t1 = _chord(p0, p1)
    t2 = t1 + _chord(p1, p2)
    t3 = t2 + _chord(p2, p3)

    # Degenerate segment — all points coincide, return p1
    if t2 - t1 == 0.0:
        return p1

    tt = t1 + t * (t2 - t1)

    def _lerp(a, b, ta, tb) -> float:
        if tb - ta == 0.0:
            return (a + b) / 2.0
        return a * (tb - tt) / (tb - ta) + b * (tt - ta) / (tb - ta)

    a1 = (_lerp(p0[0], p1[0], t0, t1), _lerp(p0[1], p1[1], t0, t1))
    a2 = (_lerp(p1[0], p2[0], t1, t2), _lerp(p1[1], p2[1], t1, t2))
    a3 = (_lerp(p2[0], p3[0], t2, t3), _lerp(p2[1], p3[1], t2, t3))

    b1 = (_lerp(a1[0], a2[0], t0, t2), _lerp(a1[1], a2[1], t0, t2))
    b2 = (_lerp(a2[0], a3[0], t1, t3), _lerp(a2[1], a3[1], t1, t3))

    c = (_lerp(b1[0], b2[0], t1, t2), _lerp(b1[1], b2[1], t1, t2))
    return c


def catmull_rom_spline(
    points: List[Tuple[float, float]],
    num_segments: int = 20,
    alpha: float = 0.5,
) -> List[Tuple[float, float]]:
    """Generate interpolated points along a centripetal Catmull-Rom spline.

    points: list of (x,y) control points (at least 2)
    num_segments: number of interpolated points BETWEEN each pair of consecutive
                  control points (total ≈ num_segments * (len(points)-1) + 1)
    alpha: 0.5 centripetal (default)
    Returns list of (x,y) tuples forming the smooth curve.

    For 2 points, just returns a linear interpolation between them.
    For 3+ points, uses Catmull-Rom (needs 4 points for the spline formula,
    so virtual start/end points are created by mirroring).
    """
    pts = list(points)
    n = len(pts)
    if n < 2:
        return pts[:]
    if n == 2:
        # Linear interpolation for two points
        result: List[Tuple[float, float]] = []
        x0, y0 = pts[0]
        x1, y1 = pts[1]
        for i in range(num_segments + 1):
            t = i / num_segments
            result.append((x0 + t * (x1 - x0), y0 + t * (y1 - y0)))
        return result

    # Mirror the first and last points to create virtual control points
    p0 = (2.0 * pts[0][0] - pts[1][0], 2.0 * pts[0][1] - pts[1][1])
    pn = (2.0 * pts[-1][0] - pts[-2][0], 2.0 * pts[-1][1] - pts[-2][1])
    extended: List[Tuple[float, float]] = [p0, *pts, pn]

    result: List[Tuple[float, float]] = []
    for i in range(n - 1):
        for j in range(num_segments):
            t = j / num_segments
            pt = catmull_rom_point(
                extended[i], extended[i + 1], extended[i + 2], extended[i + 3],
                t, alpha,
            )
            result.append(pt)
    # Append the final control point
    result.append(pts[-1])
    return result


# ─── Text helpers (verified) ────────────────────────────────────────────────


def estimate_kompas_text_size(text: str, height: float,
                              char_width_factor: float = 0.7) -> Tuple[float, float]:
    """Estimate visual width and height for a single-line KOMPAS text.

    Pure helper — no COM dependency.  The KOMPAS ``DrawingText.X/Y``
    property refers to the bottom-left corner of the bounding box.
    """
    num_chars = max(len(text), 1)
    visual_width = num_chars * height * char_width_factor
    return visual_width, height


def kompas_text_origin_from_center(
    center_x: float, center_y: float, text: str, height: float,
    char_width_factor: float = 0.7,
) -> Tuple[float, float]:
    """Convert a Scene centre-anchored text position to KOMPAS bottom-left.

    Pure helper — no COM dependency.
    """
    visual_width, visual_height = estimate_kompas_text_size(
        text, height, char_width_factor
    )
    return center_x - visual_width / 2, center_y - visual_height / 2


# ─── Drawing helpers (verified) ─────────────────────────────────────────────


def _update(obj) -> None:
    if hasattr(obj, "Update"):
        try:
            obj.Update()
        except Exception:
            pass


# KOMPAS uses the same numeric values for the standard A-series formats as
# the API constants below.  The names are preferred so this remains portable
# across API7 versions and easy to exercise with fake constants in tests.
_SHEET_FORMATS = {
    "A0": ("ksFormatA0", 0),
    "A1": ("ksFormatA1", 1),
    "A2": ("ksFormatA2", 2),
    "A3": ("ksFormatA3", 3),
    "A4": ("ksFormatA4", 4),
    "A5": ("ksFormatA5", 5),
}


def _layout_sheet_item(doc, index: int = 0):
    sheets = doc.LayoutSheets
    if hasattr(sheets, "Item"):
        return sheets.Item(index)
    if hasattr(sheets, "GetItem"):
        return sheets.GetItem(index)
    raise AttributeError("LayoutSheets has neither Item nor GetItem")


def super_scene_sheet_spec(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return normalized sheet settings for a ``kind: super-scene`` payload.

    Scene coordinates are already emitted in millimetres in the target sheet
    coordinate system (the fixtures use y-up coordinates), so rendering must
    configure the physical sheet rather than scale or re-centre entities.
    """
    if payload.get("kind") != "super-scene":
        return None

    sheet = payload.get("sheet")
    if not isinstance(sheet, dict):
        raise ValueError("super-scene payload must contain a 'sheet' object")

    format_name = str(sheet.get("format", "")).strip().upper()
    format_entry = _SHEET_FORMATS.get(format_name)
    if format_entry is None:
        supported = ", ".join(_SHEET_FORMATS)
        raise ValueError(
            f"unsupported super-scene sheet format {format_name!r}; "
            f"expected one of {supported}"
        )

    orientation = str(sheet.get("orientation", "landscape")).strip().lower()
    if orientation not in {"portrait", "landscape"}:
        raise ValueError(
            f"unsupported super-scene sheet orientation {orientation!r}; "
            "expected 'portrait' or 'landscape'"
        )

    title_block = sheet.get("titleBlock")
    if title_block is not None and not isinstance(title_block, dict):
        raise ValueError("super-scene sheet 'titleBlock' must be an object")
    if title_block is None:
        title_block = {}

    title_cell = title_block.get("cell", 2)
    try:
        title_cell = int(title_cell)
    except (TypeError, ValueError) as exc:
        raise ValueError("super-scene titleBlock.cell must be an integer") from exc
    if title_cell <= 0:
        raise ValueError("super-scene titleBlock.cell must be positive")

    title = title_block.get("text")
    if title is not None and not isinstance(title, str):
        raise ValueError("super-scene titleBlock.text must be a string")

    return {
        "format": format_name,
        "format_name": format_entry[0],
        "format_fallback": format_entry[1],
        "orientation": orientation,
        "title_cell": title_cell,
        "title": (normalize_kompas_text(title)
                   if title is not None else None),
    }


def configure_super_scene_sheet(doc, const, payload: Dict[str, Any]) -> None:
    """Apply a super-scene's sheet format/orientation and title block.

    ``ILayoutSheet.Format`` itself is read-only; its returned
    ``ISheetFormat`` is mutable and the layout sheet must be updated before
    the new dimensions become active.  KOMPAS' standard title is cell 2
    (``Наименование``) in the default drawing stamp.
    """
    spec = super_scene_sheet_spec(payload)
    if spec is None:
        return

    sheet = _layout_sheet_item(doc)
    sheet_format = sheet.Format
    format_value = int(getattr(
        const, spec["format_name"], spec["format_fallback"]
    ))
    sheet_format.Format = format_value
    sheet_format.VerticalOrientation = spec["orientation"] == "portrait"
    sheet.Update()

    # Verify the two settings after Update.  A silently ignored format would
    # otherwise leave A2 geometry outside the default A4 page.
    actual_format = sheet.Format
    if int(actual_format.Format) != format_value:
        raise RuntimeError(
            f"KOMPAS did not apply sheet format {spec['format']}; "
            f"read back {actual_format.Format!r}"
        )
    expected_vertical = spec["orientation"] == "portrait"
    if bool(actual_format.VerticalOrientation) != expected_vertical:
        raise RuntimeError(
            f"KOMPAS did not apply sheet orientation {spec['orientation']!r}"
        )

    if spec["title"] is not None:
        stamp = sheet.Stamp
        stamp.Text(spec["title_cell"]).Str = spec["title"]
        # Stamp.Update() may return False even when the text is accepted, so
        # the text is verified by reading the cell back rather than by status.
        stamp.Update()
        actual_title = stamp.Text(spec["title_cell"]).Str
        if str(actual_title) != spec["title"]:
            raise RuntimeError("KOMPAS did not apply the super-scene title")


def add_line(container, const, x1: float, y1: float, x2: float, y2: float,
             style: str = "solid", layer: str = "fixed") -> None:
    obj = container.LineSegments.Add()
    obj.X1 = float(x1)
    obj.Y1 = float(y1)
    obj.X2 = float(x2)
    obj.Y2 = float(y2)
    obj.Style = resolve_style_for_layer(const, layer, style)
    _update(obj)


def add_circle(container, const, xc: float, yc: float, radius: float,
               style: str = "solid", layer: str = "fixed") -> None:
    obj = container.Circles.Add()
    obj.Xc = float(xc)
    obj.Yc = float(yc)
    obj.Radius = float(radius)
    obj.Style = resolve_style_for_layer(const, layer, style)
    _update(obj)


def add_filled_circle(container, const, xc: float, yc: float, radius: float) -> None:
    """Render a visually solid black disk with overlapping thick scanlines.

    API7's ``Colourings`` collection creates a fill object, but it does not
    bind that object to a newly-created circle contour through COM.  Rendering
    the disk as overlapping standard line segments is deterministic, editable,
    and has been verified in KOMPAS' raster export.  ``fixed`` resolves to the
    thick black line style, and the 0.25 mm pitch leaves no visible white gaps.
    """
    radius = float(radius)
    if radius <= 0:
        return
    pitch = 0.25
    count = max(1, int(math.ceil((2.0 * radius) / pitch)))
    for index in range(count):
        y = yc - radius + (index + 0.5) * (2.0 * radius / count)
        half_chord = math.sqrt(max(0.0, radius * radius - (y - yc) ** 2))
        add_line(container, const, xc - half_chord, y, xc + half_chord, y,
                 style="solid", layer="fixed")


def add_arc(container, const, xc: float, yc: float, radius: float,
            angle1: float, angle2: float, style: str = "solid",
            layer: str = "fixed", direction: bool = True) -> None:
    obj = container.Arcs.Add()
    obj.Xc = float(xc)
    obj.Yc = float(yc)
    obj.Radius = float(radius)
    obj.Angle1 = float(angle1)
    obj.Angle2 = float(angle2)
    obj.Direction = bool(direction)
    obj.Style = resolve_style_for_layer(const, layer, style)
    _update(obj)


def add_text(module7, container, x: float, y: float, text: str,
             font_size: float = 5.0, width: float = 20.0, angle: float = 0.0,
             layer: str = "label", center: bool = True,
             api5_ctx: Optional[Api5Context] = None,
             latex: Optional[str] = None,
             entity_id: str = "<unknown>", italic: bool = False) -> None:
    """Add a single-line text object.

    When *center* is True (default) the incoming ``x, y`` are treated
    as centre-anchored Scene coordinates and converted to the
    bottom-left origin that KOMPAS ``DrawingText.X/Y`` expects.

    Text is treated as LaTeX by default.  Plain text is kept on the simpler
    API7 path as an optimization; LaTeX syntax and mathematical Unicode are
    compiled through API5 ``ksTextEx``.  The optional *latex* field is a
    backwards-compatible alias/override for callers that keep markup in a
    separate JSON property.
    """
    source = normalize_kompas_text(latex if latex is not None else text)
    text = normalize_kompas_text(text)
    has_latex_syntax = any(ch in source for ch in r"\\{}^_$")
    if latex is not None or contains_math_unicode(source) or has_latex_syntax or italic:
        if api5_ctx is None:
            raise RuntimeError(
                f"API5 context required for LaTeX text in entity {entity_id}"
            )
        # Text entities can precede arrowheads, so initialize API5 here
        # rather than relying on the separate leader-arrow path.
        api5_ctx._ensure()
        plan = (
            compile_latex_api5_exact(source, height=font_size)
            if latex is not None or has_latex_syntax
            else compile_unicode_text(source, height=font_size)
        )
        if italic:
            for line in plan.lines:
                for item in line.items:
                    if item.italic_override is None:
                        item.italic = True
        api5_ctx.add_text_plan(
            plan, center_x=x, center_y=y,
            entity_id=entity_id, angle=angle,
        )
        return

    # Plain-text API7 path.
    if center:
        kompas_x, kompas_y = kompas_text_origin_from_center(
            x, y, text, font_size
        )
    else:
        kompas_x, kompas_y = x, y
    est_width, _est_height = estimate_kompas_text_size(text, font_size)
    obj = container.DrawingTexts.Add()
    obj.X = float(kompas_x)
    obj.Y = float(kompas_y)
    obj.Height = float(font_size)
    obj.Width = float(max(width, est_width + 2.0))
    obj.Angle = float(angle)
    itext = _qi(module7, obj, "IText")
    itext.Str = str(text)
    _update(obj)


def write_table_cell_inline(
    module7,
    native_cell,
    inline_plan: TableCellInlinePlan,
):
    """Write one strict inline plan through an existing native cell ``IText``.

    KOMPAS creates the editable rich items when ``IText.Str`` receives its
    control string.  The initial ``'.'`` assignment only materializes the
    known base run so its explicit cell style can be set before parsing.  No
    ``ITextLine.Add``, ``Clear``, ``ITextItem.ItemType`` mutation, API5 call,
    or overlay ``DrawingText`` is allowed on this production path.  KOMPAS
    owns the smaller heights of the structured formula items; only native
    item type ``0`` receives the explicit cell height, while italic propagates
    to every parsed item.
    """
    text = _qi(module7, native_cell.Text, "IText")
    text.Str = "."
    try:
        initial_line = text.TextLines[0]
        initial_items = list(initial_line.TextItems)
    except Exception as exc:
        raise RuntimeError("KOMPAS cell IText did not expose its initial base run") from exc
    if not initial_items:
        raise RuntimeError("KOMPAS cell IText initial base run is empty")

    base_font = _qi(module7, initial_items[0], "ITextFont")
    base_font.Height = float(inline_plan.font_size)
    base_font.Italic = bool(inline_plan.italic)

    # This assignment is the only rich-text construction operation.  The
    # control string is compiled before COM is touched and never contains raw
    # Markdown ``$...$`` delimiters.
    text.Str = inline_plan.control_string
    try:
        line = text.TextLines[0]
        items = list(line.TextItems)
    except Exception as exc:
        raise RuntimeError("KOMPAS cell IText did not expose parsed text items") from exc

    if inline_plan.control_string and not items:
        raise RuntimeError("KOMPAS discarded the native table-cell control string")
    for item in items:
        font = _qi(module7, item, "ITextFont")
        font.Italic = bool(inline_plan.italic)
        try:
            item_type = int(item.ItemType)
        except (AttributeError, TypeError, ValueError):
            item_type = 0
        if item_type == 0:
            font.Height = float(inline_plan.font_size)
    return text


def add_table(module7, symbols, plan: TablePlan) -> None:
    """Create one native KOMPAS ``IDrawingTable`` from a validated plan.

    Unlike a line/text approximation, this is a real editable KOMPAS table:
    the grid belongs to ``ITable``, spans use ``ITableRange.CombineCells()``,
    and every cell owns its native ``IText`` object.
    """
    tables = symbols.DrawingTables
    drawing_table = tables.Add(
        len(plan.row_heights), len(plan.column_widths),
        plan.row_heights[0], plan.column_widths[0], 0,
    )
    drawing_table.FixedCellsSize = True
    drawing_table.X = float(plan.position[0])
    drawing_table.Y = float(plan.position[1])
    table = _qi(module7, drawing_table, "ITable")
    all_cells = table.Range(0, 0, len(plan.row_heights) - 1,
                            len(plan.column_widths) - 1)
    all_cells_format = _qi(module7, all_cells.CellsFormat, "ICellFormat")
    all_cells_format.ReadOnly = False
    # Range.CellsFormat.Width reports success but serializes equal columns;
    # width must be assigned through ICellFormat queried from every cell.
    try:
        for row in range(len(plan.row_heights)):
            for column, width in enumerate(plan.column_widths):
                cell_format = _qi(module7, table.Cell(row, column), "ICellFormat")
                cell_format.ReadOnly = False
                cell_format.Width = float(width)
        for row, height in enumerate(plan.row_heights):
            row_range = table.Range(row, 0, row, len(plan.column_widths) - 1)
            _qi(module7, row_range.CellsFormat, "ICellFormat").Height = float(height)
        for cell in plan.cells:
            if cell.row_span > 1 or cell.column_span > 1:
                merged = table.Range(
                    cell.row, cell.column,
                    cell.row + cell.row_span - 1,
                    cell.column + cell.column_span - 1,
                )
                if not merged.CombineCells():
                    raise RuntimeError(
                        f"KOMPAS failed to merge table {plan.entity_id!r} "
                        f"cell ({cell.row}, {cell.column})"
                    )
        for cell in plan.cells:
            write_table_cell_inline(
                module7, table.Cell(cell.row, cell.column), cell.inline_plan
            )
        if not drawing_table.Update():
            raise RuntimeError(f"KOMPAS failed to update table {plan.entity_id!r}")
    finally:
        all_cells_format.ReadOnly = True
    if not drawing_table.Update():
        raise RuntimeError(f"KOMPAS failed to finalize table {plan.entity_id!r}")


def add_polyline(container, const, points: Sequence[Tuple[float, float]], closed: bool,
                 style: str = "solid", layer: str = "filled") -> None:
    obj = container.PolyLines2D.Add()
    obj.Closed = bool(closed)
    obj.Style = resolve_style_for_layer(const, layer, style)
    for index, (x, y) in enumerate(points):
        ok = obj.AddPoint(int(index), float(x), float(y))
        if not ok:
            raise RuntimeError(f"PolyLine2D.AddPoint failed at index {index}")
    _update(obj)


def add_smooth_curve(
    container,
    const,
    points: Sequence[Sequence[float]],
    style: str = "solid",
    layer: str = "fixed",
    num_segments: int = 20,
) -> None:
    """Render a smoothCurve as an approximated polyline using Catmull-Rom spline.

    Uses existing add_polyline to draw the interpolated curve.
    """
    pts = [(float(p[0]), float(p[1])) for p in points]
    spline_pts = catmull_rom_spline(pts, num_segments=num_segments)
    add_polyline(container, const, spline_pts, closed=False, style=style, layer=layer)


def scene_entity_to_api(module7, container, const, entity: dict,
                        api5_ctx: Optional[Api5Context] = None,
                        offset: Tuple[float, float] = (0.0, 0.0),
                        symbols=None) -> None:
    entity = offset_entity(entity, offset) if offset != (0.0, 0.0) else dict(entity)
    ctype = entity.get('type')
    layer = entity.get('layer', 'fixed')
    style = entity.get('style', 'solid')
    if ctype == 'line':
        add_line(container, const,
                 entity['from'][0], entity['from'][1],
                 entity['to'][0], entity['to'][1],
                 style=style, layer=layer)
    elif ctype == 'circle':
        if entity.get('filled'):
            add_filled_circle(container, const,
                              entity['center'][0], entity['center'][1],
                              entity['radius'])
        else:
            add_circle(container, const,
                       entity['center'][0], entity['center'][1],
                       entity['radius'], style=style, layer=layer)
    elif ctype == 'arc':
        add_arc(container, const,
                entity['center'][0], entity['center'][1],
                entity['radius'],
                entity['startAngle'], entity['endAngle'],
                style=style, layer=layer,
                direction=entity.get('direction', False))
    elif ctype == 'text':
        add_text(module7, container,
                 entity['position'][0], entity['position'][1],
                 entity['text'],
                 font_size=entity.get('fontSize', 5.0),
                 width=entity.get('width', 20.0),
                 angle=entity.get('angle', 0.0),
                 layer=layer, center=True,
                 api5_ctx=api5_ctx,
                 latex=entity.get('latex'),
                 entity_id=entity.get('id', '<unknown>'))
    elif ctype == 'textBlock':
        validated = validate_text_block_entity(entity)
        layout = compile_text_block_plan(entity)
        if api5_ctx is None:
            raise RuntimeError(f"API5 context required for textBlock {validated.entity_id}")
        api5_ctx._ensure()
        api5_ctx.add_text_block_plan(
            layout.plan, validated.position[0], validated.position[1],
            validated.width, validated.entity_id, source_text=validated.text,
            italic=validated.italic,
        )
    elif ctype == 'table':
        if symbols is None:
            raise RuntimeError("KOMPAS symbols container required for table rendering")
        add_table(module7, symbols, compile_table_plan(entity))
    elif ctype == 'polygon':
        points = entity.get('points', [])
        if is_arrowhead_polygon(entity):
            base, tip = leader_arrow_base_and_tip_from_polygon(points)
            bx, by, tx, ty = compute_leader_base_and_tip(tip, base)
            ok = False
            if api5_ctx is not None:
                api5_ctx._ensure()
                ok = api5_ctx.add_leader_arrow(bx, by, tx, ty)
            if not ok:
                add_line(container, const, bx, by, tx, ty,
                         style='solid', layer='thin')
        else:
            add_polyline(container, const, points, closed=True, style=style, layer=layer)
    elif ctype == 'smoothCurve':
        points = [(float(p[0]), float(p[1])) for p in entity.get('points', [])]
        if len(points) < 2:
            return
        add_smooth_curve(container, const, points,
                         style=entity.get('style', 'solid'),
                         layer=entity.get('layer', 'fixed'))
    else:
        raise ValueError(f"Unsupported scene entity: {ctype!r}")


# ─── Drawing lifecycle ──────────────────────────────────────────────────────


def validate_payload_v2(payload: dict) -> None:
    # format/version are optional metadata; absent values mean the default v2
    # single-scene contract. Explicit incompatible values remain errors.
    payload.setdefault('format', 'tmm-scene')
    payload.setdefault('version', 2)
    if payload.get('format') != 'tmm-scene':
        raise ValueError("Unsupported payload format; expected 'tmm-scene'")
    if payload.get('version') != 2:
        raise ValueError(f"Unsupported payload version; expected 2, got {payload.get('version')!r}")
    if 'scenes' in payload:
        raise ValueError("v2 payload must not contain a 'scenes' array")
    if 'canvas' in payload:
        raise ValueError("v2 payload must not contain a 'canvas' key")
    if 'entities' not in payload or not isinstance(payload.get('entities'), list):
        raise ValueError("v2 payload must contain a top-level 'entities' list")
    # Super-scene sheet metadata is also validated before KOMPAS is opened.
    super_scene_sheet_spec(payload)
    # All strict Markdown/TeX/table validation runs before KOMPAS is connected.
    for entity in payload['entities']:
        if not isinstance(entity, dict):
            continue
        if entity.get('type') == 'textBlock':
            compile_text_block_plan(entity)
        elif entity.get('type') == 'table':
            compile_table_plan(entity)


def entity_requires_api5(entity: dict[str, Any]) -> bool:
    """Return whether an entity contains text that requires the API5 path."""
    ctype = entity.get('type')
    if ctype == 'textBlock':
        return True
    if ctype == 'table':
        return table_requires_api5(compile_table_plan(entity))
    if ctype != 'text':
        return False
    text = str(entity.get('text', ''))
    return bool(
        entity.get('italic', False) or entity.get('latex') is not None
        or contains_math_unicode(text)
        or any(ch in text for ch in r"\\{}^_$")
    )


def _close_own_document(doc) -> None:
    """Best-effort cleanup for the drawing this render operation created."""
    if doc is not None:
        try:
            doc.Close(False)
        except Exception:
            pass


def draw_scene_document(payload: dict, output_path: str,
                        visible: bool = True, keep_open: bool = False) -> str:
    validate_payload_v2(payload)
    # Keep all COM cleanup inside the apartment that owns it: closing after
    # CoUninitialize can leak a partial document when COM proxies are dead.
    with _ComApartment():
        doc = None
        try:
            module7, const, _api7, app = connect_kompas(visible=visible)
            doc_type = getattr(const, "ksDocumentDrawing", 1)
            doc = app.Documents.AddWithDefaultSettings(doc_type, bool(visible))
            time.sleep(0.2)
            # Configure the sheet before opening the active view.  The
            # super-scene coordinates are physical millimetres in y-up space;
            # changing the sheet, not the entity coordinates, preserves the
            # layout produced by tmm-render.
            configure_super_scene_sheet(doc, const, payload)
            _doc2d, view, container = open_active_view(module7, doc)
            symbols = _qi(module7, view, "ISymbols2DContainer")
            api5_ctx = Api5Context()
            # API5 can address only ActiveDocument2D. Bind the document while
            # the API7-created drawing is active, before any entity can switch
            # focus, and prove the cross-API identity by document reference.
            if any(entity_requires_api5(entity)
                   for entity in payload.get('entities', [])
                   if isinstance(entity, dict)):
                api5_ctx.bind_active_document(app, doc)
            for entity in payload.get('entities', []):
                scene_entity_to_api(module7, container, const, entity,
                                    api5_ctx=api5_ctx, symbols=symbols)
            output_path = os.path.abspath(output_path)
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            doc.SaveAs(output_path)
            if not os.path.exists(output_path):
                raise RuntimeError(f"SaveAs did not create file: {output_path}")
        except Exception:
            # This is the sole document created by this call; leave unrelated
            # user documents untouched while closing every partial render.
            _close_own_document(doc)
            raise
        else:
            if not keep_open:
                _close_own_document(doc)
            return output_path


def build_drawing(payload: dict, output_path: str,
                  visible: bool = True, keep_open: bool = False) -> str:
    return draw_scene_document(payload, output_path, visible=visible,
                               keep_open=keep_open)
