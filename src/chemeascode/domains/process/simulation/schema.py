"""Schema ``cheme/simulation/v1``: ``process/simulation.yaml``.

What a simulator needs beyond the flowsheet: the property package, the compound names where the
CAS number does not find them, and per step the specifications that fix its outlet (outlet
pressure, efficiency, outlet temperature, split fractions). Every specification is a quantity
with its provenance, so an assumed efficiency stays visible as assumed.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from chemeascode.domains.process.schema import Quantity, State, Strict
from chemeascode.domains.process.simulation import SCHEMA
from chemeascode.foundation.schema_base import unsupported_schema

#: Unit operations the translation knows, by cheme-as-code name.
UnitKind = Literal[
    "compressor",
    "expander",
    "pump",
    "heater",
    "cooler",
    "valve",
    "mixer",
    "splitter",
    "flash",
    "heat_exchanger",
    "shortcut_column",
    "distillation_column",
    "component_separator",
    "multi_stream_exchanger",
    "conversion_reactor",
    "equilibrium_reactor",
    "gibbs_reactor",
    "kinetic_pfr",
]
#: How a unit's outlet follows from its inlets: ``predictive`` (the property package and the
#: unit's equations: a flash, a rigorous column, an equilibrium), ``shortcut`` (a short-cut
#: correlation: Fenske-Underwood-Gilliland) or ``specified`` (the engineer states the result:
#: a component separator's recoveries). The basis of each unit kind is
#: :data:`chemeascode.domains.process.simulation.translate.UNIT_BASIS`.
UnitBasis = Literal["predictive", "shortcut", "specified"]
#: What an outlet of a flash or a column carries.
OutletRole = Literal["vapor", "liquid", "distillate", "bottoms", "gas", "condensate"]


class ProductSpec(Strict):
    """What fixes one end of a rigorous column: exactly one of these."""

    reflux_ratio: float | None = Field(default=None, gt=0, description="Condenser only, L/D.")
    flow: Quantity | None = Field(
        default=None, description="The product's flow (mass or molar unit)."
    )
    mole_fraction: dict[str, float] = Field(
        default_factory=dict, description="One component id -> its mole fraction in the product."
    )
    duty: Quantity | None = None
    temperature: Quantity | None = None


class SideDraw(Strict):
    """A product drawn from a stage of a rigorous column."""

    stage: int = Field(ge=1, description="Numbered from the top (1: the condenser, if any).")
    phase: Literal["liquid", "vapor"]
    flow: Quantity = Field(description="Mass or molar flow.")


class HeatIntegration(Strict):
    """A reboiler heated by another column's condenser (a condenser-reboiler)."""

    condenser_of: str = Field(description="The step id of the column whose condenser heats it.")
    min_approach: Quantity | None = Field(
        default=None, description="Least temperature difference across it (default 1 K)."
    )


class KineticCoupling(Strict):
    """How the outer loop around the DWSIM solve converges a kinetic reactor
    (``kinetic_pfr``): the bed solved at the inlet DWSIM gives must reproduce the outlet DWSIM
    has (each component's molar flow and the pressure, relative to the outlet's total molar
    flow and pressure; the temperature in K)."""

    tolerance: float = Field(
        default=1e-4, gt=0, lt=0.1, description="Relative, component flows and pressure."
    )
    temperature_tolerance: float = Field(default=0.05, gt=0, description="K")
    max_iterations: int = Field(
        default=30, ge=1, le=200, description="DWSIM solves at most (each one a full solve)."
    )


class UnitSpec(Strict):
    """The specifications of one step. Which ones a unit needs:

    - compressor, pump, expander: ``efficiency`` (adiabatic, 0 to 1) and ``outlet_pressure``
      or ``pressure_increase`` (expander: ``pressure_drop``); a compressor with intercoolers
      also ``outlet_temperature`` (after each cooler), ``stages`` (default 1: aftercooler
      only) and ``pressure_drop`` (per cooler); its power goes to the energy stream into it,
      the cooling duty to the one out of it; with a second outlet for condensate, each cooler's
      condensed liquid is separated and leaves there;
    - heater, cooler: ``outlet_temperature`` or ``duty``; ``pressure_drop`` (0 when not given);
      a second outlet takes the condensate (``outlets: {port: condensate}`` or a port id such
      as ``condensate``, ``drain``, ``water``): the cooled stream is flashed, its liquid leaves
      there (a cooler with a moisture separator, a direct contact cooler's condensed water);
    - valve: ``outlet_pressure`` or ``pressure_drop``;
    - mixer: nothing (the outlet takes the lowest inlet pressure);
    - splitter: ``split`` here or on the step (outlet port -> fraction of the inlet flow);
    - flash: nothing (adiabatic, at the inlet conditions; put a valve before it to flash at a
      lower pressure), or ``temperature`` and/or ``pressure`` (the duty follows); which outlet
      is vapour and which liquid by ``outlets`` or by the port ids;
    - heat_exchanger (two streams in, two out; DWSIM finds the hot side):
      ``hot_outlet_temperature``, ``cold_outlet_temperature`` or ``duty``; ``hot_pressure_drop``
      and ``cold_pressure_drop`` (0 when not given); which outlet belongs to which inlet by
      ``pairs`` or by the port ids;
    - shortcut_column (Fenske-Underwood-Gilliland): ``light_key`` and ``heavy_key`` (component
      ids), ``light_key_in_bottoms`` and ``heavy_key_in_distillate`` (mole fractions),
      ``reflux_ratio``, ``condenser_pressure``, ``reboiler_pressure``, ``condenser``; which
      outlet is distillate and which bottoms by ``outlets`` or by the port ids;
    - distillation_column (rigorous; a Distilling step with ``stages``): ``stages`` (condenser
      and reboiler included, numbered from the condenser), ``feed_stage`` (or ``feed_stages``
      by inlet port), ``condenser_pressure``, ``reboiler_pressure``, ``condenser_spec`` and
      ``reboiler_spec``; ``condenser``: ``total``, ``partial`` (a vapour product of
      ``vapor_flow`` beside the liquid distillate) or ``none`` (the top stage takes the liquid
      feed, nothing is condensed); ``reboiler: false`` for a column without one (a vapour feed
      at the bottom); ``side_draws`` by outlet port; ``heat_integration`` when the reboiler is
      heated by another column's condenser (checked: the duties balance and the temperature
      difference is positive);
    - component_separator (a Separating step with one stream in and two out, e.g. an adsorber,
      membrane or filter): ``recoveries`` (component -> fraction of its inlet flow into
      ``recovery_outlet``, default the first outlet port; unlisted components go to the other);
      both outlets leave at the inlet temperature and pressure. The recoveries are
      *specified*, not predicted (``basis: specified``, the default for this unit): give
      ``basis_source`` (where the recoveries come from: vendor data, a published module, a
      DESIGN.md decision) and ``operating_basis`` (the conditions they hold for); without a
      source the split is ``cheme.process-sim-specified-unsourced`` (warning). A converged
      simulation closes the balances around the stated split; it does not show the split is
      attainable;
    - multi_stream_exchanger (a heat exchanging step with three or more streams in, as many
      out): ``outlet_temperatures`` by inlet port for every stream but at most one, whose
      outlet then closes the energy balance; ``pressure_drops`` by inlet port (0 when not
      given); outlets paired with inlets by ``pairs`` or by the port ids;
    - conversion_reactor, equilibrium_reactor, gibbs_reactor (a step with ``reactions:`` or
      ``reactor:`` in the flowsheet, which give the unit, the reactions, the conversions and
      the approach): ``mode`` (``isothermal``, the default without ``outlet_temperature``;
      ``adiabatic``; ``outlet_temperature``, the default with it) and ``pressure_drop`` (0 when
      not given); an equilibrium takes ln K from the reaction's ``equilibrium_constant``, else
      from DWSIM's own Gibbs energies of formation; one outlet (vapour) or two (vapour, liquid
      by ``outlets`` or by the port ids);
    - kinetic_pfr (a step with ``reactor: pfr``, its ``bed:`` and ``catalyst:``): no native
      DWSIM unit. cheme-as-code solves the bed (:mod:`chemeascode.domains.process.fixed_bed`:
      1D pseudo-homogeneous plug flow, ideal gas, the reactions' rate laws) at the inlet DWSIM
      gives it; DWSIM sees the bed as a conversion reactor with the bed's conversions, outlet
      temperature and pressure drop, and an outer loop repeats the DWSIM solve until the bed
      at the solved inlet gives the outlet DWSIM has (``coupling``: tolerance and iterations);
      no ``mode``, ``outlet_temperature`` or ``pressure_drop`` (the bed sets them); one outlet.

    ``min_approach`` (heat_exchanger, multi_stream_exchanger) is not a specification but the
    least approach the solved exchanger's temperatures are checked against.
    """

    unit: UnitKind | None = Field(
        default=None,
        description="The unit operation, where the step's DEXPI class does not say (e.g. an "
        "expander drawn as ProcessStep).",
    )
    outlet_pressure: Quantity | None = None
    pressure_increase: Quantity | None = None
    pressure_drop: Quantity | None = None
    outlet_temperature: Quantity | None = None
    duty: Quantity | None = Field(default=None, description="Heat added (negative: removed).")
    efficiency: Quantity | None = Field(default=None, description="Adiabatic, 0 to 1.")
    drive_efficiency: Quantity | None = Field(
        default=None,
        description="Compressor, pump, expander: motor and gear (or generator), 0 to 1; the "
        "energy stream then carries the electric power, the summary also the shaft power.",
    )
    split: dict[str, float] = Field(default_factory=dict)
    temperature: Quantity | None = Field(default=None, description="Flash temperature.")
    pressure: Quantity | None = Field(default=None, description="Flash pressure (absolute).")
    outlets: dict[str, OutletRole] = Field(
        default_factory=dict,
        description="Flash, column, and a cooler or compressor with a condensate outlet: "
        "outlet port -> what it carries.",
    )
    pairs: dict[str, str] = Field(
        default_factory=dict, description="Heat exchanger: inlet port -> its outlet port."
    )
    hot_outlet_temperature: Quantity | None = None
    cold_outlet_temperature: Quantity | None = None
    hot_pressure_drop: Quantity | None = None
    cold_pressure_drop: Quantity | None = None
    light_key: str | None = None
    heavy_key: str | None = None
    light_key_in_bottoms: float | None = Field(default=None, gt=0, lt=1)
    heavy_key_in_distillate: float | None = Field(default=None, gt=0, lt=1)
    reflux_ratio: float | None = Field(default=None, gt=0, description="Actual, L/D.")
    condenser_pressure: Quantity | None = None
    reboiler_pressure: Quantity | None = None
    condenser: Literal["total", "partial", "none"] = "total"
    reboiler: bool = Field(default=True, description="Rigorous column: whether it has one.")
    vapor_flow: Quantity | None = Field(
        default=None, description="Partial condenser: the vapour product's flow."
    )
    side_draws: dict[str, SideDraw] = Field(default_factory=dict, description="By outlet port.")
    heat_integration: HeatIntegration | None = None
    stages: int | None = Field(
        default=None, ge=1, description="Rigorous column (3 or more); intercooled compressor."
    )
    feed_stage: int | None = Field(default=None, ge=1)
    feed_stages: dict[str, int] = Field(default_factory=dict, description="Inlet port -> stage.")
    condenser_spec: ProductSpec | None = None
    reboiler_spec: ProductSpec | None = None
    recoveries: dict[str, float] = Field(default_factory=dict)
    recovery_outlet: str | None = None
    outlet_temperatures: dict[str, Quantity] = Field(default_factory=dict)
    pressure_drops: dict[str, Quantity] = Field(default_factory=dict)
    mode: Literal["isothermal", "adiabatic", "outlet_temperature"] | None = Field(
        default=None, description="Reactors: how the outlet temperature is found."
    )
    coupling: KineticCoupling | None = Field(
        default=None,
        description="kinetic_pfr: the outer loop's tolerance and iterations (defaults when "
        "not given).",
    )
    basis: UnitBasis | None = Field(
        default=None,
        description="How the unit's outlet follows from its inlets; defaults to the unit "
        "kind's (component_separator: specified). A component separator cannot be predictive.",
    )
    basis_source: str | None = Field(
        default=None,
        description="Specified units (component_separator): where the recoveries come from "
        "(vendor data, a cited module or paper, DESIGN.md D-012).",
    )
    operating_basis: str | None = Field(
        default=None,
        description="Specified units: the conditions the recoveries hold for (feed, pressure, "
        "temperature, cycle), e.g. 'PSA at 6 bar(a), 25 degC, vendor quote Q-17'.",
    )
    min_approach: Quantity | None = Field(
        default=None,
        description="heat_exchanger, multi_stream_exchanger: the least temperature difference "
        "between the hot and cold sides (K) the solved exchanger is checked against; overrides "
        "the simulation's min_approach. Not passed to the simulator.",
    )


class SimTolerance(Strict):
    """How far a simulated value may differ from a given or assumed one before
    ``cheme.process-sim-deviation``. Flows use the flowsheet ``tolerance``."""

    temperature: float = Field(default=1.0, ge=0, description="K")
    pressure_rel: float = Field(default=0.01, ge=0)
    composition: float = Field(default=0.001, ge=0, description="Mole fraction, absolute.")


class InteractionParameter(Strict):
    """A binary interaction parameter (kij) of the property package's equation of state, where
    the simulator's own value is not the one to use (fitted to other data, missing)."""

    components: tuple[str, str] = Field(description="The two component ids.")
    kij: Quantity = Field(description="Dimensionless, the same in both orders.")


class MethodSelection(Strict):
    """The recorded thermodynamic model selection the property package rests on: the facts of
    ``select_thermo_model`` (thermodynamic-model-selection), re-evaluated on every translation,
    and the reason an engineer accepted a package the selection did not recommend."""

    facts: dict[str, bool | float | int | str] = Field(
        default_factory=dict,
        description="Inputs of select_thermo_model (pressure_value, pressure_unit, is_polar, "
        "is_electrolyte, has_pseudocomponents, interaction_parameters_available, "
        "liquid_liquid_expected, vapor_association_expected, polymerization_degree).",
    )
    substitution: str | None = Field(
        default=None,
        description="Why property_package is used although the selection did not recommend it "
        "(e.g. the nearest executable substitute of methods.yml, accepted by <who>); without it "
        "such a package is cheme.process-sim-method-not-recommended.",
    )


class Simulation(Strict):
    """``process/simulation.yaml``."""

    schema_: str = Field(alias="schema", description=f"Always {SCHEMA}.")
    kind: Literal["simulation"]
    simulator: Literal["dwsim"] = "dwsim"
    property_package: str = Field(
        default="Peng-Robinson (PR)",
        description="The simulator's property package name: one of the packages the DWSIM "
        "route runs (methods.yml; others are cheme.process-sim-property-package).",
    )
    method_selection: MethodSelection | None = Field(
        default=None,
        description="The recorded model selection: a property_package it does not recommend is "
        "flagged unless a substitution reason is recorded.",
    )
    components: dict[str, str] = Field(
        default_factory=dict,
        description="Component id -> the simulator's compound name, where the CAS number "
        "does not find it.",
    )
    interaction_parameters: list[InteractionParameter] = Field(
        default_factory=list,
        description="Equation-of-state packages (Peng-Robinson, PR78, SRK): kij that replace "
        "the simulator's for these pairs.",
    )
    tolerance: SimTolerance = Field(default_factory=SimTolerance)
    tear_streams: list[str] = Field(
        default_factory=list,
        description="Where recycle loops are torn and solved iteratively (one stream per loop); "
        "chosen by cheme-as-code when not given.",
    )
    exclude: list[str] = Field(
        default_factory=list,
        description="Steps and blocks left out: streams from them into the simulated part are "
        "feeds (they need their values), streams into them are products.",
    )
    guesses: dict[str, State] = Field(
        default_factory=dict,
        description="Tear stream id -> its first guess (temperature, pressure, flow, "
        "composition); a guess, never a stream value.",
    )
    min_approach: Quantity | None = Field(
        default=None,
        description="The least temperature difference (K) every simulated exchanger is checked "
        "against (a spec's min_approach overrides it); not given: only temperature crosses are "
        "reported. A check of the result, not passed to the simulator.",
    )
    specs: dict[str, UnitSpec] = Field(default_factory=dict, description="Step id -> specs.")

    @model_validator(mode="after")
    def _version(self) -> Simulation:
        if self.schema_ != SCHEMA:
            raise ValueError(unsupported_schema(self.schema_, SCHEMA))
        return self
