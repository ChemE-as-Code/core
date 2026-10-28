"""Transport between gas and catalyst in a fixed bed: the effectiveness factor of an intrinsic
rate law, and the Weisz-Prater and Mears criteria of the rates the bed uses.

With the catalyst's effective diffusivity ``De`` (m2/s; given, or the bed's gas
``diffusivity`` times the particle's ``porosity / tortuosity``), the particle's density
``rho_p`` and the characteristic length ``L = d_p / 6`` (volume over outer surface of a
sphere; Aris), per reaction and its key reactant (the first with a positive order) at the gas
concentration ``C`` (kmol/m3) and order ``n``:

- generalised Thiele modulus ``phi = L sqrt((n + 1) / 2 * r rho_p / (De C))`` of an intrinsic
  rate ``r`` (kmol/(kg s)), effectiveness ``eta = tanh(phi) / phi`` (the generalised form, within
  about 15 % of the exact sphere for phi of order 1, exact at both ends);
- Weisz-Prater on the particle radius, ``C_WP = r_obs rho_p R_p^2 / (De C)`` of the rate the bed
  uses (Fogler, Elements of Chemical Reaction Engineering): below 1 internal diffusion does
  not limit; above, the rate is not intrinsic at this particle size;
- Mears ``r_obs rho_b (d_p / 2) n / (k_c C)`` with ``k_c`` from Ranz-Marshall,
  ``Sh = 2 + 0.6 Re^(1/2) Sc^(1/3)`` on the particle diameter (the gas viscosity, density and
  diffusivity): below 0.15 the external film does not limit.

Rate laws are effective rates of the particles unless they say ``scale: intrinsic``: then the
bed multiplies them by ``eta`` at each point, and needs the data. Pure Python.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from chemeascode.domains.chemistry.rates import R

#: Below these, internal diffusion (Weisz-Prater on the radius, Fogler) and the external film
#: (Mears) do not limit the rate.
WEISZ_PRATER = 1.0
MEARS = 0.15


def effective_diffusivity(catalyst: Any, bed: Any) -> float | None:
    """m2/s: the catalyst's ``effective_diffusivity``, else the bed's gas ``diffusivity`` times
    the particle's porosity over its tortuosity; None when neither is given."""
    physical = getattr(catalyst, "physical", None)
    given = getattr(physical, "effective_diffusivity", None)
    if given:
        return given
    porosity = getattr(physical, "porosity", None)
    tortuosity = getattr(physical, "tortuosity", None)
    gas = getattr(bed, "diffusivity", None)
    if porosity and tortuosity and gas:
        return gas * porosity / tortuosity
    return None


def lacking(catalyst: Any, bed: Any) -> list[str]:
    """What the transport checks need and the bed or catalyst does not give."""
    physical = getattr(catalyst, "physical", None)
    found = []
    if not getattr(physical, "particle_diameter", None):
        found.append("the catalyst's particle_diameter")
    if not getattr(physical, "particle_density", None):
        found.append("the catalyst's particle_density")
    if effective_diffusivity(catalyst, bed) is None:
        found.append(
            "the catalyst's effective_diffusivity (or porosity and tortuosity with the bed's "
            "diffusivity)"
        )
    return found


def key_order(law: Any, stoichiometry: Mapping[str, float]) -> tuple[str, float] | None:
    """The key reactant of a rate law and its order: the first reactant with a positive
    order; None when there is none."""
    for name, order in law.orders.items():
        if order > 0 and stoichiometry.get(name, 0.0) < 0:
            return name, order
    return None


def concentration(y: Mapping[str, float], name: str, t: float, p: float) -> float:
    """kmol/m3 of *name* in an ideal gas of mole fractions *y* at *t* K and *p* kPa."""
    return y.get(name, 0.0) * p / (R * t)


def thiele(
    rate_per_kg: float, order: float, c: float, rho_p: float, length: float, de: float
) -> float:
    """The generalised Thiele modulus of an intrinsic rate (see the module docstring)."""
    if rate_per_kg <= 0 or c <= 0:
        return 0.0
    return length * math.sqrt((order + 1) / 2 * rate_per_kg * rho_p / (de * c))


def effectiveness(phi: float) -> float:
    """``tanh(phi) / phi`` (1 at phi = 0)."""
    return 1.0 if phi < 1e-8 else math.tanh(phi) / phi


def criteria(
    reactions: list[Any],
    rates_per_kg: list[float],
    y: Mapping[str, float],
    t: float,
    p: float,
    catalyst: Any,
    bed: Any,
    bulk: float,
    mass_flux: float | None,
    gas_density: float | None,
) -> dict[str, Any]:
    """Weisz-Prater and Mears of each reaction at one point of the bed (*rates_per_kg* the
    rates the bed uses there, kmol/(kg s)): ``{reaction id: {key, weisz_prater, mears}}``;
    Mears is None without the mass flux, the gas density, viscosity and diffusivity."""
    physical = catalyst.physical
    dp = physical.particle_diameter
    rho_p = physical.particle_density
    de = effective_diffusivity(catalyst, bed)
    found: dict[str, Any] = {}
    for r, value in zip(reactions, rates_per_kg, strict=True):
        key = key_order(r.rate, r.stoichiometry)
        if key is None or value <= 0:
            continue
        name, order = key
        c = concentration(y, name, t, p)
        if c <= 0:
            continue
        entry: dict[str, Any] = {
            "key": name,
            "weisz_prater": value * rho_p * (dp / 2) ** 2 / (de * c),
        }
        mu, gas = getattr(bed, "viscosity", None), getattr(bed, "diffusivity", None)
        if mass_flux and gas_density and mu and gas:
            reynolds = mass_flux * dp / mu
            schmidt = mu / (gas_density * gas)
            sherwood = 2.0 + 0.6 * math.sqrt(reynolds) * schmidt ** (1 / 3)
            k_c = sherwood * gas / dp
            entry["mears"] = value * bulk * (dp / 2) * order / (k_c * c)
        else:
            entry["mears"] = None
        found[r.id] = entry
    return found
