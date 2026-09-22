"""Parity tests for the synchronized strict table-cell corpus."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest

from tmm_scene_kompas.table import (
    TableCellCompileError,
    compile_table_cell_inline_plan,
)


ROOT = Path(__file__).resolve().parents[1]
CORPUS_PATH = ROOT / "src" / "tmm_scene_kompas" / "fixtures" / "table-cell-corpus.v1.json"
EXPECTED_SHA256 = "eee604813eb02c132b59b1d9ecb4b94177e2239974d91b060de819bd5b2ca617"


class TestTableCellCorpus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = CORPUS_PATH.read_bytes()
        cls.corpus = json.loads(cls.raw)

    def test_fixture_digest_and_case_sets_are_stable(self):
        self.assertEqual(hashlib.sha256(self.raw).hexdigest(), EXPECTED_SHA256)
        self.assertEqual(
            [case["id"] for case in self.corpus["accepted"]],
            ["empty", "cyrillic", "escaped-pipe", "mixed-inline-math", "several-math", "inline-plain-prefix"],
        )
        self.assertEqual(len(self.corpus["rejected"]), 10)

    def test_accepted_cases_have_stable_run_shape(self):
        for case in self.corpus["accepted"]:
            plan = compile_table_cell_inline_plan(
                case["source"], 5.0, True, entity_id=f"cell-{case['id']}"
            )
            actual = [
                {
                    "kind": run.kind,
                    "value": run.value,
                    "start": run.source_span.start.offset,
                    "end": run.source_span.end.offset,
                }
                for run in plan.runs
            ]
            self.assertEqual(actual, case["runs"], case["id"])

    def test_rejected_cases_have_stable_diagnostics(self):
        for case in self.corpus["rejected"]:
            with self.assertRaises(TableCellCompileError) as context:
                compile_table_cell_inline_plan(
                    case["source"], 5.0, True, entity_id=f"cell-{case['id']}"
                )
            error = context.exception
            self.assertEqual(error.code, case["code"], case["id"])
            self.assertEqual(error.token_kind, case["tokenKind"], case["id"])
            self.assertEqual(error.source_span.start.offset, case["start"], case["id"])
            self.assertEqual(error.entity_id, f"cell-{case['id']}")
        with self.assertRaises(TableCellCompileError) as context:
            compile_table_cell_inline_plan("$\\notacommand{x}$", 5.0, True)
        self.assertEqual(context.exception.details["code"], "invalid-tex")


if __name__ == "__main__":
    unittest.main()
