# Physical YAML reference

This reference follows the public CLI skills and the
`tmm-linkage-once` 0.1.0 YAML contract. Physical inputs use the strict
`linkage/v2` schema; the CLI rejects missing schemas and does not convert the
legacy slot/body/frame syntax.

## Complete input

A full input describes one physical assembly pose:

```yaml
schema: linkage/v2
units: SI
parameters: {}
geometry:
  points: {}
  construct: []
  aliases: {}
bodies: {}
joints: []
drive: {}
loads: []
gravity: [0.0, -9.81, 0.0]
# dynamics: {}  # optional; omission and an empty block use defaults
```

The top-level `units` value is informational. Geometry is written in metres
for `SI`; the parser does not translate arbitrary length units. Convert input
quantities before authoring and retain the conversion in the task provenance.

## Physical fields

- `parameters` is a numeric or reference-value dictionary used by construction
  steps. References resolve within this YAML.
- `geometry.points` contains fixed `[x, y]` coordinates.
- `geometry.construct` derives points with the supported step types below.
- `geometry.aliases` gives another semantic name to an existing point.
- `bodies` contains moving bodies only. IDs are quoted integers. Every body has
  `type: rigid` or `type: slider`, a complete `points` list, and an object-shaped
  `frame`. Complete analysis also requires `mass`, `inertia`, and `com`.
- `joints` closes the mechanism explicitly.
- `output_body` is an optional physical selector for extrema; it is not a
  runtime output configuration.
- `drive` or `drives` declares the driven body. Complete analysis requires
  `omega` and `alpha`; `q_ratio` is the relation between body angle and the
  generalized coordinate.
- `gravity` is a three-component SI vector. `loads` is an explicit list,
  possibly empty.
- `attached_masses` adds a point mass to an existing body without adding a
  degree of freedom.
- `dynamics` is optional physical analysis configuration. Effective defaults
  remain solver-owned and must not be copied into the input as generated data.

## Geometry construction

Supported steps:

| Type | Required fields and meaning |
| --- | --- |
| `point_on_ray` | `point`, `from`, `length`, `angle_deg`; absolute angle in degrees |
| `circle_line_y` | `point`, `center`, `radius`, `y`, `branch: right\|left` |
| `circle_line_x` | `point`, `center`, `radius`, `x`, `branch: upper\|lower` |
| `circle_circle` | two centers/radii and `branch: upper\|lower\|right\|left\|ccw\|cw` |
| `circle_ray` | circle and ray fields plus `branch: positive\|far_positive\|near\|far` |
| `point_at_angle` | vertex, reference point, length, angle, and side |
| `point_on_line` | endpoints plus `distance` or `fraction` |
| `point_towards` | `from`, `to`, and length |
| `point_offset` | `from`, vector/direction/angle, and length |

A construction branch is part of the physical model. Do not let a renderer or
the solver silently choose a different intersection.

## Bodies, joints, and physical data

```yaml
bodies:
  "1":
    type: rigid
    points: [A, B]
    frame: {origin: A, x_axis: {through: B}}
    mass: 2.0
    inertia: 0.12
    com: mid
  "2":
    type: slider
    points: [C]
    frame: {origin: C}
    mass: 1.0
    inertia: 0.01
    com: C

joints:
  - id: A
    type: revolute
    endpoints:
      - {body: ground, point: A}
      - {body: "1", point: A}
  - id: H
    type: prismatic
    guide:
      body: ground
      axis: {origin: [0.0, 0.0], angle_deg: 0.0}
    slider: {body: "2", point: C}

drive:
  body: "1"
  q_ratio: 1
  omega: 10.0
  alpha: 0.0

gravity: [0.0, -9.81, 0.0]
loads: []
```

A revolute pair has two coincident endpoints. A prismatic pair has separate
`guide` and `slider` roles. The guide axis is a line datum with an `origin` and
the tangent `angle_deg`; the slider role names a point on a body declared with
`type: slider`. The old `slot`, `pin`, `normal_axis`, and `axis_points` fields
are not part of `linkage/v2` and are rejected rather than converted.

Frames must have distinct points. For a massless rod whose meaningful points
coincide, add a declared nonzero marker point and reference it in the frame.
The marker is physical authoring data, not a synthesis result.

## Diagnostics and verification

Parser diagnostics use a stable code/message/field/stage envelope. YAML syntax
errors may include one-based `line` and `column`; semantic errors identify a
JSON-Pointer-like field such as `/bodies/2/mass`. Preserve the field and stage
when asking the user for a correction.

Verify a saved model only as follows:

```bash
tmm linkage "/absolute/path/to/model.yaml" \
  --output "/absolute/path/to/output-dir"
```

Check the exit status, the result status, and the declared output files. Do not
report a YAML as checked because it parsed, because a synthesis result existed,
or because a fixture was copied.

## Forbidden runtime fields

These keys are not physical input and must be rejected:

- `outputs`
- `vectorPlans`
- `graphs`
- `force_reference`

Do not add browser-import limits, sampled traces, output vectors, or renderer
configuration to this YAML.

## Synthesis handoff

A metric-synthesis result supplies only the fields its model solves:

- `slider_crank.two_positions_stroke`: use `l_1`, `l_2`, `e`, and the
  H-pose angle; the K pose and stroke remain provenance.
- `slider_crank.mean_velocity`: use `l_1`, `H`, and `l_2`; frequency
  can inform `omega`, but `alpha`, pose, branch, and physical data remain
  inputs.
- `slider_crank.pressure_angle`: `theta_max` alone gives only
  dimensionless `lambda_2`. Require absolute `l_1` before writing `l_2`
  and geometry; the result does not choose a pose or prove crankability.
- `fourbar.two_extreme_positions`: construct fixed A/D, the H-pose crank from
  `l_1`, `phi_1H`, and the rocker from `l_3`, `gamma_H`; use revolute A/B/C/D.
- `fourbar.two_extreme_positions_speed_ratio`: use solved `X_D`, `l_1`, `l_2`
  for the same H-pose; `gamma_K` and `K_omega` are provenance.
- `fourbar.three_positions`: author position 1 using `l_1`, `l_2`, `phi_1H`
  and `gamma_1` or `phi_21`; preserve positions 2/3 as provenance.
- `oscillating_cylinder.fixed_y_theta_k`: choose H or K, use solved
  `X_D`, `l_1`, `phi_1`, `phi_3H`/`phi_3K`, and author a nonzero frame marker
  for a massless rod.

The result must be combined with an explicit one-pose branch, drive, masses,
inertia, centers of mass, gravity, and loads before linkage verification.

## XMCD editing boundary

For an XMCD artifact returned by `tmm linkage` or `tmm xmcd`, use the standalone
[`xmcd` library](https://github.com/nickadminroot/xmcd) for agent editing and
static validation. `Worksheet.read(...)` loads an existing worksheet;
`Worksheet.write(...)` performs the library's static checks before writing.
Keep this typed library as the only editing path instead of hand-editing XML or
using a local/private ad-hoc generator.

Static checks (`Worksheet.check()`, `Worksheet.validate()`, `Worksheet.write()`,
structural `validate(...)`, and inspection of saved `calculation_errors(...)`)
do not execute Mathcad. Native evidence requires opening, recalculating, and
saving the worksheet in installed classic Mathcad, then checking saved formula
results, errors, and graphs. Report these gates separately; neither YAML
verification nor static XMCD validation proves native recalculation.

## Scene intermediate editing

Generated `.scene.json` and `.render.json` files are presentation
intermediates, not physical YAML. An agent may edit them arbitrarily to improve
or repair drawing presentation. Keep a high-level `.scene.json` valid for its
scene-input contract and a resolved `.render.json` valid Scene v2 JSON. Resolve
a high-level file with `tmm resolve`, then render the edited `.render.json`
with `tmm kompas render-json`; both arbitrary JSON CDW paths are tokenless and
do not affect mechanism balance or registry admission. Native CDW output still
requires the local KOMPAS Renderer.
