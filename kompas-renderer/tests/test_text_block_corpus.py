"""Tests for the synchronized textBlock conformance corpus foundation."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import unittest

from tmm_scene_kompas.text_block_corpus import (
    CORPUS_FORMAT,
    CORPUS_VERSION,
    SNAPSHOT_DOMAINS,
    SNAPSHOT_STATE,
    TEXT_BLOCK_CONTRACT,
    TextBlockCorpusError,
    corpus_bytes,
    iter_conformance_cases,
    load_text_block_corpus,
    validate_text_block_corpus,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
PYTHON_ENVELOPE = REPOSITORY_ROOT / "src" / "tmm_scene_kompas" / "fixtures" / "python-layout-envelope.v1.json"
EXPECTED_CORPUS_SHA256 = "422169f7d44bda3eea9da58ed0d5cb12827c431ec65b22dfee23295a0554bd15"


class TestTextBlockCorpus(unittest.TestCase):

    def test_package_copy_is_valid_contract_foundation(self):
        corpus = load_text_block_corpus()
        self.assertEqual(corpus["format"], CORPUS_FORMAT)
        self.assertEqual(corpus["version"], CORPUS_VERSION)
        self.assertEqual(corpus["contract"], TEXT_BLOCK_CONTRACT)
        self.assertEqual(corpus["snapshotState"], SNAPSHOT_STATE)
        self.assertEqual(SNAPSHOT_DOMAINS, (
            "semanticIr", "visualLines", "formulaSplits", "errors", "metricEnvelope",
        ))
        self.assertGreaterEqual(len(corpus["fixtures"]), 14)
        self.assertEqual(
            {fixture["id"] for fixture in corpus["fixtures"] if fixture["kind"] == "reference"},
            {
                "reference-problem-statement",
                "reference-planar-motion",
                "reference-force-equilibrium",
            },
        )

    def test_package_corpus_digest_is_stable(self):
        self.assertEqual(
            hashlib.sha256(corpus_bytes()).hexdigest(),
            EXPECTED_CORPUS_SHA256,
        )

    def test_python_layout_envelope_identifies_this_corpus(self):
        self.assertTrue(PYTHON_ENVELOPE.is_file())
        envelope = json.loads(PYTHON_ENVELOPE.read_text(encoding="utf-8"))
        self.assertEqual(envelope["format"], "tmm-python-layout-envelope")
        self.assertEqual(envelope["version"], 1)
        self.assertEqual(envelope["contract"], TEXT_BLOCK_CONTRACT)
        self.assertEqual(envelope["corpusSha256"], hashlib.sha256(corpus_bytes()).hexdigest())
        self.assertEqual(len(envelope["cases"]), 7)

    def test_reference_image_provenance_matches_owned_pngs(self):
        corpus = load_text_block_corpus()
        for fixture in corpus["fixtures"]:
            image = fixture["source"].get("referenceImage")
            if image is None:
                continue
            image_path = REPOSITORY_ROOT / image["path"]
            self.assertTrue(image_path.is_file(), fixture["id"])
            self.assertEqual(
                hashlib.sha256(image_path.read_bytes()).hexdigest(),
                image["sha256"],
                fixture["id"],
            )

    def test_conformance_scaffold_exposes_stable_outcomes(self):
        cases = {case.fixture_id: case for case in iter_conformance_cases()}
        self.assertEqual(cases["supported-display-safe-breaks"].outcome, "success")
        self.assertEqual(cases["invalid-tex-command"].error_codes, ("invalid-tex",))
        self.assertEqual(
            cases["invalid-font-size"].error_codes,
            ("unsupported-font-size",),
        )

    def test_validation_rejects_modified_source_digest(self):
        corpus = copy.deepcopy(load_text_block_corpus())
        corpus["fixtures"][0]["source"]["markdown"] += "!"
        with self.assertRaises(TextBlockCorpusError):
            validate_text_block_corpus(corpus)


if __name__ == "__main__":
    unittest.main()
