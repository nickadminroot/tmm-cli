"""Measure one API5 formula structure at a time through live KOMPAS.

The probe is deliberately smaller than a textBlock corpus. Each case contains
one primitive or one TeX structure, is lowered through the production API5
compiler, and is measured with ksGetObjGabaritRect. It is diagnostic evidence
for the COM-free estimator only.
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

from tmm_scene_kompas.api5_text import _gabarit_xywh, _new_text_param
from tmm_scene_kompas.kompas_text import compile_latex_api5_exact
from probe_kompas_api5_control_syntax import API5_GUID, API7_GUID, CONST_GUID, qi


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
    return module7, const, app, doc, raw5.ActiveDocument2D, raw5


def cases() -> list[dict[str, Any]]:
    return [
        {"family": "plain", "label": "A", "tex": "A"},
        {"family": "plain", "label": "a", "tex": "a"},
        {"family": "plain", "label": "zero", "tex": "0"},
        {"family": "plain", "label": "plus", "tex": "+"},
        {"family": "symbol", "label": "alpha", "tex": r"\alpha"},
        {"family": "symbol", "label": "sum", "tex": r"\sum"},
        {"family": "symbol", "label": "integral", "tex": r"\int"},
        {"family": "symbol", "label": "perp", "tex": r"\perp"},
        {"family": "script", "label": "subscript", "tex": r"F_{1}"},
        {"family": "script", "label": "superscript", "tex": r"F^{2}"},
        {"family": "script", "label": "dual-script", "tex": r"F_{21}^{\tau}"},
        {"family": "script", "label": "long-subscript", "tex": r"F_{12345}"},
        {"family": "fraction", "label": "one-half", "tex": r"\frac{1}{2}"},
        {"family": "fraction", "label": "M-over-l", "tex": r"\frac{M}{l}"},
        {"family": "fraction", "label": "sum-over-sum", "tex": r"\frac{A+B}{C+D}"},
        {"family": "decorated", "label": "overline-F", "tex": r"\overline{F}"},
        {"family": "decorated", "label": "overline-long", "tex": r"\overline{ABC}"},
        {"family": "decorated", "label": "sqrt-x", "tex": r"\sqrt{x}"},
        {"family": "decorated", "label": "sqrt-long", "tex": r"\sqrt{A+B}"},
        {"family": "upright", "label": "mathrm-I", "tex": r"\mathrm{I}"},
        {"family": "mixed", "label": "force", "tex": r"F_{21}^{\tau}=\frac{M}{l}"},
        {"family": "mixed", "label": "kinematic", "tex": r"\omega=\frac{d\varphi}{dt}"},
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default=os.path.join(
        os.environ.get("TEMP", "."), "tmm-scene-kompas-formula-calibration"))
    parser.add_argument("--height", type=float, default=5.0)
    parser.add_argument("--close", action="store_true")
    args = parser.parse_args()
    out = Path(args.out_dir).absolute()
    out.mkdir(parents=True, exist_ok=True)

    module7, const, app, doc, doc2d, raw5 = connect()
    evidence: list[dict[str, Any]] = []
    for index, case in enumerate(cases()):
        x = 20.0 + (index % 6) * 30.0
        y = 270.0 - (index // 6) * 16.0
        try:
            plan = compile_latex_api5_exact(case["tex"], height=args.height)
            param = _new_text_param(raw5, const, x, y, args.height,
                                    plan.lines, width=500.0,
                                    track_styles=True)
            reference = int(doc2d.ksTextEx(param, 0))
            bounds = _gabarit_xywh(doc2d, raw5, const, reference)
            evidence.append({**case, "height": args.height,
                             "position": [x, y], "reference": reference,
                             "plan": [{"items": [item.content for item in line.items],
                                       "kinds": [item.kind for item in line.items]}
                                      for line in plan.lines],
                             "gabarit": bounds})
        except Exception as exc:
            evidence.append({**case, "height": args.height,
                             "position": [x, y], "error": str(exc)})

    cdw = out / "formula-calibration.cdw"
    doc.SaveAs(str(cdw))
    report = {"format": "tmm-kompas-formula-calibration", "version": 1,
              "fontHeight": args.height, "cases": evidence,
              "cdw": str(cdw), "documentKeptOpen": not args.close}
    report_path = out / "formula-calibration.json"
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
