"""Rate laws of reactions: power law and Langmuir-Hinshelwood-Hougen-Watson (LHHW).

A reaction's ``rate`` (in ``process/reactions.yaml``) gives its rate per kilogram of catalyst
(``basis: catalyst_mass``, kmol/(kg s)) or per cubic metre of reactor (``basis: volume``,
kmol/(m3 s)), per kmol of extent of the reaction as written::

    power law:  r = k(T) prod(c_i^a_i) (1 - Q/K)
    LHHW:       r = k(T) prod(c_i^a_i) (1 - Q/K) / (1 + sum_j K_j(T) prod(c_i^b_ij))^m

with ``c_i`` the partial pressures in bar (``driving: partial_pressure``) or the
concentrations in kmol/m3 (``driving: concentration``, ideal gas: ``y P / (R T)``); in a
liquid (:mod:`.liquid`) the mole fractions (``driving: mole_fraction``), the activities
(``driving: activity``) or the concentrations ``x / v``,
``k(T) = A (T/T_ref)^n exp(-Ea / (R T))`` (Ea in kJ/kmol, which is J/mol), each adsorption
constant ``K_j = A_j exp(-dH_j / (R T))``, and the factor ``(1 - Q/K)`` only with
``reverse: equilibrium`` (Q the reaction quotient on the basis K is written on: partial
pressures in bar for a gas, the liquid's measure for a liquid). Pure Python.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from chemeascode.foundation.schema_base import Provenance, Strict
from chemeascode.foundation.uncertainty import Uncertainty

#: kJ/(kmol K)
R = 8.314462618
#: kPa
P_STANDARD = 100.0


class Arrhenius(Strict):
    """``k = A (T/T_ref)^n exp(-Ea / (R T))``, in the rate law's units."""

    A: float = Field(gt=0, description="At T_ref, in the units of the rate law.")
    Ea: float = Field(default=0.0, description="kJ/kmol (numerically J/mol)")
    n: float = 0.0
    T_ref: float = Field(default=1.0, gt=0, description="K")

    def k(self, temperature: float) -> float:
        return (
            self.A * (temperature / self.T_ref) ** self.n * math.exp(-self.Ea / (R * temperature))
        )


class Adsorption(Strict):
    """One term of an LHHW denominator: ``K = A exp(-dH / (R T))`` times its species'
    driving forces to their exponents (no species: a constant term)."""

    A: float = Field(gt=0)
    dH: float = Field(default=0.0, description="kJ/kmol; negative: adsorption is exothermic")
    exponents: dict[str, float] = Field(default_factory=dict, description="component id -> b")

    def term(self, temperature: float, driving: Mapping[str, float]) -> float:
        k = self.A * math.exp(-self.dH / (R * temperature))
        return k * math.prod(driving.get(n, 0.0) ** b for n, b in self.exponents.items())


class RateUncertainty(Strict):
    """The uncertainty of a rate law's Arrhenius parameters, each relative to its value (a
    fit's intervals: A lognormal, Ea normal)."""

    A: Uncertainty | None = None
    Ea: Uncertainty | None = None


class RateLaw(Strict):
    """The rate of one reaction (see the module docstring)."""

    form: Literal["power_law", "lhhw"]
    basis: Literal["catalyst_mass", "volume"] = Field(
        description="catalyst_mass: kmol/(kg_cat s); volume: kmol/(m3 s)"
    )
    driving: Literal["partial_pressure", "concentration", "mole_fraction", "activity"] = Field(
        description="partial_pressure: bar (gas); concentration: kmol/m3; mole_fraction, "
        "activity: a liquid's x or gamma x (domains/chemistry/liquid.py)"
    )
    k: Arrhenius
    orders: dict[str, float] = Field(
        default_factory=dict, description="component id -> its exponent in the forward term"
    )
    reverse: Literal["none", "equilibrium"] = Field(
        default="none",
        description="equilibrium: times (1 - Q/K), so the rate is zero at equilibrium",
    )
    adsorption: list[Adsorption] = Field(default_factory=list, description="LHHW denominator")
    power: float = Field(default=1.0, gt=0, description="LHHW: the denominator's exponent m")
    catalyst: str = Field(
        default="",
        description="The catalyst it holds for (an id of process/catalysts.yaml).",
    )
    temperature_range: tuple[float, float] | None = Field(default=None, description="K")
    scale: Literal["effective", "intrinsic"] = Field(
        default="effective",
        description="effective: the particles' rate as used (the default); intrinsic: the "
        "catalyst's own rate, which a fixed bed multiplies by its effectiveness factor.",
        exclude_if=lambda value: value == "effective",
    )
    provenance: Provenance
    source: str = ""
    uncertainty: RateUncertainty | None = Field(
        default=None,
        description="Of A and Ea, relative: cheme process reactor-uncertainty.",
        exclude_if=lambda value: value is None,
    )

    @field_validator("temperature_range")
    @classmethod
    def _range(cls, value: tuple[float, float] | None) -> tuple[float, float] | None:
        if value is not None and not 0 < value[0] < value[1]:
            raise ValueError("temperature_range is (min, max) in K, 0 < min < max")
        return value

    @model_validator(mode="after")
    def _form(self) -> RateLaw:
        if self.form == "power_law" and (self.adsorption or self.power != 1.0):
            raise ValueError("a power law has no adsorption terms or power; use form: lhhw")
        if self.form == "lhhw" and not self.adsorption:
            raise ValueError("an LHHW rate needs adsorption terms")
        return self

    def species(self) -> list[str]:
        """Every component id the rate law names."""
        names = list(self.orders)
        for a in self.adsorption:
            names += [n for n in a.exponents if n not in names]
        return names

    def covers(self, temperature: float) -> bool:
        lo, hi = self.temperature_range or (0.0, math.inf)
        return lo <= temperature <= hi


def driving_forces(
    law: RateLaw,
    fractions: Mapping[str, float],
    temperature: float,
    pressure: float,
    liquid: Any = None,
) -> dict[str, float]:
    """Partial pressures (bar) or concentrations (kmol/m3) of an ideal gas of mole *fractions*
    at *temperature* K and *pressure* kPa; with *liquid* (a :class:`.liquid.Liquid`), the
    liquid's measure on the law's ``driving`` (ValueError for partial pressures)."""
    if liquid is not None:
        from chemeascode.domains.chemistry.liquid import measures

        return measures(law.driving, fractions, temperature, liquid)
    if law.driving in ("mole_fraction", "activity"):
        raise ValueError(f"driving: {law.driving} is a liquid's measure; this is a gas")
    if law.driving == "partial_pressure":
        return {n: y * pressure / P_STANDARD for n, y in fractions.items()}
    return {n: y * pressure / (R * temperature) for n, y in fractions.items()}


def rate(
    law: RateLaw,
    stoichiometry: Mapping[str, float],
    fractions: Mapping[str, float],
    temperature: float,
    pressure: float,
    ln_k: float | None = None,
    liquid: Any = None,
    k_basis: str = "partial_pressure",
) -> float:
    """The rate (kmol/(kg s) or kmol/(m3 s), per extent as written) of an ideal gas of mole
    *fractions* at *temperature* K and *pressure* kPa, or of a *liquid* (a
    :class:`.liquid.Liquid`) of those mole fractions; *ln_k* (on *k_basis*, the basis of the
    reaction's equilibrium constant) is needed with ``reverse: equilibrium``. Raises ValueError
    when it is missing, when a species with a negative order is absent, and with ``reverse:
    equilibrium`` when a reactant is absent (the reverse rate is then not defined by the law)."""
    c = driving_forces(law, fractions, temperature, pressure, liquid)
    for n, a in law.orders.items():
        if a < 0 and c.get(n, 0.0) <= 0:
            raise ValueError(f"{n} is absent, and its order {a:g} is negative")
    for term in law.adsorption:
        for n, b in term.exponents.items():
            if b < 0 and c.get(n, 0.0) <= 0:
                raise ValueError(f"{n} is absent, and its adsorption exponent {b:g} is negative")
    forward = law.k.k(temperature) * math.prod(c.get(n, 0.0) ** a for n, a in law.orders.items())
    if law.reverse == "equilibrium":
        if ln_k is None:
            raise ValueError("reverse: equilibrium needs the equilibrium constant")
        absent = [n for n, nu in stoichiometry.items() if nu < 0 and fractions.get(n, 0.0) <= 0]
        if absent:
            # Q is infinite: the reaction runs backwards at a rate this law does not give
            raise ValueError(
                f"reactant {', '.join(absent)} absent: the reverse rate is not defined by (1 - Q/K)"
            )
        if liquid is not None:
            from chemeascode.domains.chemistry.liquid import ln_quotient

            ln_q = ln_quotient(stoichiometry, k_basis, fractions, temperature, liquid)
        else:
            if k_basis != "partial_pressure":
                raise ValueError(f"the equilibrium constant on {k_basis} is a liquid's")
            ln_q = 0.0
            for n, nu in stoichiometry.items():
                y = fractions.get(n, 0.0)
                if y <= 0:  # a product absent: Q = 0
                    ln_q = -math.inf
                    break
                ln_q += nu * math.log(y * pressure / P_STANDARD)
        forward *= 1.0 - math.exp(min(ln_q - ln_k, 700.0))
    if law.form == "lhhw":
        forward /= (1.0 + sum(a.term(temperature, c) for a in law.adsorption)) ** law.power
    return forward


def rate_law_from_record(record: Any, ids: Mapping[str, str], canonical: Any = None) -> RateLaw:
    """A power law (per volume, on concentrations) from a filtered NIST or RMG Arrhenius record
    (:class:`~chemeascode.domains.chemistry.kinetics.records.FilteredKinetics`), its reactants
    named by component id (*ids*: SMILES -> id; *canonical* maps a SMILES to the form *ids* is
    keyed by, e.g. RDKit's canonical SMILES, as the filter matches species). The record's SI
    ``A`` (mol, m3, s) is converted to kmol: ``A * 1000^(order - 1)``. A repeated reactant
    (a self-reaction, 2 OH) counts twice. Raises ValueError when A or a reactant id is missing."""
    from collections import Counter

    key = canonical or (lambda smiles: smiles)
    if record.A is None:
        raise ValueError("the record has no pre-exponential factor A")
    counts: dict[str, float] = {}
    stoich = record.reactant_stoichiometry or Counter(record.reactants)
    for smiles, count in stoich.items():
        found = ids.get(key(smiles), ids.get(smiles))
        if found is None:
            raise ValueError(f"no component id for reactant {smiles}")
        counts[found] = counts.get(found, 0.0) + float(count)
    order = record.order if record.order is not None else sum(counts.values())
    window = (
        (float(record.T_min), float(record.T_max))
        if record.T_min and record.T_max and record.T_min < record.T_max
        else None
    )
    detail = ", ".join(
        str(v)
        for v in (record.reaction, record.data_type, record.reference, record.source_library)
        if v
    )
    return RateLaw(
        form="power_law",
        basis="volume",
        driving="concentration",
        k=Arrhenius(
            A=record.A * 1000.0 ** (order - 1),
            Ea=record.Ea or 0.0,
            n=record.n or 0.0,
            T_ref=record.T_ref or 1.0,
        ),
        orders=counts,
        temperature_range=window,
        provenance="assumed",
        source=f"cheme chemistry kinetics ({record.confidence or 'no'} confidence): {detail}",
    )
