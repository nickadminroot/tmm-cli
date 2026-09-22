"""Measure primitive API5 text gabarits for incremental metrics calibration.

This is diagnostic-only. It deliberately probes tiny strings first: individual
GOST/Symbol characters, repeated characters, spaces, punctuation, and style
variants. Production rendering never imports this module and never uses COM
for estimation.

The KOMPAS document is kept open by default for visual inspection; pass
``--close`` only when the probe document should be closed explicitly.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pythoncom
from win32com.client import Dispatch, gencache

from tmm_scene_kompas.api5_text import _gabarit_xywh
from probe_kompas_api5_control_syntax import API5_GUID, API7_GUID, CONST_GUID, qi


_FONT_ITALIC = 0x40
_FONT_BOLD = 0x100


def connect():
    pythoncom.CoInitialize()
    module7 = gencache.EnsureModule(API7_GUID, 0, 1, 0)
    gencache.EnsureModule(API5_GUID, 0, 1, 0)
    const = gencache.EnsureModule(CONST_GUID, 0, 1, 0).constants
    raw7 = Dispatch("KOMPAS.Application.7")
    api7 = qi(module7, raw7, "IKompasAPIObject")
    app = api7.Application
    app.Visible = True
    doc = app.Documents.AddWithDefaultSettings(const.ksDocumentDrawing, True)
    raw5 = Dispatch("KOMPAS.Application.5")
    doc2d = raw5.ActiveDocument2D
    return module7, const, app, doc, doc2d, raw5


def text_param(raw5, const, x: float, y: float, text: str, height: float,
               font_name: str, bit_vector: int):
    value = raw5.GetParamStruct(const.ko_TextParam)
    value.Init()
    paragraph = raw5.GetParamStruct(const.ko_ParagraphParam)
    paragraph.Init()
    paragraph.x = float(x)
    paragraph.y = float(y)
    paragraph.height = float(height)
    paragraph.width = 500.0
    paragraph.ang = 0.0
    paragraph.hFormat = 0
    paragraph.vFormat = 0
    value.SetParagraphParam(paragraph)

    item = raw5.GetParamStruct(const.ko_TextItemParam)
    item.Init()
    item.s = text
    item.type = 0
    font = item.GetItemFont()
    font.fontName = font_name
    font.height = float(height)
    font.ksu = 1
    font.color = 0
    font.bitVector = int(bit_vector)
    item.SetItemFont(font)

    line = raw5.GetParamStruct(const.ko_TextLineParam)
    line.Init()
    items = line.GetTextItemArr()
    items.ksClearArray()
    items.ksAddArrayItem(-1, item)
    line.SetTextItemArr(items)
    lines = value.GetTextLineArr()
    lines.ksClearArray()
    lines.ksAddArrayItem(-1, line)
    value.SetTextLineArr(lines)
    return value


def primitive_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    gost_single = (
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "abcdefghijklmnopqrstuvwxyz"
        "АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"
        "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"
        "0123456789"
        " .,;:!?+-=*/()[]{}<>_"
    )
    for index, character in enumerate(gost_single):
        cases.append({"family": "single", "label": f"gost-{index:03d}",
                      "text": character, "font": "GOST type A", "style": "plain"})
    for index, character in enumerate("αβγΔΩ∑∫∞≤≥±×÷⊥∠"):
        cases.append({"family": "symbol-single", "label": f"symbol-{index:03d}",
                      "text": character, "font": "Symbol type A", "style": "plain"})

    runs = [
        ("AAAA", "GOST type A"), ("aaaa", "GOST type A"),
        ("АААА", "GOST type A"), ("аааа", "GOST type A"),
        ("0000", "GOST type A"), ("....", "GOST type A"),
        ("----", "GOST type A"), ("A A", "GOST type A"),
        ("a a", "GOST type A"), ("WMWM", "GOST type A"),
        ("iiii", "GOST type A"), ("αβαβ", "Symbol type A"),
    ]
    for character, font in (("A", "GOST type A"), ("a", "GOST type A"),
                            ("А", "GOST type A"), ("а", "GOST type A"),
                            ("0", "GOST type A"), (".", "GOST type A"),
                            ("-", "GOST type A"), ("W", "GOST type A"),
                            ("i", "GOST type A"), ("α", "Symbol type A")):
        for length in range(1, 9):
            cases.append({"family": "repeat", "label": f"repeat-{ord(character):04x}-{length:02d}",
                          "text": character * length, "font": font, "style": "plain"})
    for index, (text, font) in enumerate(runs):
        cases.append({"family": "run", "label": f"run-{index:03d}",
                      "text": text, "font": font, "style": "plain"})

    for style, bits in (("italic", _FONT_ITALIC), ("bold", _FONT_BOLD),
                        ("bold-italic", _FONT_BOLD | _FONT_ITALIC)):
        for index, text in enumerate(("A", "a", "А", "а", "0", "W")):
            cases.append({"family": "style", "label": f"{style}-{index:02d}",
                          "text": text, "font": "GOST type A", "style": style,
                          "bitVector": bits})
        for index, text in enumerate(("AAAA", "aaaa", "0000", "WWWW")):
            cases.append({"family": "style-run", "label": f"{style}-run-{index:02d}",
                          "text": text, "font": "GOST type A", "style": style,
                          "bitVector": bits})
    return cases


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default=os.path.join(
        os.environ.get("TEMP", "."), "tmm-scene-kompas-text-calibration"))
    parser.add_argument("--height", type=float, default=5.0)
    parser.add_argument("--close", action="store_true",
                        help="close the probe document after saving")
    args = parser.parse_args()
    out = Path(args.out_dir).absolute()
    out.mkdir(parents=True, exist_ok=True)

    module7, const, app, doc, doc2d, raw5 = connect()
    evidence: list[dict[str, Any]] = []
    y = 280.0
    for index, case in enumerate(primitive_cases()):
        x = 20.0 + (index % 8) * 22.0
        if index and index % 8 == 0:
            y -= 12.0
        try:
            reference = int(doc2d.ksTextEx(text_param(
                raw5, const, x, y, case["text"], args.height,
                case["font"], int(case.get("bitVector", 0))), 0))
            bounds = _gabarit_xywh(doc2d, raw5, const, reference)
            evidence.append({**case, "height": args.height,
                             "position": [x, y], "reference": reference,
                             "gabarit": bounds})
        except Exception as exc:  # retain all failures as probe evidence
            evidence.append({**case, "height": args.height,
                             "position": [x, y], "error": str(exc)})

    cdw = out / "text-calibration.cdw"
    doc.SaveAs(str(cdw))
    report = {
        "format": "tmm-kompas-text-calibration",
        "version": 1,
        "fontHeight": args.height,
        "cases": evidence,
        "cdw": str(cdw),
        "documentKeptOpen": not args.close,
    }
    report_path = out / "text-calibration.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2,
                                      default=str), encoding="utf-8")
    print(json.dumps({"report": str(report_path), "cdw": str(cdw),
                      "cases": len(evidence),
                      "measured": sum(item.get("gabarit") is not None
                                      for item in evidence)},
                     ensure_ascii=False, indent=2))
    if args.close:
        doc.Close(False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
