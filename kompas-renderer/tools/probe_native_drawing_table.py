"""Discover the installed KOMPAS native DrawingTable automation surface.

Creates one private drawing, records API7/API5 table-related wrappers and
collections, then closes it without saving.  It deliberately does not call an
unknown Add method: use the report to choose one minimal creation attempt.
"""
from __future__ import annotations

import json
from pathlib import Path

import pythoncom
from win32com.client import Dispatch, gencache

from tmm_scene_kompas.render import API5_GUID, API7_GUID, CONST_GUID, _qi


def public_names(obj):
    if obj is None:
        return None
    return [name for name in dir(obj) if not name.startswith("_")]


def describe(obj):
    if obj is None:
        return None
    result = {"pythonType": type(obj).__name__, "members": public_names(obj)}
    for name in ("Count", "Reference", "Type", "DrawingObjectType"):
        if hasattr(obj, name):
            try:
                result[name] = getattr(obj, name)
            except Exception as exc:  # diagnostics must not stop early
                result[name + "Error"] = repr(exc)
    return result


def main() -> int:
    output = Path("test_output/native-drawing-table-probe.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    pythoncom.CoInitialize()
    doc = None
    try:
        module7 = gencache.EnsureModule(API7_GUID, 0, 1, 0)
        module5 = gencache.EnsureModule(API5_GUID, 0, 1, 0)
        const = gencache.EnsureModule(CONST_GUID, 0, 1, 0).constants
        raw7 = Dispatch("KOMPAS.Application.7")
        api7 = _qi(module7, raw7, "IKompasAPIObject")
        app = api7.Application
        doc = app.Documents.AddWithDefaultSettings(const.ksDocumentDrawing, True)
        doc2d = _qi(module7, doc, "IKompasDocument2D")
        view = doc2d.ViewsAndLayersManager.Views.ActiveView
        symbols = _qi(module7, view, "ISymbols2DContainer")

        collections = {}
        for name in ("DrawingTables", "LineDimensions", "RadialDimensions", "Leaders"):
            try:
                collections[name] = describe(getattr(symbols, name))
            except Exception as exc:
                collections[name] = {"error": repr(exc)}

        raw5 = Dispatch("KOMPAS.Application.5")
        kompas5 = module5.KompasObject(
            raw5._oleobj_.QueryInterface(module5.KompasObject.CLSID, pythoncom.IID_IDispatch)
        )
        active5 = kompas5.ActiveDocument2D()
        report = {
            "module7TableNames": [name for name in dir(module7) if "Table" in name],
            "constantTableNames": [name for name in dir(const) if "Table" in name],
            "symbols": describe(symbols),
            "collections": collections,
            "api5DocumentTableNames": [name for name in public_names(active5) if "table" in name.lower()],
            "api5KompasTableNames": [name for name in public_names(kompas5) if "table" in name.lower()],
        }
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return 0
    finally:
        if doc is not None:
            try:
                doc.Close(False)
            except Exception:
                pass
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    raise SystemExit(main())
