"""Dump API7 text/line/item/font readback for the active KOMPAS drawing."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pythoncom
from win32com.client import Dispatch, gencache

from probe_stage1_capabilities import API7_GUID, qi, readback_texts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output")
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
        data = readback_texts(module7, container)
        output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote {output}; DrawingTexts={data['count']}")
        for text in data["texts"]:
            rendered = ascii(text.get("IText.Str"))
            print(f"text[{text['index']}]: lines={len(text.get('lines', []))} str={rendered}")
            for line in text.get("lines", []):
                kinds = [(item.get("ItemType"), item.get("Number"), item.get("Str")) for item in line.get("items", [])]
                print(f"  line[{line['index']}]: {ascii(kinds)}")
        return 0
    finally:
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    raise SystemExit(main())
