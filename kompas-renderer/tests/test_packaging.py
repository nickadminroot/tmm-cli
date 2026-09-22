"""COM-free checks for the Windows release packaging contract."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
PACKAGING_ROOT = PACKAGE_ROOT / "packaging"
_SPEC = importlib.util.spec_from_file_location(
    "tmm_packaging_build_windows", PACKAGING_ROOT / "build_windows.py"
)
assert _SPEC is not None and _SPEC.loader is not None
build_windows = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = build_windows
_SPEC.loader.exec_module(build_windows)


class InstallerContractTests(TestCase):
    PUBLIC_KEY = "-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=\n-----END PUBLIC KEY-----"

    def test_release_config_is_exact_and_deterministic(self) -> None:
        config = build_windows.make_release_config(
            public_key=self.PUBLIC_KEY,
            key_id="release-2026",
            allowed_origins=["https://app.example", "http://127.0.0.1:5173"],
            renderer_version="0.2.0",
        )
        self.assertEqual(
            set(config.as_dict()),
            {"public_key", "key_id", "allowed_origins", "renderer_version", "data_directory"},
        )
        self.assertEqual(config.data_directory, r"%LOCALAPPDATA%\TMM\KompasRenderer")
        self.assertEqual(build_windows.config_bytes(config), build_windows.config_bytes(config))
        self.assertNotIn("PRIVATE", build_windows.config_bytes(config).decode("ascii"))

    def test_deployment_origin_is_used_by_cli_when_flag_is_omitted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.dict(build_windows.os.environ, {"TMM_SITE_ORIGIN": "https://www.tmm-agent.ru"}, clear=False):
                with redirect_stdout(StringIO()):
                    status = build_windows.main([
                        "--public-key",
                        self.PUBLIC_KEY,
                        "--key-id",
                        "release",
                        "--renderer-version",
                        "0.2.0",
                        "--build-dir",
                        str(root / "build"),
                        "--output-dir",
                        str(root / "dist"),
                        "--dry-run",
                    ])

            self.assertEqual(status, 0)
            config = json.loads((root / "build" / "renderer-config.json").read_text(encoding="utf-8"))
            self.assertEqual(config["allowed_origins"], ["https://www.tmm-agent.ru"])

    def test_explicit_origins_are_not_widened_by_deployment_environment(self) -> None:
        with patch.dict(build_windows.os.environ, {"TMM_SITE_ORIGIN": "https://attacker.example"}, clear=False):
            origins = build_windows._release_allowed_origins(["https://www.tmm-agent.ru"])

        self.assertEqual(origins, ("https://www.tmm-agent.ru",))

    def test_release_inputs_reject_wildcards_and_private_material(self) -> None:
        with self.assertRaises(build_windows.BuildError):
            build_windows.make_release_config(
                public_key=self.PUBLIC_KEY,
                key_id="release",
                allowed_origins=["*"],
                renderer_version="0.2.0",
            )
        with self.assertRaises(build_windows.BuildError):
            build_windows._canonical_public_key("-----BEGIN PRIVATE KEY-----")
        with self.assertRaises(build_windows.BuildError):
            build_windows._canonical_public_key("0" * 64)
        with self.assertRaises(build_windows.BuildError):
            build_windows.make_release_config(
                public_key=self.PUBLIC_KEY,
                key_id="release",
                allowed_origins=[],
                renderer_version="0.2.0",
            )

    def test_release_inputs_reject_invalid_ports(self) -> None:
        for origin in ("https://app.example:0", "https://app.example:65536"):
            with self.assertRaises(build_windows.BuildError):
                build_windows.make_release_config(
                    public_key=self.PUBLIC_KEY,
                    key_id="release",
                    allowed_origins=[origin],
                    renderer_version="0.2.0",
                )

    def test_dry_run_writes_config_and_fixed_tool_commands(self) -> None:
        config = build_windows.make_release_config(
            public_key=self.PUBLIC_KEY,
            key_id="release",
            allowed_origins=["https://app.example"],
            renderer_version="0.2.0",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            layout = build_windows._layout(root / "build", root / "dist", config.renderer_version)
            self.assertIsNone(build_windows.build_release(config, layout=layout, dry_run=True))
            self.assertEqual(layout.config_path.read_bytes(), build_windows.config_bytes(config))
            pyinstaller, inno = build_windows.build_commands(
                layout, pyinstaller="pyinstaller", iscc="ISCC.exe", version=config.renderer_version
            )
            self.assertEqual(pyinstaller[0], "pyinstaller")
            self.assertIn("/DAppVersion=0.2.0", inno)
            self.assertEqual(layout.artifact_path.name, "tmm-kompas-renderer-setup-0.2.0.exe")

    def test_pyinstaller_spec_places_release_config_beside_executable(self) -> None:
        source = (PACKAGING_ROOT / "tmm-kompas-renderer.spec").read_text(encoding="utf-8")
        self.assertIn('contents_directory="."', source)
        self.assertNotIn('"win32com.gen_py"', source)

    def test_inno_contract_is_per_user_and_unsigned(self) -> None:
        source = (PACKAGING_ROOT / "tmm-kompas-renderer.iss").read_text(encoding="utf-8")
        self.assertIn("PrivilegesRequired=lowest", source)
        self.assertIn("CloseApplications=no", source)
        self.assertIn("RestartApplications=no", source)
        self.assertIn("function InitializeSetup(): Boolean", source)
        self.assertIn("function InitializeUninstall(): Boolean", source)
        self.assertIn("TerminateProcess", source)
        self.assertIn("tmm-kompas-renderer.exe", source)
        self.assertIn("tmm-kompas-agent.exe", source)
        self.assertNotIn("AppMutex=", source)
        self.assertNotIn("CloseApplicationsFilter=", source)
        self.assertIn('ValueType: none; ValueName: "TMM KOMPAS Agent"; Flags: deletevalue', source)
        self.assertIn('Name: "{app}\\tmm-kompas-agent.exe"', source)
        self.assertIn('Name: "{app}\\agent-config.json"', source)
        self.assertIn("Root: HKCU", source)
        self.assertNotIn("\nSignTool=", source)


if __name__ == "__main__":
    import unittest

    unittest.main()
