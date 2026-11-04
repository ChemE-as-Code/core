"""Anolyte model ``well-mixed-carbonate`` v1: a well-mixed reservoir of a cation hydroxide
(KOH, NaOH, CsOH) taking up inorganic carbon, in instantaneous carbonate equilibrium.

An independent, concentration-basis implementation of the anolyte balance of Prats Vergel et
al. (Nat. Chem. Eng. 2025; process-library#329), formulated on conserved quantities with
equilibrium speciation instead of the authors' finite-rate kinetics:

- state: moles of the cation M+ (``cation``), total inorganic carbon C_T = CO2(aq) + HCO3- +
  CO3-2 (``carbon``), and the solution volume (``volume``, L);
- ``rates``: dM/dt and dC_T/dt from the ion fluxes (M+ and HCO3-, CO3-2 or CO2 from the cells,
  the dosing), minus the bleed at the reservoir's composition and the CO2 degassing; dV/dt from
  the solution added and the bleed. OH- and H+ in the fluxes are not states: the charge balance
  fixes them, and :func:`charge_closure` checks that the fluxes are electroneutral;
- ``speciate``: [H+] from the charge balance

  ``[M+] + [H+] = [OH-] + [HCO3-] + 2 [CO3-2]``

  with ``[OH-] = Kw / [H+]``, ``[HCO3-] = C_T K1 [H+] / D``, ``[CO3-2] = C_T K1 K2 / D``,
  ``[CO2] = C_T [H+]^2 / D``, ``D = [H+]^2 + K1 [H+] + K1 K2``; Kw = 1e-14, pK1 = 6.37,
  pK2 = 10.32 at 25 °C. The residual is strictly increasing in [H+], so the root is unique; it
  is solved on log10 [H+] by Newton's method kept inside a bracket (bisection when a Newton step
  leaves it), to 1e-13 in log10 [H+]. pH = -log10 [H+] in mol/L (concentrations, not
  activities);
- degassing (optional): ``k_L a V ([CO2] - H p_CO2)`` mol/s when the dissolved CO2 is above
  saturation (Henry's constant H = 0.034 mol/(L atm) at 25 °C), none below; without ``kla`` it
  is off.

The time to a pH threshold of this model depends on the concentrations only: it scales exactly
with the reservoir volume at volume-independent fluxes (the authors' pH stop on the H+ amount
does not; process-library#329 D1).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from chemeascode.domains.chemistry.anolyte import ReservoirFluxes, Speciation, Validity

MODEL_ID = "well-mixed-carbonate"
MODEL_VERSION = 1
#: ion product of water at 25 °C, (mol/L)^2
KW = 1e-14
#: first and second dissociation constants of carbonic acid at 25 °C
PK1 = 6.37
PK2 = 10.32
#: Henry's constant of CO2 in water at 25 °C, mol/(L atm)
HENRY_CO2 = 0.034
_LN10 = math.log(10.0)
_CARBON = {"HCO3-": 1.0, "CO3-2": 1.0, "CO3--": 1.0, "CO2": 1.0}
_CHARGE = {"OH-": -1, "H+": 1, "HCO3-": -1, "CO3-2": -2, "CO3--": -2, "CO2": 0}

ASSUMPTIONS = (
    "well mixed reservoir; instantaneous carbonate equilibrium (no finite-rate CO2 hydration)",
    "ideal solution: equilibrium constants on concentrations, Kw = 1e-14, pK1 = 6.37, "
    "pK2 = 10.32 at 25 °C; pH = -log10 [H+] (mol/L)",
    "conserved quantities: moles of the cation and of total inorganic carbon; OH- and H+ follow "
    "from the charge balance",
    "the solution volume changes only by the solution added and the bleed (water formed or "
    "consumed by the electrode reactions and the membrane is neglected)",
    "CO2 degassing k_L a V ([CO2] - H p_CO2) above saturation only, H = 0.034 mol/(L atm); off "
    "without k_L a",
)
LIMITATIONS = (
    "concentrations, not activities: at an ionic strength of 1 mol/L (1 M KOH) the activity "
    "coefficients of monovalent ions are well below 1, so the pH is a concentration-basis pH, "
    "not a measured (activity) pH, and the constants are those at infinite dilution",
    "the constants are at 25 °C; their temperature dependence is not modelled",
    "no other ions (chloride, sulfate, formate) and no solids (carbonate precipitation)",
    "dissolved CO2 above saturation stays in solution when degassing is off",
)
VALIDITY = Validity(
    ionic_strength_mol_l=(0.0, 1.5),
    ph=(2.0, 14.5),
    temperature_k=(293.15, 303.15),
    source="constants at 25 °C (±5 K claimed); compared with the authors' model of "
    "process-library#329 at 0.1 and 1 M KOH (tests/test_carbonate.py)",
)


def ions_of(cation: str) -> dict[str, int]:
    """The charge of each species the model accepts in the fluxes, for *cation* (K+)."""
    return {cation: 1, **_CHARGE}


def charge_closure(fluxes: ReservoirFluxes, cation: str) -> float:
    """The net charge (mol/s of elementary charges) the ion and dosing fluxes bring; zero
    for electroneutral fluxes. Species the model does not know count as no charge."""
    charges = ions_of(cation)
    total = 0.0
    for flows in (fluxes.ions, fluxes.dosing):
        for name, rate in flows.items():
            total += charges.get(name, 0) * rate
    return total


class WellMixedCarbonate:
    """``well-mixed-carbonate`` v1 (see the module docstring). *cation* names the cation of the
    hydroxide (``K+``); *kla_per_s* (1/s) and *co2_partial_pressure_atm* switch the degassing
    on (both are needed); *temperature_k* is checked against the validity range only."""

    id = MODEL_ID
    version = MODEL_VERSION
    state = (("cation", "mol"), ("carbon", "mol"), ("volume", "L"))
    composition_keys = ("hydroxide", "carbonate", "bicarbonate", "co2")
    validity = VALIDITY
    assumptions = ASSUMPTIONS
    limitations = LIMITATIONS

    def __init__(
        self,
        cation: str = "K+",
        kla_per_s: float | None = None,
        co2_partial_pressure_atm: float | None = None,
        temperature_k: float | None = None,
    ) -> None:
        if not cation.endswith("+") or cation.endswith("++"):
            raise ValueError(f"cation {cation!r}: a monovalent cation, e.g. K+")
        if kla_per_s is not None and kla_per_s < 0:
            raise ValueError("kla must not be negative")
        if co2_partial_pressure_atm is not None and co2_partial_pressure_atm < 0:
            raise ValueError("the CO2 partial pressure must not be negative")
        self.cation = cation
        self.kla_per_s = kla_per_s
        self.co2_partial_pressure_atm = co2_partial_pressure_atm
        self.temperature_k = temperature_k
        self.species = (cation, "OH-", "H+", "HCO3-", "CO3-2", "CO3--", "CO2")
        self._k1 = 10.0**-PK1
        self._k2 = 10.0**-PK2

    @property
    def degassing(self) -> bool:
        return bool(self.kla_per_s) and self.co2_partial_pressure_atm is not None

    def describe(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "state": [list(s) for s in self.state],
            "cation": self.cation,
            "constants": {"Kw": KW, "pK1": PK1, "pK2": PK2, "henry_co2_mol_l_atm": HENRY_CO2},
            "degassing": {
                "kla_per_s": self.kla_per_s,
                "co2_partial_pressure_atm": self.co2_partial_pressure_atm,
            }
            if self.degassing
            else None,
            "validity": self.validity.as_dict(),
            "assumptions": list(self.assumptions),
            "limitations": list(self.limitations),
        }

    # -- state ------------------------------------------------------------------------------

    def initial(self, composition: Mapping[str, float], volume_l: float) -> list[float]:
        """The state of *volume_l* L of: ``hydroxide`` (mol/L of MOH), ``carbonate`` (M2CO3),
        ``bicarbonate`` (MHCO3) and ``co2`` (dissolved CO2), each default 0."""
        unknown = sorted(set(composition) - set(self.composition_keys))
        if unknown:
            raise ValueError(
                f"composition: {', '.join(unknown)} not known; give "
                + ", ".join(self.composition_keys)
            )
        if not volume_l > 0:
            raise ValueError("the volume must be positive")
        oh = composition.get("hydroxide", 0.0)
        co3 = composition.get("carbonate", 0.0)
        hco3 = composition.get("bicarbonate", 0.0)
        co2 = composition.get("co2", 0.0)
        if min(oh, co3, hco3, co2) < 0:
            raise ValueError("composition: concentrations must not be negative")
        cation = (oh + 2 * co3 + hco3) * volume_l
        carbon = (co3 + hco3 + co2) * volume_l
        return [cation, carbon, volume_l]

    def losses(self, state: Sequence[float]) -> dict[str, float]:
        """mol/s of CO2 degassing (above saturation; 0 when off or below it)."""
        if not self.degassing:
            return {"CO2": 0.0}
        volume = state[2]
        co2 = self.speciate(state).concentrations["CO2"]
        saturation = HENRY_CO2 * (self.co2_partial_pressure_atm or 0.0)
        return {"CO2": (self.kla_per_s or 0.0) * volume * max(co2 - saturation, 0.0)}

    def rates(self, state: Sequence[float], fluxes: ReservoirFluxes, t: float) -> list[float]:
        """d(cation, carbon, volume)/dt in mol/s, mol/s and L/s."""
        cation, carbon, volume = state
        unknown = [
            name
            for flows in (fluxes.ions, fluxes.dosing)
            for name in flows
            if name not in self.species
        ]
        if unknown:
            raise ValueError(f"{self.id} carries no {', '.join(sorted(set(unknown)))}")
        bleed = fluxes.bleed / volume if volume > 0 else 0.0
        d_cation = fluxes.ions.get(self.cation, 0.0) + fluxes.dosing.get(self.cation, 0.0)
        d_carbon = sum(
            rate * _CARBON.get(name, 0.0)
            for flows in (fluxes.ions, fluxes.dosing)
            for name, rate in flows.items()
        )
        d_cation -= bleed * cation
        d_carbon -= bleed * carbon + self.losses(state)["CO2"]
        return [d_cation, d_carbon, fluxes.volume_in - fluxes.bleed]

    # -- speciation -------------------------------------------------------------------------

    def _residual(self, x: float, m: float, c: float) -> tuple[float, float]:
        """The charge balance at log10 [H+] = x and its derivative in x."""
        h = 10.0**x
        k1, k2 = self._k1, self._k2
        d = h * h + k1 * h + k1 * k2
        n = k1 * h + 2 * k1 * k2
        g = n / d
        dg = (k1 * d - n * (2 * h + k1)) / (d * d)
        f = m + h - KW / h - c * g
        df = (1.0 + KW / (h * h) - c * dg) * h * _LN10
        return f, df

    def speciate(self, state: Sequence[float], volume_l: float | None = None) -> Speciation:
        """The pH and the species of *state* (*volume_l*: the volume, default the state's)."""
        cation, carbon = state[0], state[1]
        volume = state[2] if volume_l is None else volume_l
        if not volume > 0:
            raise ValueError("the reservoir is empty: no speciation")
        m = max(cation, 0.0) / volume
        c = max(carbon, 0.0) / volume
        lo, hi = -20.0, 2.0
        while self._residual(lo, m, c)[0] > 0:  # a very large cation excess
            lo -= 5.0
        while self._residual(hi, m, c)[0] < 0:  # a very large carbon excess
            hi += 5.0
        # start from the strong-base estimate where the cation dominates
        excess = m - c
        x = math.log10(KW / excess) if excess > 1e-7 else 0.5 * (lo + hi)
        x = min(max(x, lo), hi)
        iterations = 0
        for iterations in range(1, 200):  # noqa: B007 - the count is reported
            f, df = self._residual(x, m, c)
            if f == 0:
                break
            if f > 0:
                hi = x
            else:
                lo = x
            step = -f / df if df > 0 else math.inf
            if abs(step) < 1e-13:
                x += step
                break
            nxt = x + step
            if not lo <= nxt <= hi:
                nxt = 0.5 * (lo + hi)
            if abs(nxt - x) < 1e-13 or hi - lo < 1e-13:
                x = nxt
                break
            x = nxt
        h = 10.0**x
        k1, k2 = self._k1, self._k2
        d = h * h + k1 * h + k1 * k2
        concentrations = {
            self.cation: m,
            "H+": h,
            "OH-": KW / h,
            "CO2": c * h * h / d,
            "HCO3-": c * k1 * h / d,
            "CO3-2": c * k1 * k2 / d,
        }
        residual = (
            m + h - concentrations["OH-"] - concentrations["HCO3-"] - 2 * concentrations["CO3-2"]
        )
        strength = 0.5 * (
            m + h + concentrations["OH-"] + concentrations["HCO3-"] + 4 * concentrations["CO3-2"]
        )
        return Speciation(-x, concentrations, strength, residual, iterations)
