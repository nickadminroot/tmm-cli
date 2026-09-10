from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from msynth.models import render, solve

ROOT = Path(__file__).resolve().parents[1]

REFERENCE_SOLUTIONS: dict[str, dict[str, float]] = {
    "p1_1_slider_crank_two_positions.json": {
        "unknowns.l_1": 0.11327540717342367,
        "unknowns.phi_2H": -0.18750698721885295,
        "unknowns.phi_2K": -0.04001067435398889,
        "unknowns.X_CH": 0.33486249619010683,
        "derived.l_2": 0.2831885179335592,
        "derived.e": 0.04531016286936947,
    },
    "p1_2_fourbar_two_extreme.json": {
        "unknowns.l_1": 0.24151703160264398,
        "unknowns.l_2": 0.7975435309161845,
        "unknowns.phi_1H": 0.36392293697823974,
        "unknowns.theta": 0.17010958844091473,
    },
    "p1_3_fourbar_speed_ratio.json": {
        "unknowns.l_1": 0.2133035246629855,
        "unknowns.l_2": 0.9407115700068734,
        "unknowns.phi_1H": 0.24777757719079352,
        "unknowns.X_D": 0.7973775126427549,
        "derived.theta": 0.2855993321445266,
    },
    "p1_4_fourbar_three_positions.json": {
        "unknowns.l_1": 0.235510661055376,
        "unknowns.l_2": 0.5385786040132193,
        "unknowns.phi_1H": 0.7205806646645385,
        "unknowns.phi_21": 0.40953227912216894,
        "unknowns.phi_22": 0.3198534787140743,
        "unknowns.phi_23": 0.4983990397934437,
    },
    "p1_5_oscillating_cylinder_v1.json": {
        "unknowns.X_D": 0.5074306673752904,
        "unknowns.l_1": 0.27702975280442843,
        "unknowns.phi_1": 1.1377263110134033,
        "unknowns.phi_3H": 2.666015215689564,
        "unknowns.phi_3K": 2.8830555630077335,
        "derived.theta_H": 0.04250742211873604,
    },
    "slider_crank_mean_velocity.json": {
        "unknowns.l_1": 0.0625,
        "derived.H": 0.125,
        "derived.l_2": 0.2,
    },
    "slider_crank_pressure_angle.json": {
        "unknowns.lambda_2": 2.9238044001630876,
        "derived.l_2": 0.29238044001630875,
    },
}


def _nested(mapping: dict[str, Any], dotted_key: str) -> Any:
    value: Any = mapping
    for part in dotted_key.split("."):
        value = value[part]
    return value


@pytest.mark.parametrize("filename", sorted(REFERENCE_SOLUTIONS))
def test_example_matches_reference_solution(filename: str) -> None:
    path = ROOT / "examples" / filename
    payload = json.loads(path.read_text(encoding="utf-8"))

    result = solve(payload["model"], payload)

    assert result["status"] == "ok", (path.name, result)
    if payload["model"].startswith("fourbar."):
        assert result["validation"]["crank_rotatability_condition"]
    for key, expected in REFERENCE_SOLUTIONS[filename].items():
        actual = _nested(result["solution"], key)
        assert actual == pytest.approx(expected, abs=1e-9), (filename, key)
    assert result["solution"]["residual_norm"] < 1e-8

    rendered = render(payload["model"], payload, result)
    assert rendered["mathcad_text"].strip()
    assert rendered["short_explanation"].strip()
    combined = (rendered["mathcad_text"] + rendered["short_explanation"]).lower()
    for forbidden in ("python", "scipy", "traceback", "json", "cli"):
        assert forbidden not in combined
