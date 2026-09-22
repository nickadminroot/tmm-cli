"""Pure tmm-scene v2 payload validation for the KOMPAS adapter."""

from __future__ import annotations

from typing import Any, Dict, Optional


def validate_v2(payload: Dict[str, Any]) -> Optional[str]:
    """Validate a tmm-scene v2 single-scene payload.

    Returns ``None`` on success or a human-readable error string.
    """
    fmt = payload.get("format", "tmm-scene")
    if fmt != "tmm-scene":
        return f"expected format 'tmm-scene', got {fmt!r}"

    ver = payload.get("version", 2)
    if ver != 2:
        return f"expected version 2, got {ver!r}"

    if "scenes" in payload:
        return (
            "v2 single-scene files must not contain a 'scenes' array; "
            "the scene is the document root"
        )

    if "canvas" in payload:
        return "v2 single-scene files must not contain a 'canvas' key"

    if "entities" not in payload:
        return "v2 payload must contain a top-level 'entities' list"

    if not isinstance(payload["entities"], list):
        return "'entities' must be a list"

    if payload.get("kind") == "super-scene":
        sheet = payload.get("sheet")
        if not isinstance(sheet, dict):
            return "super-scene payload must contain a 'sheet' object"
        format_name = str(sheet.get("format", "")).strip().upper()
        if format_name not in {"A0", "A1", "A2", "A3", "A4", "A5"}:
            return f"unsupported super-scene sheet format {format_name!r}"
        orientation = str(sheet.get("orientation", "landscape")).strip().lower()
        if orientation not in {"portrait", "landscape"}:
            return f"unsupported super-scene sheet orientation {orientation!r}"
        title_block = sheet.get("titleBlock")
        if title_block is not None and not isinstance(title_block, dict):
            return "super-scene sheet 'titleBlock' must be an object"
        if isinstance(title_block, dict):
            if (
                title_block.get("text") is not None
                and not isinstance(title_block.get("text"), str)
            ):
                return "super-scene titleBlock.text must be a string"
            try:
                title_cell = int(title_block.get("cell", 2))
            except (TypeError, ValueError):
                return "super-scene titleBlock.cell must be an integer"
            if title_cell <= 0:
                return "super-scene titleBlock.cell must be positive"

    return None
