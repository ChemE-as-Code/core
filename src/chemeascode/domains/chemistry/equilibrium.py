"""Chemical equilibrium of ideal-gas reactions at a given temperature and pressure.

The extents ``xi`` of the reactions minimise the Gibbs energy of the mixture::

    Phi(xi) = sum_i n_i ln(n_i / N) + sum_j xi_j (-ln K_j + dnu_j ln(P / 1 bar)),
    n = n0 + nu xi,

whose gradient is zero where every reaction is at equilibrium
(``K_j = prod (y_i P / 1 bar)^nu_ij``). ``Phi`` is convex, so Newton steps with a backtracking
line search that keeps every amount positive converge from the feed. Species that are not fed
start from a trace (:data:`SEED` of the feed), which is dropped from the result: the outlet is
``n0 + nu xi`` exactly, so the elements balance.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from chemeascode.domains.chemistry.thermochemistry import P_STANDARD

#: The trace a species that is not fed starts from, relative to the total feed.
SEED = 1e-10
TOLERANCE = 1e-10
MAX_ITERATIONS = 200


class NotConverged(ValueError):
    """The equilibrium was not found."""


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    """a x = b by Gaussian elimination with partial pivoting (a small, symmetric positive
    semi-definite; a zero pivot gives that unknown 0)."""
    m = len(b)
    rows = [[*a[i], b[i]] for i in range(m)]
    for col in range(m):
        best = max(range(col, m), key=lambda r: abs(rows[r][col]))
        rows[col], rows[best] = rows[best], rows[col]
        p = rows[col][col]
        if abs(p) < 1e-14:
            continue
        for r in range(col + 1, m):
            f = rows[r][col] / p
            if f:
                rows[r] = [v - f * w for v, w in zip(rows[r], rows[col], strict=True)]
    x = [0.0] * m
    for i in reversed(range(m)):
        p = rows[i][i]
        if abs(p) < 1e-14:
            continue
        x[i] = (rows[i][m] - sum(rows[i][k] * x[k] for k in range(i + 1, m))) / p
    return x


def equilibrate(
    reactions: Sequence[Mapping[str, float]],
    ln_k: Sequence[float],
    feed: Mapping[str, float],
    pressure: float,
) -> tuple[dict[str, float], list[float]]:
    """The equilibrium outlet (species -> kmol/h) of *feed* (kmol/h) through *reactions*
    (stoichiometry each) with equilibrium constants ``exp(ln_k)`` (partial pressures in bar) at
    *pressure* kPa, and the extents (kmol/h). Every species of the feed is in the gas (inerts
    too); raises :class:`NotConverged` when Newton does not converge."""
    names = list(dict.fromkeys([*feed, *(n for r in reactions for n in r)]))
    total = sum(v for v in feed.values() if v > 0)
    if total <= 0:
        raise NotConverged("the feed is empty")
    m = len(reactions)
    nu = [[r.get(n, 0.0) for r in reactions] for n in names]
    dnu = [sum(r.values()) for r in reactions]
    base = [max(feed.get(n, 0.0), 0.0) for n in names]
    start = [b if b > 0 else SEED * total for b in base]
    shift = [-ln_k[j] + dnu[j] * math.log(pressure / P_STANDARD) for j in range(m)]

    def amounts(xi: list[float]) -> list[float]:
        return [start[i] + sum(nu[i][j] * xi[j] for j in range(m)) for i in range(len(names))]

    def phi(xi: list[float]) -> float:
        n = amounts(xi)
        big = sum(n)
        return sum(v * math.log(v / big) for v in n) + sum(xi[j] * shift[j] for j in range(m))

    def gradient(xi: list[float]) -> list[float]:
        n = amounts(xi)
        big = sum(n)
        return [
            sum(nu[i][j] * math.log(n[i] / big) for i in range(len(names))) + shift[j]
            for j in range(m)
        ]

    def size(g: list[float]) -> float:
        return max((abs(v) for v in g), default=0.0)

    xi = [0.0] * m
    for _ in range(MAX_ITERATIONS):
        n = amounts(xi)
        big = sum(n)
        grad = gradient(xi)
        scale = max(1.0, *(abs(v) for v in shift)) if shift else 1.0
        if max((abs(g) for g in grad), default=0.0) < TOLERANCE * scale:
            break
        hess = [
            [
                sum(nu[i][j] * nu[i][k] / n[i] for i in range(len(names)))
                - dnu[j] * dnu[k] / big
                + (1e-12 * total if j == k else 0.0)
                for k in range(m)
            ]
            for j in range(m)
        ]
        step = _solve(hess, [-g for g in grad])
        dn = [sum(nu[i][j] * step[j] for j in range(m)) for i in range(len(names))]
        alpha = 1.0
        for i, d in enumerate(dn):
            if d < 0:
                alpha = min(alpha, 0.99 * n[i] / -d)
        now = phi(xi)
        slope = sum(g * s for g, s in zip(grad, step, strict=True))
        while alpha > 1e-14:
            trial = [x + alpha * s for x, s in zip(xi, step, strict=True)]
            # near the solution the Gibbs energy changes below its rounding: a step that shrinks
            # the gradient is accepted too (Phi is convex, so that step is towards the minimum)
            if min(amounts(trial)) > 0 and (
                phi(trial) <= now + 1e-4 * alpha * slope or size(gradient(trial)) < size(grad)
            ):
                break
            alpha /= 2
        else:
            raise NotConverged("no step lowers the Gibbs energy")
        xi = trial
        # relative to each amount: a species near zero moves by tiny steps that still matter
        if max(abs(alpha * d) / v for d, v in zip(dn, n, strict=True)) < 1e-13:
            # the step vanished: converged only if the gradient is (nearly) zero, else stalled
            if size(gradient(xi)) > 1e-6 * scale:
                raise NotConverged("the Newton steps stalled away from equilibrium")
            break
    else:
        raise NotConverged(f"no convergence in {MAX_ITERATIONS} Newton steps")
    # the seeds are dropped: n0 + nu t xi, with the largest t <= 1 that keeps every amount
    # non-negative (t < 1 only when a product's equilibrium amount is below its seed)
    t = 1.0
    for i in range(len(names)):
        d = sum(nu[i][j] * xi[j] for j in range(m))
        if base[i] + d < 0 and d < 0:
            t = min(t, base[i] / -d)
    xi = [t * x for x in xi]
    out = {
        n: max(base[i] + sum(nu[i][j] * xi[j] for j in range(m)), 0.0) for i, n in enumerate(names)
    }  # max() only removes rounding below zero
    return out, xi


def reaction_ln_k(
    reaction: Any, data: Mapping[str, Any], temperature: float, basis: str = "partial_pressure"
) -> float:
    """ln K of *reaction* at *temperature* on *basis*: its own ``equilibrium_constant``, else
    from the components' ideal-gas data (partial pressures). Raises ValueError naming what is
    missing or out of range, or when K is on another basis than the caller computes Q on (a
    liquid's K is never taken as a gas's)."""
    from chemeascode.domains.chemistry.thermochemistry import ln_k, missing, outside

    given = reaction.equilibrium_constant
    found = given.basis if given is not None else "partial_pressure"
    if given is not None and found != basis:
        raise ValueError(
            f"reaction {reaction.id}: its equilibrium_constant is on {found}, not on {basis} as "
            "this calculation needs"
        )
    if given is None and getattr(reaction, "phase", None) == "liquid":
        raise ValueError(
            f"reaction {reaction.id} is liquid-phase: give its equilibrium_constant (basis "
            "mole_fraction, activity or concentration); ideal-gas data give the K of the gas"
        )
    if given is not None:
        if not given.covers(temperature):
            raise ValueError(
                f"reaction {reaction.id}: {temperature:.6g} K is outside its "
                "equilibrium_constant temperature_range"
            )
        return given.ln_k(temperature)
    names = list(reaction.stoichiometry)
    lacking = missing(names, data)
    if lacking:
        raise ValueError(
            f"reaction {reaction.id}: no equilibrium_constant and no ideal_gas data for "
            + ", ".join(lacking)
        )
    beyond = outside(names, data, temperature)
    if beyond:
        raise ValueError(
            f"reaction {reaction.id}: {temperature:.6g} K is outside the ideal_gas "
            "temperature_range of " + ", ".join(beyond)
        )
    return ln_k(reaction.stoichiometry, data, temperature)


def equilibrate_real(
    reactions: Sequence[Mapping[str, float]],
    ln_k: Sequence[float],
    feed: Mapping[str, float],
    pressure: float,
    temperature: float,
    critical: Mapping[str, Any],
) -> tuple[dict[str, float], list[float]]:
    """:func:`equilibrate` of a real gas: ``K = prod (phi_i y_i P / 1 bar)^nu_i`` with the
    Peng-Robinson fugacity coefficients (:mod:`.eos`) of the outlet, by successive substitution
    of ``ln K - sum nu ln phi`` (damped when it oscillates; converged when no amount changes by
    1e-10 of the feed), phi at *temperature* K (the gas's own, not K's). Every species with a
    flow needs its critical constants (ValueError otherwise)."""
    from chemeascode.domains.chemistry.eos import fugacity_coefficients

    out, xi = equilibrate(reactions, ln_k, feed, pressure)
    total_feed = sum(v for v in feed.values() if v > 0)
    corrected = list(ln_k)
    weight, last = 1.0, math.inf
    for _ in range(200):
        total = sum(out.values())
        phi = fugacity_coefficients(
            {n: v / total for n, v in out.items()}, temperature, pressure, critical
        )
        target = [
            k - sum(nu * math.log(phi.get(n, 1.0)) for n, nu in r.items())
            for k, r in zip(ln_k, reactions, strict=True)
        ]
        size = max(abs(t - c) for t, c in zip(target, corrected, strict=True))
        if size > last:
            weight = max(weight / 2, 1 / 64)  # oscillating: a smaller step
        last = size
        corrected = [c + weight * (t - c) for t, c in zip(target, corrected, strict=True)]
        new, xi = equilibrate(reactions, corrected, feed, pressure)
        if max(abs(new[n] - out.get(n, 0.0)) for n in new) < 1e-10 * total_feed and size < 1e-9:
            return new, xi
        out = new
    raise NotConverged("the fugacity coefficients did not converge")
