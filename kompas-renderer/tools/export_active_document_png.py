"""Export the active KOMPAS drawing to PNG and record API7 object counts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pythoncom
from win32com.client import Dispatch, gencache

API7_GUID = "{69AC2981-37C0-4379-84FD-5DD2F3C0A520}"
KS_OBJECT_RASTER_CONVERT_PARAMETERS = 10130
RASTER_FORMAT_PNG = 3


def qi(module, obj, interface_name):
    iface = getattr(module, interface_name)
    return iface(obj._oleobj_.QueryInterface(iface.CLSID, pythoncom.IID_IDispatch))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output")
    parser.add_argument("--dpi", type=int, default=180)
    parser.add_argument("--work-area", action="store_true")
    parser.add_argument("--close", action="store_true", help="Close only the exported active document")
    args = parser.parse_args()

    output = Path(args.output).absolute()
    output.parent.mkdir(parents=True, exist_ok=True)
    pythoncom.CoInitialize()
    try:
        module7 = gencache.EnsureModule(API7_GUID, 0, 1, 0)
        raw = Dispatch("KOMPAS.Application.7")
        api7 = qi(module7, raw, "IKompasAPIObject")
        doc = api7.Application.ActiveDocument
        if doc is None:
            raise RuntimeError("KOMPAS has no active document")

        doc2d = qi(module7, doc, "IKompasDocument2D")
        view = doc2d.ViewsAndLayersManager.Views.ActiveView
        container = qi(module7, view, "IDrawingContainer")
        counts = {}
        for name in ("LineSegments", "Circles", "Arcs", "DrawingTexts", "PolyLines2D"):
            collection = getattr(container, name, None)
            if collection is not None:
                counts[name] = int(collection.Count)
        symbols = qi(module7, view, "ISymbols2DContainer")
        drawing_tables = getattr(symbols, "DrawingTables", None)
        if drawing_tables is not None:
            counts["DrawingTables"] = int(drawing_tables.Count)

        doc1 = qi(module7, doc, "IKompasDocument1")
        api_obj = doc1.GetInterface(KS_OBJECT_RASTER_CONVERT_PARAMETERS)
        params = qi(module7, api_obj, "IRasterConvertParameters")
        params.Clear()
        params.RasterFormat = RASTER_FORMAT_PNG
        params.Resolution = int(args.dpi)
        params.Scale = 1.0
        params.SaveWorkArea = bool(args.work_area)
        params.Sheets = "1"
        ok = bool(doc1.SaveAsToRasterFormat(str(output), params))
        if not ok or not output.exists():
            raise RuntimeError(f"PNG export failed: return={ok}")

        report = {
            "png": str(output),
            "size": output.stat().st_size,
            "dpi": args.dpi,
            "workArea": bool(args.work_area),
            "counts": counts,
        }
        report_path = output.with_suffix(".report.json")
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if args.close:
            doc.Close(False)
        return 0
    finally:
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    raise SystemExit(main())
