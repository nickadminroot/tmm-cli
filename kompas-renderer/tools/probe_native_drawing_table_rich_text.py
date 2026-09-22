"""Bounded live probe for rich text owned by one native DrawingTable cell.

This is an API7-only capability probe.  It never creates a DrawingText and it
never imports or calls API5.  The source checkout must be passed first so the
Windows interpreter imports this WSL checkout rather than another editable
copy::

    /mnt/c/Windows/py.exe -3.14 -u probe_native_drawing_table_rich_text.py \
        "$(wslpath -w src)" --output-dir "$(wslpath -w test_output)"

The default run executes four isolated private-document cases in this order:

1. ``item-update`` — the existing Clear()+Add path, with ITextItem.Update().
2. ``reuse-initial`` — reuse the known initial TextItems[0], then Add the
   remaining runs; no item Update, isolating the empty-item hypothesis.
3. ``geometry-first`` — update the table after geometry is complete, then
   write the rich cell and do not call IDrawingTable.Update() again; each item
   is updated.
4. ``strict`` — the final acceptance path combines the successful lifecycle
   hypotheses and remains the last/default case.

Every case creates one private table, saves a CDW, closes it, reopens that CDW,
reads the known single table and cell back, and exports the reopened document
to PNG.  No unknown collection indices are probed: the only table collection
index is ``Item(0)`` after a strict ``Count == 1`` check, and the only text
indices are the known initial ``TextLines[0]``/``TextItems[0]`` paths.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path
from typing import Any


# Keep this before importing tmm_scene_kompas.  Windows Python can otherwise
# silently load a different editable checkout from its own sys.path.
def _insert_current_src_from_argv() -> str:
    if len(sys.argv) < 2:
        raise SystemExit(
            "usage: probe_native_drawing_table_rich_text.py WSL_SRC_PATH "
            "[--output-dir WINDOWS_OUTPUT_DIR] [--case all|item-update|"
            "reuse-initial|geometry-first|strict]"
        )
    if sys.argv[1] in {"-h", "--help"}:
        raise SystemExit(
            "usage: probe_native_drawing_table_rich_text.py WSL_SRC_PATH "
            "[--output-dir WINDOWS_OUTPUT_DIR] [--case all|item-update|"
            "reuse-initial|geometry-first|strict]"
        )
    src_path = sys.argv.pop(1)
    sys.path.insert(0, src_path)
    return src_path


CURRENT_SRC_PATH = _insert_current_src_from_argv()

import pythoncom  # noqa: E402
from win32com.client import Dispatch, gencache  # noqa: E402

from tmm_scene_kompas.render import (  # noqa: E402
    API7_GUID,
    CONST_GUID,
    _qi,
    write_table_cell_inline,
)
from tmm_scene_kompas.table import compile_table_cell_inline_plan  # noqa: E402


SOURCE_TEXT = "Длина $l_1$, мм"
CONTROL_STRING = "Длина l$;1$, мм"
RUN_SPECS = (
    {"content": "Длина ", "item_type": 0, "kind": "plain"},
    {"content": "l", "item_type": 0, "kind": "plain"},
    {
        "content": "1",
        "item_type": "subscript",
        "kind": "subscript",
        "size_factor": 0.6,
    },
    {"content": ", мм", "item_type": 0, "kind": "plain"},
)

# The order is intentional: strict is always the final case.
CASE_SPECS = (
    {
        "name": "item-update",
        "hypothesis": "H1",
        "description": (
            "Keep Clear()+Add, call ITextItem.Update() after Str/ItemType/"
            "font for every run, then update the table."
        ),
        "reuse_initial_item": False,
        "geometry_first": False,
        "item_update": True,
        "update_after_rich": True,
    },
    {
        "name": "reuse-initial",
        "hypothesis": "H2",
        "description": (
            "Reuse the initial ITextLine.TextItems[0] instead of Clear(), "
            "then Add only the remaining runs; do not call item Update."
        ),
        "reuse_initial_item": True,
        "geometry_first": False,
        "item_update": False,
        "update_after_rich": True,
    },
    {
        "name": "geometry-first",
        "hypothesis": "H3",
        "description": (
            "Finalize table geometry with one table Update first, then "
            "populate rich cell items, call item Update, and never update "
            "the table after the rich write."
        ),
        "reuse_initial_item": False,
        "geometry_first": True,
        "item_update": True,
        "update_after_rich": False,
    },
    {
        "name": "control-string",
        "hypothesis": "known control-string check",
        "description": (
            "Set the exact known index control string on the existing cell "
            "IText.Str, then perform one table Update and save/reopen/readback."
        ),
        "reuse_initial_item": False,
        "geometry_first": False,
        "item_update": False,
        "update_after_rich": True,
        "control_string": True,
    },
    {
        "name": "strict",
        "hypothesis": "H1+H2+H3+H4",
        "description": (
            "Final strict path: geometry first, reuse initial item, use the "
            "successful DrawingText mutation order on the existing cell IText, "
            "call every ITextItem.Update(), and avoid a post-rich table Update."
        ),
        "reuse_initial_item": True,
        "geometry_first": True,
        "item_update": True,
        "update_after_rich": False,
    },
)
CASE_BY_NAME = {case["name"]: case for case in CASE_SPECS}
OUTPUT_STEMS = {
    "item-update": "native-table-rich-text-item-update",
    "reuse-initial": "native-table-rich-text-reuse-initial",
    "geometry-first": "native-table-rich-text-geometry-first",
    "control-string": "native-table-rich-text-control-string",
    # Preserve the original focused-probe artifact names for the final case.
    "strict": "native-table-rich-text",
}

RASTER_PARAMETERS_INTERFACE = 10130
RASTER_FORMAT_PNG = 3
TABLE_ROWS = 1
TABLE_COLUMNS = 1
TABLE_CELL_WIDTH = 60.0
TABLE_CELL_HEIGHT = 20.0
TABLE_X = 40.0
TABLE_Y = 170.0
RUN_HEIGHT = 5.0


# ---------------------------------------------------------------------------
# Small, bounded COM/report helpers
# ---------------------------------------------------------------------------


def _setup_stdout() -> None:
    """Make JSON output readable when Windows stdout is attached to WSL."""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        encoding = str(getattr(sys.stdout, "encoding", "") or "").lower()
        if encoding in {"cp1251", "cp1252", "latin-1", "iso-8859-1"}:
            sys.stdout = io.TextIOWrapper(
                sys.stdout.buffer, encoding="utf-8", errors="replace"
            )


def _json_value(value: Any) -> Any:
    """Convert common COM scalar values without invoking unknown members."""
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    return str(value)


def _bounded_public_names(obj: Any, limit: int = 80) -> dict[str, Any] | None:
    """Return bounded, non-invasive names for a failed COM wrapper."""
    if obj is None:
        return None
    try:
        names = [name for name in dir(obj) if not name.startswith("_")]
        return {"total": len(names), "shown": names[:limit]}
    except Exception as exc:  # pragma: no cover - depends on COM wrapper
        return {"error": repr(exc)}


def _record_failure(
    report: dict[str, Any], path: str, exc: Any, obj: Any = None
) -> None:
    failure: dict[str, Any] = {"path": path, "error": repr(exc)}
    names = _bounded_public_names(obj)
    if names is not None:
        failure["bounded_public_names"] = names
    report.setdefault("failures", []).append(failure)


def _read_property(
    report: dict[str, Any],
    obj: Any,
    path: str,
    property_name: str,
) -> Any:
    try:
        return _json_value(getattr(obj, property_name))
    except Exception as exc:
        _record_failure(report, path, exc, obj)
        return f"<ERROR: {exc}>"


def _call(
    report: dict[str, Any],
    obj: Any,
    path: str,
    method_name: str,
    *args: Any,
) -> Any:
    try:
        return getattr(obj, method_name)(*args)
    except Exception as exc:
        _record_failure(report, path, exc, obj)
        return None


def _qi_or_record(
    report: dict[str, Any],
    module7: Any,
    obj: Any,
    path: str,
    interface_name: str,
) -> Any:
    try:
        return _qi(module7, obj, interface_name)
    except Exception as exc:
        _record_failure(report, path, exc, obj)
        return None


def _set_property(
    report: dict[str, Any],
    obj: Any,
    path: str,
    property_name: str,
    value: Any,
) -> bool:
    try:
        setattr(obj, property_name, value)
        return True
    except Exception as exc:
        _record_failure(report, path, exc, obj)
        return False


def _update(
    report: dict[str, Any], obj: Any, path: str
) -> Any:
    """Call a known Update and retain its exact COM result."""
    result = _call(report, obj, path, "Update")
    report.setdefault("updates", []).append(
        {"path": path, "return": _json_value(result)}
    )
    if result is False:
        _record_failure(report, f"{path} returned False", RuntimeError("Update returned False"), obj)
    return result


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _file_info(path: Path) -> dict[str, Any]:
    try:
        exists = path.exists()
        return {
            "path": str(path),
            "exists": exists,
            "size": path.stat().st_size if exists else 0,
        }
    except Exception as exc:
        return {"path": str(path), "exists": False, "size": 0, "error": repr(exc)}


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Known API7 object paths
# ---------------------------------------------------------------------------


def _document_view_handles(
    report: dict[str, Any], module7: Any, doc: Any, label: str
) -> dict[str, Any] | None:
    prefix = f"{label}: "
    doc2d = _qi_or_record(
        report,
        module7,
        doc,
        f"{prefix}IKompasDocument -> QI(IKompasDocument2D)",
        "IKompasDocument2D",
    )
    if doc2d is None:
        return None
    try:
        view = doc2d.ViewsAndLayersManager.Views.ActiveView
    except Exception as exc:
        _record_failure(
            report,
            f"{prefix}IKompasDocument2D.ViewsAndLayersManager.Views.ActiveView",
            exc,
            doc2d,
        )
        return None
    symbols = _qi_or_record(
        report,
        module7,
        view,
        f"{prefix}IView -> QI(ISymbols2DContainer)",
        "ISymbols2DContainer",
    )
    container = _qi_or_record(
        report,
        module7,
        view,
        f"{prefix}IView -> QI(IDrawingContainer)",
        "IDrawingContainer",
    )
    if symbols is None or container is None:
        return None
    try:
        tables = symbols.DrawingTables
    except Exception as exc:
        _record_failure(report, f"{prefix}ISymbols2DContainer.DrawingTables", exc, symbols)
        return None
    return {
        "doc2d": doc2d,
        "view": view,
        "symbols": symbols,
        "container": container,
        "tables": tables,
    }


def _read_counts(
    report: dict[str, Any], handles: dict[str, Any], drawing_table: Any,
    table: Any, label: str
) -> dict[str, Any]:
    tables = handles.get("tables")
    container = handles.get("container")
    counts: dict[str, Any] = {}
    if tables is not None:
        counts["DrawingTables"] = _read_property(
            report, tables, f"{label}.ISymbols2DContainer.DrawingTables.Count", "Count"
        )
    if container is not None:
        try:
            drawing_texts = container.DrawingTexts
            counts["DrawingTexts"] = _read_property(
                report,
                drawing_texts,
                f"{label}.IDrawingContainer.DrawingTexts.Count",
                "Count",
            )
        except Exception as exc:
            _record_failure(report, f"{label}.IDrawingContainer.DrawingTexts", exc, container)
    if drawing_table is not None:
        counts["table.Valid"] = _read_property(
            report, drawing_table, f"{label}.IDrawingTable.Valid", "Valid"
        )
    if table is not None:
        counts["table.RowsCount"] = _read_property(
            report, table, f"{label}.ITable.RowsCount", "RowsCount"
        )
        counts["table.ColumnsCount"] = _read_property(
            report, table, f"{label}.ITable.ColumnsCount", "ColumnsCount"
        )
    return counts


def _item_readback(
    report: dict[str, Any], module7: Any, item: Any, index: int
) -> dict[str, Any]:
    """Read one ITextItem and its ITextFont through known properties only."""
    item_path = f"IText.TextLines[0].TextItems[{index}]"
    info: dict[str, Any] = {
        "index": index,
        "path": item_path,
        "Str": _read_property(report, item, f"{item_path}.Str", "Str"),
        "ItemType": _read_property(
            report, item, f"{item_path}.ItemType", "ItemType"
        ),
        "SizeFactor": _read_property(
            report, item, f"{item_path}.SizeFactor", "SizeFactor"
        ),
    }
    font = _qi_or_record(
        report, module7, item, f"{item_path} -> QI(ITextFont)", "ITextFont"
    )
    if font is None:
        info["ITextFont"] = None
    else:
        info["ITextFont"] = {
            "path": f"{item_path} -> ITextFont",
            "FontName": _read_property(
                report, font, f"{item_path}.ITextFont.FontName", "FontName"
            ),
            "Height": _read_property(
                report, font, f"{item_path}.ITextFont.Height", "Height"
            ),
            "Italic": _read_property(
                report, font, f"{item_path}.ITextFont.Italic", "Italic"
            ),
            "Bold": _read_property(
                report, font, f"{item_path}.ITextFont.Bold", "Bold"
            ),
            "Underline": _read_property(
                report, font, f"{item_path}.ITextFont.Underline", "Underline"
            ),
            "WidthFactor": _read_property(
                report, font, f"{item_path}.ITextFont.WidthFactor", "WidthFactor"
            ),
        }
    return info


def _read_cell_text(
    report: dict[str, Any],
    module7: Any,
    table: Any,
    label: str,
    *,
    check_native_runs: bool = False,
    expected_subscript: int = 20,
) -> dict[str, Any] | None:
    """Read only the known cell (0, 0), first line, and its items."""
    cell_path = f"ITable.Cell(0, 0) [{label}]"
    cell = _call(report, table, cell_path, "Cell", 0, 0)
    if cell is None:
        return None
    try:
        raw_text = cell.Text
    except Exception as exc:
        _record_failure(report, f"{cell_path}.Text", exc, cell)
        return None
    text = _qi_or_record(
        report, module7, raw_text, f"{cell_path}.Text -> QI(IText)", "IText"
    )
    if text is None:
        return None

    result: dict[str, Any] = {
        "cell_path": cell_path,
        "text_path": f"{cell_path}.Text -> IText",
        "Str": _read_property(report, text, f"{cell_path}.Text.Str", "Str"),
        "Count": _read_property(report, text, f"{cell_path}.Text.Count", "Count"),
        "lines": [],
    }
    try:
        lines = text.TextLines
        line = lines[0]  # Exactly one line is created; no index probing.
    except Exception as exc:
        _record_failure(
            report,
            f"{cell_path}.Text.TextLines[0] -> ITextLine",
            exc,
            text,
        )
        return result

    line_path = f"{cell_path}.Text.TextLines[0]"
    line_info: dict[str, Any] = {
        "path": line_path,
        "Count": _read_property(report, line, f"{line_path}.Count", "Count"),
        "Str": _read_property(report, line, f"{line_path}.Str", "Str"),
        "items": [],
    }
    first_item = None
    try:
        items = line.TextItems
        for index, item in enumerate(items):
            if first_item is None:
                first_item = item
            line_info["items"].append(_item_readback(report, module7, item, index))
    except Exception as exc:
        _record_failure(report, f"{line_path}.TextItems", exc, line)
    result["lines"].append(line_info)

    if check_native_runs:
        items_info = line_info["items"]
        if len(items_info) != len(RUN_SPECS):
            _record_failure(
                report,
                f"{line_path}.TextItems semantic readback (expected 4 native items)",
                RuntimeError(f"read back {len(items_info)} item(s), expected 4"),
                line,
            )
        if not any(
            item.get("ItemType") == expected_subscript and item.get("Str") == "1"
            for item in items_info
        ):
            _record_failure(
                report,
                f"{line_path}.TextItems semantic readback (expected native subscript)",
                RuntimeError(f"no item with ItemType={expected_subscript} and Str='1'"),
                line,
            )
        report.setdefault("bounded_introspection", {})[label] = {
            "IText": _bounded_public_names(text),
            "ITextLine": _bounded_public_names(line),
            "ITextItem": _bounded_public_names(first_item),
        }
    return result


def _write_native_runs(
    report: dict[str, Any],
    module7: Any,
    table: Any,
    subscript_item_type: int,
    case: dict[str, Any],
) -> dict[str, Any] | None:
    """Write four native runs through the existing cell IText only."""
    cell = _call(report, table, "ITable.Cell(0, 0) [write]", "Cell", 0, 0)
    if cell is None:
        return None
    try:
        raw_text = cell.Text
    except Exception as exc:
        _record_failure(report, "ITable.Cell(0, 0).Text [write]", exc, cell)
        return None
    text = _qi_or_record(
        report,
        module7,
        raw_text,
        "ITable.Cell(0, 0).Text [write] -> QI(IText)",
        "IText",
    )
    if text is None:
        return None

    # This is the same initialization/mutation order used by the successful
    # API7 DrawingText probe, but it stays on the existing cell IText.
    if not _set_property(
        report, text, "ITable.Cell(0, 0).Text.Str = '.'", "Str", "."
    ):
        return None
    try:
        line = text.TextLines[0]
    except Exception as exc:
        _record_failure(
            report,
            "ITable.Cell(0, 0).Text.TextLines[0] -> ITextLine [write]",
            exc,
            text,
        )
        return None

    if case["reuse_initial_item"]:
        try:
            initial_item = line.TextItems[0]  # Known initial item, not a probe.
        except Exception as exc:
            _record_failure(
                report,
                "ITable.Cell(0, 0).Text.TextLines[0].TextItems[0] [reuse initial]",
                exc,
                line,
            )
            return None
        item_entries: list[tuple[str, Any]] = [
            (
                "ITable.Cell(0, 0).Text.TextLines[0].TextItems[0] "
                "[reused initial item]",
                initial_item,
            )
        ]
        for index in range(1, len(RUN_SPECS)):
            item_path = (
                "ITable.Cell(0, 0).Text.TextLines[0].Add() -> "
                f"ITextItem[{index}]"
            )
            item = _call(report, line, item_path, "Add")
            if item is None:
                return None
            item_entries.append((item_path, item))
        write_mode = "reuse initial TextItems[0]; Add remaining runs"
    else:
        clear_path = "ITable.Cell(0, 0).Text.TextLines[0].Clear()"
        failures_before = len(report.get("failures", []))
        _call(report, line, clear_path, "Clear")
        if len(report.get("failures", [])) != failures_before:
            return None
        item_entries = []
        for index in range(len(RUN_SPECS)):
            item_path = (
                "ITable.Cell(0, 0).Text.TextLines[0].Add() -> "
                f"ITextItem[{index}]"
            )
            item = _call(report, line, item_path, "Add")
            if item is None:
                return None
            item_entries.append((item_path, item))
        write_mode = "Clear(); Add all four runs"

    item_update_results: list[Any] = []
    runs: list[dict[str, Any]] = []
    for index, (item_path, item) in enumerate(item_entries):
        spec = RUN_SPECS[index]
        item_type = (
            subscript_item_type
            if spec["item_type"] == "subscript"
            else int(spec["item_type"])
        )
        if not _set_property(
            report,
            item,
            f"{item_path}.Str = {spec['content']!r}",
            "Str",
            spec["content"],
        ):
            return None
        if not _set_property(
            report,
            item,
            f"{item_path}.ItemType = {item_type}",
            "ItemType",
            item_type,
        ):
            return None
        if "size_factor" in spec and not _set_property(
            report,
            item,
            f"{item_path}.SizeFactor = {spec['size_factor']}",
            "SizeFactor",
            spec["size_factor"],
        ):
            return None
        font = _qi_or_record(
            report,
            module7,
            item,
            f"{item_path} -> QI(ITextFont) [write]",
            "ITextFont",
        )
        if font is None:
            return None
        if not _set_property(
            report,
            font,
            f"{item_path}.ITextFont.Height = {RUN_HEIGHT}",
            "Height",
            RUN_HEIGHT,
        ):
            return None
        if not _set_property(
            report,
            font,
            f"{item_path}.ITextFont.Italic = True",
            "Italic",
            True,
        ):
            return None

        if case["item_update"]:
            update_result = _update(report, item, f"{item_path}.Update()")
            item_update_results.append(_json_value(update_result))
        runs.append(
            {
                "index": index,
                "content": spec["content"],
                "kind": spec["kind"],
                "item_type": item_type,
                "size_factor": spec.get("size_factor", 1.0),
                "item_path": item_path,
            }
        )

    pre_update_readback = _read_cell_text(
        report,
        module7,
        table,
        "before IDrawingTable.Update / before save",
        check_native_runs=False,
        expected_subscript=subscript_item_type,
    )
    report["observed_item_counts_before_table_update"] = (
        ((pre_update_readback or {}).get("lines") or [{}])[0].get("Count")
        if pre_update_readback
        else None
    )
    return {
        "source": SOURCE_TEXT,
        "native_runs": runs,
        "pre_update_readback": pre_update_readback,
        "literal_dollar_in_native_runs": any(
            "$" in run["content"] for run in runs
        ),
        "write_mode": write_mode,
        "write_path": (
            "ITable.Cell(0, 0).Text -> QI(IText) -> IText.TextLines[0] -> "
            "ITextItem.Str/ItemType/SizeFactor -> QI(ITextFont).Height/Italic"
        ),
        "item_update_requested": bool(case["item_update"]),
        "item_update_results": item_update_results,
        "drawingtext_pattern_comparison": {
            "same_order": "Str -> ItemType -> SizeFactor -> ITextFont properties",
            "existing_cell_IText_only": True,
            "overlay_DrawingText_created": False,
        },
    }


def _write_control_string(
    report: dict[str, Any], module7: Any, table: Any
) -> dict[str, Any] | None:
    """Assign one known KOMPAS control string to the existing cell IText."""
    cell = _call(report, table, "ITable.Cell(0, 0) [control-string]", "Cell", 0, 0)
    if cell is None:
        return None
    try:
        raw_text = cell.Text
    except Exception as exc:
        _record_failure(report, "ITable.Cell(0, 0).Text [control-string]", exc, cell)
        return None
    text = _qi_or_record(
        report,
        module7,
        raw_text,
        "ITable.Cell(0, 0).Text [control-string] -> QI(IText)",
        "IText",
    )
    if text is None:
        return None
    try:
        inline_plan = compile_table_cell_inline_plan(SOURCE_TEXT, RUN_HEIGHT, True)
    except Exception as exc:
        _record_failure(report, "compile production table-cell inline plan", exc)
        return None
    try:
        write_table_cell_inline(module7, cell, inline_plan)
    except Exception as exc:
        _record_failure(report, "production native table-cell IText writer", exc, text)
        return None
    if inline_plan.control_string != CONTROL_STRING:
        _record_failure(
            report,
            "production table-cell control-string parity",
            RuntimeError(
                f"compiled {inline_plan.control_string!r}, expected {CONTROL_STRING!r}"
            ),
        )
        return None
    readback = _read_cell_text(
        report,
        module7,
        table,
        "after control-string assignment / before table Update",
        check_native_runs=False,
    )
    return {
        "source": CONTROL_STRING,
        "write_path": "ITable.Cell(0, 0).Text -> QI(IText) -> IText.Str",
        "pre_update_readback": readback,
        "item_updates_requested": False,
        "native_items_added": False,
        "drawingtext_pattern_comparison": {
            "existing_cell_IText_only": True,
            "overlay_DrawingText_created": False,
        },
    }


def _export_png(
    report: dict[str, Any], module7: Any, doc: Any, path: Path, phase: str
) -> None:
    doc1 = _qi_or_record(
        report,
        module7,
        doc,
        "IKompasDocument -> QI(IKompasDocument1)",
        "IKompasDocument1",
    )
    if doc1 is None:
        return
    raw_params = _call(
        report,
        doc1,
        "IKompasDocument1.GetInterface(10130)",
        "GetInterface",
        RASTER_PARAMETERS_INTERFACE,
    )
    if raw_params is None:
        return
    params = _qi_or_record(
        report,
        module7,
        raw_params,
        "IKompasDocument1.GetInterface(10130) -> QI(IRasterConvertParameters)",
        "IRasterConvertParameters",
    )
    if params is None:
        return
    for property_name, value in (
        ("RasterFormat", RASTER_FORMAT_PNG),
        ("Resolution", 180),
        ("Scale", 1.0),
        ("SaveWorkArea", False),
        ("Sheets", "1"),
    ):
        _set_property(
            report,
            params,
            f"IRasterConvertParameters.{property_name} = {value!r}",
            property_name,
            value,
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    result = _call(
        report,
        doc1,
        "IKompasDocument1.SaveAsToRasterFormat(output_png, params)",
        "SaveAsToRasterFormat",
        str(path),
        params,
    )
    report.setdefault("raster_exports", []).append(
        {
            "phase": phase,
            "return": _json_value(result),
            "file": _file_info(path),
        }
    )


def _semantic_readback(
    readback: dict[str, Any] | None, subscript_item_type: int
) -> dict[str, Any]:
    lines = (readback or {}).get("lines") or []
    items = lines[0].get("items") if lines else []
    items = items or []
    expected = [
        ("Длина ", 0),
        ("l", 0),
        ("1", subscript_item_type),
        (", мм", 0),
    ]
    actual = [(item.get("Str"), item.get("ItemType")) for item in items]
    fonts = [item.get("ITextFont") for item in items]
    return {
        "actual": actual,
        "expected": expected,
        "four_items": len(items) == 4,
        "semantic_runs": actual == expected,
        "all_height_5": len(fonts) == 4
        and all(isinstance(font, dict) and font.get("Height") == RUN_HEIGHT for font in fonts),
        "all_italic": len(fonts) == 4
        and all(isinstance(font, dict) and bool(font.get("Italic")) for font in fonts),
        "str": (readback or {}).get("Str"),
    }


def _add_api_paths(report: dict[str, Any]) -> None:
    report["exact_com_paths"] = [
        "Dispatch('KOMPAS.Application.7') -> QI(IKompasAPIObject) -> IKompasAPIObject.Application",
        "IApplication.Documents.AddWithDefaultSettings(ksDocumentDrawing, True) -> private IKompasDocument",
        "IKompasDocument -> QI(IKompasDocument2D) -> IKompasDocument2D.ViewsAndLayersManager.Views.ActiveView",
        "IView -> QI(ISymbols2DContainer) -> ISymbols2DContainer.DrawingTables",
        "IDrawingTables.Add(1, 1, 60.0, 20.0, 0) -> IDrawingTable",
        "IDrawingTable.X / IDrawingTable.Y",
        "IDrawingTable -> QI(ITable)",
        "ITable.Range(0, 0, 0, 0) -> ITableRange.CellsFormat -> QI(ICellFormat)",
        "ICellFormat.ReadOnly = False",
        "ITable.Cell(0, 0) -> ITableCell.Text -> QI(IText)",
        "IText.Str = '.' (base-run initialization)",
        "production compile_table_cell_inline_plan('Длина $l_1$, мм', 5, True) -> 'Длина l$;1$, мм'",
        "production write_table_cell_inline -> existing IText.Str assignment + existing-item style readback",
        "IText.Str = 'Длина l$;1$, мм' (control-string case only)",
        "IText.TextLines[0] -> ITextLine (readback only on production path)",
        "known initial ITextLine.TextItems[0] reuse (strict/reuse-initial only)",
        "ITextLine.Clear() (item-update/geometry-first only)",
        "ITextLine.Add() -> ITextItem; ITextItem.Str / ItemType / SizeFactor",
        "ITextItem -> QI(ITextFont); ITextFont.Height / Italic",
        "ITextItem.Update() (H1/H3/strict only)",
        "IDrawingTable.Update() before rich write (H3/strict only)",
        "IDrawingTable.Update() after rich write (H1/H2 only)",
        "IKompasDocument.SaveAs(output_cdw)",
        "IKompasDocument.Close(False)",
        "IApplication.Documents.Open(output_cdw, True, False)",
        "reopened ISymbols2DContainer.DrawingTables.Count == 1",
        "reopened ISymbols2DContainer.DrawingTables.Item(0) [known single table only]",
        "reopened table object -> QI(ITable)",
        "reopened ITable.Cell(0, 0) -> IText readback",
        "IKompasDocument -> QI(IKompasDocument1) -> GetInterface(10130) -> QI(IRasterConvertParameters)",
        "IRasterConvertParameters.RasterFormat / Resolution / Scale / SaveWorkArea / Sheets",
        "IKompasDocument1.SaveAsToRasterFormat(output_png, params)",
    ]
    report["bounded_index_policy"] = {
        "text_lines": [0],
        "initial_text_items": [0],
        "cell": [0, 0],
        "reopened_table_items": [0],
        "reopened_table_item_requires_count": 1,
        "unknown_index_brute_force": False,
    }


def _new_case_report(
    case: dict[str, Any], output_dir: Path, subscript_item_type: int
) -> tuple[dict[str, Any], Path, Path, Path]:
    stem = OUTPUT_STEMS[case["name"]]
    cdw_path = output_dir / f"{stem}.cdw"
    png_path = output_dir / f"{stem}.png"
    report_path = output_dir / f"{stem}.report.json"
    report: dict[str, Any] = {
        "probe": "focused-native-drawing-table-rich-text",
        "milestone": "4",
        "case": case["name"],
        "hypothesis": case["hypothesis"],
        "description": case["description"],
        "case_options": {
            key: case.get(key, False)
            for key in (
                "reuse_initial_item",
                "geometry_first",
                "item_update",
                "update_after_rich",
                "control_string",
            )
        },
        "case_isolated_private_document": True,
        "source_path_inserted_before_imports": CURRENT_SRC_PATH,
        "source": SOURCE_TEXT,
        "requested_native_runs": [
            {
                "content": spec["content"],
                "kind": spec["kind"],
                "item_type": (
                    [0, 4, 5, 6][index]
                    if case.get("control_string")
                    else (
                        subscript_item_type
                        if spec["item_type"] == "subscript"
                        else spec["item_type"]
                    )
                ),
            }
            for index, spec in enumerate(RUN_SPECS)
        ],
        "requested_font": {"Height": RUN_HEIGHT, "Italic": True},
        "forbidden_paths_used": {
            "overlay_DrawingText": False,
            "API5": False,
            "unknown_index_brute_force": False,
        },
        "failures": [],
        "updates": [],
        "counts": {},
        "readbacks": {},
        "files": {
            "cdw": _file_info(cdw_path),
            "png": _file_info(png_path),
            "report": {"path": str(report_path)},
        },
        "checks": {},
    }
    _add_api_paths(report)
    return report, cdw_path, png_path, report_path


def _reopen_and_read(
    report: dict[str, Any],
    module7: Any,
    app: Any,
    cdw_path: Path,
    png_path: Path,
    *,
    check_native_runs: bool = True,
) -> Any:
    """Close the original doc, reopen the saved CDW, read known table 0."""
    reopened_doc = _call(
        report,
        app.Documents,
        "IApplication.Documents.Open(output_cdw, True, False)",
        "Open",
        str(cdw_path),
        True,
        False,
    )
    if reopened_doc is None:
        return None
    report["reopen"] = {"opened": True, "path": str(cdw_path)}
    _set_property(
        report,
        reopened_doc,
        "reopened IKompasDocument.Active = True",
        "Active",
        True,
    )
    handles = _document_view_handles(report, module7, reopened_doc, "reopened")
    if handles is None:
        return reopened_doc
    tables = handles["tables"]
    table_count = _as_int(
        _read_property(
            report,
            tables,
            "reopened ISymbols2DContainer.DrawingTables.Count",
            "Count",
        )
    )
    if table_count != 1:
        _record_failure(
            report,
            "reopened DrawingTables.Item(0) guarded by Count == 1",
            RuntimeError(f"reopened table count is {table_count!r}, expected 1"),
            tables,
        )
        report["counts"]["after_reopen"] = _read_counts(
            report, handles, None, None, "after_reopen"
        )
        return reopened_doc

    # Item(0) is not an exploratory index: this document was created with one
    # table and the Count==1 guard above is part of the acceptance evidence.
    raw_table = _call(
        report,
        tables,
        "reopened ISymbols2DContainer.DrawingTables.Item(0) [Count==1]",
        "Item",
        0,
    )
    if raw_table is None:
        return reopened_doc

    # On the tested wrapper Item(0) is already an IDrawingTable.  Keep a
    # single known-interface fallback for wrappers that return IDrawingObject.
    try:
        valid = getattr(raw_table, "Valid")
        reopened_drawing_table = raw_table
        report.setdefault("reopen", {})["table_item_valid_read"] = _json_value(valid)
    except Exception:
        reopened_drawing_table = _qi_or_record(
            report,
            module7,
            raw_table,
            "reopened DrawingTables.Item(0) -> QI(IDrawingTable)",
            "IDrawingTable",
        )
    reopened_table = _qi_or_record(
        report,
        module7,
        raw_table,
        "reopened DrawingTables.Item(0) -> QI(ITable)",
        "ITable",
    )
    report["counts"]["after_reopen"] = _read_counts(
        report,
        handles,
        reopened_drawing_table,
        reopened_table,
        "after_reopen",
    )
    if reopened_table is not None:
        report["readbacks"]["after_save_reopen"] = _read_cell_text(
            report,
            module7,
            reopened_table,
            "after save/reopen",
            check_native_runs=check_native_runs,
            expected_subscript=int(report["constants"]["const.ksTItSpecialSymbolDown"]),
        )
    _export_png(report, module7, reopened_doc, png_path, "after_save_reopen")
    return reopened_doc


def _finish_case_checks(
    report: dict[str, Any], case: dict[str, Any], subscript_item_type: int
) -> None:
    after_reopen = report.get("counts", {}).get("after_reopen", {})
    readback = report.get("readbacks", {}).get("after_save_reopen")

    if case.get("control_string"):
        lines = (readback or {}).get("lines") or []
        items = (lines[0].get("items") or []) if lines else []
        cell_str = str((readback or {}).get("Str", ""))
        line_str = str(lines[0].get("Str", "")) if lines else ""
        actual_types = [item.get("ItemType") for item in items]
        native_structure = actual_types == [0, 4, 5, 6]
        heights = [item.get("ITextFont", {}).get("Height") for item in items]
        all_italic = len(items) == 4 and all(
            bool(item.get("ITextFont", {}).get("Italic")) for item in items
        )
        base_and_tail_height_5 = (
            len(heights) == 4
            and abs(float(heights[0]) - 5.0) < 1e-6
            and abs(float(heights[3]) - 5.0) < 1e-6
        )
        internal_height_scaled = (
            len(heights) == 4
            and all(abs(float(heights[index]) - (10.0 / 3.0)) < 0.02 for index in (1, 2))
        )
        report["control_string_readback"] = {
            "input": CONTROL_STRING,
            "cell_IText_Str": cell_str,
            "line_Str": line_str,
            "items": items,
            "item_types": actual_types,
            "structured_native_items": native_structure,
            "base_and_tail_height_5": base_and_tail_height_5,
            "internal_height_scaled_3_333": internal_height_scaled,
            "all_italic": all_italic,
            "control_syntax_is_editable_native_structure": native_structure,
        }
        report["checks"] = {
            "DrawingTables.Count == 1 after save/reopen": after_reopen.get("DrawingTables") == 1,
            "DrawingTexts.Count == 0 after save/reopen": after_reopen.get("DrawingTexts") == 0,
            "table.Valid after save/reopen": after_reopen.get("table.Valid") is True,
            "control IText.Str readable after save/reopen": readback is not None,
            "control syntax parsed to native [0,4,5,6] structure": native_structure,
            "plain/tail native Height=5": base_and_tail_height_5,
            "internal formula heights are KOMPAS-scaled 3.333": internal_height_scaled,
            "all native items italic": all_italic,
            "CDW non-empty": report["files"]["cdw"].get("size", 0) > 0,
            "PNG non-empty": report["files"]["png"].get("size", 0) > 0,
        }
        report["ok"] = bool(report["checks"]) and all(report["checks"].values()) and not report["failures"]
        report["files"] = {
            "cdw": _file_info(Path(report["files"]["cdw"]["path"])),
            "png": _file_info(Path(report["files"]["png"]["path"])),
            "report": report["files"]["report"],
        }
        return

    semantic = _semantic_readback(readback, subscript_item_type)
    report["semantic_readback_after_save_reopen"] = semantic

    update_results = (report.get("write") or {}).get("item_update_results", [])
    item_updates_all_true = bool(update_results) and all(
        result is True for result in update_results
    )
    post_rich_updates = [
        entry
        for entry in report.get("updates", [])
        if "after rich write" in str(entry.get("path"))
    ]
    report["checks"] = {
        "DrawingTables.Count == 1 after save/reopen": after_reopen.get("DrawingTables") == 1,
        "DrawingTexts.Count == 0 after save/reopen": after_reopen.get("DrawingTexts") == 0,
        "table.Valid after save/reopen": after_reopen.get("table.Valid") is True,
        "readback has four items": semantic["four_items"],
        "readback has semantic plain/subscript/plain runs": semantic["semantic_runs"],
        "readback all Height=5": semantic["all_height_5"],
        "readback all Italic": semantic["all_italic"],
        "CDW non-empty": report["files"]["cdw"].get("size", 0) > 0,
        "PNG non-empty": report["files"]["png"].get("size", 0) > 0,
    }
    if case["item_update"]:
        report["checks"]["all requested ITextItem.Update calls returned True"] = (
            len(update_results) == 4 and item_updates_all_true
        )
    if case["name"] == "strict":
        report["checks"].update(
            {
                "strict reused known initial item": bool(case["reuse_initial_item"]),
                "strict geometry update precedes rich write": bool(case["geometry_first"]),
                "strict has no IDrawingTable.Update after rich write": len(post_rich_updates) == 0,
                "strict has four item Update calls": len(update_results) == 4,
                "strict native table remains Valid before reopen": (
                    report.get("counts", {}).get("before_reopen", {}).get("table.Valid") is True
                ),
                "strict DrawingTexts zero before reopen": (
                    report.get("counts", {}).get("before_reopen", {}).get("DrawingTexts") == 0
                ),
            }
        )
    report["ok"] = bool(report["checks"]) and all(report["checks"].values()) and not report["failures"]
    report["files"] = {
        "cdw": _file_info(Path(report["files"]["cdw"]["path"])),
        "png": _file_info(Path(report["files"]["png"]["path"])),
        "report": report["files"]["report"],
    }


def _run_case(
    report: dict[str, Any],
    case: dict[str, Any],
    module7: Any,
    const: Any,
    app: Any,
    subscript_item_type: int,
    cdw_path: Path,
    png_path: Path,
) -> None:
    doc = None
    reopened_doc = None
    drawing_table = None
    table = None
    cell_format = None
    handles = None
    try:
        doc = _call(
            report,
            app.Documents,
            "IApplication.Documents.AddWithDefaultSettings(ksDocumentDrawing, True)",
            "AddWithDefaultSettings",
            int(getattr(const, "ksDocumentDrawing", 1)),
            True,
        )
        if doc is None:
            return
        _set_property(report, doc, "private IKompasDocument.Active = True", "Active", True)
        handles = _document_view_handles(report, module7, doc, "created")
        if handles is None:
            return
        tables = handles["tables"]
        drawing_table = _call(
            report,
            tables,
            "created ISymbols2DContainer.DrawingTables.Add(1, 1, 60.0, 20.0, 0)",
            "Add",
            TABLE_ROWS,
            TABLE_COLUMNS,
            TABLE_CELL_WIDTH,
            TABLE_CELL_HEIGHT,
            0,
        )
        if drawing_table is None:
            return
        _set_property(report, drawing_table, "IDrawingTable.X = 40.0", "X", TABLE_X)
        _set_property(report, drawing_table, "IDrawingTable.Y = 170.0", "Y", TABLE_Y)
        table = _qi_or_record(
            report,
            module7,
            drawing_table,
            "created IDrawingTable -> QI(ITable)",
            "ITable",
        )
        if table is None:
            return

        cell_range = _call(
            report,
            table,
            "created ITable.Range(0, 0, 0, 0)",
            "Range",
            0,
            0,
            0,
            0,
        )
        if cell_range is not None:
            try:
                raw_format = cell_range.CellsFormat
                cell_format = _qi_or_record(
                    report,
                    module7,
                    raw_format,
                    "created ITable.Range(0, 0, 0, 0).CellsFormat -> QI(ICellFormat)",
                    "ICellFormat",
                )
            except Exception as exc:
                _record_failure(
                    report,
                    "created ITable.Range(0, 0, 0, 0).CellsFormat",
                    exc,
                    cell_range,
                )
        if cell_format is not None:
            _set_property(
                report,
                cell_format,
                "created ICellFormat.ReadOnly = False",
                "ReadOnly",
                False,
            )

        if case["geometry_first"]:
            _update(report, drawing_table, "IDrawingTable.Update() [geometry before rich write]")
            # Geometry Update can rebuild the native table/cell wrappers.  Do
            # not write through the pre-update ITable handle; reacquire the
            # same known interface before touching the cell text.
            refreshed_table = _qi_or_record(
                report,
                module7,
                drawing_table,
                "IDrawingTable after geometry Update -> QI(ITable) [fresh handle]",
                "ITable",
            )
            if refreshed_table is None:
                return
            table = refreshed_table
            refreshed_range = _call(
                report,
                table,
                "fresh ITable.Range(0, 0, 0, 0) after geometry Update",
                "Range",
                0,
                0,
                0,
                0,
            )
            if refreshed_range is not None:
                try:
                    refreshed_raw_format = refreshed_range.CellsFormat
                    cell_format = _qi_or_record(
                        report,
                        module7,
                        refreshed_raw_format,
                        "fresh ITable.Range(0, 0, 0, 0).CellsFormat -> QI(ICellFormat)",
                        "ICellFormat",
                    )
                except Exception as exc:
                    _record_failure(
                        report,
                        "fresh ITable.Range(0, 0, 0, 0).CellsFormat",
                        exc,
                        refreshed_range,
                    )
            if cell_format is not None:
                _set_property(
                    report,
                    cell_format,
                    "fresh ICellFormat.ReadOnly = False",
                    "ReadOnly",
                    False,
                )
            report["lifecycle"] = {
                "geometry_update_before_rich_write": True,
                "reacquired_ITable_after_geometry_update": True,
                "table_updates_after_rich_write": 0,
            }
        else:
            report["lifecycle"] = {
                "geometry_update_before_rich_write": False,
                "reacquired_ITable_after_geometry_update": False,
                "table_updates_after_rich_write": 1 if case["update_after_rich"] else 0,
            }

        if case.get("control_string"):
            write_info = _write_control_string(report, module7, table)
        else:
            write_info = _write_native_runs(
                report, module7, table, subscript_item_type, case
            )
        report["write"] = write_info
        if write_info is None:
            return

        if case["update_after_rich"]:
            _update(report, drawing_table, "IDrawingTable.Update() [after rich write]")
            report["readbacks"]["after_table_update"] = _read_cell_text(
                report,
                module7,
                table,
                "after IDrawingTable.Update",
                check_native_runs=False,
                expected_subscript=subscript_item_type,
            )
        else:
            report["readbacks"]["after_rich_without_table_update"] = _read_cell_text(
                report,
                module7,
                table,
                "after rich write without IDrawingTable.Update",
                check_native_runs=False,
                expected_subscript=subscript_item_type,
            )

        report["counts"]["before_reopen"] = _read_counts(
            report, handles, drawing_table, table, "before_reopen"
        )
        save_result = _call(
            report,
            doc,
            "IKompasDocument.SaveAs(output_cdw)",
            "SaveAs",
            str(cdw_path),
        )
        report["save_results"] = {
            "cdw_return": _json_value(save_result),
            "cdw_file_after_save": _file_info(cdw_path),
        }
        # Export once before closing so a partial case still has visual
        # evidence; a successful reopen overwrites this with the persisted PNG.
        _export_png(report, module7, doc, png_path, "before_close_reopen")
        try:
            doc.Close(False)
        except Exception as exc:
            _record_failure(report, "original IKompasDocument.Close(False)", exc, doc)
        doc = None
        reopened_doc = _reopen_and_read(
            report,
            module7,
            app,
            cdw_path,
            png_path,
            check_native_runs=not bool(case.get("control_string")),
        )
    except Exception as exc:
        _record_failure(report, "case.unhandled", exc)
    finally:
        if reopened_doc is not None:
            try:
                reopened_doc.Close(False)
            except Exception as exc:
                _record_failure(report, "reopened IKompasDocument.Close(False)", exc, reopened_doc)
        if doc is not None:
            try:
                doc.Close(False)
            except Exception as exc:
                _record_failure(report, "cleanup IKompasDocument.Close(False)", exc, doc)
        report["files"] = {
            "cdw": _file_info(cdw_path),
            "png": _file_info(png_path),
            "report": report["files"]["report"],
        }
        _finish_case_checks(report, case, subscript_item_type)


def main() -> int:
    _setup_stdout()
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        default="test_output",
        help="Windows path for ignored CDW/PNG/report output",
    )
    parser.add_argument(
        "--case",
        choices=["all", *CASE_BY_NAME],
        default="all",
        help="Run all bounded cases (strict last) or one named case",
    )
    args = parser.parse_args()
    output_dir = Path(args.output_dir).absolute()
    output_dir.mkdir(parents=True, exist_ok=True)
    selected_cases = list(CASE_SPECS) if args.case == "all" else [CASE_BY_NAME[args.case]]

    aggregate_path = output_dir / "native-table-rich-text.cases.report.json"
    aggregate: dict[str, Any] = {
        "probe": "focused-native-drawing-table-rich-text",
        "milestone": "4",
        "source_path_inserted_before_imports": CURRENT_SRC_PATH,
        "selection": args.case,
        "case_order": [case["name"] for case in selected_cases],
        "strict_is_final_case": bool(selected_cases and selected_cases[-1]["name"] == "strict"),
        "cases": [],
        "forbidden_paths_used": {
            "overlay_DrawingText": False,
            "API5": False,
            "unknown_index_brute_force": False,
        },
        "failures": [],
        "files": {"aggregate_report": str(aggregate_path)},
    }

    pythoncom.CoInitialize()
    try:
        module7 = gencache.EnsureModule(API7_GUID, 0, 1, 0)
        const = gencache.EnsureModule(CONST_GUID, 0, 1, 0).constants
        try:
            subscript_item_type = int(
                getattr(const, "ksTItSpecialSymbolDown", 20)
            )
        except Exception as exc:
            subscript_item_type = 20
            aggregate["failures"].append(
                {
                    "path": "constants.ksTItSpecialSymbolDown",
                    "error": repr(exc),
                }
            )
        aggregate["constants"] = {
            "const.ksDocumentDrawing": int(getattr(const, "ksDocumentDrawing", 1)),
            "const.ksTItSpecialSymbolDown": subscript_item_type,
        }
        raw = Dispatch("KOMPAS.Application.7")
        api7 = _qi(module7, raw, "IKompasAPIObject")
        app = api7.Application
        app.Visible = True

        for case in selected_cases:
            report, cdw_path, png_path, report_path = _new_case_report(
                case, output_dir, subscript_item_type
            )
            report["constants"] = aggregate["constants"]
            _run_case(
                report,
                case,
                module7,
                const,
                app,
                subscript_item_type,
                cdw_path,
                png_path,
            )
            _write_json(report_path, report)
            aggregate["cases"].append(
                {
                    "case": case["name"],
                    "hypothesis": case["hypothesis"],
                    "ok": report.get("ok", False),
                    "report": str(report_path),
                    "cdw": report["files"]["cdw"],
                    "png": report["files"]["png"],
                    "failures": report.get("failures", []),
                    "checks": report.get("checks", {}),
                    "semantic_readback_after_save_reopen": report.get(
                        "semantic_readback_after_save_reopen"
                    ),
                }
            )
    except Exception as exc:
        aggregate["failures"].append({"path": "probe.unhandled", "error": repr(exc)})
    finally:
        strict_results = [
            item["ok"]
            for item in reversed(aggregate["cases"])
            if item["case"] == "strict"
        ]
        aggregate["strict_ok"] = strict_results[0] if strict_results else None
        aggregate["ok"] = (
            bool(aggregate["strict_ok"])
            if strict_results
            else bool(aggregate["cases"]) and all(
                item["ok"] for item in aggregate["cases"]
            )
        )
        try:
            _write_json(aggregate_path, aggregate)
        except Exception as exc:
            aggregate["failures"].append(
                {"path": "aggregate report write", "error": repr(exc)}
            )
            aggregate["ok"] = False
        print(json.dumps(aggregate, ensure_ascii=False, indent=2, default=str))
        pythoncom.CoUninitialize()

    return 0 if aggregate.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
