from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

import numpy as np
from scipy.optimize import differential_evolution, least_squares


@dataclass
class SolveCandidate:
    x: np.ndarray
    residual_norm: float
    cost: float
    success: bool
    message: str


def _unique_solutions(cands: list[SolveCandidate], atol: float = 1e-7) -> list[SolveCandidate]:
    out: list[SolveCandidate] = []
    for c in sorted(cands, key=lambda z: z.residual_norm):
        if not c.success:
            continue
        if not any(np.allclose(c.x, o.x, atol=atol, rtol=1e-6) for o in out):
            out.append(c)
    return out


def solve_multistart(
    residuals: Callable[[np.ndarray], np.ndarray],
    starts: Iterable[Iterable[float]],
    bounds: tuple[Iterable[float], Iterable[float]] | None = None,
    xtol: float = 1e-12,
    ftol: float = 1e-12,
    gtol: float = 1e-12,
    max_nfev: int = 20000,
) -> list[SolveCandidate]:
    starts_arr = [np.asarray(s, dtype=float) for s in starts]
    if not starts_arr:
        raise ValueError("At least one initial guess is required")
    if bounds is None:
        lb = np.full_like(starts_arr[0], -np.inf, dtype=float)
        ub = np.full_like(starts_arr[0], np.inf, dtype=float)
    else:
        lb = np.asarray(list(bounds[0]), dtype=float)
        ub = np.asarray(list(bounds[1]), dtype=float)
    cands: list[SolveCandidate] = []
    for s in starts_arr:
        s2 = np.minimum(np.maximum(s, lb + 1e-10), ub - 1e-10)
        try:
            res = least_squares(
                residuals,
                s2,
                bounds=(lb, ub),
                xtol=xtol,
                ftol=ftol,
                gtol=gtol,
                max_nfev=max_nfev,
            )
            rn = float(np.linalg.norm(res.fun))
            cands.append(SolveCandidate(res.x, rn, float(res.cost), bool(res.success), str(res.message)))
        except Exception as exc:
            cands.append(SolveCandidate(s2, float("inf"), float("inf"), False, repr(exc)))
    return _unique_solutions(cands)


def solve_global_then_local(
    residuals: Callable[[np.ndarray], np.ndarray],
    bounds: tuple[Iterable[float], Iterable[float]],
    seed: int = 1,
    maxiter: int = 800,
) -> SolveCandidate:
    lb = np.asarray(list(bounds[0]), dtype=float)
    ub = np.asarray(list(bounds[1]), dtype=float)
    b = list(zip(lb, ub))

    def objective(x: np.ndarray) -> float:
        r = np.asarray(residuals(x), dtype=float)
        return float(np.dot(r, r))

    de = differential_evolution(objective, b, seed=seed, polish=False, maxiter=maxiter, tol=1e-10)
    local = least_squares(residuals, de.x, bounds=(lb, ub), xtol=1e-12, ftol=1e-12, gtol=1e-12, max_nfev=50000)
    return SolveCandidate(local.x, float(np.linalg.norm(local.fun)), float(local.cost), bool(local.success), str(local.message))
