"""Stage-1 live capability probe for one-object API5 ksTextEx text.

This probe is intentionally diagnostic-only. It creates one private drawing,
uses API7 only for document/readback, and API5 only for ksTextEx,
ksGetObjGabaritRect, and ksMoveObj. It never touches an existing document,
clipboard, raster/SVG output, or a subprocess fallback.

The report separates raw observations (COM return values/readback) from
interpretation. The created document is saved under TEMP and only that newly
created document is closed by default.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import time
from pathlib import Path
from typing import Any, Iterable

import pythoncom
from win32com.client import Dispatch, gencache

API7_GUID = "{69AC2981-37C0-4379-84FD-5DD2F3C0A520}"
API5_GUID = "{0422828C-F174-495E-AC5D-D31014DBBE87}"
CONST_GUID = "{75C9F5D0-B5B8-4526-8681-9903C567D2ED}"


def qi(module: Any, obj: Any, name: str) -> Any:
    iface = getattr(module, name)
    return iface(obj._oleobj_.QueryInterface(iface.CLSID, pythoncom.IID_IDispatch))


def safe_get(obj: Any, name: str, default: Any = None) -> Any:
    try:
        return getattr(obj, name)
    except Exception as exc:  # COM property is itself evidence
        return f"<error: {exc}>"


def json_value(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    try:
        return float(value)
    except Exception:
        return str(value)


def public_names(obj: Any) -> list[str]:
    try:
        return [name for name in dir(obj) if not name.startswith("_")]
    except Exception as exc:
        return [f"<dir error: {exc}>"]


def connect_and_create() -> tuple[Any, Any, Any, Any, Any, Any, Any, Any]:
    """Connect inside the caller-owned, already initialized COM apartment."""
    module7 = gencache.EnsureModule(API7_GUID, 0, 1, 0)
    module5 = gencache.EnsureModule(API5_GUID, 0, 1, 0)
    const = gencache.EnsureModule(CONST_GUID, 0, 1, 0).constants
    raw7 = Dispatch("KOMPAS.Application.7")
    api7 = qi(module7, raw7, "IKompasAPIObject")
    app = api7.Application
    before_documents = int(app.Documents.Count)
    doc = app.Documents.AddWithDefaultSettings(const.ksDocumentDrawing, True)
    time.sleep(0.4)
    doc2d7 = qi(module7, doc, "IKompasDocument2D")
    view = doc2d7.ViewsAndLayersManager.Views.ActiveView
    container = qi(module7, view, "IDrawingContainer")
    raw5 = Dispatch("KOMPAS.Application.5")
    doc2d5 = raw5.ActiveDocument2D
    return module7, module5, const, app, doc, doc2d5, container, before_documents


def make_item(raw5: Any, const: Any, content: str, *, height: float = 5.0,
              item_type: int = 0, i_s_numb: int = 0,
              bit_vector: int = 0, bold: bool = False,
              italic: bool = False, underline: bool = False,
              font_name: str = "GOST type A") -> tuple[Any, dict[str, Any]]:
    item = raw5.GetParamStruct(const.ko_TextItemParam)
    item.Init()
    item.s = content
    item.type = int(item_type)
    item.iSNumb = int(i_s_numb)
    font = item.GetItemFont()
    attempted: dict[str, Any] = {"public_names": public_names(font)}
    for name, value in (
        ("fontName", font_name), ("height", float(height)), ("ksu", 1),
        ("color", 0), ("bitVector", int(bit_vector)),
        ("bold", bool(bold)), ("italic", bool(italic)),
        ("underline", bool(underline)),
    ):
        try:
            setattr(font, name, value)
            attempted[name] = {"set": True, "readback": json_value(getattr(font, name))}
        except Exception as exc:
            attempted[name] = {"set": False, "error": str(exc)}
    item.SetItemFont(font)
    return item, {
        "content": content,
        "item_type_requested": item_type,
        "i_s_numb_requested": i_s_numb,
        "font_requested": {
            "fontName": font_name, "height": height,
            "bitVector": bit_vector, "bold": bold,
            "italic": italic, "underline": underline,
        },
        "font_setter_observations": attempted,
    }


def make_line(raw5: Any, const: Any, specs: Iterable[dict[str, Any]]) -> tuple[Any, list[dict[str, Any]]]:
    line = raw5.GetParamStruct(const.ko_TextLineParam)
    line.Init()
    arr = line.GetTextItemArr()
    arr.ksClearArray()
    observations: list[dict[str, Any]] = []
    for spec in specs:
        item, observation = make_item(raw5, const, **spec)
        ok = arr.ksAddArrayItem(-1, item)
        observation["array_add_return"] = json_value(ok)
        observations.append(observation)
    line.SetTextItemArr(arr)
    return line, observations


def make_text_param(raw5: Any, const: Any, *, x: float, y: float,
                    lines: list[list[dict[str, Any]]], height: float = 5.0,
                    width: float = 120.0) -> tuple[Any, dict[str, Any]]:
    text_param = raw5.GetParamStruct(const.ko_TextParam)
    text_param.Init()
    para = raw5.GetParamStruct(const.ko_ParagraphParam)
    para.Init()
    para.x = float(x)
    para.y = float(y)
    para.height = float(height)
    para.width = float(width)
    para.ang = 0.0
    para.hFormat = 0
    para.vFormat = 0
    text_param.SetParagraphParam(para)

    para_names = public_names(para)
    line_spacing_candidates = [
        name for name in para_names
        if any(token in name.lower() for token in ("space", "step", "interval", "leading"))
    ]
    lines_arr = text_param.GetTextLineArr()
    lines_arr.ksClearArray()
    line_observations: list[Any] = []
    for specs in lines:
        line, obs = make_line(raw5, const, specs)
        line_observations.append(obs)
        line_observations.append(json_value(lines_arr.ksAddArrayItem(-1, line)))
    text_param.SetTextLineArr(lines_arr)
    return text_param, {
        "paragraph_input": {"x": x, "y": y, "height": height, "width": width},
        "paragraph_public_names": para_names,
        "paragraph_spacing_like_names": line_spacing_candidates,
        "line_input_count": len(lines),
        "line_item_observations": line_observations,
    }


def readback_texts(module7: Any, container: Any) -> dict[str, Any]:
    collection = container.DrawingTexts
    count = int(collection.Count)
    texts: list[dict[str, Any]] = []
    for index in range(count):
        obj = collection.Item(index)
        info: dict[str, Any] = {"index": index}
        geometry_error: str | None = None
        try:
            geometry = qi(module7, obj, "DrawingText")
        except Exception:
            try:
                geometry = qi(module7, obj, "IDrawingText")
            except Exception as exc:
                geometry = obj
                geometry_error = str(exc)
        for name in ("X", "Y", "Height", "Width", "Angle"):
            info[name] = json_value(safe_get(geometry, name))
        if geometry_error is not None:
            info["geometry_qi_error"] = geometry_error
        text = qi(module7, obj, "IText")
        info["IText.Str"] = json_value(safe_get(text, "Str"))
        info["IText.Count"] = json_value(safe_get(text, "Count"))
        lines: list[dict[str, Any]] = []
        try:
            for line_index, line in enumerate(text.TextLines):
                line_info: dict[str, Any] = {
                    "index": line_index,
                    "Str": json_value(safe_get(line, "Str")),
                    "Count": json_value(safe_get(line, "Count")),
                    "items": [],
                }
                items = safe_get(line, "TextItems")
                if items is not None and not isinstance(items, str):
                    for item_index, item in enumerate(items):
                        item_info: dict[str, Any] = {
                            "index": item_index,
                            "Str": json_value(safe_get(item, "Str")),
                            "ItemType": json_value(safe_get(item, "ItemType")),
                            "Number": json_value(safe_get(item, "Number")),
                            "SizeFactor": json_value(safe_get(item, "SizeFactor")),
                            "SymbolFontName": json_value(safe_get(item, "SymbolFontName")),
                        }
                        try:
                            font = qi(module7, item, "ITextFont")
                            item_info["ITextFont"] = {
                                key: json_value(safe_get(font, key))
                                for key in ("FontName", "Height", "Bold", "Italic", "Underline", "WidthFactor", "Color")
                            }
                        except Exception as exc:
                            item_info["ITextFontError"] = str(exc)
                        line_info["items"].append(item_info)
                lines.append(line_info)
        except Exception as exc:
            info["TextLinesError"] = str(exc)
        info["lines"] = lines
        texts.append(info)
    return {"count": count, "texts": texts}


def rect_observation(module5: Any, const: Any, doc2d: Any, reference: int) -> dict[str, Any]:
    result: dict[str, Any] = {
        "method": "API5.ksDocument2D.ksGetObjGabaritRect(ref, ko_RectParam)",
        "reference": int(reference),
    }
    try:
        rect = module5  # kept only to make the module type visible in reports
        del rect
        # The API5 generated module's constants are shared with the caller;
        # the struct itself is obtained from the raw Application.5 object.
        raw5 = Dispatch("KOMPAS.Application.5")
        rect = raw5.GetParamStruct(const.ko_RectParam)
        # ko_RectParam has no Init method in the installed API5 wrapper.
        result["rect_public_names_before"] = public_names(rect)
        status = doc2d.ksGetObjGabaritRect(int(reference), rect)
        result["status"] = json_value(status)
        result["rect_values_after"] = {
            name: json_value(safe_get(rect, name))
            for name in result["rect_public_names_before"]
            if not callable(safe_get(rect, name))
        }
        result["rect_candidate_values"] = {
            name: json_value(safe_get(rect, name))
            for name in ("x", "y", "width", "height", "left", "bottom", "right", "top", "X", "Y", "Width", "Height")
            if name in result["rect_public_names_before"]
        }
        for method_name in ("GetpBot", "GetpTop"):
            try:
                point = getattr(rect, method_name)()
                point_names = public_names(point)
                result[method_name] = {
                    "public_names": point_names,
                    "values": {
                        name: json_value(safe_get(point, name))
                        for name in point_names
                        if not callable(safe_get(point, name))
                    },
                    "xy_candidates": {
                        name: json_value(safe_get(point, name))
                        for name in ("x", "y", "X", "Y")
                        if name in point_names
                    },
                }
            except Exception as exc:
                result[method_name] = {"error": str(exc)}
    except Exception as exc:
        result["error"] = str(exc)
    return result


def inferred_xywh(observation: dict[str, Any]) -> tuple[float, float, float, float] | None:
    values = observation.get("rect_candidate_values", {})
    names = {key.lower(): value for key, value in values.items()}
    try:
        x, y = float(names["x"]), float(names["y"])
        width, height = float(names["width"]), float(names["height"])
        if all(math.isfinite(value) for value in (x, y, width, height)):
            return x, y, width, height
    except (KeyError, TypeError, ValueError):
        pass

    def point_xy(name: str) -> tuple[float, float] | None:
        point_info = observation.get(name, {})
        point_values = {key.lower(): value for key, value in point_info.get("xy_candidates", {}).items()}
        try:
            point = (float(point_values["x"]), float(point_values["y"]))
            return point if all(math.isfinite(value) for value in point) else None
        except (KeyError, TypeError, ValueError):
            return None

    bottom = point_xy("GetpBot")
    top = point_xy("GetpTop")
    if bottom is not None and top is not None:
        left, bottom_y = bottom
        right, top_y = top
        result = (left, bottom_y, right - left, top_y - bottom_y)
        if all(math.isfinite(value) for value in result):
            return result
    return None


def add_case(raw5: Any, const: Any, doc2d: Any, container: Any,
             module7: Any, label: str, *, x: float, y: float,
             lines: list[list[dict[str, Any]]], height: float = 5.0,
             width: float = 120.0) -> dict[str, Any]:
    before = int(container.DrawingTexts.Count)
    param, input_observation = make_text_param(
        raw5, const, x=x, y=y, lines=lines, height=height, width=width,
    )
    reference = doc2d.ksTextEx(param, 0)
    after = int(container.DrawingTexts.Count)
    gabarit = rect_observation(module7, const, doc2d, int(reference)) if reference else {"error": "zero reference"}
    return {
        "label": label,
        "reference": json_value(reference),
        "object_count": {"before": before, "after": after, "delta": after - before},
        "input_observation": input_observation,
        "gabarit_observation": gabarit,
        "readback_after_case": readback_texts(module7, container),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default=os.path.join(os.environ.get("TEMP", "."), "tmm-scene-kompas-stage1"))
    parser.add_argument("--keep-open", action="store_true")
    args = parser.parse_args()
    out_dir = Path(args.out_dir).absolute()
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "stage1-capabilities.json"
    cdw_path = out_dir / "stage1-capabilities.cdw"

    module7 = module5 = const = app = doc = doc2d = container = None
    com_initialized = False
    report: dict[str, Any] = {
        "probe": "stage1-capabilities-v1",
        "policy": {
            "api5_text_creation": "ksTextEx only",
            "forbidden": ["raster", "clipboard", "SVG", "subprocess KOMPAS fallback"],
            "document_scope": "new document only; unrelated documents are not closed",
        },
        "observations": {},
        "interpretations": [],
    }
    try:
        pythoncom.CoInitialize()
        com_initialized = True
        module7, module5, const, app, doc, doc2d, container, before_documents = connect_and_create()
        api7_active = app.ActiveDocument
        report["observations"]["installed_environment"] = {
            "python": os.sys.version,
            "api7_module_attributes": len(dir(module7)),
            "api5_module_attributes": len(dir(module5)),
            "documents_before_create": before_documents,
            "documents_after_create": int(app.Documents.Count),
            "ksDocumentDrawing": json_value(getattr(const, "ksDocumentDrawing", None)),
            "ksDocumentFragment": json_value(getattr(const, "ksDocumentFragment", None)),
            "api5_rect_constant": json_value(getattr(const, "ko_RectParam", None)),
            "api5_methods_under_test": ["ksTextEx", "ksGetObjGabaritRect", "ksMoveObj"],
            "active_document_identity": {
                "api7_created_reference": json_value(safe_get(doc, "Reference")),
                "api7_active_reference": json_value(safe_get(api7_active, "Reference")),
                "api5_active_reference": json_value(safe_get(doc2d, "reference")),
            },
        }
        raw5 = Dispatch("KOMPAS.Application.5")
        cases: list[dict[str, Any]] = []
        cases.append(add_case(
            raw5, const, doc2d, container, module7, "explicit-multiline",
            x=100, y=100,
            lines=[[{"content": "LINE-A"}], [{"content": "LINE-B"}], [{"content": "LINE-C"}]],
        ))
        cases.append(add_case(
            raw5, const, doc2d, container, module7, "at-slash-single-item",
            x=100, y=70,
            lines=[[{"content": "A@/B"}]],
        ))
        cases.append(add_case(
            raw5, const, doc2d, container, module7, "empty-spacing-line",
            x=100, y=40,
            lines=[[{"content": "ABOVE"}], [], [{"content": "BELOW"}]],
        ))
        cases.append(add_case(
            raw5, const, doc2d, container, module7, "styles-heights-structural",
            x=100, y=10,
            lines=[[
                {"content": "PLAIN", "height": 5.0},
                {"content": "BOLD", "height": 4.0, "bold": True},
                {"content": "ITALIC", "height": 3.5, "italic": True},
                {"content": "BIT-I", "height": 3.5, "bit_vector": 0x40},
                {"content": "BIT-B", "height": 3.5, "bit_vector": 0x100},
                {"content": "BIT-IB", "height": 3.5, "bit_vector": 0x140},
                {"content": "F", "height": 5.0, "bit_vector": 0x7 | 0x40, "bold": True, "italic": True},
                {"content": "t", "height": 3.5, "bit_vector": 0x8 | 0x100, "font_name": "Symbol type A"},
                {"content": "32", "height": 3.5, "bit_vector": 0x9 | 0x140},
                {"content": "", "height": 5.0, "bit_vector": 0x10},
            ]],
            height=5.0,
        ))
        cases.append(add_case(
            raw5, const, doc2d, container, module7, "fraction-structural-styles",
            x=100, y=-20,
            lines=[[
                {"content": "NUM", "bit_vector": 0x1 | 0x100, "bold": True},
                {"content": "DEN", "bit_vector": 0x2 | 0x40, "italic": True},
                {"content": "", "bit_vector": 0x3},
            ]],
        ))
        cases.append(add_case(
            raw5, const, doc2d, container, module7, "special-decoration-structural-style",
            x=100, y=-50,
            lines=[[
                {"content": "OVER", "item_type": 17, "i_s_numb": 95, "bit_vector": 0x11 | 0x100, "bold": True},
                {"content": "", "bit_vector": 0x12},
                {"content": "UNDER", "item_type": 17, "i_s_numb": 96, "bit_vector": 0x11 | 0x40, "italic": True},
                {"content": "", "bit_vector": 0x12},
            ]],
        ))
        cases.append(add_case(
            raw5, const, doc2d, container, module7, "top-left-retained-move",
            x=200, y=100,
            lines=[[{"content": "TOP@/BOTTOM"}]],
        ))

        top_left_case = cases[-1]
        reference = top_left_case.get("reference")
        top_left_observation: dict[str, Any] = {"reference": reference}
        if isinstance(reference, int) and reference > 0:
            before_g = rect_observation(module5, const, doc2d, reference)
            before_xywh = inferred_xywh(before_g)
            top_left_observation["before"] = before_g
            top_left_observation["before_xywh_inferred"] = before_xywh
            if before_xywh is not None:
                left, bottom, width, height = before_xywh
                target_left, target_top = 50.0, 180.0
                dx = target_left - left
                dy = target_top - (bottom + height)
                move_result = doc2d.ksMoveObj(int(reference), float(dx), float(dy))
                after_g = rect_observation(module5, const, doc2d, reference)
                after_xywh = inferred_xywh(after_g)
                top_left_observation.update({
                    "target_top_left": [target_left, target_top],
                    "delta_requested": [dx, dy],
                    "ksMoveObj_return": json_value(move_result),
                    "after": after_g,
                    "after_xywh_inferred": after_xywh,
                    "retained_reference_reused": True,
                })
                if after_xywh is not None:
                    top_left_observation["after_top_left_inferred"] = [
                        after_xywh[0], after_xywh[1] + after_xywh[3]
                    ]
        report["observations"]["cases"] = cases
        report["observations"]["top_left_retained_move"] = top_left_observation
        report["observations"]["final_api7_readback"] = readback_texts(module7, container)
        doc.SaveAs(str(cdw_path))
        report["observations"]["saved_cdw"] = {
            "path": str(cdw_path),
            "exists": cdw_path.exists(),
            "size": cdw_path.stat().st_size if cdw_path.exists() else 0,
        }
        report["interpretations"] = [
            "Each case calls ksTextEx once; object-count deltas are the direct one-object evidence.",
            "@/ is interpreted only from API7 TextLines/IText.Str readback; no visual claim is made.",
            "Font height/style setter success and API7 ITextFont values are observations, not production recommendations.",
            "Gabarit/move/top-left conclusions require non-error rect fields and a successful retained-reference move readback.",
        ]
        report["status"] = "completed"
        return_code = 0
    except Exception as exc:
        report["status"] = "error"
        report["error"] = str(exc)
        return_code = 1
    finally:
        try:
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        finally:
            try:
                if doc is not None and not args.keep_open:
                    try:
                        doc.Close(False)
                    except Exception as exc:
                        print(f"own probe document close failed: {exc}")
            finally:
                if com_initialized:
                    pythoncom.CoUninitialize()
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
