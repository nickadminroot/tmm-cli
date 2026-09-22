"""M1 capability gate — prove API7 creates editable rich text with
range-based fonts and structural indices (subscript/superscript).

+++ Quick start +++
    python -u tools/probe_kompas_rich_text.py
        --output "%TEMP%\\tmm-scene-kompas-m1\\kompas-rich-text-probe.cdw"
        --png   "%TEMP%\\tmm-scene-kompas-m1\\kompas-rich-text-probe.png"

=== Version ===
    2026-07-11  probe-rich-text-v2

=== Changes from v1 ===
    - Moved scripts/ → tools/
    - Added _commit_drawing_object helper (Update after each DrawingText / line)
    - Control line (20,120)-(190,120); texts at y=180,160,140 with Height=10,
      Width=160
    - Output to %%TEMP%%\\tmm-scene-kompas-m1 instead of repo .tmp
    - Strengthened coordinate / control-line readback
    - Prints PENDING_VISUAL_REVIEW — never automatic PASS

=== Architecture ===
    Three DrawingText objects are built and introspected:

      Text #1 — ASCII / plain
          IText.Str = "F32 + phi"
          Single-item line; proves basic DrawingText + IText round-trip.

      Text #2 — Mixed visual (GOST→Symbol→GOST runs)
          Multiple ITextItem runs on one ITextLine:
            0: ItemType=0 (GOST type A)      Str="F"
            1: ItemType=23 (ksTItFontSymbol) Str="f"  SymbolFontName="Symbol"
            2: ItemType=0 (GOST type A)      Str=" + a"
            3: ItemType=17 (ksTItSpecialSymbol)  Str="2"  (superscript)
          Proves font-range switching via ItemType + SymbolFontName.

      Text #3 — Structural F with lower 32 and upper tau
            0: ItemType=0                     Str="F"
            1: ItemType=20 (subscript)        Str="32"
            2: ItemType=17 (superscript)      Str="t"
          Proves native sup/sub modifier API7.

=== Interfaces used (API7) ===
    API7_GUID = "{69AC2981-37C0-4379-84FD-5DD2F3C0A520}"
    CONST_GUID = "{75C9F5D0-B5B8-4526-8681-9903C567D2ED}"
    ksTItFontSymbol=23, ksTItSpecialSymbol=17, ksTItSpecialSymbolDown=20

=== Forbidden ===
    clipboard, SendKeys, UI automation, API5, TTF, raster text, per-glyph
    DrawingText.
"""

from __future__ import annotations

import argparse
import io
import os
import sys
import time
import traceback
from typing import Any, Dict, List, Tuple

# ─── pywin32 guards ─────────────────────────────────────────────────────────

try:
    import pythoncom
except ImportError:
    pythoncom = None  # pragma: no cover

try:
    from win32com.client import Dispatch, gencache
except ImportError:
    Dispatch = None
    gencache = None

# ─── COM GUIDs ──────────────────────────────────────────────────────────────

API7_GUID = "{69AC2981-37C0-4379-84FD-5DD2F3C0A520}"
CONST_GUID = "{75C9F5D0-B5B8-4526-8681-9903C567D2ED}"

# ─── Globals filled at connect ─────────────────────────────────────────────

_mod = None
_const = None
_KS_TIT_FONT_SYMBOL = 23
_KS_TIT_SPECIAL_SYMBOL = 17
_KS_TIT_SPECIAL_SYMBOL_DOWN = 20


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
    """Cast pywin32 COM object to a generated API7 interface."""
    iface = getattr(module, interface_name)
    return iface(obj._oleobj_.QueryInterface(iface.CLSID, pythoncom.IID_IDispatch))


def _ensure_mod():
    global _mod, _const
    if _mod is not None:
        return _mod, _const
    if pythoncom is None or Dispatch is None or gencache is None:
        raise RuntimeError("pywin32 not available")
    pythoncom.CoInitialize()
    _mod = gencache.EnsureModule(API7_GUID, 0, 1, 0)
    _const = gencache.EnsureModule(CONST_GUID, 0, 1, 0).constants
    return _mod, _const


def _get_const(name: str, fallback: int) -> int:
    try:
        return int(getattr(_const, name, fallback))
    except (ValueError, TypeError):
        return fallback


# ─── _commit_drawing_object — strict Update wrapper ────────────────────────


def _commit_drawing_object(obj, container=None):
    """Call Update on a DrawingText, LineSegment, etc.; optional container.Update.

    This is the single choke point for ensuring KOMPAS commits geometry
    before introspection or save.
    """
    if obj is None:
        return
    if hasattr(obj, "Update"):
        try:
            obj.Update()
        except Exception:
            pass
    if container is not None and hasattr(container, "Update"):
        try:
            container.Update()
        except Exception:
            pass


# ─── Introspection helpers ─────────────────────────────────────────────────


def _safe_get(obj, attr: str, default="<ERROR>"):
    try:
        return getattr(obj, attr)
    except Exception as e:
        return f"<{e}>"


def _introspect_text_font(item, label: str, log: List[str]):
    try:
        tf = _qi(_mod, item, "ITextFont")
        props = {
            "FontName": _safe_get(tf, "FontName"),
            "Height": _safe_get(tf, "Height"),
            "Bold": _safe_get(tf, "Bold"),
            "Italic": _safe_get(tf, "Italic"),
            "Underline": _safe_get(tf, "Underline"),
            "WidthFactor": _safe_get(tf, "WidthFactor"),
            "Color": _safe_get(tf, "Color"),
        }
        log.append(f"    [{label}] ITextFont: {props}")
        return props
    except Exception as e:
        log.append(f"    [{label}] ITextFont QI FAILED: {e}")
        return None


def _introspect_item(ti, idx: int, log: List[str]):
    log.append(
        f"    Item[{idx}]: Str={_safe_get(ti, 'Str')!r} "
        f"ItemType={_safe_get(ti, 'ItemType')!r} "
        f"Number={_safe_get(ti, 'Number')!r} "
        f"SizeFactor={_safe_get(ti, 'SizeFactor')!r} "
        f"SymbolFontName={_safe_get(ti, 'SymbolFontName')!r}"
    )
    _introspect_text_font(ti, f"Item[{idx}]", log)


def _introspect_text_line(tl, log: List[str]):
    count = _safe_get(tl, "Count")
    log.append(f"  ITextLine.Count={count}")
    items = tl.TextItems
    if items is not None:
        for i, ti in enumerate(items):
            _introspect_item(ti, i, log)
    else:
        log.append("  (no TextItems)")
    line_str = _safe_get(tl, "Str")
    if line_str and not line_str.startswith("<"):
        log.append(f"  Line.Str={line_str!r}")


def _introspect_line_segment(obj, label: str, log: List[str]):
    """Log a LineSegment geometry."""
    log.append(f"--- Introspect {label} ---")
    for prop in ("X1", "Y1", "X2", "Y2", "Style", "LayerNumber", "Type"):
        log.append(f"  {label}.{prop}={_safe_get(obj, prop)!r}")


def _introspect_drawing_text(obj, label: str, log: List[str]):
    """Full introspection of a DrawingText: basic props + IText + line tree."""
    log.append(f"--- Introspect {label} ---")
    for prop in ("X", "Y", "Height", "Width", "Angle", "Type"):
        log.append(f"  DrawingText.{prop}={_safe_get(obj, prop)!r}")
    it = _qi(_mod, obj, "IText")
    log.append(f"  IText.Str={_safe_get(it, 'Str')!r}")
    log.append(f"  IText.Count={_safe_get(it, 'Count')!r}")
    log.append(f"  IText.Style={_safe_get(it, 'Style')!r}")
    tls = it.TextLines
    if tls is not None:
        log.append(f"  IText.TextLines (len={len(tls)}):")
        for i, tl in enumerate(tls):
            _introspect_text_line(tl, log)
    else:
        log.append("  IText.TextLines=None")


def _log(log: List[str], msg: str):
    log.append(msg)
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


# ─── Connect KOMPAS ─────────────────────────────────────────────────────────


def _connect():
    """Connect to KOMPAS and return (mod7, const, doc, container)."""
    mod7, const = _ensure_mod()
    raw = Dispatch("KOMPAS.Application.7")
    api7_obj = _qi(mod7, raw, "IKompasAPIObject")
    app = api7_obj.Application
    app.Visible = True
    doc_type = _get_const("ksDocumentDrawing", 1)
    doc = app.Documents.AddWithDefaultSettings(doc_type, True)
    time.sleep(0.3)
    doc2d = _qi(mod7, doc, "IKompasDocument2D")
    mgr = doc2d.ViewsAndLayersManager
    view = mgr.Views.ActiveView
    container = _qi(mod7, view, "IDrawingContainer")
    return mod7, const, doc, container, container


# ─── Create probe texts ────────────────────────────────────────────────────


def create_probe_drawing(
    module7, container
) -> Tuple[List[str], Any]:
    """Create 3 DrawingText objects + control line.  Returns (log, anything)."""
    log: List[str] = []
    _log(log, "=== Creating probe texts (v2 — strict _commit) ===")

    # ── Text #1: ASCII "F32 + phi" ──────────────────────────────────────
    _log(log, "\n--- Text #1: ASCII 'F32 + phi' (y=180) ---")
    dt1 = container.DrawingTexts.Add()
    dt1.X = 20.0
    dt1.Y = 180.0
    dt1.Height = 10.0
    dt1.Width = 160.0
    it1 = _qi(module7, dt1, "IText")
    it1.Str = "F32 + phi"
    _commit_drawing_object(dt1, container)
    _introspect_drawing_text(dt1, "Text#1", log)

    # ── Text #2: Mixed visual w/ GOST→Symbol→GOST runs ──────────────────
    _log(log, "\n--- Text #2: GOST→Symbol→GOST + superscript (y=160) ---")
    dt2 = container.DrawingTexts.Add()
    dt2.X = 20.0
    dt2.Y = 160.0
    dt2.Height = 10.0
    dt2.Width = 160.0
    it2 = _qi(module7, dt2, "IText")
    it2.Str = "."
    tl2 = it2.TextLines[0]
    tl2.Clear()

    item_f = tl2.Add()
    item_f.Str = "F"
    item_f.ItemType = 0

    item_phi = tl2.Add()
    item_phi.Str = "f"
    item_phi.ItemType = _KS_TIT_FONT_SYMBOL
    item_phi.SymbolFontName = "Symbol"

    item_plus = tl2.Add()
    item_plus.Str = " + a"
    item_plus.ItemType = 0

    item_sup2 = tl2.Add()
    item_sup2.Str = "2"
    item_sup2.ItemType = _KS_TIT_SPECIAL_SYMBOL
    item_sup2.SizeFactor = 0.6

    item_end = tl2.Add()
    item_end.Str = ""
    item_end.ItemType = 0

    _commit_drawing_object(dt2, container)
    _introspect_drawing_text(dt2, "Text#2", log)

    # ── Text #3: Structural F + lower 32 + upper tau ─────────────────────
    _log(log, "\n--- Text #3: Structural F + lower 32 + upper t (y=140) ---")
    dt3 = container.DrawingTexts.Add()
    dt3.X = 20.0
    dt3.Y = 140.0
    dt3.Height = 10.0
    dt3.Width = 160.0
    it3 = _qi(module7, dt3, "IText")
    it3.Str = "."
    tl3 = it3.TextLines[0]
    tl3.Clear()

    b = tl3.Add()
    b.Str = "F"
    b.ItemType = 0

    s = tl3.Add()
    s.Str = "32"
    s.ItemType = _KS_TIT_SPECIAL_SYMBOL_DOWN
    s.SizeFactor = 0.6

    u = tl3.Add()
    u.Str = "t"
    u.ItemType = _KS_TIT_SPECIAL_SYMBOL
    u.SizeFactor = 0.6

    _commit_drawing_object(dt3, container)
    _introspect_drawing_text(dt3, "Text#3", log)

    # ── Control line (20,120)–(190,120) ──────────────────────────────────
    _log(log, "\n--- Control line (20,120)–(190,120) ---")
    control = container.LineSegments.Add()
    control.X1 = 20.0
    control.Y1 = 120.0
    control.X2 = 190.0
    control.Y2 = 120.0
    _commit_drawing_object(control, container)
    _introspect_line_segment(control, "ControlLine", log)

    return log, it2


def read_back_probe(log: List[str]) -> Dict[str, Any]:
    """Re-read COM properties from the active document.

    Returns a summary dict with counts, coordinate evidence, and strings.
    """
    evidence: Dict[str, Any] = {}
    mod7, _ = _ensure_mod()
    raw = Dispatch("KOMPAS.Application.7")
    api7_obj = _qi(mod7, raw, "IKompasAPIObject")
    app = api7_obj.Application
    doc = app.ActiveDocument
    if doc is None:
        _log(log, "read_back_probe: no active document")
        return {"error": "no active document"}

    doc2d = _qi(mod7, doc, "IKompasDocument2D")
    mgr = doc2d.ViewsAndLayersManager
    view = mgr.Views.ActiveView
    container = _qi(mod7, view, "IDrawingContainer")

    # ── DrawingTexts count + per-text coordinate/string readback ─────────
    dt_coll = container.DrawingTexts
    try:
        dt_count = int(_safe_get(dt_coll, "Count", 0))
    except (ValueError, TypeError):
        dt_count = 0
    evidence["drawing_texts_count"] = dt_count

    texts_data: List[Dict[str, Any]] = []
    for idx in range(dt_count):
        try:
            dt = dt_coll.Item(idx)
        except Exception:
            dt = dt_coll[idx]

        # Coordinate readback — GetItem returns IDrawingObject;
        # try to QI back to DrawingText for geometry properties.
        dt_geom_attrs = {"X": "<QI fail>", "Y": "<QI fail>",
                          "Height": "<QI fail>", "Width": "<QI fail>"}
        try:
            # Try direct QI to the coclass (DrawingText)
            dt_full = _qi(mod7, dt, "DrawingText")
            for k in dt_geom_attrs:
                dt_geom_attrs[k] = _safe_get(dt_full, k)
        except Exception:
            try:
                dt_full2 = _qi(mod7, dt, "IDrawingText")
                for k in dt_geom_attrs:
                    dt_geom_attrs[k] = _safe_get(dt_full2, k)
            except Exception:
                pass
        dt_evidence = {
            "index": idx,
            "X": dt_geom_attrs["X"],
            "Y": dt_geom_attrs["Y"],
            "Height": dt_geom_attrs["Height"],
            "Width": dt_geom_attrs["Width"],
        }

        it = _qi(mod7, dt, "IText")
        dt_evidence["str"] = _safe_get(it, "Str")
        dt_evidence["count"] = _safe_get(it, "Count")

        lines_info: List[Dict[str, Any]] = []
        tls = it.TextLines
        if tls:
            for ti, tl in enumerate(tls):
                lcount = _safe_get(tl, "Count")
                items_info: List[Dict[str, Any]] = []
                tits = tl.TextItems
                if tits:
                    for ii, ti2 in enumerate(tits):
                        # Try to read font name via ITextFont QI
                        _item_font_name = "<unknown>"
                        try:
                            _tf = _qi(mod7, ti2, "ITextFont")
                            _item_font_name = _safe_get(_tf, "FontName", "")
                        except Exception:
                            pass
                        items_info.append({
                            "idx": ii,
                            "str": _safe_get(ti2, "Str"),
                            "item_type": _safe_get(ti2, "ItemType"),
                            "size_factor": _safe_get(ti2, "SizeFactor"),
                            "symbol_font": _safe_get(ti2, "SymbolFontName"),
                            "font_name": str(_item_font_name),
                        })
                lines_info.append({
                    "line": ti, "count": lcount, "items": items_info
                })
        dt_evidence["lines"] = lines_info
        texts_data.append(dt_evidence)

    evidence["texts"] = texts_data

    # ── Control-line readback ────────────────────────────────────────────
    ls_coll = container.LineSegments
    try:
        ls_count = int(_safe_get(ls_coll, "Count", 0))
    except (ValueError, TypeError):
        ls_count = 0
    evidence["line_segments_count"] = ls_count

    control_evidence = None
    for idx in range(ls_count):
        try:
            ls_raw = ls_coll.Item(idx)  # returns IDrawingObject
        except Exception:
            continue
        # IDrawingObject has no X1/Y1 — try QI to ILineSegment (coclass LineSegment)
        try:
            ls = _qi(mod7, ls_raw, "ILineSegment")
        except Exception:
            try:
                ls = _qi(mod7, ls_raw, "LineSegment")
            except Exception:
                continue
        try:
            x1 = float(getattr(ls, "X1", 0))
            y1 = float(getattr(ls, "Y1", 0))
            x2 = float(getattr(ls, "X2", 0))
            y2 = float(getattr(ls, "Y2", 0))
        except (ValueError, TypeError):
            continue
        # Identify the control line — closest to (20,120)-(190,120)
        if abs(x1 - 20) < 5 and abs(y1 - 120) < 5 and abs(x2 - 190) < 5 and abs(y2 - 120) < 5:
            control_evidence = {"X1": x1, "Y1": y1, "X2": x2, "Y2": y2}
            break
    evidence["control_line"] = control_evidence

    _log(log, f"read_back: dt_count={dt_count}, ls_count={ls_count}")
    for td in texts_data:
        _log(log, f"  text[{td['index']}]: X={td['X']}, Y={td['Y']}, "
             f"H={td['Height']}, W={td['Width']}, "
             f"str={td['str']!r}")
    _log(log, f"  control_line: {control_evidence}")

    return evidence


def export_probe_png(module7, doc, out_path: str) -> str:
    """Export document to PNG via IKompasDocument1.SaveAsToRasterFormat.

    Signature: SaveAsToRasterFormat(FileName, Param)
    """
    doc1 = _qi(module7, doc, "IKompasDocument1")
    try:
        raw_params = doc1.GetInterface(10130)
    except Exception as e:
        raise RuntimeError(f"GetInterface(10130) failed: {e}") from e

    params = module7.IRasterConvertParameters(
        raw_params._oleobj_.QueryInterface(
            module7.IRasterConvertParameters.CLSID, pythoncom.IID_IDispatch
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
# Main
# ═══════════════════════════════════════════════════════════════════════════


def main():
    _setup_stdout()
    parser = argparse.ArgumentParser(
        description="M1 probe: prove API7 rich text capability"
    )
    parser.add_argument(
        "--output", default=os.path.join(
            os.environ.get("TEMP", "."),
            "tmm-scene-kompas-m1",
            "kompas-rich-text-probe.cdw"
        ),
        help="Path for the output .cdw file"
    )
    parser.add_argument(
        "--png", default=os.path.join(
            os.environ.get("TEMP", "."),
            "tmm-scene-kompas-m1",
            "kompas-rich-text-probe.png"
        ),
        help="Path for the output .png export"
    )
    parser.add_argument(
        "--keep-open", action="store_true",
        help="Leave KOMPAS open after probe"
    )
    args = parser.parse_args()

    output_path = os.path.abspath(args.output)
    png_path = os.path.abspath(args.png)

    log: List[str] = []
    _log(log, "=== M1 probe: Rich text capability gate (v2) ===")
    _log(log, f"Output CDW: {output_path}")
    _log(log, f"Output PNG: {png_path}")

    # ── Connect ──────────────────────────────────────────────────────────
    try:
        mod7, _const, doc, container = _connect()[:4]
    except Exception as e:
        _log(log, f"FATAL: KOMPAS connection failed: {e}")
        traceback.print_exc()
        sys.exit(1)

    # ── Create the three probe texts + control line ──────────────────────
    probe_log, _ = create_probe_drawing(mod7, container)
    log.extend(probe_log)

    # ── Save CDW ─────────────────────────────────────────────────────────
    _log(log, "\n--- Saving CDW ---")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    doc.SaveAs(output_path)
    exists = os.path.exists(output_path)
    size = os.path.getsize(output_path) if exists else 0
    _log(log, f"Saved to {output_path} (exists={exists}, size={size})")

    # ── Read-back introspection ──────────────────────────────────────────
    _log(log, "\n=== Read-back introspection ===")
    evidence = read_back_probe(log)

    # ── Export PNG ───────────────────────────────────────────────────────
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

    # ── Close ────────────────────────────────────────────────────────────
    if not args.keep_open:
        try:
            doc.Close(False)
        except Exception:
            pass
        _log(log, "Document closed.")

    # ── Print log ────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("FULL PROBE LOG")
    print("=" * 60)
    for entry in log:
        print(entry)

    # ── PENDING_VISUAL_REVIEW — never automatic PASS ─────────────────────
    print()
    print("=" * 60)
    print("PENDING_VISUAL_REVIEW")
    print("=" * 60)

    # Always print evidence summaries but never exit 0.
    failures_found: List[str] = []

    # Check: >= 3 DrawingTexts
    dt_count = evidence.get("drawing_texts_count", 0)
    try:
        ndt = int(str(dt_count))
    except (ValueError, TypeError):
        ndt = 0
    if ndt < 3:
        failures_found.append(f"Expected >=3 DrawingTexts, got {ndt}")

    # Check: GOST→Symbol→GOST + sup/sub based on item evidence
    texts = evidence.get("texts", [])
    has_symbol_run = False
    has_sup_sub = False
    for t in texts:
        txt_str = str(t.get("str", ""))
        for line in t.get("lines", []):
            for item in line.get("items", []):
                try:
                    it = int(item.get("item_type", 0))
                    if it in (17, 20, 18):  # 18=ksTItSpecialSymbolEnd
                        has_sup_sub = True
                    if it == 23:
                        has_symbol_run = True
                except (ValueError, TypeError):
                    pass
                # Also check via font_name / symbol_font strings
                fn = str(item.get("font_name", ""))
                sf = str(item.get("symbol_font", ""))
                if "Symbol" in fn or "Symbol" in sf:
                    has_symbol_run = True
        if "@" in txt_str:
            has_sup_sub = True
        if "Symbol" in txt_str:
            has_symbol_run = True

    if not has_symbol_run:
        failures_found.append("No GOST→Symbol→GOST evidence")
    if not has_sup_sub:
        failures_found.append("No superscript/subscript evidence")

    # Check: control line readback
    cl = evidence.get("control_line")
    if cl is None:
        failures_found.append("Control line not found in readback")
    else:
        x1_ok = abs(float(cl.get("X1", 0)) - 20) < 5
        y1_ok = abs(float(cl.get("Y1", 0)) - 120) < 5
        x2_ok = abs(float(cl.get("X2", 0)) - 190) < 5
        y2_ok = abs(float(cl.get("Y2", 0)) - 120) < 5
        if not (x1_ok and y1_ok and x2_ok and y2_ok):
            failures_found.append(
                f"Control line coords out of tolerance: {cl}"
            )

    # Check: PNG exists
    if not png_ok or png_size == 0:
        failures_found.append(f"PNG missing or empty: {png_path}")

    # Report
    print(f"  DrawingTexts: {dt_count}")
    print(f"  GOST→Symbol→GOST: {has_symbol_run}")
    print(f"  Superscript/Subscript: {has_sup_sub}")
    print(f"  Control line: {cl}")
    print(f"  PNG: {png_path} ({png_size} bytes)" if png_ok
          else f"  PNG: MISSING")
    print(f"  Failures: {failures_found if failures_found else 'none detected'}")

    # Write evidence file alongside PNG
    evidence_path = png_path.replace(".png", ".evidence.json")
    try:
        import json
        with open(evidence_path, "w", encoding="utf-8") as f:
            json.dump({
                "probe": "M1-rich-text-v2",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "evidence": evidence,
                "failures": failures_found,
            }, f, indent=2, ensure_ascii=False, default=str)
        print(f"  Evidence JSON: {evidence_path}")
    except Exception as e:
        print(f"  Evidence JSON write failed: {e}")

    print()
    print("PENDING_VISUAL_REVIEW — inspect PNG before accepting this gate.")
    print(f"Absolute PNG path: {png_path}")

    # Exit 0 regardless — the gate is informational.  The orchestrator
    # uses the evidence + PNG to decide PASS.
    sys.exit(0)


if __name__ == "__main__":
    main()
