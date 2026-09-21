---
name: metric-synthesis
description: Derive planar mechanism dimensions in Python or classic Mathcad and document the editable synthesis in XMCD with mathcad-mechanisms, then hand the selected geometry to tmm-yaml.
---

# Metric synthesis

Requires mathcad-mechanisms for XMCD authoring; the optional bundled numerical runtime requires uv and Python 3.10 or newer.

The user-facing result is an editable classic Mathcad `.xmcd`: source data,
equations, chosen assembly, calculation, checks and dimensions. Use
[mathcad-mechanisms](../mathcad-mechanisms/SKILL.md) and its bundled `xmcd`
library to write it. JSON requests and numerical solution dumps are internal
working data, not the synthesis deliverable.

## Procedure

1. Read the task and its diagram. Record the topology, known dimensions,
   constraints, units and required positions. Preserve dimensions already given
   by the user; synthesize only unknowns. Ask for missing constraints rather
   than choosing arbitrary numbers. Read the synthesis generator and relevant
   methods in `mathcad-mechanisms` before authoring the worksheet.
2. Choose the calculation environment. For one of the seven supported numerical
   models, read [REFERENCE.md](REFERENCE.md) and use the bundled Python runtime
   below. For a different problem, derive and solve the actual equations in
   Mathcad or Python using `mathcad-mechanisms`; do not force it into an
   unrelated numerical model.
3. Solve and inspect mechanical admissibility: positive lengths, contour
   residuals in every prescribed position, assembly branch, travel and any
   specified pressure-angle or full-rotation constraint. A converged root alone
   is insufficient. Distinguish a dimensionless ratio from an absolute length.
4. Write the synthesis into the user's XMCD using typed expressions and regions.
   Include the original data and units, assumptions, unknowns, contour equations,
   editable formulas or `Given/Find`, initial guesses/branch, resulting dimensions,
   checks and configuration diagrams. Keep the calculation reproducible inside
   Mathcad: a text summary or a table of frozen Python answers is not a completed
   worksheet. Use Python results as independent checks or solver initial guesses;
   label any externally computed value honestly.
5. Validate through `Worksheet.write(...)` / the skill's adapter. When classic
   Mathcad is available, open, fully recalculate, save and inspect the sheet.
   Report static validation and native recalculation separately. If native
   Mathcad is unavailable, still deliver the XMCD as statically checked and
   explicitly not natively recalculated. If XMCD authoring is unavailable,
   report the missing dependency instead of silently substituting JSON.
6. Hand the accepted dimensions and one chosen pose/branch to
   [tmm-yaml](../tmm-yaml/SKILL.md). Iterate the physical YAML in the web editor
   or with the public CLI; keep the XMCD and YAML geometry consistent. Synthesis
   does not supply masses, inertias, centers of mass, drive or load laws: obtain
   those inputs before claiming the complete physical model is verified.

For the available course-project sections and the separate coursework-homework
scope, read [the coursework guide](https://github.com/nickadminroot/tmm-cli/blob/main/WORKFLOW.md).
Every graph retained in the final Mathcad calculation must also be rendered in
KOMPAS using [tmm-graphics](../tmm-graphics/SKILL.md), with matching source data.

## Optional numerical runtime

The runtime is an independent checking/solving tool. Its supported model schemas
and JSON examples remain useful internally; they do not prescribe the final
user document. Keep temporary request/result files outside installed skills.

```bash
SKILL_DIR="/absolute/path/to/metric-synthesis"
uv sync --locked --project "$SKILL_DIR/scripts"
uv run --locked --project "$SKILL_DIR/scripts" python -m msynth.cli models
uv run --locked --project "$SKILL_DIR/scripts" python -m msynth.cli schema <model-id>
uv run --locked --project "$SKILL_DIR/scripts" python -m msynth.cli run \
  --input "/absolute/path/to/request.json" --output-format json
```

If model selection is unclear, `python -m msynth.cli classify --text TASK.txt`
within the same project offers a hint; confirm its model definition yourself.
Use structured `unknowns`, `derived`, residual and validation at full precision,
not rounded `--output-format final` text. Exit 0 means a valid numerical result;
3 means invalid/incomplete/inadmissible input; 2 means incorrect request or
invocation; 1 means runtime failure. Correct a failed solution before using its
geometry. Do not invent required values or install numerical packages into
system Python. If needed, install uv using its
[official instructions](https://docs.astral.sh/uv/getting-started/installation/).

## Delivery

Link the `.xmcd`, summarize the selected assembly and dimensions with units,
state which checks actually ran, and identify the remaining inputs for YAML.
Numerical diagnostics may accompany the worksheet when useful, but are never
its replacement. Keep secrets out of artifacts and diagnostics.
