from __future__ import annotations

import pytest

from msynth.classify import classify_text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Синтез кривошипно-ползунного механизма по двум положениям кривошипа и ходу ползуна",
            "slider_crank.two_positions_stroke",
        ),
        (
            "Аксиальный кривошипно-ползунный механизм по средней скорости и частоте вращения",
            "slider_crank.mean_velocity",
        ),
        (
            "Определить размеры кривошипно-ползунного механизма по допустимому углу давления",
            "slider_crank.pressure_angle",
        ),
        (
            "Четырёхшарнирный механизм по двум крайним положениям коромысла",
            "fourbar.two_extreme_positions",
        ),
        (
            "Четырёхшарнирный механизм по крайним положениям и коэффициенту средней угловой скорости",
            "fourbar.two_extreme_positions_speed_ratio",
        ),
        (
            "Четырёхшарнирный механизм по три положения",
            "fourbar.three_positions",
        ),
        (
            "Механизм с качающимся цилиндром и углом давления в конечном положении",
            "oscillating_cylinder.fixed_y_theta_k",
        ),
    ],
)
def test_archive_phrasings_are_classified(text: str, expected: str) -> None:
    result = classify_text(text)

    assert result["status"] == "ok"
    assert result["model"] == expected


def test_unrelated_task_is_unknown() -> None:
    result = classify_text("Рассчитать зубчатую передачу и выбрать модуль колеса")

    assert result["status"] == "unknown"
    assert result["model"] is None
