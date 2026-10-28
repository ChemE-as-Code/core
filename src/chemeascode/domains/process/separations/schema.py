"""``process/adsorption.yaml`` (schema ``cheme/adsorption/v1``): the performance basis of an
adsorber.

One entry per adsorbing separator of the flowsheet (a step or block, by id). It states either
the inputs of core's equilibrium TSA cycle calculation (``performance: calculated``: the layers
with their adsorbent and sourced isotherms, the bed and the cycle) or the results of an external
performance model (``performance: external``: a vendor or published cycle model, with its source,
version and operating range). :mod:`.adsorption` evaluates it; the file is optional: a sourced
``component_separator`` split in ``process/simulation.yaml`` stays the conceptual representation.

Values are ``{value, unit, provenance, source}``; each field accepts the units named in its
description. Isotherm parameters are plain numbers in the units fixed per model (see
:data:`ISOTHERM_PARAMETERS`).
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from chemeascode.foundation.schema_base import Strict

SCHEMA = "cheme/adsorption/v1"

#: Isotherm model -> its parameters. Loadings in mol/kg, energies in kJ/mol, ``b0`` in
#: 1/``pressure_unit``, ``T_ref`` in K. The temperature dependence: ``b = b0 exp(E / (R T))``
#: (``b0`` is the pre-exponential factor, not ``b`` at ``T_ref``). Sips after Hefti et al. (2015)
#: as IDAES writes it: ``q_s = q_s_ref exp(chi (T/T_ref - 1))``,
#: ``n = n_ref + alpha (T/T_ref - 1)``, ``q = q_s (b p)^n / (1 + (b p)^n)``. Toth after Do (1998):
#: ``q_s = q_s_ref exp(chi (1 - T/T_ref))`` (the opposite sign of chi),
#: ``t = t_ref + alpha (1 - T_ref/T)``, ``q = q_s b p / (1 + (b p)^t)^(1/t)``.
ISOTHERM_PARAMETERS: dict[str, tuple[str, ...]] = {
    "langmuir": ("q_s", "b0", "E"),
    "dual-site-langmuir": ("q_s1", "b01", "E1", "q_s2", "b02", "E2"),
    "sips": ("q_s_ref", "chi", "b0", "E", "n_ref", "alpha", "T_ref"),
    "toth": ("q_s_ref", "chi", "b0", "E", "t_ref", "alpha", "T_ref"),
}
#: ``multi-site-langmuir`` (Cmarik et al., NASA/TM-2017-219847) takes ``a0_j`` (mol/kg),
#: ``c0_j`` (mol/(kg K)), ``b0_j`` (1/``pressure_unit``) and ``E_j`` (**K**) for each site
#: j = 1..k: ``q_s,j = a0_j + c0_j T``, ``b_j = b0_j exp(E_j / T)``.


class Value(Strict):
    """One input with its unit and where it comes from."""

    value: float
    unit: str
    provenance: Literal["given", "assumed"] = "given"
    source: str = ""


class Validity(Strict):
    """Where the isotherm was measured and fitted: core evaluates it nowhere else."""

    temperature: tuple[float, float] = Field(description="K, lowest and highest.")
    partial_pressure: tuple[float, float] = Field(
        description="kPa, the lowest and highest partial pressure of the component measured."
    )


class Isotherm(Strict):
    component: str
    model: Literal["langmuir", "dual-site-langmuir", "multi-site-langmuir", "sips", "toth"]
    parameters: dict[str, float] = Field(
        description="See ISOTHERM_PARAMETERS; multi-site-langmuir: a0_j, c0_j, b0_j, E_j (K)."
    )
    pressure_unit: Literal["Pa", "kPa", "bar"] = Field(
        default="kPa", description="The unit of the partial pressure in b0 * p."
    )
    heat_of_adsorption: Value = Field(
        description="Isosteric heat, a positive magnitude: kJ/mol or J/mol."
    )
    valid: Validity
    source: str = Field(description="Where the parameters and their range are published.")


class Layer(Strict):
    """One adsorbent layer of the bed, from the feed end."""

    adsorbent: str
    length: Value = Field(description="m or mm.")
    bulk_density: Value = Field(description="kg/m3 of packed bed.")
    heat_capacity: Value = Field(description="Of the adsorbent: kJ/(kg K) or J/(kg K).")
    void_fraction: Value = Field(
        description="Gas volume (between and inside the particles) per bed volume: - or %."
    )
    isotherms: list[Isotherm] = Field(default_factory=list)
    removes: list[str] = Field(
        default_factory=list,
        description="The components this layer holds until breakthrough (its key components).",
    )
    mass_transfer_zone: Value | None = Field(
        default=None,
        description="Measured length of the mass transfer zone of the key component (m or mm): "
        "the length of unused bed is taken as half of it. Without it the bed is used to its "
        "stoichiometric capacity (an optimistic bound, reported as a limitation).",
    )
    mixture: Literal["extended", "independent"] = Field(
        default="extended",
        description="extended: competitive extended Langmuir or Sips over the components of "
        "the layer with an isotherm of that model; independent: single-component isotherms.",
    )
    life: Value | None = Field(
        default=None, description="Adsorbent life before replacement: a, h or d."
    )


class Purge(Strict):
    flow: Value = Field(description="During heating: kmol/h or mol/s.")
    composition: dict[str, float] = Field(description="Mole fractions; others are zero.")
    supply_temperature: Value = Field(description="Before the regeneration heater: K or °C.")
    heat_capacity: Value = Field(description="Molar, of the purge gas: kJ/(kmol K) or J/(mol K).")


class Cycle(Strict):
    beds: int = Field(default=2, ge=2)
    diameter: Value = Field(description="Bed inside diameter: m or mm.")
    adsorption_time: Value = Field(description="s, min or h.")
    heating_time: Value = Field(description="Hot purge: s, min or h.")
    cooling_time: Value | None = None
    switch_time: Value | None = Field(
        default=None, description="Depressurisation and repressurisation together."
    )
    regeneration_temperature: Value = Field(description="Hot purge at the bed inlet: K or °C.")
    regeneration_pressure: Value = Field(description="kPa(a), bar(a) or MPa(a).")
    purge: Purge
    vessel_heat_capacity: Value | None = Field(
        default=None,
        description="Heat capacity of the vessel wall heated with the bed, per bed: kJ/K.",
    )


class Utility(Strict):
    name: str
    value: float
    unit: str
    basis: str = Field(default="", description="What it is per, e.g. 'per t of feed'.")


class OperatingRange(Strict):
    temperature: tuple[float, float] = Field(description="Feed temperature, K.")
    pressure: tuple[float, float] = Field(description="Feed pressure, kPa(a).")
    mole_fractions: dict[str, tuple[float, float]] = Field(
        default_factory=dict, description="Feed mole fraction of each component, lowest, highest."
    )


class External(Strict):
    """The results of a performance model core does not run."""

    model: str = Field(description="The model or vendor tool, e.g. a published PSA cycle model.")
    version: str = ""
    source: str
    recoveries: dict[str, float] = Field(
        description="Fraction of each component's feed flow into the product outlet; "
        "components not listed are reported as not covered."
    )
    utilities: list[Utility] = Field(default_factory=list)
    operating_range: OperatingRange


class AdsorptionUnit(Strict):
    id: str = Field(description="The adsorbing step or block of process/flowsheet.yaml.")
    technique: Literal["tsa", "psa"]
    performance: Literal["calculated", "external"]
    feed_stream: str | None = Field(
        default=None, description="Default: the node's one material inlet."
    )
    product_outlet: str | None = Field(
        default=None, description="Port of the purified product; default: the first outlet."
    )
    specification: dict[str, Value] = Field(
        default_factory=dict,
        description="Highest mole fraction of each impurity in the product: ppm, ppb, % or -.",
    )
    layers: list[Layer] = Field(default_factory=list)
    cycle: Cycle | None = None
    external: External | None = None
    split_tolerance: float = Field(
        default=0.01,
        ge=0,
        description="Largest absolute difference between a recovery in process/simulation.yaml "
        "and the one this basis gives, for the split to count as following from it.",
    )


class Adsorption(Strict):
    """``process/adsorption.yaml``."""

    schema_: str = Field(alias="schema", description=f"Always {SCHEMA}.")
    kind: Literal["adsorption"]
    units: list[AdsorptionUnit] = Field(default_factory=list)
