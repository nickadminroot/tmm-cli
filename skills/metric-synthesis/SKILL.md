---
name: metric-synthesis
description: Derive planar slider-crank, four-bar, or oscillating-cylinder dimensions from stated constraints, then hand the structured result to a physical YAML authoring workflow.
compatibility: Requires uv and Python 3.10 or newer; use the bundled scripts/ runtime without system-site-packages or a private checkout.
---

# Metric synthesis

Use the bundled numerical runtime to solve the inverse geometry problem. This
skill produces dimensions and diagnostic evidence; it does not invent a complete
physical linkage model.

## Procedure

1. Read [REFERENCE.md](REFERENCE.md). Select exactly one supported model. If the
   task is outside the seven listed models, say so instead of forcing a match.
2. If selection is uncertain, save only the user's task text in a temporary UTF-8
   file and run the bundled classifier:

   ```bash
   uv run --locked --project /absolute/path/to/metric-synthesis/scripts \
     python -m msynth.cli classify --text /absolute/path/to/task.txt
   ```

   Classification is a hint. Confirm the model definition and required fields
   yourself.
3. Query the runtime schema before constructing a request:

   ```bash
   uv run --locked --project /absolute/path/to/metric-synthesis/scripts \
     python -m msynth.cli schema <model-id>
   ```

4. Ask for every absent required value. Keep the canonical missing-field
   diagnostic when the request is incomplete. Never replace an absent length,
   angle, pose, branch, drive value, mass, inertia, or load with zero, a fixture
   value, or a guessed default.
5. Write a temporary request JSON using the units and fields actually supplied.
   Run structured JSON output:

   ```bash
   uv run --locked --project /absolute/path/to/metric-synthesis/scripts \
     python -m msynth.cli run \
     --input /absolute/path/to/request.json \
     --output-format json
   ```

   Exit 0 is a valid solution. Exit 3 is invalid, incomplete, or mechanically
   inadmissible input. Exit 2 means the request or invocation must be corrected.
   Exit 1 is an internal runtime failure. Do not continue to YAML after a
   non-success result.
6. Read dimensions from the structured JSON result, never from rounded
   `--output-format final` text. Keep `unknowns`, `derived`, residual, and
   validation together. A dimensionless ratio is not an absolute length.
7. Hand the result to [tmm-yaml](../tmm-yaml/SKILL.md) when that neighboring skill
   is available. Choose one assembly pose and branch. Request all physical data
   that synthesis does not provide: drive `omega`/`alpha`, body mass,
   inertia, center of mass, gravity, external loads, and any required marker
   geometry. Do not pretend that multi-position constraints describe all poses
   in one YAML file.
8. Verify the authored model only with the public CLI:

   ```bash
   tmm linkage /absolute/path/to/model.yaml \
     --output /absolute/path/to/output-dir
   ```

   Report the actual status and artifact paths. If the binary, token, network,
   physical data, pose, or branch is unavailable, stop and name that blocker.
   Do not call an unexecuted YAML “verified”.

## Runtime setup

The install target is the `scripts/` directory inside this skill:

```bash
SKILL_DIR=/absolute/path/to/metric-synthesis
uv sync --locked --project "$SKILL_DIR/scripts"
uv run --locked --project "$SKILL_DIR/scripts" \
  python -m msynth.cli models
```

The command works from any current directory when the project and user paths are
absolute. The runtime writes neither requests nor outputs into the installed
skill directory.

## Output discipline

For a successful synthesis, report the selected model, structured numerical
result, units, residual, validation, and the exact next physical inputs needed
for YAML. For a failure, preserve the runtime's concise diagnostic and ask only
for fields that are actually missing. Never disclose secrets or place them in
JSON, YAML, URLs, command arguments, chat, or logs.
