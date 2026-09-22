"""Load and validate the shared ``kompas-text-block-v1`` fixture corpus.

The corpus is contract data, not a renderer.  Keeping this loader COM-free lets
future Markdown/parser/layout tests consume exactly the same source fixtures as
the Node metrics package without depending on Node at runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, Tuple


CORPUS_FORMAT = "tmm-text-block-corpus"
CORPUS_VERSION = 1
TEXT_BLOCK_CONTRACT = "kompas-text-block-v1"
SNAPSHOT_STATE = "implemented-conformance-v1"
SUPPORTED_FONT_SIZES = (1.8, 2.5, 3.5, 5.0, 7.0, 10.0, 14.0, 20.0, 28.0, 40.0)
SNAPSHOT_DOMAINS = (
    "semanticIr",
    "visualLines",
    "formulaSplits",
    "errors",
    "metricEnvelope",
)


class TextBlockCorpusError(ValueError):
    """Raised when the committed conformance corpus is malformed."""


@dataclass(frozen=True)
class TextBlockConformanceCase:
    """Fixture outcome available before parser/layout conformance exists."""

    fixture_id: str
    markdown: str
    entity: Dict[str, Any]
    outcome: str
    error_codes: Tuple[str, ...]


def corpus_path() -> Path:
    """Return the package-owned synchronized copy of the canonical corpus."""

    return Path(__file__).with_name("fixtures") / "text-block-corpus.v1.json"


def corpus_bytes(path: Optional[Path] = None) -> bytes:
    """Return canonical UTF-8 corpus bytes with platform-neutral newlines."""

    return (path or corpus_path()).read_bytes().replace(b"\r\n", b"\n")


def _fail(message: str) -> None:
    raise TextBlockCorpusError("Invalid text-block corpus: " + message)


def _is_finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _validate_fixture(fixture: Any, seen_ids: set) -> None:
    if not isinstance(fixture, dict):
        _fail("fixture must be an object")
    fixture_id = fixture.get("id")
    if not isinstance(fixture_id, str) or not fixture_id:
        _fail("fixture id must be a non-empty string")
    if fixture_id in seen_ids:
        _fail("fixture ids must be unique: %r" % fixture_id)
    seen_ids.add(fixture_id)

    kind = fixture.get("kind")
    if kind not in {"reference", "supported", "invalid"}:
        _fail("fixture %r has invalid kind" % fixture_id)

    source = fixture.get("source")
    markdown = source.get("markdown") if isinstance(source, dict) else None
    if not isinstance(markdown, str):
        _fail("fixture %r source.markdown must be a string" % fixture_id)
    if "\r" in markdown:
        _fail("fixture %r source.markdown must use LF only" % fixture_id)

    digest = fixture.get("digests", {}).get("sourceSha256")
    expected_digest = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    if digest != expected_digest:
        _fail("fixture %r sourceSha256 does not match UTF-8 Markdown" % fixture_id)

    entity = fixture.get("entity")
    if not isinstance(entity, dict) or entity.get("type") != "textBlock":
        _fail("fixture %r entity must be a textBlock" % fixture_id)
    if entity.get("id") != fixture_id:
        _fail("fixture %r entity.id must equal fixture id" % fixture_id)
    position = entity.get("position")
    if (not isinstance(position, list) or len(position) != 2 or
            not all(_is_finite_number(value) for value in position)):
        _fail("fixture %r position must contain two finite numbers" % fixture_id)
    if not _is_finite_number(entity.get("fontSize")):
        _fail("fixture %r fontSize must be finite" % fixture_id)
    if not _is_finite_number(entity.get("width")) or entity["width"] <= 0:
        _fail("fixture %r width must be a positive finite number" % fixture_id)

    expected = fixture.get("expected")
    if not isinstance(expected, dict) or expected.get("outcome") not in {"success", "error"}:
        _fail("fixture %r expected.outcome must be success or error" % fixture_id)
    if kind == "invalid" and expected["outcome"] != "error":
        _fail("invalid fixture %r must expect an error" % fixture_id)
    if kind != "invalid" and expected["outcome"] != "success":
        _fail("non-invalid fixture %r must expect success" % fixture_id)
    errors = expected.get("errors", [])
    if expected["outcome"] == "error" and not errors:
        _fail("error fixture %r must declare at least one error" % fixture_id)
    if not isinstance(errors, list) or any(not isinstance(error, dict) or not error.get("code") for error in errors):
        _fail("fixture %r errors must contain coded objects" % fixture_id)
    for error in errors:
        source_span = error.get("sourceSpan")
        if not isinstance(source_span, dict) or not all(
                isinstance(source_span.get(key), int) and source_span[key] >= 0
                for key in ("start", "end")) or source_span["end"] < source_span["start"]:
            _fail("fixture %r errors must contain a non-negative sourceSpan" % fixture_id)

    reference_image = source.get("referenceImage") if isinstance(source, dict) else None
    if kind == "reference":
        if not isinstance(reference_image, dict):
            _fail("reference fixture %r must declare image provenance" % fixture_id)
        if reference_image.get("owner") != "tmm-scene-kompas":
            _fail("reference fixture %r has unexpected image owner" % fixture_id)
        image_digest = reference_image.get("sha256")
        if not isinstance(image_digest, str) or len(image_digest) != 64:
            _fail("reference fixture %r has invalid image SHA-256" % fixture_id)


def validate_text_block_corpus(corpus: Any) -> Dict[str, Any]:
    """Validate the dependency-free structural contract and return ``corpus``.

    This deliberately does not parse Markdown or TeX: those implementations are
    later conformance subjects, not authorities over the fixture source.
    """

    if not isinstance(corpus, dict):
        _fail("root must be an object")
    if corpus.get("format") != CORPUS_FORMAT:
        _fail("unexpected format")
    if corpus.get("version") != CORPUS_VERSION:
        _fail("unexpected version")
    if corpus.get("contract") != TEXT_BLOCK_CONTRACT:
        _fail("unexpected contract")
    if corpus.get("snapshotState") != SNAPSHOT_STATE:
        _fail("unexpected snapshot state")
    profile = corpus.get("markdownProfile")
    expected_profile = {
        "breaks": True,
        "html": False,
        "images": False,
        "linkify": False,
        "typographer": False,
        "inlineMath": "$...$",
        "displayMath": "$$...$$",
    }
    if profile != expected_profile:
        _fail("markdown profile differs from the v1 contract")
    if tuple(corpus.get("supportedFontSizes", ())) != SUPPORTED_FONT_SIZES:
        _fail("supported font-size ladder differs from the v1 contract")
    fixtures = corpus.get("fixtures")
    if not isinstance(fixtures, list) or not fixtures:
        _fail("fixtures must be a non-empty array")
    seen_ids = set()
    for fixture in fixtures:
        _validate_fixture(fixture, seen_ids)
    return corpus


def load_text_block_corpus(path: Optional[Path] = None) -> Dict[str, Any]:
    """Read and validate a corpus; default to the synchronized package copy."""

    source_path = path or corpus_path()
    try:
        corpus = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TextBlockCorpusError("Unable to read text-block corpus: %s" % exc) from exc
    return validate_text_block_corpus(corpus)


def iter_conformance_cases(path: Optional[Path] = None) -> Iterator[TextBlockConformanceCase]:
    """Yield stable expected outcomes for future parser/layout conformance tests."""

    for fixture in load_text_block_corpus(path)["fixtures"]:
        errors = fixture["expected"].get("errors", [])
        yield TextBlockConformanceCase(
            fixture_id=fixture["id"],
            markdown=fixture["source"]["markdown"],
            entity=dict(fixture["entity"]),
            outcome=fixture["expected"]["outcome"],
            error_codes=tuple(error["code"] for error in errors),
        )
