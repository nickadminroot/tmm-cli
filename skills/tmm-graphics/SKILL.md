---
name: tmm-graphics
description: Reuse CLI-generated drafts, then edit, validate, compose, and render TMM mechanism scenes, engineering graphs, Scene v2 sheets, and Markdown pages when a Mathcad calculation needs matching KOMPAS drawings or plots.
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

YAML and the CLI do not solve every coursework section and do not replace an
independent Mathcad calculation. They do, however, provide the physical model
and usable draft mechanism scenes. Always obtain those drafts before authoring
graphics: build or repair `mechanism.yaml`, run `tmm linkage`, inspect its scene
catalog, and use the closest generated scene as the starting point.

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

1. Before producing graphics, visually inspect **every** bundled reference page
   in [`assets/scans/`](assets/scans/) (`page_157.jpg` through
   `page_169.jpg`) with an image-viewing tool. Pages 157–158 describe the
   expected coursework sheets; pages 159–169 show complete layouts. Use them
   to understand the required density, composition, labels, graphs, tables,
   line hierarchy, and title blocks. Merely listing the files or extracting
   text does not satisfy this step.
2. Pick the authoritative XMCD/YAML snapshot and write down its pose, units,
   input values, output values, and graph sample data. For **every Mathcad
   graph in the final worksheet**, obtain a finite table of evaluated points
   from native Mathcad or from the same verified Python calculation. Preserve
   the axis ranges and labels, including zero and sign conventions.
3. Run `tmm linkage MODEL.yaml --output DIR`, inspect all generated
   `.scene.json` and `.render.json` files, and copy the closest scene to the
   user's work directory. Edit that copy for the required pose, values,
   annotations, and layout. If the catalog has no suitable scene, adapt another
   CLI mechanism draft before considering a new scene. Author a new high-level
   scene only as a last resort after recording which generated scenes were
   inspected and why none can represent the required graphic. Never hand-author
   an SVG illustration.
4. Validate and resolve a high-level scene:

   ```bash
   tmm resolve "/absolute/work/velocity.scene.json" \
     --output "/absolute/work/velocity.render.json"
   ```

   This public endpoint is tokenless. Exit status `0` and a non-empty
   `.render.json` are required before continuing. For a synchronous Scene v2
   calculation with an explicit scale, `tmm render` uses the same tokenless
   public compute route and accepts one of `--scale` or `--target-max-side`.
5. Make the native KOMPAS drawing from either form:

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
   response or preview is not evidence that a `.cdw` was created. If the
   renderer is unavailable, follow the installation and verification section in
   [`tmm-cli`](../tmm-cli/SKILL.md) before retrying the final CDW step.
6. Open the CDW and inspect geometry, text, arrows, dimensions, line weights,
   page scale, and clipping. If anything is wrong, fix the scene or the
   source data, rerun the command, and keep the resulting XMCD/scene/CDW paths
   together. Do not silently round a scene until it no longer agrees with the
   worksheet.

When a quick non-CAD preview is necessary, let the CLI generate it from the
scene and keep it as temporary inspection evidence outside the skill directory.
Do not draw or deliver an agent-authored SVG unless the user explicitly asks
for SVG. The graphics deliverable for this workflow is the native `.cdw` from
`kompas scene-json` or `kompas render-json`.

## Required contents of coursework sheets

Page 157 of the bundled reference defines the graphic part as a system of
project sheets rather than a loose collection of pictures. Preserve the order
of schemes and diagrams imposed by the solution algorithm, use consistent
scales and explanatory text, and prepare the sheets under the applicable ESKD
rules, including the cited kinematic-scheme and diagram conventions. Treat the
reference as a composition target; verify the standards against the current
assignment when formal compliance matters.

For the **first sheet**, which explains determination of the law of motion,
include the applicable items below.

- In steady motion: the mechanism kinematic scheme at an arbitrary pose and
  position plans at the initial and final output-link poses; indicator diagrams
  for piston machines or diagrams of external forces and moments; analogues of
  point velocities and link angular velocities; reduced force moments for each
  load and their sum; reduced inertia moments for each component and their sum;
  work of the resistance force, driving force, and total work; second-group
  kinetic energy, commonly combined with the reduced inertia-moment diagram;
  total work and the first-group kinetic-energy change on one diagram; and the
  generalized angular velocity and acceleration.
- In unsteady motion: the corresponding mechanism and position plans,
  indicator/external-load diagrams, velocity analogues, reduced force and
  inertia moments, and total-work diagram; then generalized velocity versus
  generalized coordinate, time versus generalized coordinate, generalized
  velocity versus time, and generalized acceleration versus coordinate and
  time.

For the **second sheet**, which explains the kinetostatic force calculation,
include the mechanism scheme at the calculated pose with the accepted scale
when the method is graphical, or at an arbitrary pose for a numerical method;
velocity and acceleration plans with their scales; the calculation algorithm
and formula, including Assur-group schemes with external and inertia loads and
the necessary equilibrium equations; vector force diagrams with scale when the
vector equations are solved graphically; and a results table with force and
moment magnitudes plus force-vector angles from the horizontal x-axis. For a
numerical calculation, add force diagrams and hodographs over the machine cycle
when the assignment requires them.

The same page begins the **third sheet** as the place for kinematic schemes of
gear trains and meshings plus the diagrams and graphs used in the synthesis of
involute gearing, a gear train, a mechanism drawn with an instrument, or a
planetary mechanism. Continue its exact contents from the assignment and the
following reference page rather than inventing missing requirements.

## Coursework project sections

Use only the sections requested by the assignment, in the appropriate order;
this list is not a mandatory sequence.

- **Synthesis:** Record the derivation, constraints, chosen assembly, and
  checks in XMCD with `mathcad-mechanisms`. Python/JSON may be working data,
  but the final handoff is a readable `.xmcd`. After the dimensions and pose
  are settled, obtain the CLI scene drafts before editing or extending them.
- **Kinematics:** Obtain the native XMCD with `tmm xmcd MODEL.yaml --output
  KINEMATICS.xmcd` or the full artifact tree with `tmm linkage`. Edit and
  recalculate it with `mathcad-mechanisms`. **Every graph present in the final
  XMCD needs a matching graph scene (usually `engineering-graph`) rendered in
  KOMPAS**, separately or on a shared Markdown sheet, including graphs
  originally generated by Mathcad.
- **Dynamics:** The site/CLI dynamics worksheet is alpha material. Read it for
  orientation only, then replace the dynamic derivation with an independent
  XMCD calculation. `dynamic-model` is a compact schematic renderer, not a
  dynamics solver. First reuse the CLI mechanism drafts. When the CLI catalog
  cannot express an independently evaluated curve, create the missing
  `engineering-graph` high-level scene as the documented last resort and render
  every graph in the final XMCD.
- **Analytical kinetostatics:** Keep the edited XMCD and all force schemes,
  vector plans, tables, and graphs on one pose and one set of loads. A scene
  is correct only when its point coordinates, vector directions, labels,
  units, and values describe the same worksheet state. Markdown from the CLI
  supplies explanations; review it after XMCD edits, then render and arrange
  the resulting pages.
- **Gears and cams:** These are not a site/CLI calculation handoff. Derive
  them in XMCD with `mathcad-mechanisms`. Still use the YAML mechanism and CLI
  drafts for the surrounding mechanism views. Create only the missing
  diagrams/curves as new high-level scenes. The renderer's `gear-meshing` kind
  is useful only when its input contract matches the requested gear study.
## Coursework homework

Homework uses YAML modeling, kinematics and the requested single-position
kinematic and graphical kinetostatic sheets, usually for the first semester.
Use the corresponding CLI scene kinds and Markdown pages with `tmm-yaml` and
`mathcad-mechanisms`. Do not automatically add synthesis, dynamics, analytical
kinetostatics or gear/cam studies from the project sections. The assignment
determines which homework sections are needed and their order. Single-position
sheets usually do not belong in a course project.

## Markdown sheets

Markdown is a working input for the CLI page renderer, not the preferred final
document. Deliver prose and report material as editable `.docx`; prefer DOCX
over both PDF and Markdown. Convert an existing Markdown draft with Pandoc when
available, for example `pandoc report.md -o report.docx`, and visually inspect
the DOCX. Create a PDF only when the user explicitly requests one.

For a text-heavy CLI page with scene placements, write one H1, then top-level H2
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

For a coursework drawing sheet, prepare and validate every referenced scene
first, then compose the sheet in Markdown with `tmm-scene` links. Prefer A1
unless the assignment requires another format. Use `tmm md ... --format A1` to
compile and inspect the composed page, then use `tmm kompas page ... --page N
--format A1` to render it as one native CDW; replace the format in both commands
when required by the assignment. Do not manually assemble or arrange drawing
sheets inside KOMPAS. Fix the source scenes or Markdown layout and regenerate
the sheet through the CLI.

These Markdown commands use the synchronous public mechanism pipeline. They
do not require an account token, quote, balance reservation, or
`--accept-new-mechanism` flag. The YAML mechanism, Markdown document, options,
and explicitly referenced local scenes are sent to the public CDW plan route;
the returned signed plan is still checked before the local Renderer runs it.

## Completion gate

Finish only when **every graph present in the final Mathcad XMCD** has a
corresponding scene and native CDW, each scene resolves or validates with the
public CLI, and the edited XMCD has been checked separately for static
structure and (when available) native Mathcad recalculation. Also report the
generated CLI drafts used, any last-resort scenes and why they were necessary,
and confirmation that pages 157–169 were visually inspected. Static XMCD
validation does not execute Mathcad, and successful JSON generation does not
prove KOMPAS output.
