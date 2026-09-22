"""Development-only CLI shim (Windows VM diagnostics).

Public CDW rendering requests a dedicated authenticated server plan and then
uses the localhost KOMPAS Renderer. This module directly probes the adapter on
the Windows VM and is not part of the public client surface.

Usage::

    python -m tmm_scene_kompas.cli input.json --output out.cdw
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Optional, Sequence


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render tmm-scene JSON to a KOMPAS-3D .cdw drawing."
    )
    parser.add_argument(
        "payload_pos",
        nargs="?",
        default=None,
        help="Path to the JSON payload file (positional)",
    )
    parser.add_argument(
        "--payload",
        default=None,
        help="Path to the JSON payload file",
    )
    parser.add_argument(
        "--output", default=None,
        help="Output .cdw path (default: payload stem + .cdw)",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)

    payload_path = args.payload or args.payload_pos
    if payload_path is None:
        print("Error: no payload specified. Pass a file or use --payload.",
              file=sys.stderr)
        return 2

    payload_path = os.path.abspath(payload_path)
    if not os.path.exists(payload_path):
        print(f"Payload not found: {payload_path}", file=sys.stderr)
        return 2

    with open(payload_path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)

    # Validate v2 payload before touching KOMPAS.
    from tmm_scene_kompas.validation import validate_v2

    err = validate_v2(payload)
    if err:
        print(f"Error: {err}", file=sys.stderr)
        return 2

    output_path = args.output or os.path.splitext(payload_path)[0] + ".cdw"

    # Deferred import — only touches pywin32 at call time.
    from tmm_scene_kompas.render import build_drawing

    try:
        written = build_drawing(payload, output_path, visible=True,
                                keep_open=False)
    except Exception as exc:
        print(f"KOMPAS render failed: {exc}", file=sys.stderr)
        return 1

    print(f"KOMPAS drawing written: {written}")
    return 0
