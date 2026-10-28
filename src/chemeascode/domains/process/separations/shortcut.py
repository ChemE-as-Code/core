"""Shortcut distillation: Fenske, Underwood, Gilliland (Molokanov form).

Typed functions on mole fractions and relative volatilities (to the heavy key, so
``alpha[heavy_key] == 1``). They assume constant relative volatility and constant molar
overflow, as the methods do.

- Fenske (1932): minimum theoretical stages at total reflux,
  ``Nmin = ln[(xD_LK / xD_HK) (xB_HK / xB_LK)] / ln(alpha_LK)``.
- Underwood (1948): ``sum alpha_i z_i / (alpha_i - theta) = 1 - q`` for the root theta between
  ``alpha_HK`` and ``alpha_LK``, then ``Rmin + 1 = sum alpha_i xD_i / (alpha_i - theta)``.
- Gilliland (1940) in the equation of Molokanov et al. (1972):
  ``Y = 1 - exp[(1 + 54.4 X) / (11 + 117.2 X) (X - 1) / sqrt(X)]``,
  ``X = (R - Rmin) / (R + 1)``, ``Y = (N - Nmin) / (N + 1)``.

References: M. R. Fenske, Ind. Eng. Chem. 24 (1932) 482-485; A. J. V. Underwood, Chem. Eng.
Prog. 44 (1948) 603-614; E. R. Gilliland, Ind. Eng. Chem. 32 (1940) 1220-1223;
Y. K. Molokanov, T. P. Korablina, N. I. Mazurina, G. A. Nikiforov, Int. Chem. Eng. 12 (1972)
209-212. The stage counts are theoretical stages including the reboiler (and a partial
condenser, if any).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

SOURCES = (
    "Fenske, Ind. Eng. Chem. 24 (1932) 482; Underwood, Chem. Eng. Prog. 44 (1948) 603; "
    "Gilliland, Ind. Eng. Chem. 32 (1940) 1220, as Molokanov et al., Int. Chem. Eng. 12 (1972) 209"
)


def fenske(xd_lk: float, xd_hk: float, xb_lk: float, xb_hk: float, alpha_lk: float) -> float:
    """Minimum theoretical stages at total reflux; *alpha_lk* relative to the heavy key."""
    if min(xd_lk, xd_hk, xb_lk, xb_hk) <= 0:
        raise ValueError("Fenske needs both keys in both products (fractions > 0)")
    if alpha_lk <= 1:
        raise ValueError("the light key must be more volatile than the heavy key (alpha > 1)")
    return math.log((xd_lk / xd_hk) * (xb_hk / xb_lk)) / math.log(alpha_lk)


def underwood_theta(
    alphas: dict[str, float], feed: dict[str, float], q: float, light_key: str, heavy_key: str
) -> float:
    """The Underwood root between the keys' volatilities, by bisection."""
    lo, hi = alphas[heavy_key], alphas[light_key]
    if hi <= lo:
        raise ValueError("the light key must be more volatile than the heavy key")

    def g(theta: float) -> float:
        return sum(alphas[i] * feed[i] / (alphas[i] - theta) for i in feed) - (1.0 - q)

    # g rises from -inf just above lo to +inf just below hi (dg/dtheta > 0 between the poles)
    a, b = lo + 1e-12 * (hi - lo), hi - 1e-12 * (hi - lo)
    for _ in range(200):
        mid = 0.5 * (a + b)
        if g(mid) > 0:
            b = mid
        else:
            a = mid
    return 0.5 * (a + b)


def underwood_min_reflux(
    alphas: dict[str, float], distillate: dict[str, float], theta: float
) -> float:
    """Minimum reflux ratio from the Underwood root *theta*."""
    return sum(alphas[i] * distillate[i] / (alphas[i] - theta) for i in distillate) - 1.0


def gilliland(reflux: float, min_reflux: float, min_stages: float) -> float:
    """Theoretical stages at *reflux* (Gilliland, Molokanov equation)."""
    if reflux <= min_reflux:
        raise ValueError("the reflux ratio must exceed the minimum reflux ratio")
    x = (reflux - min_reflux) / (reflux + 1.0)
    y = 1.0 - math.exp((1.0 + 54.4 * x) / (11.0 + 117.2 * x) * (x - 1.0) / math.sqrt(x))
    return (min_stages + y) / (1.0 - y)


@dataclass
class Shortcut:
    """The result of :func:`fug`."""

    min_stages: float
    theta: float
    min_reflux: float
    reflux: float | None
    stages: float | None


def fug(
    alphas: dict[str, float],
    feed: dict[str, float],
    distillate: dict[str, float],
    bottoms: dict[str, float],
    q: float,
    light_key: str,
    heavy_key: str,
    reflux: float | None = None,
) -> Shortcut:
    """Fenske-Underwood-Gilliland for one feed and two products; with *reflux* the stages."""
    alpha_lk = alphas[light_key] / alphas[heavy_key]
    rel = {k: v / alphas[heavy_key] for k, v in alphas.items()}
    nmin = fenske(
        distillate[light_key],
        distillate[heavy_key],
        bottoms[light_key],
        bottoms[heavy_key],
        alpha_lk,
    )
    theta = underwood_theta(rel, feed, q, light_key, heavy_key)
    rmin = underwood_min_reflux(rel, distillate, theta)
    stages = gilliland(reflux, rmin, nmin) if reflux is not None else None
    return Shortcut(nmin, theta, rmin, reflux, stages)
