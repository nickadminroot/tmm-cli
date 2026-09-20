from __future__ import annotations

import math

import pytest

from msynth.models import MODELS, _fourbar_validation, render, schema, solve


def test_every_model_reports_all_required_inputs_without_exception() -> None:
    for model, spec in MODELS.items():
        expected = [name for name, field in spec.inputs.items() if field["required"]]
        result = solve(model, {"inputs": {}})
        assert result["status"] == "invalid"
        assert result["error_code"] == "missing_inputs"
        assert result["missing_inputs"] == expected


def test_missing_inputs_are_reported_together() -> None:
    result = solve(
        "fourbar.two_extreme_positions",
        {"inputs": {"X_D": 0.8, "l_3": 0.5}},
    )

    assert result["status"] == "invalid"
    assert result["error_code"] == "missing_inputs"
    assert result["missing_inputs"] == ["Y_D", "gamma_H", "gamma_K"]


def test_runtime_schema_advertises_only_relevant_units_and_defaults() -> None:
    mean_schema = schema("slider_crank.mean_velocity")
    pressure_schema = schema("slider_crank.pressure_angle")
    cylinder_schema = schema("oscillating_cylinder.fixed_y_theta_k")

    assert set(mean_schema["units"]) == {"length", "frequency"}
    assert set(pressure_schema["units"]) == {"length", "angle"}
    assert pressure_schema["inputs"]["lambda_e"]["default"] == 0.0
    assert cylinder_schema["inputs"]["l_sh"]["default"] == "1.3 * h_max"


def test_mean_velocity_accepts_rpm_and_converts_to_per_second() -> None:
    payload = {
        "units": {"frequency": "rpm"},
        "inputs": {"v_cp": 5.0, "n_1": 1300.0, "lambda_2": 3.8},
    }

    result = solve("slider_crank.mean_velocity", payload)

    assert result["status"] == "ok"
    assert result["solution"]["derived"]["n_1_hz"] == pytest.approx(1300 / 60)
    assert result["solution"]["derived"]["H"] == pytest.approx(5 / (2 * (1300 / 60)))
    assert result["solution"]["unknowns"]["l_1"] == pytest.approx(5 / (4 * (1300 / 60)))


@pytest.mark.parametrize(
    "inputs,error_fragment",
    [
        ({"v_cp": 1.0, "n_1": 0.0, "lambda_2": 3.0}, "n_1"),
        ({"v_cp": -1.0, "n_1": 5.0, "lambda_2": 3.0}, "v_cp"),
        ({"v_cp": 1.0, "n_1": 5.0, "lambda_2": 0.0}, "lambda_2"),
    ],
)
def test_mean_velocity_rejects_nonpositive_inputs(inputs: dict[str, float], error_fragment: str) -> None:
    result = solve("slider_crank.mean_velocity", {"inputs": inputs})

    assert result["status"] == "invalid"
    assert error_fragment in result["error"]


def test_mean_velocity_rejects_finite_inputs_that_overflow_results() -> None:
    result = solve(
        "slider_crank.mean_velocity",
        {"inputs": {"v_cp": 1e308, "n_1": 1e-308, "lambda_2": 3.0}},
    )

    assert result["status"] == "invalid"
    assert result["error_code"] == "numerical_overflow"
    assert "solution" not in result


def test_pressure_angle_uses_dimensionally_consistent_formula() -> None:
    payload = {
        "units": {"angle": "deg"},
        "inputs": {"theta_max": 20.0, "lambda_e": 0.4, "l_1": 0.1},
    }

    result = solve("slider_crank.pressure_angle", payload)

    expected_lambda_2 = (1 + 0.4) / math.sin(math.radians(20))
    assert result["status"] == "ok"
    assert result["solution"]["unknowns"]["lambda_2"] == pytest.approx(expected_lambda_2)
    assert result["solution"]["derived"]["l_2"] == pytest.approx(0.1 * expected_lambda_2)


@pytest.mark.parametrize("theta", [0.0, -1.0, 90.0, 180.0])
def test_pressure_angle_rejects_nonacute_angle(theta: float) -> None:
    result = solve(
        "slider_crank.pressure_angle",
        {"units": {"angle": "deg"}, "inputs": {"theta_max": theta}},
    )

    assert result["status"] == "invalid"
    assert "theta_max" in result["error"]


def test_slider_crank_no_solution_failures_have_stable_contract() -> None:
    asin_failure = solve(
        "slider_crank.two_positions_stroke",
        {
            "units": {"angle": "deg"},
            "inputs": {
                "lambda_2": 0.1,
                "lambda_e": 0.0,
                "phi_1H": 45.0,
                "phi_1K": 135.0,
                "h_C": 0.1,
            },
        },
    )
    degenerate = solve(
        "slider_crank.two_positions_stroke",
        {
            "units": {"angle": "deg"},
            "inputs": {
                "lambda_2": 3.0,
                "lambda_e": 0.0,
                "phi_1H": 60.0,
                "phi_1K": 60.0,
                "h_C": 0.1,
            },
        },
    )

    assert asin_failure["status"] == "no_solution"
    assert asin_failure["error_code"] == "geometry_no_solution"
    assert asin_failure["validation"] == {"asin_arguments_in_range": False}
    assert degenerate["status"] == "no_solution"
    assert degenerate["error_code"] == "degenerate_stroke_equation"
    assert degenerate["validation"] == {"stroke_equation_nondegenerate": False}


def test_fourbar_admissibility_checks_grashof_and_shortest_link() -> None:
    admissible = _fourbar_validation(l0=1.0, l1=0.2, l2=0.7, l3=0.6)
    non_grashof = _fourbar_validation(l0=1.0, l1=0.2, l2=0.5, l3=0.4)
    wrong_shortest = _fourbar_validation(l0=0.1, l1=0.2, l2=0.5, l3=0.5)

    assert admissible["crank_rotatability_condition"]
    assert not non_grashof["grashof_strict"]
    assert not non_grashof["crank_rotatability_condition"]
    assert wrong_shortest["grashof_strict"]
    assert not wrong_shortest["shortest_link_is_l1"]
    assert not wrong_shortest["crank_rotatability_condition"]


def test_nonrotatable_slider_crank_is_invalid() -> None:
    result = solve(
        "slider_crank.two_positions_stroke",
        {
            "units": {"angle": "deg"},
            "inputs": {
                "lambda_2": 0.5,
                "lambda_e": 0.0,
                "phi_1H": 0.0,
                "phi_1K": 150.0,
                "h_C": 0.1,
            },
        },
    )

    assert result["status"] == "invalid"
    assert not result["validation"]["crank_rotatability_condition"]
    rendered = render("slider_crank.two_positions_stroke", {}, result)
    assert "проворачиваемости" in rendered["short_explanation"]


def test_speed_ratio_rejects_nonpositive_value_without_exception() -> None:
    result = solve(
        "fourbar.two_extreme_positions_speed_ratio",
        {
            "units": {"angle": "deg"},
            "inputs": {
                "Y_D": -0.1,
                "l_3": 0.5,
                "K_omega": -1.0,
                "gamma_H": 50.0,
                "gamma_K": 110.0,
            },
        },
    )

    assert result["status"] == "invalid"
    assert "K_omega" in result["error"]


def test_malformed_units_are_invalid_without_exception() -> None:
    result = solve(
        "slider_crank.pressure_angle",
        {"units": {"angle": 3}, "inputs": {"theta_max": 0.3}},
    )

    assert result["status"] == "invalid"
    assert result["error_code"] == "invalid_input"
    assert "strings" in result["error"]


def test_oscillating_cylinder_scales_search_to_large_valid_geometry() -> None:
    result = solve(
        "oscillating_cylinder.fixed_y_theta_k",
        {
            "units": {"angle": "rad"},
            "inputs": {
                "h_min": 0.059608966,
                "h_max": 0.3,
                "beta": 0.003005475,
                "theta_K": 0.5,
                "Y_D": 75.24076927,
                "l_sh": 0.39,
            },
        },
    )

    assert result["status"] == "ok"
    assert result["solution"]["unknowns"]["l_1"] == pytest.approx(100.0, abs=1e-4)
    assert result["solution"]["unknowns"]["X_D"] == pytest.approx(65.36928, abs=1e-4)
    assert result["solution"]["residual_norm"] < 1e-8


def test_radian_input_is_rendered_in_radians() -> None:
    payload = {
        "units": {"angle": "rad"},
        "inputs": {"theta_max": 0.35, "lambda_e": 0.0},
    }
    result = solve("slider_crank.pressure_angle", payload)
    rendered = render("slider_crank.pressure_angle", payload, result)

    assert "theta_max := 0.35 rad" in rendered["mathcad_text"]
    assert " deg" not in rendered["mathcad_text"]
