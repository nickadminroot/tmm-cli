"""Localhost KOMPAS Renderer for signed declarative render plans.

The renderer is intentionally a narrow native boundary. It accepts one signed
`tmm-kompas-plan` at a time, reconstructs a validated Scene v2 document, and
runs the existing COM adapter. It never accepts commands, paths, scripts, or
arbitrary COM member names.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import errno
import hashlib
import ipaddress
import json
import math
import ntpath
import os
import re
import sys
import tempfile
import threading
import uuid
from collections import OrderedDict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .render import build_drawing
from .text_block_parser import STANDARD_TEXT_HEIGHTS

PLAN_FORMAT = "tmm-kompas-plan"
PLAN_VERSION = 1
PLAN_ALGORITHM = "ed25519"
RENDERER_PROTOCOL_VERSION = 2
RENDERER_VERSION = "0.2.0"
MAX_RENDERER_VERSION_LENGTH = 64
REQUIRED_CAPABILITIES = (
    "scene-v2",
    "api7",
    "api5-text",
    "visible-document",
    "cdw-return",
)
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 17_342
MAX_PLAN_BYTES = 8 * 1024 * 1024
MAX_CDW_BYTES = 25 * 1024 * 1024
MAX_CONFIG_BYTES = 64 * 1024
MAX_ENTITIES = 10_000
MAX_TEXT_BYTES = 256 * 1024
MAX_COORDINATE = 1_000_000_000.0
CHALLENGE_BYTES = 32
CHALLENGE_TTL = timedelta(minutes=10)
RUNS_DIRECTORY = "runs"
RUNS_MARKER = ".tmm-kompas-renderer-runs"

_LAYERS = {"fixed", "thin", "hatch", "label", "dimension"}
_STYLES = {"solid", "dashed", "dotted"}
_SHEET_FORMATS = {"A0", "A1", "A2", "A3", "A4", "A5"}
_KEY_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class RendererError(ValueError):
    """A safe protocol or plan error suitable for a JSON response."""

    def __init__(self, code: str, message: str, *, status: int = 422):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


class RendererUnavailable(RuntimeError):
    """The renderer cannot start with its configured verification key."""


def canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise RendererError("plan_invalid", "plan contains an invalid value") from exc


def _decode_b64(value: object, field: str) -> bytes:
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise RendererError("plan_invalid", f"{field} is invalid")
    try:
        encoded = value.encode("ascii")
        padding = b"=" * (-len(encoded) % 4)
        return base64.b64decode(encoded + padding, altchars=b"-_", validate=True)
    except (UnicodeEncodeError, binascii.Error) as exc:
        raise RendererError("plan_invalid", f"{field} is invalid") from exc


def _load_public_key(material: str, *, field: str) -> Ed25519PublicKey:
    material = material.strip()
    if not material:
        raise RendererUnavailable(f"{field} is empty")
    if material.startswith("-----BEGIN"):
        try:
            key = serialization.load_pem_public_key(material.encode("utf-8"))
        except (ValueError, TypeError) as exc:
            raise RendererUnavailable(f"{field} is invalid") from exc
        if not isinstance(key, Ed25519PublicKey):
            raise RendererUnavailable(f"{field} must be an Ed25519 public key")
        return key
    if len(material) == 64:
        try:
            raw = bytes.fromhex(material)
        except ValueError:
            pass
        else:
            try:
                return Ed25519PublicKey.from_public_bytes(raw)
            except ValueError as exc:
                raise RendererUnavailable(f"{field} is invalid") from exc
    try:
        raw = _decode_b64(material, field=field)
    except RendererError as exc:
        raise RendererUnavailable(f"{field} is invalid") from exc
    if len(raw) != 32:
        raise RendererUnavailable(f"{field} must encode 32 bytes")
    try:
        return Ed25519PublicKey.from_public_bytes(raw)
    except ValueError as exc:
        raise RendererUnavailable(f"{field} is invalid") from exc

_CONFIG_KEYS = frozenset(
    {"public_key", "key_id", "allowed_origins", "renderer_version", "data_directory"}
)
_SEMVER_RE = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


def _origin(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > 1024:
        raise RendererUnavailable(f"{field} contains an invalid origin")
    if any(character.isspace() for character in value) or "*" in value or value == "null":
        raise RendererUnavailable(f"{field} contains an invalid origin")
    try:
        parsed = urlsplit(value)
    except ValueError:
        raise RendererUnavailable(f"{field} contains an invalid origin") from None
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise RendererUnavailable(f"{field} contains an invalid origin")
    try:
        hostname = parsed.hostname
        port = parsed.port
        if (
            (parsed.scheme.lower() == "http" and port == 80)
            or (parsed.scheme.lower() == "https" and port == 443)
        ):
            raise ValueError
        if not hostname or any(character.isspace() for character in hostname):
            raise ValueError
        if port is not None and not 1 <= port <= 65535:
            raise ValueError
    except (TypeError, ValueError):
        raise RendererUnavailable(f"{field} contains an invalid origin") from None
    # Origin serialization has no trailing slash and no default-port rewrite
    # that this boundary should guess.  Keep the configured text exact.
    if value != f"{parsed.scheme}://{parsed.netloc}":
        raise RendererUnavailable(f"{field} contains an invalid origin")
    return value

def _origins(value: object, field: str = "allowed_origins") -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > 32:
        raise RendererUnavailable(f"{field} must be a list")
    result: list[str] = []
    for index, item in enumerate(value):
        parsed = _origin(item, f"{field}[{index}]")
        if parsed not in result:
            result.append(parsed)
    return tuple(result)


def _expand_config_path(value: object) -> Path:
    if isinstance(value, os.PathLike):
        value = os.fspath(value)
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > 4096:
        raise RendererUnavailable("data_directory is invalid")
    if "\x00" in value:
        raise RendererUnavailable("data_directory is invalid")
    expanded = os.path.expanduser(os.path.expandvars(value))
    # ``expandvars`` does not expand Windows %NAME% syntax on POSIX.  This
    # keeps release config fixtures inspectable on Linux while still refusing
    # unresolved variables at runtime.
    if os.name != "nt":
        expanded = expanded.replace("\\", "/")
    expanded = re.sub(
        r"%([A-Za-z_][A-Za-z0-9_]*)%",
        lambda match: os.environ.get(match.group(1), match.group(0)),
        expanded,
    )
    if "%" in expanded and re.search(r"%[A-Za-z_][A-Za-z0-9_]*%", expanded):
        raise RendererUnavailable("data_directory contains an unknown environment variable")
    if not (Path(expanded).is_absolute() or ntpath.isabs(expanded)):
        raise RendererUnavailable("data_directory must be absolute")
    return Path(expanded)


def _strict_json_object(data: bytes, *, field: str) -> dict[str, Any]:
    if len(data) > MAX_CONFIG_BYTES:
        raise RendererUnavailable(f"{field} exceeds the size limit")

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise RendererUnavailable(f"{field} contains duplicate keys")
            result[key] = value
        return result

    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=pairs,
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise RendererUnavailable(f"{field} is invalid") from exc
    if not isinstance(value, dict):
        raise RendererUnavailable(f"{field} must contain an object")
    return value


@dataclass(frozen=True)
class RendererConfig:
    """Verified release configuration used by an installed renderer.

    Release files intentionally have a tiny exact schema.  Endpoint overrides
    are runtime concerns and are not read from the installed JSON.
    """

    public_key: Ed25519PublicKey
    key_id: str
    origins: tuple[str, ...]
    renderer_version: str
    data_dir: Path | str
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    installed: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.public_key, Ed25519PublicKey):
            raise RendererUnavailable("public_key must be an Ed25519 public key")
        if not isinstance(self.key_id, str) or not _KEY_ID_RE.fullmatch(self.key_id):
            raise RendererUnavailable("key_id is invalid")
        if (
            not isinstance(self.renderer_version, str)
            or len(self.renderer_version) > MAX_RENDERER_VERSION_LENGTH
            or not _SEMVER_RE.fullmatch(self.renderer_version)
        ):
            raise RendererUnavailable("renderer_version is invalid")
        if isinstance(self.origins, str):
            raise RendererUnavailable("allowed_origins must be a list")
        checked_origins = _origins(list(self.origins))
        if self.host != DEFAULT_HOST:
            raise RendererUnavailable("renderer must bind to 127.0.0.1")
        if isinstance(self.port, bool) or not isinstance(self.port, int) or not 1 <= self.port <= 65535:
            raise RendererUnavailable("renderer port is invalid")
        directory = _expand_config_path(self.data_dir)
        object.__setattr__(self, "origins", checked_origins)
        object.__setattr__(self, "data_dir", directory)

    @property
    def allowed_origins(self) -> tuple[str, ...]:
        return self.origins

    @property
    def data_directory(self) -> Path:
        return self.data_dir  # type: ignore[return-value]

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> RendererConfig:
        if not isinstance(value, Mapping) or set(value) != _CONFIG_KEYS:
            raise RendererUnavailable(
                "renderer-config.json must contain exactly public_key, key_id, "
                "allowed_origins, renderer_version, and data_directory"
            )
        return cls(
            public_key=_load_public_key(str(value["public_key"]), field="public_key"),
            key_id=value["key_id"],  # type: ignore[arg-type]
            origins=tuple(_origins(value["allowed_origins"])),
            renderer_version=value["renderer_version"],  # type: ignore[arg-type]
            data_dir=value["data_directory"],  # type: ignore[arg-type]
            installed=True,
        )

    @classmethod
    def from_file(cls, path: str | os.PathLike[str]) -> RendererConfig:
        config_path = Path(path).expanduser()
        try:
            data = config_path.read_bytes()
        except OSError as exc:
            raise RendererUnavailable("installed renderer configuration is unavailable") from exc
        return cls.from_mapping(_strict_json_object(data, field="renderer-config.json"))

    @classmethod
    def from_environment(cls) -> RendererConfig:
        """Load the explicitly supported development-only environment seam."""
        raw = os.environ.get("TMM_KOMPAS_PLAN_PUBLIC_KEY", "")
        key_file = os.environ.get("TMM_KOMPAS_PLAN_PUBLIC_KEY_FILE", "")
        if raw and key_file:
            raise RendererUnavailable("configure only one KOMPAS plan public key source")
        if key_file:
            try:
                raw = Path(os.path.expanduser(key_file)).read_text(encoding="utf-8")
            except OSError as exc:
                raise RendererUnavailable("KOMPAS plan public key unavailable") from exc
        key = _load_public_key(raw, field="TMM_KOMPAS_PLAN_PUBLIC_KEY")
        raw_origins = os.environ.get("TMM_KOMPAS_RENDERER_ORIGINS")
        if raw_origins is None:
            single_origin = os.environ.get("TMM_KOMPAS_RENDERER_ORIGIN")
            raw_origins = "" if single_origin is None else single_origin
        origins = [] if not raw_origins else [item.strip() for item in raw_origins.split(",")]
        return cls(
            public_key=key,
            key_id=os.environ.get("TMM_KOMPAS_PLAN_KEY_ID", "default"),
            origins=tuple(_origins(origins)),
            renderer_version=os.environ.get("TMM_KOMPAS_RENDERER_VERSION", RENDERER_VERSION),
            data_dir=os.environ.get("TMM_KOMPAS_RENDERER_DATA_DIR", str(default_renderer_data_dir())),
            installed=False,
        )


def default_renderer_data_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "TMM" / "KompasRenderer"
    if os.name == "nt":
        return Path.home() / "AppData" / "Local" / "TMM" / "KompasRenderer"
    return Path(tempfile.gettempdir()) / "TMM" / "KompasRenderer"


def load_renderer_config(
    config_path: str | os.PathLike[str] | None = None,
    *,
    development: bool = False,
) -> RendererConfig:
    configured_path = config_path or os.environ.get("TMM_KOMPAS_RENDERER_CONFIG")
    if getattr(sys, "frozen", False):
        if development:
            raise RendererUnavailable("installed renderer does not support development configuration")
        install_config = Path(sys.executable).resolve().parent / "renderer-config.json"
        candidate = install_config if configured_path is None else Path(configured_path).expanduser()
        try:
            if candidate.resolve(strict=False) != install_config:
                raise RendererUnavailable("installed renderer configuration must come from its install directory")
        except RuntimeError as exc:
            raise RendererUnavailable("installed renderer configuration path is invalid") from exc
        return RendererConfig.from_file(install_config)
    if configured_path:
        # Installed config is authoritative.  Development env/CLI values must
        # never override release public key, origins, or data directory.
        return RendererConfig.from_file(configured_path)
    if not development and os.environ.get("TMM_KOMPAS_RENDERER_DEV") != "1":
        raise RendererUnavailable(
            "installed renderer configuration is required; use --dev only for development"
        )
    return RendererConfig.from_environment()
def public_key_from_environment() -> Ed25519PublicKey:
    """Load the development public key without accepting installed overrides."""
    return RendererConfig.from_environment().public_key


def _string(value: object, field: str, *, empty: bool = False, max_bytes: int = 1024) -> str:
    if not isinstance(value, str):
        raise RendererError("plan_invalid", f"{field} must be a string")
    if not empty and not value:
        raise RendererError("plan_invalid", f"{field} must be non-empty")
    try:
        encoded_length = len(value.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise RendererError("plan_invalid", f"{field} must contain valid UTF-8") from exc
    if encoded_length > max_bytes:
        raise RendererError("plan_invalid", f"{field} is too long")
    return value


def _number(value: object, field: str, *, minimum: float | None = None, positive: bool = False) -> object:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RendererError("plan_invalid", f"{field} must be a finite number")
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise RendererError("plan_invalid", f"{field} must be a finite number") from exc
    if not math.isfinite(number):
        raise RendererError("plan_invalid", f"{field} must be a finite number")
    if abs(number) > MAX_COORDINATE:
        raise RendererError("plan_invalid", f"{field} is outside the supported range")
    if positive and number <= 0:
        raise RendererError("plan_invalid", f"{field} must be positive")
    if minimum is not None and number < minimum:
        raise RendererError("plan_invalid", f"{field} is below the supported range")
    return value


def _standard_text_size(value: object, field: str) -> object:
    size = _number(value, field, positive=True)
    if not any(math.isclose(float(size), allowed, abs_tol=1e-9) for allowed in STANDARD_TEXT_HEIGHTS):
        raise RendererError("plan_invalid", f"{field} is not a supported text height")
    return size


def _point(value: object, field: str) -> list[object]:
    if not isinstance(value, list) or len(value) != 2:
        raise RendererError("plan_invalid", f"{field} must be a point")
    return [_number(value[0], f"{field}[0]"), _number(value[1], f"{field}[1]")]


def _optional_text(value: object, field: str) -> str:
    return _string(value, field, empty=True, max_bytes=MAX_TEXT_BYTES)


def _check_layer_style(entity: dict[str, Any]) -> None:
    if "layer" in entity and entity["layer"] not in _LAYERS:
        raise RendererError("plan_invalid", "entity layer is unsupported")
    if "style" in entity and entity["style"] not in _STYLES:
        raise RendererError("plan_invalid", "entity style is unsupported")


def _validate_cells(value: object, *, rows: int, columns: int) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > 65_536:
        raise RendererError("plan_invalid", "table cells are invalid")
    result: list[dict[str, Any]] = []
    allowed = {"row", "column", "rowSpan", "colSpan", "text", "fontSize", "italic", "layer"}
    occupied: set[tuple[int, int]] = set()
    for index, raw in enumerate(value):
        if not isinstance(raw, dict) or set(raw) - allowed:
            raise RendererError("plan_invalid", f"table cell {index} is invalid")
        row = raw.get("row")
        column = raw.get("column")
        row_span = raw.get("rowSpan", 1)
        col_span = raw.get("colSpan", 1)
        if (
            isinstance(row, bool)
            or not isinstance(row, int)
            or row < 0
            or isinstance(column, bool)
            or not isinstance(column, int)
            or column < 0
            or isinstance(row_span, bool)
            or not isinstance(row_span, int)
            or row_span < 1
            or isinstance(col_span, bool)
            or not isinstance(col_span, int)
            or col_span < 1
        ):
            raise RendererError("plan_invalid", f"table cell {index} coordinates are invalid")
        if row >= rows or column >= columns or row + row_span > rows or column + col_span > columns:
            raise RendererError("plan_invalid", f"table cell {index} is outside the table")
        footprint = {
            (occupied_row, occupied_column)
            for occupied_row in range(row, row + row_span)
            for occupied_column in range(column, column + col_span)
        }
        if occupied.intersection(footprint):
            raise RendererError("plan_invalid", f"table cell {index} overlaps another cell")
        occupied.update(footprint)
        text = _optional_text(raw.get("text"), f"cells[{index}].text")
        if "\r" in text or "\n" in text:
            raise RendererError("plan_invalid", f"cells[{index}].text must be a single line")
        item: dict[str, Any] = {
            "row": row,
            "column": column,
            "text": text,
        }
        if row_span != 1:
            item["rowSpan"] = row_span
        if col_span != 1:
            item["colSpan"] = col_span
        if "fontSize" in raw:
            item["fontSize"] = _number(raw["fontSize"], f"cells[{index}].fontSize", positive=True)
        if "italic" in raw:
            if not isinstance(raw["italic"], bool):
                raise RendererError("plan_invalid", f"cells[{index}].italic is invalid")
            item["italic"] = raw["italic"]
        if "layer" in raw:
            if raw["layer"] not in _LAYERS:
                raise RendererError("plan_invalid", f"cells[{index}].layer is invalid")
            item["layer"] = raw["layer"]
        result.append(item)
    return result


def _sizes(value: object, field: str) -> list[object]:
    if not isinstance(value, list) or not value or len(value) > 256:
        raise RendererError("plan_invalid", f"{field} is invalid")
    return [_number(item, f"{field}[{index}]", positive=True) for index, item in enumerate(value)]


def _entity(raw: object) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise RendererError("plan_invalid", "plan entity must be an object")
    ctype = _string(raw.get("type"), "entity.type")
    allowed_fields = {
        "line": {"id", "type", "layer", "style", "from", "to"},
        "circle": {"id", "type", "layer", "style", "center", "radius", "filled"},
        "arc": {"id", "type", "layer", "style", "center", "radius", "startAngle", "endAngle", "direction"},
        "polygon": {"id", "type", "layer", "style", "points", "filled", "role"},
        "text": {"id", "type", "layer", "style", "text", "position", "fontSize", "width", "angle", "italic", "latex"},
        "smoothCurve": {"id", "type", "layer", "style", "points", "strokeWidth"},
        "textBlock": {"id", "type", "layer", "style", "text", "position", "fontSize", "width", "italic"},
        "table": {"id", "type", "layer", "style", "position", "columnWidths", "rowHeights", "cells", "fontSize", "italic", "gridLayer", "gridStyle"},
    }
    allowed = allowed_fields.get(ctype)
    if allowed is None or set(raw) - allowed:
        raise RendererError("plan_invalid", "plan entity type or fields are unsupported")
    result: dict[str, Any] = {
        "id": _string(raw.get("id"), "entity.id"),
        "type": ctype,
    }
    _check_layer_style(raw)
    for key in ("layer", "style"):
        if key in raw:
            result[key] = raw[key]
    if ctype == "line":
        result["from"] = _point(raw.get("from"), "from")
        result["to"] = _point(raw.get("to"), "to")
    elif ctype == "circle":
        result["center"] = _point(raw.get("center"), "center")
        result["radius"] = _number(raw.get("radius"), "radius", minimum=0)
        if "filled" in raw:
            if not isinstance(raw["filled"], bool):
                raise RendererError("plan_invalid", "circle.filled is invalid")
            result["filled"] = raw["filled"]
    elif ctype == "arc":
        result["center"] = _point(raw.get("center"), "center")
        result["radius"] = _number(raw.get("radius"), "radius", minimum=0)
        result["startAngle"] = _number(raw.get("startAngle"), "startAngle")
        result["endAngle"] = _number(raw.get("endAngle"), "endAngle")
        if "direction" in raw:
            if not isinstance(raw["direction"], bool):
                raise RendererError("plan_invalid", "arc.direction is invalid")
            result["direction"] = raw["direction"]
    elif ctype == "polygon":
        points = raw.get("points")
        if not isinstance(points, list) or len(points) < 3 or len(points) > MAX_ENTITIES:
            raise RendererError("plan_invalid", "polygon points are invalid")
        result["points"] = [_point(point, f"points[{index}]") for index, point in enumerate(points)]
        if "filled" in raw:
            if not isinstance(raw["filled"], bool):
                raise RendererError("plan_invalid", "polygon.filled is invalid")
            result["filled"] = raw["filled"]
        if "role" in raw:
            result["role"] = _string(raw["role"], "polygon.role", empty=True)
    elif ctype == "text":
        result["text"] = _optional_text(raw.get("text"), "text")
        result["position"] = _point(raw.get("position"), "position")
        if "fontSize" in raw:
            result["fontSize"] = _number(raw["fontSize"], "fontSize", minimum=0)
        if "width" in raw:
            result["width"] = _number(raw["width"], "width", positive=True)
        if "angle" in raw:
            result["angle"] = _number(raw["angle"], "angle")
        if "italic" in raw:
            if not isinstance(raw["italic"], bool):
                raise RendererError("plan_invalid", "text.italic is invalid")
            result["italic"] = raw["italic"]
        if "latex" in raw:
            result["latex"] = _optional_text(raw["latex"], "latex")
    elif ctype == "smoothCurve":
        points = raw.get("points")
        if not isinstance(points, list) or len(points) < 2 or len(points) > MAX_ENTITIES:
            raise RendererError("plan_invalid", "smoothCurve points are invalid")
        result["points"] = [_point(point, f"points[{index}]") for index, point in enumerate(points)]
        if "strokeWidth" in raw:
            result["strokeWidth"] = _number(raw["strokeWidth"], "strokeWidth", positive=True)
    elif ctype == "textBlock":
        result["text"] = _optional_text(raw.get("text"), "text")
        result["position"] = _point(raw.get("position"), "position")
        result["fontSize"] = _standard_text_size(raw.get("fontSize"), "fontSize")
        result["width"] = _number(raw.get("width"), "width", positive=True)
        if "italic" in raw:
            if not isinstance(raw["italic"], bool):
                raise RendererError("plan_invalid", "textBlock.italic is invalid")
            result["italic"] = raw["italic"]
    elif ctype == "table":
        result["position"] = _point(raw.get("position"), "position")
        columns = _sizes(raw.get("columnWidths"), "columnWidths")
        rows = _sizes(raw.get("rowHeights"), "rowHeights")
        result["columnWidths"] = columns
        result["rowHeights"] = rows
        result["cells"] = _validate_cells(raw.get("cells"), rows=len(rows), columns=len(columns))
        if "fontSize" in raw:
            result["fontSize"] = _number(raw["fontSize"], "fontSize", positive=True)
        if "italic" in raw:
            if not isinstance(raw["italic"], bool):
                raise RendererError("plan_invalid", "table.italic is invalid")
            result["italic"] = raw["italic"]
        for key, values in (("gridLayer", _LAYERS), ("gridStyle", _STYLES)):
            if key in raw:
                if raw[key] not in values:
                    raise RendererError("plan_invalid", f"table.{key} is invalid")
                result[key] = raw[key]
    return result


def _sheet(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RendererError("plan_invalid", "document.sheet is invalid")
    allowed = {"format", "orientation", "titleBlock"}
    if set(value) - allowed:
        raise RendererError("plan_invalid", "document.sheet fields are unsupported")
    format_name = _string(value.get("format"), "sheet.format").upper()
    if format_name not in _SHEET_FORMATS:
        raise RendererError("plan_invalid", "sheet.format is unsupported")
    orientation = _string(value.get("orientation", "landscape"), "sheet.orientation").lower()
    if orientation not in {"landscape", "portrait"}:
        raise RendererError("plan_invalid", "sheet.orientation is unsupported")
    result: dict[str, Any] = {"format": format_name, "orientation": orientation}
    if "titleBlock" in value:
        title_block = value["titleBlock"]
        if not isinstance(title_block, dict) or set(title_block) - {"cell", "text"}:
            raise RendererError("plan_invalid", "sheet.titleBlock is invalid")
        title: dict[str, Any] = {}
        if "cell" in title_block:
            cell = title_block["cell"]
            if isinstance(cell, bool) or not isinstance(cell, int) or cell < 1:
                raise RendererError("plan_invalid", "sheet.titleBlock.cell is invalid")
            title["cell"] = cell
        if "text" in title_block:
            title["text"] = _optional_text(title_block["text"], "sheet.titleBlock.text")
        result["titleBlock"] = title
    return result


def _parse_timestamp(value: object, field: str) -> datetime:
    text = _string(value, field)
    try:
        parsed = datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise RendererError("plan_invalid", f"{field} is invalid") from exc
    return parsed


def _scene_from_plan(
    plan: dict[str, Any],
    *,
    challenge: str,
    public_key: Ed25519PublicKey,
    key_id: str,
    check_challenge: bool = True,
) -> tuple[str, dict[str, Any]]:
    if set(plan) != {"format", "version", "algorithm", "key_id", "payload", "signature"}:
        raise RendererError("plan_invalid", "plan envelope fields are invalid")
    if (
        plan["format"] != PLAN_FORMAT
        or plan["version"] != PLAN_VERSION
        or plan["algorithm"] != PLAN_ALGORITHM
        or plan["key_id"] != key_id
    ):
        raise RendererError("plan_invalid", "plan envelope is unsupported")
    unsigned = {
        key: plan[key] for key in ("format", "version", "algorithm", "key_id", "payload")
    }
    signature = _decode_b64(plan["signature"], "signature")
    if len(signature) != 64:
        raise RendererError("plan_invalid", "signature is invalid")
    try:
        public_key.verify(signature, canonical_json(unsigned))
    except Exception as exc:  # cryptography exposes backend-specific errors
        raise RendererError("plan_invalid", "plan signature is invalid", status=401) from exc
    payload = plan["payload"]
    required = {"operation", "job_id", "agent_challenge", "issued_at", "expires_at", "scene_sha256", "document", "operations"}
    if not isinstance(payload, dict) or set(payload) != required:
        raise RendererError("plan_invalid", "plan payload fields are invalid")
    if payload["operation"] != "kompas-plan" or not isinstance(payload["agent_challenge"], str):
        raise RendererError("plan_invalid", "plan is not issued for this renderer", status=401)
    if check_challenge and payload["agent_challenge"] != challenge:
        raise RendererError("plan_invalid", "plan is not issued for this renderer", status=401)
    try:
        job_id = uuid.UUID(_string(payload["job_id"], "job_id"))
    except (ValueError, AttributeError, TypeError) as exc:
        raise RendererError("plan_invalid", "job_id is invalid") from exc
    if job_id.version != 4 or job_id.variant != uuid.RFC_4122:
        raise RendererError("plan_invalid", "job_id must be UUID v4")
    issued_at = _parse_timestamp(payload["issued_at"], "issued_at")
    expires_at = _parse_timestamp(payload["expires_at"], "expires_at")
    now = datetime.now(timezone.utc)
    if issued_at > now + timedelta(minutes=1) or expires_at <= now or expires_at <= issued_at or expires_at - issued_at > CHALLENGE_TTL:
        raise RendererError("plan_expired", "plan is expired or outside its validity window", status=401)
    scene_hash = _string(payload["scene_sha256"], "scene_sha256")
    if not _SHA256_RE.fullmatch(scene_hash):
        raise RendererError("plan_invalid", "scene_sha256 is invalid")
    document = payload["document"]
    if not isinstance(document, dict) or set(document) - {"id", "units", "kind", "sheet"}:
        raise RendererError("plan_invalid", "plan document is invalid")
    scene: dict[str, Any] = {
        "format": "tmm-scene",
        "version": 2,
        "units": document.get("units"),
        "id": _string(document.get("id"), "document.id"),
    }
    if scene["units"] != "mm":
        raise RendererError("plan_invalid", "plan document units are unsupported")
    if "kind" in document:
        scene["kind"] = _string(document["kind"], "document.kind", empty=True)
    if "sheet" in document:
        scene["sheet"] = _sheet(document["sheet"])
    if scene.get("kind") == "super-scene" and "sheet" not in scene:
        raise RendererError("plan_invalid", "super-scene requires a sheet")
    operations = payload["operations"]
    if not isinstance(operations, list) or len(operations) > MAX_ENTITIES:
        raise RendererError("plan_invalid", "plan operations are invalid")
    entities: list[dict[str, Any]] = []
    for index, operation in enumerate(operations):
        if not isinstance(operation, dict) or set(operation) != {"op", "entity"}:
            raise RendererError("plan_invalid", f"operation {index} is invalid")
        entity = _entity(operation["entity"])
        if operation["op"] != entity["type"]:
            raise RendererError("plan_invalid", f"operation {index} type does not match entity")
        entities.append(entity)
    scene["entities"] = entities
    return str(job_id), scene


RENDERER_MUTEX_NAME = r"Local\TMM.KompasRenderer"


class RendererState:
    """In-memory challenge, replay, and backing-file state."""

    def __init__(
        self,
        public_key: Ed25519PublicKey,
        *,
        key_id: str = "default",
        origin: str | None = None,
        origins: Iterable[str] | None = None,
        renderer_version: str = RENDERER_VERSION,
        data_dir: str | os.PathLike[str] | None = None,
    ):
        if origins is not None and origin is not None:
            raise ValueError("configure origins or origin, not both")
        configured_origins = tuple(origins) if origins is not None else (() if origin is None else (origin,))
        self.config = RendererConfig(
            public_key=public_key,
            key_id=key_id,
            origins=configured_origins,
            renderer_version=renderer_version,
            data_dir=default_renderer_data_dir() if data_dir is None else data_dir,
            installed=False,
        )
        self.public_key = self.config.public_key
        self.key_id = self.config.key_id
        self.origins = self.config.origins
        self.renderer_version = self.config.renderer_version
        self.data_dir = self.config.data_directory
        self.runs_dir = self.data_dir / RUNS_DIRECTORY
        self.runs_marker = self.runs_dir / RUNS_MARKER
        self.renderer_id = str(uuid.uuid4())
        self._challenge = _encode_b64(os.urandom(CHALLENGE_BYTES))
        self._used: OrderedDict[str, None] = OrderedDict()
        self._owned_paths: set[Path] = set()
        self.lock = threading.RLock()
        self.render_lock = threading.Lock()

    @classmethod
    def from_config(cls, config: RendererConfig) -> RendererState:
        return cls(
            config.public_key,
            key_id=config.key_id,
            origins=config.origins,
            renderer_version=config.renderer_version,
            data_dir=config.data_directory,
        )

    @property
    def origin(self) -> str | None:
        """Development compatibility view; release checks use ``origins``."""
        return self.origins[0] if self.origins else None

    @property
    def challenge(self) -> str:
        with self.lock:
            return self._challenge

    def capabilities(self) -> dict[str, Any]:
        return {
            "version": RENDERER_PROTOCOL_VERSION,
            "agent_id": self.renderer_id,
            "agent_version": self.renderer_version,
            "challenge": self.challenge,
            "capabilities": list(REQUIRED_CAPABILITIES),
        }

    def prepare_storage(self) -> None:
        try:
            if self.data_dir.is_symlink() or (self.data_dir.exists() and not self.data_dir.is_dir()):
                raise OSError("invalid data directory")
            if self.runs_dir.is_symlink() or (self.runs_dir.exists() and not self.runs_dir.is_dir()):
                raise OSError("invalid runs directory")
            self.runs_dir.mkdir(parents=True, exist_ok=True)
            if self.runs_dir.is_symlink() or not self.runs_dir.is_dir():
                raise OSError("invalid runs directory")
            if self.runs_marker.is_symlink() or (
                self.runs_marker.exists() and not self.runs_marker.is_file()
            ):
                raise OSError("invalid runs marker")
            if not self.runs_marker.exists():
                self.runs_marker.write_bytes(f"{self.renderer_id}\n".encode("ascii"))
        except OSError as exc:
            raise RendererUnavailable("renderer data directory is unavailable") from exc

    def backing_path(self, job_id: str) -> Path:
        try:
            parsed = uuid.UUID(job_id)
        except (ValueError, AttributeError, TypeError) as exc:
            raise RendererError("plan_invalid", "job_id is invalid") from exc
        if parsed.version != 4 or parsed.variant != uuid.RFC_4122:
            raise RendererError("plan_invalid", "job_id must be UUID v4")
        self.prepare_storage()
        path = (self.runs_dir / f"{parsed}.cdw").resolve()
        if path.parent != self.runs_dir.resolve():
            raise RendererUnavailable("renderer backing path is invalid")
        self._owned_paths.add(path)
        return path

    def cleanup_backing_files(self) -> list[Path]:
        """Remove only old, owned-looking, unlocked run files.

        The marker establishes ownership of the runs directory and UUID-v4
        names are the only names this process ever creates.  A sharing
        violation (including a KOMPAS-open file on Windows) is deliberately
        ignored.
        """
        try:
            if (
                self.data_dir.is_symlink()
                or not self.data_dir.is_dir()
                or self.runs_dir.is_symlink()
                or not self.runs_dir.is_dir()
            ):
                return []
            runs_root = self.runs_dir.resolve(strict=True)
            if self.runs_marker.is_symlink() or not self.runs_marker.is_file():
                return []
            if self.runs_marker.resolve(strict=True).parent != runs_root:
                return []
        except (OSError, RuntimeError):
            return []
        removed: list[Path] = []
        try:
            candidates = tuple(self.runs_dir.glob("*.cdw"))
        except OSError:
            return removed
        for path in candidates:
            try:
                parsed = uuid.UUID(path.stem)
            except (ValueError, AttributeError):
                continue
            if parsed.version != 4 or parsed.variant != uuid.RFC_4122:
                continue
            try:
                if path.is_symlink() or not path.is_file():
                    continue
                resolved = path.resolve(strict=True)
            except (OSError, RuntimeError):
                continue
            if resolved.parent != runs_root or resolved in self._owned_paths:
                continue
            try:
                with path.open("rb"):
                    pass
                path.unlink()
            except (OSError, PermissionError):
                continue
            removed.append(path)
        return removed

    def claim(self, job_id: str, challenge: str) -> None:
        with self.lock:
            if job_id in self._used:
                raise RendererError("plan_replayed", "plan has already been consumed", status=409)
            if challenge != self._challenge:
                raise RendererError("plan_invalid", "plan is not issued for this renderer", status=401)
            self._used[job_id] = None
            while len(self._used) > 2048:
                self._used.popitem(last=False)
            # Rotate as part of the atomic claim, before any COM work starts.
            self._challenge = _encode_b64(os.urandom(CHALLENGE_BYTES))

    def rotate_challenge(self) -> None:
        with self.lock:
            self._challenge = _encode_b64(os.urandom(CHALLENGE_BYTES))


class RendererInstanceLock:
    """Per-user mutex/lock held for the complete interactive renderer lifetime."""

    def __init__(self, data_dir: str | os.PathLike[str]):
        self.data_dir = _expand_config_path(data_dir)
        self._file = None
        self._handle = None

    def acquire(self) -> None:
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RendererUnavailable("renderer data directory is unavailable") from exc
        if os.name == "nt":
            self._acquire_windows()
            return
        try:
            import fcntl

            self._file = (self.data_dir / "renderer.lock").open("a+", encoding="ascii")
            fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (ImportError, OSError) as exc:
            if self._file is not None:
                self._file.close()
                self._file = None
            if isinstance(exc, OSError) and exc.errno in {errno.EACCES, errno.EAGAIN}:
                raise RendererUnavailable("KOMPAS Renderer is already running") from exc
            raise RendererUnavailable("unable to acquire the KOMPAS Renderer lock") from exc

    def _acquire_windows(self) -> None:
        import ctypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_mutex = kernel32.CreateMutexW
        create_mutex.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p)
        create_mutex.restype = ctypes.c_void_p
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = (ctypes.c_void_p,)
        close_handle.restype = ctypes.c_bool
        release_mutex = kernel32.ReleaseMutex
        release_mutex.argtypes = (ctypes.c_void_p,)
        release_mutex.restype = ctypes.c_bool
        handle = create_mutex(None, True, RENDERER_MUTEX_NAME)
        if not handle:
            raise RendererUnavailable("unable to acquire the KOMPAS Renderer mutex")
        if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
            close_handle(handle)
            raise RendererUnavailable("KOMPAS Renderer is already running")
        self._handle = (release_mutex, close_handle, handle)

    def release(self) -> None:
        if self._file is not None:
            try:
                import fcntl

                fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
            except (ImportError, OSError):
                pass
            self._file.close()
            self._file = None
        if self._handle is not None:
            release_mutex, close_handle, handle = self._handle
            release_mutex(handle)
            close_handle(handle)
            self._handle = None

    def __enter__(self) -> RendererInstanceLock:
        self.acquire()
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.release()


def _encode_b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


class RendererHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler, state: RendererState):
        self.state = state
        super().__init__(address, handler)


class RendererRequestHandler(BaseHTTPRequestHandler):
    server: RendererHTTPServer
    protocol_version = "HTTP/1.1"

    def log_message(self, _format: str, *_args: object) -> None:
        return

    @property
    def state(self) -> RendererState:
        return self.server.state

    def _send(
        self,
        status: int,
        body: bytes,
        content_type: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        origin = self.headers.get("Origin")
        if origin and origin in self.state.origins:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Expose-Headers", "Content-Disposition, X-TMM-Result-Sha256")
            self.send_header("Vary", "Origin")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        self._send(status, canonical_json(payload), "application/json; charset=utf-8")

    def _error(self, error: RendererError) -> None:
        self._json(
            error.status,
            {
                "version": RENDERER_PROTOCOL_VERSION,
                "error": {"code": error.code, "message": error.message},
            },
        )

    def _peer_is_loopback(self) -> bool:
        try:
            return ipaddress.ip_address(self.client_address[0].split("%", 1)[0]).is_loopback
        except ValueError:
            return False

    def _host_is_loopback(self) -> bool:
        host = self.headers.get("Host", "")
        if not host or any(character.isspace() for character in host) or "@" in host:
            return False
        host = host.lower()
        if host in {"localhost", "127.0.0.1"}:
            return True
        hostname, separator, port = host.partition(":")
        if hostname not in {"localhost", "127.0.0.1"} or separator != ":":
            return False
        if not port.isdigit() or len(port) > 5:
            return False
        try:
            return 1 <= int(port) <= 65535
        except ValueError:
            return False

    def _has_ambiguous_headers(self) -> bool:
        for name in (
            "Host",
            "Content-Length",
            "Origin",
            "Transfer-Encoding",
            "X-TMM-Agent-Request",
            "Access-Control-Request-Method",
            "Access-Control-Request-Headers",
            "Access-Control-Request-Private-Network",
        ):
            values = self.headers.get_all(name)
            if values is not None and len(values) != 1:
                return True
        return self.headers.get("Transfer-Encoding") is not None

    def _origin_is_allowed(self) -> bool:
        origin = self.headers.get("Origin")
        return origin is None or origin in self.state.origins

    def _common_request_check(self, *, custom_header: bool = False) -> bool:
        if self._has_ambiguous_headers():
            self._json(
                400,
                {
                    "version": RENDERER_PROTOCOL_VERSION,
                    "error": {
                        "code": "request_invalid",
                        "message": "ambiguous request headers",
                    },
                },
            )
            return False
        if not self._peer_is_loopback() or not self._host_is_loopback() or not self._origin_is_allowed():
            self._json(
                403,
                {
                    "version": RENDERER_PROTOCOL_VERSION,
                    "error": {"code": "forbidden", "message": "request is not allowed"},
                },
            )
            return False
        if custom_header and self.headers.get("X-TMM-Agent-Request") != "1":
            self._json(
                400,
                {
                    "version": RENDERER_PROTOCOL_VERSION,
                    "error": {
                        "code": "request_invalid",
                        "message": "missing renderer request header",
                    },
                },
            )
            return False
        return True

    def do_OPTIONS(self) -> None:
        if not self._common_request_check():
            return
        origin = self.headers.get("Origin")
        if origin is None or origin not in self.state.origins:
            self._error(RendererError("forbidden", "origin is not allowed", status=403))
            return
        requested_method = self.headers.get("Access-Control-Request-Method")
        if requested_method and requested_method.upper() not in {"GET", "POST", "OPTIONS"}:
            self._error(RendererError("forbidden", "request method is not allowed", status=403))
            return
        requested_headers = self.headers.get("Access-Control-Request-Headers", "")
        allowed_headers = {"content-type", "x-tmm-agent-request"}
        if any(
            header.strip().lower() not in allowed_headers
            for header in requested_headers.split(",")
            if header.strip()
        ):
            self._error(RendererError("forbidden", "request header is not allowed", status=403))
            return
        pna = self.headers.get("Access-Control-Request-Private-Network")
        if pna is not None and pna.lower() != "true":
            self._error(RendererError("forbidden", "private network request is invalid", status=403))
            return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-TMM-Agent-Request")
        if pna is not None:
            self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Access-Control-Max-Age", "300")
        self.send_header("Vary", "Origin")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        if not self._common_request_check():
            return
        if self.path != "/v1/capabilities":
            self._error(RendererError("not_found", "not found", status=404))
            return
        self._json(200, self.state.capabilities())

    def do_POST(self) -> None:
        if not self._common_request_check(custom_header=True):
            return
        if self.path != "/v1/render":
            self._error(RendererError("not_found", "not found", status=404))
            return
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            self._error(RendererError("request_invalid", "Content-Type must be application/json", status=415))
            return
        try:
            length = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            length = -1
        if length < 0:
            self._error(RendererError("request_invalid", "Content-Length is required", status=411))
            return
        if length > MAX_PLAN_BYTES:
            self._error(RendererError("input_too_large", "plan exceeds the size limit", status=413))
            return
        body = self.rfile.read(length)
        if len(body) != length:
            self._error(RendererError("request_invalid", "request body is truncated"))
            return
        try:
            plan = json.loads(
                body.decode("utf-8"),
                parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
            )
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError):
            self._error(RendererError("request_invalid", "plan JSON is invalid"))
            return
        if not isinstance(plan, dict):
            self._error(RendererError("request_invalid", "plan JSON root must be an object"))
            return
        acquired = self.state.render_lock.acquire(blocking=False)
        if not acquired:
            self._error(RendererError("agent_busy", "KOMPAS Renderer is busy", status=409))
            return
        try:
            try:
                job_id, scene = _scene_from_plan(
                    plan,
                    challenge=self.state.challenge,
                    public_key=self.state.public_key,
                    key_id=self.state.key_id,
                    check_challenge=False,
                )
                self.state.claim(job_id, plan["payload"]["agent_challenge"])
            except RendererError as exc:
                self._error(exc)
                return
            output: Path | None = None
            try:
                output = self.state.backing_path(job_id)
                self.state.cleanup_backing_files()
                build_drawing(scene, str(output), visible=True, keep_open=True)
                if not output.is_file():
                    raise RuntimeError("KOMPAS did not produce a drawing")
                size = output.stat().st_size
                if size <= 0 or size > MAX_CDW_BYTES:
                    raise RuntimeError("KOMPAS drawing size is invalid")
                cdw = output.read_bytes()
                if len(cdw) != size:
                    raise RuntimeError("KOMPAS drawing changed while reading")
            except Exception:  # noqa: BLE001 - COM failures stay behind the typed renderer error boundary.
                if output is not None:
                    try:
                        if not output.is_symlink() and output.is_file():
                            output.unlink()
                    except (OSError, RuntimeError):
                        pass
                self._error(RendererError("kompas_render_failed", "KOMPAS rendering failed", status=502))
                return
            self._send(
                200,
                cdw,
                "application/octet-stream",
                headers={
                    "Content-Disposition": "attachment; filename=\"result.cdw\"",
                    "X-TMM-Result-Sha256": hashlib.sha256(cdw).hexdigest(),
                },
            )
        finally:
            self.state.render_lock.release()


def create_server(
    state: RendererState,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> RendererHTTPServer:
    if host != DEFAULT_HOST:
        raise ValueError("KOMPAS Renderer must bind to 127.0.0.1")
    if isinstance(port, bool) or not isinstance(port, int) or not 0 <= port <= 65535:
        raise ValueError("KOMPAS Renderer port is invalid")
    try:
        return RendererHTTPServer((host, port), RendererRequestHandler, state)
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            raise RendererUnavailable(
                f"KOMPAS Renderer port {port} is already in use; close the other interactive session"
            ) from exc
        raise


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local TMM KOMPAS Renderer.")
    parser.add_argument("--config", default=os.environ.get("TMM_KOMPAS_RENDERER_CONFIG"))
    parser.add_argument(
        "--dev",
        action="store_true",
        help="use development environment configuration (never overrides --config)",
    )
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--origin", action="append", default=None)
    parser.add_argument("--key-id", default=None)
    parser.add_argument("--data-dir", default=None)
    return parser.parse_args(argv)


def _config_from_args(args: argparse.Namespace) -> RendererConfig:
    config = load_renderer_config(args.config, development=args.dev)
    if args.config or os.environ.get("TMM_KOMPAS_RENDERER_CONFIG"):
        if args.host is not None or args.port is not None:
            raise RendererUnavailable("installed renderer configuration fixes the localhost endpoint")
        # Installed release config is authoritative.  Development env/CLI
        # values never alter its trust material or endpoint.
        return config
    if any(value is not None for value in (args.origin, args.key_id, args.data_dir)):
        origins = config.origins if args.origin is None else tuple(args.origin)
        config = replace(
            config,
            origins=origins,
            key_id=config.key_id if args.key_id is None else args.key_id,
            data_dir=config.data_dir if args.data_dir is None else args.data_dir,
        )
    if args.host is not None:
        config = replace(config, host=args.host)
    if args.port is not None:
        config = replace(config, port=args.port)
    return config
def _write_startup_diagnostic(message: str, data_dir: Path | None) -> None:
    directory = data_dir or default_renderer_data_dir()
    safe_message = message.replace("\r", " ").replace("\n", " ")[:4096]
    try:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "renderer-startup.log").write_text(
            f"{datetime.now(timezone.utc).isoformat()} {safe_message}\n",
            encoding="utf-8",
        )
    except OSError:
        pass




def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    lock: RendererInstanceLock | None = None
    server: RendererHTTPServer | None = None
    config: RendererConfig | None = None
    try:
        config = _config_from_args(args)
        lock = RendererInstanceLock(config.data_directory)
        lock.acquire()
        state = RendererState.from_config(config)
        state.prepare_storage()
        state.cleanup_backing_files()
        server = create_server(
            state,
            host=config.host,
            port=config.port,
        )
    except (RendererUnavailable, ValueError, OSError) as exc:
        if lock is not None:
            lock.release()
        _write_startup_diagnostic(str(exc), config.data_directory if config is not None else None)
        print(str(exc), file=sys.stderr)
        return 2
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
        if lock is not None:
            lock.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
