"""Liquid-phase reactions: the composition measures a liquid rate law or equilibrium constant is
written on, and the equilibrium of a liquid mixture.

A liquid reaction's equilibrium constant and rate law name their basis (``basis`` of an
``equilibrium_constant``, ``driving`` of a ``rate``):

- ``mole_fraction``: ``x_i`` (ideal solution);
- ``activity``: ``a_i = gamma_i x_i``, the activity coefficients from UNIFAC (``thermo``,
  extra ``props``; components need a CAS number), or 1 with ``activity_model: ideal``;
- ``concentration``: ``c_i = x_i / v`` in kmol/m3, with ``v = sum x_j v_j`` from each
  component's ``liquid_molar_volume`` (m3/kmol; ideal mixing).

Partial pressures are the measure of a gas: a liquid reaction on ``partial_pressure`` is refused
here (``cheme.reaction-phase-basis`` warns in validate). The equilibrium
(:func:`equilibrate_liquid`) is the ideal-solution equilibrium of :func:`.equilibrium.equilibrate`
(``K_x = prod x^nu``) with ``ln K_x = ln K - correction(x)`` updated by successive substitution
until no amount changes by 1e-10 of the feed: ``sum nu ln gamma`` on an activity basis,
``-dnu ln v`` on a concentration basis. Every component of the feed is in the liquid, solvents
and inerts included.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from chemeascode.domains.chemistry.equilibrium import NotConverged, equilibrate
from chemeascode.domains.chemistry.thermochemistry import P_STANDARD

#: The bases a liquid reaction's K or rate law may be written on.
LIQUID_BASES = ("mole_fraction", "activity", "concentration")
MAX_ITERATIONS = 200

#: (component ids, temperature K, mole fractions) -> activity coefficient per component.
ActivityModel = Callable[[Sequence[str], float, Mapping[str, float]], Mapping[str, float]]


@dataclass(frozen=True)
class Liquid:
    """What a liquid composition measure needs beyond the mole fractions."""

    #: m3/kmol per component (``liquid_molar_volume``); needed on a concentration basis.
    molar_volumes: Mapping[str, float | None]
    #: The activity coefficients; needed on an activity basis. None: not available.
    activity: ActivityModel | None = None

    def molar_volume(self, fractions: Mapping[str, float]) -> float:
        """``v = sum x_i v_i`` (m3/kmol). Raises ValueError naming the components without one."""
        lacking = sorted(n for n, x in fractions.items() if x > 0 and not self.molar_volumes.get(n))
        if lacking:
            raise ValueError("no liquid_molar_volume for " + ", ".join(lacking))
        return sum(x * (self.molar_volumes[n] or 0.0) for n, x in fractions.items() if x > 0)

    def gammas(self, temperature: float, fractions: Mapping[str, float]) -> Mapping[str, float]:
        if self.activity is None:
            raise ValueError("no activity model: give the components their CAS numbers")
        return self.activity(list(fractions), temperature, fractions)


def measures(
    basis: str, fractions: Mapping[str, float], temperature: float, liquid: Liquid
) -> dict[str, float]:
    """The composition measure of a liquid of mole *fractions* on *basis*
    (:data:`LIQUID_BASES`): x, gamma x or x / v (kmol/m3). Raises ValueError for another basis
    or a missing input."""
    if basis == "mole_fraction":
        return dict(fractions)
    if basis == "activity":
        gamma = liquid.gammas(temperature, fractions)
        return {n: gamma.get(n, 1.0) * x for n, x in fractions.items()}
    if basis == "concentration":
        v = liquid.molar_volume(fractions)
        return {n: x / v for n, x in fractions.items()}
    raise ValueError(
        f"a liquid-phase reaction is not written on {basis}; use mole_fraction, activity or "
        "concentration"
    )


def ln_quotient(
    stoichiometry: Mapping[str, float],
    basis: str,
    fractions: Mapping[str, float],
    temperature: float,
    liquid: Liquid,
) -> float:
    """ln Q of a liquid on *basis*; -inf when a product is absent, +inf when a reactant is."""
    a = measures(basis, fractions, temperature, liquid)
    if any(a.get(n, 0.0) <= 0 for n, nu in stoichiometry.items() if nu < 0):
        return math.inf
    if any(a.get(n, 0.0) <= 0 for n, nu in stoichiometry.items() if nu > 0):
        return -math.inf
    return sum(nu * math.log(a[n]) for n, nu in stoichiometry.items())


def _correction(
    reaction: Mapping[str, float], basis: str, x: Mapping[str, float], t: float, liquid: Liquid
) -> float:
    """``ln K - ln K_x`` of *reaction* at mole fractions *x*."""
    if basis == "mole_fraction":
        return 0.0
    if basis == "activity":
        gamma = liquid.gammas(t, x)
        return sum(nu * math.log(gamma.get(n, 1.0)) for n, nu in reaction.items())
    if basis == "concentration":
        return -sum(reaction.values()) * math.log(liquid.molar_volume(x))
    raise ValueError(f"a liquid-phase reaction is not written on {basis}")


def equilibrate_liquid(
    reactions: Sequence[Mapping[str, float]],
    ln_k: Sequence[float],
    bases: Sequence[str],
    feed: Mapping[str, float],
    temperature: float,
    liquid: Liquid,
) -> tuple[dict[str, float], list[float]]:
    """The equilibrium outlet (species -> kmol/h) of the liquid *feed* (kmol/h) through
    *reactions* with ``ln K`` on *bases* (one per reaction), at *temperature* K, and the
    extents. Raises :class:`~.equilibrium.NotConverged`, or ValueError naming a missing input."""
    total = sum(v for v in feed.values() if v > 0)
    if total <= 0:
        raise NotConverged("the feed is empty")

    def fractions(out: Mapping[str, float]) -> dict[str, float]:
        big = sum(out.values())
        return {n: v / big for n, v in out.items()}

    def solve(x: Mapping[str, float]) -> tuple[dict[str, float], list[float]]:
        k_x = [
            k - _correction(r, b, x, temperature, liquid)
            for r, k, b in zip(reactions, ln_k, bases, strict=True)
        ]
        # equilibrate's shift dnu ln(P / 1 bar) vanishes at 1 bar: K_x = prod x^nu
        return equilibrate(reactions, k_x, feed, P_STANDARD)

    if all(b == "mole_fraction" for b in bases):
        return solve({})
    x = fractions({n: max(v, 0.0) for n, v in feed.items()})
    out, xi = solve(x)
    damping = 1.0
    previous: list[float] | None = None
    for _ in range(MAX_ITERATIONS):
        x_new = fractions(out)
        trial = {n: (1 - damping) * x.get(n, 0.0) + damping * v for n, v in x_new.items()}
        new_out, new_xi = solve(trial)
        change = max(abs(new_out.get(n, 0.0) - out.get(n, 0.0)) for n in new_out | out)
        # an extent that turned back (up then down, or down then up) is oscillating: damp
        if previous is not None and any(
            (a - b) * (b - c) < 0 for a, b, c in zip(new_xi, xi, previous, strict=True)
        ):
            damping = max(damping / 2, 0.05)
        previous = xi
        out, xi, x = new_out, new_xi, trial
        if change < 1e-10 * total:
            return out, xi
    raise NotConverged("the liquid-phase equilibrium did not converge (activity coefficients)")


def unifac_model(cas: Mapping[str, str]) -> ActivityModel:
    """UNIFAC activity coefficients (``thermo``, extra ``props``) of components by their CAS
    numbers (*cas*: component id -> CAS). The model raises ValueError naming a component
    without a CAS number or without UNIFAC groups."""
    from chemeascode.integrations.thermo import unifac_activity_coefficients

    def model(
        names: Sequence[str], temperature: float, fractions: Mapping[str, float]
    ) -> Mapping[str, float]:
        present = [n for n in names if fractions.get(n, 0.0) > 0]
        lacking = [n for n in present if not cas.get(n)]
        if lacking:
            raise ValueError("no CAS number for the activity coefficients of " + ", ".join(lacking))
        gammas = unifac_activity_coefficients(
            [cas[n] for n in present], temperature, [fractions[n] for n in present]
        )
        found = dict(zip(present, gammas, strict=True))
        return {n: found.get(n, 1.0) for n in names}

    return model


def ideal_model(names: Sequence[str], temperature: float, fractions: Any) -> Mapping[str, float]:
    """Activity coefficients of an ideal solution: 1."""
    return dict.fromkeys(names, 1.0)
