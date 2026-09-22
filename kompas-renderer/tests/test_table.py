"""COM-free contract and lowering tests for the tmm-scene ``table`` entity."""

import unittest
from unittest.mock import patch

from tmm_scene_kompas.render import add_table, entity_requires_api5, offset_entity, validate_payload_v2
from tmm_scene_kompas.table import (
    TableCellCompileError,
    TableCompileError,
    compile_table_cell_inline_plan,
    compile_table_plan,
    table_requires_api5,
)


class TestTablePlan(unittest.TestCase):

    def test_positions_cells_from_a_y_up_top_left_corner(self):
        plan = compile_table_plan({
            "type": "table", "id": "t", "position": [10, 50],
            "columnWidths": [20, 30], "rowHeights": [8, 12],
            "cells": [{"row": 0, "column": 0, "text": "A"},
                      {"row": 1, "column": 1, "text": "B"}],
        })
        self.assertEqual(plan.width, 50.0)
        self.assertEqual(plan.height, 20.0)
        self.assertEqual(plan.cell_center(plan.cells[0]), (20.0, 46.0))
        self.assertEqual(plan.cell_center(plan.cells[1]), (45.0, 36.0))

    def test_merged_cells_suppress_only_the_grid_segments_inside_the_merge(self):
        plan = compile_table_plan({
            "type": "table", "id": "merged", "position": [0, 30],
            "columnWidths": [10, 10, 10], "rowHeights": [10, 10, 10],
            "cells": [
                {"row": 0, "column": 0, "colSpan": 3, "text": "title"},
                {"row": 1, "column": 0, "rowSpan": 2, "text": "side"},
                {"row": 1, "column": 1, "text": "a"},
                {"row": 1, "column": 2, "text": "b"},
                {"row": 2, "column": 1, "text": "c"},
                {"row": 2, "column": 2, "text": "d"},
            ],
        })
        self.assertEqual(list(plan.internal_vertical_segments()), [
            (10.0, 10.0, 20.0), (10.0, 0.0, 10.0),
            (20.0, 10.0, 20.0), (20.0, 0.0, 10.0),
        ])
        self.assertEqual(list(plan.internal_horizontal_segments()), [
            (20.0, 0.0, 10.0), (20.0, 10.0, 20.0), (20.0, 20.0, 30.0),
            (10.0, 10.0, 20.0), (10.0, 20.0, 30.0),
        ])

    def test_rejects_overlapping_cells_and_invalid_spans(self):
        base = {
            "type": "table", "id": "bad", "position": [0, 0],
            "columnWidths": [10, 10], "rowHeights": [10],
            "cells": [
                {"row": 0, "column": 0, "colSpan": 2, "text": "first"},
                {"row": 0, "column": 1, "text": "second"},
            ],
        }
        with self.assertRaisesRegex(TableCompileError, "overlaps"):
            compile_table_plan(base)
        base["cells"] = [{"row": 0, "column": 0, "colSpan": 0, "text": "x"}]
        with self.assertRaisesRegex(TableCompileError, "greater than zero"):
            compile_table_plan(base)

    def test_table_is_validated_before_kompas_and_offset_as_a_single_entity(self):
        table = {
            "type": "table", "id": "t", "position": [0, 0],
            "columnWidths": [10], "rowHeights": [10],
            "cells": [{"row": 0, "column": 0, "text": "x"}],
        }
        validate_payload_v2({"entities": [table]})
        self.assertEqual(offset_entity(table, (3, 4))["position"], [3.0, 4.0])

    def test_native_table_cells_never_require_the_api5_text_path(self):
        plain = compile_table_plan({
            "type": "table", "id": "plain", "position": [0, 0],
            "columnWidths": [10], "rowHeights": [10],
            "cells": [{"row": 0, "column": 0, "text": "plain"}],
        })
        self.assertFalse(table_requires_api5(plain))
        math = compile_table_plan({
            "type": "table", "id": "math", "position": [0, 0],
            "columnWidths": [10], "rowHeights": [10],
            "cells": [{"row": 0, "column": 0, "text": "F_1"}],
        })
        self.assertFalse(table_requires_api5(math))
        self.assertFalse(entity_requires_api5({
            "type": "table", "id": "italic", "position": [0, 0],
            "columnWidths": [10], "rowHeights": [10],
            "cells": [{"row": 0, "column": 0, "text": "x", "italic": True}],
        }))


class TestTableLowering(unittest.TestCase):

    def test_creates_one_native_table_with_formats_merges_and_cell_text(self):
        class Format:
            def __init__(self, owner=None, row=None, column=None):
                self.ReadOnly = None
                self._width = None
                self.Height = None
                self._owner = owner
                self._row = row
                self._column = column

            @property
            def Width(self):
                return self._width

            @Width.setter
            def Width(self, value):
                self._width = value
                if self._owner is not None:
                    self._owner.width_assignments.append((self._row, self._column, value))

        class Range:
            def __init__(self):
                self.CellsFormat = Format()
                self.combined = False

            def CombineCells(self):
                self.combined = True
                return True

        class Font:
            def __init__(self, height=10.0):
                self.Height = height
                self.Italic = False

        class Item:
            def __init__(self, value, item_type, height=10.0):
                self.Str = value
                self.ItemType = item_type
                self.font = Font(height)

        class Line:
            def __init__(self, text):
                self._text = text
                self.add_calls = 0
                self.clear_calls = 0

            @property
            def TextItems(self):
                return self._text.items

        class Text:
            def __init__(self):
                self._str = ""
                self.items = []
                self.lines = [Line(self)]

            @property
            def Str(self):
                return self._str

            @Str.setter
            def Str(self, value):
                base_height = self.items[0].font.Height if self.items else 10.0
                self._str = str(value)
                if self._str == ".":
                    self.items = [Item(".", 0, base_height)]
                elif self._str == "Длина l$;1$, мм":
                    self.items = [
                        Item("Длина l", 0, base_height),
                        Item("", 4, base_height * 2.0 / 3.0),
                        Item("1", 5, base_height * 2.0 / 3.0),
                        Item(", мм", 6, base_height),
                    ]
                elif self._str:
                    self.items = [Item(self._str, 0, base_height)]
                else:
                    self.items = []

            @property
            def TextLines(self):
                return self.lines

        class Cell:
            def __init__(self, owner, row, column):
                self.format = Format(owner, row, column)
                self.Text = Text()
        class NativeTable:
            def __init__(self):
                self.X = None
                self.Y = None
                self.ranges = []
                self.cells = {}
                self.width_assignments = []
                self.update_count = 0
                self.table = self

            def Range(self, *args):
                value = Range()
                self.ranges.append((args, value))
                return value

            def Cell(self, row, column):
                return self.cells.setdefault((row, column), Cell(self, row, column))

            def Update(self):
                self.update_count += 1
                return True

        class Tables:
            def __init__(self):
                self.add_args = None
                self.native = NativeTable()

            def Add(self, *args):
                self.add_args = args
                return self.native

        tables = Tables()
        symbols = type("Symbols", (), {"DrawingTables": tables})()
        plan = compile_table_plan({
            "type": "table", "id": "t", "position": [0, 20],
            "columnWidths": [10, 20], "rowHeights": [5, 10], "italic": True,
            "cells": [
                {"row": 0, "column": 0, "colSpan": 2, "text": "title"},
                {"row": 1, "column": 0, "text": "left"},
                {"row": 1, "column": 1, "text": "Длина $l_1$, мм"},
            ],
        })

        def fake_qi(_module, obj, interface):
            if interface == "ITable":
                return obj.table
            if interface == "ITextFont":
                return obj.font
            if interface == "ICellFormat":
                return getattr(obj, "format", obj)
            if interface == "IText":
                return obj
            raise AssertionError(interface)

        with patch("tmm_scene_kompas.render._qi", side_effect=fake_qi):
            add_table(object(), symbols, plan)
        native = tables.native
        self.assertEqual(tables.add_args, (2, 2, 5.0, 10.0, 0))
        self.assertEqual((native.X, native.Y), (0.0, 20.0))
        self.assertEqual(native.width_assignments, [
            (0, 0, 10.0), (0, 1, 20.0), (1, 0, 10.0), (1, 1, 20.0)
        ])
        self.assertEqual(native.update_count, 2)
        self.assertEqual(native.cells[(0, 0)].Text.Str, "title")
        self.assertEqual(native.cells[(1, 0)].Text.Str, "left")
        rich_text = native.cells[(1, 1)].Text
        self.assertEqual(rich_text.Str, "Длина l$;1$, мм")
        self.assertEqual([item.ItemType for item in rich_text.items], [0, 4, 5, 6])
        self.assertEqual([item.font.Height for item in rich_text.items], [5.0, 10.0 / 3.0, 10.0 / 3.0, 5.0])
        self.assertTrue(all(item.font.Italic for item in rich_text.items))
        self.assertEqual(rich_text.lines[0].add_calls, 0)
        self.assertEqual(rich_text.lines[0].clear_calls, 0)

    def test_rejects_removed_cell_latex_key_even_when_null(self):
        with self.assertRaisesRegex(TableCompileError, "removed legacy field"):
            compile_table_plan({
                "type": "table", "id": "legacy", "position": [0, 10],
                "columnWidths": [10], "rowHeights": [10],
                "cells": [{"row": 0, "column": 0, "text": "x", "latex": None}],
            })


if __name__ == "__main__":
    unittest.main()
