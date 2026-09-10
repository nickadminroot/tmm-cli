from __future__ import annotations

import re
from typing import Any

from .models import MODELS


def classify_text(text: str) -> dict[str, Any]:
    """Classify common Russian archive phrasings without extracting numeric data."""
    normalized = text.lower().replace("ё", "е")
    scores: list[tuple[float, int, str, list[str]]] = []

    def score(model: str, patterns: list[str], priority: int = 0) -> None:
        hits = [pattern for pattern in patterns if re.search(pattern, normalized)]
        ratio = len(hits) / len(patterns)
        if len(hits) >= 2 and ratio >= 0.5:
            scores.append((ratio, priority, model, hits))

    score(
        "slider_crank.two_positions_stroke",
        [r"кривошип", r"ползун", r"(?:двум|двух)\w*\s+.*полож", r"ход"],
    )
    score(
        "slider_crank.mean_velocity",
        [r"кривошип", r"ползун", r"средн", r"скорост", r"частот|оборот"],
        priority=1,
    )
    score(
        "slider_crank.pressure_angle",
        [r"кривошип", r"ползун", r"давлен"],
        priority=2,
    )
    score(
        "fourbar.two_extreme_positions_speed_ratio",
        [r"четыр", r"крайн", r"коэффициент", r"средн|углов|скорост"],
        priority=2,
    )
    score(
        "fourbar.two_extreme_positions",
        [r"четыр", r"крайн", r"коромысл"],
        priority=1,
    )
    score(
        "fourbar.three_positions",
        [r"четыр", r"(?:три|трем|трех)\w*\s+полож"],
        priority=1,
    )
    score(
        "oscillating_cylinder.fixed_y_theta_k",
        [r"качающ\w*\s+цилиндр", r"theta_k|θк|давлен|конечн"],
        priority=2,
    )

    if not scores:
        return {"status": "unknown", "model": None, "confidence": 0.0, "candidates": []}
    scores.sort(reverse=True)
    top_score, _, top_model, top_hits = scores[0]
    return {
        "status": "ok",
        "model": top_model,
        "confidence": round(min(0.99, 0.4 + 0.6 * top_score), 3),
        "matched_patterns": top_hits,
        "candidates": [
            {"model": model, "score": round(candidate_score, 3)}
            for candidate_score, _, model, _ in scores[:5]
            if model in MODELS
        ],
    }
