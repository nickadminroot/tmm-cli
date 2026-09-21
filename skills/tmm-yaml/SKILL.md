---
name: tmm-yaml
description: Author and verify one complete physical planar-linkage YAML model with explicit SI geometry, assembly branches, joints, drive, and physical data.
---

# Physical linkage YAML

Requires a TMM CLI for linkage verification; the skill does not execute a private solver or invent missing physical values.

The current public contract is strict `linkage/v2`: `schema: linkage/v2` is
required, and the CLI does not convert legacy YAML automatically.

Use this skill after numerical synthesis or when the task already supplies a
physical planar mechanism. A YAML file describes one assembly pose and the
physical data needed by the complete `tmm linkage` analysis. It is not a
container for sampled output or renderer settings.

## Procedure

1. Read [REFERENCE.md](REFERENCE.md) and choose the topology supported by the
   actual physical mechanism. Read [metric-synthesis](../metric-synthesis/SKILL.md)
   first when dimensions are being derived; if that neighboring skill is not
   installed, request the numerical dimensions instead of guessing.
2. Collect one pose: fixed points, body lengths, absolute angles, assembly
   branch, aliases, and the selected output body. Convert supplied geometry to
   metres before writing it. Keep `units: SI`; it records the convention and
   does not perform automatic conversion. Start the file with
   `schema: linkage/v2`.
3. Add the physical inputs required by the complete calculation: body `type`
   (`rigid` or `slider`), object-shaped frames, mass, inertia, center of mass,
   drive `omega`/`alpha`, gravity, and loads. A genuinely massless rod may have
   zero mass and inertia, but its frame still needs two distinct points. Ask for
   missing values; never insert educational values into a user's model without
   saying so.
4. Use only physical YAML fields. Do not copy `outputs`, `vectorPlans`,
   `graphs`, `force_reference`, sampled arrays, Mathcad formulas, or debug
   dumps into the input.
5. Save the input outside the installed skill directory and verify it with
   absolute paths:

   ```bash
   tmm linkage "/absolute/path/to/model.yaml" \
     --output "/absolute/path/to/output-dir"
   ```

   Inspect the command exit status and returned artifact paths. A prepared file
   is not verified until this command actually runs. If the CLI, token, network,
   or physical data is unavailable, report the exact blocker and stop.
6. Report the selected pose/branch, input path, verification status, and useful
   artifacts. Keep synthesis provenance separate from YAML fields that were
   supplied or selected by the user.

## Coursework workflow

Use [the coursework sections guide](https://github.com/nickadminroot/tmm-cli/blob/main/WORKFLOW.md)
to distinguish the two assignments. A **course project** may include synthesis,
YAML modeling, kinematics, dynamics, analytical kinetostatics and gear/cam
studies. These are sections, not a mandatory sequence: select and order them
according to the task. Dynamics output from the site/CLI is alpha material
and needs independent work.

**Coursework homework** uses YAML modeling, kinematics, and the requested
single-position kinematic and graphical kinetostatic sheets. Do not add the
other project sections automatically or confuse graphical with analytical
kinetostatics. Use [tmm-graphics](../tmm-graphics/SKILL.md) for drawing formats,
custom plots and Markdown-to-KOMPAS commands. Every graph in the final
Mathcad document needs its matching KOMPAS rendering.

## XMCD handoff

Use [mathcad-mechanisms](../mathcad-mechanisms/SKILL.md) for mechanism methods,
notation and worksheet layout; it includes the `xmcd` authoring library.

The linkage artifact may include a classic Mathcad `.xmcd` worksheet. If an
agent needs to edit that file, use the standalone
[`xmcd` library](https://github.com/nickadminroot/xmcd): load it with
`Worksheet.read(...)`, make typed edits, and save through `Worksheet.write(...)`.
Use its typed editing path or the bundled typed adapter in
`mathcad-mechanisms`; preserve editable formulas instead of rewriting raw XML.

Keep evidence separate. `Worksheet.check()`, `Worksheet.validate()`,
`Worksheet.write(...)`, structural `validate(...)`, and saved-error inspection
are static checks only. Native acceptance requires opening, recalculating, and
saving the worksheet in installed classic Mathcad, followed by inspection of
the saved results, errors, and graphs. A YAML/CLI success or a clean static
XMCD report does not prove native Mathcad recalculation.

## Intermediate drawing files

The linkage result may also contain `.scene.json` and `.render.json`
intermediates. Agents may freely edit those files to improve or repair
presentation—such as labels,
visibility, line weights, or layout—without changing the physical YAML model.
Keep a high-level scene valid for its scene-input contract; keep a resolved
`.render.json` valid Scene v2 JSON. Render the edited file with the tokenless
`tmm kompas render-json INPUT.render.json --output OUTPUT.cdw` command. For a
high-level scene that has not yet been resolved, use `tmm resolve` first or
`tmm kompas scene-json` directly. These commands do not quote or charge a
mechanism, but native CDW output still requires the local KOMPAS Renderer.

## Shape and branches

- Use `geometry.points` for fixed coordinates and `geometry.construct` for
  derived points.
- Use quoted body IDs such as `"1"`; `ground` is the fixed body.
- Use `geometry.aliases` when two semantic labels refer to one point.
- Use explicit `circle_circle`, `circle_line_y`, `circle_line_x`, or
  `circle_ray` branches when two intersections are possible.
- A `prismatic` is a constrained lower pair with separate `guide` and `slider`
  roles. The slider body must have `type: slider`; legacy `slot`, `pin`,
  `normal_axis`, and `axis_points` fields are not accepted by the v2 parser.
- Multi-position synthesis constraints select one pose for this YAML. Do not
  duplicate one physical body for every numerical position.

Examples in [examples/](examples/) are complete models, not output archives.
The root files are small metric-synthesis handoff examples; the
[tmm-web corpus](examples/tmm-web/) and
[linkage-once corpus](examples/linkage-once/) are source snapshots of the
working mechanism inventories. They use explicit values so their structure can
be inspected before a real user model is authored. Treat every copied model as
a starting point: if you change it, verify the changed file with the public
CLI and preserve the selected pose and branch.
