# PyInstaller onedir specification for the unsigned Windows KOMPAS Renderer.
#
# build_windows.py sets TMM_RENDERER_CONFIG to the generated, strict release
# config.  The config is copied into the frozen application root as well as
# passed separately to Inno Setup, so the setup is self-contained and the
# installed executable can be started with --config <install-dir>\renderer-config.json.

from pathlib import Path
import os
import sys

from PyInstaller.utils.hooks import collect_data_files

try:
    spec_dir = Path(SPECPATH)
except NameError:  # pragma: no cover - only useful when inspecting this file
    spec_dir = Path(__file__).resolve().parent

project_root = spec_dir.parent
source_root = project_root / "src"
entrypoint = spec_dir / "renderer_entry.py"
config_value = os.environ.get("TMM_RENDERER_CONFIG")
config_path = Path(config_value) if config_value else project_root / "build" / "windows" / "renderer-config.json"
if not config_path.is_file():
    raise FileNotFoundError(
        "generated renderer-config.json is missing; run packaging/build_windows.py first"
    )

if str(source_root) not in sys.path:
    sys.path.insert(0, str(source_root))

# Fixtures are package data used by the renderer.  pywin32 creates API7 generated
# modules at runtime; the stable pywin32 import roots stay explicit while COM
# activation remains entirely inside tmm_scene_kompas.render.
data_files = collect_data_files("tmm_scene_kompas")
data_files.extend(collect_data_files("cryptography"))
data_files.extend(collect_data_files("win32com"))
data_files.append((str(config_path), "."))
data_files = sorted(data_files, key=lambda item: (str(item[1]), str(item[0])))
hidden_imports = sorted(
    {
        "pythoncom",
        "pywintypes",
        "win32api",
        "win32com",
        "win32com.client",
    }
)

a = Analysis(
    [str(entrypoint)],
    pathex=[str(source_root)],
    binaries=[],
    datas=data_files,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="tmm-kompas-renderer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=True,
    contents_directory=".",
)
COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="tmm-kompas-renderer",
)
