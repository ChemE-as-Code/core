"""Schema ``cheme/furnaces/v1`` (``process/furnaces.yaml``) and the energy basis of a
high-temperature solid-reaction furnace: today one bounded case, the calcination of limestone
in a lime kiln, ``CaCO3(calcite) -> CaO(s) + CO2(g)``.

The furnace is a box around the solids, the gas and the heat source, at steady state. Everything
that crosses the box is declared: the solid feed (mass flow, temperature, mass fractions of
calcite, inert oxides and moisture), the degree of calcination (given: the model does not
predict conversion, temperature profiles or lime grade), the temperatures of the product solids
and of the off-gas, the heat source (a fuel with combustion air, or electric power) and the
losses through the walls. :func:`evaluate` computes, with condensed-phase data and never a
fluid flash:

- the element balance (Ca, C, O, H, N, S, Ar and the oxides' metals), feed, fuel and air
  against product and off-gas;
- the product (CaO, residual calcite, inerts, residual CO2 in the lime) and the off-gas
  composition (calcination CO2 and fuel CO2 kept apart, wet and dry mole fractions);
- the reaction enthalpy of the calcination at 298.15 K, and the furnace energy balance on
  298.15 K and the elements: heat input (the fuel's lower heating value times its flow, or the
  electric power) plus the sensible heat of what enters equals the reaction enthalpy, the
  evaporation of the feed moisture, the sensible heat of product and off-gas and the losses.
  With the heat input given (a measured fuel flow or power) it reports the closure residual;
  without it, it solves the heat input that closes the balance;
- with a ``calcining_temperature``, whether calcination can proceed there against the off-gas
  CO2 partial pressure (the equilibrium pressure of CO2 over calcite and lime from the same
  data), and the equilibrium decomposition temperature at that partial pressure.

Thermochemical data: the NASA Glenn polynomials (McBride, Gordon and Reno, NASA TM-4513, 1993)
of the gas and condensed species Cantera ships (``nasa_gas.yaml``, ``nasa_condensed.yaml``),
read through :mod:`chemeascode.integrations.cantera` (extra ``cantera``). Each component maps to
its NASA phases (:data:`COMPONENTS`); a phase change on the way from 298.15 K (alpha to beta
quartz at 847 K) is in the enthalpy, a temperature outside every phase's range (calcite above
1200 K, where its data end; lime above 3200 K, where it melts) is refused, never extrapolated.
The NASA fits of some solids start at 300 K; 298.15 K, the reference of their formation
enthalpies, is allowed (:data:`BELOW_RANGE`).

The fallback (``method: specific-energy``) is a labelled conceptual inventory, not a
calculation: a specific heat use per tonne of product, given with its source, or the range of
the kiln type in the EU lime BREF (:data:`BREF_HEAT_USE`), times the product flow.

Rules (``cheme.furnace-*``), each finding naming the file, line, rule and a hint:

- ``furnace-schema``: the file does not follow ``cheme/furnaces/v1``;
- ``furnace-unsupported``: a reaction or a feed or fuel component this model does not cover
  (carbothermal reduction, dolomite, alumina calcination, ...);
- ``furnace-input``: a missing or inconsistent input (fractions that do not sum to one, no or
  two heat sources, no losses, a unit this file does not read);
- ``furnace-data-range``: a temperature outside the thermochemical data of a species;
- ``furnace-extra``: Cantera is not installed;
- ``furnace-infeasible``: no positive heat input closes the balance, too little air to burn the
  fuel, or calcination impossible at the declared calcining temperature;
- ``furnace-closure`` (warning): the residual exceeds the tolerance;
- ``furnace-provenance`` (warning): a given input the energy depends on without a source;
- ``furnace-specific-energy`` (warning outside, info inside): the specific heat use against the
  BREF range of the declared kiln type; (info) the fallback is used.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field, ValidationError, model_validator

from chemeascode.domains.chemistry.formulas import ATOMIC_MASS
from chemeascode.foundation.findings import Finding
from chemeascode.foundation.provenance import SourceRevision, source_revision
from chemeascode.foundation.schema_base import Provenance, Strict, unsupported_schema
from chemeascode.foundation.units import to_kelvin, to_kpa_abs
from chemeascode.foundation.yamlsource import _yaml_line, syntax_finding

SCHEMA = "cheme/furnaces/v1"
FURNACES_FILE = "process/furnaces.yaml"
#: The contract's version, in every result.
CONTRACT = "furnace-energy-basis/1"

#: K: the reference temperature of the enthalpies and of the lower heating value.
T_REF = 298.15
#: K below a NASA range's lower end still evaluated: some solids' fits start at 300 K, and
#: 298.15 K is the reference their formation enthalpies are defined at.
BELOW_RANGE = 2.0
#: kPa(a)
P_DEFAULT = 101.325
#: kPa: the standard pressure of the NASA data (McBride, Gordon and Reno, NASA TM-4513, p. 2,
#: "Standard States": ideal gas at 10^5 Pa, condensed species at the same pressure). Cantera's
#: files converted from them declare 1 atm, the Chemkin default; that is not used.
P_STANDARD = 100.0

#: The reactions this model covers.
REACTIONS = {
    "calcination-caco3": "CaCO3(calcite) -> CaO(s) + CO2(g)",
}
#: What the model assumes, for reports and maturity.
ASSUMPTIONS = (
    "steady state; one box around solids, gas and heat source",
    "degree of calcination given, not predicted: no kinetics, heat transfer or residence time",
    "inert oxides (MgO, SiO2, Al2O3, Fe2O3) and fuel ash do not react (no silicate or "
    "aluminate formation)",
    "complete combustion: no CO, soot or unburnt fuel in the off-gas; sulfur burns to SO2",
    "the off-gas is an ideal gas at the furnace pressure; the combustion air is dry",
    "the solids leave at one temperature, the off-gas at one temperature",
    "fuel ash: no thermochemical data, its sensible heat is left out",
)
#: What the model does not claim.
NOT_CLAIMED = (
    "temperature profiles, burning-zone temperature or lime reactivity/grade",
    "conversion: the degree of calcination is an input",
    "dolomite or magnesite calcination, hydrated lime, carbothermal reduction",
    "CO, NOx or SO2 capture by the lime",
)

#: Feed and product components: id -> (formula atoms, NASA phases (name, label) in order of
#: temperature). Moisture enters as liquid water and leaves in the off-gas.
COMPONENTS: dict[str, tuple[dict[str, int], tuple[tuple[str, str], ...]]] = {
    "CaCO3": ({"Ca": 1, "C": 1, "O": 3}, (("CaCO3(caL)", "calcite"),)),
    "CaO": ({"Ca": 1, "O": 1}, (("CaO(s)", "lime (solid)"),)),
    "MgO": ({"Mg": 1, "O": 1}, (("MgO(s)", "periclase"),)),
    "SiO2": ({"Si": 1, "O": 2}, (("SiO2(Lqz)", "alpha quartz"), ("SiO2(hqz)", "beta quartz"))),
    "Al2O3": ({"Al": 2, "O": 3}, (("AL2O3(a)", "corundum"),)),
    "Fe2O3": ({"Fe": 2, "O": 3}, (("Fe2O3(s)", "hematite"),)),
    "H2O(l)": ({"H": 2, "O": 1}, (("H2O(L)", "liquid water"),)),
}
#: Feed components, mass fractions of the solid feed.
FEED = ("CaCO3", "MgO", "SiO2", "Al2O3", "Fe2O3", "H2O")
INERTS = ("MgO", "SiO2", "Al2O3", "Fe2O3")
#: Gas species (NASA name = id).
GASES: dict[str, dict[str, int]] = {
    "CO2": {"C": 1, "O": 2},
    "H2O": {"H": 2, "O": 1},
    "N2": {"N": 2},
    "O2": {"O": 2},
    "Ar": {"Ar": 1},
    "SO2": {"S": 1, "O": 2},
    "CH4": {"C": 1, "H": 4},
    "C2H6": {"C": 2, "H": 6},
    "C3H8": {"C": 3, "H": 8},
    "CO": {"C": 1, "O": 1},
    "H2": {"H": 2},
}
#: Components of a gaseous fuel (mole fractions).
FUEL_GASES = ("CH4", "C2H6", "C3H8", "CO", "H2", "N2", "CO2")
#: Keys of an ultimate analysis (mass fractions, as fired).
ULTIMATE = ("C", "H", "O", "N", "S", "ash", "moisture")

#: Dry air, mole fractions: N2, O2, Ar and CO2 of the U.S. Standard Atmosphere 1976 (NOAA,
#: NASA, USAF, NOAA-S/T 76-1562, Table 3), normalised over these four.
_AIR_RAW = {"N2": 0.78084, "O2": 0.209476, "Ar": 0.00934, "CO2": 0.000314}
DRY_AIR = {k: v / sum(_AIR_RAW.values()) for k, v in _AIR_RAW.items()}
AIR_SOURCE = "dry air: U.S. Standard Atmosphere 1976, Table 3 (N2, O2, Ar, CO2, normalised)"

BREF_SOURCE = (
    "European Commission JRC, Best Available Techniques (BAT) Reference Document for the "
    "Production of Cement, Lime and Magnesium Oxide, Schorcht et al., EUR 26129 EN (2013), "
    "doi:10.2788/12850, Table 2.23 (p. 223): typical heat use by kiln type, EU-27, lime and "
    "dolime"
)
KilnType = Literal[
    "long-rotary",
    "preheater-rotary",
    "parallel-flow-regenerative",
    "annular-shaft",
    "mixed-feed-shaft",
    "other",
]
#: GJ per tonne of product, BREF Table 2.23.
BREF_HEAT_USE: dict[str, tuple[float, float]] = {
    "long-rotary": (6.0, 9.2),
    "preheater-rotary": (5.1, 7.8),
    "parallel-flow-regenerative": (3.2, 4.2),
    "annular-shaft": (3.3, 4.9),
    "mixed-feed-shaft": (3.4, 4.7),
    "other": (3.5, 7.0),
}

MASS_FLOW_UNITS = {"kg/h": 1.0, "kg/s": 3600.0, "t/h": 1000.0, "t/d": 1000.0 / 24.0}
POWER_UNITS = {"kW": 1.0, "MW": 1000.0, "W": 0.001}
HEATING_VALUE_UNITS = {"kJ/kg": 1.0, "MJ/kg": 1000.0}
SPECIFIC_ENERGY_UNITS = {"GJ/t": 1.0, "MJ/kg": 1.0, "MJ/t": 0.001, "kWh/t": 0.0036}
FRACTION_UNITS = {"1": 1.0, "%": 0.01}


# -- schema -------------------------------------------------------------------------------------


class Amount(Strict):
    """A number with its unit, provenance and source."""

    value: float
    unit: str
    provenance: Provenance = "given"
    source: str = ""


class Composition(Strict):
    """Fractions by component, with their provenance and source."""

    fractions: dict[str, float]
    provenance: Provenance = "given"
    source: str = ""


class SolidFeed(Strict):
    mass_flow: Amount = Field(description="kg/h, kg/s, t/h or t/d")
    temperature: Amount = Field(description="K or °C")
    composition: Composition = Field(
        description="Mass fractions of CaCO3, MgO, SiO2, Al2O3, Fe2O3 and H2O (moisture)."
    )


class Fuel(Strict):
    """A gaseous fuel by mole fractions (``gas``) or a solid or liquid fuel by its ultimate
    analysis, as fired (``ultimate``: mass fractions of C, H, O, N, S, ash, moisture)."""

    gas: Composition | None = None
    ultimate: Composition | None = None
    lhv: Amount | None = Field(
        default=None,
        description="Lower heating value at 298.15 K, kJ/kg or MJ/kg: required for an "
        "ultimate analysis; for a gas calculated from the data and compared when given.",
    )
    mass_flow: Amount | None = Field(
        default=None, description="Measured fuel flow: the closure is checked; absent: solved."
    )
    temperature: Amount | None = Field(default=None, description="Default 298.15 K.")

    @model_validator(mode="after")
    def _one(self) -> Fuel:
        if (self.gas is None) == (self.ultimate is None):
            raise ValueError("give the fuel as gas (mole fractions) or ultimate (mass fractions)")
        return self


class Air(Strict):
    """Combustion air: its excess (``excess``, lambda, actual over stoichiometric O2) or its
    mass flow."""

    excess: Amount | None = None
    mass_flow: Amount | None = None
    temperature: Amount | None = Field(default=None, description="Default 298.15 K.")

    @model_validator(mode="after")
    def _one(self) -> Air:
        if (self.excess is None) == (self.mass_flow is None):
            raise ValueError("give the air as excess (lambda) or mass_flow, not both")
        return self


class Electric(Strict):
    power: Amount | None = Field(
        default=None, description="Measured electric power: the closure is checked; absent: solved."
    )


class Losses(Strict):
    """Heat lost through the walls and openings: ``heat`` (kW, MW) or ``fraction`` of the heat
    input."""

    heat: Amount | None = None
    fraction: Amount | None = None

    @model_validator(mode="after")
    def _one(self) -> Losses:
        if (self.heat is None) == (self.fraction is None):
            raise ValueError("give the losses as heat or as fraction of the heat input")
        return self


class Furnace(Strict):
    """One furnace: a box around solids, gas and heat source."""

    id: str
    name: str = ""
    block: str | None = Field(default=None, description="The flowsheet block it represents.")
    kiln_type: KilnType | None = Field(
        default=None, description="The kiln type of the lime BREF: its typical heat use."
    )
    reaction: str = Field(description="calcination-caco3 (the only one supported).")
    method: Literal["energy-balance", "specific-energy"] = "energy-balance"
    feed: SolidFeed
    conversion: Amount = Field(description="Degree of calcination of the CaCO3, '1' or '%'.")
    product_temperature: Amount
    off_gas_temperature: Amount
    pressure: Amount | None = Field(default=None, description="Default 101.325 kPa(a).")
    calcining_temperature: Amount | None = Field(
        default=None, description="Checks that calcination can proceed there (equilibrium)."
    )
    fuel: Fuel | None = None
    air: Air | None = None
    electric: Electric | None = None
    losses: Losses | None = None
    specific_energy: Amount | None = Field(
        default=None, description="method specific-energy: GJ/t of product, with its source."
    )
    tolerance: Amount | None = Field(
        default=None,
        description="Closure tolerance: kW, MW or % of the heat input (default 1 %).",
    )


class FurnacesFile(Strict):
    """``process/furnaces.yaml``."""

    schema_: str = Field(alias="schema", description=f"Always {SCHEMA}.")
    furnaces: list[Furnace] = Field(default_factory=list)

    @model_validator(mode="after")
    def _schema(self) -> FurnacesFile:
        if self.schema_ != SCHEMA:
            raise ValueError(unsupported_schema(self.schema_, SCHEMA))
        return self


# -- results ------------------------------------------------------------------------------------


@dataclass
class Term:
    """One term of the energy balance, kW, relative to 298.15 K and the elements."""

    name: str
    side: Literal["in", "out"]
    kW: float
    provenance: Provenance
    source: str = ""


@dataclass
class SpeciesData:
    """Where the data of one component come from and where they hold."""

    component: str
    nasa: list[str]
    phases: list[str]
    temperature_range: tuple[float, float]
    notes: list[str]
    file: str


@dataclass
class FurnaceResult:
    id: str
    method: str
    reaction: str
    contract: str = CONTRACT
    #: "calculated" (the energy balance) or "conceptual fallback" (a specific heat use)
    basis: str = ""
    #: closure: the heat input given and checked; solved: the heat input solved
    mode: str = ""
    feed_kg_h: float = 0.0
    product_kg_h: dict[str, float] = field(default_factory=dict)
    product_total_kg_h: float = 0.0
    conversion: float = 0.0
    residual_co2_mass_percent: float = 0.0
    off_gas_kmol_h: dict[str, float] = field(default_factory=dict)
    off_gas_kg_h: dict[str, float] = field(default_factory=dict)
    off_gas_mole_fractions: dict[str, float] = field(default_factory=dict)
    off_gas_dry_mole_fractions: dict[str, float] = field(default_factory=dict)
    co2_kg_h: dict[str, float] = field(default_factory=dict)
    #: element -> (in, out) kmol/h
    elements: dict[str, tuple[float, float]] = field(default_factory=dict)
    reaction_enthalpy_kJ_kmol: float | None = None
    terms: list[Term] = field(default_factory=list)
    heat_input_kW: float | None = None
    heat_input_range_kW: tuple[float, float] | None = None
    fuel_kg_h: float | None = None
    fuel_lhv_kJ_kg: float | None = None
    air_kg_h: float | None = None
    air_excess: float | None = None
    residual_kW: float | None = None
    tolerance_kW: float | None = None
    specific_energy_GJ_t: float | None = None
    bref_range_GJ_t: tuple[float, float] | None = None
    co2_partial_pressure_kPa: float | None = None
    equilibrium: dict[str, Any] = field(default_factory=dict)
    data: list[SpeciesData] = field(default_factory=list)
    provenance: dict[str, str] = field(default_factory=dict)
    assumptions: list[str] = field(default_factory=list)
    not_claimed: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    @property
    def closed(self) -> bool | None:
        if self.residual_kW is None or self.tolerance_kW is None:
            return None
        return abs(self.residual_kW) <= self.tolerance_kW

    def entry(self) -> dict[str, Any]:
        from chemeascode.foundation.schemas.run import finding_dict

        out = asdict(self)
        out["findings"] = [finding_dict(f) for f in self.findings]
        out["closed"] = self.closed
        return out


@dataclass
class FurnaceReport:
    results: list[FurnaceResult] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    source: SourceRevision | None = None

    def entry(self) -> dict[str, Any]:
        from chemeascode.foundation.schemas.run import finding_dict

        return {
            "contract": CONTRACT,
            "results": [r.entry() for r in self.results],
            "findings": [finding_dict(f) for f in self.findings],
            "source": self.source.as_dict() if self.source else None,
        }


class _Refused(Exception):
    """A furnace this model does not evaluate; the finding says why."""

    def __init__(self, rule: str, message: str, loc: tuple[Any, ...], hint: str = "") -> None:
        super().__init__(message)
        self.rule, self.message, self.loc, self.hint = rule, message, loc, hint


# -- thermochemistry ----------------------------------------------------------------------------


class _Data:
    """The NASA data of the components, through Cantera, with their ranges checked."""

    def __init__(self) -> None:
        from chemeascode.integrations import cantera

        self._cantera = cantera
        names = [n for _, phases in COMPONENTS.values() for n, _ in phases] + list(GASES)
        self.species = cantera.nasa_species(names)
        self.version = cantera.version()
        self.used: dict[str, SpeciesData] = {}

    def _phase(self, component: str, temperature: float, loc: tuple[Any, ...]) -> str:
        phases = COMPONENTS[component][1] if component in COMPONENTS else ((component, "gas"),)
        lo = self.species[phases[0][0]]["temperature_ranges"][0]
        hi = self.species[phases[-1][0]]["temperature_ranges"][-1]
        if not lo - BELOW_RANGE <= temperature <= hi:
            ends = (
                f"; above {hi:g} K the data end"
                if component != "CaO"
                else f"; lime melts at {hi:g} K, liquid lime is not modelled"
            )
            raise _Refused(
                "furnace-data-range",
                f"{component} at {temperature:g} K is outside its thermochemical data "
                f"({lo:g}-{hi:g} K, NASA {', '.join(n for n, _ in phases)}{ends})",
                loc,
                "the model never extrapolates the data: declare a temperature inside the range "
                "or leave the component out",
            )
        self._record(component, phases, lo, hi)
        for name, _label in phases:
            if temperature <= self.species[name]["temperature_ranges"][-1]:
                return name
        return phases[-1][0]

    def _record(self, component: str, phases: Any, lo: float, hi: float) -> None:
        if component in self.used:
            return
        self.used[component] = SpeciesData(
            component=component,
            nasa=[n for n, _ in phases],
            phases=[label for _, label in phases],
            temperature_range=(lo, hi),
            notes=[self.species[n]["note"] for n, _ in phases],
            file=self.species[phases[0][0]]["file"],
        )

    def h(self, component: str, temperature: float, loc: tuple[Any, ...] = ()) -> float:
        """kJ/kmol on the elements at 298.15 K."""
        return self._cantera.nasa_properties(self._phase(component, temperature, loc), temperature)[
            0
        ]

    def g_over_rt(self, component: str, temperature: float) -> float:
        h, s, _ = self._cantera.nasa_properties(
            self._phase(component, temperature, ()), temperature
        )
        return (h - temperature * s) / (8.314462618 * temperature)

    def sensible(self, component: str, temperature: float, loc: tuple[Any, ...] = ()) -> float:
        """kJ/kmol from 298.15 K."""
        return self.h(component, temperature, loc) - self.h(component, T_REF)


def _molar_mass(atoms: dict[str, int | float]) -> float:
    return sum(ATOMIC_MASS[e] * n for e, n in atoms.items())


def _atoms(component: str) -> dict[str, int]:
    if component in COMPONENTS:
        return COMPONENTS[component][0]
    return GASES[component]


def calcination_enthalpy(data: _Data | None = None, temperature: float = T_REF) -> float:
    """kJ/kmol of CaCO3 decomposed at *temperature* (calcite and lime solid, CO2 gas)."""
    data = data or _Data()
    return data.h("CaO", temperature) + data.h("CO2", temperature) - data.h("CaCO3", temperature)


def co2_equilibrium_pressure(temperature: float, data: _Data | None = None) -> float:
    """kPa: the equilibrium pressure of CO2 over pure calcite and lime at *temperature* K."""
    data = data or _Data()
    ln_k = -(
        data.g_over_rt("CaO", temperature)
        + data.g_over_rt("CO2", temperature)
        - data.g_over_rt("CaCO3", temperature)
    )
    return math.exp(ln_k) * P_STANDARD


def decomposition_temperature(pressure: float, data: _Data | None = None) -> float | None:
    """K at which the equilibrium CO2 pressure over calcite and lime is *pressure* kPa; None
    when that lies outside the data of calcite and lime (300-1200 K)."""
    data = data or _Data()
    ranges = [data.species[n]["temperature_ranges"] for n in ("CaCO3(caL)", "CaO(s)")]
    lo, hi = max(r[0] for r in ranges), min(r[-1] for r in ranges)
    if not co2_equilibrium_pressure(lo, data) <= pressure <= co2_equilibrium_pressure(hi, data):
        return None
    for _ in range(80):
        mid = (lo + hi) / 2
        if co2_equilibrium_pressure(mid, data) < pressure:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


# -- evaluation ---------------------------------------------------------------------------------


def _convert(amount: Amount, units: dict[str, float], loc: tuple[Any, ...]) -> float:
    if amount.unit not in units:
        raise _Refused(
            "furnace-input",
            f"unit {amount.unit!r} is not read here",
            (*loc, "unit"),
            f"use one of {', '.join(units)}",
        )
    return amount.value * units[amount.unit]


def _kelvin(amount: Amount | None, loc: tuple[Any, ...], default: float = T_REF) -> float:
    if amount is None:
        return default
    value = to_kelvin(amount.value, amount.unit)
    if value is None or value <= 0:
        raise _Refused(
            "furnace-input",
            f"{amount.value:g} {amount.unit} is no temperature",
            loc,
            "give K or °C",
        )
    return value


def _fractions(
    comp: Composition, allowed: tuple[str, ...], what: str, loc: tuple[Any, ...]
) -> dict[str, float]:
    unknown = sorted(set(comp.fractions) - set(allowed))
    if unknown:
        raise _Refused(
            "furnace-unsupported",
            f"{what} component(s) {', '.join(unknown)} not covered by this model",
            (*loc, "fractions"),
            f"supported: {', '.join(allowed)}",
        )
    if any(x < 0 for x in comp.fractions.values()):
        raise _Refused(
            "furnace-input",
            f"a negative {what} fraction",
            (*loc, "fractions"),
            "fractions are between 0 and 1",
        )
    total = sum(comp.fractions.values())
    if abs(total - 1.0) > 1e-3:
        raise _Refused(
            "furnace-input",
            f"the {what} fractions sum to {total:.4g}, not 1",
            (*loc, "fractions"),
            "fractions are of the whole (as fired / as fed), summing to 1",
        )
    return {k: v / total for k, v in comp.fractions.items() if v > 0}


def _fuel_basis(
    fuel: Fuel, data: _Data
) -> tuple[dict[str, float], dict[str, float], float, float | None, float, str]:
    """Per kg of fuel: kmol of atoms, kmol of combustion products (gas species; ``ash`` kg),
    kmol O2 needed, the LHV calculated from the data (gas fuels), the fuel's own enthalpy
    minus that of its combustion products at 298.15 K per kg (= LHV) and a description."""
    loc = ("fuel",)
    if fuel.gas is not None:
        y = _fractions(fuel.gas, FUEL_GASES, "fuel gas", (*loc, "gas"))
        mass = sum(x * _molar_mass(GASES[k]) for k, x in y.items())
        atoms: dict[str, float] = {}
        for k, x in y.items():
            for e, n in GASES[k].items():
                atoms[e] = atoms.get(e, 0.0) + x * n / mass
        products = _products(atoms)
        h_fuel = sum(x * data.h(k, T_REF) for k, x in y.items()) / mass
        h_products = sum(n * data.h(k, T_REF) for k, n in products.items() if k != "ash")
        o2 = atoms.get("C", 0) + atoms.get("H", 0) / 4 + atoms.get("S", 0) - atoms.get("O", 0) / 2
        lhv = h_fuel - h_products + o2 * data.h("O2", T_REF)
        return (
            atoms,
            products,
            o2,
            lhv,
            lhv,
            "gas: " + ", ".join(f"{k} {v:.4g}" for k, v in y.items()),
        )
    w = _fractions(fuel.ultimate, ULTIMATE, "ultimate analysis", (*loc, "ultimate"))
    atoms = {e: w.get(e, 0.0) / ATOMIC_MASS[e] for e in ("C", "H", "O", "N", "S") if w.get(e)}
    moisture = w.get("moisture", 0.0) / _molar_mass(GASES["H2O"])
    if moisture:
        atoms["H"] = atoms.get("H", 0.0) + 2 * moisture
        atoms["O"] = atoms.get("O", 0.0) + moisture
    products = _products(atoms)
    if w.get("ash"):
        products["ash"] = w["ash"]
    o2 = atoms.get("C", 0) + atoms.get("H", 0) / 4 + atoms.get("S", 0) - atoms.get("O", 0) / 2
    if fuel.lhv is None:
        raise _Refused(
            "furnace-input",
            "a fuel given by its ultimate analysis needs its lower heating value",
            loc,
            "give fuel.lhv (kJ/kg or MJ/kg, as fired) with its source",
        )
    lhv = _convert(fuel.lhv, HEATING_VALUE_UNITS, (*loc, "lhv"))
    return (
        atoms,
        products,
        o2,
        None,
        lhv,
        "ultimate: " + ", ".join(f"{k} {v:.4g}" for k, v in w.items()),
    )


def _products(atoms: dict[str, float]) -> dict[str, float]:
    """kmol of complete-combustion products per kg (O2 balance apart)."""
    out = {
        "CO2": atoms.get("C", 0.0),
        "H2O": atoms.get("H", 0.0) / 2,
        "SO2": atoms.get("S", 0.0),
        "N2": atoms.get("N", 0.0) / 2,
    }
    return {k: v for k, v in out.items() if v}


def _add(into: dict[str, float], what: dict[str, float], factor: float = 1.0) -> None:
    for k, v in what.items():
        into[k] = into.get(k, 0.0) + v * factor


def _element_totals(flows: dict[str, float]) -> dict[str, float]:
    out: dict[str, float] = {}
    for k, n in flows.items():
        if k == "ash":
            continue
        for e, a in _atoms(k).items():
            out[e] = out.get(e, 0.0) + n * a
    return out


def evaluate(furnace: Furnace, data: Any = None) -> FurnaceResult:
    """The energy basis of one furnace; refusals are findings (file :data:`FURNACES_FILE`, the
    line left to the caller through ``Finding.key``)."""
    result = FurnaceResult(id=furnace.id, method=furnace.method, reaction=furnace.reaction)
    result.assumptions = list(ASSUMPTIONS)
    result.not_claimed = list(NOT_CLAIMED)
    try:
        _evaluate(furnace, result, data)
    except _Refused as refusal:
        result.findings.append(
            _finding(furnace, refusal.rule, refusal.message, refusal.loc, refusal.hint)
        )
    return result


def _finding(
    furnace: Furnace,
    rule: str,
    message: str,
    loc: tuple[Any, ...],
    hint: str = "",
    level: str = "error",
) -> Finding:
    """The finding's key is ``<furnace id>:<field path>``: stable, and the line is found from
    it (:func:`furnace_report`)."""
    return Finding(
        FURNACES_FILE,
        level,  # type: ignore[arg-type]
        f"cheme.{rule}",
        f"{furnace.id}: {message}",
        ids=[furnace.id],
        hint=hint,
        key=f"{furnace.id}:{'.'.join(str(p) for p in loc)}" if loc else furnace.id,
    )


def _loc(finding: Finding) -> tuple[str, ...]:
    """The field path of a furnace finding, from its key."""
    _, _, path = finding.key.partition(":")
    return tuple(path.split(".")) if path else ()


def _evaluate(furnace: Furnace, result: FurnaceResult, data: Any) -> None:
    if furnace.reaction not in REACTIONS:
        raise _Refused(
            "furnace-unsupported",
            f"reaction {furnace.reaction!r} is not covered: the furnace energy basis is "
            f"qualified for {', '.join(REACTIONS)} only",
            ("reaction",),
            "carbothermal reduction (SiC, CaC2), dolomite or magnesite and alumina calcination "
            "are not supported: keep a sourced specific-energy inventory outside cheme-as-code "
            "and say so in DESIGN.md",
        )
    feed_kg_h = _convert(furnace.feed.mass_flow, MASS_FLOW_UNITS, ("feed", "mass_flow"))
    w = _fractions(furnace.feed.composition, FEED, "feed", ("feed", "composition"))
    if not w.get("CaCO3"):
        raise _Refused(
            "furnace-input",
            "the feed holds no CaCO3",
            ("feed", "composition"),
            "give the CaCO3 mass fraction of the limestone",
        )
    conversion = _convert(furnace.conversion, FRACTION_UNITS, ("conversion",))
    if not 0 < conversion <= 1:
        raise _Refused(
            "furnace-input",
            f"degree of calcination {conversion:g} is not in (0, 1]",
            ("conversion",),
            "the fraction of the CaCO3 fed that decomposes: '1' or '%'",
        )
    t_feed = _kelvin(furnace.feed.temperature, ("feed", "temperature"))
    t_product = _kelvin(furnace.product_temperature, ("product_temperature",))
    t_gas = _kelvin(furnace.off_gas_temperature, ("off_gas_temperature",))
    pressure = P_DEFAULT
    if furnace.pressure is not None:
        p = to_kpa_abs(furnace.pressure.value, furnace.pressure.unit)
        if p is None or p <= 0:
            raise _Refused(
                "furnace-input",
                "the pressure is not an absolute pressure",
                ("pressure",),
                "give kPa(a), bar(a) or the like",
            )
        pressure = p
    result.feed_kg_h = feed_kg_h
    result.conversion = conversion

    # -- solids
    feed = {
        k: feed_kg_h * x / _molar_mass(_atoms("H2O(l)" if k == "H2O" else k)) for k, x in w.items()
    }
    moisture = feed.pop("H2O", 0.0)
    extent = conversion * feed["CaCO3"]
    product = {k: v for k, v in feed.items() if k != "CaCO3"}
    product["CaO"] = extent
    if feed["CaCO3"] - extent > 0:
        product["CaCO3"] = feed["CaCO3"] - extent
    product_kg = {k: n * _molar_mass(_atoms(k)) for k, n in product.items()}

    gas: dict[str, float] = {"CO2": extent}
    if moisture:
        gas["H2O"] = moisture
    co2 = {"calcination": extent * _molar_mass(GASES["CO2"])}

    if furnace.method == "specific-energy":
        _fallback(furnace, result, product_kg, gas, co2)
        return

    if data is None:
        try:
            data = _Data()
        except ImportError as failure:
            raise _Refused(
                "furnace-extra",
                f"the thermochemical data need Cantera ({failure})",
                ("method",),
                "pip install 'cheme-as-code[cantera]', or use method: specific-energy with a "
                "sourced specific heat use (a conceptual fallback)",
            ) from failure
    result.basis = "calculated"
    dh = calcination_enthalpy(data)
    result.reaction_enthalpy_kJ_kmol = dh
    # every temperature is checked against the data before any number is reported
    for k in feed:
        data.sensible(k, t_feed, ("feed", "temperature"))
    if moisture:
        data.sensible("H2O(l)", t_feed, ("feed", "temperature"))
    for k in product:
        data.sensible(k, t_product, ("product_temperature",))

    # -- heat source
    sources = [s for s in (furnace.fuel, furnace.electric) if s is not None]
    if len(sources) != 1:
        raise _Refused(
            "furnace-input",
            "give one heat source: fuel (with air) or electric",
            ("fuel",) if furnace.fuel else ("electric",),
            "a fuel-fired kiln declares fuel and air, an electric calciner electric",
        )
    if furnace.losses is None:
        raise _Refused(
            "furnace-input",
            "the losses are not given: the furnace energy cannot be closed without them",
            ("losses",),
            "give losses.heat (kW) or losses.fraction of the heat input, with its source "
            "(0 with a source if negligible)",
        )
    loss_kw = loss_fraction = 0.0
    if furnace.losses.heat is not None:
        loss_kw = _convert(furnace.losses.heat, POWER_UNITS, ("losses", "heat"))
    else:
        loss_fraction = _convert(furnace.losses.fraction, FRACTION_UNITS, ("losses", "fraction"))
        if not 0 <= loss_fraction < 1:
            raise _Refused(
                "furnace-input",
                "the loss fraction is not in [0, 1)",
                ("losses", "fraction"),
                "a fraction of the heat input: '1' or '%'",
            )

    # fixed terms (kW), independent of the heat input
    kw = 1.0 / 3600.0
    fixed_in = {
        "sensible heat of the solid feed": sum(
            n * data.sensible(k, t_feed) for k, n in feed.items()
        )
        * kw,
    }
    if moisture:
        fixed_in["sensible heat of the feed moisture (liquid)"] = (
            moisture * data.sensible("H2O(l)", t_feed) * kw
        )
    fixed_out = {
        "reaction enthalpy of calcination (298.15 K)": extent * dh * kw,
        "sensible heat of the product solids": sum(
            n * data.sensible(k, t_product) for k, n in product.items()
        )
        * kw,
    }
    if moisture:
        fixed_out["evaporation of the feed moisture (298.15 K)"] = (
            moisture * (data.h("H2O", T_REF) - data.h("H2O(l)", T_REF)) * kw
        )

    fuel_kg = None
    air_kmol = 0.0
    per_fuel: dict[str, float] = {}  # off-gas kmol per kg fuel
    o2_per_kg = lhv = 0.0
    air_per_kg = 0.0  # kmol air per kg fuel (excess given)
    t_air = t_fuel = T_REF
    fuel_sensible = 0.0  # kJ/kg
    if furnace.fuel is not None:
        fuel = furnace.fuel
        if furnace.air is None:
            raise _Refused(
                "furnace-input",
                "a fuel needs its combustion air",
                ("air",),
                "give air.excess (lambda) or air.mass_flow",
            )
        atoms, products, o2_per_kg, lhv_data, lhv, described = _fuel_basis(fuel, data)
        if lhv <= 0:
            raise _Refused(
                "furnace-input",
                f"lower heating value {lhv:g} kJ/kg",
                ("fuel",),
                "a fuel releases heat: check the composition or the LHV",
            )
        result.fuel_lhv_kJ_kg = lhv
        if lhv_data is not None and fuel.lhv is not None:
            given = _convert(fuel.lhv, HEATING_VALUE_UNITS, ("fuel", "lhv"))
            if abs(given - lhv_data) > 0.01 * lhv_data:
                result.findings.append(
                    _finding(
                        furnace,
                        "furnace-input",
                        f"the given LHV {given:.6g} kJ/kg differs from the {lhv_data:.6g} "
                        "kJ/kg the data give for this gas by more than 1 %",
                        ("fuel", "lhv"),
                        "check the composition or the LHV basis (net, 298.15 K)",
                        level="warning",
                    )
                )
        t_fuel = _kelvin(fuel.temperature, ("fuel", "temperature"))
        if fuel.gas is not None:
            y = _fractions(fuel.gas, FUEL_GASES, "fuel gas", ("fuel", "gas"))
            mass = sum(x * _molar_mass(GASES[k]) for k, x in y.items())
            fuel_sensible = (
                sum(x * data.sensible(k, t_fuel, ("fuel", "temperature")) for k, x in y.items())
                / mass
            )
        elif abs(t_fuel - T_REF) > 1.0:
            result.notes.append(
                f"fuel at {t_fuel:g} K: the sensible heat of a fuel given by its ultimate "
                "analysis is not modelled (taken at 298.15 K)"
            )
        per_fuel = {k: v for k, v in products.items() if k != "ash"}
        per_fuel["O2"] = -o2_per_kg
        t_air = _kelvin(furnace.air.temperature, ("air", "temperature"))
        for k in DRY_AIR:
            data.sensible(k, t_air, ("air", "temperature"))
        air_molar_mass = sum(x * _molar_mass(GASES[k]) for k, x in DRY_AIR.items())
        if furnace.air.excess is not None:
            excess = _convert(furnace.air.excess, FRACTION_UNITS, ("air", "excess"))
            if excess < 1:
                raise _Refused(
                    "furnace-infeasible",
                    f"air excess {excess:g} below 1: the fuel does not burn completely",
                    ("air", "excess"),
                    "the model assumes complete combustion: lambda >= 1",
                )
            air_per_kg = excess * o2_per_kg / DRY_AIR["O2"]
            _add(per_fuel, DRY_AIR, air_per_kg)
        else:
            air_kmol = (
                _convert(furnace.air.mass_flow, MASS_FLOW_UNITS, ("air", "mass_flow"))
                / air_molar_mass
            )
            _add(gas, DRY_AIR, air_kmol)
            fixed_in["sensible heat of the combustion air"] = (
                air_kmol * sum(x * data.sensible(k, t_air) for k, x in DRY_AIR.items()) * kw
            )
        result.provenance["fuel"] = described
        if fuel.mass_flow is not None:
            fuel_kg = _convert(fuel.mass_flow, MASS_FLOW_UNITS, ("fuel", "mass_flow"))
        result.provenance["air"] = AIR_SOURCE
        ash_per_kg = products.get("ash", 0.0)
    else:
        ash_per_kg = 0.0
        if furnace.air is not None and furnace.air.excess is not None:
            raise _Refused(
                "furnace-input",
                "an air excess needs a fuel to refer to",
                ("air", "excess"),
                "an electric calciner gives its purge or sweep air as air.mass_flow, or none",
            )
        if furnace.air is not None and furnace.air.mass_flow is not None:
            t_air = _kelvin(furnace.air.temperature, ("air", "temperature"))
            air_molar_mass = sum(x * _molar_mass(GASES[k]) for k, x in DRY_AIR.items())
            air_kmol = (
                _convert(furnace.air.mass_flow, MASS_FLOW_UNITS, ("air", "mass_flow"))
                / air_molar_mass
            )
            _add(gas, DRY_AIR, air_kmol)
            fixed_in["sensible heat of the purge air"] = (
                air_kmol
                * sum(
                    x * data.sensible(k, t_air, ("air", "temperature")) for k, x in DRY_AIR.items()
                )
                * kw
            )
            result.provenance["air"] = AIR_SOURCE

    for k in set(gas) | set(per_fuel):
        data.sensible(k, t_gas, ("off_gas_temperature",))

    def gas_out_kw(flows: dict[str, float]) -> float:
        return sum(n * data.sensible(k, t_gas) for k, n in flows.items()) * kw

    fixed_gas = gas_out_kw(gas)
    # per kg of fuel (kW per kg/h)
    per_kg_in = (
        fuel_sensible + air_per_kg * sum(x * data.sensible(k, t_air) for k, x in DRY_AIR.items())
    ) * kw
    per_kg_gas = gas_out_kw(per_fuel)
    a = sum(fixed_out.values()) + fixed_gas - sum(fixed_in.values())

    tol_kw = None
    if furnace.fuel is not None:
        if fuel_kg is None:
            result.mode = "solved"
            denominator = lhv * kw * (1 - loss_fraction) + per_kg_in - per_kg_gas
            if denominator <= 0:
                raise _Refused(
                    "furnace-infeasible",
                    f"each kg of fuel releases {lhv * kw * 3600:.6g} kJ but its combustion gas "
                    f"leaving at {t_gas:g} K carries away more: no fuel flow closes the balance",
                    ("off_gas_temperature",),
                    "check the off-gas temperature, the air excess and the losses",
                )
            fuel_kg = (a + loss_kw) / denominator
            if fuel_kg <= 0:
                raise _Refused(
                    "furnace-infeasible",
                    "the balance closes only with a negative fuel flow: the declared outputs "
                    "need no heat",
                    ("fuel",),
                    "check the temperatures, the conversion and the losses",
                )
        else:
            result.mode = "closure"
        heat_input = fuel_kg * lhv * kw
        result.fuel_kg_h = fuel_kg
        _add(gas, per_fuel, fuel_kg)
        o2_left = gas.get("O2", 0.0)
        if o2_left < -1e-12:
            raise _Refused(
                "furnace-infeasible",
                "the air does not hold enough oxygen to burn the fuel completely",
                ("air",),
                "raise the air flow or lower the fuel flow",
            )
        gas = {k: v for k, v in gas.items() if v > 1e-15}
        o2_supplied = o2_left + o2_per_kg * fuel_kg
        air_total = air_kmol + air_per_kg * fuel_kg
        result.air_kg_h = air_total * sum(x * _molar_mass(GASES[k]) for k, x in DRY_AIR.items())
        result.air_excess = o2_supplied / (o2_per_kg * fuel_kg) if o2_per_kg * fuel_kg > 0 else None
        terms_in = {"fuel heat (LHV x fuel flow)": heat_input, **fixed_in}
        if fuel_sensible:
            terms_in["sensible heat of the fuel"] = fuel_kg * fuel_sensible * kw
        if air_per_kg:
            terms_in["sensible heat of the combustion air"] = (
                air_per_kg
                * fuel_kg
                * sum(x * data.sensible(k, t_air) for k, x in DRY_AIR.items())
                * kw
            )
        heat_term = Term(
            "fuel heat (LHV x fuel flow)",
            "in",
            heat_input,
            "given" if result.mode == "closure" else "calculated",
            _source(fuel.mass_flow, fuel.lhv),
        )
        if ash_per_kg:
            product_kg["ash"] = ash_per_kg * fuel_kg
            result.notes.append("fuel ash leaves with the product; its sensible heat is left out")
    else:
        electric = furnace.electric
        assert electric is not None
        if electric.power is None:
            result.mode = "solved"
            heat_input = (a + loss_kw) / (1 - loss_fraction)
            if heat_input <= 0:
                raise _Refused(
                    "furnace-infeasible",
                    "the balance closes only with a negative electric power",
                    ("electric",),
                    "check the temperatures, the conversion and the losses",
                )
        else:
            result.mode = "closure"
            heat_input = _convert(electric.power, POWER_UNITS, ("electric", "power"))
        terms_in = {"electric power": heat_input, **fixed_in}
        heat_term = Term(
            "electric power",
            "in",
            heat_input,
            "given" if result.mode == "closure" else "calculated",
            _source(electric.power),
        )

    losses = loss_kw + loss_fraction * heat_input
    terms_out = {**fixed_out, "sensible heat of the off-gas": gas_out_kw(gas), "losses": losses}
    result.heat_input_kW = heat_input
    result.terms = (
        [heat_term]
        + [
            Term(name, "in", value, "calculated", "")
            for name, value in terms_in.items()
            if name != heat_term.name
        ]
        + [Term(name, "out", value, "calculated", "") for name, value in terms_out.items()]
    )
    loss_source = _source(furnace.losses.heat or furnace.losses.fraction)
    result.terms[-1].provenance = (furnace.losses.heat or furnace.losses.fraction).provenance
    result.terms[-1].source = loss_source
    result.residual_kW = sum(terms_in.values()) - sum(terms_out.values())
    if furnace.tolerance is None:
        tol_kw = 0.01 * heat_input
    elif furnace.tolerance.unit == "%":
        tol_kw = furnace.tolerance.value / 100 * heat_input
    else:
        tol_kw = _convert(furnace.tolerance, POWER_UNITS, ("tolerance",))
    result.tolerance_kW = tol_kw
    if result.mode == "closure" and abs(result.residual_kW) > tol_kw:
        result.findings.append(
            _finding(
                furnace,
                "furnace-closure",
                f"the energy balance does not close: residual {result.residual_kW:+.4g} kW "
                f"(in minus out) against a tolerance of {tol_kw:.4g} kW",
                ("fuel", "mass_flow") if furnace.fuel else ("electric", "power"),
                "a positive residual is heat not accounted for (losses larger than given), a "
                "negative one more heat out than in: check the measured flows, temperatures and "
                "losses",
                level="warning",
            )
        )

    # -- product, gas, elements
    _product_and_gas(result, product_kg, gas, co2, pressure)
    result.co2_kg_h["fuel"] = (
        result.off_gas_kg_h.get("CO2", 0.0)
        - co2["calcination"]
        - (air_kmol + air_per_kg * (fuel_kg or 0.0)) * DRY_AIR["CO2"] * _molar_mass(GASES["CO2"])
    )
    feed_flows = {**feed}
    if moisture:
        feed_flows["H2O"] = moisture
    in_flows = dict(feed_flows)
    _add(in_flows, DRY_AIR, air_kmol + air_per_kg * (fuel_kg or 0.0))
    elements_in = _element_totals(in_flows)
    if furnace.fuel is not None:
        _add(elements_in, atoms, fuel_kg)
    elements_out = _element_totals({**product, **gas})
    result.elements = {
        e: (elements_in.get(e, 0.0), elements_out.get(e, 0.0))
        for e in sorted(set(elements_in) | set(elements_out))
    }
    for e, (n_in, n_out) in result.elements.items():
        if abs(n_in - n_out) > 1e-9 * max(n_in, n_out, 1e-12):
            result.findings.append(
                _finding(
                    furnace,
                    "furnace-infeasible",
                    f"element {e} does not balance: {n_in:.6g} in, {n_out:.6g} out kmol/h",
                    ("feed",),
                    "report this: it is a defect",
                    level="error",
                )
            )

    # -- specific energy, BREF, equilibrium, provenance
    _specific(furnace, result)
    if furnace.calcining_temperature is not None:
        _equilibrium(furnace, result, data, pressure)
    result.data = list(data.used.values())
    result.provenance.update(
        {
            "thermochemistry": (
                f"NASA Glenn polynomials (McBride, Gordon and Reno, NASA TM-4513, 1993) in Cantera "
                f"{data.version} ({', '.join(sorted({d.file for d in data.used.values()}))}); "
                f"enthalpies on the elements in their reference states at {T_REF} K, standard "
                f"pressure {P_STANDARD:g} kPa (TM-4513, p. 2)"
            ),
            "atomic weights": "IUPAC 2021 (chemistry.formulas.ATOMIC_MASS)",
        }
    )
    _provenance_findings(furnace, result)


def _source(*amounts: Amount | None) -> str:
    sources = [a.source for a in amounts if a is not None and a.source]
    return "; ".join(dict.fromkeys(sources))


def _product_and_gas(
    result: FurnaceResult,
    product_kg: dict[str, float],
    gas: dict[str, float],
    co2: dict[str, float],
    pressure: float,
) -> None:
    result.product_kg_h = product_kg
    result.product_total_kg_h = sum(product_kg.values())
    result.residual_co2_mass_percent = (
        100
        * product_kg.get("CaCO3", 0.0)
        / _molar_mass(COMPONENTS["CaCO3"][0])
        * _molar_mass(GASES["CO2"])
        / result.product_total_kg_h
    )
    total = sum(gas.values())
    dry = total - gas.get("H2O", 0.0)
    result.off_gas_kmol_h = dict(sorted(gas.items()))
    result.off_gas_kg_h = {k: n * _molar_mass(GASES[k]) for k, n in sorted(gas.items())}
    result.off_gas_mole_fractions = {k: n / total for k, n in sorted(gas.items())}
    result.off_gas_dry_mole_fractions = (
        {k: n / dry for k, n in sorted(gas.items()) if k != "H2O"} if dry > 0 else {}
    )
    result.co2_kg_h = dict(co2)
    result.co2_partial_pressure_kPa = result.off_gas_mole_fractions.get("CO2", 0.0) * pressure


def _fallback(
    furnace: Furnace,
    result: FurnaceResult,
    product_kg: dict[str, float],
    gas: dict[str, float],
    co2: dict[str, float],
) -> None:
    result.basis = "conceptual fallback: a sourced specific heat use, not a calculation"
    result.mode = "fallback"
    _product_and_gas(result, product_kg, gas, co2, P_DEFAULT)
    # the combustion gas is not calculated: the process gas alone is no off-gas composition
    result.off_gas_mole_fractions = result.off_gas_dry_mole_fractions = {}
    result.co2_partial_pressure_kPa = None
    result.notes.append(
        "off-gas: the calcination CO2 and the feed moisture only; the combustion gas, its "
        "composition and the CO2 partial pressure are not calculated"
    )
    tonnes = result.product_total_kg_h / 1000.0
    if furnace.specific_energy is not None:
        value = _convert(furnace.specific_energy, SPECIFIC_ENERGY_UNITS, ("specific_energy",))
        result.specific_energy_GJ_t = value
        result.heat_input_kW = value * tonnes * 1e6 / 3600.0
        result.provenance["specific energy"] = furnace.specific_energy.source
        if not furnace.specific_energy.source.strip():
            result.findings.append(
                _finding(
                    furnace,
                    "furnace-provenance",
                    "the specific heat use has no source",
                    ("specific_energy",),
                    "a fallback stands only on its source",
                    level="warning",
                )
            )
    elif furnace.kiln_type is not None:
        low, high = BREF_HEAT_USE[furnace.kiln_type]
        result.heat_input_range_kW = (low * tonnes * 1e6 / 3600.0, high * tonnes * 1e6 / 3600.0)
        result.provenance["specific energy"] = BREF_SOURCE
    else:
        raise _Refused(
            "furnace-input",
            "method specific-energy needs specific_energy (GJ/t, with its source) or kiln_type",
            ("specific_energy",),
            f"kiln_type: one of {', '.join(BREF_HEAT_USE)} (lime BREF Table 2.23)",
        )
    if furnace.kiln_type is not None:
        result.bref_range_GJ_t = BREF_HEAT_USE[furnace.kiln_type]
    result.notes.append(
        "conceptual fallback: the heat input is a specific heat use times the product flow; "
        "no reaction or furnace energy is calculated and no temperature or grade is claimed"
    )
    result.findings.append(
        _finding(
            furnace,
            "furnace-specific-energy",
            "conceptual fallback: heat input from a specific heat use, not from the energy balance",
            ("method",),
            "use method: energy-balance with the fuel, air and losses for a calculated basis",
            level="info",
        )
    )


def _specific(furnace: Furnace, result: FurnaceResult) -> None:
    if not result.product_total_kg_h or result.heat_input_kW is None:
        return
    result.specific_energy_GJ_t = (
        result.heat_input_kW * 3600.0 / 1e6 / (result.product_total_kg_h / 1000.0)
    )
    if furnace.kiln_type is None:
        return
    low, high = BREF_HEAT_USE[furnace.kiln_type]
    result.bref_range_GJ_t = (low, high)
    inside = low <= result.specific_energy_GJ_t <= high
    result.findings.append(
        _finding(
            furnace,
            "furnace-specific-energy",
            f"specific heat use {result.specific_energy_GJ_t:.3g} GJ/t of product "
            f"{'inside' if inside else 'outside'} the {low:g}-{high:g} GJ/t typical of "
            f"{furnace.kiln_type} kilns (lime BREF Table 2.23)",
            ("kiln_type",),
            "the typical range, not a limit: a value outside it needs a reason (fuel, stone "
            "size, moisture, residual CO2, dolime; BREF section 2.3.2.1)",
            level="info" if inside else "warning",
        )
    )


def _equilibrium(furnace: Furnace, result: FurnaceResult, data: _Data, pressure: float) -> None:
    t = _kelvin(furnace.calcining_temperature, ("calcining_temperature",))
    data.sensible("CaCO3", t, ("calcining_temperature",))
    p_eq = co2_equilibrium_pressure(t, data)
    p_co2 = result.co2_partial_pressure_kPa or 0.0
    result.equilibrium = {
        "calcining_temperature_K": t,
        "co2_equilibrium_pressure_kPa": p_eq,
        "off_gas_co2_partial_pressure_kPa": p_co2,
        "decomposition_temperature_K": decomposition_temperature(p_co2, data) if p_co2 else None,
        "basis": "pure calcite and lime (unit activity), CO2 ideal gas; the off-gas partial "
        "pressure is the highest the gas reaches in counter- and co-current kilns",
    }
    if p_eq <= p_co2:
        result.findings.append(
            _finding(
                furnace,
                "furnace-infeasible",
                f"calcination cannot proceed at {t:g} K: the equilibrium CO2 pressure "
                f"{p_eq:.4g} kPa is below the off-gas CO2 partial pressure {p_co2:.4g} kPa",
                ("calcining_temperature",),
                "raise the calcining temperature or check the off-gas composition",
            )
        )


def _provenance_findings(furnace: Furnace, result: FurnaceResult) -> None:
    checks: list[tuple[str, Amount | Composition | None, tuple[Any, ...]]] = [
        ("degree of calcination", furnace.conversion, ("conversion",)),
        (
            "losses",
            furnace.losses.heat or furnace.losses.fraction if furnace.losses else None,
            ("losses",),
        ),
        ("feed composition", furnace.feed.composition, ("feed", "composition")),
    ]
    if furnace.fuel is not None:
        checks += [
            ("fuel LHV", furnace.fuel.lhv, ("fuel", "lhv")),
            ("fuel flow", furnace.fuel.mass_flow, ("fuel", "mass_flow")),
            ("fuel composition", furnace.fuel.gas or furnace.fuel.ultimate, ("fuel",)),
        ]
    for what, amount, loc in checks:
        if amount is not None and amount.provenance == "given" and not amount.source.strip():
            result.findings.append(
                _finding(
                    furnace,
                    "furnace-provenance",
                    f"the {what} is given without a source",
                    loc,
                    "add source: (document, table, page) or mark it assumed",
                    level="warning",
                )
            )


# -- the plant's file ---------------------------------------------------------------------------


def load(root: Path) -> tuple[FurnacesFile | None, Any, list[Finding]]:
    """``process/furnaces.yaml`` of the plant at *root*, its YAML nodes and its schema
    findings; None (and no findings) without the file."""
    path = Path(root) / FURNACES_FILE
    if not path.is_file():
        return None, None, []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as failure:
        return None, None, [Finding(FURNACES_FILE, "error", "yaml.syntax", str(failure))]
    try:
        data = yaml.safe_load(text) or {}
        doc = yaml.compose(text)
    except yaml.YAMLError as failure:
        return None, None, [syntax_finding(FURNACES_FILE, failure, text)]
    try:
        return FurnacesFile.model_validate(data), doc, []
    except ValidationError as failure:
        return (
            None,
            doc,
            [
                Finding(
                    FURNACES_FILE,
                    "error",
                    "cheme.furnace-schema",
                    f"{SCHEMA}: {'.'.join(str(p) for p in e['loc']) or '(file)'}: {e['msg']}",
                    line=_yaml_line(doc, e["loc"]),
                    hint="see `cheme schema furnaces`",
                )
                for e in failure.errors()
            ],
        )


def furnace_report(
    root: Path,
    furnace_id: str | None = None,
    evaluate_one: Callable[[Furnace], FurnaceResult] = evaluate,
) -> FurnaceReport:
    """The energy basis of every furnace of ``process/furnaces.yaml`` (or of *furnace_id*).
    Raises KeyError for a furnace id the file does not declare."""
    root = Path(root)
    model, doc, findings = load(root)
    report = FurnaceReport(findings=list(findings), source=source_revision(root, [FURNACES_FILE]))
    if model is None:
        if not findings:
            report.findings.append(
                Finding(
                    FURNACES_FILE,
                    "error",
                    "cheme.furnace-input",
                    "process/furnaces.yaml does not exist",
                    hint=f"write it (schema: {SCHEMA}); see `cheme schema furnaces`",
                )
            )
        return report
    chosen = [(i, f) for i, f in enumerate(model.furnaces) if furnace_id in (None, f.id)]
    if furnace_id is not None and not chosen:
        raise KeyError(furnace_id)
    for index, furnace in chosen:
        result = evaluate_one(furnace)
        for finding in result.findings:
            finding.line = _yaml_line(doc, ("furnaces", index, *_loc(finding)))
        report.results.append(result)
        report.findings.extend(result.findings)
    return report


def furnace_text(report: FurnaceReport) -> str:
    """The report as text, one block per furnace."""
    lines: list[str] = []
    for r in report.results:
        lines.append(
            f"furnace {r.id}: {REACTIONS.get(r.reaction, r.reaction)} [{r.method}, "
            f"{r.basis or 'not evaluated'}{', ' + r.mode if r.mode else ''}]"
        )
        if r.product_total_kg_h:
            lines.append(
                f"  feed {r.feed_kg_h:.6g} kg/h, degree of calcination {r.conversion:.4g}; "
                f"product {r.product_total_kg_h:.6g} kg/h ("
                + ", ".join(f"{k} {v:.5g}" for k, v in r.product_kg_h.items())
                + f"), residual CO2 {r.residual_co2_mass_percent:.3g} %"
            )
            lines.append(
                "  off-gas kg/h: " + ", ".join(f"{k} {v:.5g}" for k, v in r.off_gas_kg_h.items())
            )
            if r.off_gas_mole_fractions:
                lines.append(
                    "  off-gas mole fractions (wet): "
                    + ", ".join(f"{k} {v:.4f}" for k, v in r.off_gas_mole_fractions.items())
                )
            lines.append("  CO2 kg/h: " + ", ".join(f"{k} {v:.5g}" for k, v in r.co2_kg_h.items()))
        if r.reaction_enthalpy_kJ_kmol is not None:
            lines.append(
                f"  reaction enthalpy {r.reaction_enthalpy_kJ_kmol / 1000:.5g} kJ/mol "
                "CaCO3 at 298.15 K"
            )
        for t in r.terms:
            lines.append(
                f"  {t.side:>3} {t.kW:12.5g} kW  {t.name} ({t.provenance}"
                f"{', ' + t.source if t.source else ''})"
            )
        if r.residual_kW is not None:
            lines.append(f"  residual {r.residual_kW:+.4g} kW (tolerance {r.tolerance_kW:.4g} kW)")
        if r.heat_input_range_kW is not None:
            lo, hi = r.heat_input_range_kW
            lines.append(f"  heat input {lo:.5g}-{hi:.5g} kW (conceptual fallback)")
        if r.specific_energy_GJ_t is not None:
            bref = (
                f", BREF {r.bref_range_GJ_t[0]:g}-{r.bref_range_GJ_t[1]:g}"
                if r.bref_range_GJ_t
                else ""
            )
            lines.append(f"  specific heat use {r.specific_energy_GJ_t:.4g} GJ/t product{bref}")
        if r.equilibrium:
            eq = r.equilibrium
            lines.append(
                f"  equilibrium CO2 pressure {eq['co2_equilibrium_pressure_kPa']:.4g} kPa at "
                f"{eq['calcining_temperature_K']:g} K; off-gas CO2 "
                f"{eq['off_gas_co2_partial_pressure_kPa']:.4g} kPa"
            )
        for key, text in r.provenance.items():
            lines.append(f"  {key}: {text}")
        for note in r.notes:
            lines.append(f"  note: {note}")
    return "\n".join(lines)
