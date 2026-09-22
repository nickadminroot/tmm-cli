# KOMPAS rendering reference

This page documents the KOMPAS adapter's lowering and diagnostic evidence. It
is not the owner of the `tmm-scene` v2 input contract. The shared structural
contract is the [portable v2 JSON Schema](../../skills/tmm-graphics/references/tmm-scene-v2.schema.json),
with maintained public [scene examples](../../skills/tmm-graphics/examples/). The
renderer-neutral `textBlock` and table-cell grammar, corpus, and conservative
metrics snapshots used here are bundled in the
[fixture package](../src/tmm_scene_kompas/fixtures/README.md).

The implementation and regression tests linked below are executable evidence
for this adapter. Fixture, probe, and diagnostic outputs are evidence only;
they are not additional Scene or KOMPAS API owners.

## Adapter-local envelope and sheet handling

The adapter consumes one scene at the JSON document root. Its existing runtime
boundary remains permissive about omitted envelope fields (including its
`format`/`version` defaults) and rejects explicit incompatible values. That is
adapter-local behavior; it does not make the required fields in the shared
schema optional. See [`validate_payload_v2`](../src/tmm_scene_kompas/render.py)
and the adapter tests in [`test_helpers.py`](../tests/test_helpers.py).

A payload with `kind: "super-scene"` and a `sheet` object is lowered to the
physical KOMPAS layout sheet. Entity coordinates stay in the supplied y-up
millimetre coordinate system: the adapter configures the sheet rather than
scaling or re-centering entities. `titleBlock.text` is written to the selected
standard stamp cell (cell 2, `Наименование`, by default).

KOMPAS currently accepts the following sheet values at this adapter boundary:

- formats `A0` through `A5`;
- orientations `portrait` and `landscape`;
- an optional `titleBlock`, including an optional positive `cell` selector.

These A0-A5, portrait, and omitted-envelope behaviors are **adapter-local
extensions**. They do not expand or narrow the canonical shared sheet, which
is documented by the [Scene schema](../../skills/tmm-graphics/references/tmm-scene-v2.schema.json).
The sheet normalization and read-back checks live in
[`render.py`](../src/tmm_scene_kompas/render.py), with focused coverage in
[`test_helpers.py`](../tests/test_helpers.py).

## Table lowering

Use the [shared table entity schema](../../skills/tmm-graphics/references/tmm-scene-v2.schema.json)
and the bundled [table-cell corpus](../src/tmm_scene_kompas/fixtures/table-cell-corpus.v1.json) for
field structure and accepted one-line plain-text/inline-math grammar. The
KOMPAS adapter owns only the lowering of that input into a native drawing table.

Before COM is touched, the adapter compiles each table into a deterministic
plan. In KOMPAS it then:

- creates one editable native `IDrawingTable`/`ITable`, rather than a line and
  text approximation;
- applies explicit column widths and row heights to native cell formats;
- uses `ITableRange.CombineCells()` for `rowSpan`/`colSpan` merges; and
- assigns each compiled control string to the existing native cell `IText.Str`.

The production writer does not create `ITextLine` items, API5 text, or overlay
`DrawingText` objects for table cells. Explicit cell `fontSize`/`italic` values
are applied to native type-0 runs; KOMPAS retains its smaller internal formula
item heights. The installed native defaults provide centered alignment and
horizontal fitting for long one-line cell content without wrapping; the writer
does not write unverified alignment or fit properties. See the lowering in
[`table.py`](../src/tmm_scene_kompas/table.py) and [`render.py`](../src/tmm_scene_kompas/render.py),
with regression coverage in [`test_table.py`](../tests/test_table.py).

Other geometry mappings remain adapter-local as well: a filled `circle` is
rendered as a solid black disk, and Scene `dotted` style is mapped to the
native KOMPAS dash-dot style (distinct from `dashed`).

## Text and textBlock lowering

The bundled [text-block corpus](../src/tmm_scene_kompas/fixtures/text-block-corpus.v1.json)
and [layout envelope](../src/tmm_scene_kompas/fixtures/python-layout-envelope.v1.json)
record the accepted Markdown/TeX profile, source diagnostics, line-breaking
rules, and conservative dimensions. This section records only how this adapter
lowers those plans into KOMPAS objects.

For a single `text` entity, the adapter treats `text` as LaTeX when math syntax
or mathematical Unicode is present; the optional `latex` field remains a
backwards-compatible override. Plain labels use the simpler API7
`DrawingText` path. Mathematical text, mathematical Unicode, and italic text
use editable API5 `ksTextEx` text. KOMPAS-incompatible en/em dashes are
normalized to ASCII hyphen-minus before lowering. See [`render.py`](../src/tmm_scene_kompas/render.py)
and [`kompas_text.py`](../src/tmm_scene_kompas/kompas_text.py).

A `textBlock` is lowered as exactly one editable `DrawingText` through one
API5 `ksTextEx` call. Markdown runs, formulas, and visual lines are compiled
inside that object; there is no raster, clipboard, SVG, or subprocess fallback
in the production backend. API7 document/geometry creation remains a separate
path. The adapter reads the API5 gabarit and uses `ksMoveObj` to correct the
retained reference until its measured y-up top-left matches `position`. A
missing measurement, failed move, or failed verification is an error rather
than a silent fallback. The implementation is in
[`api5_text.py`](../src/tmm_scene_kompas/api5_text.py) and
[`render.py`](../src/tmm_scene_kompas/render.py); parser/layout and lowering
coverage is in [`test_text_block.py`](../tests/test_text_block.py).

The adapter enforces the standard text heights used by the shared metrics
profile. It also preserves the existing style behavior when API5 expands
subscripts, superscripts, or other structured runs; this is KOMPAS lowering,
not a new Scene grammar.

## Capability evidence

The pure parser, layout, and fixture tests are COM-free. They prove source
mapping and diagnostics, deterministic plans, and the one-call textBlock
lowering shape, but they do not prove typography on an installed KOMPAS
version. The committed Python layout envelope is a deterministic COM-free
baseline synchronized with metrics; it is not a live-typography claim. See the
labelled [fixture notes](../src/tmm_scene_kompas/fixtures/README.md) and the
[Python envelope fixture](../src/tmm_scene_kompas/fixtures/python-layout-envelope.v1.json).

[`probe_stage1_capabilities.py`](../tools/probe_stage1_capabilities.py) creates
only a new private drawing and records raw API5/API7 observations under its
selected output directory. Its evidence includes object counts,
document-reference identity, gabarit results, retained-reference movement, and
the probe CDW. A successful stage-1 probe is capability evidence only. Full
live acceptance, visual calibration, and conservative metrics calibration
remain unverified until they are separately run and recorded.
