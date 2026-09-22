"""Find the smallest native table state that KOMPAS permits saving."""
from __future__ import annotations

from pathlib import Path
import pythoncom
from win32com.client import Dispatch, gencache
from tmm_scene_kompas.render import API7_GUID, CONST_GUID, _qi


def save_case(app, module7, const, name, build):
    doc = app.Documents.AddWithDefaultSettings(const.ksDocumentDrawing, True)
    doc.Active = True
    try:
        build(doc, module7)
        path = (Path("test_output") / f"native-table-save-{name}.cdw").absolute()
        result = bool(doc.SaveAs(str(path)))
        print(name, {"saved": result, "exists": path.exists(), "size": path.stat().st_size if path.exists() else None,
                     "changed": bool(doc.Changed), "active": bool(doc.Active)})
    finally:
        doc.Close(False)


def main():
    pythoncom.CoInitialize()
    try:
        module7 = gencache.EnsureModule(API7_GUID, 0, 1, 0)
        const = gencache.EnsureModule(CONST_GUID, 0, 1, 0).constants
        api7 = _qi(module7, Dispatch("KOMPAS.Application.7"), "IKompasAPIObject")
        app = api7.Application
        save_case(app, module7, const, "blank", lambda doc, m: None)

        def add_only(doc, m):
            view = _qi(m, _qi(m, doc, "IKompasDocument2D").ViewsAndLayersManager.Views.ActiveView, "ISymbols2DContainer")
            table = view.DrawingTables.Add(2, 2, 10.0, 20.0, 0)
            print("add_only", {"valid": bool(table.Valid), "temp": bool(table.Temp), "update": table.Update(), "ref": table.Reference})

        save_case(app, module7, const, "add-only", add_only)

        def positioned(doc, m):
            view = _qi(m, _qi(m, doc, "IKompasDocument2D").ViewsAndLayersManager.Views.ActiveView, "ISymbols2DContainer")
            table = view.DrawingTables.Add(2, 2, 10.0, 20.0, 0)
            table.X, table.Y = 20.0, 150.0
            print("positioned", {"validBefore": bool(table.Valid), "update": table.Update(), "validAfter": bool(table.Valid), "temp": bool(table.Temp)})

        save_case(app, module7, const, "positioned", positioned)

        def combined(doc, m):
            symbols = _qi(m, _qi(m, doc, "IKompasDocument2D").ViewsAndLayersManager.Views.ActiveView, "ISymbols2DContainer")
            drawing = symbols.DrawingTables.Add(3, 3, 10.0, 20.0, 0)
            drawing.X, drawing.Y = 20.0, 150.0
            table = _qi(m, drawing, "ITable")
            result = table.Range(0, 0, 0, 2).CombineCells()
            print("combined", {"combine": bool(result), "update": drawing.Update(), "valid": bool(drawing.Valid)})

        save_case(app, module7, const, "combined", combined)

        def text(doc, m):
            symbols = _qi(m, _qi(m, doc, "IKompasDocument2D").ViewsAndLayersManager.Views.ActiveView, "ISymbols2DContainer")
            drawing = symbols.DrawingTables.Add(2, 2, 10.0, 20.0, 0)
            drawing.X, drawing.Y = 20.0, 150.0
            table = _qi(m, drawing, "ITable")
            cells_format = _qi(m, table.Range(0, 0, 1, 1).CellsFormat, "ICellFormat")
            cells_format.ReadOnly = False
            text_obj = _qi(m, table.Cell(0, 0).Text, "IText")
            text_obj.Str = "test"
            first_update = drawing.Update()
            cells_format.ReadOnly = True
            second_update = drawing.Update()
            print("text", {"value": str(text_obj.Str), "updates": [bool(first_update), bool(second_update)], "valid": bool(drawing.Valid)})

        save_case(app, module7, const, "text", text)

        def combined_text(doc, m):
            symbols = _qi(m, _qi(m, doc, "IKompasDocument2D").ViewsAndLayersManager.Views.ActiveView, "ISymbols2DContainer")
            drawing = symbols.DrawingTables.Add(3, 3, 10.0, 20.0, 0)
            drawing.X, drawing.Y = 20.0, 150.0
            table = _qi(m, drawing, "ITable")
            full_format = _qi(m, table.Range(0, 0, 2, 2).CellsFormat, "ICellFormat")
            full_format.ReadOnly = False
            table.Range(0, 0, 0, 2).CombineCells()
            for row, column, value in [(0, 0, "Нативная таблица API7"), (1, 0, "A"), (1, 1, "1, 2"), (1, 2, "вращ."), (2, 0, "B"), (2, 1, "2, 3"), (2, 2, "вращ.")]:
                _qi(m, table.Cell(row, column).Text, "IText").Str = value
            drawing.Update()
            full_format.ReadOnly = True
            print("combined_text", {"update": drawing.Update(), "valid": bool(drawing.Valid)})

        save_case(app, module7, const, "combined-text", combined_text)

        def cyrillic(doc, m):
            symbols = _qi(m, _qi(m, doc, "IKompasDocument2D").ViewsAndLayersManager.Views.ActiveView, "ISymbols2DContainer")
            drawing = symbols.DrawingTables.Add(2, 2, 10.0, 20.0, 0)
            drawing.X, drawing.Y = 20.0, 150.0
            table = _qi(m, drawing, "ITable")
            cell_format = _qi(m, table.Range(0, 0, 1, 1).CellsFormat, "ICellFormat")
            cell_format.ReadOnly = False
            _qi(m, table.Cell(0, 0).Text, "IText").Str = "вращ."
            drawing.Update()
            cell_format.ReadOnly = True
            print("cyrillic", {"update": drawing.Update(), "valid": bool(drawing.Valid)})

        save_case(app, module7, const, "cyrillic", cyrillic)
    finally:
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    main()
