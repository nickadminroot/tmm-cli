from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = SKILL_ROOT / "scripts"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "msynth.cli", *args],
        cwd=RUNTIME_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_skill_path_points_to_discoverable_skill() -> None:
    completed = _run("skill-path")

    assert completed.returncode == 0
    path = Path(completed.stdout.strip())
    assert path.is_file()
    assert path.read_text(encoding="utf-8").startswith("---\nname: metric-synthesis\n")

def test_skill_path_is_adjacent_from_arbitrary_cwd(tmp_path: Path) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "msynth.cli", "skill-path"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert Path(completed.stdout.strip()).resolve() == (SKILL_ROOT / "SKILL.md").resolve()



def test_nonobject_json_has_concise_error_without_traceback(tmp_path: Path) -> None:
    path = tmp_path / "array.json"
    path.write_text("[]", encoding="utf-8")

    completed = _run("run", "--input", str(path), "--output-format", "json")

    assert completed.returncode == 2
    assert "root must be an object" in completed.stderr
    assert "Traceback" not in completed.stderr


def test_invalid_json_has_concise_error_without_traceback(tmp_path: Path) -> None:
    path = tmp_path / "invalid.json"
    path.write_text("{", encoding="utf-8")

    completed = _run("run", "--input", str(path), "--output-format", "json")

    assert completed.returncode == 2
    assert "invalid JSON" in completed.stderr
    assert "Traceback" not in completed.stderr


def test_missing_inputs_are_structured_and_return_nonzero(tmp_path: Path) -> None:
    path = tmp_path / "missing.json"
    path.write_text(
        json.dumps(
            {
                "model": "fourbar.two_extreme_positions",
                "inputs": {"X_D": 0.8, "l_3": 0.5},
            }
        ),
        encoding="utf-8",
    )

    completed = _run("run", "--input", str(path), "--output-format", "json")

    assert completed.returncode == 3
    result = json.loads(completed.stdout)
    assert result["status"] == "invalid"
    assert result["missing_inputs"] == ["Y_D", "gamma_H", "gamma_K"]
    assert "Traceback" not in completed.stderr


def test_success_returns_zero_and_final_contract() -> None:
    completed = _run(
        "run",
        "--input",
        str(SKILL_ROOT / "examples" / "p1_2_fourbar_two_extreme.json"),
        "--output-format",
        "final",
    )

    assert completed.returncode == 0
    assert "Given" in completed.stdout
    assert "\nКраткое пояснение: " in completed.stdout
    assert "Python" not in completed.stdout


def test_malformed_unit_type_returns_three_without_traceback(tmp_path: Path) -> None:
    path = tmp_path / "bad-unit.json"
    path.write_text(
        json.dumps(
            {
                "model": "slider_crank.pressure_angle",
                "units": {"angle": 3},
                "inputs": {"theta_max": 0.3},
            }
        ),
        encoding="utf-8",
    )

    completed = _run("run", "--input", str(path), "--output-format", "json")

    assert completed.returncode == 3
    result = json.loads(completed.stdout)
    assert result["status"] == "invalid"
    assert "strings" in result["error"]
    assert "Traceback" not in completed.stderr


def test_invalid_domain_returns_three_without_traceback(tmp_path: Path) -> None:
    path = tmp_path / "invalid-domain.json"
    path.write_text(
        json.dumps(
            {
                "model": "slider_crank.mean_velocity",
                "inputs": {"v_cp": 1, "n_1": 0, "lambda_2": 3},
            }
        ),
        encoding="utf-8",
    )

    completed = _run("run", "--input", str(path), "--output-format", "final")

    assert completed.returncode == 3
    assert "n_1" in completed.stdout
    assert "Traceback" not in completed.stderr

def test_unknown_model_is_rejected_without_traceback(tmp_path: Path) -> None:
    path = tmp_path / "unsupported.json"
    path.write_text(
        json.dumps({"model": "linkage.unknown", "inputs": {}}),
        encoding="utf-8",
    )

    completed = _run("run", "--input", str(path), "--output-format", "json")

    assert completed.returncode == 2
    assert "linkage.unknown" in completed.stderr
    assert "Traceback" not in completed.stderr
