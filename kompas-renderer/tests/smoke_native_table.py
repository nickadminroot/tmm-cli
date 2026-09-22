"""Live acceptance smoke for one native rich-text KOMPAS DrawingTable.

The production path assigns a precompiled KOMPAS control string to the
existing cell ``IText.Str``.  It never adds/clears ``ITextLine`` items and
never creates an overlay ``DrawingText``.  Run this with Windows Python and
KOMPAS; output artifacts are intentionally ignored by git.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


# Insert the converted WSL source path before importing the package. Windows
# Python may otherwise resolve an older editable checkout from another drive.
def _insert_current_src_from_argv() -> str:
    if len(sys.argv) < 2 or sys.argv[1] in {"-h", "--help"}:
        raise SystemExit(
            "usage: smoke_native_table.py WSL_SRC_PATH "
            "[--output-dir WINDOWS_OUTPUT_DIR] [--dpi DPI]"
        )
    source_path = sys.argv.pop(1)
    sys.path.insert(0, source_path)
    return source_path


CURRENT_SRC_PATH = _insert_current_src_from_argv()

import pythoncom  # noqa: E402
from win32com.client import Dispatch, gencache  # noqa: E402


def _setup_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


_setup_stdout()

from tmm_scene_kompas.render import API7_GUID, CONST_GUID, _qi, add_table  # noqa: E402
from tmm_scene_kompas.table import compile_table_plan  # noqa: E402


KS_OBJECT_RASTER_CONVERT_PARAMETERS = 10130
RASTER_FORMAT_PNG = 3
SOURCE_TEXT = "Очень длинное описание параметра $l_1$, мм"
EXPECTED_CONTROL_STRING = "Очень длинное описание параметра l$;1$, мм"
EXPECTED_ITEM_TYPES = [0, 4, 5, 6]
EXPECTED_COLUMN_WIDTHS = [35.0, 45.0]
EXPECTED_ROW_HEIGHTS = [12.0, 12.0]


def export_raster_file(module7, doc, output: Path, dpi: int = 180) -> None:
    doc1 = _qi(module7, doc, "IKompasDocument1")
    raw_params = doc1.GetInterface(KS_OBJECT_RASTER_CONVERT_PARAMETERS)
    params = _qi(module7, raw_params, "IRasterConvertParameters")
    params.Clear()
    params.RasterFormat = RASTER_FORMAT_PNG
    params.Resolution = int(dpi)
    params.Scale = 1.0
    params.SaveWorkArea = False
    params.Sheets = "1"
    doc1.SaveAsToRasterFormat(str(output), params)
    if not output.exists() or output.stat().st_size <= 0:
        raise RuntimeError("Native-table raster export failed")


def _read_rich_cell(module7, table, row: int, column: int) -> dict[str, Any]:
    cell = table.Cell(int(row), int(column))
    text = _qi(module7, cell.Text, "IText")
    line = text.TextLines[0]
    items = []
    for item in line.TextItems:
        font = _qi(module7, item, "ITextFont")
        items.append({
            "Str": str(item.Str),
            "ItemType": int(item.ItemType),
            "Height": float(font.Height),
            "Italic": bool(font.Italic),
            "WidthFactor": float(font.WidthFactor),
        })
    return {
        "cellStr": str(text.Str),
        "lineStr": str(line.Str),
        "items": items,
    }


def _handles(module7, doc) -> tuple[Any, Any, Any]:
    doc2d = _qi(module7, doc, "IKompasDocument2D")
    view = doc2d.ViewsAndLayersManager.Views.ActiveView
    symbols = _qi(module7, view, "ISymbols2DContainer")
    container = _qi(module7, view, "IDrawingContainer")
    return symbols, container, symbols.DrawingTables


def _counts(tables, container, drawing_table) -> dict[str, Any]:
    return {
        "DrawingTables": int(tables.Count),
        "DrawingTexts": int(container.DrawingTexts.Count),
        "Valid": bool(drawing_table.Valid),
    }


def _acceptance(
    readback: dict[str, Any], counts: dict[str, Any], dimensions: dict[str, Any]
) -> dict[str, bool]:
    items = readback["items"]
    types = [item["ItemType"] for item in items]
    return {
        "DrawingTables == 1": counts["DrawingTables"] == 1,
        "DrawingTexts == 0": counts["DrawingTexts"] == 0,
        "Valid == True": counts["Valid"] is True,
        "control string parsed/readable": readback is not None and bool(readback["items"]),
        "structured item types == [0,4,5,6]": types == EXPECTED_ITEM_TYPES,
        "base and tail Height == 5": (
            len(items) == 4
            and abs(items[0]["Height"] - 5.0) < 1e-6
            and abs(items[3]["Height"] - 5.0) < 1e-6
        ),
        "internal formula heights are KOMPAS-scaled": (
            len(items) == 4
            and all(abs(items[index]["Height"] - (10.0 / 3.0)) < 0.02 for index in (1, 2))
        ),
        "all native items italic": len(items) == 4 and all(item["Italic"] for item in items),
        "row/column counts == 2": dimensions["rows"] == 2 and dimensions["columns"] == 2,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="test_output")
    parser.add_argument("--dpi", type=int, default=180)
    args = parser.parse_args()
    out_dir = Path(args.output_dir).absolute()
    out_dir.mkdir(parents=True, exist_ok=True)
    cdw_path = out_dir / "native-table-smoke.cdw"
    png_path = out_dir / "native-table-smoke.png"
    report_path = out_dir / "native-table-smoke.report.json"

    pythoncom.CoInitialize()
    doc = None
    reopened = None
    report: dict[str, Any] = {
        "probe": "production-native-table-smoke",
        "sourcePathInsertedBeforeImports": CURRENT_SRC_PATH,
        "source": SOURCE_TEXT,
        "expectedControlString": EXPECTED_CONTROL_STRING,
        "expectedItemTypes": EXPECTED_ITEM_TYPES,
        "files": {},
    }
    try:
        module7 = gencache.EnsureModule(API7_GUID, 0, 1, 0)
        const = gencache.EnsureModule(CONST_GUID, 0, 1, 0).constants
        raw = Dispatch("KOMPAS.Application.7")
        api7 = _qi(module7, raw, "IKompasAPIObject")
        app = api7.Application
        app.Visible = True

        doc = app.Documents.AddWithDefaultSettings(const.ksDocumentDrawing, True)
        doc.Active = True
        symbols, container, tables = _handles(module7, doc)
        plan = compile_table_plan({
            "type": "table",
            "id": "production-smoke-table",
            "position": [30.0, 170.0],
            "columnWidths": EXPECTED_COLUMN_WIDTHS,
            "rowHeights": EXPECTED_ROW_HEIGHTS,
            "fontSize": 5.0,
            "italic": True,
            "cells": [
                {"row": 0, "column": 0, "colSpan": 2, "text": "Нативная таблица"},
                {"row": 1, "column": 0, "text": SOURCE_TEXT},
                {"row": 1, "column": 1, "text": "20"},
            ],
        })
        add_table(module7, symbols, plan)
        if int(tables.Count) != 1:
            raise RuntimeError(f"production add_table created {tables.Count!r} tables, expected 1")
        drawing_table = tables.Item(0)
        table = _qi(module7, drawing_table, "ITable")
        report["beforeReopen"] = _counts(tables, container, drawing_table)

        doc.SaveAs(str(cdw_path))
        export_raster_file(module7, doc, png_path, args.dpi)
        doc.Close(False)
        doc = None

        reopened = app.Documents.Open(str(cdw_path), True, False)
        reopened.Active = True
        symbols, container, tables = _handles(module7, reopened)
        if int(tables.Count) != 1:
            raise RuntimeError(f"reopened DrawingTables.Count is {tables.Count!r}, expected 1")
        drawing_table = tables.Item(0)
        table = _qi(module7, drawing_table, "ITable")
        report["afterReopen"] = _counts(tables, container, drawing_table)
        report["readback"] = _read_rich_cell(module7, table, 1, 0)
        report["dimensions"] = {
            "rows": int(table.RowsCount),
            "columns": int(table.ColumnsCount),
            "expectedColumnWidths": EXPECTED_COLUMN_WIDTHS,
            "expectedRowHeights": EXPECTED_ROW_HEIGHTS,
            # Aggregate ICellFormat returns zero after reopen on this wrapper,
            # so exact width/height writes remain covered by COM-free fakes and
            # the raster is authoritative live geometry evidence.
            "rangeAggregateReadback": {
                "columnWidths": [
                    float(_qi(module7, table.Range(0, column, 1, column).CellsFormat, "ICellFormat").Width)
                    for column in range(2)
                ],
                "rowHeights": [
                    float(_qi(module7, table.Range(row, 0, row, 1).CellsFormat, "ICellFormat").Height)
                    for row in range(2)
                ],
            },
        }
        report["visualAcceptanceRequired"] = [
            "top row is one merged visual cell",
            "long mixed formula is centered on one line",
            "long mixed formula is compressed only horizontally within the 35 mm cell",
        ]
        export_raster_file(module7, reopened, png_path, args.dpi)
        report["checks"] = _acceptance(
            report["readback"], report["afterReopen"], report["dimensions"]
        )
        report["files"] = {
            "cdw": {"path": str(cdw_path), "size": cdw_path.stat().st_size if cdw_path.exists() else 0},
            "png": {"path": str(png_path), "size": png_path.stat().st_size if png_path.exists() else 0},
        }
        report["checks"]["CDW non-empty"] = report["files"]["cdw"]["size"] > 0
        report["checks"]["PNG non-empty"] = report["files"]["png"]["size"] > 0
        report["ok"] = all(report["checks"].values())
        print(json.dumps(report, ensure_ascii=False, indent=2))
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0 if report["ok"] else 1
    except Exception as exc:
        report["error"] = repr(exc)
        report["ok"] = False
        print(json.dumps(report, ensure_ascii=False, indent=2))
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return 1
    finally:
        for candidate in (reopened, doc):
            if candidate is not None:
                try:
                    candidate.Close(False)
                except Exception:
                    pass
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    raise SystemExit(main())
