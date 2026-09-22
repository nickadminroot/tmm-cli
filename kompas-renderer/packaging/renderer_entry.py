"""Frozen-process entry point for the installed TMM KOMPAS Renderer.

The runtime owns config validation and the Windows single-instance mutex.  This
thin module exists so PyInstaller has a stable script target without exposing
another command/path/COM execution surface.
"""

from __future__ import annotations

from tmm_scene_kompas.renderer import main

if __name__ == "__main__":
    raise SystemExit(main())
