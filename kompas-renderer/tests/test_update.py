import unittest
import hashlib
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from tmm_scene_kompas import update
from tmm_scene_kompas.update import ASSET_PREFIX, SETUP_NAME, _newer_setup


class RendererUpdateTest(unittest.TestCase):
    def setUp(self):
        self.release = {
            "tag_name": "tmm-cli/v0.1.8",
            "assets": [{
                "name": SETUP_NAME,
                "label": "renderer-v0.2.1",
                "browser_download_url": ASSET_PREFIX + "tmm-cli/v0.1.8/" + SETUP_NAME,
                "digest": "sha256:" + "a" * 64,
                "size": 1234,
            }],
        }

    def test_newer_labeled_installer_is_selected(self):
        self.assertEqual(_newer_setup(self.release, "0.2.0")[0], "0.2.1")
        self.assertIsNone(_newer_setup(self.release, "0.2.1"))

    def test_unverified_or_unlabeled_installer_is_ignored(self):
        asset = self.release["assets"][0]
        for field, bad in (("label", ""), ("digest", "sha256:bad"),
                           ("browser_download_url", "https://example.org/setup.exe")):
            candidate = {**self.release, "assets": [{**asset, field: bad}]}
            self.assertIsNone(_newer_setup(candidate, "0.2.0"))

    def test_verified_setup_starts_only_after_digest_check(self):
        setup = b"installer bytes"
        self.release["assets"][0]["size"] = len(setup)
        self.release["assets"][0]["digest"] = "sha256:" + hashlib.sha256(setup).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            install_dir = Path(directory) / "installed"
            install_dir.mkdir()
            executable = install_dir / "tmm-kompas-renderer.exe"
            config = install_dir / "renderer-config.json"
            with patch.object(update.sys, "platform", "win32"), \
                 patch.object(update.sys, "frozen", True, create=True), \
                 patch.object(update.sys, "executable", str(executable)), \
                 patch.object(update, "_read_url", side_effect=[json.dumps(self.release).encode(), setup]), \
                 patch.object(update.subprocess, "Popen") as launch:
                self.assertTrue(update.check_and_start_update("0.2.0", Path(directory), str(config)))
                self.assertEqual(Path(launch.call_args.args[0][0]).read_bytes(), setup)
                launch.assert_called_once()

            self.release["assets"][0]["digest"] = "sha256:" + "0" * 64
            with patch.object(update.sys, "platform", "win32"), \
                 patch.object(update.sys, "frozen", True, create=True), \
                 patch.object(update.sys, "executable", str(executable)), \
                 patch.object(update, "_read_url", side_effect=[json.dumps(self.release).encode(), setup]), \
                 patch.object(update.subprocess, "Popen") as launch:
                with self.assertRaisesRegex(RuntimeError, "digest mismatch"):
                    update.check_and_start_update("0.2.0", Path(directory), str(config))
                launch.assert_not_called()
