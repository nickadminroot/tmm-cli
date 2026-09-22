"""Minimal live creation probe for the API7 native DrawingTable collection."""
from __future__ import annotations

import json
from pathlib import Path

import pythoncom
from win32com.client import Dispatch, gencache

from tmm_scene_kompas.render import API7_GUID, CONST_GUID, _qi


def names(obj):
    return [name for name in dir(obj) if not name.startswith("_")]


def main() -> int:
    output = Path("test_output/native-drawing-table-add-probe.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    pythoncom.CoInitialize()
    doc = None
    try:
        module7 = gencache.EnsureModule(API7_GUID, 0, 1, 0)
        const = gencache.EnsureModule(CONST_GUID, 0, 1, 0).constants
        raw = Dispatch("KOMPAS.Application.7")
        api7 = _qi(module7, raw, "IKompasAPIObject")
        doc = api7.Application.Documents.AddWithDefaultSettings(const.ksDocumentDrawing, True)
        doc2d = _qi(module7, doc, "IKompasDocument2D")
        view = doc2d.ViewsAndLayersManager.Views.ActiveView
        symbols = _qi(module7, view, "ISymbols2DContainer")
        tables = symbols.DrawingTables

        table_object = tables.Add(2, 3, 10.0, 20.0, 0)
        table_object.X = 20.0
        table_object.Y = 150.0
        table_object.Update()
        table = _qi(module7, table_object, "ITable")
        cell = table.Cell(0, 0)
        report = {
            "tablesCount": int(tables.Count),
            "table": {
                "reference": int(table_object.Reference),
                "x": float(table_object.X),
                "y": float(table_object.Y),
                "rows": int(table.RowsCount),
                "columns": int(table.ColumnsCount),
                "members": names(table_object),
            },
            "cell": {
                "pythonType": type(cell).__name__,
                "members": names(cell),
                "row": int(cell.Row),
                "column": int(cell.Column),
                "text": str(cell.Text),
            },
        }
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
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
