---
name: tmm-graphics
description: Build, validate, edit, and render TMM mechanism scenes, engineering graphs, Scene v2 sheets, and Markdown pages when a Mathcad calculation needs matching KOMPAS drawings or custom plots.
---

# TMM graphics

Use this skill whenever a calculation has a drawing, graph, force plan,
velocity/acceleration plan, dynamic diagram, or explanatory sheet that must be
opened in KOMPAS. The public CLI is a transport and publication client. It does
not read an XMCD graph and does not invent its samples, labels, units, or
physical meaning. Take the numbers and names from the same XMCD/YAML snapshot
that the drawing documents.

The project and homework sections are described in the public [`WORKFLOW.md`](https://github.com/nickadminroot/tmm-cli/blob/main/WORKFLOW.md). Use
[`mathcad-mechanisms`](../mathcad-mechanisms/SKILL.md) for XMCD authoring and
editing, [`tmm-yaml`](../tmm-yaml/SKILL.md) for the physical mechanism, and
[`tmm-cli`](../tmm-cli/SKILL.md) for installation, tokenless commands, and diagnostics.
The detailed scene contracts and examples are in
[`REFERENCE.md`](REFERENCE.md).

## Artifact contract

Keep the calculation, input scenes, resolved scenes, and native drawings as
separate files outside the installed skill directory:

```text
calculation.xmcd                 # source of equations and evaluated values
kinematics.scene.json             # high-level renderer input, authored/edited
kinematics.render.json            # resolved Scene v2 document
kinematics.cdw                    # native KOMPAS output
```

`*.scene.json` is a high-level input. Its `kind` selects a renderer and its
fields describe a mechanism, plan, graph, or diagram. `*.render.json` is the
resolved single-scene document with `format: "tmm-scene"` and `version: 2`.
Never put a `scenes` array or v1 `canvas` in a resolved file. A resolved file
may be edited for presentation, but preserve its entities, units, and semantic
labels; it is not a replacement for the XMCD calculation.

## Working loop

1. Pick the authoritative XMCD/YAML snapshot and write down its pose, units,
   input values, output values, and graph sample data. For **every Mathcad
   graph in the final worksheet**, obtain a finite table of evaluated points
   from native Mathcad or from the same verified Python calculation. Preserve
   the axis ranges and labels, including zero and sign conventions.
2. Reuse a CLI scene when it already expresses the required geometry. Copy it
   to the user's work directory before editing. For a graph or an alpha-stage
   dynamic result, author a new high-level scene from the source data; do not
   embed a screenshot as a substitute for geometry.
3. Validate and resolve a high-level scene:

   ```bash
   tmm resolve "/absolute/work/velocity.scene.json" \
     --output "/absolute/work/velocity.render.json"
   ```

   This public endpoint is tokenless. Exit status `0` and a non-empty
   `.render.json` are required before continuing. For a synchronous Scene v2
   calculation with an explicit scale, `tmm render` uses the same tokenless
   public compute route and accepts one of `--scale` or `--target-max-side`.
4. Make the native KOMPAS drawing from either form:

   ```bash
   # high-level input; the service resolves it and the local Renderer writes CDW
   tmm kompas scene-json "/absolute/work/velocity.scene.json" \
     --target-max-side 200 \
     --output "/absolute/work/velocity.cdw"

   # already resolved Scene v2 input; no scale flag is accepted here
   tmm kompas render-json "/absolute/work/velocity.render.json" \
     --output "/absolute/work/velocity.cdw"
   ```

   Both JSON CDW commands are tokenless, but they require the installed local
   KOMPAS Renderer and KOMPAS. They obtain a renderer challenge, verify the
   signed plan, and only then send the plan to the loopback renderer. A JSON
   response or preview is not evidence that a `.cdw` was created.
5. Open the CDW and inspect geometry, text, arrows, dimensions, line weights,
   page scale, and clipping. If anything is wrong, fix the scene or the
   source data, rerun the command, and keep the resulting XMCD/scene/CDW paths
   together. Do not silently round a scene until it no longer agrees with the
   worksheet.

For a quick non-CAD preview, use the CLI's `svg` command on the input accepted
by the installed release and write the preview outside the skill directory.
Use it to inspect layout; the final deliverable for this workflow remains the
native `.cdw` from `kompas scene-json` or `kompas render-json`.

## Coursework project sections

Use only the sections requested by the assignment, in the appropriate order;
this list is not a mandatory sequence.

- **Synthesis:** Record the derivation, constraints, chosen assembly, and
  checks in XMCD with `mathcad-mechanisms`. Python/JSON may be working data,
  but the final handoff is a readable `.xmcd`. Create scenes only after the
  dimensions and pose are settled.
- **Kinematics:** Obtain the native XMCD with `tmm xmcd MODEL.yaml --output
  KINEMATICS.xmcd` or the full artifact tree with `tmm linkage`. Edit and
  recalculate it with `mathcad-mechanisms`. **Every graph present in the final
  XMCD needs a matching graph scene (usually `engineering-graph`) rendered in
  KOMPAS**, separately or on a shared Markdown sheet, including graphs
  originally generated by Mathcad.
- **Dynamics:** The site/CLI dynamics worksheet is alpha material. Read it for
  orientation only, then replace the dynamic derivation with an independent
  XMCD calculation. `dynamic-model` is a compact schematic renderer, not a
  dynamics solver. Build custom `engineering-graph` scenes (or direct Scene v2
  entities) from the independently evaluated curves and render every graph in
  the final XMCD.
- **Analytical kinetostatics:** Keep the edited XMCD and all force schemes,
  vector plans, tables, and graphs on one pose and one set of loads. A scene
  is correct only when its point coordinates, vector directions, labels,
  units, and values describe the same worksheet state. Markdown from the CLI
  supplies explanations; review it after XMCD edits, then render and arrange
  the resulting pages.
- **Gears and cams:** These are not a site/CLI calculation handoff. Derive
  them in XMCD with `mathcad-mechanisms` and author their diagrams/curves as
  custom scenes. The renderer's `gear-meshing` kind is useful only when its
  input contract matches the requested gear study.
## Coursework homework

Homework uses YAML modeling, kinematics and the requested single-position
kinematic and graphical kinetostatic sheets, usually for the first semester.
Use the corresponding CLI scene kinds and Markdown pages with `tmm-yaml` and
`mathcad-mechanisms`. Do not automatically add synthesis, dynamics, analytical
kinetostatics or gear/cam studies from the project sections. The assignment
determines which homework sections are needed and their order. Single-position
sheets usually do not belong in a course project.

## Markdown sheets

For a text-heavy page with scene placements, write one H1, then top-level H2
sections, and place each scene in a standalone directive:

```md
# Кинематический анализ механизма

## План скоростей

Пояснение и формула $v_A = \omega_1 l_{AB}$.

{{tmm-scene name="kinematics/velocity.scene.json"}}
```

Scene names are portable relative paths ending in `.scene.json` or
`.render.json`. Put each local file at that path relative to the Markdown
file's directory. The CLI uploads referenced local scenes with the model and
Markdown; it does not recursively upload the directory. Uploaded scenes take
precedence over generated scenes with the same logical path. If no local file
exists, a reference can still use a scene from the model's generated catalog.
The scene format is validated in both cases; its origin is not restricted to
the catalog. Use [examples/sheet.md](examples/sheet.md) as a local-file example.

Send the model, document, and its referenced scenes to the preview command:

```bash
tmm md "/absolute/work/model.yaml" "/absolute/work/sheet.md" \
  --format A3 \
  --source-path "kinematics/sheet.md" \
  --output "/absolute/work/sheet.preview.zip"

tmm kompas page "/absolute/work/model.yaml" "/absolute/work/sheet.md" \
  --page 1 --format A3 --source-path "kinematics/sheet.md" \
  --output "/absolute/work/sheet.cdw"
```

These Markdown commands use the synchronous public mechanism pipeline. They
do not require an account token, quote, balance reservation, or
`--accept-new-mechanism` flag. The YAML mechanism, Markdown document, options,
and explicitly referenced local scenes are sent to the public CDW plan route;
the returned signed plan is still checked before the local Renderer runs it.

## Completion gate

Finish only when **every graph present in the final Mathcad XMCD** has a
corresponding scene and native CDW, each scene resolves or validates with the
public CLI, and the edited XMCD has been checked separately for static
structure and (when available) native Mathcad recalculation. Report which gates ran; static XMCD
validation does not execute Mathcad, and successful JSON generation does not
prove KOMPAS output.
