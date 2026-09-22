"""Live KOMPAS regression probe for formula italic persistence.

The probe creates one API5 textBlock per case through the production exact
lowering, saves a CDW, closes the original document, reopens that CDW, and
fails unless every API7 text item reports ``ITextFont.Italic == True``.

Run on Windows with the KOMPAS Python environment.  The script deliberately
closes both documents and has no keep-open mode; terminate only the KOMPAS
processes created by the probe after the run if the COM server remains alive.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

import pythoncom
from win32com.client import Dispatch, gencache

from tmm_scene_kompas.api5_text import add_api5_text_block_plan
from tmm_scene_kompas.kompas_text import (
    TextLinePlan,
    TextRenderPlan,
    compile_latex_api5_exact,
)

API7_GUID = "{69AC2981-37C0-4379-84FD-5DD2F3C0A520}"
API5_GUID = "{0422828C-F174-495E-AC5D-D31014DBBE87}"
CONST_GUID = "{75C9F5D0-B5B8-4526-8681-9903C567D2ED}"

CASES = (
    ("base", r"V_H"),
    ("fraction", r"\frac{V_B}{l_{AB}}"),
    ("underline", r"\underline{V_H}"),
    ("underset", r"\underset{\perp HK}{\underline{V_H}}"),
    ("vec", r"\vec V_H"),
    ("text", r"\text{м/с}"),
    ("nested", r"\underset{\perp HK}{\underline{\vec V_H}}"),
)


def qi(module, obj, name):
    iface = getattr(module, name)
    return iface(obj._oleobj_.QueryInterface(iface.CLSID, pythoncom.IID_IDispatch))


def safe(obj, name):
    try:
        value = getattr(obj, name)
        return value if isinstance(value, (str, int, float, bool)) or value is None else str(value)
    except Exception as exc:  # pragma: no cover - COM-specific
        return f"<error: {exc}>"


def italicize(plan: TextRenderPlan) -> TextRenderPlan:
    return TextRenderPlan(
        lines=[TextLinePlan(
            [replace(item, italic=True) for item in line.items],
            height=line.height,
            break_after=line.break_after,
        ) for line in plan.lines],
        height=plan.height,
    )


def read_text(module7, drawing, index: int) -> dict:
    text = qi(module7, drawing, "IText")
    items = []
    for line_index, line in enumerate(text.TextLines):
        for item_index, item in enumerate(line.TextItems):
            entry = {
                "line": line_index,
                "index": item_index,
                "str": safe(item, "Str"),
                "itemType": safe(item, "ItemType"),
                "italic": None,
            }
            try:
                font = qi(module7, item, "ITextFont")
                entry["italic"] = safe(font, "Italic")
            except Exception as exc:  # pragma: no cover - COM-specific
                entry["fontError"] = str(exc)
            items.append(entry)
    return {
        "drawingTextIndex": index,
        "str": safe(text, "Str"),
        "items": items,
    }


def read_all(module7, document) -> list[dict]:
    document2d = qi(module7, document, "IKompasDocument2D")
    view = document2d.ViewsAndLayersManager.Views.ActiveView
    container = qi(module7, view, "IDrawingContainer")
    drawings = container.DrawingTexts
    return [read_text(module7, drawings.Item(index), index)
            for index in range(int(drawings.Count))]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir", type=Path,
        default=Path.home() / "tmm-kompas-cdw" / "formula-italic-regression",
    )
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

    pythoncom.CoInitialize()
    document = None
    reopened = None
    report = {"cases": [], "allItemsItalic": False, "formulaItemsFalse": None}
    try:
        module7 = gencache.EnsureModule(API7_GUID, 0, 1, 0)
        gencache.EnsureModule(API5_GUID, 0, 1, 0)
        const = gencache.EnsureModule(CONST_GUID, 0, 1, 0).constants
        raw7 = Dispatch("KOMPAS.Application.7")
        api7 = qi(module7, raw7, "IKompasAPIObject")
        app = api7.Application
        app.Visible = True
        document = app.Documents.AddWithDefaultSettings(const.ksDocumentDrawing, True)
        time.sleep(0.5)
        raw5 = Dispatch("KOMPAS.Application.5")
        document2d = raw5.ActiveDocument2D

        args.output_dir.mkdir(parents=True, exist_ok=True)
        cdw_path = args.output_dir / "formula-italic-regression.cdw"
        for case_index, (label, source) in enumerate(CASES):
            plan = italicize(compile_latex_api5_exact(source, height=5.0))
            reference = add_api5_text_block_plan(
                document2d, raw5, const, plan,
                top_left_x=20.0,
                top_left_y=260.0 - case_index * 25.0,
                width=120.0,
                entity_id=f"formula-italic-{label}",
            )
            report["cases"].append({
                "label": label,
                "source": source,
                "reference": int(reference),
                "planKinds": [item.kind for line in plan.lines for item in line.items],
            })

        document.SaveAs(str(cdw_path))
        if not cdw_path.is_file() or cdw_path.stat().st_size == 0:
            raise RuntimeError(f"KOMPAS SaveAs did not create a CDW: {cdw_path}")
        document.Close(False)
        document = None
        time.sleep(0.5)
        reopened = app.Documents.Open(str(cdw_path), True, False)
        time.sleep(0.5)
        readback = read_all(module7, reopened)
        reopened.Close(False)
        reopened = None

        all_items = [item for drawing in readback for item in drawing["items"]]
        false_items = [
            {"drawingTextIndex": drawing["drawingTextIndex"], **item}
            for drawing in readback
            for item in drawing["items"]
            if item["italic"] is not True
        ]
        report.update({
            "cdw": str(cdw_path),
            "drawingTexts": len(readback),
            "allItems": len(all_items),
            "allItemsItalic": bool(all_items) and not false_items,
            "formulaItemsFalse": len(false_items),
            "readback": readback,
        })
        report_path = args.output_dir / "formula-italic-regression.json"
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return 0 if report["allItemsItalic"] and report["formulaItemsFalse"] == 0 else 1
    except Exception as exc:  # pragma: no cover - live COM failure path
        report["error"] = repr(exc)
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return 1
    finally:
        for active in (reopened, document):
            if active is not None:
                try:
                    active.Close(False)
                except Exception:
                    pass
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    raise SystemExit(main())
