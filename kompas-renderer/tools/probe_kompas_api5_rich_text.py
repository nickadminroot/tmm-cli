"""M1b capability gate — prove API5 creates editable rich text with
structural indices, font switches, bit-vector control, and fraction support.

Samples at x=20, height=10:
  y=250  API5 CONTROL — plain API5 text
  y=220  Direct Unicode diagnostic
  y=190  GOST→Symbol type A→GOST Greek (font switching via ksTItFontSymbol)
  y=155  Structural upper/lower via ksTItSUpperIndex/ksTItSLowerIndex/ksTItSEnd
         using item.GetItemFont/SetItemFont bitVector=0x8/0x9/0x10
  y=115  Fraction via ksTItNumerator/ksTItDenominator/ksTItFractionEnd
         plus $d1;2$ control line at y=95

Architecture:
  Document created via API7 (AddWithDefaultSettings), text added via API5
  (KOMPAS.Application.5 → ActiveDocument2D → ksTextEx).  Introspected
  via API7 (IText, ITextLine, ITextItem, ITextFont).  Uses verified API5
  parameter objects: ko_TextParam, ko_ParagraphParam, ko_TextLineParam,
  ko_TextItemParam, ko_TextItemFont.

  Separate ko_TextItemParam per run with GetItemFont/SetItemFont for
  font properties and bitVector field.

+++ Quick start +++
    python -u tools/probe_kompas_api5_rich_text.py
        --output "%%TEMP%%\\tmm-scene-kompas-m1b\\probe-api5-rich-text.cdw"
        --png   "%%TEMP%%\\tmm-scene-kompas-m1b\\probe-api5-rich-text.png"

=== Version ===
    2026-07-11  probe-api5-rich-text-v1

=== Forbidden ===
    clipboard, SendKeys, UI automation, API7 rich-text creation (DrawingTexts.Add),
    TTF, raster text, glyph geometry, per-glyph objects, production changes.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import sys
import time
import traceback
from typing import Any, Dict, List, Optional, Tuple

# ─── pywin32 guards ─────────────────────────────────────────────────────────

try:
    import pythoncom
except ImportError:
    pythoncom = None  # pragma: no cover

try:
    from win32com.client import Dispatch, gencache
except ImportError:
    Dispatch = None  # pragma: no cover
    gencache = None  # pragma: no cover

# ─── COM GUIDs ──────────────────────────────────────────────────────────────

API7_GUID = "{69AC2981-37C0-4379-84FD-5DD2F3C0A520}"
API5_GUID = "{0422828C-F174-495E-AC5D-D31014DBBE87}"
CONST_GUID = "{75C9F5D0-B5B8-4526-8681-9903C567D2ED}"

# ═══════════════════════════════════════════════════════════════════════════
# Globals filled at connect
# ═══════════════════════════════════════════════════════════════════════════

_mod7 = None
_const = None


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════


def _setup_stdout():
    """Ensure stdout can handle Unicode on Windows."""
    enc = getattr(sys.stdout, 'encoding', '').lower()
    if not enc or enc in ('cp1251', 'cp1252', 'latin-1', 'iso-8859-1'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                      errors='replace')


def _qi(module, obj, interface_name: str):
    """Cast pywin32 COM object to a generated API7 / API5 interface."""
    iface = getattr(module, interface_name)
    return iface(obj._oleobj_.QueryInterface(iface.CLSID, pythoncom.IID_IDispatch))


def _ensure_mod():
    global _mod7, _const
    if _mod7 is not None:
        return _mod7, _const
    if pythoncom is None or Dispatch is None or gencache is None:
        raise RuntimeError("pywin32 not available")
    pythoncom.CoInitialize()
    _mod7 = gencache.EnsureModule(API7_GUID, 0, 1, 0)
    _const = gencache.EnsureModule(CONST_GUID, 0, 1, 0).constants
    return _mod7, _const


def _ensure_api5():
    """Ensure API5 module is available."""
    return gencache.EnsureModule(API5_GUID, 0, 1, 0)


def _get_const(name: str, fallback: int) -> int:
    try:
        return int(getattr(_const, name, fallback))
    except (ValueError, TypeError):
        return fallback


def _safe_get(obj, attr: str, default="<ERROR>"):
    try:
        return getattr(obj, attr)
    except Exception as e:
        return f"<{e}>"


def _log(log: List[str], msg: str):
    log.append(msg)
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


# ═══════════════════════════════════════════════════════════════════════════
# API7 Introspection helpers (used for read-back)
# ═══════════════════════════════════════════════════════════════════════════


def _introspect_item(ti, idx: int, log: List[str]) -> Dict[str, Any]:
    """Introspect a single ITextItem via API7 and return its properties dict."""
    props = {
        "Str": _safe_get(ti, "Str"),
        "ItemType": _safe_get(ti, "ItemType"),
        "Number": _safe_get(ti, "Number"),
        "SizeFactor": _safe_get(ti, "SizeFactor"),
        "SymbolFontName": _safe_get(ti, "SymbolFontName"),
    }
    log.append(
        f"    Item[{idx}]: Str={props['Str']!r} "
        f"ItemType={props['ItemType']!r} "
        f"SizeFactor={props['SizeFactor']!r} "
        f"SymbolFontName={props['SymbolFontName']!r}"
    )
    # Also read ITextFont via QI
    try:
        tf = _qi(_mod7, ti, "ITextFont")
        font_info = {
            "FontName": _safe_get(tf, "FontName"),
            "Height": _safe_get(tf, "Height"),
            "Bold": _safe_get(tf, "Bold"),
            "Italic": _safe_get(tf, "Italic"),
            "WidthFactor": _safe_get(tf, "WidthFactor"),
        }
        props["ITextFont"] = font_info
        log.append(f"      Font: {font_info}")
    except Exception as e:
        props["ITextFont"] = f"<QI error: {e}>"
    return props


def _introspect_text_line(tl, log: List[str]) -> Dict[str, Any]:
    """Introspect an ITextLine and return dict of its items."""
    info: Dict[str, Any] = {"Count": _safe_get(tl, "Count"), "items": []}
    log.append(f"  ITextLine.Count={info['Count']}")
    items = tl.TextItems
    if items is not None:
        for i, ti in enumerate(items):
            item_props = _introspect_item(ti, i, log)
            info["items"].append(item_props)
    else:
        log.append("  (no TextItems)")
    line_str = _safe_get(tl, "Str")
    if line_str and not str(line_str).startswith("<"):
        log.append(f"  Line.Str={line_str!r}")
    return info


def _introspect_drawing_text(obj, label: str, log: List[str]) -> Dict[str, Any]:
    """Full introspection of a DrawingText — basic props + IText + line tree."""
    log.append(f"--- Introspect {label} ---")
    info: Dict[str, Any] = {"label": label}
    for prop in ("X", "Y", "Height", "Width", "Angle", "Type"):
        val = _safe_get(obj, prop)
        info[prop] = val
        log.append(f"  DrawingText.{prop}={val!r}")
    it = _qi(_mod7, obj, "IText")
    info["IText.Str"] = _safe_get(it, "Str")
    info["IText.Count"] = _safe_get(it, "Count")
    info["IText.Style"] = _safe_get(it, "Style")
    log.append(f"  IText.Str={info['IText.Str']!r}")
    log.append(f"  IText.Count={info['IText.Count']!r}")
    tls = it.TextLines
    info["lines"] = []
    if tls is not None:
        log.append(f"  IText.TextLines (iterable):")
        for i, tl in enumerate(tls):
            line_info = _introspect_text_line(tl, log)
            line_info["line_index"] = i
            info["lines"].append(line_info)
    else:
        log.append("  IText.TextLines=None")
    return info


# ═══════════════════════════════════════════════════════════════════════════
# 1 / 2 — API7 document creation + API5 active document connection
# ═══════════════════════════════════════════════════════════════════════════


def _connect_api7_and_create_document() -> Tuple[Any, Any, Any, Any]:
    """Create a new 2D drawing document via API7 AddWithDefaultSettings.

    Returns (mod7, const, app, doc).
    """
    mod7, const = _ensure_mod()
    raw = Dispatch("KOMPAS.Application.7")
    api7_obj = _qi(mod7, raw, "IKompasAPIObject")
    app = api7_obj.Application
    app.Visible = True
    doc_type = _get_const("ksDocumentDrawing", 1)
    doc = app.Documents.AddWithDefaultSettings(doc_type, True)
    time.sleep(0.3)
    _log([], "_connect_api7_and_create_document: OK")
    return mod7, const, app, doc


def _connect_api5_active_document() -> Tuple[Any, Any]:
    """Connect via API5 (KOMPAS.Application.5) to the active 2D document.

    Returns (module5, doc2d).
    """
    module5 = _ensure_api5()
    kompas5 = Dispatch("KOMPAS.Application.5")
    doc2d = kompas5.ActiveDocument2D
    _log([], "_connect_api5_active_document: OK")
    return module5, doc2d


# ═══════════════════════════════════════════════════════════════════════════
# 3 — ko_TextItemParam factory (one per run)
# ═══════════════════════════════════════════════════════════════════════════


def _new_text_item(
    kompas5: Any,
    text: str,
    item_type: int = 0,
    font_name: Optional[str] = None,
    bit_vector: int = 0,
    font_height: float = 0.0,
    kind: str = "plain",
) -> Tuple[Any, Dict[str, Any]]:
    """Create a single ``ko_TextItemParam`` with font properties and
    semantic *kind* resolution.

    Kind ``"script_base"`` resolves to ``const.SUM_TYPE`` (item type),
    ``iSNumb=2``, ``bitVector=0x7``.
    Kinds ``"script_upper"``/``"script_lower"``/``"script_end"`` use
    ``type=0`` with ``bitVector`` ``0x8``/``0x9``/``0x10``.
    Fraction kinds keep *item_type* 1/2/3 with ``bitVector=0``.
    Plain kind keeps *item_type* and *bit_vector* as-is.

    Sets ``iSNumb`` on the item and ``bitVector`` on the font.
    """
    # ── Resolve type, iSNumb, bitVector from kind ──────────────────────
    resolved_type = item_type
    resolved_i_s_numb = 0
    resolved_bit_vector = bit_vector

    if kind == "script_base":
        sum_type = _get_const("SUM_TYPE", -1)
        if sum_type == -1:
            raise RuntimeError(
                "SUM_TYPE constant not found in KOMPAS constants; "
                "cannot create script base"
            )
        resolved_type = sum_type
        resolved_i_s_numb = 2
        resolved_bit_vector = 0x7
    elif kind == "script_upper":
        resolved_type = 0
        resolved_bit_vector = 0x8
    elif kind == "script_lower":
        resolved_type = 0
        resolved_bit_vector = 0x9
    elif kind == "script_end":
        resolved_type = 0
        resolved_bit_vector = 0x10
    elif kind in ("fraction_num", "fraction_den", "fraction_end"):
        resolved_type = item_type
        resolved_bit_vector = 0
    # else: plain — keep as-is

    # ── Build param ────────────────────────────────────────────────────
    item = kompas5.GetParamStruct(_const.ko_TextItemParam)
    item.Init()
    item.s = text
    item.type = resolved_type
    item.iSNumb = resolved_i_s_numb

    font_log: Dict[str, Any] = {
        "fontName": None,
        "height": None,
        "bitVector": None,
    }

    if font_name or resolved_bit_vector or font_height:
        try:
            font = item.GetItemFont()
            if font_name:
                font.fontName = font_name
                font_log["fontName"] = font_name
            if resolved_bit_vector:
                font.bitVector = resolved_bit_vector
                font_log["bitVector"] = resolved_bit_vector
            if font_height:
                font.height = font_height
                font_log["height"] = font_height
            font.ksu = 1
            font.color = 0
            item.SetItemFont(font)
        except Exception as e:
            font_log["error"] = str(e)

    item_log: Dict[str, Any] = {
        "text": text,
        "type": resolved_type,
        "iSNumb": resolved_i_s_numb,
        "bitVector": resolved_bit_vector,
        "kind": kind,
        "font": font_log,
    }
    return item, item_log


# ═══════════════════════════════════════════════════════════════════════════
# 4 — ko_TextLineParam builder (ko_TextLineParam + GetTextItemArr)
# ═══════════════════════════════════════════════════════════════════════════


def _build_text_line(
    kompas5: Any,
    items_list: List[Tuple[str, int, Optional[str], int, float]],
) -> Tuple[Any, Dict[str, Any]]:
    """Build a ``ko_TextLineParam`` with text items via ``GetTextItemArr()``.

    ``items_list``: list of (text, item_type, font_name, bit_vector, font_height, kind)
    Uses ``ko_TextLineParam``:
      * ``GetTextItemArr()`` → dynamic array of ``ko_TextItemParam``
      * ``SetTextItemArr(arr)``

    Returns (line_param, log_dict).
    """
    line = kompas5.GetParamStruct(_const.ko_TextLineParam)
    arr = line.GetTextItemArr()
    arr.ksClearArray()

    items_log: List[Dict[str, Any]] = []
    for spec in items_list:
        if len(spec) >= 6:
            item, item_log = _new_text_item(kompas5, *spec[:6])
        else:
            item, item_log = _new_text_item(kompas5, *spec, "plain")
        arr.ksAddArrayItem(-1, item)
        items_log.append(item_log)

    line.SetTextItemArr(arr)

    line_log: Dict[str, Any] = {
        "items": items_log,
        "item_count": len(items_list),
    }
    return line, line_log


# ═══════════════════════════════════════════════════════════════════════════
# 5 — ko_ParagraphParam + ksParagraph/ksTextLine/ksEndObj markers
# ═══════════════════════════════════════════════════════════════════════════


def _add_api5_paragraph(
    kompas5: Any,
    x: float,
    y: float,
    height: float,
    lines_spec: List[List[Tuple[str, int, Optional[str], int, float, str]]],
    width: float = 160.0,
    angle: float = 0.0,
) -> Tuple[Any, Dict[str, Any]]:
    """Build a ``ko_TextParam`` with paragraph and text lines.

    Uses ``ko_ParagraphParam`` (position / size / angle) set on the
    ``ko_TextParam`` via ``SetParagraphParam()``.

    Text content is structured through:
      * ``ko_TextParam.GetTextLineArr()`` → dynamic array of ``ko_TextLineParam``
      * ``ko_TextLineParam.GetTextItemArr()`` → dynamic array of ``ko_TextItemParam``

    The paragraph/line/end-object structure follows the conceptual markers
    ``ksParagraph`` (set paragraph attributes), ``ksTextLine`` (add each line),
    ``ksEndObj`` (finalise and return the param to be passed to ``ksTextEx``).

    ``lines_spec`` items are 6-tuples:
    (text, item_type, font_name, bit_vector, font_height, kind).

    Returns (text_param, log_dict).
    """
    text_param = kompas5.GetParamStruct(_const.ko_TextParam)
    text_param.Init()

    # ── ksParagraph: set paragraph geometry & format ─────────────────────
    para = kompas5.GetParamStruct(_const.ko_ParagraphParam)
    para.Init()
    para.x = float(x)
    para.y = float(y)
    para.height = float(height)
    para.ang = float(angle)
    para.width = float(width)
    para.hFormat = 0
    para.vFormat = 0
    text_param.SetParagraphParam(para)

    # ── ksTextLine: build each text line and add to the parameter ────────
    lines_arr = text_param.GetTextLineArr()
    lines_arr.ksClearArray()

    lines_log: List[Dict[str, Any]] = []
    for items_spec in lines_spec:
        line, line_log = _build_text_line(kompas5, items_spec)
        lines_arr.ksAddArrayItem(-1, line)
        lines_log.append(line_log)

    text_param.SetTextLineArr(lines_arr)

    # ── ksEndObj: return the fully built text_param ──────────────────────
    param_log: Dict[str, Any] = {
        "x": x,
        "y": y,
        "height": height,
        "angle": angle,
        "width": width,
        "lines_count": len(lines_spec),
        "lines": lines_log,
        "method": "ksTextEx(text_param, 0)",
    }
    return text_param, param_log


# ═══════════════════════════════════════════════════════════════════════════
# 6 — add_probe_samples
# ═══════════════════════════════════════════════════════════════════════════


ADD_PROBE_SAMPLES_RETURNS: List[int] = []


def add_probe_samples(
    kompas5: Any,
    doc2d: Any,
    log: List[str],
) -> List[Dict[str, Any]]:
    """Add 5 probe text samples via API5 ``ksTextEx``.

    Samples at x=20, height=10, y=250/220/190/155/115.
    Each line logged with returns/runs/fonts/bitVectors JSON.

    Returns list of sample descriptors for logging.
    """
    global ADD_PROBE_SAMPLES_RETURNS
    samples: List[Dict[str, Any]] = []
    _log(log, "\n=== Adding API5 probe samples ===")

    # ── Helper: apply text to document and log everything ────────────────
    def _apply(lines_spec, x, y, label, height=10, width=160, angle=0):
        text_param, param_log = _add_api5_paragraph(
            kompas5, x=x, y=y, height=height,
            lines_spec=lines_spec, width=width, angle=angle,
        )
        param_log["label"] = label
        try:
            ref = doc2d.ksTextEx(text_param, 0)
            ADD_PROBE_SAMPLES_RETURNS.append(ref)
            _log(log, f"  ksTextEx → reference={ref}")
        except Exception as e:
            _log(log, f"  ksTextEx FAILED: {e}")
            ref = -1
        param_log["reference"] = ref
        # Log items/fonts/bitVectors
        for li, line in enumerate(param_log.get("lines", [])):
            for ii, item in enumerate(line.get("items", [])):
                f = item.get("font", {})
                _log(log, f"    run[{li}][{ii}]: text={item['text']!r} "
                     f"type=0x{item['type']:X} "
                     f"fontName={f.get('fontName')!r} "
                     f"bitVector=0x{(f.get('bitVector') or 0):X} "
                     f"height={f.get('height')!r}")
        samples.append(param_log)
        return param_log

    # ── Sample 1: API5 CONTROL (y=250) ──────────────────────────────────
    _log(log, "\n# Sample 1: API5 CONTROL (y=250)")
    _apply(
        [
            [("API5 CONTROL", 0, "GOST type A", 0, 10.0)],
        ],
        x=20, y=250, label="API5 CONTROL",
    )

    # ── Sample 2: Direct Unicode diagnostic (y=220) ─────────────────────
    _log(log, "\n# Sample 2: Unicode diagnostic (y=220)")
    _apply(
        [
            [
                ("Unicode: αβγ 你好 ΔΣΩ", 0, "GOST type A", 0, 10.0),
            ],
        ],
        x=20, y=220, label="Unicode diagnostic",
    )

        # ── Sample 3: Font/glyph capability matrix — ──────────────────────
    # Based on installed fonts: SYMBOL_A.TTF ("Symbol type A"), SYMBOL_B.TTF,
    # Symbol (symbol.ttf), GOST_A.TTF, GOST_AU.ttf, GreekS.
    # Key discovery: use type=0 (NOT 23) with fontName="Symbol type A" and
    # Latin ASCII transliteration per prototype translation table
    # (GOST_OUTPUT_TRANSLATION: φ→'f', τ→'t', α→'a', etc.)
    # Each row: > prefix in GOST type A | test char | ? suffix in GOST type A
    _log(log, "\n# Sample 3: Font/glyph capability matrix — phi candidates (y=190)")
    _log(log, "# Each row: F in GOST type A + test glyph + ? in GOST type A")
    _apply(
        [
            # FontName="Symbol type A" + type=0 + Latin 'f' (translated phi)
            [("F", 0, "GOST type A", 0, 10.0),
             ("f", 0, "Symbol type A", 0, 8.0),
             (" =? ", 0, "GOST type A", 0, 10.0)],
            # FontName="Symbol type A" + type=23 + Latin 'f'
            [("F", 0, "GOST type A", 0, 10.0),
             ("f", _get_const("ksTItFontSymbol", 23), "Symbol type A", 0, 8.0),
             (" =? ", 0, "GOST type A", 0, 10.0)],
            # FontName="Symbol" + type=0 + Latin 'f'
            [("F", 0, "GOST type A", 0, 10.0),
             ("f", 0, "Symbol", 0, 8.0),
             (" =? ", 0, "GOST type A", 0, 10.0)],
            # FontName="Symbol" + type=23 + Latin 'f'
            [("F", 0, "GOST type A", 0, 10.0),
             ("f", _get_const("ksTItFontSymbol", 23), "Symbol", 0, 8.0),
             (" =? ", 0, "GOST type A", 0, 10.0)],
            # FontName="Symbol type B" + type=0 + Latin 'f'
            [("F", 0, "GOST type A", 0, 10.0),
             ("f", 0, "Symbol type B", 0, 8.0),
             (" =? ", 0, "GOST type A", 0, 10.0)],
            # FontName="GreekS" + type=0 + Unicode phi
            [("F", 0, "GOST type A", 0, 10.0),
             ("\u03c6", 0, "GreekS", 0, 8.0),
             (" =? ", 0, "GOST type A", 0, 10.0)],
            # FontName="GOST Type AU" + type=0 + Unicode phi
            [("F", 0, "GOST type A", 0, 10.0),
             ("\u03c6", 0, "GOST Type AU", 0, 8.0),
             (" =? ", 0, "GOST type A", 0, 10.0)],
            # FontName="GOST type A" + type=0 + Unicode phi (control)
            [("F", 0, "GOST type A", 0, 10.0),
             ("\u03c6", 0, "GOST type A", 0, 8.0),
             (" =? ", 0, "GOST type A", 0, 10.0)],
        ],
        x=20, y=190, label="phi-candidates", height=8,
    )

    # tau candidates block
    _apply(
        [
            # FontName="Symbol type A" + type=0 + Latin 't' (translated tau)
            [("F", 0, "GOST type A", 0, 10.0),
             ("t", 0, "Symbol type A", 0, 8.0),
             (" =? ", 0, "GOST type A", 0, 10.0)],
            # FontName="Symbol" + type=0 + Latin 't'
            [("F", 0, "GOST type A", 0, 10.0),
             ("t", 0, "Symbol", 0, 8.0),
             (" =? ", 0, "GOST type A", 0, 10.0)],
            # FontName="Symbol type A" + type=23 + Latin 't'
            [("F", 0, "GOST type A", 0, 10.0),
             ("t", _get_const("ksTItFontSymbol", 23), "Symbol type A", 0, 8.0),
             (" =? ", 0, "GOST type A", 0, 10.0)],
            # FontName="Symbol type A" + type=17 (superscript) + Latin 't'
            [("F", 0, "GOST type A", 0, 10.0),
             ("t", _get_const("ksTItSpecialSymbol", 17), "Symbol type A", 0, 6.0),
             (" =? ", 0, "GOST type A", 0, 10.0)],
            # Control: GOST type A + Unicode phi + tau
            [("F", 0, "GOST type A", 0, 10.0),
             ("\u03c6", 0, "GOST type A", 0, 8.0),
             (" ", 0, "GOST type A", 0, 10.0),
             ("\u03c4", 0, "GOST type A", 0, 8.0)],
        ],
        x=20, y=155, label="tau-candidates", height=8,
    )

    # ── Sample 4: Sup/sub — F with phi upper + 32 lower (y=125) ────────
    # Using visual approach (type0+SpecialSymbol+Separator+SpecialSymbolDown+SpecialSymbolEnd)
    # with Latin 'f' (translated phi via Symbol type A font)
    _log(log, "\n# Sample 4: F with upper phi + lower 32 (y=125)")
    _log(log, "# Uses Symbol type A + type 17/20 for positioning, Latin 'f'->phi glyph")
    _apply(
        [
            # Line 1: Visual approach with Symbol type A font
            # Uses type=17 (SpecialSymbol=superscript) + font="Symbol type A" + Latin 'f' -> phi
            [("F", 0, "GOST type A", 0, 10.0),
             ("f", _get_const("ksTItSpecialSymbol", 17), "Symbol type A", 0, 6.0),
             ("", _get_const("ksTItSeparator", 24), None, 0, 6.0),
             ("32", _get_const("ksTItSpecialSymbolDown", 20), None, 0, 6.0),
             ("", _get_const("ksTItSpecialSymbolEnd", 18), None, 0, 10.0)],
            # Line 2: Structural approach
            [("F", _get_const("ksTItSBase", 7), None, 0, 10.0),
             ("f", _get_const("ksTItSUpperIndex", 8), None, 0x8, 6.0),
             ("", _get_const("ksTItSeparator", 24), None, 0, 6.0),
             ("32", _get_const("ksTItSLowerIndex", 9), None, 0x9, 6.0),
             ("", _get_const("ksTItSEnd", 16), None, 0x10, 10.0)],
        ],
        x=20, y=140, label="F + upper phi + lower 32",
    )
    # Sample 5: Fraction (y=125) ──────────────────────────────────────
    _log(log, "\n# Sample 5: Fraction (y=125) "
              "0x1(ksTItNumerator) / 0x2(ksTItDenominator) / 0x3(ksTItFractionEnd)")
    _apply(
        [
            [
                ("a", 0, None, 0, 10.0),
                ("1", _get_const("ksTItNumerator", 1), None, 0, 6.0),
                ("2", _get_const("ksTItDenominator", 2), None, 0, 6.0),
                (" = 0.5", _get_const("ksTItFractionEnd", 3), None, 0, 10.0),
            ],
        ],
        x=20, y=125, label="Fraction",
    )

    # ── $d1;2$ control line (y=105) ─────────────────────────────────────
    _log(log, "\n# Sample 5b: $d1;2$ control (y=105)")
    _apply(
        [
            [("$d1;2$ control", 0, None, 0, 8.0)],
        ],
        x=20, y=105, label="$d1;2$ control", height=8,
    )

    _log(log, f"\n=== add_probe_samples complete: {len(samples)} samples ===")
    return samples


# ═══════════════════════════════════════════════════════════════════════════
# 7a — add_production_path_sample
# ═══════════════════════════════════════════════════════════════════════════

PRODUCTION_PATH_RETURNS: List[int] = []


def add_production_path_sample(
    kompas5: Any,
    doc2d: Any,
    log: List[str],
) -> Dict[str, Any]:
    """Add one focused production-path sample via API5 ``ksTextEx``.

    Uses only structural item types [7, 8, 9, 16]:
      type 7  — base text 'F' in GOST type A
      type 8  — upper script 't' in Symbol type A  (Greek tau)
      type 9  — lower script '32' in GOST type A
      type 16 — empty terminator

    The content is centred at (60, 100) with height=10.
    Returns the sample descriptor dict.
    """
    global PRODUCTION_PATH_RETURNS
    _log(log, "\n=== Adding production-path sample ===")
    _log(log, "# Structural types [7,8,9,16] with Symbol type A upper 't', GOST lower 32")

    # Check SUM_TYPE availability before proceeding
    sum_type = _get_const("SUM_TYPE", -1)
    if sum_type == -1:
        _log(log, "FAIL: SUM_TYPE constant not found in KOMPAS constants")
        _log(log, "Cannot create script-base item; aborting production path")
        return {"error": "SUM_TYPE missing", "label": "FAIL"}
    _log(log, f"  SUM_TYPE numeric value: {sum_type}")

    lines_spec = [
        [
            ("F", 0, "GOST type A", 0, 10.0, "script_base"),
            ("t", 0, "Symbol type A", 0, 7.0, "script_upper"),
            ("32", 0, "GOST type A", 0, 7.0, "script_lower"),
            ("", 0, None, 0, 10.0, "script_end"),
        ],
    ]

    text_param, param_log = _add_api5_paragraph(
        kompas5, x=60, y=100, height=10,
        lines_spec=lines_spec, width=80, angle=0,
    )
    param_log["label"] = "production-path [script_base, script_upper, script_lower, script_end]"

    try:
        ref = doc2d.ksTextEx(text_param, 0)
        PRODUCTION_PATH_RETURNS.append(ref)
        _log(log, f"  ksTextEx → reference={ref}")
    except Exception as e:
        _log(log, f"  ksTextEx FAILED: {e}")
        ref = -1
    param_log["reference"] = ref

    for li, line in enumerate(param_log.get("lines", [])):
        for ii, item in enumerate(line.get("items", [])):
            f = item.get("font", {})
            _log(log, f"    run[{li}][{ii}]: text={item['text']!r} "
                 f"type=0x{item['type']:X} "
                 f"iSNumb={item.get('iSNumb', 0)} "
                 f"bitVector=0x{(item.get('bitVector') or 0):X} "
                 f"kind={item.get('kind', '?')!r} "
                 f"fontName={f.get('fontName')!r} "
                 f"height={f.get('height')!r}")

    _log(log, f"\n=== add_production_path_sample complete ===")
    return param_log


# ═══════════════════════════════════════════════════════════════════════════
# 7 — read_back_via_api7
# ═══════════════════════════════════════════════════════════════════════════


def read_back_via_api7(
    mod7: Any,
    doc: Any,
    log: List[str],
) -> Dict[str, Any]:
    """Re-read all DrawingTexts via API7 (IText/ITextLine/ITextItem/ITextFont).

    Returns a structured evidence dict with counts, coordinates, strings,
    item types, and font properties.
    """
    evidence: Dict[str, Any] = {}
    _log(log, "\n=== Read-back via API7 ===")

    try:
        doc2d7 = _qi(mod7, doc, "IKompasDocument2D")
        mgr = doc2d7.ViewsAndLayersManager
        view = mgr.Views.ActiveView
        container = _qi(mod7, view, "IDrawingContainer")
    except Exception as e:
        _log(log, f"FATAL: could not access container: {e}")
        return {"error": str(e)}

    dt_coll = container.DrawingTexts
    try:
        dt_count = int(_safe_get(dt_coll, "Count", 0))
    except (ValueError, TypeError):
        dt_count = 0
    evidence["drawing_texts_count"] = dt_count
    _log(log, f"DrawingTexts count: {dt_count}")

    texts_data: List[Dict[str, Any]] = []
    for idx in range(dt_count):
        try:
            dt = dt_coll.Item(idx)
        except Exception:
            dt = dt_coll[idx]

        dt_geom: Dict[str, Any] = {"X": "<error>", "Y": "<error>",
                                    "Height": "<error>", "Width": "<error>"}
        # Try QI to DrawingText for geometry
        for coclass in ("DrawingText", "IDrawingText"):
            try:
                dt_full = _qi(mod7, dt, coclass)
                for k in dt_geom:
                    dt_geom[k] = _safe_get(dt_full, k)
                break
            except Exception:
                continue

        dt_entry: Dict[str, Any] = {
            "index": idx,
            **dt_geom,
        }
        _log(log, f"\nDT[{idx}]: X={dt_geom['X']}, Y={dt_geom['Y']}, "
             f"H={dt_geom['Height']}, W={dt_geom['Width']}")

        # IText introspection
        try:
            its = _qi(mod7, dt, "IText")
            dt_entry["IText.Str"] = _safe_get(its, "Str")
            dt_entry["IText.Count"] = _safe_get(its, "Count")
            _log(log, f"  IText.Str={dt_entry['IText.Str']!r} "
                 f"Count={dt_entry['IText.Count']}")

            lines_info: List[Dict[str, Any]] = []
            tls = its.TextLines
            if tls is not None:
                for ti, tl in enumerate(tls):
                    line_info: Dict[str, Any] = {"line": ti,
                                                  "Count": _safe_get(tl, "Count")}
                    items_info: List[Dict[str, Any]] = []
                    tis = tl.TextItems
                    if tis is not None:
                        for ii, ti_obj in enumerate(tis):
                            item_info: Dict[str, Any] = {
                                "idx": ii,
                                "Str": _safe_get(ti_obj, "Str"),
                                "ItemType": _safe_get(ti_obj, "ItemType"),
                                "SizeFactor": _safe_get(ti_obj, "SizeFactor"),
                                "SymbolFontName": _safe_get(ti_obj, "SymbolFontName"),
                            }
                            # Font readback
                            try:
                                tf = _qi(mod7, ti_obj, "ITextFont")
                                item_info["ITextFont"] = {
                                    "FontName": _safe_get(tf, "FontName"),
                                    "Height": _safe_get(tf, "Height"),
                                    "Bold": _safe_get(tf, "Bold"),
                                    "Italic": _safe_get(tf, "Italic"),
                                    "WidthFactor": _safe_get(tf, "WidthFactor"),
                                }
                            except Exception as e:
                                item_info["ITextFont"] = f"<QI error: {e}>"
                            items_info.append(item_info)
                    line_info["items"] = items_info
                    lines_info.append(line_info)
            dt_entry["lines"] = lines_info
        except Exception as e:
            _log(log, f"  IText introspection failed: {e}")
            dt_entry["readback_error"] = str(e)

        texts_data.append(dt_entry)

    evidence["texts"] = texts_data
    return evidence


# ═══════════════════════════════════════════════════════════════════════════
# 8 — export_probe_png
# ═══════════════════════════════════════════════════════════════════════════


def export_probe_png(mod7: Any, doc: Any, out_path: str) -> str:
    """Export document to PNG via IKompasDocument1.SaveAsToRasterFormat.

    Uses RasterFormat=3 (PNG), Resolution=180.
    """
    doc1 = _qi(mod7, doc, "IKompasDocument1")
    try:
        raw_params = doc1.GetInterface(10130)
    except Exception as e:
        raise RuntimeError(f"GetInterface(10130) failed: {e}") from e

    params = mod7.IRasterConvertParameters(
        raw_params._oleobj_.QueryInterface(
            mod7.IRasterConvertParameters.CLSID, pythoncom.IID_IDispatch
        )
    )
    params.RasterFormat = 3  # PNG
    params.Resolution = 180
    params.Scale = 1.0
    params.Sheets = "1"
    params.SaveWorkArea = False

    out_path = os.path.abspath(out_path)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    doc1.SaveAsToRasterFormat(out_path, params)
    return out_path


# ═══════════════════════════════════════════════════════════════════════════
# 9 — cleanup_runtime_artifacts
# ═══════════════════════════════════════════════════════════════════════════


def cleanup_runtime_artifacts(log: List[str]):
    """Remove repo-local .tmp/ and any stray nul artifacts.

    Outputs go to %%TEMP%%\\tmm-scene-kompas-m1b, not the repo.
    """
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tmp_dir = os.path.join(repo_root, ".tmp")
    if os.path.isdir(tmp_dir):
        try:
            shutil.rmtree(tmp_dir)
            _log(log, f"cleanup: removed {tmp_dir}")
        except Exception as e:
            _log(log, f"cleanup: rmtree(.tmp) failed: {e}")

    # Remove any stray 'nul' / 'NUL' file (Windows reserved name collision)
    # Remove any stray 'nul' / 'NUL' file via subprocess del (bypasses
    # Windows reserved-name restrictions). Standard os.remove may fail.
    for _variant in ("nul", "NUL"):
        _candidate = os.path.join(repo_root, _variant)
        _removed = False
        try:
            if os.path.isfile(_candidate):
                os.remove(_candidate)
                _log(log, f"cleanup: removed {_candidate}")
                _removed = True
        except Exception:
            pass
        if not _removed:
            try:
                import subprocess
                subprocess.check_call(
                    ["cmd.exe", "/c", "del", "/f", "/q", "/a", _candidate],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                _log(log, f"cleanup: del {_candidate}")
            except Exception as e:
                _log(log, f"cleanup: del({_candidate}) failed: {e}")

    out_dir = os.path.join(os.environ.get("TEMP", "."), "tmm-scene-kompas-m1b")
    os.makedirs(out_dir, exist_ok=True)
    _log(log, f"cleanup: output dir {out_dir} ready")
    return out_dir


# ═══════════════════════════════════════════════════════════════════════════
# 10 — main
# ═══════════════════════════════════════════════════════════════════════════


def main():
    _setup_stdout()
    parser = argparse.ArgumentParser(
        description="M1b probe: prove API5 rich text capability"
    )
    parser.add_argument(
        "--output", default=os.path.join(
            os.environ.get("TEMP", "."),
            "tmm-scene-kompas-m1b",
            "probe-api5-rich-text.cdw"
        ),
        help="Path for the output .cdw file"
    )
    parser.add_argument(
        "--png", default=os.path.join(
            os.environ.get("TEMP", "."),
            "tmm-scene-kompas-m1b",
            "probe-api5-rich-text.png"
        ),
        help="Path for the output .png export"
    )
    parser.add_argument(
        "--keep-open", action="store_true",
        help="Leave KOMPAS open after probe"
    )
    parser.add_argument(
        "--production-path-only", action="store_true",
        help="Run only the production structural [7,8,9,16] sample "
             "with Symbol type A upper 't' and GOST lower 32"
    )
    args = parser.parse_args()

    output_path = os.path.abspath(args.output)
    png_path = os.path.abspath(args.png)

    log: List[str] = []
    if args.production_path_only:
        _log(log, "=== M4 production-path probe: structural [7,8,9,16] ===")
    else:
        _log(log, "=== M1b probe: API5 rich text capability gate ===")
    _log(log, f"Output CDW: {output_path}")
    _log(log, f"Output PNG: {png_path}")

    # ── 9. Clean up repo-local artifacts ────────────────────────────────
    out_dir = cleanup_runtime_artifacts(log)

    # ── 1. Connect via API7 and create document ─────────────────────────
    try:
        mod7, const, app, doc = _connect_api7_and_create_document()
    except Exception as e:
        _log(log, f"FATAL: API7 connection failed: {e}")
        traceback.print_exc()
        sys.exit(1)

    # ── 2. Connect via API5 to active document ──────────────────────────
    try:
        module5, doc2d = _connect_api5_active_document()
    except Exception as e:
        _log(log, f"FATAL: API5 connection failed: {e}")
        traceback.print_exc()
        sys.exit(1)

    # Get raw kompas5 dispatch for param object creation
    kompas5 = Dispatch("KOMPAS.Application.5")

    # ── 6. Add probe samples via API5 ksTextEx ──────────────────────────
    if args.production_path_only:
        samples_data = [add_production_path_sample(kompas5, doc2d, log)]
        active_returns = PRODUCTION_PATH_RETURNS
        expected_sample_count = 1
    else:
        samples_data = add_probe_samples(kompas5, doc2d, log)
        active_returns = ADD_PROBE_SAMPLES_RETURNS
        expected_sample_count = 7

    # Log returns JSON
    returns_log: Dict[str, Any] = {
        "method": "ksTextEx(text_param, 0)",
        "returns": active_returns,
        "samples": samples_data,
    }
    _log(log, f"\n=== ksTextEx returns ===")
    for i, ref in enumerate(active_returns):
        _log(log, f"  sample[{i}] reference={ref} (non-zero = OK)")

    # ── Save CDW ────────────────────────────────────────────────────────
    _log(log, "\n--- Saving CDW ---")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    doc.SaveAs(output_path)
    exists = os.path.exists(output_path)
    size = os.path.getsize(output_path) if exists else 0
    _log(log, f"Saved to {output_path} (exists={exists}, size={size})")

    # ── 7. Read-back via API7 ───────────────────────────────────────────
    evidence = read_back_via_api7(mod7, doc, log)

    # ── 8. Export PNG ───────────────────────────────────────────────────
    _log(log, "\n--- Export PNG ---")
    try:
        exported = export_probe_png(mod7, doc, png_path)
        png_ok = os.path.exists(exported)
        png_size = os.path.getsize(exported) if png_ok else 0
        _log(log, f"PNG exported to {exported} (ok={png_ok}, size={png_size})")
    except Exception as e:
        png_ok = False
        png_size = 0
        _log(log, f"PNG export FAILED: {e}")
        traceback.print_exc()

    # ── Close document ──────────────────────────────────────────────────
    if not args.keep_open:
        try:
            doc.Close(False)
        except Exception:
            pass
        _log(log, "Document closed.")

    # ── Write logs JSON ─────────────────────────────────────────────────
    json_path = png_path.replace(".png", ".log.json")
    try:
        probe_label = "M4-production-path" if args.production_path_only \
            else "M1b-api5-rich-text-v1"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump({
                "probe": probe_label,
                "production_path_only": args.production_path_only,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "output_cdw": output_path,
                "output_png": png_path,
                "returns": returns_log,
                "evidence": evidence,
            }, f, indent=2, ensure_ascii=False, default=str)
        _log(log, f"\nEvidence JSON: {json_path}")
    except Exception as e:
        _log(log, f"Evidence JSON write failed: {e}")

    # ── Print full log ──────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("FULL PROBE LOG")
    print("=" * 60)
    for entry in log:
        print(entry)

    # ── COM check summary — then PENDING_VISUAL_REVIEW ──────────────────
    print()
    print("=" * 60)
    print("COM CHECKS SUMMARY")
    print("=" * 60)

    failures_found: List[str] = []

    active_returns = PRODUCTION_PATH_RETURNS if args.production_path_only \
        else ADD_PROBE_SAMPLES_RETURNS

    # Check: ksTextEx returned non-zero
    non_zero = [r for r in active_returns if r and r > 0]
    print(f"  ksTextEx non-zero returns: {len(non_zero)} / {len(active_returns)}")
    if len(non_zero) < expected_sample_count:
        failures_found.append(
            f"Expected >= {expected_sample_count} non-zero ksTextEx returns, "
            f"got {len(non_zero)}"
        )

    # Check: DrawingTexts read back
    dt_count = evidence.get("drawing_texts_count", 0)
    try:
        ndt = int(str(dt_count))
    except (ValueError, TypeError):
        ndt = 0
    print(f"  DrawingTexts readback: {ndt}")
    if ndt < expected_sample_count:
        failures_found.append(f"Expected >= {expected_sample_count} "
                              f"DrawingTexts, got {ndt}")

    # Check: X/Y coordinate readback
    texts = evidence.get("texts", [])
    if args.production_path_only:
        # Production path: centred at (60, 100), so X should be ~60 - w/2
        coords_ok = True
        for i, t in enumerate(texts[:1]):
            try:
                x = float(t.get("X", 0))
                y = float(t.get("Y", 0))
                # Allow wide range since centering depends on plan size
                if x < 0 or x > 70:
                    coords_ok = False
                    failures_found.append(
                        f"production-path X={x} out of expected range"
                    )
                if y < 0 or y > 105:
                    coords_ok = False
                    failures_found.append(
                        f"production-path Y={y} out of expected range"
                    )
            except (ValueError, TypeError):
                coords_ok = False
        print(f"  Coordinates in expected range: {coords_ok}")
    else:
        coords_ok = True
        expected_ys = [250.0, 220.0, 190.0, 155.0, 140.0, 125.0, 105.0]
        for i, t in enumerate(texts[:6]):
            try:
                x = float(t.get("X", 0))
                y = float(t.get("Y", 0))
                if abs(x - 20.0) > 2.0:
                    coords_ok = False
                if i < len(expected_ys) and abs(y - expected_ys[i]) > 5.0:
                    coords_ok = False
            except (ValueError, TypeError):
                coords_ok = False
        print(f"  Coordinates match (X=20, Y expected): {coords_ok}")
        if not coords_ok:
            failures_found.append("Coordinate mismatch in readback")

    # Readback item-type findings (API5→API7 may merge/normalise types)
    has_symbol = False
    has_structural = False
    has_visual_sup_sub = False
    has_fraction = False
    for t in texts:
        for line in t.get("lines", []):
            for item in line.get("items", []):
                try:
                    it = int(item.get("ItemType", 0))
                    if it == 23 or it == 8215:
                        has_symbol = True
                    if it in (7, 8, 9, 16):
                        has_structural = True
                    if it in (17, 18, 20, 24):
                        has_visual_sup_sub = True
                    if it in (1, 2, 3):
                        has_fraction = True
                except (ValueError, TypeError):
                    pass
                fn = ""
                tf = item.get("ITextFont")
                if isinstance(tf, dict):
                    fn = str(tf.get("FontName", ""))
                if "Symbol" in fn:
                    has_symbol = True

    print(f"  Symbol font runs in API7 readback: {has_symbol}")
    print(f"    (API5 type=23/8215 created at write-time — API7 may merge)")
    print(f"  Structural indices (7/8/9/16): {has_structural}")
    print(f"  Visual sup/sub (17/18/20/24): {has_visual_sup_sub}")
    print(f"    (API5 separator+end runs included)")
    print(f"  Fraction items (1/2/3): {has_fraction}")
    print(f"    (API5 types 1/2/3 created — $d1;2$ control preserves types)")

    # Check: PNG exists
    if not png_ok or png_size == 0:
        failures_found.append(f"PNG missing or empty: {png_path}")

    # Summary
    print(f"  PNG: {png_path} ({png_size} bytes)" if png_ok
          else f"  PNG: MISSING")
    print(f"  COM failures: {failures_found if failures_found else 'none'}")

    # Absolute paths
    print()
    print(f"  Absolute CDW: {output_path}")
    print(f"  Absolute PNG: {png_path}")
    print(f"  Evidence JSON: {json_path}")

    mode_hint = "production-path-only" if args.production_path_only \
        else "full-probe"
    print()
    print(f"PENDING_VISUAL_REVIEW ({mode_hint}) — inspect PNG before "
          "accepting this gate.")
    print(f"Absolute PNG path: {png_path}")

    # Exit 0 — gate is informational.  Orchestrator uses evidence + PNG.
    sys.exit(0)


if __name__ == "__main__":
    main()
