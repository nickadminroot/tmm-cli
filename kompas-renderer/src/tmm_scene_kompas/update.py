"""Verified GitHub release update for the installed Windows renderer."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen

RELEASE_URL = "https://api.github.com/repos/nickadminroot/tmm-cli/releases/latest"
ASSET_PREFIX = "https://github.com/nickadminroot/tmm-cli/releases/download/"
SETUP_NAME = "tmm-kompas-renderer-setup.exe"
MAX_SETUP_BYTES = 64 * 1024 * 1024
_VERSION = re.compile(r"^\d+\.\d+\.\d+$")
_DIGEST = re.compile(r"^sha256:([0-9a-f]{64})$")


def _parts(version: str) -> tuple[int, int, int] | None:
    if not _VERSION.fullmatch(version):
        return None
    return tuple(map(int, version.split(".")))  # type: ignore[return-value]


def _newer_setup(release: dict, current_version: str) -> tuple[str, dict] | None:
    tag = release.get("tag_name")
    if not isinstance(tag, str) or not tag.startswith("tmm-cli/v"):
        return None
    current = _parts(current_version)
    if current is None:
        return None
    for asset in release.get("assets", []):
        if not isinstance(asset, dict) or asset.get("name") != SETUP_NAME:
            continue
        label = asset.get("label")
        if not isinstance(label, str) or not label.startswith("renderer-v"):
            continue
        version = label.removeprefix("renderer-v")
        parts = _parts(version)
        url = asset.get("browser_download_url")
        digest = asset.get("digest")
        size = asset.get("size")
        if (parts is not None and parts > current
                and isinstance(url, str)
                and url == f"{ASSET_PREFIX}{tag}/{SETUP_NAME}"
                and isinstance(digest, str) and _DIGEST.fullmatch(digest)
                and isinstance(size, int) and 0 < size <= MAX_SETUP_BYTES):
            return version, asset
    return None


def _read_url(url: str, limit: int, timeout: int) -> bytes:
    request = Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "tmm-kompas-renderer-updater",
    })
    with urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"GitHub returned HTTP {response.status}")
        data = response.read(limit + 1)
    if not data or len(data) > limit:
        raise RuntimeError("GitHub response size is invalid")
    return data


def check_and_start_update(current_version: str, data_dir: Path, config_path: str | None) -> bool:
    """Start a verified setup and let it replace this installed process."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False) or not config_path:
        return False
    if Path(config_path).resolve().parent != Path(sys.executable).resolve().parent:
        return False
    release = json.loads(_read_url(RELEASE_URL, 1 << 20, 3))
    selected = _newer_setup(release, current_version)
    if selected is None:
        return False
    version, asset = selected
    setup = _read_url(asset["browser_download_url"], MAX_SETUP_BYTES, 30)
    if len(setup) != asset["size"] or hashlib.sha256(setup).hexdigest() != asset["digest"][7:]:
        raise RuntimeError("GitHub setup digest mismatch")
    update_dir = data_dir / "updates"
    update_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=update_dir, suffix=".exe", delete=False) as target:
        target.write(setup)
        setup_path = Path(target.name)
    try:
        subprocess.Popen(
            [str(setup_path), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
            close_fds=True,
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
        )
    except OSError:
        setup_path.unlink(missing_ok=True)
        raise
    print(f"KOMPAS Renderer: updating to {version} from GitHub", file=sys.stderr)
    return True
