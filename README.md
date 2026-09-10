# TMM skills

Portable skills for AI agents working with planar-mechanism tools:

- **tmm-cli** — install and operate the public TMM command-line client without
  putting credentials in prompts, files, or arguments.
- **tmm-yaml** — author one physical linkage YAML model, keep units and branches
  explicit, and verify it with `tmm linkage`.
- **metric-synthesis** — derive mechanism dimensions with the bundled numerical
  runtime, then hand the dimensions to `tmm-yaml` instead of inventing physical
  data.

The intended workflow is:

```text
task constraints
  -> metric-synthesis (numerical dimensions)
  -> tmm-yaml (one physical assembly pose plus physical properties)
  -> tmm linkage (server-side verification and artifacts)
```

These directories are self-contained. Copy a complete skill directory together
with its `REFERENCE.md`, `examples/`, and, for `metric-synthesis`,
`scripts/`. There is no repository-wide installer and no requirement to
install every skill.

## Installation

Use the installation mechanism documented by the AI-agent client you use. The
portable unit is one of:

```text
skills/tmm-cli/
skills/tmm-yaml/
skills/metric-synthesis/
```

The directory layout has been checked with `uv` for the bundled
`metric-synthesis/scripts` runtime. Other clients may use the same files, but
their installation behavior is not verified here.

## Metric-synthesis runtime

The numerical runtime is a standalone Python project under
`skills/metric-synthesis/scripts`. It requires Python 3.10 or newer, `uv`,
NumPy, and SciPy. Install only the bundled project:

```bash
SKILL_DIR=/absolute/path/to/tmm-skills/skills/metric-synthesis
uv sync --locked --project "$SKILL_DIR/scripts"
uv run --locked --project "$SKILL_DIR/scripts" python -m msynth.cli models
```

Run it from any working directory with absolute input paths:

```bash
uv run --locked --project "$SKILL_DIR/scripts" \
  python -m msynth.cli run \
  --input /absolute/path/to/request.json \
  --output-format json
```

The request file and output directory belong to the user. The runtime never
writes task inputs into its installed skill directory.

## Minimal sequence

1. Select one model from `skills/metric-synthesis/REFERENCE.md`.
2. Ask for every missing numerical or physical value; do not use zero or a
   fixture value as a substitute.
3. Run the model and keep the structured JSON result.
4. Choose one assembly pose and write a complete physical YAML with
   `skills/tmm-yaml/REFERENCE.md`.
5. Run `tmm linkage <absolute-model.yaml> --output <absolute-output-dir>`.
6. Report the numerical result, the authored YAML path, and the actual linkage
   status/artifacts. If the CLI, network, token, pose, branch, or physical data
   are unavailable, stop at the corresponding step and say exactly what is
   missing.

A synthesis result proves only the constraints represented by that numerical
model. It does not by itself provide a drive, masses, inertia, center of mass,
loads, assembly branch, or crankability proof for an arbitrary YAML pose.

## Compatibility

The skills are aligned with the TMM CLI and linkage YAML contracts at the
repository revision recorded in each skill reference. The seven supported
synthesis model IDs and their result fields are listed explicitly; no private
checkout, private document, `PYTHONPATH`, system-site-packages, or unpublished
runtime is required.
