"""The Peng-Robinson equation of state for gas mixtures: fugacity coefficients for equilibria at
high pressure.

``P = R T / (v - b) - a alpha / (v^2 + 2 b v - b^2)`` with ``a = 0.45724 R^2 Tc^2 / Pc`` and
``b = 0.07780 R Tc / Pc`` (the exact constants :data:`OMEGA_A`, :data:`OMEGA_B`),
``alpha = (1 + kappa (1 - sqrt(T / Tc)))^2`` and
``kappa = 0.37464 + 1.54226 omega - 0.26992 omega^2`` (Peng and Robinson, Ind. Eng. Chem.
Fundam. 15 (1976) 59), van der Waals mixing without interaction parameters (k_ij = 0), and the
largest root of the cubic in Z (the vapour). Pure Python.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

from pydantic import Field

from chemeascode.foundation.schema_base import Provenance, Strict

#: kJ/(kmol K)
R = 8.314462618
#: The exact roots behind the paper's rounded 0.45724 and 0.07780 (as thermo uses them).
OMEGA_A = 0.45723552892138218938
OMEGA_B = 0.077796073903888455972


class Critical(Strict):
    """Critical constants of a component."""

    Tc: float = Field(gt=0, description="K")
    Pc: float = Field(gt=0, description="kPa")
    omega: float = Field(description="acentric factor")
    provenance: Provenance = "given"
    source: str = ""


def _cubic_largest(c2: float, c1: float, c0: float) -> float:
    """The largest real root of z^3 + c2 z^2 + c1 z + c0."""
    q = (3 * c1 - c2 * c2) / 9
    r = (9 * c2 * c1 - 27 * c0 - 2 * c2**3) / 54
    disc = q**3 + r**2
    if disc >= 0:  # one real root (or a triple root: q = r = 0)
        s = math.copysign(abs(r + math.sqrt(disc)) ** (1 / 3), r + math.sqrt(disc))
        t = math.copysign(abs(r - math.sqrt(disc)) ** (1 / 3), r - math.sqrt(disc))
        return s + t - c2 / 3
    theta = math.acos(max(-1.0, min(1.0, r / math.sqrt(-(q**3)))))
    roots = [2 * math.sqrt(-q) * math.cos((theta + 2 * math.pi * k) / 3) - c2 / 3 for k in range(3)]
    return max(roots)


def fugacity_coefficients(
    fractions: Mapping[str, float],
    temperature: float,
    pressure: float,
    critical: Mapping[str, Critical],
) -> dict[str, float]:
    """phi of every component of the gas mixture of mole *fractions* at *temperature* K and
    *pressure* kPa; ValueError when a component lacks critical constants."""
    names = [n for n, y in fractions.items() if y > 0]
    lacking = [n for n in names if critical.get(n) is None]
    if lacking:
        raise ValueError("no critical constants for " + ", ".join(lacking))
    a, b = {}, {}
    for n in names:
        c = critical[n]
        kappa = 0.37464 + 1.54226 * c.omega - 0.26992 * c.omega**2
        alpha = (1 + kappa * (1 - math.sqrt(temperature / c.Tc))) ** 2
        a[n] = OMEGA_A * R**2 * c.Tc**2 / c.Pc * alpha
        b[n] = OMEGA_B * R * c.Tc / c.Pc
    total = sum(fractions[n] for n in names)
    y = {n: fractions[n] / total for n in names}
    a_mix = sum(y[i] * y[j] * math.sqrt(a[i] * a[j]) for i in names for j in names)
    b_mix = sum(y[i] * b[i] for i in names)
    big_a = a_mix * pressure / (R * temperature) ** 2
    big_b = b_mix * pressure / (R * temperature)
    z = _cubic_largest(
        -(1 - big_b), big_a - 3 * big_b**2 - 2 * big_b, -(big_a * big_b - big_b**2 - big_b**3)
    )
    out = {}
    sqrt2 = math.sqrt(2.0)
    for i in names:
        shared = sum(y[j] * math.sqrt(a[i] * a[j]) for j in names)
        ln_phi = (
            b[i] / b_mix * (z - 1)
            - math.log(z - big_b)
            - big_a
            / (2 * sqrt2 * big_b)
            * (2 * shared / a_mix - b[i] / b_mix)
            * math.log((z + (1 + sqrt2) * big_b) / (z + (1 - sqrt2) * big_b))
        )
        out[i] = math.exp(ln_phi)
    return out


def lookup_critical(identifier: str) -> Critical:
    """The critical constants of *identifier* from ``chemicals`` (extra ``props``), with their
    source."""
    from chemeascode.integrations.thermo import critical_constants

    found = critical_constants(identifier)
    sources = found["sources"]
    return Critical(
        Tc=found["Tc"],
        Pc=found["Pc"],
        omega=found["omega"],
        provenance="given",
        source=f"chemicals: Tc {sources['Tc']}, Pc {sources['Pc']}, omega {sources['omega']}",
    )
