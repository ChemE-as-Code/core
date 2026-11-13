"""Semi-batch kinetics beyond one temperature and one liquid (ADR 0074), for the batch and
semi-batch of :mod:`.stirred_tank`:

- an **initiation** (``batch.initiation``): before its ``time`` the rate laws of its reactions
  run at ``factor`` of their rate; a dose with ``after_initiation`` starts counting from it (a
  feed interlocked on a positive initiation). The **uninitiated** scenario keeps the factor
  for good and drops the waiting doses: what accumulates when the dosing goes on into a charge
  that never initiates;
- a **temperature programme** (``batch.program``): an isothermal batch's temperature linear
  between ``(s, K)`` points, and **reflux** (``batch.heat: reflux``): the liquid at its bubble
  point at the vessel's pressure, its vapour condensed and returned (total reflux, no vapour
  hold-up), from :func:`bubble_point` (Raoult's law);
- the **light** of a photochemical rate law (``batch.light``): ``q_0 = P lambda / (h c N_A)``
  photons per second of the lamp's radiant power ``P`` at the wavelength ``lambda`` (CODATA
  2022 exact constants), of which the content absorbs ``1 - 10^(-epsilon c l)`` (Beer-Lambert,
  decadic).

The integrator splits its run at the :func:`breaks` these give, so that within a segment each
is constant (:class:`Regime`): a reaction's factor, the lamp, the programme's slope. Pure
Python.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

#: J s, the Planck constant (CODATA 2022, exact; NIST, physics.nist.gov/cgi-bin/cuu/Value?h).
PLANCK = 6.62607015e-34
#: m/s, the speed of light in vacuum (CODATA 2022, exact; physics.nist.gov/cgi-bin/cuu/Value?c).
LIGHT_SPEED = 299792458.0
#: 1/mol, the Avogadro constant (CODATA 2022, exact; physics.nist.gov/cgi-bin/cuu/Value?na).
AVOGADRO = 6.02214076e23


#: What each ADR 0074 term takes for granted (reported by :mod:`.model_basis` where declared).
ASSUMPTIONS = {
    "initiation": "an induction period as a switch: the rate laws at a declared factor until "
    "the declared initiation time, then at their own (the initiation is not predicted)",
    "solids": "a solid phase out of the liquid (none of it dissolved unless a reaction says "
    "so), at its own density; a rate per m3 is per m3 of the liquid",
    "surface": "a rate per m2 of a solid on equal spheres charged at the start, shrinking at a "
    "constant number (no fines, breakage or passivation; mass transfer only as the rate law "
    "states it)",
    "program": "the content follows the temperature programme exactly (the jacket never limits)",
    "reflux": "at reflux: the liquid at its bubble point (Raoult's law), total reflux with no "
    "vapour hold-up, the jacket and condenser never limiting",
    "light": "the light monochromatic, absorbed by one absorber along one path length "
    "(Beer-Lambert), the content well mixed (no light gradient in the rate)",
}


def assumptions(batch: Any) -> list[str]:
    """The :data:`ASSUMPTIONS` of the ADR 0074 terms *batch* declares."""
    surface = any(s.diameter or s.specific_area for s in getattr(batch, "solids", {}).values())
    declared = {
        "initiation": getattr(batch, "initiation", None) is not None,
        "solids": bool(getattr(batch, "solids", None)),
        "surface": surface,
        "program": getattr(batch, "program", None) is not None,
        "reflux": getattr(batch, "heat", None) == "reflux",
        "light": getattr(batch, "light", None) is not None,
    }
    return [ASSUMPTIONS[k] for k, on in declared.items() if on]


@dataclass(frozen=True)
class Regime:
    """What holds between two break points of a batch: each reaction's rate factor (None:
    every one 1), whether the lamp is on, and the programme's slope (K/s)."""

    factors: tuple[float, ...] | None = None
    lit: bool = True
    slope: float = 0.0


#: A batch with none of ADR 0074's terms.
PLAIN = Regime()


def photon_flux(watts: float, wavelength_nm: float) -> float:
    """kmol/s of photons in *watts* W of radiant power at *wavelength_nm* nm: ``P lambda / (h c
    N_A)``, mol/s, over 1000."""
    return watts * wavelength_nm * 1e-9 / (PLANCK * LIGHT_SPEED * AVOGADRO) / 1000.0


def absorbed_share(light: Any, concentration: float) -> float:
    """The share of *light* (a :class:`~.schema.Light`) the content absorbs at its absorber's
    *concentration* (kmol/m3): ``1 - 10^(-epsilon c l)``; all of it without an absorber."""
    if light.absorber is None:
        return 1.0
    return 1.0 - 10.0 ** (-light.absorptivity * max(concentration, 0.0) * light.path_length)


def breaks(batch: Any) -> list[float]:
    """s after the charge where an ADR 0074 term changes: the initiation, the programme's points
    and the lamp's windows; empty without them."""
    found: set[float] = set()
    if (start := getattr(batch, "initiation", None)) is not None:
        found.add(start.time)
    if (program := getattr(batch, "program", None)) is not None:
        found |= {t for t, _ in program.points}
    if (light := getattr(batch, "light", None)) is not None:
        found |= {x for window in light.on for x in window}
    return sorted(x for x in found if x > 0)


def regime(
    batch: Any, reactions: Sequence[Any], a: float, b: float | None, uninitiated: bool = False
) -> Regime:
    """The :class:`Regime` of *batch* from *a* to *b* s (None: open-ended); *uninitiated*: the
    initiation never comes."""
    start = getattr(batch, "initiation", None)
    light = getattr(batch, "light", None)
    program = getattr(batch, "program", None)
    if start is None and light is None and program is None:
        return PLAIN
    mid = a + 1.0 if b is None else (a + b) / 2
    lit = light is None or light.lit(mid)
    factors = None
    if start is not None or light is not None:
        found = []
        for r in reactions:
            f = 1.0
            held = start is not None and (not start.reactions or r.id in start.reactions)
            if held and (uninitiated or mid < start.time):
                f = start.factor
            if r.rate is not None and r.rate.form == "photochemical" and not lit:
                f = 0.0
            found.append(f)
        factors = tuple(found)
    slope = 0.0
    if program is not None and b is not None and b > a:
        slope = (program.at(b) - program.at(a)) / (b - a)
    return Regime(factors, lit, slope)


def saturation_pressure(comp: Any, temperature: float) -> float | None:
    """kPa of *comp*'s vapour at *temperature* K: its Antoine ``vapour_pressure``, else
    Clausius-Clapeyron from ``normal_boiling_point`` and ``heat_of_vaporization``; 0 for a
    component that does not boil (neither given, or ``phase: solid``); None when it boils but
    lacks the data (a normal boiling point only)."""
    from chemeascode.domains.chemistry.thermochemistry import R

    if getattr(comp, "phase", None) == "solid":
        return 0.0
    vapour = getattr(comp, "vapour_pressure", None)
    if vapour is not None:
        return vapour.kpa(temperature)
    normal = getattr(comp, "normal_boiling_point", None)
    if not normal:
        return 0.0
    heat = getattr(comp, "heat_of_vaporization", None)
    if not heat:
        return None
    exponent = -heat / R * (1.0 / temperature - 1.0 / normal)
    return 101.325 * math.exp(min(exponent, 700.0))


def bubble_point(
    moles: Mapping[str, float],
    comps: Mapping[str, Any],
    pressure: float,
    activity: Mapping[str, float] | None = None,
    left_out: Sequence[str] = (),
) -> tuple[float | None, list[str]]:
    """K: the bubble point of the liquid *moles* (kmol by component) at *pressure* kPa(a), its
    *left_out* components counted in the liquid but not boiling (they leave or boil off), and
    the components lacking a vapour pressure (then None). None too when nothing boils."""
    activity = activity or {}
    total = sum(v for v in moles.values() if v > 0)
    if total <= 0:
        return None, []
    x = {n: v / total for n, v in moles.items() if v > 0 and n not in left_out}
    lacking = sorted(n for n in x if saturation_pressure(comps.get(n), 300.0) is None)
    if lacking:
        return None, lacking

    def excess(t: float) -> float:
        return (
            sum(
                activity.get(n, 1.0) * xi * (saturation_pressure(comps.get(n), t) or 0.0)
                for n, xi in x.items()
            )
            - pressure
        )

    low, high = 20.0, 5000.0
    if excess(high) < 0:
        return None, []
    if excess(low) >= 0:
        return low, []
    for _ in range(200):
        mid = 0.5 * (low + high)
        if excess(mid) < 0:
            low = mid
        else:
            high = mid
        if high - low < 1e-10:
            break
    return 0.5 * (low + high), []
