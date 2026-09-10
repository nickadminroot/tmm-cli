from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np

DEG = math.pi / 180.0

DEG_UNITS = {"deg", "degree", "degrees", "град", "градус", "градусы"}
RAD_UNITS = {"rad", "radian", "radians", "рад"}
RPM_UNITS = {"rpm", "rev/min", "r/min", "об/мин", "об.мин-1"}
HZ_UNITS = {"hz", "1/s", "s^-1", "s⁻¹", "об/с", "rev/s"}


def load_json(path: str | Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        value = json.load(f)
    if not isinstance(value, dict):
        raise ValueError("Input JSON root must be an object")
    return value


def dump_json(obj: Any) -> str:
    return json.dumps(as_jsonable(obj), ensure_ascii=False, indent=2, allow_nan=False)


def angle_to_rad(value: Any, default_unit: str = "rad") -> float:
    if isinstance(value, dict):
        val = float(value["value"])
        unit = str(value.get("unit", default_unit))
    else:
        val = float(value)
        unit = default_unit
    if not math.isfinite(val):
        raise ValueError("Angle value must be finite")
    if not isinstance(unit, str):
        raise ValueError("Angle unit must be a string")
    unit = unit.lower()
    if unit in DEG_UNITS:
        return val * DEG
    if unit in RAD_UNITS:
        return val
    raise ValueError(f"Unknown angle unit: {unit}")


def canonical_angle_unit(unit: str) -> str:
    if not isinstance(unit, str):
        raise ValueError("Angle unit must be a string")
    normalized = unit.lower()
    if normalized in DEG_UNITS:
        return "deg"
    if normalized in RAD_UNITS:
        return "rad"
    raise ValueError(f"Unknown angle unit: {unit}")


def frequency_to_hz(value: Any, default_unit: str = "s^-1") -> float:
    if isinstance(value, dict):
        val = float(value["value"])
        unit = str(value.get("unit", default_unit))
    else:
        val = float(value)
        unit = default_unit
    if not math.isfinite(val):
        raise ValueError("Frequency value must be finite")
    if not isinstance(unit, str):
        raise ValueError("Frequency unit must be a string")
    normalized = unit.lower()
    if normalized in RPM_UNITS:
        return val / 60.0
    if normalized in HZ_UNITS:
        return val
    raise ValueError(f"Unknown frequency unit: {unit}")


def canonical_frequency_unit(unit: str) -> str:
    if not isinstance(unit, str):
        raise ValueError("Frequency unit must be a string")
    normalized = unit.lower()
    if normalized in RPM_UNITS:
        return "rpm"
    if normalized in HZ_UNITS:
        return "s^-1"
    raise ValueError(f"Unknown frequency unit: {unit}")


def rad_to_deg(x: float) -> float:
    return float(x) / DEG


def normalize_angle(a: float, center: float = 0.0) -> float:
    """Normalize angle to [center-pi, center+pi)."""
    return (a - center + math.pi) % (2 * math.pi) - math.pi + center


def input_angle(inputs: dict[str, Any], key: str, units: dict[str, str] | None = None) -> float:
    if key not in inputs:
        raise KeyError(f"Missing required input: {key}")
    default_unit = (units or {}).get("angle", "rad")
    return angle_to_rad(inputs[key], default_unit)


def input_frequency(inputs: dict[str, Any], key: str, units: dict[str, str] | None = None) -> float:
    if key not in inputs:
        raise KeyError(f"Missing required input: {key}")
    default_unit = (units or {}).get("frequency", "s^-1")
    return frequency_to_hz(inputs[key], default_unit)


def input_float(inputs: dict[str, Any], key: str, default: float | None = None) -> float:
    if key not in inputs:
        if default is None:
            raise KeyError(f"Missing required input: {key}")
        return default
    value = float(inputs[key])
    if not math.isfinite(value):
        raise ValueError(f"{key} must be finite")
    return value


def fmt_float(x: float, digits: int = 6, trim: bool = True) -> str:
    if abs(x) < 0.5 * 10 ** (-digits):
        x = 0.0
    s = f"{x:.{digits}f}"
    if trim:
        s = s.rstrip("0").rstrip(".")
    if s == "-0":
        s = "0"
    return s


def fmt_angle_rad(x: float, digits: int = 6) -> str:
    return fmt_float(x, digits)


def fmt_angle_deg(x: float, digits: int = 3) -> str:
    return fmt_float(rad_to_deg(x), digits)


def vec_norm(x: np.ndarray) -> float:
    return float(np.linalg.norm(np.asarray(x, dtype=float)))


def as_jsonable(obj: Any) -> Any:
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (np.float64, np.float32)):
        return float(obj)
    if isinstance(obj, (np.int64, np.int32)):
        return int(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, dict):
        return {k: as_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [as_jsonable(v) for v in obj]
    return obj
