# Graphics reference

This is the public reference for the `tmm-graphics` skill. It repeats the
small contracts an agent needs while preparing a drawing, so a user does not
need a private renderer checkout. The released CLI and this skill are the
authorities for commands; use `tmm --help` to confirm flags in the installed
version.

## Pipeline and file names

```text
XMCD/YAML values
      │
      ├── authored high-level *.scene.json ──┐
      │                                      ├─ tmm resolve ── *.render.json
      └── existing CLI scene ────────────────┘          │
                                                       ├─ tmm kompas render-json ── *.cdw
high-level *.scene.json ── tmm kompas scene-json ──────┘
```

The extensions are conventions that make handoff obvious:

| File | Meaning | What may be edited |
| --- | --- | --- |
| `*.scene.json` | High-level input. `kind` selects a renderer; mechanism-family inputs carry `schema: "mechanism/v2"`. | Source geometry, labels, curves, analysis annotations, and layout fields supported by that kind. |
| `*.render.json` | One resolved Scene v2 document. It is the output of `tmm resolve` or `tmm render`. | Entity geometry/style and presentation metadata, while preserving Scene v2 and semantic IDs. |
| `*.cdw` | Native KOMPAS drawing emitted by the installed or portable local Renderer. | Edit in KOMPAS only when the user's drawing workflow requires it; regenerate from JSON after source changes. |

Do not call a high-level input “render JSON”: the renderer has not yet
materialized its entities. Do not use a `.render.json` as a solver or as a
replacement for the equations in XMCD.

## Scene v2 (`*.render.json`)

The resolved root is one object. The minimum is:

```json
{
  "format": "tmm-scene",
  "version": 2,
  "units": "mm",
  "id": "velocity-graph",
  "kind": "engineering-graph",
  "sourcePath": "kinematics/velocity.scene.json",
  "bounds": {
    "low": [0, 0], "high": [160, 100],
    "width": 160, "height": 100
  },
  "metadata": {},
  "entities": []
}
```

Root fields:

- `format` is exactly `"tmm-scene"`; `version` is exactly `2`.
- `units` is `mm`, `cm`, or `m`. Scene geometry is not converted for you;
  choose one unit system and keep every point, radius, width, and label
  placement in it. Renderer-produced scenes normally use `mm`.
- `id` is a non-empty scene identifier; `kind` is a descriptive category.
- `sourcePath`, `bounds`, `metadata`, and `sheet` are optional. `bounds` has
  `low`, `high`, `width`, and `height`; renderer output computes it.
- `sheet`, when present, is `{ "format": "A1"|"A2"|"A3",
  "orientation": "landscape", "titleBlock": {"text": "..."} }`.
- `entities` is an array. IDs should be unique and stable because Markdown
  bindings and review notes may refer to them.

The root must not contain `scenes` or `canvas`. Scene v2 is not a page-set
wrapper; use one document with `sheet` metadata and `textBlock`/`table` entities
for a composed page. Markdown compilation creates a page set from separate
high-level child scenes.

The executable draft-2020-12 schema is bundled at
[`references/tmm-scene-v2.schema.json`](references/tmm-scene-v2.schema.json).
Use it with any JSON Schema validator when the local renderer is unavailable;
the public CLI remains the final producer/consumer check. This copy is pinned
to Scene v2 and should be updated together with the skill when the public
contract changes.

### Entity forms

Every entity has a non-empty `id`. `layer` is one of `fixed`, `thin`, `hatch`,
`label`, or `dimension`; `style` is `solid`, `dashed`, or `dotted` when the
consumer supports it. Required fields are:

| `type` | Required geometry/content | Useful optional fields |
| --- | --- | --- |
| `line` | `from: [x,y]`, `to: [x,y]` | `layer`, `style`, renderer metadata such as `strokeWidth`, `role` |
| `circle` | `center: [x,y]`, `radius >= 0` | `layer`, `style`, `strokeWidth`, `role` |
| `arc` | `center`, `radius >= 0`, `startAngle`, `endAngle` | `layer`, `style`, renderer metadata |
| `polygon` | `points` with at least 3 points | `filled`, `role`, `layer`, `style` |
| `smoothCurve` | `points` with at least 2 points | positive `strokeWidth`, `layer`, `style` |
| `text` | `text`, `position: [x,y]` | non-negative `fontSize`, `italic`, `layer` |
| `textBlock` | `text`, `position`, positive `fontSize`, positive `width` | `italic`, `layer`; use for authored Markdown-like prose |
| `table` | `position`, positive `columnWidths` and `rowHeights`, `cells` | `fontSize`, `italic`, `gridLayer`, `gridStyle` |

A table cell is `{row, column, text}` with optional positive `rowSpan` or
`colSpan`, `fontSize`, `italic`, and `layer`. `text` is plain text with optional
inline `$...$` math. Use `text`, never a legacy `latex` property; block Markdown
does not belong in a cell. Keep geometry finite and provide bounds when
authoring a direct resolved file, even though the schema permits the renderer
to compute them.

The complete public examples are in [`examples/`](examples/). Their numeric
values are deliberately small demonstration fixtures for the file contracts,
not a verified mechanism or dynamics result; replace every point, force, and
curve with values from the user's recalculated XMCD/YAML before delivery.

- [`engineering-graph.scene.json`](examples/engineering-graph.scene.json) is a
  high-level curve scene.
- [`engineering-graph.render.json`](examples/engineering-graph.render.json) is
  a hand-authored Scene v2 document with graph geometry, text, and a table.
- [`dynamic-model.scene.json`](examples/dynamic-model.scene.json) is the
  compact schematic input; it is not a dynamic solver.
- [`dynamics-graph.scene.json`](examples/dynamics-graph.scene.json) shows how
  an independently calculated dynamic curve can be made into an engineering
  graph.
- [`sheet.md`](examples/sheet.md) shows the Markdown scene directive.

The schema intentionally allows renderer metadata on entities
(`additionalProperties: true`) but the required subtype fields above are
closed. Keep the following mechanism skeleton as the smallest useful resolved
mechanism-family input; it contains world points, body-owned points, an R pair,
and a resolved P guide/slider pair:

```json
{
  "schema": "mechanism/v2",
  "kind": "mechanism",
  "units": "SI",
  "points": {"O": [0, 0], "A": [1, 0], "E": [2, 0]},
  "bodies": {
    "1": {"type": "rigid", "points": ["O", "A"], "com": [0.5, 0]},
    "2": {"type": "slider", "points": ["E"], "com": [2, 0]}
  },
  "joints": [
    {"id": "O", "type": "revolute", "endpoints": [
      {"body": "ground", "point": "O"}, {"body": "1", "point": "O"}
    ]},
    {"id": "P", "type": "prismatic",
      "guide": {"body": "ground", "axis": {"origin": [0, 0], "direction": [1, 0]}},
      "slider": {"body": "2", "point": "E"}}
  ]
}
```

Force drawings carry resolved applications, for example:

```json
{
  "schema": "mechanism/v2",
  "kind": "force-calculation",
  "points": {"E": [2, 0]},
  "joints": [{"id": "P", "type": "prismatic",
    "guide": {"body": "ground", "axis": {"origin": [0, 0], "direction": [1, 0]}},
    "slider": {"body": "2", "point": "E"}}],
  "analysis": {"loads": [{"id": "F", "body": "2", "point": "E", "F_xy": [10, 0]}]}
}
```

A hodograph uses angle/length vectors and lets the renderer create the
endpoint curve and selected arrow annotations:

```json
{
  "kind": "hodograph",
  "id": "velocity-hodograph",
  "title": "Velocity hodograph",
  "unit": "m/s",
  "vectors": [
    {"angle": 0, "length": 30},
    {"angle": 45, "length": 42},
    {"angle": 90, "length": 15}
  ]
}
```

## High-level scene kinds (`*.scene.json`)

The CLI dispatches the following kinds. Required fields below are the routing
minimum; read the kind's existing example in a generated artifact before
adding analysis-specific fields.

| `kind` | Required or defining fields | Use |
| --- | --- | --- |
| `mechanism` | `schema: "mechanism/v2"`, `points`, `joints`; optional resolved `bodies`, `drive`, `dimensions`, `outputs` | One mechanism pose. R joints have two body-qualified `endpoints`; P joints have a resolved `guide.axis` and `slider.body/point`. |
| `mechanism-extreme-positions` | `schema`, base mechanism fields, `extreme_positions` with exactly two complete snapshots | Base pose plus prime/double-prime overlays. The renderer does not solve extrema. |
| `calculation-schematic` | `schema`, `points`, `joints`, `bodies`, `calculation_schematic` | Geometry plus semantic axes/angle/coordinate/segment/radius annotations. |
| `force-calculation` | `schema`, `points`, `joints`; optional `bodies`, resolved `analysis` | Loads, gravity, inertia, and drives already resolved by the producer. It does not solve equilibrium. |
| `isolated-force-calculation` | `schema`, `points`, `joints`, `step` (usually with `system_bodies`) | One isolated-body/group free-body scheme. The step selects the displayed subsystem. |
| `dynamic-model` | `type` (`translational` or `rotational`) | Compact symbolic dynamic diagram; fields for labels include `coordinate`/`velocity`/`mass`/`forces` or `angle`/`angular_velocity`/`moment_inertia`/`moments`. |
| `velocity-plan` | `schema`, mechanism data, `analysis.kinematic_plans.velocity` | Resolved velocity vector plan. |
| `acceleration-plan` | `schema`, mechanism data, `analysis.kinematic_plans.acceleration` | Resolved acceleration vector plan. |
| `force-plan` | `schema`, mechanism data, `analysis.groups` with exactly one group | One force-plan sheet per input; split multiple groups into separate files. |
| `engineering-graph` | `horizontalAxis.divisions`, `verticalAxis.divisions` (each at least two) | XY graph for Mathcad samples. Curves use points, labels, and line styles. |
| `gear-meshing` | `z1`, `z2`, `m`; optional `α`, `β`, `x1`, `x2`, `haStar`, `cStar`, `rhoFStar` | Supported gear geometry when its contract matches the study. |
| `hodograph` | non-empty `title`, `unit`, `vectors` (`angle`, `length`); optional `breaks` | Vector-endpoint hodograph. |
| custom vector | an otherwise unknown `kind` plus named `points`; optional `vectors`, `pointLabels`, `guides`, `angles` | A simple custom vector plan. Use the exact field shapes shown below. |

Mechanism-family inputs use producer-resolved world coordinates and strict
`mechanism/v2` data. A body frame, slot/normal-axis witness, guide datum as a
material point, or non-unit P direction is not a renderer input. Keep that
resolution in the YAML/analysis producer.

### Scale selection

`--scale` is a positive millimetres-per-input-unit factor. `--target-max-side`
asks the CLI to probe bounds and choose a nice scale. They are mutually
exclusive. With neither flag, `tmm resolve` uses the service's default-target
path; an already resolved `.render.json` has no scale request.

| Kind family | Default target max side |
| --- | ---: |
| mechanism, extremes, schematic, force, isolated force | 200 mm |
| velocity/acceleration plan | 300 mm |
| force plan | 100 mm |
| dynamic model | 50 mm (fixed 50 × 50 mm symbol) |
| engineering graph, gear meshing | 160 mm |
| hodograph | renderer default; use an explicit target when the sheet requires one |
| custom vector | 300 mm |

An explicit scale changes layout metadata and geometry scale; it does not
change the values or units used by XMCD.

## Authoring graphs from Mathcad

Use one graph scene per worksheet graph. Before writing JSON, make a small
source table containing:

```text
graph id | x symbol/unit | y symbol/unit | x range | y range | samples | source region
```

Copy evaluated sample pairs, not pixels read from a screenshot. Use the same
decimal values that the worksheet displays or a documented precision from the
native recalculation. Put physical units into the axis labels, for example
`"φ, °"`, `"s, mm"`, `"M, Н·м"`; keep the numeric `value` fields unitless in
the graph coordinate system. If Mathcad uses metres or radians, either graph
those values directly and label them, or convert every point deliberately and
record the conversion in the XMCD prose. Never mix a converted axis with raw
curve samples.

The engineering graph input is:

```json
{
  "kind": "engineering-graph",
  "id": "position-graph",
  "title": "s = f(φ)",
  "plotArea": {"width": 180, "height": 90},
  "horizontalAxis": {
    "label": "φ, °",
    "divisions": [
      {"value": 0, "label": "0°"},
      {"value": 180, "label": "180°"},
      {"value": 360, "label": "360°"}
    ]
  },
  "verticalAxis": {
    "label": "s, mm",
    "divisions": [
      {"value": 0, "label": "0"},
      {"value": 60, "label": "60"},
      {"value": 120, "label": "120"}
    ]
  },
  "curves": [{
    "id": "s-phi", "label": "s(φ)", "lineType": "main",
    "strokeWidth": 0.7,
    "points": [[0, 0], [90, 58], [180, 100], [270, 58], [360, 0]]
  }]
}
```

`curves[].points` may be `[x,y]` arrays or `{x,y}` objects. Every point must
be finite and within the corresponding division ranges. Division values are
distinct and each axis spans a non-zero range. Supported `lineType` values are
`main`, `thin`, `solid`, `dashed`, `dash-dot`, and `dotted`; leaders are
optimizer-owned and must not be authored in the graph input.

For a custom vector plan, keep the point names and vector endpoints explicit:

```json
{
  "kind": "my-force-plan",
  "id": "force-construction",
  "points": {"p": [0, 0], "f1": [40, 0], "f2": [25, 30]},
  "pointLabels": {"p": "P", "f1": "F₁", "f2": "F₂"},
  "vectors": [
    {"id": "F1", "from": "p", "to": "f1", "label": "F₁"},
    {"id": "F2", "from": "f1", "to": "f2", "label": "F₂"}
  ],
  "guides": [{"id": "normal", "through": "f1", "direction": [0, 1], "label": "n"}],
  "angles": [{"id": "phi", "vector": "F1", "label": "φ"}]
}
```

The custom builder scales named points by the chosen render scale. `vectors`
refer to those names; a missing endpoint is an input error. Prefer a named
kind (`engineering-graph`, `velocity-plan`, or `force-plan`) when it conveys
the semantics needed by Markdown bindings or reviewers.

## Kinematics and analytical kinetostatics

`velocity-plan`, `acceleration-plan`, and `force-plan` scenes are resolved
analysis artifacts, not independent calculations. When a CLI result supplies
one, copy it and update only the presentation fields you need. If the XMCD
pose, sign convention, load, or body label changes, regenerate or rebuild the
scene from the same state. Do not leave a graph or plan from a previous pose
beside a new worksheet.

For analytical kinetostatics, keep a short cross-check beside the artifacts:

```text
pose / φ:       XMCD = …        scene = …
point B:        XMCD = …        scene = …
force F21:      XMCD = …        scene = …
unit / sign:    XMCD = …        scene = …
```

Check every force-plan vector, isolated-body reaction, graph sample, and scale
binding against that table. Markdown explanations can remain prose, but after
editing the XMCD they must be reread for stale numbers and rerendered.

## Markdown-to-KOMPAS pages

The Markdown producer accepts exactly one initial H1 and top-level H2 sections.
An entire paragraph must be a scene directive:

```md
# Динамика механизма

## График момента

Пояснение: $M(φ)$ строится по данным из XMCD.

{{tmm-scene name="dynamics/torque.scene.json"}}
```

Names are canonical workspace-relative paths ending in `.scene.json` or
`.render.json`. For a local file, use its path relative to the Markdown
file's directory. `tmm md` and `tmm kompas page` read only files explicitly
referenced by scene directives or graphic bindings, and send a `scenes` JSON
part alongside the existing model, Markdown, and options. Files are uploaded
as JSON objects keyed by their logical paths; local scenes override generated
catalog entries with the same key. A missing local file falls back to the
model's generated catalog; a missing scene in both sources is an error.
Code examples in fences or inline code are not file attachments.

`--source-path` sets the document's logical publication path for either
command; it does not change the local Markdown directory from which files
are read. Keep the same source path for preview and CDW export. Both high-level
scene inputs and resolved Scene v2 documents may be embedded, so custom
Mathcad plots can share a page with Markdown explanations without manual
merging of separate CDW drawings.

An optional
`scale="1.25"` applies only to a high-level scene; resolved Scene v2 documents are already scaled. Inline bindings available in
prose/math are:

```md
{{tmm-scale scene="velocity.scene.json"}}
{{tmm-segment scene="velocity.scene.json" id="plan-segment:absolute:point:B"}}
{{tmm-lever scene="force.scene.json" id="lever:F52@D"}}
```

Use bindings only when the referenced scene emits the corresponding
`metadata.renderScale` or `metadata.graphicMeasurements`; keep them out of
tables, code, links, and headings. The full page grammar is intentionally
small so the KOMPAS layout remains deterministic.

## CLI output and failure gates

| Goal | Command | Token | Local KOMPAS |
| --- | --- | --- | --- |
| Resolve high-level scene to `.render.json` | `tmm resolve INPUT.scene.json --output OUT.render.json` | no | no |
| Compute a high-level Scene v2 result | `tmm render INPUT.scene.json --scale N --output OUT.render.json` | no | no |
| Direct high-level scene to CDW | `tmm kompas scene-json INPUT.scene.json --output OUT.cdw [--scale N\|--target-max-side N]` | no | yes |
| Resolved Scene v2 to CDW | `tmm kompas render-json INPUT.render.json --output OUT.cdw` | no | yes |
| Markdown preview | `tmm md MODEL.yaml DOCUMENT.md --format A1\|A2\|A3 --output OUT.zip` | no | no |
| One Markdown page to CDW | `tmm kompas page MODEL.yaml DOCUMENT.md --page N --format A1\|A2\|A3 --output OUT.cdw` | no | yes |

Keep stdout for the CLI's output path. Read stderr for the stable diagnostic,
stage, field, and exit class. A `6` from the KOMPAS path means server/worker/
Renderer failure; check the Renderer URL and installed-or-portable process
before changing scene data. A successful `tmm resolve` only proves the JSON
contract.

## Public links

- [TMM CLI README](https://github.com/nickadminroot/tmm-cli#readme)
- [Recommended coursework workflow](https://github.com/nickadminroot/tmm-cli/blob/main/WORKFLOW.md)
- [CLI skill](../tmm-cli/SKILL.md)
- [Physical YAML skill](../tmm-yaml/SKILL.md)
- [Metric synthesis skill](../metric-synthesis/SKILL.md)
- [Mathcad mechanisms skill](../mathcad-mechanisms/SKILL.md)
- [Scene v2 JSON Schema](https://github.com/nickadminroot/tmm-cli/blob/main/skills/tmm-graphics/references/tmm-scene-v2.schema.json)
- [TMM CLI releases](https://github.com/nickadminroot/tmm-cli/releases)
