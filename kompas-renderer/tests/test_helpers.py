"""Unit tests for pure helpers in tmm_scene_kompas.render.

These tests exercise only the COM-free helper functions and the
Api5Context with fake objects.  They can run on any platform
without pywin32 or a KOMPAS install.
"""

import inspect
import json
import math
import os
import unittest
from unittest.mock import MagicMock, patch

from tmm_scene_kompas.render import (
    POLYLINE_ARR,
    _ComApartment,
    POINT_ARR,
    Api5Context,
    add_filled_circle,
    add_smooth_curve,
    add_text,
    api5_math_point,
    build_drawing,
    catmull_rom_point,
    catmull_rom_spline,
    compute_leader_base_and_tip,
    configure_super_scene_sheet,
    disable_clear_background,
    draw_scene_document,
    estimate_kompas_text_size,
    is_arrowhead_polygon,
    kompas_text_origin_from_center,
    leader_arrow_base_and_tip_from_polygon,
    resolve_style_for_layer,
    scene_entity_to_api,
    super_scene_sheet_spec,
    validate_payload_v2,
)
from tmm_scene_kompas.validation import validate_v2


# ─── Fake helpers ───────────────────────────────────────────────────────────


class _FakeConst:
    """Minimal stand-in for KOMPAS constants."""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class _FakeDynamicArray:
    """Mimics pywin32 dynamic array returned by GetDynamicArray()."""

    def __init__(self, kind):
        self.kind = kind
        self.items = []

    def ksClearArray(self):
        self.items.clear()
        return True

    def ksAddArrayItem(self, index, item):
        self.items.append(item)
        return True


class _FakeMathPoint:
    def __init__(self, x=0.0, y=0.0):
        self.x = float(x)
        self.y = float(y)

    def Init(self):
        pass


class _FakeLeaderParam:
    def __init__(self):
        self.Init()

    def Init(self):
        self.arrowType = 0
        self.signType = 0
        self.dirX = 1
        self.x = 0.0
        self.y = 0.0
        self.around = 0
        self.cText0 = 0
        self.cText1 = 0
        self.cText2 = 0
        self.cText3 = 0
        self._pPolyline = None

    def SetpPolyline(self, branches):
        self._pPolyline = branches
        return True


class _FakeDrawingObject1:
    def __init__(self):
        self.TransparentBackground = True
        self.AutoTransparentBackground = True
        self.updated = False

    def Update(self):
        self.updated = True


class _FakeKompasObject:
    """Mimics the generated API5 KompasObject for testing."""

    def __init__(self):
        self._doc2d = MagicMock()
        self._doc2d.ksLeader = MagicMock(return_value=42)
        self.GetDynamicArray_calls = []
        self.transferred = _FakeDrawingObject1()
        self.TransferReference = MagicMock(return_value=self.transferred)

    def ActiveDocument2D(self):
        return self._doc2d

    def GetParamStruct(self, struct_type):
        if struct_type == 200:  # ko_MathPointParam
            return _FakeMathPoint()
        return _FakeLeaderParam()

    def GetDynamicArray(self, kind):
        self.GetDynamicArray_calls.append(kind)
        return _FakeDynamicArray(kind)


class _FakeConst5:
    ko_LeaderParam = 100
    ko_MathPointParam = 200
    ksLeaderArrow = 2


class _FakeSheetFormat:
    def __init__(self):
        self.Format = 4
        self.VerticalOrientation = True
        self.FormatWidth = 210.0
        self.FormatHeight = 297.0


class _FakeStampText:
    def __init__(self):
        self.Str = ""


class _FakeStamp:
    def __init__(self):
        self.cells = {}
        self.updated = False

    def Text(self, cell_id):
        return self.cells.setdefault(int(cell_id), _FakeStampText())

    def Update(self):
        self.updated = True
        # KOMPAS can return False even though the stamp text was accepted.
        return False


class _FakeLayoutSheet:
    def __init__(self):
        self.Format = _FakeSheetFormat()
        self.Stamp = _FakeStamp()
        self.updated = False

    def Update(self):
        self.updated = True
        # Mirror the real API's update of the format dimensions.
        if self.Format.Format == 2 and not self.Format.VerticalOrientation:
            self.Format.FormatWidth = 594.0
            self.Format.FormatHeight = 420.0
        return True


class _FakeLayoutSheets:
    def __init__(self, sheet):
        self.sheet = sheet

    def Item(self, index):
        assert index == 0
        return self.sheet


class _FakeSheetDocument:
    def __init__(self, sheet):
        self.LayoutSheets = _FakeLayoutSheets(sheet)


# ─── resolve_style_for_layer ─────────────────────────────────────────────────


class TestResolveStyleForLayer(unittest.TestCase):

    def setUp(self):
        self.const = _FakeConst(
            ksCSNormal=1,
            ksCSThin=2,
            ksCSThick=7,
            ksCSDashed=4,
            ksCSNormalDashDot=10,
            ksCSDashedNormal=9,
            ksCSThinForHatch=11,
        )

    def test_fixed_solid_uses_thick(self):
        self.assertEqual(resolve_style_for_layer(self.const, 'fixed', 'solid'), 7)

    def test_fixed_dashed_uses_dashed(self):
        self.assertEqual(resolve_style_for_layer(self.const, 'fixed', 'dashed'), 4)

    def test_thin_solid_uses_thin(self):
        self.assertEqual(resolve_style_for_layer(self.const, 'thin', 'solid'), 2)

    def test_thin_dashed_uses_dashed(self):
        self.assertEqual(resolve_style_for_layer(self.const, 'thin', 'dashed'), 4)

    def test_thin_dashdot_uses_dashdot(self):
        self.assertEqual(resolve_style_for_layer(self.const, 'thin', 'dashdot'), 10)

    def test_hatch_uses_thin_for_hatch(self):
        self.assertEqual(resolve_style_for_layer(self.const, 'hatch', 'solid'), 11)

    def test_hatch_dashed_uses_thin_for_hatch(self):
        self.assertEqual(resolve_style_for_layer(self.const, 'hatch', 'dashed'), 11)

    def test_dimension_solid_uses_thin(self):
        self.assertEqual(resolve_style_for_layer(self.const, 'dimension', 'solid'), 2)

    def test_label_dashed_uses_dashed(self):
        self.assertEqual(resolve_style_for_layer(self.const, 'label', 'dashed'), 4)

    def test_dotted_uses_dash_dot_style(self):
        self.assertEqual(resolve_style_for_layer(self.const, 'thin', 'dotted'), 10)

    def test_missing_attributes_fallback(self):
        bare = _FakeConst(ksCSNormal=1)
        self.assertEqual(resolve_style_for_layer(bare, 'fixed', 'solid'), 1)
        self.assertEqual(resolve_style_for_layer(bare, 'thin', 'dashed'), 1)
        self.assertEqual(resolve_style_for_layer(bare, 'hatch', 'solid'), 1)

    def test_empty_const_uses_one_fallback(self):
        empty = _FakeConst()
        self.assertEqual(resolve_style_for_layer(empty, 'fixed', 'solid'), 1)


# ─── super-scene sheet setup ─────────────────────────────────────────────────


class TestSuperSceneSheet(unittest.TestCase):

    def setUp(self):
        self.const = _FakeConst(
            ksFormatA0=0, ksFormatA1=1, ksFormatA2=2,
            ksFormatA3=3, ksFormatA4=4, ksFormatA5=5,
        )
        self.payload = {
            "kind": "super-scene",
            "sheet": {
                "format": "A2",
                "orientation": "landscape",
                "titleBlock": {"text": "Mechanism title"},
            },
            "entities": [],
        }

    def test_spec_normalizes_fixture_sheet(self):
        spec = super_scene_sheet_spec(self.payload)
        self.assertEqual(spec["format"], "A2")
        self.assertEqual(spec["format_fallback"], 2)
        self.assertEqual(spec["orientation"], "landscape")
        self.assertEqual(spec["title_cell"], 2)
        self.assertEqual(spec["title"], "Mechanism title")

    def test_non_super_scene_has_no_sheet_setup(self):
        self.assertIsNone(super_scene_sheet_spec({"kind": "ordinary"}))

    def test_missing_sheet_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "sheet"):
            super_scene_sheet_spec({"kind": "super-scene"})

    def test_invalid_format_is_rejected(self):
        payload = {"kind": "super-scene", "sheet": {"format": "A7"}}
        with self.assertRaisesRegex(ValueError, "format"):
            super_scene_sheet_spec(payload)

    def test_configures_a2_landscape_and_stamp_title(self):
        sheet = _FakeLayoutSheet()
        configure_super_scene_sheet(
            _FakeSheetDocument(sheet), self.const, self.payload
        )
        self.assertEqual(sheet.Format.Format, 2)
        self.assertFalse(sheet.Format.VerticalOrientation)
        self.assertAlmostEqual(sheet.Format.FormatWidth, 594.0)
        self.assertAlmostEqual(sheet.Format.FormatHeight, 420.0)
        self.assertTrue(sheet.updated)
        self.assertEqual(sheet.Stamp.Text(2).Str, "Mechanism title")
        self.assertTrue(sheet.Stamp.updated)


# ─── compute_leader_base_and_tip ─────────────────────────────────────────────


class TestComputeLeaderBaseAndTip(unittest.TestCase):

    def test_no_offset(self):
        bx, by, tx, ty = compute_leader_base_and_tip(
            tip=(10, 20), base=(5, 10),
        )
        self.assertAlmostEqual(bx, 5.0)
        self.assertAlmostEqual(by, 10.0)
        self.assertAlmostEqual(tx, 10.0)
        self.assertAlmostEqual(ty, 20.0)

    def test_with_offset(self):
        bx, by, tx, ty = compute_leader_base_and_tip(
            tip=(0, 0), base=(-1, -2), offset=(100, 200),
        )
        self.assertAlmostEqual(bx, 99.0)
        self.assertAlmostEqual(by, 198.0)
        self.assertAlmostEqual(tx, 100.0)
        self.assertAlmostEqual(ty, 200.0)

    def test_default_offset_is_zero(self):
        bx, by, tx, ty = compute_leader_base_and_tip(
            tip=(3, 4), base=(1, 2),
        )
        self.assertAlmostEqual(bx, 1.0)
        self.assertAlmostEqual(by, 2.0)
        self.assertAlmostEqual(tx, 3.0)
        self.assertAlmostEqual(ty, 4.0)

    def test_zero_length_leader(self):
        bx, by, tx, ty = compute_leader_base_and_tip(
            tip=(7, 7), base=(7, 7),
        )
        self.assertAlmostEqual(bx, 7.0)
        self.assertAlmostEqual(tx, 7.0)


# ─── Arrowhead polygon helpers ───────────────────────────────────────────────


class TestArrowheadPolygonHelpers(unittest.TestCase):

    def test_arrowhead_role_detection(self):
        self.assertTrue(is_arrowhead_polygon({'type': 'polygon', 'role': 'arrowhead'}))
        self.assertTrue(is_arrowhead_polygon({'type': 'polygon', 'metadata': {'role': 'arrowhead'}}))
        self.assertFalse(is_arrowhead_polygon({'type': 'polygon'}))
        self.assertFalse(is_arrowhead_polygon({'type': 'polygon', 'metadata': {'role': 'other'}}))

    def test_leader_arrow_base_and_tip_from_polygon(self):
        base, tip = leader_arrow_base_and_tip_from_polygon(
            [(5.0, 10.0), (0.0, 0.0), (10.0, 0.0)],
            length=0.5,
        )
        self.assertAlmostEqual(tip[0], 5.0)
        self.assertAlmostEqual(tip[1], 10.0)
        self.assertAlmostEqual(base[0], 5.0)
        self.assertAlmostEqual(base[1], 9.5)

    def test_non_arrowhead_triangle_remains_polygon(self):
        self.assertFalse(is_arrowhead_polygon({'type': 'polygon', 'points': [[5, 10], [0, 0], [10, 0]]}))


# ─── Api5Context with fake COM objects ───────────────────────────────────────


class TestApi5ContextLeaderArrow(unittest.TestCase):
    """Verify Api5Context.add_leader_arrow() calls the right API5 methods
    with the right dynamic-array shape, without any real COM."""

    def _make_ctx(self, kompas_obj=None):
        """Build an Api5Context with injected fake objects (no _ensure())."""
        ctx = Api5Context.__new__(Api5Context)
        ctx._kompas = kompas_obj or _FakeKompasObject()
        ctx._const = _FakeConst5()
        ctx._module7 = None
        return ctx

    def test_gets_dynamic_arrays_with_correct_constants(self):
        kompas = _FakeKompasObject()
        ctx = self._make_ctx(kompas)
        ctx.add_leader_arrow(base_x=5.0, base_y=10.0, tip_x=15.0, tip_y=20.0)
        self.assertEqual(kompas.GetDynamicArray_calls, [POLYLINE_ARR, POINT_ARR])

    def test_branch_contains_only_tip(self):
        """The inner POINT_ARR must contain exactly one point: the tip."""
        kompas = _FakeKompasObject()
        ctx = self._make_ctx(kompas)
        ctx.add_leader_arrow(base_x=5.0, base_y=10.0, tip_x=15.0, tip_y=20.0)

        doc2d = kompas.ActiveDocument2D()
        ks_leader_call = doc2d.ksLeader
        self.assertTrue(ks_leader_call.called)
        leader_param = ks_leader_call.call_args[0][0]

        branches = leader_param._pPolyline
        self.assertIsInstance(branches, _FakeDynamicArray)
        self.assertEqual(branches.kind, POLYLINE_ARR)
        self.assertEqual(len(branches.items), 1)

        branch = branches.items[0]
        self.assertIsInstance(branch, _FakeDynamicArray)
        self.assertEqual(branch.kind, POINT_ARR)
        self.assertEqual(len(branch.items), 1, 'branch has only the tip point')

        tip_point = branch.items[0]
        self.assertIsInstance(tip_point, _FakeMathPoint)
        self.assertAlmostEqual(tip_point.x, 15.0)
        self.assertAlmostEqual(tip_point.y, 20.0)

    def test_leader_base_point_is_leader_xy(self):
        """leader.x/y must be the base point, not the tip."""
        kompas = _FakeKompasObject()
        ctx = self._make_ctx(kompas)
        ctx.add_leader_arrow(base_x=5.0, base_y=10.0, tip_x=15.0, tip_y=20.0)

        doc2d = kompas.ActiveDocument2D()
        leader_param = doc2d.ksLeader.call_args[0][0]
        self.assertAlmostEqual(leader_param.x, 5.0)
        self.assertAlmostEqual(leader_param.y, 10.0)

    def test_ksLeader_called_on_active_document(self):
        """ksLeader must be called on the active API5 document, not API7."""
        kompas = _FakeKompasObject()
        ctx = self._make_ctx(kompas)
        result = ctx.add_leader_arrow(base_x=0, base_y=0, tip_x=1, tip_y=1)
        doc2d = kompas.ActiveDocument2D()
        doc2d.ksLeader.assert_called_once()
        self.assertTrue(result)

    def test_returns_false_when_not_available(self):
        ctx = Api5Context.__new__(Api5Context)
        ctx._kompas = None
        ctx._const = None
        self.assertFalse(ctx.add_leader_arrow(0, 0, 1, 1))

    def test_returns_false_on_exception(self):
        kompas = _FakeKompasObject()
        kompas.ActiveDocument2D = MagicMock(return_value=None)
        ctx = self._make_ctx(kompas)
        self.assertFalse(ctx.add_leader_arrow(0, 0, 1, 1))

    def test_disables_leader_clear_background(self):
        kompas = _FakeKompasObject()
        ctx = self._make_ctx(kompas)
        ctx.add_leader_arrow(base_x=3.0, base_y=4.0, tip_x=8.0, tip_y=9.0)

        kompas.TransferReference.assert_called_once_with(42, 0)
        self.assertFalse(kompas.transferred.TransparentBackground)
        self.assertFalse(kompas.transferred.AutoTransparentBackground)
        self.assertTrue(kompas.transferred.updated)

    def test_clear_background_failure_does_not_fail_leader_creation(self):
        kompas = _FakeKompasObject()
        kompas.TransferReference = MagicMock(side_effect=RuntimeError('no transfer'))
        ctx = self._make_ctx(kompas)
        self.assertTrue(ctx.add_leader_arrow(base_x=0, base_y=0, tip_x=1, tip_y=1))

    def test_leader_param_fields(self):
        """Verify all expected fields on the leader param struct."""
        kompas = _FakeKompasObject()
        ctx = self._make_ctx(kompas)
        ctx.add_leader_arrow(base_x=3.0, base_y=4.0, tip_x=8.0, tip_y=9.0)

        doc2d = kompas.ActiveDocument2D()
        leader = doc2d.ksLeader.call_args[0][0]
        self.assertEqual(leader.arrowType, 2)  # ksLeaderArrow
        self.assertEqual(leader.signType, 0)
        self.assertEqual(leader.dirX, 1)
        self.assertEqual(leader.around, 0)
        self.assertEqual(leader.cText0, 0)
        self.assertEqual(leader.cText1, 0)
        self.assertEqual(leader.cText2, 0)
        self.assertEqual(leader.cText3, 0)


# ─── api5_math_point ─────────────────────────────────────────────────────────


class TestApi5MathPoint(unittest.TestCase):

    def test_creates_point_with_coordinates(self):
        fake_kompas = MagicMock()
        fake_const = MagicMock()
        fake_point = _FakeMathPoint()
        fake_kompas.GetParamStruct.return_value = fake_point

        result = api5_math_point(fake_kompas, fake_const, 7.5, 3.2)
        self.assertAlmostEqual(result.x, 7.5)
        self.assertAlmostEqual(result.y, 3.2)
        fake_kompas.GetParamStruct.assert_called_once_with(fake_const.ko_MathPointParam)


# ─── Api5Context._ensure signature ───────────────────────────────────────────


class TestApi5DocumentIdentity(unittest.TestCase):
    """API5 text must remain bound to the API7-created document reference."""

    @staticmethod
    def _document(reference, attribute):
        document = type("Document", (), {})()
        setattr(document, attribute, reference)
        return document

    @staticmethod
    def _context(api5_document):
        ctx = Api5Context.__new__(Api5Context)
        ctx._kompas = MagicMock()
        ctx._kompas.ActiveDocument2D.return_value = api5_document
        ctx._const = MagicMock()
        ctx._module7 = None
        ctx._expected_doc2d = None
        ctx._api7_app = None
        ctx._expected_document_reference = None
        return ctx

    def test_bind_requires_matching_api7_active_and_api5_references(self):
        created = self._document(123, "Reference")
        active = self._document(123, "Reference")
        app = self._document(active, "ActiveDocument")
        api5_document = self._document(123, "reference")
        ctx = self._context(api5_document)

        ctx.bind_active_document(app, created)
        self.assertEqual(ctx._expected_document_reference, 123)
        self.assertIs(ctx._active_document("text-1"), api5_document)

    def test_bind_rejects_api5_document_that_is_not_the_created_api7_document(self):
        created = self._document(123, "Reference")
        app = self._document(self._document(123, "Reference"), "ActiveDocument")
        api5_document = self._document(456, "reference")
        with self.assertRaisesRegex(RuntimeError, "does not match"):
            self._context(api5_document).bind_active_document(app, created)

    def test_use_rejects_active_document_change_after_successful_bind(self):
        created = self._document(123, "Reference")
        app = self._document(self._document(123, "Reference"), "ActiveDocument")
        api5_document = self._document(123, "reference")
        ctx = self._context(api5_document)
        ctx.bind_active_document(app, created)
        app.ActiveDocument = self._document(456, "Reference")
        with self.assertRaisesRegex(RuntimeError, "document changed"):
            ctx._active_document("text-1")


class TestComApartment(unittest.TestCase):

    def test_balances_only_its_own_com_initialization(self):
        events = []

        class PythonCom:
            def CoInitialize(self): events.append("init")
            def CoUninitialize(self): events.append("uninit")

        with patch("tmm_scene_kompas.render._ensure_pythoncom"):
            with patch("tmm_scene_kompas.render.pythoncom", PythonCom()):
                with _ComApartment():
                    self.assertEqual(events, ["init"])
        self.assertEqual(events, ["init", "uninit"])


class TestEnsureIsSelfContained(unittest.TestCase):

    def test_ensure_takes_no_arguments(self):
        sig = inspect.signature(Api5Context._ensure)
        # _ensure(self) — only self, no api7_app parameter
        params = [p for p in sig.parameters if p != 'self']
        self.assertEqual(params, [], '_ensure() must not accept api7_app')


# ─── estimate_kompas_text_size ───────────────────────────────────────────────


class TestEstimateKompasTextSize(unittest.TestCase):

    def test_single_char(self):
        w, h = estimate_kompas_text_size('A', 5.0)
        self.assertAlmostEqual(w, 1 * 5.0 * 0.7)
        self.assertAlmostEqual(h, 5.0)

    def test_empty_string_treated_as_one_char(self):
        w, h = estimate_kompas_text_size('', 5.0)
        self.assertAlmostEqual(w, 1 * 5.0 * 0.7)
        self.assertAlmostEqual(h, 5.0)

    def test_multi_char(self):
        w, h = estimate_kompas_text_size('Hello', 5.0)
        self.assertAlmostEqual(w, 5 * 5.0 * 0.7)
        self.assertAlmostEqual(h, 5.0)

    def test_custom_char_width_factor(self):
        w, h = estimate_kompas_text_size('AB', 4.0, char_width_factor=1.0)
        self.assertAlmostEqual(w, 2 * 4.0 * 1.0)
        self.assertAlmostEqual(h, 4.0)

    def test_height_passthrough(self):
        _w, h = estimate_kompas_text_size('test', 7.5)
        self.assertAlmostEqual(h, 7.5)


# ─── kompas_text_origin_from_center ──────────────────────────────────────────


class TestKompasTextOriginFromCenter(unittest.TestCase):

    def test_returns_bottom_left(self):
        # 'AB' at height 5: width = 2 * 5 * 0.7 = 7.0, height = 5.0
        # center (100, 50) → origin (100 - 3.5, 50 - 2.5) = (96.5, 47.5)
        ox, oy = kompas_text_origin_from_center(100, 50, 'AB', 5.0)
        self.assertAlmostEqual(ox, 96.5)
        self.assertAlmostEqual(oy, 47.5)

    def test_single_char_at_origin(self):
        # 'X' at height 5: width = 3.5, height = 5
        # center (0, 0) → origin (-1.75, -2.5)
        ox, oy = kompas_text_origin_from_center(0, 0, 'X', 5.0)
        self.assertAlmostEqual(ox, -1.75)
        self.assertAlmostEqual(oy, -2.5)

    def test_custom_factor(self):
        ox, oy = kompas_text_origin_from_center(10, 10, 'T', 5.0,
                                                 char_width_factor=1.0)
        # width = 1 * 5 * 1.0 = 5.0
        self.assertAlmostEqual(ox, 10 - 2.5)
        self.assertAlmostEqual(oy, 10 - 2.5)



# ─── Catmull-Rom spline helpers ──────────────────────────────────────────────


class TestCatmullRomPoint(unittest.TestCase):
    """Unit tests for catmull_rom_point."""

    def test_linear_points_centripetal(self):
        """Four collinear points at equal spacing with t=0 should return p1."""
        p0 = (0.0, 0.0)
        p1 = (1.0, 0.0)
        p2 = (2.0, 0.0)
        p3 = (3.0, 0.0)
        pt = catmull_rom_point(p0, p1, p2, p3, 0.0)
        self.assertAlmostEqual(pt[0], 1.0)
        self.assertAlmostEqual(pt[1], 0.0)

    def test_linear_points_t_end(self):
        """t=1 should return p2."""
        pt = catmull_rom_point((0, 0), (1, 0), (2, 0), (3, 0), 1.0)
        self.assertAlmostEqual(pt[0], 2.0)

    def test_linear_points_midpoint(self):
        """At t=0.5 for equally-spaced collinear points, result should be
        near the midpoint of p1 and p2."""
        pt = catmull_rom_point((0, 0), (1, 0), (3, 0), (4, 0), 0.5)
        self.assertAlmostEqual(pt[0], 2.0, places=4)

    def test_uniform_alpha_zero(self):
        """With alpha=0.0 (uniform), the result is a standard Catmull-Rom."""
        pt = catmull_rom_point((0, 0), (1, 1), (2, 0), (3, 1), 0.5, alpha=0.0)
        # Should land exactly on the spline; check a known property
        self.assertAlmostEqual(pt[1], 0.5, places=4)

    def test_degenerate_all_coincident(self):
        """When all four points coincide, return p1."""
        pt = catmull_rom_point((5, 5), (5, 5), (5, 5), (5, 5), 0.5)
        self.assertAlmostEqual(pt[0], 5.0)
        self.assertAlmostEqual(pt[1], 5.0)

    def test_two_identical_pairs(self):
        pt = catmull_rom_point((0, 0), (1, 1), (1, 1), (2, 0), 0.5)
        # Should still produce a finite result, not NaN
        self.assertTrue(math.isfinite(pt[0]))
        self.assertTrue(math.isfinite(pt[1]))


class TestCatmullRomSpline(unittest.TestCase):
    """Unit tests for catmull_rom_spline."""

    def test_two_points_linear(self):
        """With only 2 control points, returns a linear interpolation."""
        result = catmull_rom_spline([(0.0, 0.0), (10.0, 0.0)], num_segments=4)
        self.assertEqual(len(result), 5)  # 4 segments + 1 = 5 pts
        self.assertAlmostEqual(result[0][0], 0.0)
        self.assertAlmostEqual(result[4][0], 10.0)
        self.assertAlmostEqual(result[2][0], 5.0)
        self.assertAlmostEqual(result[2][1], 0.0)

    def test_three_points_count(self):
        """3 control points with 10 segments each → 21 total points."""
        result = catmull_rom_spline([(0, 0), (5, 10), (10, 0)], num_segments=10)
        self.assertEqual(len(result), 10 * 2 + 1)  # 21

    def test_three_points_start_end(self):
        """Start and end must match the original control points."""
        pts = [(0.0, 0.0), (5.0, 10.0), (10.0, 0.0)]
        result = catmull_rom_spline(pts, num_segments=5)
        self.assertAlmostEqual(result[0][0], 0.0)
        self.assertAlmostEqual(result[0][1], 0.0)
        self.assertAlmostEqual(result[-1][0], 10.0)
        self.assertAlmostEqual(result[-1][1], 0.0)

    def test_single_point(self):
        """A single control point returns a list with that point."""
        result = catmull_rom_spline([(7, 8)], num_segments=10)
        self.assertEqual(result, [(7, 8)])

    def test_empty_list(self):
        result = catmull_rom_spline([], num_segments=10)
        self.assertEqual(result, [])

    def test_spline_is_smooth(self):
        """Check that interpolated points are monotonic in x for a simple
        rightward curve — a basic sanity check."""
        pts = [(0.0, 0.0), (3.0, 4.0), (6.0, 1.0), (9.0, 5.0)]
        result = catmull_rom_spline(pts, num_segments=10)
        xs = [p[0] for p in result]
        for i in range(1, len(xs)):
            self.assertGreaterEqual(xs[i], xs[i - 1] - 1e-9)


# ─── v2 validation (cli.validate_v2) ───────────────────────────────────────


class TestValidateV2(unittest.TestCase):
    """Ensure validate_v2 rejects old format and accepts v2 payloads."""

    def test_valid_v2_passes(self):
        payload = {
            'format': 'tmm-scene',
            'version': 2,
            'units': 'mm',
            'id': 'x',
            'entities': [],
        }
        self.assertIsNone(validate_v2(payload))

    def test_missing_metadata_defaults_to_v2(self):
        self.assertIsNone(validate_v2({'entities': []}))

    def test_wrong_format_rejected(self):
        payload = {'format': 'other', 'version': 2, 'entities': []}
        err = validate_v2(payload)
        self.assertIsNotNone(err)
        self.assertIn('tmm-scene', err)

    def test_wrong_version_rejected(self):
        payload = {'format': 'tmm-scene', 'version': 1, 'entities': []}
        err = validate_v2(payload)
        self.assertIsNotNone(err)
        self.assertIn('version 2', err)

    def test_scenes_key_rejected(self):
        payload = {
            'format': 'tmm-scene', 'version': 2, 'entities': [],
            'scenes': [{'entities': []}],
        }
        err = validate_v2(payload)
        self.assertIsNotNone(err)
        self.assertIn('scenes', err)

    def test_canvas_key_rejected(self):
        payload = {
            'format': 'tmm-scene', 'version': 2, 'entities': [],
            'canvas': {},
        }
        err = validate_v2(payload)
        self.assertIsNotNone(err)
        self.assertIn('canvas', err)

    def test_missing_entities_rejected(self):
        payload = {'format': 'tmm-scene', 'version': 2}
        err = validate_v2(payload)
        self.assertIsNotNone(err)
        self.assertIn('entities', err)

    def test_entities_must_be_list(self):
        payload = {'format': 'tmm-scene', 'version': 2, 'entities': 'bad'}
        err = validate_v2(payload)
        self.assertIsNotNone(err)
        self.assertIn('list', err)


# ─── build_drawing v2 validation ────────────────────────────────────────────


class TestBuildDrawingV2Validation(unittest.TestCase):
    """build_drawing must reject payloads that are not v2."""

    def test_missing_metadata_defaults_to_v2(self):
        payload = {'entities': []}
        validate_payload_v2(payload)
        self.assertEqual(payload['format'], 'tmm-scene')
        self.assertEqual(payload['version'], 2)

    def test_wrong_format_raises(self):
        with self.assertRaises(ValueError) as ctx:
            build_drawing({'format': 'wrong', 'version': 2, 'entities': []}, 'x.cdw')
        self.assertIn('tmm-scene', str(ctx.exception))

    def test_wrong_version_raises(self):
        with self.assertRaises(ValueError) as ctx:
            build_drawing({'format': 'tmm-scene', 'version': 1, 'entities': []}, 'x.cdw')
        self.assertIn('expected 2', str(ctx.exception))

    def test_scenes_key_raises(self):
        payload = {
            'format': 'tmm-scene', 'version': 2, 'entities': [],
            'scenes': [{'entities': []}],
        }
        with self.assertRaises(ValueError) as ctx:
            build_drawing(payload, 'x.cdw')
        self.assertIn('scenes', str(ctx.exception))

    def test_canvas_key_raises(self):
        payload = {
            'format': 'tmm-scene', 'version': 2, 'entities': [],
            'canvas': {},
        }
        with self.assertRaises(ValueError) as ctx:
            build_drawing(payload, 'x.cdw')
        self.assertIn('canvas', str(ctx.exception))

    def test_missing_entities_raises(self):
        with self.assertRaises(ValueError) as ctx:
            build_drawing({'format': 'tmm-scene', 'version': 2}, 'x.cdw')
        self.assertIn('entities', str(ctx.exception))


# ─── draw_scene_document processes top-level entities ────────────────────────


class TestDrawSceneDocumentEntities(unittest.TestCase):
    """Verify that draw_scene_document iterates top-level entities
    (no scenes[] wrapper) by monkeypatching scene_entity_to_api."""

    @patch('tmm_scene_kompas.render.os.path.exists', return_value=True)
    @patch('tmm_scene_kompas.render.os.makedirs')
    @patch('tmm_scene_kompas.render.connect_kompas')
    @patch('tmm_scene_kompas.render.open_active_view')
    @patch('tmm_scene_kompas.render._ComApartment')
    def test_top_level_entities_called(self, mock_apartment, mock_open, mock_connect, mock_makedirs, mock_exists):
        entities = [
            {'type': 'line', 'from': [0, 0], 'to': [1, 0]},
            {'type': 'circle', 'center': [5, 5], 'radius': 1.0},
        ]
        payload = {
            'format': 'tmm-scene', 'version': 2,
            'entities': entities,
        }

        # Fake KOMPAS objects
        mock_apartment.return_value.__enter__.return_value = mock_apartment.return_value
        fake_doc = MagicMock()
        mock_connect.return_value = (MagicMock(), MagicMock(), MagicMock(), MagicMock())
        mock_connect.return_value[3].Documents.AddWithDefaultSettings.return_value = fake_doc
        mock_open.return_value = (MagicMock(), MagicMock(), MagicMock())
        fake_doc.SaveAs = MagicMock()

        calls = []
        def spy(*args, **kwargs):
            calls.append((args, kwargs))

        with (
            patch('tmm_scene_kompas.render._qi', return_value=MagicMock()),
            patch.object(
                __import__('tmm_scene_kompas.render', fromlist=['scene_entity_to_api']),
                'scene_entity_to_api', side_effect=spy,
            ),
        ):
            output = draw_scene_document(payload, '/tmp/test.cdw')

        # scene_entity_to_api was called once per entity, with no offset
        self.assertEqual(len(calls), 2)
        # Verify the first call received the first entity (no offset kwarg)
        args0, kwargs0 = calls[0]
        self.assertEqual(args0[3], entities[0])
        self.assertEqual(kwargs0.get('offset', (0, 0)), (0, 0))
        args1, kwargs1 = calls[1]
        self.assertEqual(args1[3], entities[1])

    @patch('tmm_scene_kompas.render._ComApartment')
    @patch('tmm_scene_kompas.render.connect_kompas')
    @patch('tmm_scene_kompas.render.open_active_view')
    def test_render_failure_closes_only_the_new_partial_document(self, mock_open, mock_connect, mock_apartment):
        payload = {'format': 'tmm-scene', 'version': 2,
                   'entities': [{'type': 'unknown'}]}
        doc = MagicMock()
        mock_apartment.return_value.__enter__.return_value = mock_apartment.return_value
        app = MagicMock()
        app.Documents.AddWithDefaultSettings.return_value = doc
        mock_connect.return_value = (MagicMock(), MagicMock(), MagicMock(), app)
        mock_open.return_value = (MagicMock(), MagicMock(), MagicMock())
        with (
            patch('tmm_scene_kompas.render._qi', return_value=MagicMock()),
            self.assertRaisesRegex(ValueError, 'Unsupported scene entity'),
        ):
            draw_scene_document(payload, '/tmp/partial.cdw')
        doc.Close.assert_called_once_with(False)

    def test_old_scenes_wrapper_rejected(self):
        payload = {
            'format': 'tmm-scene', 'version': 2,
            'entities': [{'type': 'line', 'from': [0, 0], 'to': [1, 0]}],
            'scenes': [{'entities': [{'type': 'circle', 'center': [0, 0], 'radius': 1}]}],
        }

        with self.assertRaises(ValueError) as ctx:
            draw_scene_document(payload, '/tmp/test.cdw')
        self.assertIn('scenes', str(ctx.exception))


# ─── filled-circle dispatch ─────────────────────────────────────────────────


class _FakeLineSegment:
    def __init__(self):
        self.updated = False

    def Update(self):
        self.updated = True


class _FakeContainerWithLines:
    def __init__(self):
        self.lines = []

    @property
    def LineSegments(self):
        return self

    def Add(self):
        line = _FakeLineSegment()
        self.lines.append(line)
        return line


class TestFilledCircleDispatch(unittest.TestCase):

    def test_filled_circle_is_dense_disk_of_thick_horizontal_chords(self):
        container = _FakeContainerWithLines()
        const = _FakeConst(ksCSNormal=1, ksCSThick=7)
        add_filled_circle(container, const, xc=10.0, yc=20.0, radius=1.0)

        self.assertEqual(len(container.lines), 8)  # 2 mm / 0.25 mm pitch
        for line in container.lines:
            self.assertEqual(line.Style, 7)
            self.assertLessEqual(abs(line.Y1 - 20.0), 1.0)
            self.assertAlmostEqual(line.Y1, line.Y2)
            self.assertLessEqual(line.X1, line.X2)
            self.assertTrue(line.updated)

    def test_filled_circle_entity_uses_disk_not_outline_polyline(self):
        container = _FakeContainerWithLines()
        const = _FakeConst(ksCSNormal=1, ksCSThick=7)
        scene_entity_to_api(MagicMock(), container, const, {
            'type': 'circle', 'center': [10.0, 20.0], 'radius': 1.0,
            'filled': True,
        })
        self.assertEqual(len(container.lines), 8)

    def test_zero_radius_does_not_create_geometry(self):
        container = _FakeContainerWithLines()
        add_filled_circle(container, _FakeConst(), xc=0, yc=0, radius=0)
        self.assertEqual(container.lines, [])


# ─── smoothCurve dispatch ───────────────────────────────────────────────────


class _FakePolyLine:
    """Minimal stand-in for KOMPAS PolyLines2D item."""

    def __init__(self):
        self.Closed = False
        self.points = []
        self.updated = False

    def AddPoint(self, index, x, y):
        self.points.append((index, x, y))
        return True

    def Update(self):
        self.updated = True


class _FakeContainerWithPolyLine:
    """A container that tracks the last added polyline."""

    def __init__(self):
        self._last = None

    @property
    def PolyLines2D(self):
        return self

    def Add(self):
        obj = _FakePolyLine()
        self._last = obj
        return obj


class TestSmoothCurveDispatch(unittest.TestCase):
    """Verify scene_entity_to_api dispatches smoothCurve correctly."""

    def test_smooth_curve_calls_add_polyline(self):
        container = _FakeContainerWithPolyLine()
        const = MagicMock()
        entity = {
            'type': 'smoothCurve',
            'id': 'curve-1',
            'points': [[0, 0], [40, 25], [80, 10], [120, 50]],
            'layer': 'fixed',
            'style': 'solid',
        }
        scene_entity_to_api(MagicMock(), container, const, entity)
        poly = container._last
        self.assertIsNotNone(poly)
        self.assertIsInstance(poly, _FakePolyLine)
        self.assertFalse(poly.Closed)
        # Should produce more than the 4 control points (num_segments=20 for 3 segments = 61 pts)
        self.assertGreater(len(poly.points), 10,
                          'smoothCurve should produce >10 polyline points')

    def test_smooth_curve_degenerate_one_point_skipped(self):
        container = _FakeContainerWithPolyLine()
        const = MagicMock()
        entity = {
            'type': 'smoothCurve',
            'points': [[10, 20]],  # only 1 point — degenerate
        }
        scene_entity_to_api(MagicMock(), container, const, entity)
        self.assertIsNone(container._last,
                          'degenerate smoothCurve should not add a polyline')

    def test_smooth_curve_defaults(self):
        """Verify defaults (style='solid', layer='fixed') are used when omitted."""
        container = _FakeContainerWithPolyLine()
        const = MagicMock()
        entity = {
            'type': 'smoothCurve',
            'points': [[0, 0], [10, 10]],
            # no style, no layer
        }
        scene_entity_to_api(MagicMock(), container, const, entity)
        # Should not raise, polyline should be created
        self.assertIsNotNone(container._last)
        self.assertGreater(len(container._last.points), 2)


# ─── v2 fixture file ────────────────────────────────────────────────────────


FIXTURES_DIR = os.path.join(os.path.dirname(__file__), 'fixtures')


class TestV2Fixture(unittest.TestCase):
    """Ensure the committed v2 fixture is valid JSON and passes validate_v2."""

    def test_fixture_is_valid_v2(self):
        path = os.path.join(FIXTURES_DIR, 'v2-single-scene.json')
        with open(path, 'r', encoding='utf-8') as f:
            payload = json.load(f)
        self.assertIsNone(validate_v2(payload))
        self.assertIsInstance(payload['entities'], list)
        self.assertGreater(len(payload['entities']), 0)
        # Must NOT have scenes or canvas
        self.assertNotIn('scenes', payload)
        self.assertNotIn('canvas', payload)

    def test_super_scene_fixture_declares_a2_sheet(self):
        path = os.path.join(FIXTURES_DIR, 'variant-7-force-page-1.A2.render.json')
        with open(path, 'r', encoding='utf-8') as f:
            payload = json.load(f)
        self.assertIsNone(validate_v2(payload))
        self.assertEqual(payload['kind'], 'super-scene')
        self.assertEqual(payload['sheet']['format'], 'A2')
        self.assertEqual(payload['sheet']['orientation'], 'landscape')
        self.assertTrue(payload['sheet']['titleBlock']['text'])


# ─── Api5Context.add_text_plan ───────────────────────────────────────────────


class TestApi5ContextAddTextPlan(unittest.TestCase):
    """Verify Api5Context.add_text_plan with fake objects."""

    def test_add_text_plan_unavailable_raises(self):
        from tmm_scene_kompas.kompas_text import (
            FontRole, TextItemPlan, TextLinePlan, TextRenderPlan,
        )
        ctx = Api5Context.__new__(Api5Context)
        ctx._kompas = None
        ctx._const = None

        plan = TextRenderPlan(
            lines=[TextLinePlan(items=[
                TextItemPlan(item_type=0, kind="plain",
                             font=FontRole.GOST_TYPE_A, content=""),
            ])],
            height=5.0,
        )
        with self.assertRaises(RuntimeError) as cm:
            ctx.add_text_plan(plan, center_x=0, center_y=0,
                              entity_id="unavail")
        self.assertIn("unavail", str(cm.exception))

    def test_add_text_plan_no_doc_raises(self):
        from tmm_scene_kompas.kompas_text import (
            FontRole, TextItemPlan, TextLinePlan, TextRenderPlan,
        )
        kompas = MagicMock()
        kompas.ActiveDocument2D.return_value = None
        ctx = Api5Context.__new__(Api5Context)
        ctx._kompas = kompas
        ctx._const = MagicMock()

        plan = TextRenderPlan(
            lines=[TextLinePlan(items=[
                TextItemPlan(item_type=0, kind="plain",
                             font=FontRole.GOST_TYPE_A, content="x"),
            ])],
            height=5.0,
        )
        with self.assertRaises(RuntimeError) as cm:
            ctx.add_text_plan(plan, center_x=0, center_y=0,
                              entity_id="nodoc")
        self.assertIn("nodoc", str(cm.exception))

    @patch('tmm_scene_kompas.api5_text.add_api5_text_plan')
    def test_add_text_plan_delegates(self, mock_add):
        from tmm_scene_kompas.kompas_text import (
            FontRole, TextItemPlan, TextLinePlan, TextRenderPlan,
        )
        doc2d = MagicMock()
        doc2d.ksTextEx.return_value = 99
        kompas = MagicMock()
        kompas.ActiveDocument2D.return_value = doc2d

        ctx = Api5Context.__new__(Api5Context)
        ctx._kompas = kompas
        ctx._const = MagicMock()
        ctx._module7 = None

        plan = TextRenderPlan(
            lines=[TextLinePlan(items=[
                TextItemPlan(item_type=0, kind="plain",
                             font=FontRole.GOST_TYPE_A, content="Test"),
            ])],
            height=5.0,
        )
        ctx.add_text_plan(plan, center_x=10, center_y=20,
                          entity_id="text-1")
        mock_add.assert_called_once()
        _, kwargs = mock_add.call_args
        self.assertEqual(kwargs['center_x'], 10)
        self.assertEqual(kwargs['center_y'], 20)
        self.assertEqual(kwargs['entity_id'], 'text-1')


# ─── add_text with latex ─────────────────────────────────────────────────────


class TestAddTextLatex(unittest.TestCase):
    """Verify add_text handles the latex parameter correctly."""

    def test_latex_without_api5_ctx_raises(self):
        """When latex is provided but api5_ctx is None, must raise."""
        with self.assertRaises(RuntimeError) as cm:
            add_text(
                MagicMock(), MagicMock(),
                10, 20, "fallback",
                latex=r"F_{32}^{\\tau}",
            )
        self.assertIn("API5 context", str(cm.exception))

    @patch('tmm_scene_kompas.render.Api5Context.add_text_plan')
    def test_latex_calls_add_text_plan(self, mock_add_text_plan):
        """When latex is provided with api5_ctx, must compile and call add_text_plan."""
        ctx = Api5Context.__new__(Api5Context)
        ctx._kompas = MagicMock()
        ctx._const = MagicMock()
        ctx._module7 = None

        add_text(
            MagicMock(), MagicMock(),
            10, 20, "fallback",
            api5_ctx=ctx,
            latex=r"F_{32}^{\\tau}",
            entity_id="text-ltx",
        )
        mock_add_text_plan.assert_called_once()
        _, kwargs = mock_add_text_plan.call_args
        self.assertEqual(kwargs['center_x'], 10)
        self.assertEqual(kwargs['center_y'], 20)
        self.assertEqual(kwargs['entity_id'], 'text-ltx')


# ─── scene_entity_to_api with latex entity ─────────────────────────────────


class TestSceneEntityToApiLatexText(unittest.TestCase):
    """Verify scene_entity_to_api dispatches latex entity correctly."""

    @patch('tmm_scene_kompas.render.Api5Context.add_text_plan')
    def test_latex_entity_calls_api5_path(self, mock_add_text_plan):
        """An entity with 'latex' field triggers API5 path."""
        ctx = Api5Context.__new__(Api5Context)
        ctx._kompas = MagicMock()
        ctx._const = MagicMock()
        ctx._module7 = None

        entity = {
            'type': 'text',
            'id': 'latex-text',
            'text': 'F tau',
            'latex': r'F_{32}^{\\tau}',
            'position': [50, 100],
            'fontSize': 5.0,
        }
        scene_entity_to_api(
            MagicMock(), MagicMock(), MagicMock(),
            entity, api5_ctx=ctx,
        )
        mock_add_text_plan.assert_called_once()

    def test_plain_text_no_latex_does_not_call_api5(self):
        """An entity without 'latex' must NOT use API5."""
        ctx = Api5Context.__new__(Api5Context)
        ctx._kompas = MagicMock()
        ctx._const = MagicMock()

        # We'll just verify no RuntimeError is raised (plain path succeeds
        # or fails on API7, not API5).  Use a mock container where
        # DrawingTexts.Add succeeds.
        fake_dt = MagicMock()
        fake_container = MagicMock()
        fake_container.DrawingTexts.Add.return_value = fake_dt
        mock_module7 = MagicMock()

        entity = {
            'type': 'text',
            'id': 'plain-text',
            'text': 'Hello',
            'position': [25, 50],
            'fontSize': 3.5,
        }
        # Should not raise — plain path is taken. QueryInterface itself is
        # mocked because this test is part of the COM-free Linux suite.
        with patch('tmm_scene_kompas.render._qi', return_value=MagicMock()):
            scene_entity_to_api(
                mock_module7, fake_container, MagicMock(),
                entity, api5_ctx=ctx,
            )
        fake_container.DrawingTexts.Add.assert_called_once()


if __name__ == '__main__':
    unittest.main()
