#!/usr/bin/env python3
"""Build the unsigned per-user TMM KOMPAS Renderer Windows setup.

The release inputs and generated configuration are deliberately handled in
Python rather than in the Inno preprocessor.  This keeps the release contract
strict and gives non-Windows release authors a deterministic ``--dry-run``
that validates inputs and prints the exact PyInstaller/ISCC commands without
trying to execute Windows tools.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

RENDERER_PROTOCOL_VERSION = 2
DEFAULT_DATA_DIRECTORY = r"%LOCALAPPDATA%\TMM\KompasRenderer"
PACKAGING_DIR = Path(__file__).resolve().parent
PACKAGE_ROOT = PACKAGING_DIR.parent
SPEC_PATH = PACKAGING_DIR / "tmm-kompas-renderer.spec"
INNO_PATH = PACKAGING_DIR / "tmm-kompas-renderer.iss"
SEMVER_RE = re.compile(
    r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
KEY_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
MAX_RENDERER_VERSION_LENGTH = 64
HEX_KEY_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class BuildError(ValueError):
    """An invalid release input or an unavailable build tool."""


@dataclass(frozen=True)
class ReleaseConfig:
    """The exact five-key config consumed by an installed renderer.

    Protocol version is intentionally not serialized here.  The installed
    renderer owns the protocol constant (currently v2); adding a sixth key would
    violate the strict installed-config contract.
    """

    public_key: str
    key_id: str
    allowed_origins: tuple[str, ...]
    renderer_version: str
    data_directory: str = DEFAULT_DATA_DIRECTORY

    def as_dict(self) -> dict[str, object]:
        return {
            "public_key": self.public_key,
            "key_id": self.key_id,
            "allowed_origins": list(self.allowed_origins),
            "renderer_version": self.renderer_version,
            "data_directory": self.data_directory,
        }


@dataclass(frozen=True)
class BuildLayout:
    """All generated paths for one release build."""

    build_dir: Path
    output_dir: Path
    config_path: Path
    pyinstaller_dist: Path
    pyinstaller_work: Path
    pyinstaller_cache: Path
    renderer_dist: Path
    artifact_path: Path
    portable_artifact_path: Path


@dataclass(frozen=True)
class BuildResult:
    """Release evidence emitted after Inno Setup succeeds."""

    installer_artifact: Path | None
    installer_sha256: str | None
    installer_size: int | None
    installer_hash_file: Path | None
    portable_artifact: Path
    portable_sha256: str
    portable_size: int
    portable_hash_file: Path
    evidence_file: Path


def _canonical_public_key(material: str) -> str:
    """Validate an Ed25519 PUBLIC KEY PEM and return raw base64url bytes.

    Release input is deliberately PEM-only.  Raw 32-byte values are
    indistinguishable from Ed25519 private seeds, so accepting hexadecimal or
    base64url here could accidentally embed private material in the installer
    configuration.
    """

    if not isinstance(material, str):
        raise BuildError("the Ed25519 public key must be text")
    value = material.strip()
    if not value:
        raise BuildError("the Ed25519 public key is empty")
    if not value.startswith("-----BEGIN PUBLIC KEY-----") or not value.endswith("-----END PUBLIC KEY-----"):
        raise BuildError("release public key must be PEM encoded Ed25519 PUBLIC KEY material")
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        loaded = serialization.load_pem_public_key(value.encode("utf-8"))
    except ImportError as exc:  # pragma: no cover - build environment setup
        raise BuildError("cryptography is required to validate a PEM public key") from exc
    except (TypeError, ValueError) as exc:
        raise BuildError("public-key PEM is invalid") from exc
    if not isinstance(loaded, Ed25519PublicKey):
        raise BuildError("public-key PEM must contain an Ed25519 public key")
    raw = loaded.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _canonical_origin(origin: str) -> str:
    """Validate and canonicalize one exact browser Origin value."""

    if not isinstance(origin, str):
        raise BuildError("allowed origins must be strings")
    value = origin.strip()
    if not value or value != origin:
        raise BuildError("allowed origins may not be empty or padded")
    if value == "null" or "*" in value or any(character.isspace() for character in value):
        raise BuildError("allowed origins must be exact URLs without wildcard or null origins")
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise BuildError("allowed origin has an invalid host or port") from exc
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc or not hostname:
        raise BuildError("allowed origins must use an http or https origin")
    if port is not None and not 1 <= port <= 65535:
        raise BuildError("allowed origin port must be between 1 and 65535")
    if (
        (parsed.scheme.lower() == "http" and port == 80)
        or (parsed.scheme.lower() == "https" and port == 443)
    ):
        raise BuildError("default ports must be omitted from browser origins")
    if parsed.username is not None or parsed.password is not None:
        raise BuildError("allowed origins may not contain credentials")
    if parsed.path or parsed.query or parsed.fragment:
        raise BuildError("allowed origins may not contain a path, query, or fragment")
    if any(character in hostname for character in ("%", "\\", "/")):
        raise BuildError("allowed origin host is invalid")
    host = hostname.lower()
    if ":" in host and not host.startswith("["):
        host = "[" + host + "]"
    netloc = host if port is None else f"{host}:{port}"
    canonical = f"{parsed.scheme.lower()}://{netloc}"
    if canonical != value:
        raise BuildError(f"allowed origin is not canonical: {origin!r}")
    return canonical


def make_release_config(
    *,
    public_key: str,
    key_id: str,
    allowed_origins: Iterable[str],
    renderer_version: str,
) -> ReleaseConfig:
    """Validate required release inputs and build the strict config object."""

    if not isinstance(key_id, str) or not KEY_ID_RE.fullmatch(key_id):
        raise BuildError("key id must be 1-64 ASCII letters, digits, '.', '_' or '-'")
    if (
        not isinstance(renderer_version, str)
        or len(renderer_version) > MAX_RENDERER_VERSION_LENGTH
        or not SEMVER_RE.fullmatch(renderer_version)
    ):
        raise BuildError("renderer version must be a semantic version such as 0.2.0 and at most 64 characters")
    try:
        origins = tuple(sorted({_canonical_origin(item) for item in allowed_origins}))
    except TypeError as exc:
        raise BuildError("at least one exact allowed origin is required") from exc
    if not origins:
        raise BuildError("at least one exact allowed origin is required")
    return ReleaseConfig(
        public_key=_canonical_public_key(public_key),
        key_id=key_id,
        allowed_origins=origins,
        renderer_version=renderer_version,
    )


def config_bytes(config: ReleaseConfig) -> bytes:
    """Serialize config deterministically, with no private release material."""

    return (
        json.dumps(config.as_dict(), ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def write_release_config(path: Path, config: ReleaseConfig) -> None:
    """Write the generated strict config using stable UTF-8/newline bytes."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(config_bytes(config))


def sha256_file(path: Path) -> str:
    """Hash a finished artifact without loading it all into memory."""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _layout(build_dir: Path, output_dir: Path, version: str) -> BuildLayout:
    build_dir = build_dir.resolve()
    output_dir = output_dir.resolve()
    pyinstaller_dist = build_dir / "pyinstaller-dist"
    return BuildLayout(
        build_dir=build_dir,
        output_dir=output_dir,
        config_path=build_dir / "renderer-config.json",
        pyinstaller_dist=pyinstaller_dist,
        pyinstaller_work=build_dir / "pyinstaller-work",
        pyinstaller_cache=build_dir / "pyinstaller-cache",
        renderer_dist=pyinstaller_dist / "tmm-kompas-renderer",
        artifact_path=output_dir / f"tmm-kompas-renderer-setup-{version}.exe",
        portable_artifact_path=output_dir / "tmm-kompas-renderer-portable-windows-amd64.zip",
    )


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _prepare_stage(layout: BuildLayout) -> None:
    """Clear only the generated PyInstaller staging tree.

    The guard prevents an accidental ``--build-dir /`` from deleting outside
    the selected build root.  The release output directory is never removed;
    only the exact versioned artifact and evidence are replaced.
    """

    layout.build_dir.mkdir(parents=True, exist_ok=True)
    stage = layout.pyinstaller_dist
    if stage.exists():
        if not _inside(stage, layout.build_dir) or stage == layout.build_dir:
            raise BuildError("refusing to clear a PyInstaller path outside build-dir")
        shutil.rmtree(stage)
    layout.pyinstaller_work.mkdir(parents=True, exist_ok=True)
    layout.pyinstaller_cache.mkdir(parents=True, exist_ok=True)
    layout.output_dir.mkdir(parents=True, exist_ok=True)


def _windows_path(path: Path) -> str:
    """Render a path for Inno's preprocessor on Windows."""

    return str(path).replace("/", "\\")


def build_commands(layout: BuildLayout, *, pyinstaller: str, iscc: str, version: str) -> tuple[list[str], list[str]]:
    """Return fixed, shell-free commands for PyInstaller and Inno Setup."""

    pyinstaller_command = [
        pyinstaller,
        "--noconfirm",
        "--clean",
        "--log-level",
        "WARN",
        "--distpath",
        str(layout.pyinstaller_dist),
        "--workpath",
        str(layout.pyinstaller_work),
        str(SPEC_PATH),
    ]
    inno_command = [
        iscc,
        f"/DAppVersion={version}",
        f"/DDistDir={_windows_path(layout.renderer_dist)}",
        f"/DConfigFile={_windows_path(layout.config_path)}",
        f"/DOutputDir={_windows_path(layout.output_dir)}",
        str(INNO_PATH),
    ]
    return pyinstaller_command, inno_command


def _run(command: Sequence[str], *, cwd: Path, env: dict[str, str]) -> None:
    try:
        subprocess.run(list(command), cwd=str(cwd), env=env, check=True, shell=False)
    except FileNotFoundError as exc:
        raise BuildError(f"build tool is unavailable: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        raise BuildError(f"build tool failed with exit code {exc.returncode}: {command[0]}") from exc


def _portable_zip_timestamp(source_date_epoch: int) -> tuple[int, int, int, int, int, int]:
    """Return a ZIP-compatible deterministic UTC timestamp."""

    from datetime import datetime, timezone

    epoch = max(source_date_epoch, 315532800)  # ZIP starts at 1980-01-01.
    value = datetime.fromtimestamp(epoch, tz=timezone.utc)
    return (value.year, value.month, value.day, value.hour, value.minute, value.second)


def build_portable_archive(
    renderer_dist: Path,
    artifact_path: Path,
    *,
    source_date_epoch: int,
) -> None:
    """Package the complete frozen onedir runtime without installing it."""

    executable = renderer_dist / "tmm-kompas-renderer.exe"
    config = renderer_dist / "renderer-config.json"
    if not executable.is_file() or not config.is_file():
        raise BuildError("portable renderer requires the executable and adjacent renderer-config.json")
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = _portable_zip_timestamp(source_date_epoch)
    prefix = "tmm-kompas-renderer"
    readme = (
        "TMM KOMPAS Renderer portable\r\n\r\n"
        "Keep this complete directory together. Run tmm-kompas-renderer.exe in the "
        "logged-in interactive Windows session; do not run it as a service. The adjacent "
        "renderer-config.json contains only the production public verification key and "
        "non-secret runtime settings. Probe http://127.0.0.1:17342/v1/capabilities after "
        "startup. Stop the process when the one-off agent task is complete.\r\n"
    ).encode("utf-8")
    with zipfile.ZipFile(
        artifact_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for path in sorted(renderer_dist.rglob("*"), key=lambda item: item.as_posix()):
            if not path.is_file():
                continue
            relative = path.relative_to(renderer_dist).as_posix()
            info = zipfile.ZipInfo(f"{prefix}/{relative}", timestamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
        info = zipfile.ZipInfo(f"{prefix}/README-portable.txt", timestamp)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o100644 << 16
        archive.writestr(info, readme)


def build_release(
    config: ReleaseConfig,
    *,
    layout: BuildLayout,
    pyinstaller: str = "pyinstaller",
    iscc: str = "ISCC.exe",
    source_date_epoch: int = 0,
    portable_only: bool = False,
    dry_run: bool = False,
) -> BuildResult | None:
    """Generate config and optionally run the Windows packaging toolchain."""

    write_release_config(layout.config_path, config)
    commands = build_commands(layout, pyinstaller=pyinstaller, iscc=iscc, version=config.renderer_version)
    if dry_run:
        return None
    if os.name != "nt":
        raise BuildError("Windows PyInstaller/Inno build requires Windows; use --dry-run on another host")
    if sys.maxsize <= 2**32:
        raise BuildError("the released KOMPAS Renderer requires 64-bit Windows Python")

    _prepare_stage(layout)
    env = os.environ.copy()
    env["SOURCE_DATE_EPOCH"] = str(source_date_epoch)
    env["PYTHONHASHSEED"] = "0"
    env["PYINSTALLER_CONFIG_DIR"] = str(layout.pyinstaller_cache)
    env["TMM_RENDERER_CONFIG"] = str(layout.config_path)
    _run(commands[0], cwd=PACKAGE_ROOT, env=env)
    executable = layout.renderer_dist / "tmm-kompas-renderer.exe"
    packaged_config = layout.renderer_dist / "renderer-config.json"
    if not executable.is_file() or not packaged_config.is_file():
        raise BuildError("PyInstaller did not produce the executable and embedded renderer-config.json")
    if packaged_config.read_bytes() != config_bytes(config):
        raise BuildError("PyInstaller embedded a different renderer-config.json")

    build_portable_archive(
        layout.renderer_dist,
        layout.portable_artifact_path,
        source_date_epoch=source_date_epoch,
    )
    portable_digest = sha256_file(layout.portable_artifact_path)
    portable_hash_path = layout.portable_artifact_path.with_name(
        layout.portable_artifact_path.name + ".sha256"
    )
    with portable_hash_path.open("w", encoding="ascii", newline="\n") as stream:
        stream.write(f"{portable_digest}  {layout.portable_artifact_path.name}\n")

    installer_digest: str | None = None
    installer_hash_path: Path | None = None
    if not portable_only:
        _run(commands[1], cwd=PACKAGE_ROOT, env=env)
        if not layout.artifact_path.is_file():
            raise BuildError(f"Inno Setup did not produce {layout.artifact_path.name}")
        installer_digest = sha256_file(layout.artifact_path)
        installer_hash_path = layout.artifact_path.with_name(layout.artifact_path.name + ".sha256")
        with installer_hash_path.open("w", encoding="ascii", newline="\n") as stream:
            stream.write(f"{installer_digest}  {layout.artifact_path.name}\n")
    evidence_path = layout.artifact_path.with_name("release-evidence.json")
    evidence = {
        "renderer_version": config.renderer_version,
        "installer_artifact": None if portable_only else layout.artifact_path.name,
        "installer_sha256": installer_digest,
        "installer_size": None if portable_only else layout.artifact_path.stat().st_size,
        "portable_artifact": layout.portable_artifact_path.name,
        "portable_sha256": portable_digest,
        "portable_size": layout.portable_artifact_path.stat().st_size,
        "config_sha256": hashlib.sha256(config_bytes(config)).hexdigest(),
        "protocol_version": RENDERER_PROTOCOL_VERSION,
    }
    with evidence_path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(evidence, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n")
    return BuildResult(
        installer_artifact=None if portable_only else layout.artifact_path,
        installer_sha256=installer_digest,
        installer_size=None if portable_only else layout.artifact_path.stat().st_size,
        installer_hash_file=installer_hash_path,
        portable_artifact=layout.portable_artifact_path,
        portable_sha256=portable_digest,
        portable_size=layout.portable_artifact_path.stat().st_size,
        portable_hash_file=portable_hash_path,
        evidence_file=evidence_path,
    )


def _release_allowed_origins(explicit: Iterable[str]) -> tuple[str, ...]:
    """Use the deployment origin only when no explicit origins were supplied."""

    origins = tuple(explicit)
    if origins:
        return origins
    site_origin = os.environ.get("TMM_SITE_ORIGIN")
    return (site_origin,) if site_origin else ()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    key = parser.add_mutually_exclusive_group(required=True)
    key.add_argument("--public-key", help="Ed25519 public key in PEM format")
    key.add_argument("--public-key-file", type=Path, help="UTF-8 file containing an Ed25519 public key")
    parser.add_argument("--key-id", required=True, help="release signing key id")
    parser.add_argument(
        "--allowed-origin",
        "--origin",
        "--origins",
        dest="allowed_origins",
        action="append",
        help="one exact browser Origin; repeat for multiple origins (falls back to TMM_SITE_ORIGIN when omitted)",
    )
    parser.add_argument("--renderer-version", required=True, help="semantic renderer version")
    parser.add_argument(
        "--build-dir",
        type=Path,
        default=PACKAGE_ROOT / "build" / "windows",
        help="generated PyInstaller/config staging directory",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PACKAGE_ROOT / "dist",
        help="directory receiving setup.exe and release evidence",
    )
    parser.add_argument("--pyinstaller", default="pyinstaller", help="PyInstaller executable")
    parser.add_argument("--iscc", default="ISCC.exe", help="Inno Setup compiler executable")
    parser.add_argument(
        "--source-date-epoch",
        type=int,
        default=int(os.environ.get("SOURCE_DATE_EPOCH", "0")),
        help="stable SOURCE_DATE_EPOCH passed to build tools (default: 0)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate inputs, write renderer-config.json, and print commands without executing Windows tools",
    )
    parser.add_argument(
        "--portable-only",
        action="store_true",
        help="build the portable ZIP without requiring or invoking Inno Setup",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.public_key_file is not None:
            try:
                public_key = args.public_key_file.read_text(encoding="utf-8")
            except OSError as exc:
                raise BuildError(f"cannot read public-key file: {args.public_key_file}") from exc
        else:
            public_key = args.public_key
        config = make_release_config(
            public_key=public_key,
            key_id=args.key_id,
            allowed_origins=_release_allowed_origins(args.allowed_origins or ()),
            renderer_version=args.renderer_version,
        )
        layout = _layout(args.build_dir, args.output_dir, config.renderer_version)
        commands = build_commands(layout, pyinstaller=args.pyinstaller, iscc=args.iscc, version=config.renderer_version)
        result = build_release(
            config,
            layout=layout,
            pyinstaller=args.pyinstaller,
            iscc=args.iscc,
            source_date_epoch=args.source_date_epoch,
            portable_only=args.portable_only,
            dry_run=args.dry_run,
        )
        report = {
            "renderer_config": str(layout.config_path),
            "installer_artifact": None if args.portable_only else str(layout.artifact_path),
            "portable_artifact": str(layout.portable_artifact_path),
            "commands": [list(command) for command in commands],
            "dry_run": args.dry_run,
            "evidence_file": str(layout.artifact_path.with_name("release-evidence.json")),
            "installer_hash_file": (
                None
                if args.portable_only
                else str(layout.artifact_path.with_name(layout.artifact_path.name + ".sha256"))
            ),
            "portable_hash_file": str(
                layout.portable_artifact_path.with_name(layout.portable_artifact_path.name + ".sha256")
            ),
            "protocol_version": RENDERER_PROTOCOL_VERSION,
        }
        if result is not None:
            report.update(
                {
                    "installer_artifact": (
                        None if result.installer_artifact is None else str(result.installer_artifact)
                    ),
                    "installer_sha256": result.installer_sha256,
                    "installer_size": result.installer_size,
                    "installer_hash_file": (
                        None
                        if result.installer_hash_file is None
                        else str(result.installer_hash_file)
                    ),
                    "portable_artifact": str(result.portable_artifact),
                    "portable_sha256": result.portable_sha256,
                    "portable_size": result.portable_size,
                    "portable_hash_file": str(result.portable_hash_file),
                    "evidence_file": str(result.evidence_file),
                }
            )
        print(json.dumps(report, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
        return 0
    except BuildError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
