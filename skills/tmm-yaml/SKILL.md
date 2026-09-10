---
name: tmm-yaml
description: Author and verify one complete physical planar-linkage YAML model with explicit SI geometry, assembly branches, joints, drive, and physical data.
compatibility: Requires a TMM CLI for linkage verification; the skill does not execute a private solver or invent missing physical values.
---

# Physical linkage YAML

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
   does not perform automatic conversion.
3. Add the physical inputs required by the complete calculation: body frames,
   mass, inertia, center of mass, drive `omega`/`alpha`, gravity, and loads.
   A genuinely massless rod may have zero mass and inertia, but its frame still
   needs two distinct points. Ask for missing values; never insert educational
   values into a user's model without saying so.
4. Use only physical YAML fields. Do not copy `outputs`, `vectorPlans`,
   `graphs`, `force_reference`, sampled arrays, Mathcad formulas, or debug
   dumps into the input.
5. Save the input outside the installed skill directory and verify it with
   absolute paths:

   ```bash
   tmm linkage /absolute/path/to/model.yaml \
     --output /absolute/path/to/output-dir
   ```

   Inspect the command exit status and returned artifact paths. A prepared file
   is not verified until this command actually runs. If the CLI, token, network,
   or physical data is unavailable, report the exact blocker and stop.
6. Report the selected pose/branch, input path, verification status, and useful
   artifacts. Keep synthesis provenance separate from YAML fields that were
   supplied or selected by the user.

## Shape and branches

- Use `geometry.points` for fixed coordinates and `geometry.construct` for
  derived points.
- Use quoted body IDs such as `"1"`; `ground` is the fixed body.
- Use `geometry.aliases` when two semantic labels refer to one point.
- Use explicit `circle_circle`, `circle_line_y`, `circle_line_x`, or
  `circle_ray` branches when two intersections are possible.
- A `slot` is a constrained lower pair. It is not a pin-in-an-unconstrained
  higher pair; `constrain_rotation: false` is rejected.
- Multi-position synthesis constraints select one pose for this YAML. Do not
  duplicate one physical body for every numerical position.

Examples in [examples/](examples/) are complete educational models, not output
archives. They use explicit values so their structure can be inspected before a
real user model is authored.
