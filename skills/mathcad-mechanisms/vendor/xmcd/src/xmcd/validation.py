"""Structural validation and inspection of Mathcad-saved calculation results."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path

from lxml import etree as ET

from .document import NS, WS


class ValidationError(ValueError):
    """The document violates an XML or XMCD structural constraint."""


def parse_xml(source: str | Path | bytes) -> ET._Element:
    parser = ET.XMLParser(resolve_entities=False, no_network=True)
    if isinstance(source, bytes):
        tree = ET.fromstring(source, parser).getroottree()
    else:
        tree = ET.parse(str(source), parser)
    if tree.docinfo.doctype:
        raise ValidationError("DTD declarations are not supported in XMCD")
    return tree.getroot()


class _SchemaResolver(ET.Resolver):
    def __init__(self, directory: Path):
        self.files = {p.name.lower(): p for p in directory.iterdir() if p.is_file()}

    def resolve(self, url, public_id, context):
        path = self.files.get(Path(url).name.lower())
        if path is not None:
            return self.resolve_filename(str(path.resolve()), context)
        raise ValidationError(f"Schema dependency is not available locally: {url}")


def validate(source: str | Path | bytes, *, schema: str | Path | None = None) -> None:
    """Raise on structural errors. Supply PTC's worksheet30.xsd for full XSD validation.

    This does not evaluate formulas or verify the contents of opaque plot blocks.
    Schema imports resolve locally, including Windows filename case differences.
    """
    try:
        root = parse_xml(source)
    except ET.XMLSyntaxError as exc:
        raise ValidationError(str(exc)) from exc
    if root.tag != f"{{{WS}}}worksheet" or root.get("version") != "3.0.3":
        raise ValidationError("Expected classic Mathcad worksheet30 version 3.0.3")
    for name in ("settings", "regions"):
        if len(root.findall(f"{{{WS}}}{name}")) != 1:
            raise ValidationError(f"Expected exactly one {name} element")
    for xpath, attribute in (
        (".//ws:region", "region-id"),
        ("ws:binaryContent/ws:item", "item-id"),
    ):
        seen = set()
        for node in root.findall(xpath, NS):
            identifier = node.get(attribute)
            if identifier is None or not identifier.isdecimal() or identifier in seen:
                raise ValidationError(f"Missing, invalid or duplicate {attribute}: {identifier}")
            seen.add(identifier)
    items = root.findall("ws:binaryContent/ws:item", NS)
    identifiers = {item.get("item-id") for item in items}
    for node in root.iter():
        ref = node.get("item-idref")
        if ref is not None and ref not in identifiers:
            raise ValidationError(f"Dangling binary item reference: {ref}")
    for item in items:
        try:
            base64.b64decode("".join((item.text or "").split()), validate=True)
        except ValueError as exc:
            raise ValidationError(f"Invalid base64 item {item.get('item-id')}") from exc
    if schema is not None:
        path = Path(schema)
        parser = ET.XMLParser(resolve_entities=False, no_network=True)
        parser.resolvers.add(_SchemaResolver(path.parent))
        validator = ET.XMLSchema(ET.parse(str(path), parser))
        if not validator.validate(root):
            raise ValidationError(str(validator.error_log))


@dataclass(frozen=True)
class CalculationError:
    region_id: str
    tag: str
    message: str


def calculation_errors(source: str | Path | bytes) -> list[CalculationError]:
    """Read errors persisted by Mathcad. An unsaved/unrecalculated file proves nothing."""
    root = parse_xml(source)
    errors = []
    for region in root.findall(".//ws:region", NS):
        for node in region:
            error = node.get("error")
            if error:
                errors.append(
                    CalculationError(region.get("region-id", ""), region.get("tag", ""), error)
                )
    return errors
