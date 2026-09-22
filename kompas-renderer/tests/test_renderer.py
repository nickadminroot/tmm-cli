"""Localhost KOMPAS Renderer protocol tests without KOMPAS/COM."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import TestCase, mock

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from tmm_scene_kompas import renderer


class RendererProtocolTests(TestCase):
    def setUp(self) -> None:
        self.private_key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
        self.tempdir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tempdir.name)
        self.state = renderer.RendererState(
            self.private_key.public_key(),
            key_id="test",
            origins=("https://app.example", "https://app.example.test"),
            data_dir=self.data_dir,
        )
        self.state.prepare_storage()
        self.server = renderer.create_server(self.state, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address[:2]
        self.base_url = f"http://{host}:{port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.tempdir.cleanup()
    def _plan(self, *, challenge: str | None = None) -> bytes:
        issued = datetime.now(timezone.utc).replace(microsecond=0)
        payload = {
            "operation": "kompas-plan",
            "job_id": "66666666-6666-4666-8666-666666666666",
            "agent_challenge": challenge or self.state.challenge,
            "issued_at": issued.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "expires_at": (issued + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "scene_sha256": "0" * 64,
            "document": {"id": "renderer-test", "units": "mm"},
            "operations": [
                {
                    "op": "line",
                    "entity": {
                        "id": "line",
                        "type": "line",
                        "from": [0, 0],
                        "to": [10, 0],
                    },
                }
            ],
        }
        unsigned = {
            "format": renderer.PLAN_FORMAT,
            "version": renderer.PLAN_VERSION,
            "algorithm": renderer.PLAN_ALGORITHM,
            "key_id": "test",
            "payload": payload,
        }
        plan = {
            **unsigned,
            "signature": base64.urlsafe_b64encode(
                self.private_key.sign(renderer.canonical_json(unsigned))
            ).decode("ascii").rstrip("="),
        }
        return renderer.canonical_json(plan)

    def _request(self, method: str, path: str, body: bytes | None = None, **headers):
        request = urllib.request.Request(self.base_url + path, data=body, method=method)
        for key, value in headers.items():
            request.add_header(key, value)
        return urllib.request.urlopen(request, timeout=3)

    def test_capabilities_and_signed_render(self) -> None:
        with mock.patch.object(
            renderer,
            "build_drawing",
            side_effect=lambda _scene, output, **_kwargs: Path(output).write_bytes(b"fake-cdw"),
        ) as build:
            capabilities = json.loads(self._request("GET", "/v1/capabilities").read())
            self.assertEqual(capabilities["version"], 2)
            self.assertEqual(capabilities["agent_version"], renderer.RENDERER_VERSION)
            self.assertEqual(capabilities["capabilities"], list(renderer.REQUIRED_CAPABILITIES))
            challenge = capabilities["challenge"]
            response = self._request(
                "POST",
                "/v1/render",
                self._plan(),
                **{
                    "Content-Type": "application/json",
                    "X-TMM-Agent-Request": "1",
                    "Origin": "https://app.example",
                },
            )
            self.assertEqual(response.headers["Content-Type"].split(";", 1)[0], "application/octet-stream")
            body = response.read()
            self.assertEqual(body, b"fake-cdw")
            self.assertEqual(response.headers["X-TMM-Result-Sha256"], hashlib.sha256(body).hexdigest())
            self.assertEqual(response.headers["Access-Control-Expose-Headers"], "Content-Disposition, X-TMM-Result-Sha256")
            build.assert_called_once()
            self.assertEqual(build.call_args.kwargs["visible"], True)
            self.assertEqual(build.call_args.kwargs["keep_open"], True)
            backing_path = Path(build.call_args.args[1])
            self.assertEqual(backing_path.parent, self.data_dir / renderer.RUNS_DIRECTORY)
            self.assertTrue(backing_path.is_file())
            self.assertNotEqual(challenge, self.state.challenge)

    def test_origin_is_exact_and_missing_custom_header_is_rejected(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as forbidden:
            self._request(
                "GET",
                "/v1/capabilities",
                **{"Origin": "https://evil.example"},
            )
        self.assertEqual(forbidden.exception.code, 403)
        with self.assertRaises(urllib.error.HTTPError) as missing:
            self._request(
                "POST",
                "/v1/render",
                self._plan(),
                **{"Content-Type": "application/json"},
            )
        self.assertEqual(missing.exception.code, 400)
        with self.assertRaises(urllib.error.HTTPError) as malformed_host:
            self._request("GET", "/v1/capabilities", **{"Host": "["})
        self.assertEqual(malformed_host.exception.code, 403)
        for host in ("localhost:bad", "localhost/path", "localhost?query"):
            with self.assertRaises(urllib.error.HTTPError) as malformed:
                self._request("GET", "/v1/capabilities", **{"Host": host})
            self.assertEqual(malformed.exception.code, 403)
    def test_pna_preflight_is_allowlisted(self) -> None:
        response = self._request(
            "OPTIONS",
            "/v1/render",
            **{
                "Origin": "https://app.example",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type, x-tmm-agent-request",
                "Access-Control-Request-Private-Network": "true",
            },
        )
        self.assertEqual(response.status, 204)
        self.assertEqual(response.headers["Access-Control-Allow-Origin"], "https://app.example")
        self.assertEqual(response.headers["Access-Control-Allow-Private-Network"], "true")
        with self.assertRaises(urllib.error.HTTPError) as forbidden:
            self._request(
                "OPTIONS",
                "/v1/render",
                **{
                    "Origin": "https://app.example",
                    "Access-Control-Request-Method": "DELETE",
                },
            )
        self.assertEqual(forbidden.exception.code, 403)

    def test_tampered_plan_is_rejected_without_com(self) -> None:
        plan = json.loads(self._plan())
        plan["payload"]["operations"][0]["entity"]["to"] = [20, 0]
        with mock.patch.object(renderer, "build_drawing") as build:
            with self.assertRaises(urllib.error.HTTPError) as rejected:
                self._request(
                    "POST",
                    "/v1/render",
                    json.dumps(plan).encode("utf-8"),
                    **{
                        "Content-Type": "application/json",
                        "X-TMM-Agent-Request": "1",
                    },
                )
            self.assertEqual(rejected.exception.code, 401)
            build.assert_not_called()


    def test_hexadecimal_public_key_is_supported(self) -> None:
        public = self.private_key.public_key()
        material = public.public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        ).hex()
        loaded = renderer._load_public_key(material, field="test")
        self.assertEqual(
            loaded.public_bytes(
                serialization.Encoding.Raw,
                serialization.PublicFormat.Raw,
            ),
            public.public_bytes(
                serialization.Encoding.Raw,
                serialization.PublicFormat.Raw,
            ),
        )

    def test_plan_validates_adapter_text_and_table_constraints(self) -> None:
        with self.assertRaises(renderer.RendererError):
            renderer._entity(
                {
                    "id": "block",
                    "type": "textBlock",
                    "position": [0, 0],
                    "text": "x",
                    "fontSize": 3.0,
                    "width": 20,
                }
            )
        with self.assertRaises(renderer.RendererError):
            renderer._validate_cells(
                [{"row": 0, "column": 0, "text": "A\nB"}],
                rows=1,
                columns=1,
            )

class RendererConfigTests(TestCase):
    def setUp(self) -> None:
        self.private_key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
        self.tempdir = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _mapping(self) -> dict[str, object]:
        material = self.private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        ).hex()
        return {
            "public_key": material,
            "key_id": "release",
            "allowed_origins": ["https://app.example"],
            "renderer_version": "0.2.0",
            "data_directory": self.tempdir.name,
        }

    def test_strict_release_config_and_unknown_keys(self) -> None:
        config = renderer.RendererConfig.from_mapping(self._mapping())
        self.assertTrue(config.installed)
        self.assertEqual(config.allowed_origins, ("https://app.example",))
        self.assertEqual(config.data_directory, Path(self.tempdir.name))
        with self.assertRaises(renderer.RendererUnavailable):
            renderer.RendererConfig.from_mapping({**self._mapping(), "extra": True})
        with self.assertRaises(renderer.RendererUnavailable):
            renderer.RendererConfig.from_mapping({key: value for key, value in self._mapping().items() if key != "key_id"})
        with self.assertRaises(renderer.RendererUnavailable):
            renderer.RendererConfig.from_mapping({**self._mapping(), "allowed_origins": ["*"]})

    def test_frozen_loader_requires_install_directory_config(self) -> None:
        install_dir = Path(self.tempdir.name) / "install"
        install_dir.mkdir()
        install_config = install_dir / "renderer-config.json"
        external_config = Path(self.tempdir.name) / "external-renderer-config.json"
        config_bytes = json.dumps(self._mapping()).encode("utf-8")
        install_config.write_bytes(config_bytes)
        external_config.write_bytes(config_bytes)
        with mock.patch.object(renderer.sys, "frozen", True, create=True), mock.patch.object(
            renderer.sys, "executable", str(install_dir / "tmm-kompas-renderer.exe")
        ):
            loaded = renderer.load_renderer_config(str(install_config))
            self.assertTrue(loaded.installed)
            with self.assertRaises(renderer.RendererUnavailable):
                renderer.load_renderer_config(str(external_config))
            with self.assertRaises(renderer.RendererUnavailable):
                renderer.load_renderer_config(development=True)

    def test_prepare_storage_rejects_runs_directory_symlink(self) -> None:
        data_dir = Path(self.tempdir.name)
        target = data_dir / "outside"
        target.mkdir()
        link = data_dir / renderer.RUNS_DIRECTORY
        if not hasattr(os, "symlink"):
            self.skipTest("symlinks are unavailable")
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError:
            self.skipTest("symlinks are unavailable")
        state = renderer.RendererState(
            self.private_key.public_key(),
            key_id="release",
            data_dir=data_dir,
        )
        with self.assertRaises(renderer.RendererUnavailable):
            state.prepare_storage()
        self.assertFalse((target / renderer.RUNS_MARKER).exists())

    def test_cleanup_removes_only_owned_uuid_files(self) -> None:
        state = renderer.RendererState(
            self.private_key.public_key(),
            key_id="release",
            data_dir=self.tempdir.name,
        )
        state.prepare_storage()
        stale = state.runs_dir / "77777777-7777-4777-8777-777777777777.cdw"
        foreign = state.runs_dir / "user.cdw"
        stale.write_bytes(b"old")
        foreign.write_bytes(b"keep")
        self.assertEqual(state.cleanup_backing_files(), [stale])
        self.assertFalse(stale.exists())
        self.assertTrue(foreign.exists())
        current = state.backing_path("88888888-8888-4888-8888-888888888888")
        current.write_bytes(b"current")
        self.assertEqual(state.cleanup_backing_files(), [])
        self.assertTrue(current.exists())

    def test_single_instance_lock_reports_conflict(self) -> None:
        first = renderer.RendererInstanceLock(self.tempdir.name)
        second = renderer.RendererInstanceLock(self.tempdir.name)
        first.acquire()
        try:
            with self.assertRaises(renderer.RendererUnavailable):
                second.acquire()
        finally:
            first.release()


if __name__ == "__main__":
    import unittest

    unittest.main()
