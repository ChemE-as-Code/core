"""Liquid-liquid equilibrium of a mixture at a given temperature: a stability test and a
two-liquid split on an activity-coefficient model (pre-release issue 369).

The model is a function of the mole fractions that returns ``(ln gamma_i, gE/RT)``, e.g.
:func:`chemeascode.integrations.thermo.nrtl_ln_gammas` (thermo's NRTL); this module holds no
model and no parameters, only the equilibrium search:

- **stability** (:func:`stability`): Michelsen's tangent-plane test, a successive substitution
  from a trial phase rich in each component in turn. The mixture can split when a stationary
  point other than the mixture itself has a negative tangent-plane distance;
- **split** (:func:`split`): successive substitution on ``K_i = gamma_i' / gamma_i''`` with the
  Rachford-Rice equation, started from the trial phase of the stability test (or from given
  K values), finished by Newton steps on ``ln K`` near a plait point where the substitution
  crawls. A split is accepted only when the two liquids differ, the phase fraction lies in
  (0, 1), the iso-activity residual is below the tolerance and the Gibbs energy of mixing of the
  two liquids lies below that of the single liquid.

Thermo's multiphase flash (``FlashVLN``, used by ``thermodynamics.phase``) also searches for a
vapour and needs each component's vapour-pressure and liquid-volume correlations; an extraction
stage is a liquid-only equilibrium at a stated temperature with the caller's parameters, so
this module searches the liquids only. Where both apply they find the same liquids
(``tests/test_extraction_lle.py`` compares them on water and ethyl acetate).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import numpy as np

#: (mole fractions) -> (ln gamma_i, gE/RT)
Model = Callable[[Sequence[float]], tuple[Sequence[float], float]]

#: Smallest mole fraction used in a logarithm.
_FLOOR = 1e-300
#: A stationary point closer than this (max abs mole fraction) to the mixture is the trivial one.
_TRIVIAL = 1e-5
#: Tangent-plane distance below which the mixture is unstable (two liquids).
TPD_TOLERANCE = 1e-8
#: Iso-activity residual (max abs difference of ln(x gamma) between the liquids) of a split.
RESIDUAL_TOLERANCE = 1e-8


@dataclass
class Equilibrium:
    """The liquids at equilibrium. ``x1`` is the first liquid, ``x2`` the second (mole
    fractions); ``beta`` is the mole fraction of the mixture in ``x2`` (0 with one liquid)."""

    liquids: int
    beta: float
    x1: list[float]
    x2: list[float]
    tpd: float
    iterations: int = 0
    residual: float = 0.0
    converged: bool = True
    messages: list[str] = field(default_factory=list)
    #: ln K = ln(x2 / x1) of the split, to start a neighbouring calculation from.
    ln_k: list[float] | None = None


def _ln(x: np.ndarray) -> np.ndarray:
    return np.log(np.maximum(x, _FLOOR))


def _lng(model: Model, x: np.ndarray) -> np.ndarray:
    return np.asarray(model(list(x))[0], dtype=float)


def gibbs_of_mixing(model: Model, x: Sequence[float]) -> float:
    """Dimensionless Gibbs energy of mixing ``sum x_i ln(x_i gamma_i)`` of one liquid."""
    xs = np.asarray(x, dtype=float)
    return float(np.sum(xs * (_ln(xs) + _lng(model, xs))))


def stability(model: Model, z: Sequence[float], max_iter: int = 500) -> tuple[float, list[float]]:
    """The lowest tangent-plane distance found (``1 - sum W`` at a stationary point) and its
    trial composition; ``(0.0, z)`` when every trial returns to the mixture itself. A distance
    below ``-TPD_TOLERANCE`` means the liquid splits."""
    zs = np.asarray(z, dtype=float)
    d = _ln(zs) + _lng(model, zs)
    n = len(zs)
    best_tpd, best_w = 0.0, zs.copy()
    for k in range(n):
        w = np.full(n, 1e-3 / max(n - 1, 1))
        w[k] = 1.0 - 1e-3
        total = 1.0
        for _ in range(max_iter):
            big_w = np.exp(d - _lng(model, w))
            total = float(big_w.sum())
            new = big_w / total
            done = float(np.max(np.abs(new - w))) < 1e-12
            w = new
            if done:
                break
        tpd = 1.0 - total
        if float(np.max(np.abs(w - zs))) > _TRIVIAL and tpd < best_tpd:
            best_tpd, best_w = tpd, w.copy()
    return best_tpd, [float(v) for v in best_w]


def _rachford_rice(z: np.ndarray, k: np.ndarray) -> float:
    """The phase fraction beta of the second liquid with ``sum z (K - 1) / (1 + beta (K - 1))
    = 0``, searched in the window where every denominator is positive (a negative flash is
    allowed while iterating)."""
    km = k - 1.0
    lo = -1.0 / km.max() if km.max() > 0 else -1e12
    hi = -1.0 / km.min() if km.min() < 0 else 1e12
    lo, hi = lo + 1e-12 * abs(lo) + 1e-15, hi - 1e-12 * abs(hi) - 1e-15

    def f(beta: float) -> float:
        return float(np.sum(z * km / (1.0 + beta * km)))

    # f falls monotonically from +inf (lo) to -inf (hi): bisection, then the bracket's middle
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if f(mid) > 0:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-15:
            break
    return 0.5 * (lo + hi)


def split(
    model: Model,
    z: Sequence[float],
    start: Sequence[float] | None = None,
    ln_k: Sequence[float] | None = None,
    max_iter: int = 200,
    max_newton: int = 50,
) -> Equilibrium:
    """Two liquids from *z*, started from a trial liquid *start* (the stability test's) or from
    *ln_k*. With neither, the stability test runs first. One liquid (``liquids == 1``) when the
    mixture is stable or the iteration falls back onto the mixture.

    Up to *max_iter* accelerated substitutions; near a plait point, where they crawl, up to
    *max_newton* Newton steps on ``ln K`` (finite-difference Jacobian) finish the split."""
    zs = np.asarray(z, dtype=float)
    zs = zs / zs.sum()
    tpd = float("nan")
    if ln_k is None:
        if start is None:
            tpd, trial = stability(model, zs)
            if tpd >= -TPD_TOLERANCE:
                return _one(zs, tpd, "stable: one liquid (tangent-plane distance >= 0)")
            start = trial
        lnk = _lng(model, zs) - _lng(model, np.asarray(start, dtype=float))
    else:
        lnk = np.asarray(ln_k, dtype=float)
    history: list[np.ndarray] = []
    iteration, converged = 0, False
    for iteration in range(1, max_iter + 1):
        beta, x1, x2 = _phases(zs, lnk)
        new = _lng(model, x1) - _lng(model, x2)
        change = float(np.max(np.abs(new - lnk)))
        lnk = _accelerate(history, new)
        if float(np.max(np.abs(x1 - x2))) < _TRIVIAL:
            return _fallback(zs, tpd, "the split fell back onto one liquid", iteration)
        if change < 1e-12:
            converged = True
            break
    for _ in range(max_newton if not converged else 0):
        iteration += 1
        residual = _residual(model, zs, lnk)
        if float(np.max(np.abs(residual))) < 1e-12:
            converged = True
            break
        jacobian = np.empty((len(zs), len(zs)))
        for j in range(len(zs)):
            step = np.zeros(len(zs))
            step[j] = 1e-7 * max(1.0, abs(lnk[j]))
            jacobian[:, j] = (_residual(model, zs, lnk + step) - residual) / step[j]
        try:
            delta = np.linalg.solve(jacobian, -residual)
        except np.linalg.LinAlgError:
            break
        largest = float(np.max(np.abs(delta)))
        lnk = lnk + (delta if largest <= 1.0 else delta / largest)
        if float(np.max(np.abs(lnk))) < _TRIVIAL:
            return _fallback(zs, tpd, "the split fell back onto one liquid", iteration)
    beta, x1, x2 = _phases(zs, lnk)
    return _result(model, zs, beta, x1, x2, tpd, iteration, lnk, converged=converged)


def _phases(zs: np.ndarray, lnk: np.ndarray) -> tuple[float, np.ndarray, np.ndarray]:
    """The phase fraction and the two liquids that *lnk* gives by the Rachford-Rice equation."""
    k = np.exp(lnk)
    beta = _rachford_rice(zs, k)
    x1 = zs / (1.0 + beta * (k - 1.0))
    x2 = k * x1
    return beta, x1 / x1.sum(), x2 / x2.sum()


def _residual(model: Model, zs: np.ndarray, lnk: np.ndarray) -> np.ndarray:
    """``ln K - (ln gamma' - ln gamma'')``: zero at the equilibrium."""
    _, x1, x2 = _phases(zs, lnk)
    return lnk - (_lng(model, x1) - _lng(model, x2))


def _accelerate(history: list[np.ndarray], new: np.ndarray, every: int = 6) -> np.ndarray:
    """The next ln K: *new*, or every *every* plain substitutions its dominant-eigenvalue
    extrapolation (Crowe and Nishio, AIChE J. 21 (1975) 528) when the last steps shrink
    steadily (eigenvalue in (0, 0.99)); the substitution itself decides convergence."""
    history.append(new)
    if len(history) < every:
        return new
    a, b, c = history[-3], history[-2], history[-1]
    history.clear()
    previous, last = b - a, c - b
    denominator = float(previous @ previous)
    if denominator == 0.0:
        return new
    eigenvalue = float(last @ previous) / denominator
    if not 0.0 < eigenvalue < 0.99:
        return new
    return c + last * eigenvalue / (1.0 - eigenvalue)


def _one(
    zs: np.ndarray, tpd: float, message: str, iterations: int = 0, converged: bool = True
) -> Equilibrium:
    x = [float(v) for v in zs]
    return Equilibrium(1, 0.0, x, list(x), tpd, iterations, 0.0, converged, [message])


def _fallback(
    zs: np.ndarray, tpd: float, message: str, iterations: int, converged: bool = True
) -> Equilibrium:
    """One liquid after the split search: not converged when the stability test found the
    mixture unstable (a negative tangent-plane distance) or the iteration did not converge, so
    a failed search is never reported as a stable single liquid."""
    if tpd < -TPD_TOLERANCE:
        message += f", although the stability test found two (tangent-plane distance {tpd:.3g})"
        converged = False
    return _one(zs, tpd, message, iterations, converged)


def _result(model, zs, beta, x1, x2, tpd, iterations, lnk, converged) -> Equilibrium:
    # iso-activity of the components present (an absent one has no activity to match)
    present = zs > 0
    activity = (_ln(x1) + _lng(model, x1)) - (_ln(x2) + _lng(model, x2))
    residual = float(np.max(np.abs(activity[present])))
    messages = []
    if not converged:
        messages.append(f"the split did not converge in {iterations} iterations")
    if not 0.0 < beta < 1.0:
        return _fallback(
            zs,
            tpd,
            f"no split inside the mixture (phase fraction {beta:.4g})",
            iterations,
            converged,
        )
    g_two = (1.0 - beta) * gibbs_of_mixing(model, x1) + beta * gibbs_of_mixing(model, x2)
    if g_two >= gibbs_of_mixing(model, zs) - 1e-12:
        return _fallback(
            zs, tpd, "the split does not lower the Gibbs energy: one liquid", iterations, converged
        )
    ok = converged and residual < RESIDUAL_TOLERANCE
    if converged and not ok:
        messages.append(f"iso-activity residual {residual:.2e} above {RESIDUAL_TOLERANCE:.0e}")
    return Equilibrium(
        2,
        float(beta),
        [float(v) for v in x1],
        [float(v) for v in x2],
        tpd,
        iterations,
        residual,
        ok,
        messages,
        [float(v) for v in lnk],
    )
