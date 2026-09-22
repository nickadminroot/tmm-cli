"""Live probe: API5 text-control syntax without clipboard/XML.

Exercises the documented ksText/ksTextLine/ksTextEx paths using the same
control strings that KOMPAS accepts in its text editor menus:
  $sup;sub$, $dnum;den$, $bnum;den$, size prefixes s/m/l,
  @/ line break, &NNN special-symbol insertion, and ^font...~ symbols.

Every sample is created through COM, read back through API7, saved as CDW,
and raster-exported.  This is an experiment only; no production code.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import pythoncom
from win32com.client import Dispatch, gencache

API7_GUID = "{69AC2981-37C0-4379-84FD-5DD2F3C0A520}"
API5_GUID = "{0422828C-F174-495E-AC5D-D31014DBBE87}"
CONST_GUID = "{75C9F5D0-B5B8-4526-8681-9903C567D2ED}"


def qi(module, obj, name):
    iface = getattr(module, name)
    return iface(obj._oleobj_.QueryInterface(iface.CLSID, pythoncom.IID_IDispatch))


def connect():
    pythoncom.CoInitialize()
    m7 = gencache.EnsureModule(API7_GUID, 0, 1, 0)
    m5 = gencache.EnsureModule(API5_GUID, 0, 1, 0)
    const = gencache.EnsureModule(CONST_GUID, 0, 1, 0).constants
    raw7 = Dispatch("KOMPAS.Application.7")
    api7 = qi(m7, raw7, "IKompasAPIObject")
    app = api7.Application
    app.Visible = True
    doc = app.Documents.AddWithDefaultSettings(const.ksDocumentDrawing, True)
    time.sleep(0.4)
    raw5 = Dispatch("KOMPAS.Application.5")
    doc2d = raw5.ActiveDocument2D
    return m7, m5, const, app, doc, doc2d, raw5


def make_item(raw5, const, text, font="GOST type A", height=8.0):
    item = raw5.GetParamStruct(const.ko_TextItemParam)
    item.Init()
    item.s = text
    item.type = 0
    font_obj = item.GetItemFont()
    font_obj.fontName = font
    font_obj.height = height
    font_obj.ksu = 1
    font_obj.color = 0
    item.SetItemFont(font_obj)
    return item


def make_text_param(raw5, const, x, y, text, height=8.0, width=180.0):
    tp = raw5.GetParamStruct(const.ko_TextParam)
    tp.Init()
    para = raw5.GetParamStruct(const.ko_ParagraphParam)
    para.Init()
    para.x, para.y = float(x), float(y)
    para.height, para.width = float(height), float(width)
    para.ang, para.hFormat, para.vFormat = 0.0, 0, 0
    tp.SetParagraphParam(para)
    line = raw5.GetParamStruct(const.ko_TextLineParam)
    line.Init()
    arr = line.GetTextItemArr()
    arr.ksClearArray()
    arr.ksAddArrayItem(-1, make_item(raw5, const, text, height=height))
    line.SetTextItemArr(arr)
    lines = tp.GetTextLineArr()
    lines.ksClearArray()
    lines.ksAddArrayItem(-1, line)
    tp.SetTextLineArr(lines)
    return tp


def safe(obj, name):
    try:
        return getattr(obj, name)
    except Exception as exc:
        return f"<error: {exc}>"


def readback(m7, doc):
    doc2d = qi(m7, doc, "IKompasDocument2D")
    view = doc2d.ViewsAndLayersManager.Views.ActiveView
    container = qi(m7, view, "IDrawingContainer")
    coll = container.DrawingTexts
    out = []
    for i in range(int(coll.Count)):
        obj = coll.Item(i)
        text = qi(m7, obj, "IText")
        entry = {"index": i, "X": safe(obj, "X"), "Y": safe(obj, "Y"),
                 "Height": safe(obj, "Height"), "IText.Str": safe(text, "Str"),
                 "IText.Count": safe(text, "Count"), "lines": []}
        try:
            for line in text.TextLines:
                li = {"Str": safe(line, "Str"), "Count": safe(line, "Count"), "items": []}
                if line.TextItems is not None:
                    for item in line.TextItems:
                        ii = {k: safe(item, k) for k in
                              ("Str", "ItemType", "Number", "SizeFactor", "SymbolFontName")}
                        try:
                            font = qi(m7, item, "ITextFont")
                            ii["FontName"] = safe(font, "FontName")
                            ii["FontHeight"] = safe(font, "Height")
                        except Exception as exc:
                            ii["font_error"] = str(exc)
                        li["items"].append(ii)
                entry["lines"].append(li)
        except Exception as exc:
            entry["read_error"] = str(exc)
        out.append(entry)
    return out


def export_png(m7, doc, path):
    d1 = qi(m7, doc, "IKompasDocument1")
    params = qi(m7, d1.GetInterface(10130), "IRasterConvertParameters")
    params.Clear()
    params.RasterFormat = 3
    params.Resolution = 180
    params.Scale = 1.0
    params.Sheets = "1"
    params.SaveWorkArea = False
    path.parent.mkdir(parents=True, exist_ok=True)
    if not d1.SaveAsToRasterFormat(str(path), params):
        raise RuntimeError("SaveAsToRasterFormat returned false")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=os.path.join(os.environ.get("TEMP", "."), "tmm-scene-kompas-control-syntax"))
    ap.add_argument("--keep-open", action="store_true")
    args = ap.parse_args()
    out = Path(args.out_dir).absolute()
    out.mkdir(parents=True, exist_ok=True)
    m7, m5, const, app, doc, doc2d, raw5 = connect()

    # Direct ksText is the key path: it receives a BSTR and is documented to
    # interpret control syntax.  ksTextLine/ksTextEx variants follow below.
    samples = [
        ("ksText_supsub", "F$t;32$"),
        ("ksText_sup_only", "a$2;$"),
        ("ksText_sub_only", "a$;2$"),
        ("ksText_supsub_small", "F$sτ;32$"),
        ("ksText_supsub_medium", "F$mτ;32$"),
        ("ksText_supsub_large", "F$lτ;32$"),
        ("ksText_fraction_d", "A$d1;2$B"),
        ("ksText_fraction_b", "A$b1;2$B"),
        ("ksText_fraction_small", "A$ds1;2$B"),
        ("ksText_line_break", "AA@/BB"),
        ("ksText_special_01", "10&01"),
        ("ksText_overline", "@+95~abc"),
        ("ksText_overline_scoped", "@+95~$(abc)$+tail"),
        ("ksText_underline_special", "@+96~abc"),
        ("ksText_underline_scoped", "@+96~$(abc)$+tail"),
        ("ksText_over_under_nested", "@+95~$(@+96~$(abc)$)$"),
        ("ksText_crossed_special", "@+169~abc"),
        ("ksText_sqrt_special", "@+98~$d1;3$"),
        ("ksText_cube_root_special", "@+99~$d1;3$"),
        ("ksText_deviation", "D$+0.1;-0.2$"),
        ("ksText_symbol_decimal", "alpha=^(Symbol type A)+945~"),
        ("ksText_symbol_hex", "beta=^(Symbol type A)*3B2~"),
        ("ksText_current_font_decimal", "alpha=^+945~"),
        ("ksText_flags_bold_italic_underline", "bold italic underline"),
    ]
    evidence = []
    y = 260.0
    for label, value in samples:
        try:
            # Last sample checks the documented ksText bit-vector path;
            # controls 0x40/0x100/0x400 are italic/bold/underline ON.
            flags = 0x40 | 0x100 | 0x400 if label.endswith("flags_bold_italic_underline") else 0
            ref = doc2d.ksText(20.0, y, 0.0, 8.0, 1.0, flags, value)
            evidence.append({"label": label, "method": "ksText", "input": value, "ref": ref, "y": y})
        except Exception as exc:
            evidence.append({"label": label, "method": "ksText", "input": value, "error": str(exc), "y": y})
        y -= 14.0

    # Same syntax in one ko_TextItemParam via ksTextLine.
    for label, value in [("ksTextLine_supsub", "F$t;32$"),
                         ("ksTextLine_fraction", "A$d1;2$B"),
                         ("ksTextLine_symbols", "alpha=^(Symbol type A)+945~")]:
        try:
            ref = doc2d.ksTextLine(make_item(raw5, const, value, height=8.0))
            evidence.append({"label": label, "method": "ksTextLine", "input": value, "ref": ref})
        except Exception as exc:
            evidence.append({"label": label, "method": "ksTextLine", "input": value, "error": str(exc)})

    # Same syntax through ksTextEx, proving that its text item parser differs
    # (or does not) from ksText; place at an explicit position.
    for i, (label, value) in enumerate([
        ("ksTextEx_supsub", "F$t;32$"),
        ("ksTextEx_fraction", "A$d1;2$B"),
        ("ksTextEx_symbols", "alpha=^(Symbol type A)+945~"),
    ]):
        try:
            tp = make_text_param(raw5, const, 20.0, 65.0 - i * 12.0, value)
            ref = doc2d.ksTextEx(tp, 0)
            evidence.append({"label": label, "method": "ksTextEx", "input": value, "ref": ref})
        except Exception as exc:
            evidence.append({"label": label, "method": "ksTextEx", "input": value, "error": str(exc)})

    cdw = out / "control-syntax.cdw"
    png = out / "control-syntax.png"
    doc.SaveAs(str(cdw))
    texts = readback(m7, doc)
    export_png(m7, doc, png)
    report = {"samples": evidence, "drawing_texts": texts,
              "cdw": str(cdw), "png": str(png)}
    (out / "control-syntax.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    if not args.keep_open:
        try:
            doc.Close(False)
        except Exception:
            pass


if __name__ == "__main__":
    main()
