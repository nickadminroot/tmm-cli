from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np

from .solver import solve_global_then_local, solve_multistart
from .util import (
    DEG,
    as_jsonable,
    canonical_angle_unit,
    canonical_frequency_unit,
    fmt_angle_deg,
    fmt_float,
    input_angle,
    input_float,
    input_frequency,
    normalize_angle,
    rad_to_deg,
)


@dataclass
class ModelSpec:
    name: str
    title: str
    inputs: dict[str, dict[str, Any]]
    unknowns: list[str]
    solve: Callable[[dict[str, Any]], dict[str, Any]]
    render: Callable[[dict[str, Any], dict[str, Any]], str]
    explain: Callable[[dict[str, Any], dict[str, Any]], str]


# ---------- common ----------

def _payload_units(payload: dict[str, Any]) -> dict[str, str]:
    return dict(payload.get("units", {}))


def _payload_inputs(payload: dict[str, Any]) -> dict[str, Any]:
    return dict(payload.get("inputs", payload))


def _finite_structure(value: Any) -> bool:
    if isinstance(value, (float, np.floating)):
        return math.isfinite(float(value))
    if isinstance(value, dict):
        return all(_finite_structure(item) for item in value.values())
    if isinstance(value, (list, tuple, np.ndarray)):
        return all(_finite_structure(item) for item in value)
    return True


def _solution(
    status: str,
    model: str,
    unknowns: dict[str, Any],
    derived: dict[str, Any],
    residual_norm: float = 0.0,
    validation: dict[str, Any] | None = None,
    all_solutions: list[dict[str, Any]] | None = None,
    error: str | None = None,
    error_code: str | None = None,
) -> dict[str, Any]:
    if status == "ok" and not _finite_structure((unknowns, derived, residual_norm)):
        return {
            "model": model,
            "status": "invalid",
            "error_code": "numerical_overflow",
            "error": "Численные параметры выходят за диапазон конечных значений",
            "validation": validation or {},
        }
    out = {
        "model": model,
        "status": status,
        "solution": {
            "unknowns": as_jsonable(unknowns),
            "derived": as_jsonable(derived),
            "residual_norm": residual_norm,
        },
        "validation": validation or {},
    }
    if error:
        out["error"] = error
    if error_code:
        out["error_code"] = error_code
    if all_solutions is not None:
        out["all_solutions"] = as_jsonable(all_solutions)
    return out


def _failure(
    model: str,
    error: str,
    *,
    error_code: str = "invalid_input",
    status: str = "invalid",
    validation: dict[str, Any] | None = None,
    missing_inputs: list[str] | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "model": model,
        "status": status,
        "error_code": error_code,
        "error": error,
        "validation": validation or {},
    }
    if missing_inputs is not None:
        out["missing_inputs"] = missing_inputs
    return out


def _angle_unit(units: dict[str, str]) -> str:
    return canonical_angle_unit(units.get("angle", "rad"))


def _fmt_angle_value(angle_rad: float, units: dict[str, str], digits: int = 6) -> str:
    if _angle_unit(units) == "deg":
        return fmt_angle_deg(angle_rad, digits)
    return fmt_float(angle_rad, digits)


def _fmt_angle_assignment(name: str, angle_rad: float, units: dict[str, str], digits: int = 6) -> str:
    unit = _angle_unit(units)
    return f"{name} := {_fmt_angle_value(angle_rad, units, digits)} {unit}"


def _angle_check_lines(name: str, angle_rad: float, units: dict[str, str], digits: int = 3) -> list[str]:
    if _angle_unit(units) == "deg":
        return [f"{name} / deg = {fmt_angle_deg(angle_rad, digits)}"]
    return []


def _raw_numeric(value: Any) -> float:
    if isinstance(value, dict):
        return float(value["value"])
    return float(value)


def _fourbar_validation(l0: float, l1: float, l2: float, l3: float) -> dict[str, bool]:
    lengths = [l0, l1, l2, l3]
    positive = all(length > 0 for length in lengths)
    shortest = min(lengths)
    longest = max(lengths)
    grashof = positive and shortest + longest < sum(lengths) - shortest - longest
    shortest_is_l1 = positive and l1 <= shortest + 1e-10
    return {
        "positive_lengths_including_ground": positive,
        "shortest_link_is_l1": shortest_is_l1,
        "grashof_strict": grashof,
        "crank_rotatability_condition": shortest_is_l1 and grashof,
    }


# ---------- slider-crank P1.1 ----------

def solve_slider_crank_two_positions(payload: dict[str, Any]) -> dict[str, Any]:
    model = "slider_crank.two_positions_stroke"
    units = _payload_units(payload)
    p = _payload_inputs(payload)
    lam2 = input_float(p, "lambda_2")
    lame = input_float(p, "lambda_e")
    phi1H = input_angle(p, "phi_1H", units)
    phi1K = input_angle(p, "phi_1K", units)
    hC = input_float(p, "h_C")
    if lam2 <= 0:
        return _failure(model, "lambda_2 must be greater than zero")
    if hC <= 0:
        return _failure(model, "h_C must be greater than zero")

    argH = (lame - math.sin(phi1H)) / lam2
    argK = (lame - math.sin(phi1K)) / lam2
    if abs(argH) > 1 or abs(argK) > 1:
        return _failure(
            model,
            "Заданные положения дают аргумент asin вне диапазона [-1, 1]",
            error_code="geometry_no_solution",
            status="no_solution",
            validation={"asin_arguments_in_range": False},
        )
    phi2H = math.asin(argH)
    phi2K = math.asin(argK)
    denom = math.cos(phi1H) - math.cos(phi1K) + lam2 * (math.cos(phi2H) - math.cos(phi2K))
    if abs(denom) < 1e-14:
        return _failure(
            model,
            "Уравнение хода вырождено: знаменатель равен нулю",
            error_code="degenerate_stroke_equation",
            status="no_solution",
            validation={"stroke_equation_nondegenerate": False},
        )
    l1 = hC / denom
    l2 = lam2 * l1
    e = lame * l1
    X_CH = l1 * math.cos(phi1H) + l2 * math.cos(phi2H)
    residuals = np.array([
        l1 * math.cos(phi1H) + l2 * math.cos(phi2H) - X_CH,
        l1 * math.sin(phi1H) + l2 * math.sin(phi2H) - e,
        l1 * math.cos(phi1K) + l2 * math.cos(phi2K) - (X_CH - hC),
        l1 * math.sin(phi1K) + l2 * math.sin(phi2K) - e,
    ])
    validation = {
        "positive_lengths": l1 > 0 and l2 > 0,
        "crank_rotatability_condition": l2 > l1 + abs(e),
        "stroke_match": abs((X_CH - (l1 * math.cos(phi1K) + l2 * math.cos(phi2K))) - hC) < 1e-8,
        "max_residual": float(np.max(np.abs(residuals))),
    }
    valid = all(
        validation[key]
        for key in ("positive_lengths", "crank_rotatability_condition", "stroke_match")
    )
    error = None if valid else "Не выполнено условие проворачиваемости кривошипа l_2 > l_1 + abs(e)"
    return _solution(
        "ok" if valid else "invalid",
        model,
        {"l_1": l1, "phi_2H": phi2H, "phi_2K": phi2K, "X_CH": X_CH},
        {"l_2": l2, "e": e, "theta_H": abs(phi2H), "theta_K": abs(phi2K)},
        float(np.linalg.norm(residuals)),
        validation,
        error=error,
        error_code=None if valid else "mechanism_condition_failed",
    )


def render_slider_crank_two_positions(payload: dict[str, Any], result: dict[str, Any]) -> str:
    units = _payload_units(payload)
    p = _payload_inputs(payload)
    sol = result["solution"]["unknowns"]
    der = result["solution"]["derived"]
    phi1H = input_angle(p, "phi_1H", units)
    phi1K = input_angle(p, "phi_1K", units)
    lines = [
        f"lambda_2 := {fmt_float(input_float(p, 'lambda_2'), 6)}",
        f"lambda_e := {fmt_float(input_float(p, 'lambda_e'), 6)}",
        _fmt_angle_assignment("phi_1H", phi1H, units),
        _fmt_angle_assignment("phi_1K", phi1K, units),
        f"h_C := {fmt_float(input_float(p, 'h_C'), 6)}",
        "",
        f"l_1 := {fmt_float(sol['l_1'], 6)}",
        _fmt_angle_assignment("phi_2H", sol["phi_2H"], units),
        _fmt_angle_assignment("phi_2K", sol["phi_2K"], units),
        f"X_CH := {fmt_float(sol['X_CH'], 6)}",
        "",
        "Given",
        "",
        "l_1 * cos(phi_1H) + l_1 * lambda_2 * cos(phi_2H) = X_CH",
        "l_1 * sin(phi_1H) + l_1 * lambda_2 * sin(phi_2H) = l_1 * lambda_e",
        "l_1 * cos(phi_1K) + l_1 * lambda_2 * cos(phi_2K) = X_CH - h_C",
        "l_1 * sin(phi_1K) + l_1 * lambda_2 * sin(phi_2K) = l_1 * lambda_e",
        "",
        "(l_1, phi_2H, phi_2K, X_CH) := Find(l_1, phi_2H, phi_2K, X_CH)",
        f"(l_1, phi_2H, phi_2K, X_CH) = ({fmt_float(sol['l_1'], 6)}, {fmt_float(sol['phi_2H'], 6)}, {fmt_float(sol['phi_2K'], 6)}, {fmt_float(sol['X_CH'], 6)})",
        "",
    ]
    lines.extend(_angle_check_lines("phi_2H", sol["phi_2H"], units))
    lines.extend(_angle_check_lines("phi_2K", sol["phi_2K"], units))
    lines.extend([
        f"l_2 := l_1 * lambda_2 = {fmt_float(der['l_2'], 6)}",
        f"e := l_1 * lambda_e = {fmt_float(der['e'], 6)}",
        f"theta_H := abs(phi_2H) = {fmt_float(der['theta_H'], 6)}",
        f"theta_K := abs(phi_2K) = {fmt_float(der['theta_K'], 6)}",
    ])
    lines.extend(_angle_check_lines("theta_H", der["theta_H"], units))
    lines.extend(_angle_check_lines("theta_K", der["theta_K"], units))
    return "\n".join(lines)


def explain_slider_crank_two_positions(payload: dict[str, Any], result: dict[str, Any]) -> str:
    return "Использованы уравнения замкнутости контура ABCA в двух положениях кривошипа. Связи lambda_2 = l_2 / l_1 и lambda_e = e / l_1 позволяют определить углы шатуна, затем из разности проекций на ось x находится l_1, после чего l_2 = lambda_2 * l_1."


# ---------- slider-crank simple formulas ----------

def solve_slider_crank_mean_velocity(payload: dict[str, Any]) -> dict[str, Any]:
    model = "slider_crank.mean_velocity"
    units = _payload_units(payload)
    p = _payload_inputs(payload)
    v_cp = input_float(p, "v_cp")
    n_1_hz = input_frequency(p, "n_1", units)
    lam2 = input_float(p, "lambda_2")
    if v_cp <= 0:
        return _failure(model, "v_cp must be greater than zero")
    if n_1_hz <= 0:
        return _failure(model, "n_1 must be greater than zero")
    if lam2 <= 0:
        return _failure(model, "lambda_2 must be greater than zero")
    H = v_cp / (2 * n_1_hz)
    l1 = H / 2
    l2 = lam2 * l1
    return _solution(
        "ok",
        model,
        {"l_1": l1},
        {"H": H, "l_2": l2, "n_1_hz": n_1_hz},
        validation={"positive_lengths": l1 > 0 and l2 > 0, "positive_frequency": n_1_hz > 0},
    )


def render_slider_crank_mean_velocity(payload: dict[str, Any], result: dict[str, Any]) -> str:
    units = _payload_units(payload)
    p = _payload_inputs(payload)
    sol = result["solution"]["unknowns"]
    der = result["solution"]["derived"]
    raw_n = _raw_numeric(p["n_1"])
    unit_source = p["n_1"].get("unit", units.get("frequency", "s^-1")) if isinstance(p["n_1"], dict) else units.get("frequency", "s^-1")
    frequency_unit = canonical_frequency_unit(str(unit_source))
    lines = [
        f"v_cp := {fmt_float(input_float(p, 'v_cp'), 6)}",
        f"n_1 := {fmt_float(raw_n, 6)} {frequency_unit}",
        f"lambda_2 := {fmt_float(input_float(p, 'lambda_2'), 6)}",
        "",
    ]
    cycle_frequency_name = "n_1"
    if frequency_unit == "rpm":
        cycle_frequency_name = "n_1_s"
        lines.append(f"n_1_s := n_1 / 60 = {fmt_float(der['n_1_hz'], 6)} s^-1")
    lines.extend([
        f"t_u := 1 / {cycle_frequency_name}",
        f"H := v_cp * t_u / 2 = {fmt_float(der['H'], 6)}",
        f"l_1 := H / 2 = {fmt_float(sol['l_1'], 6)}",
        f"l_2 := lambda_2 * l_1 = {fmt_float(der['l_2'], 6)}",
    ])
    return "\n".join(lines)


def explain_slider_crank_mean_velocity(payload: dict[str, Any], result: dict[str, Any]) -> str:
    return "Для аксиального кривошипно-ползунного механизма ход H = 2 * l_1. За цикл t_u = 1 / n_1 ползун проходит прямой и обратный ход, поэтому H = v_cp * t_u / 2 и l_1 = v_cp / (4 * n_1)."


def solve_slider_crank_pressure_angle(payload: dict[str, Any]) -> dict[str, Any]:
    model = "slider_crank.pressure_angle"
    units = _payload_units(payload)
    p = _payload_inputs(payload)
    theta_max = input_angle(p, "theta_max", units)
    lame = input_float(p, "lambda_e", 0.0)
    if not 0 < theta_max < math.pi / 2:
        return _failure(model, "theta_max must be an acute angle: 0 < theta_max < pi/2")
    if lame < 0:
        return _failure(model, "lambda_e must be nonnegative")
    lam2 = (1.0 + lame) / math.sin(theta_max)
    derived: dict[str, Any] = {"lambda_2_min": lam2}
    unknowns: dict[str, Any] = {"lambda_2": lam2}
    if "l_1" in p:
        l1 = input_float(p, "l_1")
        if l1 <= 0:
            return _failure(model, "l_1 must be greater than zero")
        derived["e"] = lame * l1
        derived["l_2"] = lam2 * l1
    validation = {
        "lambda_2_positive": lam2 > 0,
        "theta_max_acute": 0 < theta_max < math.pi / 2,
        "theta_max_deg": rad_to_deg(theta_max),
    }
    return _solution("ok", model, unknowns, derived, validation=validation)


def render_slider_crank_pressure_angle(payload: dict[str, Any], result: dict[str, Any]) -> str:
    units = _payload_units(payload)
    p = _payload_inputs(payload)
    theta_max = input_angle(p, "theta_max", units)
    sol = result["solution"]["unknowns"]
    lines = [
        _fmt_angle_assignment("theta_max", theta_max, units),
        f"lambda_e := {fmt_float(input_float(p, 'lambda_e', 0.0), 6)}",
        "",
        "theta_max = asin((1 + lambda_e) / lambda_2)",
        f"lambda_2 := (1 + lambda_e) / sin(theta_max) = {fmt_float(sol['lambda_2'], 6)}",
    ]
    der = result["solution"]["derived"]
    if "l_1" in p:
        lines.extend([
            f"l_1 := {fmt_float(input_float(p, 'l_1'), 6)}",
            f"l_2 := lambda_2 * l_1 = {fmt_float(der['l_2'], 6)}",
            f"e := lambda_e * l_1 = {fmt_float(der['e'], 6)}",
        ])
    return "\n".join(lines)


def explain_slider_crank_pressure_angle(payload: dict[str, Any], result: dict[str, Any]) -> str:
    return "Использована размерно согласованная формула максимального угла давления: theta_max = asin((1 + lambda_e) / lambda_2). Из неё определяется минимальная относительная длина шатуна lambda_2."


# ---------- fourbar P1.2 ----------

def solve_fourbar_two_extreme(payload: dict[str, Any]) -> dict[str, Any]:
    model = "fourbar.two_extreme_positions"
    units = _payload_units(payload)
    p = _payload_inputs(payload)
    XD = input_float(p, "X_D")
    YD = input_float(p, "Y_D")
    l3 = input_float(p, "l_3")
    gH = input_angle(p, "gamma_H", units)
    gK = input_angle(p, "gamma_K", units)
    if l3 <= 0:
        return _failure(model, "l_3 must be greater than zero")
    if abs(normalize_angle(gK - gH)) < 1e-12:
        return _failure(model, "gamma_H and gamma_K must describe distinct positions")
    RH = np.array([XD + l3 * math.cos(gH), YD + l3 * math.sin(gH)])
    RK = np.array([XD + l3 * math.cos(gK), YD + l3 * math.sin(gK)])
    S = float(np.linalg.norm(RH))
    D = float(np.linalg.norm(RK))
    l1 = (S - D) / 2
    l2 = (S + D) / 2
    phiH = math.atan2(RH[1], RH[0])
    theta = normalize_angle(math.atan2(RK[1], RK[0]) - phiH)
    residuals = np.array([
        (l1 + l2) * math.cos(phiH) - RH[0],
        (l1 + l2) * math.sin(phiH) - RH[1],
        (l2 - l1) * math.cos(phiH + theta) - RK[0],
        (l2 - l1) * math.sin(phiH + theta) - RK[1],
    ])
    l0 = math.hypot(XD, YD)
    validation: dict[str, Any] = {
        "positive_lengths": l1 > 0 and l2 > 0,
        "l2_ge_l1": l2 >= l1,
        "max_residual": float(np.max(np.abs(residuals))),
        **_fourbar_validation(l0, l1, l2, l3),
    }
    valid = (
        validation["positive_lengths"]
        and validation["l2_ge_l1"]
        and validation["crank_rotatability_condition"]
        and validation["max_residual"] < 1e-8
    )
    return _solution(
        "ok" if valid else "invalid",
        model,
        {"l_1": l1, "l_2": l2, "phi_1H": phiH, "theta": theta},
        {},
        float(np.linalg.norm(residuals)),
        validation,
        error=None if valid else "Не выполнены условия существования и проворачиваемости кривошипа",
        error_code=None if valid else "mechanism_condition_failed",
    )


def render_fourbar_two_extreme(payload: dict[str, Any], result: dict[str, Any]) -> str:
    units = _payload_units(payload)
    p = _payload_inputs(payload)
    sol = result["solution"]["unknowns"]
    gH = input_angle(p, "gamma_H", units)
    gK = input_angle(p, "gamma_K", units)
    lines = [
        f"X_D := {fmt_float(input_float(p, 'X_D'), 6)}",
        f"Y_D := {fmt_float(input_float(p, 'Y_D'), 6)}",
        f"l_3 := {fmt_float(input_float(p, 'l_3'), 6)}",
        _fmt_angle_assignment("gamma_H", gH, units),
        _fmt_angle_assignment("gamma_K", gK, units),
        "",
        f"l_1 := {fmt_float(sol['l_1'], 6)}",
        f"l_2 := {fmt_float(sol['l_2'], 6)}",
        _fmt_angle_assignment("phi_1H", sol["phi_1H"], units),
        _fmt_angle_assignment("theta", sol["theta"], units),
        "",
        "Given",
        "",
        "(l_1 + l_2) * cos(phi_1H) = X_D + l_3 * cos(gamma_H)",
        "(l_1 + l_2) * sin(phi_1H) = Y_D + l_3 * sin(gamma_H)",
        "(l_2 - l_1) * cos(phi_1H + theta) = X_D + l_3 * cos(gamma_K)",
        "(l_2 - l_1) * sin(phi_1H + theta) = Y_D + l_3 * sin(gamma_K)",
        "",
        "(l_1, l_2, phi_1H, theta) := Find(l_1, l_2, phi_1H, theta)",
        f"(l_1, l_2, phi_1H, theta) = ({fmt_float(sol['l_1'], 6)}, {fmt_float(sol['l_2'], 6)}, {fmt_float(sol['phi_1H'], 6)}, {fmt_float(sol['theta'], 6)})",
        "",
    ]
    lines.extend(_angle_check_lines("phi_1H", sol["phi_1H"], units))
    lines.extend(_angle_check_lines("theta", sol["theta"], units))
    return "\n".join(lines)


def explain_fourbar_two_extreme(payload: dict[str, Any], result: dict[str, Any]) -> str:
    return "Использованы уравнения замкнутости четырехшарнирного механизма в двух крайних положениях коромысла. В первом крайнем положении кривошип и шатун лежат на одной прямой, поэтому используется сумма l_1 + l_2; во втором — разность l_2 - l_1."


# ---------- fourbar P1.3 ----------

def _fourbar_speed_residual(x: np.ndarray, p: dict[str, Any], units: dict[str, str], theta: float) -> np.ndarray:
    l1, l2, phiH, XD = x
    YD = input_float(p, "Y_D")
    l3 = input_float(p, "l_3")
    gH = input_angle(p, "gamma_H", units)
    gK = input_angle(p, "gamma_K", units)
    return np.array([
        (l1 + l2) * math.cos(phiH) - (XD + l3 * math.cos(gH)),
        (l1 + l2) * math.sin(phiH) - (YD + l3 * math.sin(gH)),
        (l2 - l1) * math.cos(phiH + theta) - (XD + l3 * math.cos(gK)),
        (l2 - l1) * math.sin(phiH + theta) - (YD + l3 * math.sin(gK)),
    ], dtype=float)


def solve_fourbar_speed_ratio(payload: dict[str, Any]) -> dict[str, Any]:
    model = "fourbar.two_extreme_positions_speed_ratio"
    units = _payload_units(payload)
    p = _payload_inputs(payload)
    K = input_float(p, "K_omega")
    l3 = input_float(p, "l_3")
    YD = input_float(p, "Y_D")
    if K <= 0:
        return _failure(model, "K_omega must be greater than zero")
    if l3 <= 0:
        return _failure(model, "l_3 must be greater than zero")
    theta = math.pi * (K - 1) / (K + 1)
    base_scale = max(abs(l3), abs(YD), 1.0)
    overlap_scale = l3 / max(abs(math.sin(theta)), 1e-6)
    scale = max(base_scale, overlap_scale)
    starts = []
    l1_guesses = [0.15 * base_scale, 0.3 * base_scale, 0.1 * scale, 0.5 * scale]
    l2_guesses = [0.5 * base_scale, base_scale, 0.5 * scale, scale]
    xd_guesses = [0.1 * base_scale, 0.5 * base_scale, -0.2 * base_scale, -scale, scale]
    for l1 in l1_guesses:
        for l2 in l2_guesses:
            for phi in [10, 30, 60, 120]:
                for XD in xd_guesses:
                    starts.append([l1, l2, phi * DEG, XD])
    lb = [1e-9, 1e-9, -8 * math.pi, -100 * scale]
    ub = [100 * scale, 100 * scale, 8 * math.pi, 100 * scale]
    cands = solve_multistart(lambda x: _fourbar_speed_residual(x, p, units, theta), starts, (lb, ub))
    valid = []
    for candidate in cands:
        l1, l2, _, XD = candidate.x
        mechanism = _fourbar_validation(math.hypot(XD, YD), l1, l2, l3)
        if (
            candidate.residual_norm < 1e-8
            and l2 > l1
            and mechanism["crank_rotatability_condition"]
        ):
            valid.append(candidate)
    global_candidate = None
    if not valid:
        global_candidate = solve_global_then_local(
            lambda x: _fourbar_speed_residual(x, p, units, theta), (lb, ub), maxiter=300
        )
        global_l1, global_l2, _, global_XD = global_candidate.x
        global_mechanism = _fourbar_validation(
            math.hypot(global_XD, YD), global_l1, global_l2, l3
        )
        if (
            global_candidate.residual_norm < 1e-8
            and global_l2 > global_l1
            and global_mechanism["crank_rotatability_condition"]
        ):
            valid.append(global_candidate)
    if not valid:
        best = min([*cands, global_candidate], key=lambda candidate: candidate.residual_norm)
        out = _failure(
            model,
            "Заданные данные не образуют допустимый кривошипно-коромысловый механизм",
            error_code="no_admissible_solution",
            status="no_solution",
        )
        out.update({"best_residual_norm": best.residual_norm, "best_x": as_jsonable(best.x)})
        return out
    best = min(valid, key=lambda candidate: candidate.residual_norm)
    l1, l2, phiH, XD = best.x
    validation: dict[str, Any] = {
        "positive_lengths": l1 > 0 and l2 > 0,
        "l2_gt_l1": l2 > l1,
        "max_residual": float(np.max(np.abs(_fourbar_speed_residual(best.x, p, units, theta)))),
        **_fourbar_validation(math.hypot(XD, YD), l1, l2, l3),
    }
    return _solution(
        "ok",
        model,
        {"l_1": l1, "l_2": l2, "phi_1H": normalize_angle(phiH), "X_D": XD},
        {"theta": theta},
        best.residual_norm,
        validation,
    )


def render_fourbar_speed_ratio(payload: dict[str, Any], result: dict[str, Any]) -> str:
    units = _payload_units(payload)
    p = _payload_inputs(payload)
    sol = result["solution"]["unknowns"]
    der = result["solution"]["derived"]
    gH = input_angle(p, "gamma_H", units)
    gK = input_angle(p, "gamma_K", units)
    lines = [
        f"Y_D := {fmt_float(input_float(p, 'Y_D'), 6)}",
        f"l_3 := {fmt_float(input_float(p, 'l_3'), 6)}",
        f"K_omega := {fmt_float(input_float(p, 'K_omega'), 6)}",
        _fmt_angle_assignment("gamma_H", gH, units),
        _fmt_angle_assignment("gamma_K", gK, units),
        "",
        f"theta := pi * (K_omega - 1) / (K_omega + 1) = {fmt_float(der['theta'], 6)}",
    ]
    lines.extend(_angle_check_lines("theta", der["theta"], units))
    lines.extend([
        "",
        f"l_1 := {fmt_float(sol['l_1'], 6)}",
        f"l_2 := {fmt_float(sol['l_2'], 6)}",
        _fmt_angle_assignment("phi_1H", sol["phi_1H"], units),
        f"X_D := {fmt_float(sol['X_D'], 6)}",
        "",
        "Given",
        "",
        "(l_1 + l_2) * cos(phi_1H) = X_D + l_3 * cos(gamma_H)",
        "(l_1 + l_2) * sin(phi_1H) = Y_D + l_3 * sin(gamma_H)",
        "(l_2 - l_1) * cos(phi_1H + theta) = X_D + l_3 * cos(gamma_K)",
        "(l_2 - l_1) * sin(phi_1H + theta) = Y_D + l_3 * sin(gamma_K)",
        "",
        "(l_1, l_2, phi_1H, X_D) := Find(l_1, l_2, phi_1H, X_D)",
        f"(l_1, l_2, phi_1H, X_D) = ({fmt_float(sol['l_1'], 6)}, {fmt_float(sol['l_2'], 6)}, {fmt_float(sol['phi_1H'], 6)}, {fmt_float(sol['X_D'], 6)})",
        "",
    ])
    lines.extend(_angle_check_lines("phi_1H", sol["phi_1H"], units))
    lines.append(f"X_D = {fmt_float(sol['X_D'], 3)}")
    return "\n".join(lines)


def explain_fourbar_speed_ratio(payload: dict[str, Any], result: dict[str, Any]) -> str:
    return "Угол перекрытия определяется по формуле theta = pi * (K_omega - 1) / (K_omega + 1). Далее используются уравнения замкнутости четырехшарнирного механизма в крайних положениях: в одном положении берётся l_1 + l_2, в другом — l_2 - l_1."


# ---------- fourbar P1.4 ----------

def _fourbar_three_residual(x: np.ndarray, p: dict[str, Any], units: dict[str, str]) -> np.ndarray:
    l1, l2, phiH, phi21, phi22, phi23 = x
    XD = input_float(p, "X_D")
    YD = input_float(p, "Y_D")
    l3 = input_float(p, "l_3")
    g1 = input_angle(p, "gamma_1", units)
    g2 = input_angle(p, "gamma_2", units)
    g3 = input_angle(p, "gamma_3", units)
    d12 = input_angle(p, "phi_12", units)
    d13 = input_angle(p, "phi_13", units)
    return np.array([
        l1 * math.cos(phiH) + l2 * math.cos(phi21) - (XD + l3 * math.cos(g1)),
        l1 * math.sin(phiH) + l2 * math.sin(phi21) - (YD + l3 * math.sin(g1)),
        l1 * math.cos(phiH + d12) + l2 * math.cos(phi22) - (XD + l3 * math.cos(g2)),
        l1 * math.sin(phiH + d12) + l2 * math.sin(phi22) - (YD + l3 * math.sin(g2)),
        l1 * math.cos(phiH + d13) + l2 * math.cos(phi23) - (XD + l3 * math.cos(g3)),
        l1 * math.sin(phiH + d13) + l2 * math.sin(phi23) - (YD + l3 * math.sin(g3)),
    ], dtype=float)


def solve_fourbar_three_positions(payload: dict[str, Any]) -> dict[str, Any]:
    model = "fourbar.three_positions"
    units = _payload_units(payload)
    p = _payload_inputs(payload)
    XD = input_float(p, "X_D")
    YD = input_float(p, "Y_D")
    l3 = input_float(p, "l_3")
    d12 = input_angle(p, "phi_12", units)
    d13 = input_angle(p, "phi_13", units)
    if l3 <= 0:
        return _failure(model, "l_3 must be greater than zero")
    if abs(normalize_angle(d12)) < 1e-12 or abs(normalize_angle(d13)) < 1e-12:
        return _failure(model, "phi_12 and phi_13 must be nonzero")
    if abs(normalize_angle(d13 - d12)) < 1e-12:
        return _failure(model, "phi_12 and phi_13 must describe distinct positions")
    base_scale = max(abs(XD), abs(YD), abs(l3), 1.0)
    turn_sines = [
        abs(math.sin(normalize_angle(d12) / 2)),
        abs(math.sin(normalize_angle(d13) / 2)),
        abs(math.sin(normalize_angle(d13 - d12) / 2)),
    ]
    angular_scale = l3 / max(min(turn_sines), 1e-6)
    scale = max(base_scale, angular_scale)
    starts = []
    starts.append([0.2 * base_scale, 0.5 * base_scale, 30 * DEG, 10 * DEG, 20 * DEG, 30 * DEG])
    l1_guesses = [0.1 * base_scale, 0.25 * base_scale, 0.1 * scale, 0.5 * scale]
    l2_guesses = [0.3 * base_scale, 0.6 * base_scale, 0.5 * scale, scale]
    for l1 in l1_guesses:
        for l2 in l2_guesses:
            for phiH in [0, 30, 60, 120, -30]:
                starts.append([l1, l2, phiH * DEG, 20 * DEG, 20 * DEG, 20 * DEG])
                starts.append([l1, l2, phiH * DEG, -20 * DEG, 10 * DEG, 40 * DEG])
    lb = [1e-9, 1e-9, -8 * math.pi, -8 * math.pi, -8 * math.pi, -8 * math.pi]
    ub = [100 * scale, 100 * scale, 8 * math.pi, 8 * math.pi, 8 * math.pi, 8 * math.pi]
    cands = solve_multistart(lambda x: _fourbar_three_residual(x, p, units), starts, (lb, ub), max_nfev=50000)
    valid = []
    for candidate in cands:
        l1, l2, *_ = candidate.x
        mechanism = _fourbar_validation(math.hypot(XD, YD), l1, l2, l3)
        if candidate.residual_norm < 1e-8 and mechanism["crank_rotatability_condition"]:
            valid.append(candidate)
    global_candidate = None
    if not valid:
        global_candidate = solve_global_then_local(
            lambda x: _fourbar_three_residual(x, p, units), (lb, ub), maxiter=300
        )
        global_l1, global_l2, *_ = global_candidate.x
        global_mechanism = _fourbar_validation(
            math.hypot(XD, YD), global_l1, global_l2, l3
        )
        if (
            global_candidate.residual_norm < 1e-8
            and global_mechanism["crank_rotatability_condition"]
        ):
            valid.append(global_candidate)
    if not valid:
        best = min([*cands, global_candidate], key=lambda candidate: candidate.residual_norm)
        out = _failure(
            model,
            "Заданные положения не образуют допустимый кривошипно-коромысловый механизм",
            error_code="no_admissible_solution",
            status="no_solution",
        )
        out.update({"best_residual_norm": best.residual_norm, "best_x": as_jsonable(best.x)})
        return out
    best = min(valid, key=lambda candidate: (candidate.residual_norm, abs(candidate.x[2] - 0.7)))
    l1, l2, phiH, phi21, phi22, phi23 = best.x
    unknowns = {
        "l_1": l1,
        "l_2": l2,
        "phi_1H": normalize_angle(phiH),
        "phi_21": normalize_angle(phi21),
        "phi_22": normalize_angle(phi22),
        "phi_23": normalize_angle(phi23),
    }
    validation: dict[str, Any] = {
        "positive_lengths": l1 > 0 and l2 > 0,
        "max_residual": float(np.max(np.abs(_fourbar_three_residual(best.x, p, units)))),
        **_fourbar_validation(math.hypot(XD, YD), l1, l2, l3),
    }
    return _solution("ok", model, unknowns, {}, best.residual_norm, validation)


def render_fourbar_three_positions(payload: dict[str, Any], result: dict[str, Any]) -> str:
    units = _payload_units(payload)
    p = _payload_inputs(payload)
    sol = result["solution"]["unknowns"]
    g1 = input_angle(p, "gamma_1", units)
    g2 = input_angle(p, "gamma_2", units)
    g3 = input_angle(p, "gamma_3", units)
    d12 = input_angle(p, "phi_12", units)
    d13 = input_angle(p, "phi_13", units)
    lines = [
        f"X_D := {fmt_float(input_float(p, 'X_D'), 6)}",
        f"Y_D := {fmt_float(input_float(p, 'Y_D'), 6)}",
        f"l_3 := {fmt_float(input_float(p, 'l_3'), 6)}",
        _fmt_angle_assignment("gamma_1", g1, units),
        _fmt_angle_assignment("gamma_2", g2, units),
        _fmt_angle_assignment("gamma_3", g3, units),
        _fmt_angle_assignment("phi_12", d12, units),
        _fmt_angle_assignment("phi_13", d13, units),
        "",
        f"l_1 := {fmt_float(sol['l_1'], 6)}",
        f"l_2 := {fmt_float(sol['l_2'], 6)}",
        _fmt_angle_assignment("phi_1H", sol["phi_1H"], units),
        _fmt_angle_assignment("phi_21", sol["phi_21"], units),
        _fmt_angle_assignment("phi_22", sol["phi_22"], units),
        _fmt_angle_assignment("phi_23", sol["phi_23"], units),
        "",
        "Given",
        "",
        "l_1 * cos(phi_1H) + l_2 * cos(phi_21) = X_D + l_3 * cos(gamma_1)",
        "l_1 * sin(phi_1H) + l_2 * sin(phi_21) = Y_D + l_3 * sin(gamma_1)",
        "l_1 * cos(phi_1H + phi_12) + l_2 * cos(phi_22) = X_D + l_3 * cos(gamma_2)",
        "l_1 * sin(phi_1H + phi_12) + l_2 * sin(phi_22) = Y_D + l_3 * sin(gamma_2)",
        "l_1 * cos(phi_1H + phi_13) + l_2 * cos(phi_23) = X_D + l_3 * cos(gamma_3)",
        "l_1 * sin(phi_1H + phi_13) + l_2 * sin(phi_23) = Y_D + l_3 * sin(gamma_3)",
        "",
        "(l_1, l_2, phi_1H, phi_21, phi_22, phi_23) := Find(l_1, l_2, phi_1H, phi_21, phi_22, phi_23)",
        f"(l_1, l_2, phi_1H, phi_21, phi_22, phi_23) = ({fmt_float(sol['l_1'], 6)}, {fmt_float(sol['l_2'], 6)}, {fmt_float(sol['phi_1H'], 6)}, {fmt_float(sol['phi_21'], 6)}, {fmt_float(sol['phi_22'], 6)}, {fmt_float(sol['phi_23'], 6)})",
        "",
    ]
    lines.extend(_angle_check_lines("phi_1H", sol["phi_1H"], units))
    return "\n".join(lines)


def explain_fourbar_three_positions(payload: dict[str, Any], result: dict[str, Any]) -> str:
    return "Использована система шести уравнений замкнутости четырехшарнирного механизма для трёх заданных соответствий положений входного и выходного звеньев. Искомыми являются l_1, l_2, начальное положение кривошипа phi_1H и три положения шатуна phi_21, phi_22, phi_23."


# ---------- oscillating cylinder P1.5 variant 1 ----------

def _osc_cyl_v1_residual(x: np.ndarray, p: dict[str, Any], units: dict[str, str]) -> np.ndarray:
    XD, l1, phi1, phi3H, phi3K = x
    hmin = input_float(p, "h_min")
    hmax = input_float(p, "h_max")
    beta = input_angle(p, "beta", units)
    thetaK = input_angle(p, "theta_K", units)
    YD = input_float(p, "Y_D")
    lsh = input_float(p, "l_sh", 1.3 * hmax)
    return np.array([
        l1 * math.cos(phi1 + beta) - (XD + (hmax + lsh) * math.cos(phi3K)),
        l1 * math.sin(phi1 + beta) - (YD + (hmax + lsh) * math.sin(phi3K)),
        l1 * math.cos(phi1) - (XD + (hmin + lsh) * math.cos(phi3H)),
        l1 * math.sin(phi1) - (YD + (hmin + lsh) * math.sin(phi3H)),
        thetaK - (phi1 + beta + math.pi / 2 - phi3K),
    ], dtype=float)


def solve_osc_cyl_fixed_y_theta_k(payload: dict[str, Any]) -> dict[str, Any]:
    model = "oscillating_cylinder.fixed_y_theta_k"
    units = _payload_units(payload)
    p = _payload_inputs(payload)
    hmin = input_float(p, "h_min")
    hmax = input_float(p, "h_max")
    beta = input_angle(p, "beta", units)
    thetaK = input_angle(p, "theta_K", units)
    lsh = input_float(p, "l_sh", 1.3 * hmax)
    YD = input_float(p, "Y_D")
    if hmin < 0 or hmax <= hmin:
        return _failure(model, "Expected 0 <= h_min < h_max")
    if lsh <= 0:
        return _failure(model, "l_sh must be greater than zero")
    if not 0 < abs(beta) < math.pi:
        return _failure(model, "beta must satisfy 0 < abs(beta) < pi")
    if not 0 <= abs(thetaK) < math.pi / 2:
        return _failure(model, "theta_K must satisfy abs(theta_K) < pi/2")
    swing_scale = (hmax - hmin) / (2 * math.sin(abs(beta) / 2))
    scale = max(abs(YD), hmax + lsh, swing_scale, 1.0)
    starts = []
    for l1 in [hmax, swing_scale, scale, 1.5 * scale]:
        for phi1_deg in range(-150, 181, 30):
            phi1 = phi1_deg * DEG
            phi3K = phi1 + beta + math.pi / 2 - thetaK
            geometric_XD = l1 * math.cos(phi1 + beta) - (hmax + lsh) * math.cos(phi3K)
            for thetaH_guess in [-15 * DEG, 0.0, 15 * DEG]:
                phi3H = phi1 + math.pi / 2 - thetaH_guess
                starts.append([geometric_XD, l1, phi1, phi3H, phi3K])
    lb = [-100 * scale, 1e-9, -8 * math.pi, -8 * math.pi, -8 * math.pi]
    ub = [100 * scale, 100 * scale, 8 * math.pi, 8 * math.pi, 8 * math.pi]
    cands = solve_multistart(lambda x: _osc_cyl_v1_residual(x, p, units), starts, (lb, ub), max_nfev=50000)
    valid = []
    for candidate in cands:
        _, l1, phi1, phi3H, _ = candidate.x
        thetaH_candidate = normalize_angle(phi1 + math.pi / 2 - phi3H)
        if candidate.residual_norm < 1e-8 and l1 > 0 and abs(thetaH_candidate) < math.pi / 2:
            valid.append(candidate)
    global_candidate = None
    if not valid:
        global_candidate = solve_global_then_local(
            lambda x: _osc_cyl_v1_residual(x, p, units), (lb, ub), maxiter=300
        )
        _, global_l1, global_phi1, global_phi3H, _ = global_candidate.x
        global_thetaH = normalize_angle(global_phi1 + math.pi / 2 - global_phi3H)
        if (
            global_candidate.residual_norm < 1e-8
            and global_l1 > 0
            and abs(global_thetaH) < math.pi / 2
        ):
            valid.append(global_candidate)
    if not valid:
        best = min([*cands, global_candidate], key=lambda candidate: candidate.residual_norm)
        out = _failure(
            model,
            "Заданные данные не образуют допустимый механизм с качающимся цилиндром",
            error_code="no_admissible_solution",
            status="no_solution",
        )
        out.update({"best_residual_norm": best.residual_norm, "best_x": as_jsonable(best.x)})
        return out
    best = min(
        valid,
        key=lambda candidate: (
            candidate.x[0] < 0,
            candidate.residual_norm,
            abs(normalize_angle(candidate.x[2] - math.pi / 2)),
        ),
    )
    XD, l1, phi1, phi3H, phi3K = best.x
    thetaH = normalize_angle(phi1 + math.pi / 2 - phi3H)
    unknowns = {
        "X_D": XD,
        "l_1": l1,
        "phi_1": normalize_angle(phi1),
        "phi_3H": normalize_angle(phi3H),
        "phi_3K": normalize_angle(phi3K),
    }
    derived = {"theta_H": thetaH, "theta_K": thetaK, "l_sh": lsh}
    validation = {
        "positive_l1": l1 > 0,
        "pressure_angles_acute": abs(thetaH) < math.pi / 2 and abs(thetaK) < math.pi / 2,
        "max_residual": float(np.max(np.abs(_osc_cyl_v1_residual(best.x, p, units)))),
    }
    return _solution("ok", model, unknowns, derived, best.residual_norm, validation)


def render_osc_cyl_fixed_y_theta_k(payload: dict[str, Any], result: dict[str, Any]) -> str:
    units = _payload_units(payload)
    p = _payload_inputs(payload)
    sol = result["solution"]["unknowns"]
    der = result["solution"]["derived"]
    beta = input_angle(p, "beta", units)
    thetaK = input_angle(p, "theta_K", units)
    hmax = input_float(p, "h_max")
    lines = [
        f"h_min := {fmt_float(input_float(p, 'h_min'), 6)}",
        f"h_max := {fmt_float(hmax, 6)}",
        _fmt_angle_assignment("beta", beta, units),
        _fmt_angle_assignment("theta_K", thetaK, units),
        f"Y_D := {fmt_float(input_float(p, 'Y_D'), 6)}",
        f"l_sh := {fmt_float(der['l_sh'], 6)}",
        "",
        f"X_D := {fmt_float(sol['X_D'], 6)}",
        f"l_1 := {fmt_float(sol['l_1'], 6)}",
        _fmt_angle_assignment("phi_1", sol["phi_1"], units),
        _fmt_angle_assignment("phi_3H", sol["phi_3H"], units),
        _fmt_angle_assignment("phi_3K", sol["phi_3K"], units),
        "",
        "Given",
        "",
        "l_1 * cos(phi_1 + beta) = X_D + (h_max + l_sh) * cos(phi_3K)",
        "l_1 * sin(phi_1 + beta) = Y_D + (h_max + l_sh) * sin(phi_3K)",
        "l_1 * cos(phi_1) = X_D + (h_min + l_sh) * cos(phi_3H)",
        "l_1 * sin(phi_1) = Y_D + (h_min + l_sh) * sin(phi_3H)",
        "theta_K = phi_1 + beta + pi / 2 - phi_3K",
        "",
        "(X_D, l_1, phi_1, phi_3H, phi_3K) := Find(X_D, l_1, phi_1, phi_3H, phi_3K)",
        f"(X_D, l_1, phi_1, phi_3H, phi_3K) = ({fmt_float(sol['X_D'], 6)}, {fmt_float(sol['l_1'], 6)}, {fmt_float(sol['phi_1'], 6)}, {fmt_float(sol['phi_3H'], 6)}, {fmt_float(sol['phi_3K'], 6)})",
        "",
        f"theta_H := phi_1 + pi / 2 - phi_3H = {fmt_float(der['theta_H'], 6)}",
    ]
    lines.extend(_angle_check_lines("theta_H", der["theta_H"], units))
    lines.extend(_angle_check_lines("theta_K", der["theta_K"], units))
    return "\n".join(lines)


def explain_osc_cyl_fixed_y_theta_k(payload: dict[str, Any], result: dict[str, Any]) -> str:
    return "Использованы уравнения замкнутости механизма с качающимся цилиндром в начальном и конечном положениях. Дополнительное условие задаёт угол давления theta_K = phi_1 + beta + pi / 2 - phi_3K; угол theta_H затем вычисляется проверочно."


# ---------- registry ----------

MODELS: dict[str, ModelSpec] = {
    "slider_crank.two_positions_stroke": ModelSpec(
        "slider_crank.two_positions_stroke",
        "Кривошипно-ползунный механизм по двум положениям кривошипа и ходу ползуна",
        {
            "lambda_2": {"type": "float", "required": True},
            "lambda_e": {"type": "float", "required": True},
            "phi_1H": {"type": "angle", "required": True},
            "phi_1K": {"type": "angle", "required": True},
            "h_C": {"type": "float", "required": True},
        },
        ["l_1", "phi_2H", "phi_2K", "X_CH"],
        solve_slider_crank_two_positions,
        render_slider_crank_two_positions,
        explain_slider_crank_two_positions,
    ),
    "slider_crank.mean_velocity": ModelSpec(
        "slider_crank.mean_velocity",
        "Аксиальный кривошипно-ползунный механизм по средней скорости ползуна",
        {
            "v_cp": {"type": "float", "required": True, "constraint": "> 0"},
            "n_1": {"type": "frequency", "required": True, "constraint": "> 0"},
            "lambda_2": {"type": "float", "required": True, "constraint": "> 0"},
        },
        ["l_1"],
        solve_slider_crank_mean_velocity,
        render_slider_crank_mean_velocity,
        explain_slider_crank_mean_velocity,
    ),
    "slider_crank.pressure_angle": ModelSpec(
        "slider_crank.pressure_angle",
        "Кривошипно-ползунный механизм по допустимому углу давления",
        {
            "theta_max": {"type": "angle", "required": True},
            "lambda_e": {"type": "float", "required": False, "default": 0.0},
            "l_1": {"type": "float", "required": False},
        },
        ["lambda_2"],
        solve_slider_crank_pressure_angle,
        render_slider_crank_pressure_angle,
        explain_slider_crank_pressure_angle,
    ),
    "fourbar.two_extreme_positions": ModelSpec(
        "fourbar.two_extreme_positions",
        "Четырёхшарнирный механизм по двум крайним положениям коромысла",
        {"X_D": {"type": "float", "required": True}, "Y_D": {"type": "float", "required": True}, "l_3": {"type": "float", "required": True}, "gamma_H": {"type": "angle", "required": True}, "gamma_K": {"type": "angle", "required": True}},
        ["l_1", "l_2", "phi_1H", "theta"],
        solve_fourbar_two_extreme,
        render_fourbar_two_extreme,
        explain_fourbar_two_extreme,
    ),
    "fourbar.two_extreme_positions_speed_ratio": ModelSpec(
        "fourbar.two_extreme_positions_speed_ratio",
        "Четырёхшарнирный механизм по крайним положениям и коэффициенту изменения средней угловой скорости",
        {"Y_D": {"type": "float", "required": True}, "l_3": {"type": "float", "required": True}, "K_omega": {"type": "float", "required": True}, "gamma_H": {"type": "angle", "required": True}, "gamma_K": {"type": "angle", "required": True}},
        ["l_1", "l_2", "phi_1H", "X_D"],
        solve_fourbar_speed_ratio,
        render_fourbar_speed_ratio,
        explain_fourbar_speed_ratio,
    ),
    "fourbar.three_positions": ModelSpec(
        "fourbar.three_positions",
        "Четырёхшарнирный механизм по трём положениям",
        {"X_D": {"type": "float", "required": True}, "Y_D": {"type": "float", "required": True}, "l_3": {"type": "float", "required": True}, "gamma_1": {"type": "angle", "required": True}, "gamma_2": {"type": "angle", "required": True}, "gamma_3": {"type": "angle", "required": True}, "phi_12": {"type": "angle", "required": True}, "phi_13": {"type": "angle", "required": True}},
        ["l_1", "l_2", "phi_1H", "phi_21", "phi_22", "phi_23"],
        solve_fourbar_three_positions,
        render_fourbar_three_positions,
        explain_fourbar_three_positions,
    ),
    "oscillating_cylinder.fixed_y_theta_k": ModelSpec(
        "oscillating_cylinder.fixed_y_theta_k",
        "Механизм с качающимся цилиндром при заданных Y_D и theta_K",
        {
            "h_min": {"type": "float", "required": True},
            "h_max": {"type": "float", "required": True},
            "beta": {"type": "angle", "required": True},
            "theta_K": {"type": "angle", "required": True},
            "Y_D": {"type": "float", "required": True},
            "l_sh": {"type": "float", "required": False, "default": "1.3 * h_max"},
        },
        ["X_D", "l_1", "phi_1", "phi_3H", "phi_3K"],
        solve_osc_cyl_fixed_y_theta_k,
        render_osc_cyl_fixed_y_theta_k,
        explain_osc_cyl_fixed_y_theta_k,
    ),
}


def models_list() -> list[dict[str, Any]]:
    return [{"model": m.name, "title": m.title, "unknowns": m.unknowns} for m in MODELS.values()]


def schema(model: str) -> dict[str, Any]:
    m = MODELS[model]
    input_types = {field["type"] for field in m.inputs.values()}
    units: dict[str, Any] = {
        "length": {"accepted": "any consistent length unit", "default": None},
    }
    if "angle" in input_types:
        units["angle"] = {"accepted": ["deg", "rad"], "default": "rad"}
    if "frequency" in input_types:
        units["frequency"] = {"accepted": ["s^-1", "rpm"], "default": "s^-1"}
    return {
        "model": m.name,
        "title": m.title,
        "inputs": m.inputs,
        "unknowns": m.unknowns,
        "units": units,
    }


def solve(model: str, payload: dict[str, Any]) -> dict[str, Any]:
    if model not in MODELS:
        raise KeyError(f"Unknown model: {model}")
    if not isinstance(payload, dict):
        return _failure(model, "Input payload must be a JSON object")
    spec = MODELS[model]
    raw_units = payload.get("units", {})
    raw_inputs = payload.get("inputs", payload)
    if not isinstance(raw_units, dict):
        return _failure(model, "units must be a JSON object")
    if not isinstance(raw_inputs, dict):
        return _failure(model, "inputs must be a JSON object")
    for unit_name, unit_value in raw_units.items():
        if not isinstance(unit_name, str) or not isinstance(unit_value, str):
            return _failure(model, "Unit names and values must be strings")
    inputs = dict(raw_inputs)
    missing = [
        name
        for name, field in spec.inputs.items()
        if field.get("required", False) and name not in inputs
    ]
    if missing:
        return _failure(
            model,
            "Не заданы обязательные параметры: " + ", ".join(missing),
            error_code="missing_inputs",
            missing_inputs=missing,
        )
    try:
        return spec.solve(payload)
    except (KeyError, TypeError, ValueError, OverflowError, ZeroDivisionError) as exc:
        return _failure(model, str(exc).strip("'"))


def render(model: str, payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    if model not in MODELS:
        raise KeyError(f"Unknown model: {model}")
    if result.get("status") != "ok":
        explanation = result.get("error") or f"Решение не получено: {result.get('status', 'unknown')}"
        return {"mathcad_text": "", "short_explanation": explanation.rstrip(".") + "."}
    m = MODELS[model]
    return {"mathcad_text": m.render(payload, result), "short_explanation": m.explain(payload, result)}
