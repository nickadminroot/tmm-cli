"""COM-free conformance tests for textBlock parsing, layout, and lowering."""
from __future__ import annotations

import json
from pathlib import Path
import unittest
from unittest.mock import MagicMock

from tmm_scene_kompas.api5_text import add_api5_text_block_plan
from tmm_scene_kompas.kompas_text import (
    FontRole,
    TextItemPlan,
    compile_latex_api5_exact,
)
from tmm_scene_kompas.render import offset_entity, validate_payload_v2
from tmm_scene_kompas.text_block_corpus import iter_conformance_cases, load_text_block_corpus
from tmm_scene_kompas.text_block_layout import compile_text_block_plan, next_standard_height, split_display_math
from tmm_scene_kompas.text_block_parser import TextBlockCompileError
from tmm_scene_kompas.text_block_snapshot import conformance_snapshot


def entity(text: str, **changes):
    value = {"type": "textBlock", "id": "block", "text": text,
             "position": [10, 80], "fontSize": 5, "width": 50}
    value.update(changes)
    return value


class TestCorpusConformance(unittest.TestCase):
    def test_all_current_corpus_outcomes_are_enforced(self):
        for case in iter_conformance_cases():
            candidate = dict(case.entity)
            candidate["text"] = case.markdown
            with self.subTest(case=case.fixture_id):
                if case.outcome == "success":
                    self.assertGreaterEqual(len(compile_text_block_plan(candidate).plan.lines), 1)
                else:
                    with self.assertRaises(TextBlockCompileError) as caught:
                        compile_text_block_plan(candidate)
                    self.assertEqual(caught.exception.code, case.error_codes[0])
                    self.assertEqual(caught.exception.entity_id, case.fixture_id)
                    expected_error = next(
                        fixture["expected"]["errors"][0]
                        for fixture in load_text_block_corpus()["fixtures"]
                        if fixture["id"] == case.fixture_id
                    )
                    self.assertEqual(caught.exception.token_kind, expected_error["tokenKind"])
                    self.assertEqual(caught.exception.source_span.start.offset, expected_error["sourceSpan"]["start"])
                    self.assertEqual(caught.exception.source_span.end.offset, expected_error["sourceSpan"]["end"])

    def test_committed_python_layout_snapshot_is_byte_stable(self):
        snapshot_path = (Path(__file__).resolve().parents[1] / "src" /
                         "tmm_scene_kompas" / "fixtures" /
                         "python-layout-envelope.v1.json")
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        fixtures = {fixture["id"]: fixture for fixture in load_text_block_corpus()["fixtures"]}
        for expected in snapshot["cases"]:
            fixture = fixtures[expected["id"]]
            entity_value = {**fixture["entity"], "text": fixture["source"]["markdown"]}
            first = compile_text_block_plan(entity_value)
            second = compile_text_block_plan(entity_value)
            with self.subTest(case=expected["id"]):
                self.assertEqual((first.width, first.height, len(first.plan.lines), first.overflow), (
                    expected["width"], expected["height"], expected["lineCount"], expected["overflow"],
                ))
                self.assertEqual(repr(first.plan), repr(second.plan))

    def test_canonical_semantic_and_layout_snapshots_are_current(self):
        snapshot_path = (Path(__file__).resolve().parents[1] / "src" /
                         "tmm_scene_kompas" / "fixtures" /
                         "python-conformance-snapshots.v1.json")
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        fixtures = {fixture["id"]: fixture for fixture in load_text_block_corpus()["fixtures"]}
        self.assertEqual(snapshot["contract"], "kompas-text-block-v1")
        self.assertEqual({case["id"] for case in snapshot["cases"]}, set(fixtures))
        for case in snapshot["cases"]:
            fixture = fixtures[case["id"]]
            with self.subTest(case=case["id"]):
                actual = conformance_snapshot({
                    **fixture["entity"], "text": fixture["source"]["markdown"],
                })
                self.assertEqual(actual, case["snapshot"])

    def test_required_entity_fields_and_standard_height_are_strict(self):
        for field in ("id", "text", "position", "fontSize", "width"):
            bad = entity("x")
            del bad[field]
            with self.subTest(field=field), self.assertRaises(TextBlockCompileError):
                compile_text_block_plan(bad)
        with self.assertRaisesRegex(TextBlockCompileError, "unsupported-font-size"):
            compile_text_block_plan(entity("x", fontSize=4))


class TestLayout(unittest.TestCase):
    def test_headings_are_exactly_one_height_step_above_base(self):
        layout = compile_text_block_plan(entity("# Heading\n\nparagraph"))
        heading = layout.plan.lines[0]
        self.assertEqual(heading.height, next_standard_height(5.0))
        self.assertTrue(all(item.height == 7.0 for item in heading.items))
        self.assertEqual(layout.plan.lines[1].height, 5.0)

    def test_styles_code_and_visible_break_are_preserved(self):
        layout = compile_text_block_plan(entity("**bold** *em* `x_$y$`\nnext", italic=True))
        flat = [item for line in layout.plan.lines for item in line.items]
        self.assertTrue(any(item.bold for item in flat))
        self.assertTrue(any(item.italic for item in flat))
        self.assertTrue(any(item.content == "x_$y$" for item in flat))
        self.assertEqual(len(layout.plan.lines), 2)
        self.assertTrue(layout.plan.lines[0].break_after)

    def test_formula_text_and_scripts_inherit_entity_italic_style(self):
        layout = compile_text_block_plan(
            entity(r"$$V_H=V_E+V_{NE}+\text{м/с}$$", italic=True)
        )
        items = [item for line in layout.plan.lines for item in line.items if item.content]
        self.assertTrue(items)
        self.assertTrue(all(item.italic for item in items))

    def test_operatorname_remains_explicitly_upright(self):
        plan = compile_latex_api5_exact(r"\operatorname{sin}")
        items = [item for line in plan.lines for item in line.items if item.content]
        self.assertTrue(items)
        self.assertTrue(all(item.italic_override is False for item in items))

    def test_closing_punctuation_stays_with_a_styled_word_when_wrapped(self):
        layout = compile_text_block_plan(entity("**word**, next", width=0.1))
        rendered = ["".join(item.content for item in line.items) for line in layout.plan.lines]
        self.assertEqual(rendered[0].rstrip(), "word,")
        self.assertFalse(any(line.strip() == "," for line in rendered))

    def test_opening_punctuation_stays_with_the_following_styled_word_when_wrapped(self):
        layout = compile_text_block_plan(entity("«**word** next", width=0.1))
        rendered = ["".join(item.content for item in line.items) for line in layout.plan.lines]
        self.assertEqual(rendered[0], "«word")
        self.assertFalse(any(line.strip() == "«" for line in rendered))

    def test_underset_annotation_keeps_its_smaller_height_through_styling(self):
        layout = compile_text_block_plan(entity(
            r"$$\underset{\perp AB}{\underline{\overline{a}_{BA}^{\tau}}}$$"
        ))
        items = layout.plan.lines[0].items
        annotation_items = [item for item in items if item.kind in {"updn_upper", "updn_lower"}]
        self.assertTrue(annotation_items)
        self.assertTrue(all(item.height == 3.5 for item in annotation_items))

    def test_inline_math_is_not_split_and_display_breaks_are_safe(self):
        layout = compile_text_block_plan(entity("word $F_{21}^{\\tau}$ word", width=10))
        self.assertTrue(layout.overflow)
        pieces, _minimum, overflow = split_display_math("a=b+c-d", 12, 5)
        self.assertGreater(len(pieces), 1)
        self.assertFalse(overflow)
        self.assertEqual(pieces, ["a=", "=b+", "+c-", "-d"])
        pieces, _minimum, overflow = split_display_math("\\frac{verylong}{denominator}", 5, 5)
        self.assertEqual(len(pieces), 1)
        self.assertTrue(overflow)
        pieces, _minimum, overflow = split_display_math("\\left(a+b\\right)=c", 8, 5)
        self.assertEqual(pieces, ["\\left(a+b\\right)=", "=c"])
        self.assertTrue(overflow)

    def test_safe_split_keeps_fitting_neighbours_and_reports_only_oversized_atoms(self):
        layout = compile_text_block_plan(entity("$$a=verylong+b$$", width=10))
        self.assertTrue(layout.overflow)
        self.assertEqual(
            ["".join(item.content for item in line.items) for line in layout.plan.lines],
            ["a=", "=verylong+", "+b"],
        )
        warning = next(warning for warning in layout.warnings if warning.code == "formula-overflow")
        self.assertEqual([segment.tex for segment in warning.overflow_segments], ["=verylong+"])
        self.assertGreater(warning.overflow_segments[0].width, 10)

    def test_variable_backtick_code_is_literal_and_unmatched_tex_brace_is_precise(self):
        layout = compile_text_block_plan(entity("``code $x$ and `ticks` `` then $y$"))
        self.assertTrue(any(item.content == "code $x$ and `ticks` "
                            for line in layout.plan.lines for item in line.items))
        with self.assertRaises(TextBlockCompileError) as caught:
            compile_text_block_plan(entity("prefix $a}$ suffix"))
        self.assertEqual(caught.exception.code, "invalid-tex")
        # The error points at the unmatched TeX brace, not the opening '$'.
        self.assertEqual(caught.exception.source_span.start.offset, 9)
        self.assertEqual(caught.exception.source_span.end.offset, 10)

    def test_multiline_display_math_is_a_single_supported_display_block(self):
        layout = compile_text_block_plan(entity("before\n\n$$\na=b+c\n$$\n\nafter", width=30))
        rendered = ["".join(item.content for item in line.items) for line in layout.plan.lines]
        self.assertIn("a=b+c", rendered)

    def test_variant_7_acceleration_widehat_display_math_is_editable(self):
        source = "$$\n" + r"\triangle \widehat{a'd'b'} \sim \triangle \widehat{ABH}" + "\n$$"
        layout = compile_text_block_plan(entity(source))
        rendered = [
            "".join(item.content for item in line.items)
            for line in layout.plan.lines
        ]
        self.assertTrue(any("a'd'b'" in line and "ABH" in line for line in rendered))

    def test_internal_display_math_control_whitespace_is_lowered_to_spaces(self):
        plan = compile_latex_api5_exact("a=b\r\n+\tc")
        rendered = "".join(item.content for line in plan.lines for item in line.items)
        self.assertEqual(rendered, "a=b + c")
        self.assertNotRegex(rendered, r"[\r\n\t]")

        layout = compile_text_block_plan(entity("before\n\n$$\na=b\n+\tc\n$$\n\nafter"))
        rendered_lines = ["".join(item.content for item in line.items) for line in layout.plan.lines]
        self.assertIn("a=b + c", rendered_lines)
        self.assertTrue(layout.plan.lines[0].break_after)

    def test_layout_is_deterministic_and_shrinking_width_never_shrinks_height(self):
        source = "one two three four five six"
        wide = compile_text_block_plan(entity(source, width=50))
        narrow_one = compile_text_block_plan(entity(source, width=20))
        narrow_two = compile_text_block_plan(entity(source, width=20))
        self.assertGreaterEqual(narrow_one.height, wide.height)
        self.assertEqual(repr(narrow_one.plan), repr(narrow_two.plan))

    def test_offset_moves_only_position(self):
        original = entity("text", width=61, fontSize=7)
        moved = offset_entity(original, (3, -4))
        self.assertEqual(moved["position"], [13.0, 76.0])
        self.assertEqual(moved["width"], 61)
        self.assertEqual(moved["fontSize"], 7)

    def test_payload_validation_compiles_before_com(self):
        invalid = {"format": "tmm-scene", "version": 2,
                   "entities": [entity("$\\notacommand{}$")]}
        with self.assertRaises(TextBlockCompileError):
            validate_payload_v2(invalid)

    def test_mixed_geometry_fixture_validates(self):
        path = Path(__file__).with_name("fixtures") / "text-block-mixed.scene.json"
        validate_payload_v2(json.loads(path.read_text(encoding="utf-8")))


class _Array:
    def __init__(self): self.items = []
    def ksClearArray(self): self.items.clear()
    def ksAddArrayItem(self, _index, item): self.items.append(item); return True


class _Font:
    def __init__(self): self.height = 0; self.fontName = ""; self.ksu = 0; self.color = 0; self.bitVector = 0


class _Item:
    def Init(self): pass
    def __init__(self): self._font = _Font()
    def GetItemFont(self): return self._font
    def SetItemFont(self, font): self._font = font


class _Line:
    def __init__(self): self.array = _Array()
    def GetTextItemArr(self): return self.array
    def SetTextItemArr(self, array): self.array = array


class _Text:
    def Init(self): pass
    def __init__(self): self.array = _Array(); self.paragraph = None
    def GetTextLineArr(self): return self.array
    def SetTextLineArr(self, array): self.array = array
    def SetParagraphParam(self, paragraph): self.paragraph = paragraph


class _Paragraph:
    def Init(self): pass


class _Const:
    ko_TextItemParam = 1
    ko_TextLineParam = 2
    ko_ParagraphParam = 3
    ko_TextParam = 4


class _Point:
    def __init__(self, x, y): self.x, self.y = x, y


class _Rect:
    def __init__(self): self.bottom = _Point(0, 0); self.top = _Point(0, 0)
    def GetpBot(self): return self.bottom
    def GetpTop(self): return self.top


class _Kompas:
    def __init__(self): self.last_text = None
    def GetParamStruct(self, kind):
        if kind == 1: return _Item()
        if kind == 2: return _Line()
        if kind == 3: return _Paragraph()
        if kind == 4:
            self.last_text = _Text(); return self.last_text
        if kind == 5: return _Rect()
        raise AssertionError(kind)


class TestApi5TextBlockLowering(unittest.TestCase):
    def test_one_ks_text_ex_and_one_param_for_whole_plan(self):
        class ConstWithRect(_Const): ko_RectParam = 5

        class Doc:
            def __init__(self): self.bounds = [2.0, 60.0, 22.0, 70.0]; self.calls = 0
            def ksTextEx(self, _param, _flag): self.calls += 1; return 77
            def ksGetObjGabaritRect(self, _reference, rect):
                rect.bottom = _Point(self.bounds[0], self.bounds[1])
                rect.top = _Point(self.bounds[2], self.bounds[3])
                return 1
            def ksMoveObj(self, _reference, dx, dy):
                self.bounds = [self.bounds[0] + dx, self.bounds[1] + dy,
                               self.bounds[2] + dx, self.bounds[3] + dy]
                return 1

        plan = compile_text_block_plan(entity("one\ntwo")).plan
        kompas = _Kompas()
        doc = Doc()
        reference = add_api5_text_block_plan(doc, kompas, ConstWithRect(), plan, 10, 80, 50, "block")
        self.assertEqual(reference, 77)
        self.assertEqual(doc.calls, 1)
        self.assertIsNotNone(kompas.last_text)
        self.assertEqual(len(kompas.last_text.array.items), len(plan.lines))
        # First line gains the proven @/ separator but never creates a second object.
        self.assertEqual(kompas.last_text.array.items[0].array.items[-1].s, "@/")

    def test_retained_reference_is_moved_and_remeasured_for_top_left(self):
        class ConstWithRect(_Const): ko_RectParam = 5
        class Doc:
            def __init__(self): self.bounds = [2.0, 60.0, 22.0, 70.0]; self.moves = []
            def ksTextEx(self, _param, _flag): return 9
            def ksGetObjGabaritRect(self, reference, rect):
                self.assert_reference = reference
                rect.bottom = _Point(self.bounds[0], self.bounds[1])
                rect.top = _Point(self.bounds[2], self.bounds[3])
                return 1
            def ksMoveObj(self, reference, dx, dy):
                self.moves.append((reference, dx, dy))
                self.bounds = [self.bounds[0] + dx, self.bounds[1] + dy,
                               self.bounds[2] + dx, self.bounds[3] + dy]
                return 1
        doc = Doc()
        plan = compile_text_block_plan(entity("one")).plan
        self.assertEqual(add_api5_text_block_plan(doc, _Kompas(), ConstWithRect(), plan, 10, 80, 50, "block"), 9)
        self.assertEqual(doc.moves, [(9, 8.0, 10.0)])
        self.assertEqual(doc.bounds, [10.0, 70.0, 30.0, 80.0])

    def test_missing_or_invalid_gabarit_is_not_treated_as_success(self):
        class ConstWithRect(_Const):
            ko_RectParam = 5

        class NoGabarit:
            def __init__(self): self.calls = 0
            def ksTextEx(self, _param, _flag): self.calls += 1; return 9
            def ksMoveObj(self, _reference, _dx, _dy): return 1

        plan = compile_text_block_plan(entity("one")).plan
        doc = NoGabarit()
        with self.assertRaisesRegex(RuntimeError, "Unable to measure API5 gabarit"):
            add_api5_text_block_plan(doc, _Kompas(), ConstWithRect(), plan, 10, 80, 50, "block")
        self.assertEqual(doc.calls, 1)

        class InvalidGabarit(NoGabarit):
            def ksGetObjGabaritRect(self, _reference, rect):
                rect.bottom = _Point(float("nan"), 60.0)
                rect.top = _Point(22.0, 70.0)
                return 1

        with self.assertRaisesRegex(RuntimeError, "Unable to measure API5 gabarit"):
            add_api5_text_block_plan(InvalidGabarit(), _Kompas(), ConstWithRect(),
                                     plan, 10, 80, 50, "block")

    def test_move_failure_is_not_treated_as_success(self):
        class ConstWithRect(_Const):
            ko_RectParam = 5

        class Doc:
            def ksTextEx(self, _param, _flag):
                return 9

            def ksGetObjGabaritRect(self, _reference, rect):
                rect.bottom = _Point(2.0, 60.0)
                rect.top = _Point(22.0, 70.0)
                return 1

            def ksMoveObj(self, _reference, _dx, _dy):
                return 0

        plan = compile_text_block_plan(entity("one")).plan
        with self.assertRaisesRegex(RuntimeError, "ksMoveObj failed"):
            add_api5_text_block_plan(Doc(), _Kompas(), ConstWithRect(),
                                     plan, 10, 80, 50, "block")


if __name__ == "__main__":
    unittest.main()
