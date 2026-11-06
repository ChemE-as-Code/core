"""Schema ``cheme/process/v1``: ``process/materials.yaml`` and ``process/flowsheet.yaml``.

Every object has a stable ``id`` (its title is free text: renaming it changes nothing else).
Every quantity carries a unit (its own, else the flowsheet's ``units``), flows a basis, and every
stream property its provenance: ``given`` (a design input), ``assumed`` or ``calculated``.
"""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from chemeascode.domains.chemistry.eos import Critical
from chemeascode.domains.chemistry.thermochemistry import IdealGas
from chemeascode.domains.process import SCHEMA
from chemeascode.foundation.schema_base import INCHIKEY_RE, Origin, unsupported_schema
from chemeascode.foundation.uncertainty import Uncertainty
from chemeascode.foundation.units import PRESSURE_UNITS as PRESSURE_UNITS  # the unit convention
from chemeascode.foundation.units import TEMPERATURE_UNITS as TEMPERATURE_UNITS


class Strict(BaseModel):
    """Unknown keys are refused (as in ``chemeascode.schemas``, which imports this module)."""

    model_config = ConfigDict(extra="forbid")


Provenance = Literal["given", "assumed", "calculated"]
Direction = Literal["in", "out"]
FlowKind = Literal["material", "energy", "information"]

#: Flow units: basis and factor to kg/h, kmol/h or Nm3/h.
FLOW_UNITS = {
    "kg/h": ("mass", 1.0),
    "kg/s": ("mass", 3600.0),
    "t/h": ("mass", 1000.0),
    "kmol/h": ("mole", 1.0),
    "kmol/s": ("mole", 3600.0),
    "Nm3/h": ("normal_volume", 1.0),
}
DUTY_UNITS = {"W": 0.001, "kW": 1.0, "MW": 1000.0}
ENTHALPY_UNITS = ("kJ/kmol",)
#: The one unit of each ``state.calculated`` property that is read as a number (energy
#: balances, exergy flows, sheets); another unit is ``cheme.process-unit``, never converted.
CALCULATED_UNITS = {
    "molar_mass": "kg/kmol",
    "density": "kg/m3",
    "enthalpy": "kJ/kmol",
    "exergy": "kJ/kmol",
}
FlowBasis = Literal["mass", "mole", "normal_volume"]


class Versioned(Strict):
    """What every process file starts with."""

    schema_: str = Field(alias="schema", description=f"Always {SCHEMA}.")

    @model_validator(mode="after")
    def _version(self) -> Versioned:
        if self.schema_ != SCHEMA:
            raise ValueError(unsupported_schema(self.schema_, SCHEMA))
        return self


# -- materials.yaml -----------------------------------------------------------------------------


#: kPa per unit of an Antoine pressure.
ANTOINE_PRESSURE = {"bar": 100.0, "kPa": 1.0, "Pa": 0.001, "mmHg": 0.133322368}


class VapourPressure(Strict):
    """A component's vapour pressure, Antoine: ``log10(P) = a - b / (T + c)`` (or ``ln``), P in
    ``pressure_unit``, T in ``temperature_unit``. The default form is the NIST WebBook's (and
    ``cheme chemistry props``'): log10, bar, K."""

    a: float
    b: float
    c: float = 0.0
    form: Literal["log10", "ln"] = "log10"
    pressure_unit: Literal["bar", "kPa", "Pa", "mmHg"] = "bar"
    temperature_unit: Literal["K", "degC"] = "K"
    temperature_range: tuple[float, float] | None = Field(
        default=None, description="(K, K) the parameters were fitted over."
    )
    provenance: Provenance
    source: str = ""

    def kpa(self, kelvin: float) -> float:
        """kPa at *kelvin* K (0 where T + c is not positive: the form has no value there)."""
        t = kelvin - 273.15 if self.temperature_unit == "degC" else kelvin
        if t + self.c <= 0:
            return 0.0
        exponent = self.a - self.b / (t + self.c)
        value = 10.0**exponent if self.form == "log10" else math.exp(exponent)
        return value * ANTOINE_PRESSURE[self.pressure_unit]

    def covers(self, kelvin: float) -> bool:
        low, high = self.temperature_range or (0.0, math.inf)
        return low <= kelvin <= high


class Component(Strict):
    id: str
    name: str
    formula: str = ""
    cas: str = ""
    chebi: str = ""
    inchikey: str | None = Field(
        default=None,
        pattern=INCHIKEY_RE.pattern,
        description="Standard InChIKey: the component's key across databases.",
    )
    smiles: str | None = Field(
        default=None,
        description="SMILES; with the RDKit extra, checked against inchikey and formula.",
    )
    molar_mass: float | None = Field(default=None, gt=0, description="kg/kmol")
    normal_boiling_point: float | None = Field(default=None, gt=0, description="K at 101.325 kPa")
    liquid_heat_capacity: float | None = Field(
        default=None,
        gt=0,
        description="kJ/(kmol K) of the liquid near the reaction temperature: adiabatic liquid "
        "tanks and batches (with the reactions' heat_of_reaction).",
    )
    liquid_molar_volume: float | None = Field(
        default=None,
        gt=0,
        description="m3/kmol near the reaction temperature: the concentrations of a liquid-phase "
        "reaction (ideal mixing).",
    )
    critical: Critical | None = Field(
        default=None,
        description="Critical constants: Peng-Robinson fugacities in equilibria (fugacity: "
        "peng_robinson); cheme chemistry thermo prints them.",
    )
    ideal_gas: IdealGas | None = Field(
        default=None,
        description="Formation data and ideal-gas heat capacity: heats of reaction, equilibrium "
        "constants and reactor duties (cheme chemistry thermo prints it).",
    )
    vapour_pressure: VapourPressure | None = Field(
        default=None,
        description="Antoine vapour pressure: Raoult's law in a batch still (still: with "
        "volatility: raoult).",
        exclude_if=lambda value: value is None,  # a component's dump stays as it was
    )
    heat_of_vaporization: float | None = Field(
        default=None,
        gt=0,
        description="kJ/kmol (not kJ/mol: NIST gives kJ/mol, multiply by 1000): a batch "
        "still's boil-up from its duty, and its duty from its boil-up (give it near the "
        "still's temperature); also the default MTT of a reactor away from atmospheric "
        "pressure (Clausius-Clapeyron from normal_boiling_point; give it near the normal "
        "boiling point; ADR 0058).",
        exclude_if=lambda value: value is None,
    )
    phase: Literal["solid"] | None = Field(
        default=None,
        description="solid: the component is a solid (a crystal, a hydrate with its water of "
        "crystallization in the formula, e.g. MgSO4(H2O)7), a separate component from the same "
        "substance dissolved. A stream's dry solid is the sum of its solid components, the rest "
        "is liquid (mother liquor or moisture): see chemeascode.domains.process.solids.",
    )


class Template(Strict):
    """An ordered component list a stream names."""

    id: str
    title: str = ""
    components: list[str] = Field(min_length=1)


class Region(Strict):
    """A temperature-pressure box a component is claimed in."""

    temperature: tuple[float, float] = Field(description="K, min and max")
    pressure: tuple[float, float] = Field(description="kPa(a), min and max")
    max_mole_fraction: float | None = Field(
        default=None,
        gt=0.0,
        le=1.0,
        description="The box holds only while the component's mole fraction is at most this "
        "(a box benchmarked in mixtures only). None: at any mole fraction.",
    )


class ApplicationRange(Strict):
    temperature: tuple[float, float] | None = Field(default=None, description="K, min and max")
    pressure: tuple[float, float] | None = Field(default=None, description="kPa(a), min and max")
    vle_pressure: tuple[float, float] | None = Field(
        default=None,
        description="kPa(a): where liquid and two-phase results are claimed (vapour: pressure).",
    )
    phases: list[str] = Field(default_factory=list)
    components: list[str] = Field(default_factory=list, description="CAS numbers.")
    component_regions: dict[str, list[Region]] | None = Field(
        default=None,
        description="CAS number -> the boxes the component is benchmarked in; a state is "
        "claimed only inside a box of every component present. None: temperature and pressure "
        "above apply to every component.",
    )
    pairs: list[str] | None = Field(
        default=None,
        description="Benchmarked binary pairs, 'CAS&CAS' (sorted); a mixture is claimed only "
        "when every pair of its components is listed. None: any mixture of the components.",
    )
    pair_limits: dict[str, dict[str, Annotated[float, Field(gt=0.0, le=1.0)]]] | None = Field(
        default=None,
        description="Pair ('CAS&CAS') -> CAS number -> the largest mole fraction of that "
        "component in a mixture holding both at which the pair is claimed. None: no limits.",
    )


class Benchmark(Strict):
    """The evidence behind a property package's claim."""

    test: str = Field(description="The test file that benchmarks the claim.")
    reference: str = Field(description="What the values are compared against.")
    tolerances: dict[str, float] = Field(
        default_factory=dict, description="What the test asserts inside the claimed range."
    )


class PropertyMethod(Strict):
    """How properties are calculated: written by ``cheme process props --fill``
    (``status: configured``) with the package versions; a placeholder until then."""

    adapter: str = "thermo"
    status: Literal["placeholder", "configured"] = "placeholder"
    package: str | None = Field(
        default=None,
        description="The property package (cheme process props --coverage lists them); "
        "chosen from the streams' components when not given.",
    )
    phase_models: dict[str, str] = Field(default_factory=dict)
    eos: str = ""
    binary_interaction: str = ""
    application_range: ApplicationRange | None = None
    versions: dict[str, str] = Field(default_factory=dict)
    benchmark: Benchmark | None = None


class Materials(Versioned):
    """Components, templates and the property method of the process."""

    kind: Literal["materials"]
    components: list[Component] = Field(default_factory=list)
    templates: list[Template] = Field(default_factory=list)
    property_method: PropertyMethod | None = None


# -- flowsheet.yaml -----------------------------------------------------------------------------


class NormalConditions(Strict):
    temperature: float = Field(gt=0, description="K")
    pressure: float = Field(gt=0, description="kPa(a)")
    basis: Literal["ideal_gas"] = "ideal_gas"


class EnthalpyReference(Strict):
    state: str = Field(description="e.g. ideal_gas or elements")
    temperature: float = Field(gt=0, description="K")
    pressure: float | None = Field(default=None, gt=0, description="kPa(a)")


class Units(Strict):
    """The units a property without its own ``unit`` is in."""

    pressure: str = "kPa(a)"
    temperature: str = "K"
    flow: str = "kg/h"
    duty: str = "kW"
    enthalpy: str = "kJ/kmol"
    normal_conditions: NormalConditions | None = Field(
        default=None, description="Required when any flow is in Nm3/h."
    )
    enthalpy_reference: EnthalpyReference | None = Field(
        default=None, description="Required once any enthalpy is given."
    )


#: How a case's operating point is known. ``extrapolated``: outside what a model or data were
#: checked for; such a case is labelled, never read as predictive.
CaseProvenance = Literal["given", "calculated", "assumed", "extrapolated"]


class CaseApplicability(Strict):
    """Where a case's flows and duties hold: an envelope with its source, not a scaling law."""

    range: str = Field(min_length=1, description="e.g. 350-550 t/d GOX, 70-105 % load.")
    source: str = Field(min_length=3, description="What supports the envelope.")
    limitations: str = ""


class Case(Strict):
    id: str
    description: str = ""
    default: bool = False
    capacity: str | None = Field(
        default=None, description="The declared capacity of this case, e.g. 500 t/d GOX."
    )
    provenance: CaseProvenance | None = Field(
        default=None,
        description="How the case's operating point is known (given, calculated, assumed, "
        "extrapolated).",
    )
    applicability: CaseApplicability | None = None
    source: str | None = Field(
        default=None, description="What the case's operating point rests on."
    )


class Tolerance(Strict):
    """``|in - out| <= abs + rel * max(in, out)``, in kg/h."""

    abs: float = Field(default=1.0, ge=0)
    rel: float = Field(default=0.005, ge=0)


class Link(Strict):
    """What a process object is in the plant: equipment, a line, an instrument or a sheet."""

    target: Literal["equipment", "line", "instrument", "sheet"]
    ref: str
    sheet: str | None = None
    role: str = ""


class Port(Strict):
    id: str
    direction: Direction
    kind: FlowKind = "material"
    delegates: str | None = Field(
        default=None,
        description="Steps and nested blocks: the port of the step's block (the nested block's "
        "parent) this port stands for, when a stream crosses that boundary here.",
    )


class Node(Strict):
    id: str
    title: str = ""
    ports: list[Port] = Field(default_factory=list)
    links: list[Link] = Field(default_factory=list)


class Bed(Strict):
    """A packed catalyst bed (``reactor: pfr``; the model: :mod:`.fixed_bed`). Its size is the
    catalyst mass, else the bed volume, else ``tubes`` tubes of ``diameter`` and ``length``;
    the catalyst (``catalyst:``) gives the bulk density, particle and voidage."""

    catalyst_mass: float | None = Field(default=None, gt=0, description="kg")
    volume: float | None = Field(default=None, gt=0, description="m3 of bed")
    diameter: float | None = Field(
        default=None, gt=0, description="m, of a tube (or the vessel): pressure drop, cooling"
    )
    length: float | None = Field(default=None, gt=0, description="m")
    tubes: int = Field(default=1, ge=1)
    heat: Literal["adiabatic", "isothermal", "cooled"] = "adiabatic"
    coolant_temperature: float | None = Field(default=None, gt=0, description="K, cooled beds")
    heat_transfer_coefficient: float | None = Field(
        default=None, gt=0, description="W/(m2 K), overall, bed to coolant (cooled beds)"
    )
    viscosity: float | None = Field(
        default=None, gt=0, description="Pa s, of the gas (Ergun pressure drop)"
    )
    diffusivity: float | None = Field(
        default=None,
        gt=0,
        description="m2/s: the key reactants' diffusivity in the gas (effectiveness factor, "
        "Weisz-Prater, Mears)",
        exclude_if=lambda value: value is None,
    )
    time_on_stream: float | None = Field(
        default=None,
        ge=0,
        description="h: the catalyst's age the bed is solved at (its deactivation law); the "
        "end of run sizes the bed. None: fresh.",
        exclude_if=lambda value: value is None,  # a fresh bed's fingerprint stays as it was
    )
    provenance: Provenance
    source: str = ""


class Tank(Strict):
    """A continuous stirred tank (``reactor: cstr``; the model: :mod:`.stirred_tank`): its
    volume, or the space time V / Q0 on the inlet's volumetric flow, of each of ``count`` equal
    tanks in series; isothermal (at the outlet's temperature, else the inlet's) or adiabatic."""

    volume: float | None = Field(default=None, gt=0, description="m3 of liquid or gas, per tank")
    residence_time: float | None = Field(
        default=None, gt=0, description="s, V / Q0 per tank (instead of volume)"
    )
    count: int = Field(default=1, ge=1, description="Equal tanks in series.")
    heat: Literal["isothermal", "adiabatic"] = "isothermal"
    catalyst_loading: float | None = Field(
        default=None,
        gt=0,
        description="kg of catalyst per m3 of reactor: for rate laws per kg of catalyst.",
    )
    time_on_stream: float | None = Field(
        default=None,
        ge=0,
        description="h: the age of the step's catalyst (catalyst:, its deactivation law) the "
        "tank is solved at. None: fresh.",
        exclude_if=lambda value: value is None,  # a fresh tank's fingerprint stays as it was
    )
    provenance: Provenance
    source: str = ""

    @model_validator(mode="after")
    def _size(self) -> Tank:
        if (self.volume is None) == (self.residence_time is None):
            raise ValueError("give volume or residence_time, one of them")
        return self


class BatchTarget(Strict):
    key: str = Field(description="The component whose conversion ends the batch.")
    conversion: float = Field(gt=0, lt=1)


class HeatOfSolution(Strict):
    """The integral heat of solution, dilution or mixing of a dose's components as they mix into
    the batch's liquid (ADR 0063): per kmol of the component dosed (kJ/kmol = J/mol), at the
    batch's dilution and temperature, negative when mixing releases heat (as a heat of
    reaction). A dosed gas's heat of absorption (its dissolved share, ``absorbed``) goes here
    too; the heats of the reactions that consume it are then on the dissolved basis."""

    values: dict[str, float] = Field(
        min_length=1, description="Component of the dose -> kJ/kmol (J/mol) of it dosed."
    )
    unit: Literal["kJ/kmol"] = "kJ/kmol"
    provenance: Provenance
    source: str = ""


class Dosing(Strict):
    """A feed dosed into a semi-batch (``reactor: semibatch``): an inlet stream of the step,
    its flow the amount dosed per hour of charge, fed from ``start`` at a constant rate over
    ``time``, or in the ``profile``'s segments one after the other."""

    stream: str = Field(description="The inlet stream dosed (the step's other inlets: the charge).")
    time: float | None = Field(default=None, gt=0, description="s of dosing at a constant rate")
    profile: list[tuple[float, float]] = Field(
        default_factory=list,
        description="(s, share of the feed) segments, each at a constant rate, one after the "
        "other; the shares add up to 1.",
        exclude_if=lambda value: not value,
    )
    start: float = Field(default=0.0, ge=0, description="s after the charge the dosing starts")
    absorbed: float | None = Field(
        default=None,
        gt=0,
        le=1,
        description="A dosed gas: the share of the dose the liquid takes up (it dissolves on "
        "entry); the rest passes through to batch.vent's stream. None: all of it dissolves.",
        exclude_if=lambda value: value is None,  # a dose's fingerprint stays as it was
    )
    heat_of_solution: HeatOfSolution | None = Field(
        default=None,
        description="The heat its components release (or take up) as they mix into the "
        "liquid, released at the dose's rate: in the semi-batch's heat, duty, peak cooling "
        "duty and dT_ad, not in the MTSR (ADR 0063).",
        exclude_if=lambda value: value is None,  # a dose's fingerprint stays as it was
    )

    @model_validator(mode="after")
    def _form(self) -> Dosing:
        if (self.time is None) == (not self.profile):
            raise ValueError("give time or profile, one of them")
        if any(d <= 0 or s < 0 for d, s in self.profile):
            raise ValueError("profile: durations positive, shares not negative")
        if self.profile and abs(sum(s for _, s in self.profile) - 1.0) > 1e-6:
            raise ValueError("profile: the shares add up to 1")
        return self

    def segments(self) -> list[tuple[float, float, float]]:
        """(start s, end s, share of the feed) of each segment."""
        found, clock = [], self.start
        for duration, share in self.profile or [(self.time or 0.0, 1.0)]:
            found.append((clock, clock + duration, share))
            clock += duration
        return found


class VentVapour(Strict):
    """The vent gas leaves the vessel saturated with the liquid's volatile components at its
    temperature and pressure (ADR 0062): ``y_i = gamma_i x_i P_i^sat(T) / P`` (Raoult, each
    component's Antoine ``vapour_pressure``; ``gamma_i`` 1, an ideal liquid, unless
    ``activity`` gives a sourced constant), so each kmol of vent gas carries ``Y / (1 - Y)``
    kmol of vapour, ``Y = sum_i y_i``."""

    components: list[str] = Field(
        default_factory=list,
        description="The volatile components the gas carries; default every component in the "
        "liquid with a vapour_pressure (a vent component is a gas, never one of them).",
        exclude_if=lambda value: not value,
    )
    activity: dict[str, float] = Field(
        default_factory=dict,
        description="Component -> a constant activity coefficient in the vessel's liquid, from "
        "a source (default 1: an ideal liquid).",
        exclude_if=lambda value: not value,
    )
    source: str = ""

    @model_validator(mode="after")
    def _positive(self) -> VentVapour:
        if len(set(self.components)) != len(self.components):
            raise ValueError("vent.vapour.components: each component once")
        if any(g <= 0 for g in self.activity.values()):
            raise ValueError("vent.vapour.activity: a coefficient above 0")
        if self.components and (stray := sorted(set(self.activity) - set(self.components))):
            raise ValueError(
                "vent.vapour.activity of a component not in its components: " + ", ".join(stray)
            )
        return self


class VentCondenser(Strict):
    """A partial condenser on the vent (ADR 0062): the vapour-laden gas is cooled to
    ``temperature``, the non-condensables leave it saturated there over an ideal condensate
    (a flash with the vent's gases as inerts), and the condensate ``returns`` to the vessel
    (reflux), or leaves by an outlet stream of the step. Its duty goes on the step's energy
    stream at ``energy_port`` (ADR 0059)."""

    temperature: float = Field(gt=0, description="K: the gas and condensate leave at it.")
    returns: str = Field(
        default="vessel",
        description="vessel (the condensate runs back into the liquid), or the outlet stream "
        "of the step the condensate leaves by.",
    )
    energy_port: str | None = Field(
        default=None,
        description="The step's energy port whose stream takes the condenser's duty (the heat "
        "it removes); none: the duty is reported, not written.",
        exclude_if=lambda value: value is None,
    )
    provenance: Provenance
    source: str = ""


class HenryConstant(Strict):
    """A vent gas's solubility in the batch's liquid, Henry's law ``p_g = H x_g`` (kPa per mole
    fraction): ``points`` of (K, kPa); ln H is interpolated linearly in 1/T between them (one
    point: H at every temperature)."""

    points: list[tuple[float, float]] = Field(
        min_length=1, description="(temperature K, H kPa per mole fraction) pairs."
    )
    provenance: Provenance
    source: str = ""

    @model_validator(mode="after")
    def _positive(self) -> HenryConstant:
        if any(t <= 0 or h <= 0 for t, h in self.points):
            raise ValueError("henry.points: temperatures and constants above 0")
        if len({t for t, _ in self.points}) != len(self.points):
            raise ValueError("henry.points: each temperature once")
        return self

    def kpa(self, kelvin: float) -> tuple[float, bool]:
        """kPa per mole fraction at *kelvin* K, and whether it is extrapolated (outside the
        points' temperatures; the end segment, or the one point, is carried on)."""
        points = sorted(self.points)
        if len(points) == 1:
            return points[0][1], abs(kelvin - points[0][0]) > 1e-9
        low, high = points[0][0], points[-1][0]
        k = 1
        while k < len(points) - 1 and kelvin > points[k][0]:
            k += 1
        (t1, h1), (t2, h2) = points[k - 1], points[k]
        share = (1 / kelvin - 1 / t1) / (1 / t2 - 1 / t1)
        value = math.exp(math.log(h1) + share * (math.log(h2) - math.log(h1)))
        return value, not low - 1e-9 <= kelvin <= high + 1e-9


class Vent(Strict):
    """The gas a batch or semi-batch gives off (ADR 0054): the listed ``components`` leave the
    liquid as they form, by the outlet ``stream`` (the step's other outlet is the liquid). They
    do not accumulate in the liquid and count in neither its volume nor its concentrations; a
    ``fraction`` below 1 leaves that share of what forms and keeps the rest dissolved.

    ADR 0062: ``henry`` gives a component's dissolved share from its solubility instead (the
    liquid at the end saturated at the gas's partial pressure; ``fraction`` stays for a
    component without one); ``vapour`` saturates the gas with the liquid's volatile components;
    a ``condenser`` cools it and returns the condensate."""

    stream: str = Field(description="The outlet stream of the step the gas leaves by.")
    components: list[str] = Field(
        min_length=1, description="The components that leave the liquid as they form."
    )
    fraction: dict[str, float] = Field(
        default_factory=dict,
        description="Component -> the share of what forms that leaves (default 1).",
        exclude_if=lambda value: not value,
    )
    henry: dict[str, HenryConstant] = Field(
        default_factory=dict,
        description="Component -> its Henry's-law constant in the liquid (ADR 0062): the share "
        "that stays dissolved follows from it, instead of a fraction.",
        exclude_if=lambda value: not value,  # a vent's fingerprint stays as in 1.9.0
    )
    vapour: VentVapour | None = Field(
        default=None,
        description="The gas leaves saturated with the liquid's volatile components (ADR 0062).",
        exclude_if=lambda value: value is None,
    )
    condenser: VentCondenser | None = Field(
        default=None,
        description="A partial vent condenser: {temperature K, returns: vessel or a stream, "
        "energy_port} (ADR 0062; needs vapour).",
        exclude_if=lambda value: value is None,
    )

    @model_validator(mode="after")
    def _shares(self) -> Vent:
        if len(set(self.components)) != len(self.components):
            raise ValueError("vent.components: each component once")
        if stray := sorted(set(self.fraction) - set(self.components)):
            raise ValueError("vent.fraction of a component not in components: " + ", ".join(stray))
        if any(not 0 < f <= 1 for f in self.fraction.values()):
            raise ValueError("vent.fraction: a share above 0, at most 1")
        if stray := sorted(set(self.henry) - set(self.components)):
            raise ValueError("vent.henry of a component not in components: " + ", ".join(stray))
        if both := sorted(set(self.henry) & set(self.fraction)):
            raise ValueError(
                "vent: henry or fraction for a component, not both: " + ", ".join(both)
            )
        if self.vapour is not None and (
            both := sorted(set(self.vapour.components) & set(self.components))
        ):
            raise ValueError(
                "vent.vapour.components: a vent component is a gas: " + ", ".join(both)
            )
        if self.condenser is not None and self.vapour is None:
            raise ValueError("vent.condenser condenses the vapour: give vent.vapour too")
        if self.condenser is not None and self.condenser.returns == self.stream:
            raise ValueError("vent.condenser.returns: the condensate's stream is not the vent's")
        return self

    def shares(self) -> dict[str, float]:
        """Component -> the share of what forms that leaves."""
        return {n: self.fraction.get(n, 1.0) for n in self.components}


class Batch(Strict):
    """A batch (``reactor: batch``; the model: :mod:`.stirred_tank`): the inlet is the charge
    (its flow the charge per hour), the outlet its composition when the batch ends, after
    ``time`` or at the ``target`` conversion; isothermal or adiabatic. A liquid batch keeps its
    composition's volume (ideal mixing), a gas batch its volume (the pressure changes).

    A semi-batch (``reactor: semibatch``, liquid) adds the ``dosing`` feeds to the charge; its
    ``time`` or ``target`` is the post-reaction after the last dose (neither: it ends with the
    dosing). A liquid batch or semi-batch with a ``vent`` gives off the vent's components as
    they form, by a second outlet."""

    time: float | None = Field(default=None, gt=0, description="s of reaction")
    target: BatchTarget | None = None
    heat: Literal["isothermal", "adiabatic"] = "isothermal"
    catalyst_loading: float | None = Field(
        default=None, gt=0, description="kg of catalyst per m3: rate laws per kg of catalyst."
    )
    dosing: list[Dosing] = Field(
        default_factory=list,
        description="reactor: semibatch: the dosed feeds.",
        exclude_if=lambda value: not value,  # a batch's fingerprint stays as it was
    )
    vent: Vent | None = Field(
        default=None,
        description="A liquid batch or semi-batch that gives off gas: {stream, components, "
        "fraction} (ADR 0054), with henry, vapour and a condenser (ADR 0062).",
        exclude_if=lambda value: value is None,  # an unvented batch's fingerprint stays
    )
    heat_up: bool = Field(
        default=False,
        description="An isothermal batch or semi-batch: count the charge's heat-up from its "
        "inlet temperature to the batch's in the model's duty (ADR 0063); default: the model "
        "holds the batch at its temperature from the start and leaves it to the recipe.",
        exclude_if=lambda value: not value,  # a batch's fingerprint stays as it was
    )
    provenance: Provenance
    source: str = ""

    @model_validator(mode="after")
    def _end(self) -> Batch:
        if self.time is not None and self.target is not None:
            raise ValueError("give time or target, one of them")
        if self.heat_up and self.heat == "adiabatic":
            raise ValueError("heat_up: an isothermal batch (an adiabatic one exchanges no heat)")
        if not self.dosing and self.time is None and self.target is None:
            raise ValueError("give time or target, one of them")
        streams = [d.stream for d in self.dosing]
        if len(set(streams)) != len(streams):
            raise ValueError("dosing: each stream once")
        return self

    def dosing_end(self) -> float:
        """s: when the last dose ends (0 without dosing)."""
        return max((b for d in self.dosing for _, b, _ in d.segments()), default=0.0)


class SelectivityUncertainty(Strict):
    """The uncertainty of a ``selectivity:``'s figures, each relative to its value: sampled by
    cheme process reactor-uncertainty, never part of an outlet's fingerprint."""

    conversion: Uncertainty | None = Field(default=None, description="Of the key's conversion.")
    products: dict[str, Uncertainty] = Field(
        default_factory=dict, description="Product id -> the uncertainty of its selectivity."
    )


class Selectivity(Strict):
    """A conversion reactor given as reported: the per-pass ``conversion`` of the ``key``
    component and the molar selectivity to each product, ``F_p formed / F_key converted``. The
    extents of the reactions follow (series and parallel side reactions in one step)."""

    key: str = Field(description="The component converted (a reactant of the reactions).")
    conversion: float = Field(gt=0, le=1, description="Per pass, of the key's inlet flow.")
    products: dict[str, float] = Field(
        min_length=1, description="Product id -> kmol formed per kmol of the key converted."
    )
    provenance: Provenance
    source: str = ""
    uncertainty: SelectivityUncertainty | None = Field(
        default=None,
        description="Of the conversion and the selectivities, e.g. {conversion: {gsd2: 1.1}, "
        "products: {B: {distribution: triangular, low: 0.9, high: 1.1}}}: sampled by cheme "
        "process reactor-uncertainty.",
        exclude_if=lambda value: value is None,
    )

    @model_validator(mode="after")
    def _positive(self) -> Selectivity:
        if any(v < 0 for v in self.products.values()):
            raise ValueError("a selectivity is not negative")
        uncertain = self.uncertainty.products if self.uncertainty is not None else {}
        if stray := [p for p in uncertain if p not in self.products]:
            raise ValueError(
                "an uncertainty of a selectivity not given: " + ", ".join(sorted(stray))
            )
        return self


class ReactionHazard(Strict):
    """What the thermal screening of a reactor (``cheme process reactor-hazards``) needs beyond
    the reactions: the decomposition and the technical limit, from calorimetry and the design."""

    td24: float | None = Field(
        default=None,
        gt=0,
        description="K: the temperature at which the decomposition's adiabatic time to maximum "
        "rate is 24 h (DSC, ARC; never estimated here).",
    )
    mtt: float | None = Field(
        default=None,
        gt=0,
        description="K: the maximum technical temperature (the boiling point at the reactor's "
        "pressure, a relief set temperature); default: the lowest boiling point of the "
        "liquid's components at the reactor's pressure (the normal boiling point at about "
        "atmospheric pressure, else Clausius-Clapeyron with heat_of_vaporization), leaving "
        "out a batch's vent components, a dosed gas and dissolved gases (a minor share of the "
        "liquid boiling below the process temperature; ADR 0058).",
    )
    reactions: list[str] = Field(
        default_factory=list,
        description="The reactions of the step whose heat sets dT_ad and the MTSR (each run to "
        "completion, the largest counts), e.g. the main reaction without a slow side reaction "
        "(ADR 0058). Default: every reaction.",
        exclude_if=lambda value: not value,  # a reactor's dump stays as it was
    )
    vent_capacity: float | None = Field(
        default=None,
        gt=0,
        description="m3/h of gas the vent and its line pass at the vessel's pressure, from the "
        "vent sizing: compared with the gas a vented batch gives off at the MTSR (ADR 0058).",
        exclude_if=lambda value: value is None,
    )
    provenance: Provenance
    source: str = ""


class Reacting(Strict):
    """What blocks and steps say about the reactions taking place in them."""

    reactions: list[str] = Field(
        default_factory=list,
        description="Reaction ids of process/reactions.yaml that take place here: the balance "
        "is reactive (elements and extents instead of components).",
    )
    conversion: dict[str, float] = Field(
        default_factory=dict,
        description="Reaction id -> conversion of its key component here, instead of the "
        "reaction's own conversion (cheme process propagate).",
    )
    reactor: (
        Literal["conversion", "equilibrium", "gibbs", "pfr", "cstr", "batch", "semibatch"] | None
    ) = Field(
        default=None,
        description="How cheme process propagate solves the outlet: conversion (of each "
        "reaction's key component), equilibrium (of the reactions, ideal gas, at the outlet's "
        "temperature and pressure), gibbs (every reaction among the stream's components) or "
        "pfr (a fixed bed: the reactions' rate laws along its bed), cstr (stirred tanks: the "
        "rate laws at the outlet), batch (the rate laws over the batch time) or semibatch (a "
        "batch with feeds dosed into its charge: batch.dosing); none: conversion when every "
        "reaction has one.",
    )
    bed: Bed | None = Field(default=None, description="reactor: pfr: the catalyst bed.")
    tank: Tank | None = Field(default=None, description="reactor: cstr: the tank(s).")
    hazard: ReactionHazard | None = Field(
        default=None, description="TD24 and MTT for the thermal screening of the reactor."
    )
    selectivity: Selectivity | None = Field(
        default=None,
        description="A conversion reactor by the key's conversion and the selectivities to its "
        "products (instead of a conversion per reaction).",
    )
    batch: Batch | None = Field(default=None, description="reactor: batch or semibatch: the batch.")
    catalyst: str | None = Field(
        default=None, description="The catalyst its bed holds: an id of process/catalysts.yaml."
    )
    fugacity: Literal["ideal", "peng_robinson"] = Field(
        default="ideal",
        description="Equilibrium and Gibbs reactors: the gas as ideal, or with Peng-Robinson "
        "fugacity coefficients (the components' critical constants) for high pressures.",
    )
    approach: float = Field(
        default=0.0,
        description="Equilibrium and Gibbs reactors: K is taken at the outlet temperature plus "
        "this approach, K (positive: less conversion of an exothermic reaction).",
    )


class SaltingOut(Strict):
    """The Setschenow correction of a pure-solvent solubility for the spectator solutes of the
    mother liquor: ``log10(s0 / s) = sum_i k_i m_i`` (``log: ln``: the natural logarithm), with
    ``m_i`` the molality of spectator ``i`` in the mother liquor (mol per kg of free solvent)
    and ``k_i`` its coefficient on the molal scale (kg/mol; a molar-scale constant in L/mol is
    converted with its source's liquor density beforehand)."""

    coefficients: dict[str, float] = Field(
        min_length=1,
        description="Spectator id -> k_i (kg/mol, positive salting out, negative salting in); "
        "every spectator of the crystallizer once, 0 stated where it has no effect.",
    )
    log: Literal["log10", "ln"] = "log10"
    provenance: Provenance
    source: str = ""


class Solubility(Strict):
    """The solubility of a crystallizer's solute in its solvent: ``points`` (temperature in K,
    value), interpolated linearly at the crystallizer's temperature and never extrapolated, or
    one ``value`` that holds at the crystallizer's conditions as stated by its source (the
    saturated mother liquor; no temperature dependence claimed).

    With spectator solutes (``crystallizer.spectators``), the solubility is either measured in
    that mother liquor (``measured_in: mother_liquor``) or the pure solvent's corrected by a
    ``salting_out:`` (Setschenow) coefficient per spectator; a pure-solvent value alone is
    refused (``cheme.process-crystallizer``)."""

    unit: Literal["kg/kg_solvent", "mass_fraction", "kg/kg_liquor"] = Field(
        description="kg of anhydrous solute per kg of solvent (g/100 g divided by 100), the "
        "solute's mass fraction in the saturated solution (spectators included), or kg per kg "
        "of solute-free liquor (solvent plus spectators; measured_in: mother_liquor)."
    )
    points: list[tuple[float, float]] = Field(
        default_factory=list, description="(K, value) pairs, increasing in temperature."
    )
    value: float | None = Field(default=None, gt=0)
    measured_in: Literal["pure_solvent", "mother_liquor"] = Field(
        default="pure_solvent",
        description="Where the data were measured: in the pure solvent, or in the crystallizer's "
        "mother liquor with its spectator solutes (at the composition its source states).",
        exclude_if=lambda value: value == "pure_solvent",  # fingerprints stay as they were
    )
    salting_out: SaltingOut | None = Field(
        default=None,
        description="Setschenow coefficients that correct the pure-solvent data for the "
        "spectators' molality in the mother liquor.",
        exclude_if=lambda value: value is None,
    )
    provenance: Provenance
    source: str = ""

    @model_validator(mode="after")
    def _form(self) -> Solubility:
        if bool(self.points) == (self.value is not None):
            raise ValueError("give points or value, one of them")
        if self.unit == "kg/kg_liquor" and self.measured_in != "mother_liquor":
            raise ValueError(
                "unit kg/kg_liquor: data measured in the mother liquor (measured_in: mother_liquor)"
            )
        if self.salting_out is not None and self.measured_in != "pure_solvent":
            raise ValueError(
                "salting_out corrects pure-solvent data: not with measured_in: "
                "mother_liquor (the liquor's data already hold the spectators)"
            )
        temperatures = [t for t, _ in self.points]
        if any(t <= 0 for t in temperatures) or temperatures != sorted(set(temperatures)):
            raise ValueError("points: temperatures in K, positive and strictly increasing")
        values = [v for _, v in self.points] + ([self.value] if self.value is not None else [])
        if any(v <= 0 for v in values):
            raise ValueError("solubility values must be positive")
        if self.unit == "mass_fraction" and any(v >= 1 for v in values):
            raise ValueError("a mass fraction solubility must be below 1")
        return self


class ImposedYield(Strict):
    """The fraction of the anhydrous solute entering the crystallizer that crystallizes,
    specified (an empirical or vendor yield), not predicted."""

    value: float = Field(ge=0, lt=1)
    provenance: Provenance
    source: str = ""


class Evaporation(Strict):
    """Solvent removed as vapour before or in the crystallizer, one of: ``flow`` (kg/h),
    ``feed_fraction`` (of the crystallizer feed's total mass), ``solvent_fraction`` (of the
    feed's solvent) or ``concentration`` (the solute's mass fraction in the liquid after
    evaporation, crystals not yet formed)."""

    flow: float | None = Field(default=None, ge=0, description="kg/h of solvent")
    feed_fraction: float | None = Field(default=None, ge=0, lt=1)
    solvent_fraction: float | None = Field(default=None, ge=0, lt=1)
    concentration: float | None = Field(default=None, gt=0, lt=1)
    provenance: Provenance
    source: str = ""

    @model_validator(mode="after")
    def _one(self) -> Evaporation:
        given = [
            n
            for n in ("flow", "feed_fraction", "solvent_fraction", "concentration")
            if getattr(self, n) is not None
        ]
        if len(given) != 1:
            raise ValueError("give one of flow, feed_fraction, solvent_fraction or concentration")
        return self


class CakeLiquid(Strict):
    """The liquid (mother liquor) held in a filter or centrifuge cake."""

    value: float = Field(ge=0)
    basis: Literal["mass_fraction", "per_kg_solid"] = Field(
        description="mass_fraction: liquid over the wet cake's mass (below 1); per_kg_solid: kg "
        "of liquid per kg of dry solid."
    )

    @model_validator(mode="after")
    def _range(self) -> CakeLiquid:
        if self.basis == "mass_fraction" and self.value >= 1:
            raise ValueError("a cake liquid mass fraction must be below 1")
        return self


class Filtration(Strict):
    """A constant-pressure cake filtration (Ruth): the time to pass one batch's filtrate,
    ``t = mu (alpha M V / (2 A^2) + R_m V / A) / dP`` with M the dry solid of the cake and V
    the filtrate's volume per batch (:mod:`.dryer`; ``filter`` ``from:`` this step in
    ``process/recipe.yaml``). The split itself stays the specified one."""

    specific_cake_resistance: float = Field(gt=0, description="alpha, m/kg (incompressible)")
    medium_resistance: float = Field(default=0.0, ge=0, description="R_m, 1/m")
    pressure_difference: float = Field(gt=0, description="kPa across cake and medium")
    viscosity: float = Field(gt=0, description="mPa s of the filtrate")
    filtrate_density: float | None = Field(
        default=None, gt=0, description="kg/m3; default: the components' liquid_molar_volume"
    )
    area: float | None = Field(
        default=None, gt=0, description="m2; default: the recipe vessel's bottom (a Nutsche)"
    )
    provenance: Provenance
    source: str = ""


class SolidSeparation(Strict):
    """A filter or centrifuge: the fraction of the solid that reaches the cake and the liquid
    the cake holds, specified (no filtration or centrifuge model); the liquid divides with the
    same composition between cake and filtrate. ``outlets`` maps ``cake`` and ``filtrate`` to
    the step's outlet ports (inside a ``crystallizer:``, the crystallizer's own outlets)."""

    solid_recovery: float = Field(gt=0, le=1, description="Fraction of the solid to the cake.")
    cake_liquid: CakeLiquid
    outlets: dict[Literal["cake", "filtrate"], str] = Field(default_factory=dict)
    provenance: Provenance
    source: str = ""
    filtration: Filtration | None = Field(
        default=None,
        description="The filtration time of a batch (Ruth), for a recipe's filter from:.",
        exclude_if=lambda value: value is None,  # a filter's fingerprint stays as it was
    )


class MotherLiquorRecycle(Strict):
    """The fraction of the filtrate returned to the crystallizer's feed (before evaporation);
    the rest leaves as the purge."""

    fraction: float = Field(ge=0, le=1)
    provenance: Provenance
    source: str = ""


class CrystallizerEnergy(Strict):
    """Data of the crystallizer's lumped energy balance, from the feed's temperature to the
    crystallizer's (every outlet leaves at it)."""

    heat_capacity: float = Field(gt=0, description="kJ/(kg K) of the feed solution, constant")
    heat_of_crystallization: float = Field(
        description="kJ per kg of crystal formed, at the crystallizer's temperature: the "
        "enthalpy change, negative when crystallization releases heat."
    )
    latent_heat: float | None = Field(
        default=None, gt=0, description="kJ per kg of solvent evaporated (with evaporation)"
    )
    feed_temperature: float | None = Field(
        default=None, gt=0, description="K; default: the inlet stream's temperature"
    )
    provenance: Provenance
    source: str = ""


class Crystallizer(Strict):
    """A cooling or evaporative crystallizer for one solute in one solvent (the model:
    :mod:`.crystallization`; no population balance, no kinetics): the crystals are the solid
    component ``crystal`` (``phase: solid``; a hydrate's formula is the solute's plus n
    solvent). ``basis: solubility`` predicts the yield from the solubility at ``temperature``
    (the mother liquor leaves saturated); ``basis: yield`` imposes it. With ``separation`` a
    filter or centrifuge follows (outlets ``cake`` and ``mother_liquor``), else one ``slurry``
    outlet; ``recycle`` returns part of the filtrate to the feed. ``spectators`` are other
    dissolved components carried unchanged (a precipitation from a reaction liquor); its
    inlets are taken together (a reslurry wash: the cake and the wash liquid)."""

    solute: str = Field(description="The dissolved component that crystallizes.")
    solvent: str
    crystal: str = Field(description="The solid component formed (phase: solid).")
    basis: Literal["solubility", "yield"]
    temperature: float | None = Field(
        default=None, gt=0, description="K, the crystallizer's (the mother liquor's)"
    )
    solubility: Solubility | None = None
    yield_: ImposedYield | None = Field(default=None, alias="yield")
    evaporation: Evaporation | None = None
    separation: SolidSeparation | None = None
    recycle: MotherLiquorRecycle | None = None
    energy: CrystallizerEnergy | None = None
    spectators: list[str] = Field(
        default_factory=list,
        description="Dissolved components besides the solute and solvent (salts, base, "
        "unreacted reagent): carried unchanged in the mother liquor, never crystallized or "
        "evaporated; the solubility then needs measured_in: mother_liquor or salting_out:.",
        exclude_if=lambda value: not value,  # a single-solute crystallizer's fingerprint stays
    )
    outlets: dict[Literal["slurry", "cake", "mother_liquor", "vapour"], str] = Field(
        description="Role -> the step's outlet port."
    )

    @model_validator(mode="after")
    def _consistent(self) -> Crystallizer:
        if self.basis == "solubility" and self.solubility is None:
            raise ValueError("basis: solubility needs solubility:")
        if self.basis == "yield" and self.yield_ is None:
            raise ValueError("basis: yield needs yield:")
        if self.solubility is not None and self.solubility.points and self.temperature is None:
            raise ValueError("solubility points need the crystallizer's temperature:")
        if self.recycle is not None and self.separation is None:
            raise ValueError("recycle: needs separation: (the filtrate is what is recycled)")
        if self.separation is not None and self.separation.outlets:
            raise ValueError(
                "separation.outlets: inside a crystallizer the outlets are the crystallizer's "
                "(cake, mother_liquor)"
            )
        roles = set(self.outlets)
        want = {"cake", "mother_liquor"} if self.separation is not None else {"slurry"}
        if self.evaporation is not None:
            want.add("vapour")
        if roles != want:
            raise ValueError(f"outlets: give exactly {', '.join(sorted(want))}")
        if len({self.solute, self.solvent, self.crystal}) != 3:
            raise ValueError("solute, solvent and crystal must be three different components")
        if len(set(self.spectators)) != len(self.spectators) or {
            self.solute,
            self.solvent,
            self.crystal,
        } & set(self.spectators):
            raise ValueError("spectators: each once, none the solute, solvent or crystal")
        salting = self.solubility.salting_out if self.solubility is not None else None
        if salting is not None and set(salting.coefficients) != set(self.spectators):
            raise ValueError(
                "solubility.salting_out.coefficients: one coefficient for each spectator "
                "(0 where it has no effect), no others"
            )
        return self


class ResidualMoisture(Strict):
    """The volatiles a dried product keeps: the dryer's specification."""

    value: float = Field(ge=0)
    basis: Literal["mass_fraction", "per_kg_solid"] = Field(
        description="mass_fraction: volatiles over the dried product's mass (below 1); "
        "per_kg_solid: kg of volatiles per kg of dry solid (everything not volatile)."
    )
    provenance: Provenance
    source: str = ""

    @model_validator(mode="after")
    def _range(self) -> ResidualMoisture:
        if self.basis == "mass_fraction" and self.value >= 1:
            raise ValueError("a residual moisture mass fraction must be below 1")
        return self


class Declared(Strict):
    """One positive figure with its provenance."""

    value: float = Field(gt=0)
    provenance: Provenance
    source: str = ""


class DryingTime(Strict):
    value: float = Field(gt=0)
    unit: Literal["h", "min", "s"] = "h"
    provenance: Provenance
    source: str = ""


class DryerEnergy(Strict):
    """The dryer's heat: the wet cake from its inlet temperature to the drying temperature,
    the volatiles evaporated at it, and (per batch) the vessel, over an efficiency."""

    heat_capacity: float = Field(gt=0, description="kJ/(kg K) of the wet cake, constant")
    latent_heat: dict[str, float] = Field(
        default_factory=dict,
        description="kJ per kg evaporated, per volatile at the drying temperature; default: "
        "from the component's critical constants (Pitzer's corresponding states).",
    )
    inlet_temperature: float | None = Field(
        default=None, gt=0, description="K of the wet cake; default: the inlet stream's"
    )
    vessel_heat_capacity: float | None = Field(
        default=None,
        gt=0,
        description="kJ/K of the vessel heated with each batch (its metal mass x cp); "
        "counted per batch of process/recipe.yaml.",
    )
    efficiency: float = Field(
        default=1.0, gt=0, le=1, description="Heat to the cake over the heat supplied"
    )
    port: str | None = Field(
        default=None, description="The energy inlet port of the heat: its duty is compared."
    )
    provenance: Provenance
    source: str = ""

    @model_validator(mode="after")
    def _positive(self) -> DryerEnergy:
        if any(v <= 0 for v in self.latent_heat.values()):
            raise ValueError("latent_heat: kJ/kg, positive")
        return self


class Dryer(Strict):
    """A batch (filter-)dryer or vacuum dryer (:mod:`.dryer`): one wet-cake inlet, the dried
    product and the vapour out. The ``volatiles`` leave as vapour down to the
    ``residual_moisture``; every other component (the solid, and what the cake liquid held
    dissolved) stays in the product. The energy (``energy:``) is the cake's sensible heat to
    the drying ``temperature``, the latent heat of the volatiles evaporated and the vessel's
    heat per batch. The drying time (a recipe's ``dry`` ``from:`` this step) is the vapour of a
    batch over the ``drying_rate`` times the heated area of the recipe's vessel, or the given
    ``drying_time``."""

    volatiles: list[str] = Field(min_length=1, description="The components that evaporate.")
    residual_moisture: ResidualMoisture
    temperature: float = Field(gt=0, description="K: the drying temperature (product, vapour)")
    energy: DryerEnergy | None = None
    drying_rate: Declared | None = Field(
        default=None, description="kg evaporated per m2 of heated area and hour, constant"
    )
    drying_time: DryingTime | None = None
    cake_density: Declared | None = Field(
        default=None,
        description="kg/m3 of the wet cake (bulk): sizes the recipe's vessel and its heated area",
    )
    outlets: dict[Literal["product", "vapour"], str] = Field(
        description="Role -> the step's outlet port."
    )

    @model_validator(mode="after")
    def _consistent(self) -> Dryer:
        if set(self.outlets) != {"product", "vapour"}:
            raise ValueError("dryer.outlets: give product and vapour")
        if self.drying_rate is not None and self.drying_time is not None:
            raise ValueError("give drying_rate or drying_time, not both")
        if len(set(self.volatiles)) != len(self.volatiles):
            raise ValueError("dryer.volatiles: each component once")
        return self


class Solids(Strict):
    """The solid-handling models of a block or step (:mod:`.crystallization`, :mod:`.dryer`)."""

    crystallizer: Crystallizer | None = Field(
        default=None, description="A crystallizer (with its filter and recycle)."
    )
    solid_separation: SolidSeparation | None = Field(
        default=None, description="A filter or centrifuge on its own."
    )
    dryer: Dryer | None = Field(
        default=None,
        description="A batch (filter-)dryer or vacuum dryer to a residual moisture.",
        exclude_if=lambda value: value is None,  # other nodes' fingerprints stay as they were
    )

    @model_validator(mode="after")
    def _one_model(self) -> Solids:
        given = [n for n in ("crystallizer", "solid_separation", "dryer") if getattr(self, n)]
        if len(given) > 1:
            if "dryer" not in given:
                raise ValueError("give crystallizer or solid_separation, not both")
            raise ValueError("give one of crystallizer, solid_separation or dryer")
        if self.solid_separation is not None and set(self.solid_separation.outlets) != {
            "cake",
            "filtrate",
        }:
            raise ValueError("solid_separation.outlets: give cake and filtrate")
        return self


class Volatility(Strict):
    """How a batch still's vapour follows from its liquid: ``raoult`` (each volatile
    component's ``vapour_pressure`` in materials.yaml, the still at its bubble point at its
    pressure) or ``constant`` (a relative volatility per volatile component, to any common
    reference: ``alpha``)."""

    model: Literal["raoult", "constant"]
    alpha: dict[str, float] = Field(
        default_factory=dict,
        description="constant: component -> relative volatility (positive).",
        exclude_if=lambda value: not value,
    )
    provenance: Provenance
    source: str = ""

    @model_validator(mode="after")
    def _form(self) -> Volatility:
        if (self.model == "constant") != bool(self.alpha):
            raise ValueError("alpha: with model constant, and only then")
        if any(v <= 0 for v in self.alpha.values()):
            raise ValueError(
                "alpha: relative volatilities are positive (a non-volatile "
                "component goes in nonvolatile:)"
            )
        return self


class Boilup(Strict):
    """A batch still's boil-up, constant: a vapour rate of one still (kmol/h, kmol/s, kg/h),
    its heat input (kW, with the components' heat_of_vaporization) or a specific rate (1/h: kmol
    of vapour per hour per kmol of the charge)."""

    value: float = Field(gt=0)
    unit: Literal["kmol/h", "kmol/s", "kg/h", "kW", "1/h"]
    provenance: Provenance
    source: str = ""


class ResidueEnd(Strict):
    key: str = Field(description="The component whose mole fraction in the still ends it.")
    mole_fraction: float = Field(ge=0, lt=1)


class PurityEnd(Strict):
    key: str = Field(description="The component whose share in the cut collected ends it.")
    fraction: float = Field(
        gt=0, lt=1, description="The cut's mean share of the key (on the end's basis)."
    )


class StillEnd(Strict):
    """When a batch still (or one of its cuts) stops, one of: ``distilled`` (the share of all
    charged and fed distilled so far, on ``basis`` mole or mass), ``residue`` (the key's mole
    fraction in the still reaches the value), ``time`` (s of boil-up from the start),
    ``temperature`` (K of the still, at its bubble point: volatility raoult) or ``purity`` (the
    cut's mean share of its key, on ``basis`` mole or mass, falls to the value: a product cut
    collected to its specification)."""

    distilled: float | None = Field(default=None, gt=0, lt=1)
    basis: Literal["mole", "mass"] = "mole"
    residue: ResidueEnd | None = None
    time: float | None = Field(default=None, gt=0, description="s of boil-up from the start")
    temperature: float | None = Field(default=None, gt=0, description="K of the still")
    purity: PurityEnd | None = Field(
        default=None,
        description="The cut's mean share of the key falls to the fraction (basis mole or mass).",
        exclude_if=lambda value: value is None,  # a still's fingerprint stays as it was
    )

    @model_validator(mode="after")
    def _one(self) -> StillEnd:
        names = ("distilled", "residue", "time", "temperature", "purity")
        given = [n for n in names if getattr(self, n)]
        if len(given) != 1:
            raise ValueError("give one of distilled, residue, time, temperature or purity")
        return self


class StillCut(Strict):
    """One distillate cut: its outlet port, collected until its ``end``."""

    outlet: str = Field(description="The step's outlet port the cut leaves by.")
    end: StillEnd


class StillFeed(Strict):
    """A solvent swap: an inlet stream of the step fed into the still while it boils,
    ``constant_level`` (as fast as it boils up, the content's moles held at ``down_to`` of
    the charge's) or ``portions`` (put and take: distil down to ``down_to`` of the charge's
    moles, add one of the equal ``portions``, again, until all is in). The stream's flow is
    the amount fed per hour of charge (the flowsheet's basis, as a semi-batch's dose)."""

    stream: str
    mode: Literal["constant_level", "portions"]
    portions: int | None = Field(default=None, ge=1, description="portions: how many")
    down_to: float = Field(
        default=1.0,
        gt=0,
        le=1,
        description="The level: the still's content before each portion (constant_level: "
        "while fed), as a share of the charge's moles.",
    )

    @model_validator(mode="after")
    def _form(self) -> StillFeed:
        if (self.mode == "portions") != (self.portions is not None):
            raise ValueError("portions: with mode portions, and only then")
        if self.mode == "portions" and self.down_to >= 1:
            raise ValueError("mode portions: give down_to below 1 (the level to distil to)")
        return self


class ColumnDistillate(Strict):
    key: str = Field(description="The light key, the component the distillate is held in.")
    mole_fraction: float = Field(gt=0, lt=1)


class Column(Strict):
    """A batch still's rectifying column on the Fenske-Underwood-Gilliland shortcut (Diwekar's
    batch shortcut: :mod:`.batch_still`): ``stages`` theoretical stages, the still included (or
    ``minimum_reflux_factor``: the stages from Gilliland at the start, at that factor times
    Underwood's minimum reflux for ``distillate``), total condenser, no holdup. ``reflux:
    constant`` at ``ratio`` (L/D; with the factor: the factor times the minimum at the start),
    or ``constant_distillate``: the reflux ratio rises to hold the ``distillate``'s mole
    fraction of its key, up to ``maximum_ratio``, and stays there after."""

    stages: float | None = Field(
        default=None, ge=1, description="Theoretical stages, the still (reboiler) included."
    )
    minimum_reflux_factor: float | None = Field(
        default=None,
        gt=1,
        description="Instead of stages: R = factor x Rmin at the start for the distillate, the "
        "stages from Gilliland there.",
    )
    reflux: Literal["constant", "constant_distillate"]
    ratio: float | None = Field(
        default=None, ge=0, description="reflux constant with stages: the reflux ratio L/D."
    )
    distillate: ColumnDistillate | None = Field(
        default=None,
        description="constant_distillate: the distillate held; with minimum_reflux_factor: the "
        "distillate at the start the column is designed for.",
    )
    maximum_ratio: float | None = Field(
        default=None,
        gt=0,
        description="constant_distillate: the largest reflux ratio; past it the reflux stays "
        "there and the distillate's purity falls.",
    )
    heavy_key: str | None = Field(
        default=None,
        description="The heavy key of Underwood's minimum reflux (named: for the whole "
        "batch). Default: the next less volatile component of the charge after the "
        "distillate's key; without one, at each point the next less volatile one after the most "
        "volatile component that is not a trace (below 1 % of the still's vapour).",
    )
    provenance: Provenance
    source: str = ""

    @model_validator(mode="after")
    def _form(self) -> Column:
        if (self.stages is None) == (self.minimum_reflux_factor is None):
            raise ValueError("column: give stages or minimum_reflux_factor")
        if self.reflux == "constant":
            if self.stages is not None and self.ratio is None:
                raise ValueError("column: reflux constant with stages needs ratio")
            if self.minimum_reflux_factor is not None and self.ratio is not None:
                raise ValueError("column: give ratio or minimum_reflux_factor, not both")
            if self.maximum_ratio is not None:
                raise ValueError("column: maximum_ratio is for reflux constant_distillate")
        else:
            if self.ratio is not None:
                raise ValueError("column: reflux constant_distillate takes no ratio")
            if self.maximum_ratio is None:
                raise ValueError("column: reflux constant_distillate needs maximum_ratio")
        if self.distillate is None and (
            self.reflux == "constant_distillate" or self.minimum_reflux_factor is not None
        ):
            raise ValueError("column: give distillate {key, mole_fraction}")
        if self.distillate is not None and self.reflux == "constant" and self.stages is not None:
            raise ValueError("column: distillate is for constant_distillate or the factor")
        if self.distillate is not None and self.heavy_key == self.distillate.key:
            raise ValueError("column: the heavy key is not the distillate's key")
        return self


class Still(Strict):
    """A batch (Rayleigh) still, shortcut level (the model: :mod:`.batch_still`): one charge
    (the step's material inlet besides a ``feed``), boiled up at ``boilup`` and condensed
    totally (one equilibrium stage, no reflux); ``outlets`` maps ``distillate`` and
    ``residue`` to the step's outlet ports, or ``cuts`` collect the distillate in turn (then
    ``outlets`` names the residue only). With a ``feed`` it is a solvent swap: the ends apply
    once all of the feed is in (no end: it stops then; portions: down to the level)."""

    pressure: float | None = Field(
        default=None, gt=0, description="kPa(a) of the still; default: the charge's"
    )
    volatility: Volatility
    nonvolatile: list[str] = Field(
        default_factory=list,
        description="Components that stay in the still (solid components always do).",
    )
    boilup: Boilup
    end: StillEnd | None = None
    cuts: list[StillCut] = Field(default_factory=list)
    feed: StillFeed | None = None
    outlets: dict[Literal["distillate", "residue"], str] = Field(
        description="Role -> the step's outlet port."
    )
    heat_up: bool = Field(
        default=False,
        description="Count the charge's heat-up from its inlet temperature to its bubble point "
        "(volatility raoult), and a swap's feed warmed to the still's temperature as it mixes "
        "in, in the still's duty and its whole energy per batch (ADR 0063); default: the "
        "boil-up's latent heat alone.",
        exclude_if=lambda value: not value,  # a still's dump stays as it was
    )
    column: Column | None = Field(
        default=None,
        description="A rectifying column on the still (batch rectification, ADR 0061).",
        exclude_if=lambda value: value is None,  # a still's fingerprint stays as it was
    )
    condenser_port: str | None = Field(
        default=None,
        description="The energy port (out, to cooling) whose stream carries the condenser's "
        "duty; default with a column: its one heat stream out.",
        exclude_if=lambda value: value is None,
    )
    provenance: Provenance
    source: str = ""

    @model_validator(mode="after")
    def _consistent(self) -> Still:
        if self.cuts and self.end is not None:
            raise ValueError("give end or cuts, not both")
        if self.cuts and set(self.outlets) != {"residue"}:
            raise ValueError("with cuts, outlets names the residue only (each cut its outlet)")
        if not self.cuts and set(self.outlets) != {"distillate", "residue"}:
            raise ValueError("outlets: give distillate and residue")
        if not self.cuts and self.end is None and self.feed is None:
            raise ValueError("give end (or cuts): when the still stops")
        ends = [self.end] if self.end is not None else [c.end for c in self.cuts]
        if self.volatility.model == "constant" and any(e.temperature for e in ends):
            raise ValueError("an end at a temperature needs volatility raoult")
        if self.heat_up and self.volatility.model == "constant":
            raise ValueError("heat_up needs volatility raoult (the charge's bubble point)")
        ports = [c.outlet for c in self.cuts]
        if len(set(ports)) != len(ports):
            raise ValueError("cuts: each outlet once")
        return self

    def ends(self) -> list[tuple[str, StillEnd | None]]:
        """(outlet port, end) of each cut in turn; one cut without cuts:."""
        if self.cuts:
            return [(c.outlet, c.end) for c in self.cuts]
        return [(self.outlets["distillate"], self.end)]


class Distilling(Strict):
    """The batch still of a block or step (:mod:`.batch_still`)."""

    still: Still | None = Field(
        default=None,
        description="A batch (Rayleigh) still or solvent swap.",
        exclude_if=lambda value: value is None,  # a node's dump stays as it was
    )


class Energetic(Strict):
    """Which energy stream carries the duty of a block's or step's model (ADR 0059)."""

    energy_port: str | None = Field(
        default=None,
        description="A batch or semi-batch reactor, batch still, crystallizer or conversion "
        "step: the energy port whose stream carries the model's year-average duty (cheme "
        "process propagate writes it, or compares a given one); default: its one heat stream "
        "(an energy stream from or to a heating or cooling utility). A stream from or to "
        "another block or step is heat only where energy_port names it.",
        exclude_if=lambda value: value is None,  # a node's dump stays as it was
    )


class Block(Node, Reacting, Solids, Distilling, Energetic):
    class_: str = Field(default="ProcessStep", alias="class", description="DEXPI step class.")
    method: str | None = Field(
        default=None, description="The class's method where DEXPI has one (e.g. Compressing)."
    )
    parent: str | None = Field(
        default=None,
        description="The block this block is drawn inside on the PFD (the BFD shows top-level "
        "blocks); its ports delegate the parent's ports where streams cross the parent boundary.",
    )
    balance_scope: Literal["steady_state_nonreactive", "reactive", "dynamic"] = (
        "steady_state_nonreactive"
    )
    tolerance: Tolerance | None = None
    split: dict[str, float] = Field(
        default_factory=dict,
        description="A splitter block without steps: outlet port -> fraction of the inlet flow.",
    )


class Step(Node, Reacting, Solids, Distilling, Energetic):
    block: str
    class_: str = Field(default="ProcessStep", alias="class", description="DEXPI step class.")
    method: str | None = Field(
        default=None, description="The class's method where DEXPI has one (e.g. Cooling)."
    )
    split: dict[str, float] = Field(
        default_factory=dict,
        description="Splitters (SplittingMaterial): outlet port -> fraction of the inlet flow, "
        "for cheme process propagate.",
    )
    symbol: str | None = Field(
        default=None,
        description="PFD drawing only: the ISO 10628-2 symbol to draw the step with (a symbol "
        "name as `cheme fragment shape` takes it, e.g. TANK_CONE_ROOF_SHAPE, MIXER_SHAPE), "
        "`junction` (a mixing or splitting tee) or `box`; default: its class's symbol.",
        exclude_if=lambda value: (
            value is None
        ),  # fingerprints of steps without one stay as they were
    )


class Quantity(Strict):
    value: float
    unit: str | None = None
    basis: FlowBasis | None = None
    provenance: Provenance
    source: str = ""
    fingerprint: str | None = Field(
        default=None,
        description="Calculated values: the inputs (T, P, composition, method) they were "
        "calculated from; a mismatch is cheme.process-calculated-stale.",
    )
    uncertainty: Uncertainty | None = Field(
        default=None,
        description="Relative to the value, e.g. {gsd2: 1.2} or {distribution: triangular, "
        "low: 0.9, high: 1.1}; cheme assess lca samples a feed's or product's flow with it "
        "instead of the default for its provenance. No calculated value's fingerprint "
        "includes it.",
    )
    origin: Origin | None = Field(
        default=None,
        description="What kind of figure it is, refining the provenance: given measured, "
        "vendor or literature; assumed design-rule, estimate or literature; calculated "
        "simulated (cheme process simulate) or correlation (cheme process props). Another "
        "pairing is cheme.provenance-origin. No calculated value's fingerprint includes it.",
    )


#: What crosses the plant boundary at a terminal (``Terminal.category``): what the TEA and LCA
#: inventories need to know to count it, and what the boundary-completeness check
#: (:func:`chemeascode.domains.assessment.flows.boundary_gaps`) looks for.
TerminalCategory = Literal[
    "raw_material",
    "product",
    "by_product",
    "utility",
    "wastewater",
    "off_gas",
    "solid_waste",
    "emission",
]
#: The utilities a ``utility`` terminal supplies or takes back.
UtilityKind = Literal[
    "steam",
    "hot_oil",
    "fired_heat",
    "cooling_water",
    "air_cooling",
    "refrigerant",
    "electricity",
    "fuel",
    "other",
]


class UtilityLevel(Strict):
    """What a utility terminal supplies: its kind and, for heat, its temperature levels, which
    ``cheme process simulate`` checks against the temperatures of the duty it serves, and, for
    steam, its pressure. ``cheme assess lca`` gives the energy exchange's carrier the level,
    the supply temperature and the steam pressure (core#313)."""

    kind: UtilityKind
    level: str = Field(
        default="",
        description="The utility level's name in the design basis, e.g. LP, MP or HP steam, "
        "a hot-oil circuit or a refrigeration level.",
    )
    pressure: Quantity | None = Field(
        default=None,
        description="Steam: its supply pressure (flowsheet units; a gauge pressure is read "
        "against 101.325 kPa). It does not set the temperature: give supply_temperature "
        "(saturated steam: the saturation temperature at this pressure).",
    )
    supply_temperature: Quantity | None = Field(
        default=None, description="Where the utility enters the exchanger (flowsheet units)."
    )
    return_temperature: Quantity | None = Field(
        default=None,
        description="Where it leaves; not given: the same as the supply (condensing steam, "
        "a boiling refrigerant).",
    )
    min_approach: Quantity | None = Field(
        default=None, description="Least temperature difference to the process side, K."
    )


class Terminal(Node):
    """An external feed (DEXPI Source) or product (DEXPI Sink)."""

    category: TerminalCategory | None = Field(
        default=None,
        description="What crosses the boundary here; not given: unclassified (a gap the "
        "boundary-completeness check reports).",
    )
    utility: UtilityLevel | None = Field(
        default=None, description="category utility: the utility and its temperature levels."
    )


class CompositionValue(Strict):
    basis: Literal["mole_fraction", "mass_fraction"]
    values: dict[str, float] = Field(min_length=1)
    provenance: Provenance
    source: str = ""
    fingerprint: str | None = Field(
        default=None,
        description="Calculated compositions: the inputs they were derived from (cheme "
        "process propagate); a mismatch is cheme.process-calculated-stale.",
    )
    uncertainty: Uncertainty | None = Field(
        default=None,
        description="Of every fraction, relative to it (as on a quantity).",
    )
    origin: Origin | None = Field(
        default=None, description="What kind of figure it is (as on a quantity)."
    )


class PhaseValue(Strict):
    value: Literal["vapor", "liquid", "two-phase"]
    vapor_fraction: float | None = Field(default=None, ge=0, le=1)
    provenance: Provenance
    source: str = ""
    fingerprint: str | None = None


class State(Strict):
    pressure: Quantity | None = None
    temperature: Quantity | None = None
    flow: Quantity | None = None
    composition: CompositionValue | None = None
    phase: PhaseValue | None = None
    duty: Quantity | None = Field(default=None, description="Energy streams.")
    calculated: dict[str, Quantity] = Field(default_factory=dict)


class StreamDef(Strict):
    id: str
    title: str = ""
    kind: FlowKind = "material"
    from_: str = Field(alias="from", description="NODE.port")
    to: str = Field(description="NODE.port")
    template: str | None = None
    state: dict[str, State] = Field(default_factory=dict, description="By case id.")
    links: list[Link] = Field(default_factory=list)


class ViewItem(Strict):
    """A persisted layout override of one object in one view.

    Blocks, feeds and products: ``x``/``y`` (top left, sheet mm), optional ``width``/``height``.
    PFD steps: ``x``/``y`` relative to their block's top left. Streams: ``waypoints``.
    """

    x: float | None = None
    y: float | None = None
    width: float | None = Field(default=None, gt=0)
    height: float | None = Field(default=None, gt=0)
    waypoints: list[tuple[float, float]] = Field(default_factory=list)
    label: tuple[float, float] | None = Field(default=None, description="Label offset, mm.")
    pinned: bool = True


class Layout(Strict):
    bfd: dict[str, ViewItem] = Field(default_factory=dict)
    pfd: dict[str, ViewItem] = Field(default_factory=dict)


class BfdView(Strict):
    """How the BFD draws the boundary streams."""

    aggregate: bool | list[tuple[str, str]] = Field(
        default=False,
        description="Draw parallel boundary streams between the same two BFD nodes as one "
        "connection: true for every pair, or a list of [NODE, NODE] pairs. Streams of different "
        "kinds (material, energy, information) or directions stay separate; balances use the "
        "streams, not the connections.",
    )

    def aggregates(self, a: str, b: str) -> bool:
        """Whether streams between BFD nodes *a* and *b* are drawn as one connection."""
        if isinstance(self.aggregate, bool):
            return self.aggregate
        return any({a, b} == set(pair) for pair in self.aggregate)


class TearGuess(Strict):
    """The first guess of a tear stream, where its loop's iterations start (ADR 0060)."""

    flow: float = Field(default=0.0, ge=0, description="In `unit`; 0: an empty recycle.")
    unit: str | None = Field(default=None, description="A flow unit; default: units.flow.")
    basis: Literal["mole_fraction", "mass_fraction"] = "mass_fraction"
    composition: dict[str, float] = Field(
        default_factory=dict, description="Component id -> fraction on `basis`."
    )


class Tear(Strict):
    """A stream at which ``cheme process propagate`` tears a recycle loop (ADR 0060): its flow
    and composition are iterated until the loop closes, then written as calculated. A given or
    assumed flow or composition of the stream stays fixed (a design specification)."""

    stream: str = Field(description="A material stream between two steps (or blocks).")
    initial: TearGuess | None = Field(
        default=None,
        description="The first guess; default: an empty stream (flow 0).",
        exclude_if=lambda value: value is None,
    )


class Convergence(Strict):
    """How ``cheme process propagate`` converges the loops torn at ``tears`` (ADR 0060)."""

    method: Literal["wegstein", "substitution"] = Field(
        default="wegstein",
        description="Successive substitution, accelerated by Wegstein's method per component "
        "(q bounded to [-5, 0]) or not.",
    )
    max_iterations: int = Field(default=100, ge=1, le=10000)
    damping: float = Field(
        default=1.0,
        gt=0,
        le=1,
        description="Substitution only: the share of the step to the new iterate taken.",
    )
    tolerance: Tolerance | None = Field(
        default=None,
        description="Per component of every tear stream, kg/h; default: the flowsheet's.",
        exclude_if=lambda value: value is None,
    )


class Flowsheet(Versioned):
    """Feeds, products, blocks, steps and streams: the source of the BFD and PFD."""

    kind: Literal["flowsheet"]
    title: str = ""
    units: Units = Field(default_factory=Units)
    cases: list[Case] = Field(default_factory=lambda: [Case(id="design", default=True)])
    tolerance: Tolerance = Field(default_factory=Tolerance)
    feeds: list[Terminal] = Field(default_factory=list)
    products: list[Terminal] = Field(default_factory=list)
    blocks: list[Block] = Field(default_factory=list)
    steps: list[Step] = Field(default_factory=list)
    streams: list[StreamDef] = Field(default_factory=list)
    tears: list[Tear] = Field(
        default_factory=list,
        description="Recycle loops torn for cheme process propagate (ADR 0060).",
        exclude_if=lambda value: not value,  # a plant without recycles dumps as it did
    )
    convergence: Convergence | None = Field(
        default=None,
        description="How propagate converges the torn loops; default: Wegstein, 100 "
        "iterations, the flowsheet's tolerance.",
        exclude_if=lambda value: value is None,
    )
    bfd: BfdView | None = Field(default=None, description="How the BFD draws the streams.")
    layout: Layout = Field(default_factory=Layout)

    def default_case(self) -> str:
        marked = [c.id for c in self.cases if c.default]
        return marked[0] if marked else (self.cases[0].id if self.cases else "design")
