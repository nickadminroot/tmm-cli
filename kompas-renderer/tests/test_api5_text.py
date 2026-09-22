"""Unit tests for tmm_scene_kompas.api5_text.

These tests exercise only the COM-like parameter construction helpers
with fake objects.  They can run on any platform without pywin32 or
a KOMPAS install.
"""

import unittest
from unittest.mock import MagicMock

from tmm_scene_kompas.api5_text import (
    TEXT_ITEM_ARR,
    _new_item_param,
    _new_line_param,
    _new_text_param,
    add_api5_text_plan,
)
from tmm_scene_kompas.kompas_text import (
    FontRole,
    TextItemPlan,
    TextLinePlan,
    TextRenderPlan,
)


# ─── Fake COM objects ────────────────────────────────────────────────────────


class _FakeFont:
    """Mimics ko_TextItemFont."""

    def __init__(self):
        self.fontName = "GOST type A"
        self.height = 0.0
        self.ksu = 0
        self.color = 0
        self.iSNumb = 0
        self.bitVector = 0

    def __repr__(self):
        return (
            f"_FakeFont(fontName={self.fontName!r}, height={self.height}, "
            f"ksu={self.ksu}, color={self.color}, iSNumb={self.iSNumb}, "
            f"bitVector={self.bitVector})"
        )


class _FakeItemParam:
    """Mimics ko_TextItemParam."""

    def __init__(self):
        self.s = ""
        self.type = 0
        self.iSNumb = 0
        self._font = _FakeFont()
        self.inited = False

    def Init(self):
        self.inited = True

    def GetItemFont(self):
        return self._font

    def SetItemFont(self, font):
        self._font = font


class _FakeDynamicArray:
    """Mimics the pywin32 dynamic array returned by GetTextItemArr etc."""

    def __init__(self):
        self.items: list = []

    def ksClearArray(self):
        self.items.clear()

    def ksAddArrayItem(self, index, item):
        self.items.append(item)
        return True


class _FakeLineParam:
    """Mimics ko_TextLineParam."""

    def __init__(self):
        self._arr = _FakeDynamicArray()

    def GetTextItemArr(self):
        return self._arr

    def SetTextItemArr(self, arr):
        self._arr = arr


class _FakeParagraphParam:
    """Mimics ko_ParagraphParam."""

    def __init__(self):
        self.x = 0.0
        self.y = 0.0
        self.height = 0.0
        self.ang = 0.0
        self.width = 0.0
        self.hFormat = 0
        self.vFormat = 0
        self.inited = False

    def Init(self):
        self.inited = True


class _FakeTextParam:
    """Mimics ko_TextParam."""

    def __init__(self):
        self._para = None
        self._lines_arr = _FakeDynamicArray()
        self.inited = False

    def Init(self):
        self.inited = True

    def SetParagraphParam(self, para):
        self._para = para

    def GetTextLineArr(self):
        return self._lines_arr

    def SetTextLineArr(self, arr):
        self._lines_arr = arr


class _FakeKompas5:
    """Mimics KOMPAS.Application.5 / KompasObject for param creation."""

    def __init__(self, const):
        self._const = const
        self._last_item = None
        self._last_line = None
        self._last_text_param = None

    def GetParamStruct(self, struct_type):
        if struct_type == self._const.get("ko_TextItemParam", 1):
            self._last_item = _FakeItemParam()
            return self._last_item
        if struct_type == self._const.get("ko_TextLineParam", 2):
            self._last_line = _FakeLineParam()
            return self._last_line
        if struct_type == self._const.get("ko_ParagraphParam", 3):
            return _FakeParagraphParam()
        if struct_type == self._const.get("ko_TextParam", 4):
            self._last_text_param = _FakeTextParam()
            return self._last_text_param
        raise ValueError(f"Unknown struct type: {struct_type}")


class _FakeDoc2D:
    """Mimics API5 document 2D with ksTextEx."""

    def __init__(self):
        self.ksTextEx = MagicMock(return_value=42)


class _FakeConst:
    """Stand-in for KOMPAS constants module."""

    def __init__(self):
        self.ko_TextItemParam = 1
        self.ko_TextLineParam = 2
        self.ko_ParagraphParam = 3
        self.ko_TextParam = 4
        self.SUM_TYPE = 100


# ─── _new_item_param ─────────────────────────────────────────────────────────


class TestNewItemParam(unittest.TestCase):

    def setUp(self):
        self.const = _FakeConst()
        self.kompas5 = _FakeKompas5(self.const.__dict__)

    def test_plain_item(self):
        plan = TextItemPlan(item_type=0, kind="plain",
                            font=FontRole.GOST_TYPE_A, content="Hello")
        item = _new_item_param(self.kompas5, self.const, plan)
        self.assertTrue(item.inited)
        self.assertEqual(item.s, "Hello")
        self.assertEqual(item.type, 0)
        self.assertEqual(item.iSNumb, 0)
        self.assertEqual(item._font.fontName, "GOST type A")
        self.assertEqual(item._font.ksu, 1)
        self.assertEqual(item._font.color, 0)
        self.assertEqual(item._font.bitVector, 0)

    def test_font_height_set_when_positive(self):
        plan = TextItemPlan(item_type=0, kind="plain",
                            font=FontRole.GOST_TYPE_A, content="x")
        item = _new_item_param(self.kompas5, self.const, plan, height=8.0)
        self.assertAlmostEqual(item._font.height, 8.0)

    def test_markdown_style_flags_use_api5_font_bits(self):
        plan = TextItemPlan(item_type=0, kind="plain",
                            font=FontRole.GOST_TYPE_A, content="styled",
                            bold=True, italic=True, underline=True)
        item = _new_item_param(self.kompas5, self.const, plan)
        self.assertEqual(item._font.bitVector, 0x100 | 0x40 | 0x400)

    def test_style_flags_are_ored_with_structural_bits(self):
        plan = TextItemPlan(item_type=0, kind="script_upper",
                            font=FontRole.GOST_TYPE_A, content="x",
                            bold=True, italic=True)
        item = _new_item_param(self.kompas5, self.const, plan)
        self.assertEqual(item._font.bitVector, 0x8 | 0x100 | 0x40)

    def test_tracked_styles_emit_off_bits_for_the_next_run(self):
        state = [None, None, None]
        styled = TextItemPlan(item_type=0, kind="plain",
                              font=FontRole.GOST_TYPE_A, content="bold",
                              bold=True)
        item = _new_item_param(self.kompas5, self.const, styled,
                               style_state=state)
        self.assertEqual(item._font.bitVector, 0x100 | 0x80 | 0x800)
        plain = TextItemPlan(item_type=0, kind="plain",
                             font=FontRole.GOST_TYPE_A, content="plain")
        item = _new_item_param(self.kompas5, self.const, plain,
                               style_state=state)
        self.assertEqual(item._font.bitVector, 0x200)

    def test_repeated_styles_encode_each_run_explicitly(self):
        plan = TextItemPlan(item_type=0, kind="script_lower",
                            font=FontRole.GOST_TYPE_A, content="x",
                            italic=True)
        item = _new_item_param(self.kompas5, self.const, plan,
                               repeat_styles=True)
        self.assertEqual(item._font.bitVector, 0x9 | 0x40 | 0x200 | 0x800)

    def test_font_height_skipped_when_zero(self):
        plan = TextItemPlan(item_type=0, kind="plain",
                            font=FontRole.GOST_TYPE_A, content="")
        item = _new_item_param(self.kompas5, self.const, plan, height=0.0)
        self.assertAlmostEqual(item._font.height, 0.0)

    def test_symbol_font_name(self):
        plan = TextItemPlan(item_type=0, kind="plain",
                            font=FontRole.SYMBOL, content="t")
        item = _new_item_param(self.kompas5, self.const, plan)
        self.assertEqual(item._font.fontName, "Symbol type A")

    def test_script_base_resolves_sum_type(self):
        plan = TextItemPlan(item_type=0, kind="script_base",
                            font=FontRole.GOST_TYPE_A, content="F")
        item = _new_item_param(self.kompas5, self.const, plan)
        self.assertEqual(item.type, 0)
        self.assertEqual(item.iSNumb, 0)
        self.assertEqual(item._font.bitVector, 0x7)

    def test_script_upper_gets_bitvector_8(self):
        plan = TextItemPlan(item_type=0, kind="script_upper",
                            font=FontRole.SYMBOL, content="t")
        item = _new_item_param(self.kompas5, self.const, plan)
        self.assertEqual(item.type, 0)
        self.assertEqual(item._font.bitVector, 0x8)

    def test_script_lower_gets_bitvector_9(self):
        plan = TextItemPlan(item_type=0, kind="script_lower",
                            font=FontRole.GOST_TYPE_A, content="32")
        item = _new_item_param(self.kompas5, self.const, plan)
        self.assertEqual(item.type, 0)
        self.assertEqual(item._font.bitVector, 0x9)

    def test_script_end_gets_bitvector_10(self):
        plan = TextItemPlan(item_type=0, kind="script_end",
                            font=FontRole.GOST_TYPE_A, content="")
        item = _new_item_param(self.kompas5, self.const, plan)
        self.assertEqual(item.type, 0)
        self.assertEqual(item._font.bitVector, 0x10)

    def test_fraction_num_gets_type_1(self):
        plan = TextItemPlan(item_type=1, kind="fraction_num",
                            font=FontRole.GOST_TYPE_A, content="a")
        item = _new_item_param(self.kompas5, self.const, plan)
        self.assertEqual(item.type, 0)
        self.assertEqual(item._font.bitVector, 0x1)

    def test_fraction_den_gets_bitvector_2(self):
        plan = TextItemPlan(item_type=2, kind="fraction_den",
                            font=FontRole.GOST_TYPE_A, content="b")
        item = _new_item_param(self.kompas5, self.const, plan)
        self.assertEqual(item.type, 0)
        self.assertEqual(item._font.bitVector, 0x2)

    def test_special_symbol_uses_type_and_number(self):
        plan = TextItemPlan(item_type=17, kind="special",
                            font=FontRole.GOST_TYPE_A, content="$d1;2$",
                            i_s_numb=95)
        item = _new_item_param(self.kompas5, self.const, plan)
        self.assertEqual(item.type, 0x11)
        self.assertEqual(item.iSNumb, 95)
        self.assertEqual(item._font.bitVector, 0x11)

    def test_special_end_uses_end_bitvector(self):
        plan = TextItemPlan(item_type=18, kind="special_end",
                            font=FontRole.GOST_TYPE_A, content="")
        item = _new_item_param(self.kompas5, self.const, plan)
        self.assertEqual(item.type, 0)
        self.assertEqual(item._font.bitVector, 0x12)


# ─── _new_line_param ─────────────────────────────────────────────────────────


class TestNewLineParam(unittest.TestCase):

    def setUp(self):
        self.const = _FakeConst()
        self.kompas5 = _FakeKompas5(self.const.__dict__)

    def test_empty_items_creates_empty_line(self):
        line = _new_line_param(self.kompas5, self.const, [])
        self.assertEqual(len(line._arr.items), 0)

    def test_single_gost_item(self):
        items = [
            TextItemPlan(item_type=0, kind="plain",
                         font=FontRole.GOST_TYPE_A, content="F"),
        ]
        line = _new_line_param(self.kompas5, self.const, items)
        self.assertEqual(len(line._arr.items), 1)
        item = line._arr.items[0]
        self.assertEqual(item.s, "F")
        self.assertEqual(item._font.fontName, "GOST type A")

    def test_symbol_item_gets_symbol_font(self):
        items = [
            TextItemPlan(item_type=0, kind="plain",
                         font=FontRole.SYMBOL, content="t"),
        ]
        line = _new_line_param(self.kompas5, self.const, items)
        item = line._arr.items[0]
        self.assertEqual(item.s, "t")
        self.assertEqual(item._font.fontName, "Symbol type A")

    def test_mixed_items(self):
        items = [
            TextItemPlan(item_type=0, kind="script_base",
                         font=FontRole.GOST_TYPE_A, content="F"),
            TextItemPlan(item_type=0, kind="script_upper",
                         font=FontRole.SYMBOL, content="t"),
            TextItemPlan(item_type=0, kind="script_lower",
                         font=FontRole.GOST_TYPE_A, content="32"),
            TextItemPlan(item_type=0, kind="script_end",
                         font=FontRole.GOST_TYPE_A, content=""),
        ]
        line = _new_line_param(self.kompas5, self.const, items)
        self.assertEqual(len(line._arr.items), 4)
        self.assertEqual(line._arr.items[0]._font.fontName, "GOST type A")
        self.assertEqual(line._arr.items[1]._font.fontName, "Symbol type A")
        self.assertEqual(line._arr.items[2]._font.fontName, "GOST type A")
        self.assertEqual(line._arr.items[3]._font.fontName, "GOST type A")


    def test_repeated_styles_apply_to_line_break_marker(self):
        item = TextItemPlan(item_type=0, kind="plain",
                            font=FontRole.GOST_TYPE_A, content="formula",
                            italic=True)
        line = _new_line_param(
            self.kompas5, self.const, [item],
            height=5.0, break_after=True,
            repeat_styles=True, break_style=item,
        )
        marker = line._arr.items[-1]
        self.assertEqual(marker.s, "@/")
        self.assertTrue(marker._font.bitVector & 0x40)

    def test_clears_array_before_adding(self):
        items = [TextItemPlan(item_type=0, kind="plain",
                              font=FontRole.GOST_TYPE_A, content="a")]
        line1 = _new_line_param(self.kompas5, self.const, items)
        _new_line_param(self.kompas5, self.const, items)
        # Each call clears independently
        self.assertEqual(len(line1._arr.items), 1)


# ─── _new_text_param ─────────────────────────────────────────────────────────


class TestNewTextParam(unittest.TestCase):

    def setUp(self):
        self.const = _FakeConst()
        self.kompas5 = _FakeKompas5(self.const.__dict__)

    def _make_single_line_plan(self, content="Test", height=5.0):
        items = [TextItemPlan(item_type=0, kind="plain",
                              font=FontRole.GOST_TYPE_A, content=content)]
        return [TextLinePlan(items=items)], height

    def test_creates_param_with_paragraph(self):
        lines, height = self._make_single_line_plan()
        text_param = _new_text_param(
            self.kompas5, self.const,
            x=10.0, y=20.0, height=height,
            lines=lines, width=50.0,
        )
        self.assertTrue(text_param.inited)
        para = text_param._para
        self.assertIsNotNone(para)
        self.assertAlmostEqual(para.x, 10.0)
        self.assertAlmostEqual(para.y, 20.0)
        self.assertAlmostEqual(para.height, 5.0)
        self.assertAlmostEqual(para.width, 50.0)
        self.assertAlmostEqual(para.ang, 0.0)
        self.assertEqual(para.hFormat, 0)
        self.assertEqual(para.vFormat, 0)

    def test_creates_param_with_lines(self):
        lines, height = self._make_single_line_plan()
        text_param = _new_text_param(
            self.kompas5, self.const,
            x=0, y=0, height=height,
            lines=lines,
        )
        self.assertEqual(len(text_param._lines_arr.items), 1)

    def test_default_width(self):
        lines, height = self._make_single_line_plan()
        text_param = _new_text_param(
            self.kompas5, self.const,
            x=0, y=0, height=height,
            lines=lines,
        )
        self.assertAlmostEqual(text_param._para.width, 160.0)

    def test_empty_lines_creates_empty_array(self):
        text_param = _new_text_param(
            self.kompas5, self.const,
            x=0, y=0, height=5.0,
            lines=[],
        )
        self.assertEqual(len(text_param._lines_arr.items), 0)


# ─── add_api5_text_plan ──────────────────────────────────────────────────────


class TestAddApi5TextPlan(unittest.TestCase):

    def setUp(self):
        self.const = _FakeConst()
        self.kompas5 = _FakeKompas5(self.const.__dict__)
        self.doc2d = _FakeDoc2D()

    def test_returns_reference_on_success(self):
        plan = TextRenderPlan(
            lines=[TextLinePlan(items=[
                TextItemPlan(item_type=0, kind="plain",
                             font=FontRole.GOST_TYPE_A, content="Hi"),
            ])],
            height=5.0,
        )
        ref = add_api5_text_plan(
            self.doc2d, self.kompas5, self.const,
            plan, center_x=100, center_y=200,
        )
        self.assertEqual(ref, 42)

    def test_raises_on_zero_reference(self):
        self.doc2d.ksTextEx.return_value = 0
        plan = TextRenderPlan(
            lines=[TextLinePlan(items=[])],
            height=5.0,
        )
        with self.assertRaises(RuntimeError) as ctx:
            add_api5_text_plan(
                self.doc2d, self.kompas5, self.const,
                plan, center_x=0, center_y=0,
                entity_id="text-42",
            )
        self.assertIn("text-42", str(ctx.exception))
        self.assertIn("zero reference", str(ctx.exception))

    def test_centers_position_using_plan_size(self):
        plan = TextRenderPlan(
            lines=[TextLinePlan(items=[
                TextItemPlan(item_type=0, kind="plain",
                             font=FontRole.GOST_TYPE_A, content="AB"),
            ])],
            height=5.0,
        )
        # "AB" at height=5: w ≈ 2 * 5 * 0.7 = 7.0, h ≈ 5 * 1.4 = 7.0
        # center (50, 100) → bottom-left (50 - 3.5, 100 - 3.5) = (46.5, 96.5)
        add_api5_text_plan(
            self.doc2d, self.kompas5, self.const,
            plan, center_x=50, center_y=100,
        )
        para = self.kompas5._last_text_param._para
        self.assertAlmostEqual(para.x, 46.5, places=4)
        self.assertAlmostEqual(para.y, 96.5, places=4)

    def test_entity_id_in_error(self):
        self.doc2d.ksTextEx.return_value = 0  # zero reference triggers check
        plan = TextRenderPlan(
            lines=[TextLinePlan(items=[
                TextItemPlan(item_type=0, kind="plain",
                             font=FontRole.GOST_TYPE_A, content="x"),
            ])],
            height=5.0,
        )
        with self.assertRaises(RuntimeError) as ctx:
            add_api5_text_plan(
                self.doc2d, self.kompas5, self.const,
                plan, center_x=0, center_y=0,
                entity_id="my-label",
            )
        self.assertIn("my-label", str(ctx.exception))


# ─── TEXT_ITEM_ARR constant ──────────────────────────────────────────────────


class TestTextItemArrConstant(unittest.TestCase):

    def test_value_is_4(self):
        self.assertEqual(TEXT_ITEM_ARR, 4)


if __name__ == "__main__":
    unittest.main()
