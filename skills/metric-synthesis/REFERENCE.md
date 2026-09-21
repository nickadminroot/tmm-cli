# Model reference

## Units

Top-level `units` may contain:

- `"angle": "deg"` or `"angle": "rad"`; omitted means radians.
- `"frequency": "s^-1"` or `"frequency": "rpm"`; omitted means inverse seconds.
- `"length": "m"` records the task's length unit. All supplied lengths must use one consistent unit.

An individual angle or frequency may instead be written as `{"value": <number>, "unit": "..."}`.

## Supported models

### `slider_crank.two_positions_stroke`

Use for a slider-crank specified by two crank positions and slider travel.

```json
{
  "model": "slider_crank.two_positions_stroke",
  "units": {"length": "m", "angle": "deg"},
  "inputs": {
    "lambda_2": null,
    "lambda_e": null,
    "phi_1H": null,
    "phi_1K": null,
    "h_C": null
  }
}
```

All five inputs are required. The result is admissible only when the crank rotatability condition is satisfied.

### `slider_crank.mean_velocity`

Use for an axial slider-crank specified by mean slider speed, crank frequency, and relative connecting-rod length.

```json
{
  "model": "slider_crank.mean_velocity",
  "units": {"length": "m", "frequency": "rpm"},
  "inputs": {
    "v_cp": null,
    "n_1": null,
    "lambda_2": null
  }
}
```

All inputs are required and positive. Keep `n_1` in the unit stated by the task; do not convert rpm manually.

### `slider_crank.pressure_angle`

Use to determine the minimum relative connecting-rod length from an allowable acute pressure angle.

```json
{
  "model": "slider_crank.pressure_angle",
  "units": {"length": "m", "angle": "deg"},
  "inputs": {
    "theta_max": null,
    "lambda_e": null,
    "l_1": null
  }
}
```

Only `theta_max` is required. `lambda_e` defaults to zero; `l_1` is optional and enables absolute `l_2` and `e`. The dimensionally consistent relation is `sin(theta_max) = (1 + lambda_e) / lambda_2`.

### `fourbar.two_extreme_positions`

Use for a crank-rocker with known fixed-joint coordinates, rocker length, and two extreme rocker angles.

```json
{
  "model": "fourbar.two_extreme_positions",
  "units": {"length": "m", "angle": "deg"},
  "inputs": {
    "X_D": null,
    "Y_D": null,
    "l_3": null,
    "gamma_H": null,
    "gamma_K": null
  }
}
```

All inputs are required.

### `fourbar.two_extreme_positions_speed_ratio`

Use when `X_D` is unknown and the two extreme rocker positions plus the coefficient of mean angular-speed change are given.

```json
{
  "model": "fourbar.two_extreme_positions_speed_ratio",
  "units": {"length": "m", "angle": "deg"},
  "inputs": {
    "Y_D": null,
    "l_3": null,
    "K_omega": null,
    "gamma_H": null,
    "gamma_K": null
  }
}
```

All inputs are required; `K_omega` must be positive.

### `fourbar.three_positions`

Use for three corresponding rocker positions and two crank-rotation increments.

```json
{
  "model": "fourbar.three_positions",
  "units": {"length": "m", "angle": "deg"},
  "inputs": {
    "X_D": null,
    "Y_D": null,
    "l_3": null,
    "gamma_1": null,
    "gamma_2": null,
    "gamma_3": null,
    "phi_12": null,
    "phi_13": null
  }
}
```

All inputs are required; the two crank increments must be nonzero and distinct.

### `oscillating_cylinder.fixed_y_theta_k`

Use for oscillating-cylinder variant 1 with fixed `Y_D` and prescribed final pressure angle `theta_K`.

```json
{
  "model": "oscillating_cylinder.fixed_y_theta_k",
  "units": {"length": "m", "angle": "deg"},
  "inputs": {
    "h_min": null,
    "h_max": null,
    "beta": null,
    "theta_K": null,
    "Y_D": null,
    "l_sh": null
  }
}
```

The first five inputs are required. `l_sh` is optional and defaults to `1.3 * h_max`.

## Failure handling

- Missing fields: ask for every name in `missing_inputs`, and nothing already supplied.
- `invalid`: repeat the concise violated condition from stdout.
- `no_solution`: state that the supplied data do not produce an admissible mechanism.
- `unknown` classification: compare the task against all seven definitions before declaring it unsupported.


## Result contract

A successful `run --output-format json` result has:

```json
{
  "model": "<model-id>",
  "status": "ok",
  "solution": {
    "unknowns": {},
    "derived": {},
    "residual_norm": 0.0
  },
  "validation": {}
}
```

A non-success result keeps `status` as `invalid` or `no_solution`,
includes a stable `error_code` and `error`, and may include
`missing_inputs`, `validation`, `best_x`, or `best_residual_norm`.
The CLI maps every non-success result to exit code 3.

## Result-to-YAML mapping

The numerical result describes constraints, not a complete physical model. For
each model, use the following mapping and keep the non-representable
multi-position constraints as provenance:

| Model | Numerical fields used for one authored pose | Physical YAML handoff |
| --- | --- | --- |
| `slider_crank.two_positions_stroke` | `unknowns.l_1`, `unknowns.phi_2H`, `unknowns.phi_2K`, `unknowns.X_CH`; `derived.l_2`, `derived.e` | Use the H pose: ground point A, crank point B at `phi_1H`, rod point C from the solved `l_2` at slider ordinate `e`, and a `prismatic` pair with ground as guide and the slider body as slider. The K pose and stroke are synthesis constraints, not simultaneous YAML geometry. |
| `slider_crank.mean_velocity` | `unknowns.l_1`; `derived.H`, `derived.l_2`, `derived.n_1_hz` | Author an axial slider-crank pose with `e=0`. Frequency can inform drive `omega`, but `alpha`, body properties, pose, branch, and loads still require explicit values. |
| `slider_crank.pressure_angle` | `unknowns.lambda_2`; optionally `derived.l_2`, `derived.e` when `l_1` is supplied | `theta_max` alone yields a dimensionless ratio and cannot scale YAML. Require an absolute `l_1`, choose a pose, then author the axial or offset slider-crank. The pressure-angle result does not prove crankability. |
| `fourbar.two_extreme_positions` | `unknowns.l_1`, `unknowns.l_2`, `unknowns.phi_1H`, `unknowns.theta` | Set A=(0,0), D=(X_D,Y_D), construct B at `phi_1H`, and construct C from D with `l_3` and `gamma_H` (or a matching circle branch). Use revolute joints A/B/C/D. |
| `fourbar.two_extreme_positions_speed_ratio` | `unknowns.l_1`, `unknowns.l_2`, `unknowns.phi_1H`, `unknowns.X_D`; `derived.theta` | Use the same four-bar H-pose construction. `gamma_K` and `K_omega` remain synthesis provenance; they are not additional geometry fields in a one-pose YAML. |
| `fourbar.three_positions` | `unknowns.l_1`, `unknowns.l_2`, `unknowns.phi_1H`, `unknowns.phi_21`, `unknowns.phi_22`, `unknowns.phi_23` | Author position 1 only: construct B from A using `phi_1H` and C using `gamma_1`/`l_3` or `phi_21`/`l_2`. Preserve positions 2 and 3 as synthesis provenance, not as duplicate bodies. |
| `oscillating_cylinder.fixed_y_theta_k` | `unknowns.X_D`, `unknowns.l_1`, `unknowns.phi_1`, `unknowns.phi_3H`, `unknowns.phi_3K`; `derived.theta_H`, `derived.theta_K`, `derived.l_sh` | Set ground O/D, choose H or K, construct crank A and the cylinder axis/pin with an explicit nonzero frame marker for any massless rod. The two cylinder poses and stroke are not one YAML pose. |

`pressure_angle` with only `theta_max` is intentionally a valid numerical
answer but an incomplete physical handoff. Request `l_1` before authoring
absolute geometry.

## Physical data checklist

Before invoking `tmm linkage`, the YAML author must have:

- one explicit assembly pose and the selected construction branch;
- SI geometry in metres and the physical fields accepted by the YAML contract;
- body frames, mass, inertia, and center of mass, including an explicit
  nonzero frame marker for a massless rod when coincident points would collapse
  its frame;
- a drive body with `omega` and `alpha` for the complete analysis;
- gravity and external loads, or an explicit decision that `loads: []` is the
  supplied physical model;
- no runtime-only `outputs`, `vectorPlans`, `graphs`, or
  `force_reference` fields.

Do not serialize effective dynamics defaults back into the input YAML.
