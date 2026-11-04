"""Schema ``cheme/electrochemical-measurements/v1`` (``experiments/electrochemistry/<id>.yaml``)
and the processing of measured electrochemical series: Faradaic efficiency, partial current
densities, water dissociation efficiency, power, heat and the charge and carbon balances, per
replicate and as the mean and spread of each point.

A measurement file describes one bench cell (active area, temperature, electrolyte, membrane),
the basis of its voltages, the products it forms (electrons per molecule, the electrode) and
per operating point (a fixed current or current density held for a duration) its replicates:
the voltage (given, or the mean of a chronopotentiometry series over a stated window), the
outlet gas flow and the mole fractions of the products in it, or a Faradaic efficiency given
directly, and the titration of the anolyte (or a water dissociation efficiency given directly).

:func:`evaluate` processes a loaded file (model :data:`MODEL`), :func:`measurement_report`
reads one from a plant repository and records the input fingerprints. Per replicate, with the
current ``I`` (A), the current density ``j`` and the point's duration ``t``:

- the molar outlet flow from a volumetric standard flow (sccm, slpm), ideal gas at the stated
  standard conditions: ``Ndot = c_corr V (p_std / (R T_std))``, times the flow correction
  ``c_corr`` of the meter (default 1); a flow in mol/s is taken as it is;
- the flow of each product ``Ndot_i = x_i Ndot`` and its Faradaic efficiency
  ``FE_i = n_i F Ndot_i / I`` (``n_i`` electrons per molecule, F = 96485.33212 C/mol), its
  partial current density ``j_i = FE_i j``, and the charge balance
  ``sum FE_i + unassigned = 1``;
- the water dissociation efficiency of a bipolar membrane from a Warder double end-point
  titration of the anolyte (aliquot ``V_aliquot`` of the anolyte volume ``V_anolyte``, titrant
  concentration ``c``; ``V0`` the titrant to the second end point of the fresh anolyte, ``V1``
  and ``V2`` to the first and second end point after the run; Prats Vergel et al., Nat. Chem.
  Eng. 2025, Methods):

  ``n_K = (V0 - V2) c V_anolyte / V_aliquot`` (co-cations lost from the anolyte),
  ``n_C = (V2 - V1) c V_anolyte / V_aliquot`` (carbon gained by the anolyte),
  ``WDE = 1 - F (n_K + n_C) / (I t)``

  (each crossing ion carries one charge, as in the paper: carbon crosses as HCO3-); and the
  carbon share of the co-ion current ``n_C / (n_K + n_C)``;
- the electric power ``P = U I`` and, when every product with a Faradaic efficiency gives its
  thermoneutral voltage, the heat at an isothermal boundary ``Q = I (U - sum_i FE_i U_tn,i)``
  (the unassigned current becomes heat);
- with ``gas.inlet``, the carbon balance: carbon fed against carbon in the products, in the
  unreacted reactant (when its outlet fraction is measured) and crossed into the anolyte (from
  the titration, ``n_C / t``).

The Faradaic efficiency (the share of the current that forms each product at the electrodes)
and the water dissociation efficiency (the share of the current the bipolar membrane carries by
dissociating water rather than by co-ions) are separate quantities and never combined.

Per point every quantity has its mean, sample standard deviation and count over the
replicates. :class:`MeasuredPerformance` interpolates the point means piecewise linearly in the
current density and refuses outside the validity range or beyond the measured points: it never
extrapolates. :func:`measurement_plots` draws the polarisation curve, the Faradaic
efficiencies, the partial current densities and the water dissociation efficiency as SVG, each
only when the data support it.

Rules (``cheme.electrochem-*``), each finding naming the file, line, rule and a hint:

- ``schema``: the file does not follow the schema, a duplicate id, an unknown product, two
  points at one current density; ``unit``: a unit the quantity does not take;
- ``input-missing`` (error): a standard flow without standard conditions, product fractions
  without the outlet flow, a titration without the method block or the point's duration, a
  voltage series with no sample in its window;
- ``fe-sum-high`` (error): the Faradaic efficiencies of a point add up to more than
  ``1 + 3 sd`` (more than 1.05 with one replicate); ``fe-sum-low`` (warning): to less than 0.9
  (unmeasured products, e.g. liquids);
- ``single-replicate`` (info): a point with one replicate has no standard deviation;
- ``crossover-assumed`` (warning): a membrane cell without a measured water dissociation
  efficiency;
- ``voltage-basis`` (info): the voltages are electrode potentials against a reference, not a
  terminal voltage (no polarisation curve, power or heat);
- ``titration`` (warning): titration volumes out of the order ``V1 <= V2 <= V0``;
- ``carbon-balance`` (warning): carbon in and out differ by more than 5 % of the carbon fed;
- ``flow-correction`` (info): no flow correction stated, 1 used; ``flow-position`` (warning):
  the flow was measured at the inlet and is taken as the outlet flow;
- ``heat`` (info): a product without a thermoneutral voltage, so no heat is computed;
- ``validity`` (info): the validity range is derived from the points; (warning) a declared
  range extends beyond the measured points.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field, ValidationError, model_validator

from chemeascode.domains.chemistry.formulas import parse_formula
from chemeascode.foundation.findings import Finding
from chemeascode.foundation.schema_base import Origin, Provenance, Strict, unsupported_schema
from chemeascode.foundation.units import to_kelvin
from chemeascode.foundation.yamlsource import _compose, _yaml_line, syntax_finding

SCHEMA = "cheme/electrochemical-measurements/v1"
#: Where measurement files are in a plant repository.
MEASUREMENTS_DIR = "experiments/electrochemistry"
#: C/mol, CODATA 2018 (exact since the 2019 SI redefinition: N_A e).
FARADAY = 96485.33212
#: J/(mol K), CODATA 2018 (exact: N_A k).
GAS_CONSTANT = 8.314462618
#: The model this module evaluates, as recorded with every result.
MODEL = {"id": "electrochemical-measurements", "version": 1, "schema": SCHEMA}

ASSUMPTIONS = (
    "Faraday's law per product: FE_i = n_i F Ndot_i / I, F = 96485.33212 C/mol (CODATA 2018)",
    "a volumetric standard flow (sccm, slpm) is an ideal gas at the stated standard "
    "conditions, R = 8.314462618 J/(mol K); the flow correction of the meter multiplies it",
    "water dissociation efficiency from the Warder double end-point titration: "
    "WDE = 1 - F (n_K + n_C) / (I t), every crossing co-ion carrying one charge (carbon as "
    "HCO3-), over the point's duration",
    "the heat at an isothermal boundary Q = I (U - sum FE_i U_tn,i): current not assigned to "
    "a product becomes heat",
    "per point: mean and sample standard deviation over the replicates; between points the "
    "means and standard deviations are interpolated linearly in the current density",
)
LIMITATIONS = (
    "the Faradaic efficiency and the water dissociation efficiency are separate: neither "
    "corrects the other",
    "no polarisation model: outside the validity range or beyond the measured points nothing "
    "is extrapolated",
    "the heat counts only the products' reaction enthalpies (their thermoneutral voltages); "
    "pH gradients, neutralisation of crossed-over ions and heats of dilution are not included",
    "the standard deviation is over the replicates of a point; the uncertainty of the "
    "instruments (flow meter, gas chromatograph, titration) is not propagated",
)

_CURRENT = {"A": 1.0, "mA": 1e-3, "kA": 1e3}
_CURRENT_DENSITY = {"A/m2": 1.0, "kA/m2": 1e3, "mA/cm2": 10.0, "A/cm2": 1e4}
_AREA = {"m2": 1.0, "cm2": 1e-4}
_DURATION = {"s": 1.0, "min": 60.0, "h": 3600.0}
_VOLTAGE = {"V": 1.0, "mV": 1e-3}
_PRESSURE = {"Pa": 1.0, "Pa(a)": 1.0, "kPa": 1e3, "kPa(a)": 1e3, "bar": 1e5, "bar(a)": 1e5}
_PRESSURE["atm"] = 101325.0
_CONCENTRATION = {"mol/L": 1.0, "M": 1.0, "mmol/L": 1e-3, "mol/m3": 1e-3}
_VOLUME = {"mL": 1e-3, "L": 1.0}  # to L
_FRACTION = {None: 1.0, "-": 1.0, "1": 1.0, "%": 0.01, "mol%": 0.01, "ppm": 1e-6}
#: m3/s per unit of a volumetric standard flow
_STANDARD_FLOW = {"sccm": 1e-6 / 60, "slpm": 1e-3 / 60}
#: the Faradaic efficiencies of one replicate may add up to this much above 1
_FE_SUM_HIGH_SINGLE = 1.05
#: below this sum some product is not measured (fe-sum-low)
_FE_SUM_LOW = 0.9
#: relative carbon imbalance reported as a warning (a screening threshold, not a test)
_CARBON_TOLERANCE = 0.05


# -- schema -------------------------------------------------------------------------------------


class Value(Strict):
    """A stated or measured number with its unit (and, where it is not the file's, a source)."""

    value: float
    unit: str | None = None
    source: str = ""


class Electrolyte(Strict):
    name: str = Field(description="As text, e.g. '1 M KOH'.")
    concentration: Value | None = Field(default=None, description="mol/L (M), mmol/L, mol/m3.")


class Membrane(Strict):
    kind: Literal["bipolar", "cation_exchange", "anion_exchange", "diaphragm", "none"]
    bias: Literal["forward", "reverse"] | None = Field(
        default=None, description="Of a bipolar membrane: reverse bias dissociates water."
    )
    name: str = ""


class CellSetup(Strict):
    """The bench cell all points of the file were measured in."""

    active_area: Value = Field(description="Geometric electrode area (cm2, m2).")
    temperature: Value | None = Field(default=None, description="K or °C.")
    electrolyte: Electrolyte | None = None
    membrane: Membrane | None = None


class Product(Strict):
    id: str = Field(description="As in the fractions and Faradaic efficiencies (CO, H2, ...).")
    electrons: float = Field(gt=0, description="Electrons per molecule of the product formed.")
    electrode: Literal["cathode", "anode"]
    reaction: str | None = Field(
        default=None, description="The reaction of process/reactions.yaml that forms it."
    )
    formula: str | None = Field(
        default=None, description="For the carbon balance (default: the id, when it reads)."
    )
    thermoneutral_voltage: Value | None = Field(
        default=None, description="V: dH / (n F) of its reaction, for the heat at the boundary."
    )


class StandardConditions(Strict):
    temperature: Value = Field(description="K or °C, e.g. 273.15 K.")
    pressure: Value = Field(description="Pa, kPa, bar or atm (absolute), e.g. 101.325 kPa.")


class FlowCorrection(Strict):
    """A factor on the meter's reading (a mass-flow meter calibrated on another gas)."""

    factor: float = Field(gt=0)
    source: str = Field(min_length=1, description="Where the factor comes from.")


class GasInlet(Strict):
    """The reactant fed, for the carbon balance."""

    component: str = Field(description="The reactant (CO2); its outlet fraction may be measured.")
    formula: str | None = Field(default=None, description="Default: the component id.")
    flow: float = Field(gt=0, description="In gas.flow_unit.")


class Gas(Strict):
    flow_unit: Literal["sccm", "slpm", "mol/s"]
    standard_conditions: StandardConditions | None = Field(
        default=None,
        description="Required for sccm and slpm: the meter's reference state (never assumed).",
    )
    flow_position: Literal["outlet", "inlet"] = "outlet"
    flow_correction: FlowCorrection | None = None
    inlet: GasInlet | None = None


class TitrationMethod(Strict):
    method: Literal["warder-double-endpoint"]
    titrant_concentration: Value = Field(description="mol/L of the acid titrant (HCl).")
    anolyte_volume: Value = Field(description="mL or L of anolyte in the reservoir.")
    aliquot_volume: Value = Field(description="mL or L titrated.")
    source: str = ""


class TitrationVolumes(Strict):
    """Titrant volumes: V0 to the second end point of the fresh anolyte, V1 and V2 to the
    first and second end point after the run."""

    V0: float = Field(ge=0)
    V1: float = Field(ge=0)
    V2: float = Field(ge=0)
    unit: Literal["mL", "L"] = "mL"


class Voltage(Strict):
    """A voltage given directly (``value``) or the mean of a series of ``[t s, U]`` samples
    over the ``window`` (s; default: every sample)."""

    value: float | None = None
    series: list[tuple[float, float]] | None = None
    window: tuple[float, float] | None = None
    unit: str = "V"

    @model_validator(mode="after")
    def _one(self) -> Voltage:
        if (self.value is None) == (self.series is None):
            raise ValueError("give the voltage as value or as series, not both")
        if self.window is not None and not self.window[0] < self.window[1]:
            raise ValueError("window is (start, end) in s with start < end")
        return self


class Replicate(Strict):
    id: str
    voltage: Voltage | None = None
    outlet_flow: float | None = Field(default=None, gt=0, description="In gas.flow_unit.")
    fractions: dict[str, Value] = Field(
        default_factory=dict,
        description="Mole fraction of each product (or the reactant) in the gas: ppm, mol%, -.",
    )
    faradaic_efficiency: dict[str, Value] = Field(
        default_factory=dict, description="Given directly per product: fraction or %."
    )
    titration: TitrationVolumes | None = None
    water_dissociation_efficiency: Value | None = Field(
        default=None, description="Given directly (fraction or %), instead of a titration."
    )
    source: str = Field(default="", description="Locator: the file in the dataset.")

    @model_validator(mode="after")
    def _either(self) -> Replicate:
        both = sorted(set(self.fractions) & set(self.faradaic_efficiency))
        if both:
            raise ValueError(
                f"{', '.join(both)}: give gas data (fractions) or a Faradaic efficiency, not both"
            )
        if self.titration is not None and self.water_dissociation_efficiency is not None:
            raise ValueError("give a titration or a water dissociation efficiency, not both")
        return self


class MeasurementPoint(Strict):
    id: str
    current: Value | None = Field(default=None, description="A, mA.")
    current_density: Value | None = Field(default=None, description="A/m2, mA/cm2, A/cm2.")
    duration: Value | None = Field(default=None, description="s, min, h; needed for the WDE.")
    replicates: list[Replicate] = Field(min_length=1)
    source: str = ""

    @model_validator(mode="after")
    def _current(self) -> MeasurementPoint:
        if (self.current is None) == (self.current_density is None):
            raise ValueError("give current or current_density, not both")
        return self


class Validity(Strict):
    """Where the measured performance holds; a field left out is derived from the points."""

    current_density: tuple[float, float] | None = Field(default=None, description="A/m2")
    temperature: tuple[float, float] | None = Field(default=None, description="K")
    electrolyte: str = ""
    duration: float | None = Field(default=None, gt=0, description="s, the longest run")
    source: str = ""

    @model_validator(mode="after")
    def _ordered(self) -> Validity:
        for name in ("current_density", "temperature"):
            value = getattr(self, name)
            if value is not None and not 0 <= value[0] <= value[1]:
                raise ValueError(f"{name} is (min, max) with 0 <= min <= max")
        return self


class ElectrochemicalMeasurements(Strict):
    """A measured series of one electrochemical cell."""

    schema_: str = Field(alias="schema", description=f"Always {SCHEMA}.")
    kind: Literal["electrochemical_measurements"]
    id: str
    title: str = ""
    provenance: Provenance
    origin: Origin | None = None
    source: str = Field(default="", description="Citation and DOI of the data.")
    licence: str = ""
    cell: CellSetup
    voltage_basis: Literal["cell", "cell_ir_corrected", "electrode_vs_reference"] = Field(
        description="cell: at the terminals; cell_ir_corrected: the ohmic loss removed; "
        "electrode_vs_reference: one electrode against a reference electrode."
    )
    products: list[Product] = Field(default_factory=list)
    gas: Gas | None = None
    titration: TitrationMethod | None = None
    points: list[MeasurementPoint] = Field(min_length=1)
    validity: Validity | None = None

    @model_validator(mode="after")
    def _version(self) -> ElectrochemicalMeasurements:
        if self.schema_ != SCHEMA:
            raise ValueError(unsupported_schema(self.schema_, SCHEMA))
        return self


# -- results ------------------------------------------------------------------------------------


@dataclass
class Stat:
    """Mean, sample standard deviation (None for one value) and count."""

    mean: float
    sd: float | None
    n: int

    @classmethod
    def of(cls, values: Sequence[float | None]) -> Stat | None:
        found = [v for v in values if v is not None]
        if not found:
            return None
        mean = sum(found) / len(found)
        if len(found) < 2:
            return cls(mean, None, 1)
        var = sum((v - mean) ** 2 for v in found) / (len(found) - 1)
        return cls(mean, math.sqrt(var), len(found))

    def as_dict(self) -> dict[str, Any]:
        return {"mean": self.mean, "sd": self.sd, "n": self.n}


@dataclass
class ReplicateResult:
    id: str
    line: int | None = None
    source: str = ""
    voltage_v: float | None = None
    voltage_samples: int | None = None
    outlet_flow_mol_s: float | None = None
    #: product (or reactant) -> mol/s in the outlet gas
    flows_mol_s: dict[str, float] = field(default_factory=dict)
    faradaic_efficiency: dict[str, float] = field(default_factory=dict)
    #: product -> "gas" (from the flow and fraction) or "given"
    faradaic_basis: dict[str, str] = field(default_factory=dict)
    faradaic_sum: float | None = None
    unassigned_current_fraction: float | None = None
    partial_current_density_a_m2: dict[str, float] = field(default_factory=dict)
    co_ions_mol: dict[str, float] = field(default_factory=dict)
    co_ion_carbon_fraction: float | None = None
    water_dissociation_efficiency: float | None = None
    water_dissociation_basis: str | None = None
    power_w: float | None = None
    heat_w: float | None = None
    carbon: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class PointResult:
    id: str
    line: int | None = None
    current_a: float | None = None
    current_density_a_m2: float | None = None
    duration_s: float | None = None
    replicates: list[ReplicateResult] = field(default_factory=list)
    voltage_v: Stat | None = None
    faradaic_efficiency: dict[str, Stat] = field(default_factory=dict)
    faradaic_sum: Stat | None = None
    partial_current_density_a_m2: dict[str, Stat] = field(default_factory=dict)
    water_dissociation_efficiency: Stat | None = None
    co_ion_carbon_fraction: Stat | None = None
    power_w: Stat | None = None
    heat_w: Stat | None = None

    def as_dict(self) -> dict[str, Any]:
        def stat(s: Stat | None) -> dict[str, Any] | None:
            return s.as_dict() if s is not None else None

        return {
            "id": self.id,
            "line": self.line,
            "current_a": self.current_a,
            "current_density_a_m2": self.current_density_a_m2,
            "duration_s": self.duration_s,
            "voltage_v": stat(self.voltage_v),
            "faradaic_efficiency": {k: stat(v) for k, v in self.faradaic_efficiency.items()},
            "faradaic_sum": stat(self.faradaic_sum),
            "partial_current_density_a_m2": {
                k: stat(v) for k, v in self.partial_current_density_a_m2.items()
            },
            "water_dissociation_efficiency": stat(self.water_dissociation_efficiency),
            "co_ion_carbon_fraction": stat(self.co_ion_carbon_fraction),
            "power_w": stat(self.power_w),
            "heat_w": stat(self.heat_w),
            "replicates": [r.as_dict() for r in self.replicates],
        }


@dataclass
class MeasurementReport:
    """A processed measurement file; ``points`` is empty when the file does not load."""

    file: str
    id: str | None = None
    title: str = ""
    citation: str = ""
    licence: str = ""
    provenance: str | None = None
    voltage_basis: str | None = None
    membrane: dict[str, Any] | None = None
    products: list[str] = field(default_factory=list)
    #: product id -> the reaction id it names
    reactions: dict[str, str] = field(default_factory=dict)
    temperature_k: float | None = None
    area_m2: float | None = None
    points: list[PointResult] = field(default_factory=list)
    #: current_density (A/m2), temperature (K) and duration (s) bounds, electrolyte, derived
    validity: dict[str, Any] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    source: Any = None

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "error"]

    def as_dict(self) -> dict[str, Any]:
        from chemeascode.foundation.schemas.run import finding_dict

        return {
            "model": MODEL,
            "core_version": _version(),
            "assumptions": list(ASSUMPTIONS),
            "limitations": [*LIMITATIONS, *self.limitations],
            "file": self.file,
            "id": self.id,
            "title": self.title,
            "dataset": {
                "citation": self.citation,
                "licence": self.licence,
                "provenance": self.provenance,
            },
            "voltage_basis": self.voltage_basis,
            "membrane": self.membrane,
            "products": list(self.products),
            "reactions": dict(self.reactions),
            "temperature_k": self.temperature_k,
            "area_m2": self.area_m2,
            "validity": dict(self.validity),
            "points": [p.as_dict() for p in self.points],
            "findings": [finding_dict(f) for f in self.findings],
            "source": self.source.as_dict() if self.source is not None else None,
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), indent=2)


def _version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("cheme-as-code")
    except PackageNotFoundError:
        return "unknown"


# -- evaluation ---------------------------------------------------------------------------------


class _Out:
    def __init__(self, file: str, doc: Any) -> None:
        self.file = file
        self.doc = doc
        self.findings: list[Finding] = []

    def add(self, level: str, rule: str, message: str, loc: list[Any], ids: list[str], hint: str):
        self.findings.append(
            Finding(
                self.file,
                level,  # type: ignore[arg-type]
                f"cheme.electrochem-{rule}",
                message,
                line=_yaml_line(self.doc, loc),
                ids=ids,
                hint=hint,
            )
        )

    def value(
        self, quantity: Value | None, units: dict[Any, float], what: str, loc, ids
    ) -> float | None:
        """*quantity* in the base unit of *units*; None (and a unit error) for another unit."""
        if quantity is None:
            return None
        factor = units.get(quantity.unit)
        if factor is None:
            self.add(
                "error",
                "unit",
                f"{what} in unit {quantity.unit!r}",
                loc,
                ids,
                "use one of " + ", ".join(str(u) for u in units if u is not None),
            )
            return None
        return quantity.value * factor


def _carbon(formula: str | None, name: str) -> int | None:
    atoms = parse_formula(formula or name)
    return None if atoms is None else atoms.get("C", 0)


@dataclass
class _Context:
    area_m2: float | None
    #: mol/s per unit of the outlet flow reading (correction included); None: not convertible
    flow_mol_s: float | None
    #: mol/s per unit of the inlet flow (no meter correction)
    inlet_mol_s: float | None
    #: mol of titrant per unit titrant volume x (anolyte / aliquot): mol per mL of titrant
    titration_mol: float | None
    thermoneutral: dict[str, float | None]
    products: dict[str, Product]
    terminal: bool


def _context(data: ElectrochemicalMeasurements, out: _Out, report: MeasurementReport) -> _Context:
    cell = data.cell
    area = out.value(cell.active_area, _AREA, "cell.active_area", ["cell", "active_area"], [])
    if area is not None and area <= 0:
        out.add(
            "error",
            "schema",
            "cell.active_area is not positive",
            ["cell", "active_area"],
            [],
            "give the electrode area",
        )
        area = None
    report.area_m2 = area
    if cell.temperature is not None:
        report.temperature_k = to_kelvin(cell.temperature.value, cell.temperature.unit or "")
        if report.temperature_k is None:
            out.add(
                "error",
                "unit",
                f"cell.temperature in unit {cell.temperature.unit!r}",
                ["cell", "temperature"],
                [],
                "K or °C",
            )
    if cell.membrane is not None:
        report.membrane = cell.membrane.model_dump()
    flow = inlet = None
    gas = data.gas
    if gas is not None:
        if gas.flow_unit == "mol/s":
            flow = inlet = 1.0
        elif gas.standard_conditions is None:
            out.add(
                "error",
                "input-missing",
                f"gas flows in {gas.flow_unit} without standard_conditions: no molar flow, "
                "no Faradaic efficiency from the gas",
                ["gas", "flow_unit"],
                [],
                "give gas.standard_conditions: the flow meter's reference temperature and "
                "pressure (273.15 K and 101.325 kPa is the common choice; check the meter's "
                "manual, some use 293.15 K or 294.26 K); it is never assumed",
            )
        else:
            std = gas.standard_conditions
            t = to_kelvin(std.temperature.value, std.temperature.unit or "")
            if t is None:
                out.add(
                    "error",
                    "unit",
                    f"standard temperature in unit {std.temperature.unit!r}",
                    ["gas", "standard_conditions", "temperature"],
                    [],
                    "K or °C",
                )
            p = out.value(
                std.pressure,
                _PRESSURE,
                "standard pressure",
                ["gas", "standard_conditions", "pressure"],
                [],
            )
            if t is not None and p is not None and t > 0 and p > 0:
                inlet = _STANDARD_FLOW[gas.flow_unit] * p / (GAS_CONSTANT * t)
                flow = inlet
        if gas.flow_correction is None:
            out.add(
                "info",
                "flow-correction",
                "no flow correction stated: the meter's reading is used as it is (factor 1)",
                ["gas"],
                [],
                "give gas.flow_correction {factor, source} when the meter is calibrated on "
                "another gas than the one it measures",
            )
        elif flow is not None:
            flow *= gas.flow_correction.factor
        if gas.flow_position == "inlet":
            out.add(
                "warning",
                "flow-position",
                "the gas flow was measured at the inlet: it is taken as the outlet flow, "
                "although the reaction changes the moles of gas",
                ["gas", "flow_position"],
                [],
                "measure the outlet flow (or correct it with an internal standard)",
            )
            report.limitations.append(
                "outlet flow taken equal to the measured inlet flow: the Faradaic efficiencies "
                "carry the change in gas moles across the cell"
            )
    titration = None
    if data.titration is not None:
        method = data.titration
        c = out.value(
            method.titrant_concentration,
            _CONCENTRATION,
            "titrant_concentration",
            ["titration", "titrant_concentration"],
            [],
        )
        v_anolyte = out.value(
            method.anolyte_volume, _VOLUME, "anolyte_volume", ["titration", "anolyte_volume"], []
        )
        v_aliquot = out.value(
            method.aliquot_volume, _VOLUME, "aliquot_volume", ["titration", "aliquot_volume"], []
        )
        if c is not None and v_anolyte is not None and v_aliquot:
            titration = c * v_anolyte / v_aliquot  # mol per L of titrant
    thermoneutral: dict[str, float | None] = {}
    seen: set[str] = set()
    for i, product in enumerate(data.products):
        if product.id in seen:
            out.add(
                "error",
                "schema",
                f"product {product.id} is declared twice",
                ["products", i],
                [product.id],
                "give each product once",
            )
        seen.add(product.id)
        thermoneutral[product.id] = out.value(
            product.thermoneutral_voltage,
            _VOLTAGE,
            f"thermoneutral_voltage of {product.id}",
            ["products", i, "thermoneutral_voltage"],
            [product.id],
        )
    return _Context(
        area,
        flow,
        inlet,
        titration,
        thermoneutral,
        {p.id: p for p in data.products},
        data.voltage_basis != "electrode_vs_reference",
    )


def _voltage(voltage: Voltage, out: _Out, loc, ids) -> tuple[float | None, int | None]:
    factor = _VOLTAGE.get(voltage.unit)
    if factor is None:
        out.add("error", "unit", f"voltage in unit {voltage.unit!r}", loc, ids, "V or mV")
        return None, None
    if voltage.value is not None:
        return voltage.value * factor, None
    window = voltage.window
    samples = [u for t, u in voltage.series or [] if window is None or window[0] <= t <= window[1]]
    if not samples:
        out.add(
            "error",
            "input-missing",
            "the voltage series has no sample in its window",
            loc,
            ids,
            "give the window (s) the mean is taken over, inside the series",
        )
        return None, None
    return sum(samples) / len(samples) * factor, len(samples)


def _replicate(
    data: ElectrochemicalMeasurements,
    point: MeasurementPoint,
    rep: Replicate,
    loc: list[Any],
    current: float | None,
    density: float | None,
    duration: float | None,
    ctx: _Context,
    out: _Out,
) -> ReplicateResult:
    ids = [point.id, rep.id]
    result = ReplicateResult(rep.id, line=_yaml_line(out.doc, loc), source=rep.source)
    if rep.voltage is not None:
        result.voltage_v, result.voltage_samples = _voltage(
            rep.voltage, out, [*loc, "voltage"], ids
        )
    reactant = data.gas.inlet.component if data.gas and data.gas.inlet else None
    for name in [*rep.fractions, *rep.faradaic_efficiency]:
        if name not in ctx.products and name != reactant:
            out.add(
                "error",
                "schema",
                f"point {point.id}, replicate {rep.id}: {name} is not a declared product",
                [*loc, "fractions" if name in rep.fractions else "faradaic_efficiency", name],
                ids,
                "declare it under products: (id, electrons, electrode)",
            )
    # the gas: outlet flow and product flows
    if rep.fractions:
        if data.gas is None or rep.outlet_flow is None:
            out.add(
                "error",
                "input-missing",
                f"point {point.id}, replicate {rep.id}: fractions without "
                + ("a gas: block" if data.gas is None else "outlet_flow")
                + ": no Faradaic efficiency from the gas",
                [*loc, "fractions"],
                ids,
                "give the outlet gas flow (gas.flow_unit) of the replicate",
            )
        elif ctx.flow_mol_s is not None:
            result.outlet_flow_mol_s = rep.outlet_flow * ctx.flow_mol_s
    for name, quantity in rep.fractions.items():
        x = out.value(quantity, _FRACTION, f"fraction of {name}", [*loc, "fractions", name], ids)
        if x is None or result.outlet_flow_mol_s is None:
            continue
        result.flows_mol_s[name] = x * result.outlet_flow_mol_s
        product = ctx.products.get(name)
        if product is not None and current:
            result.faradaic_efficiency[name] = (
                product.electrons * FARADAY * result.flows_mol_s[name] / current
            )
            result.faradaic_basis[name] = "gas"
    for name, quantity in rep.faradaic_efficiency.items():
        fe = out.value(
            quantity,
            _FRACTION,
            f"faradaic_efficiency of {name}",
            [*loc, "faradaic_efficiency"],
            ids,
        )
        if fe is not None and name in ctx.products:
            result.faradaic_efficiency[name] = fe
            result.faradaic_basis[name] = "given"
    if result.faradaic_efficiency:
        result.faradaic_sum = sum(result.faradaic_efficiency.values())
        result.unassigned_current_fraction = 1.0 - result.faradaic_sum
        if density is not None:
            result.partial_current_density_a_m2 = {
                n: fe * density for n, fe in result.faradaic_efficiency.items()
            }
    # the membrane: titration or a given water dissociation efficiency
    if rep.titration is not None:
        volumes = rep.titration
        if ctx.titration_mol is None or duration is None:
            out.add(
                "error",
                "input-missing",
                f"point {point.id}, replicate {rep.id}: a titration without "
                + ("the titration: method block" if ctx.titration_mol is None else "the duration")
                + ": no water dissociation efficiency",
                [*loc, "titration"],
                ids,
                "give titration: {method, titrant_concentration, anolyte_volume, "
                "aliquot_volume} and the point's duration",
            )
        else:
            if not volumes.V1 <= volumes.V2 <= volumes.V0:
                out.add(
                    "warning",
                    "titration",
                    f"point {point.id}, replicate {rep.id}: volumes V0 {volumes.V0:g}, "
                    f"V1 {volumes.V1:g}, V2 {volumes.V2:g} are not in the order V1 <= V2 <= V0: "
                    "a negative co-ion amount",
                    [*loc, "titration"],
                    ids,
                    "check the end points: V1 (first, phenolphthalein) <= V2 (second, methyl "
                    "orange) <= V0 (fresh anolyte)",
                )
            scale = _VOLUME[volumes.unit] * ctx.titration_mol  # mol per unit volume read
            n_k = (volumes.V0 - volumes.V2) * scale
            n_c = (volumes.V2 - volumes.V1) * scale
            result.co_ions_mol = {"cation": n_k, "carbon": n_c}
            if n_k + n_c:
                result.co_ion_carbon_fraction = n_c / (n_k + n_c)
            if current:
                result.water_dissociation_efficiency = 1.0 - FARADAY * (n_k + n_c) / (
                    current * duration
                )
                result.water_dissociation_basis = "titration"
    elif rep.water_dissociation_efficiency is not None:
        wde = out.value(
            rep.water_dissociation_efficiency,
            _FRACTION,
            "water_dissociation_efficiency",
            [*loc, "water_dissociation_efficiency"],
            ids,
        )
        if wde is not None:
            result.water_dissociation_efficiency = wde
            result.water_dissociation_basis = "given"
    # power and heat at the terminals
    if ctx.terminal and result.voltage_v is not None and current is not None:
        result.power_w = result.voltage_v * current
        lacking = [n for n in result.faradaic_efficiency if ctx.thermoneutral.get(n) is None]
        if result.faradaic_efficiency and not lacking:
            enthalpy = sum(
                fe * ctx.thermoneutral[n]  # type: ignore[operator]
                for n, fe in result.faradaic_efficiency.items()
            )
            result.heat_w = current * (result.voltage_v - enthalpy)
    # carbon in and out
    inlet = data.gas.inlet if data.gas is not None else None
    if inlet is not None and ctx.inlet_mol_s is not None and result.outlet_flow_mol_s is not None:
        result.carbon = _carbon_balance(
            inlet, ctx, result, duration, point, rep, [*loc, "fractions"], out
        )
    return result


def _carbon_balance(
    inlet: GasInlet,
    ctx: _Context,
    result: ReplicateResult,
    duration: float | None,
    point: MeasurementPoint,
    rep: Replicate,
    loc: list[Any],
    out: _Out,
) -> dict[str, Any] | None:
    fed_c = _carbon(inlet.formula, inlet.component)
    if not fed_c:
        return None
    fed = inlet.flow * ctx.inlet_mol_s * fed_c  # type: ignore[operator]
    in_products = 0.0
    unknown = []
    for name, flow in result.flows_mol_s.items():
        if name == inlet.component:
            continue
        product = ctx.products.get(name)
        atoms = _carbon(product.formula if product else None, name)
        if atoms is None:
            unknown.append(name)
            continue
        in_products += atoms * flow
    unreacted = result.flows_mol_s.get(inlet.component)
    unreacted_c = unreacted * fed_c if unreacted is not None else None
    crossed = None
    if result.co_ions_mol and duration:
        crossed = result.co_ions_mol["carbon"] / duration
    balance: dict[str, Any] = {
        "fed_mol_s": fed,
        "products_mol_s": in_products,
        "unreacted_mol_s": unreacted_c,
        "anolyte_mol_s": crossed,
        "conversion_to_products": in_products / fed,
        "residual_mol_s": None,
        "relative_residual": None,
        "closed": False,
        "unknown_formula": unknown,
    }
    if unreacted_c is None or unknown:
        return balance
    residual = fed - in_products - unreacted_c - (crossed or 0.0)
    balance.update(residual_mol_s=residual, relative_residual=residual / fed, closed=True)
    if abs(residual / fed) > _CARBON_TOLERANCE:
        out.add(
            "warning",
            "carbon-balance",
            f"point {point.id}, replicate {rep.id}: carbon in and out differ by "
            f"{100 * residual / fed:+.1f} % of the carbon fed",
            loc,
            [point.id, rep.id],
            "check the flows, fractions and the meter's correction; carbon may also leave as "
            "liquid products or crossed over" + ("" if crossed is not None else " (no titration)"),
        )
    return balance


def evaluate(
    data: ElectrochemicalMeasurements, file: str = "measurements.yaml", doc: Any = None
) -> MeasurementReport:
    """Process a measurement file *data* (see the module docstring); *file* and *doc* (its YAML
    node tree) place the findings. Pure: reads and writes nothing."""
    out = _Out(file, doc)
    report = MeasurementReport(
        file,
        id=data.id,
        title=data.title,
        citation=data.source,
        licence=data.licence,
        provenance=data.provenance,
        voltage_basis=data.voltage_basis,
        products=[p.id for p in data.products],
        reactions={p.id: p.reaction for p in data.products if p.reaction},
    )
    ctx = _context(data, out, report)
    if data.voltage_basis == "electrode_vs_reference":
        out.add(
            "info",
            "voltage-basis",
            "the voltages are electrode potentials against a reference electrode: no "
            "polarisation curve, power or heat; a cell cannot take them as its voltage",
            ["voltage_basis"],
            [],
            "give the cell voltage at the terminals (voltage_basis: cell) for a cell model",
        )
    elif data.voltage_basis == "cell_ir_corrected":
        report.limitations.append(
            "the voltages are iR-corrected: the power and heat leave out the ohmic loss"
        )
    seen: set[str] = set()
    densities: dict[float, str] = {}
    for i, point in enumerate(data.points):
        loc = ["points", i]
        if point.id in seen:
            out.add(
                "error",
                "schema",
                f"point {point.id} is declared twice",
                loc,
                [point.id],
                "give each point its own id",
            )
        seen.add(point.id)
        current = out.value(point.current, _CURRENT, "current", [*loc, "current"], [point.id])
        density = out.value(
            point.current_density,
            _CURRENT_DENSITY,
            "current_density",
            [*loc, "current_density"],
            [point.id],
        )
        if ctx.area_m2 is not None:
            if current is not None:
                density = current / ctx.area_m2
            elif density is not None:
                current = density * ctx.area_m2
        duration = out.value(point.duration, _DURATION, "duration", [*loc, "duration"], [point.id])
        result = PointResult(
            point.id, _yaml_line(out.doc, loc), current, density, duration, replicates=[]
        )
        if density is not None:
            key = round(density, 9)
            if key in densities:
                out.add(
                    "error",
                    "schema",
                    f"points {densities[key]} and {point.id} are at one current density "
                    f"({density:g} A/m2)",
                    loc,
                    [densities[key], point.id],
                    "give the runs at one current density as replicates of one point",
                )
            densities.setdefault(key, point.id)
        rep_ids: set[str] = set()
        for k, rep in enumerate(point.replicates):
            if rep.id in rep_ids:
                out.add(
                    "error",
                    "schema",
                    f"point {point.id}: replicate {rep.id} is declared twice",
                    [*loc, "replicates", k],
                    [point.id, rep.id],
                    "give each replicate of a point its own id",
                )
            rep_ids.add(rep.id)
            result.replicates.append(
                _replicate(
                    data,
                    point,
                    rep,
                    [*loc, "replicates", k],
                    current,
                    density,
                    duration,
                    ctx,
                    out,
                )
            )
        _summarise(result, ctx, out, loc)
        report.points.append(result)
    _membrane_findings(data, report, out)
    _heat_findings(data, report, ctx, out)
    _validity(data, report, out)
    if data.gas is None or data.gas.inlet is None:
        report.limitations.append("carbon balance not checked: no gas.inlet given")
    elif any(r.carbon and not r.carbon["closed"] for p in report.points for r in p.replicates):
        report.limitations.append(
            "carbon balance not closed for every replicate: the unreacted reactant's outlet "
            "fraction (or a product's formula) is not measured; the conversion to products is "
            "reported"
        )
    report.findings = out.findings
    return report


def _summarise(result: PointResult, ctx: _Context, out: _Out, loc: list[Any]) -> None:
    reps = result.replicates
    result.voltage_v = Stat.of([r.voltage_v for r in reps])
    names = sorted({n for r in reps for n in r.faradaic_efficiency})
    result.faradaic_efficiency = {
        n: s for n in names if (s := Stat.of([r.faradaic_efficiency.get(n) for r in reps]))
    }
    result.faradaic_sum = Stat.of([r.faradaic_sum for r in reps])
    result.partial_current_density_a_m2 = {
        n: s for n in names if (s := Stat.of([r.partial_current_density_a_m2.get(n) for r in reps]))
    }
    result.water_dissociation_efficiency = Stat.of([r.water_dissociation_efficiency for r in reps])
    result.co_ion_carbon_fraction = Stat.of([r.co_ion_carbon_fraction for r in reps])
    result.power_w = Stat.of([r.power_w for r in reps])
    result.heat_w = Stat.of([r.heat_w for r in reps])
    if len(reps) == 1:
        out.add(
            "info",
            "single-replicate",
            f"point {result.id} has one replicate: no standard deviation",
            loc,
            [result.id],
            "repeat the run to state its spread",
        )
    total = result.faradaic_sum
    if total is None:
        return
    # above 1 by more than three standard deviations; with one replicate, above 1.05
    if total.sd is not None:
        limit, said = 1 + 3 * total.sd, f"1 + 3 sd ({1 + 3 * total.sd:.4g})"
    else:
        limit, said = _FE_SUM_HIGH_SINGLE, f"{_FE_SUM_HIGH_SINGLE:g} (one replicate)"
    if total.mean > limit:
        out.add(
            "error",
            "fe-sum-high",
            f"point {result.id}: the Faradaic efficiencies add up to {total.mean:.4g}, above "
            f"{said}: more charge in the products than the current carried",
            loc,
            [result.id],
            "check the flow (unit, standard conditions, correction), the fractions' unit and "
            "the electrons per product",
        )
    elif total.mean < _FE_SUM_LOW:
        out.add(
            "warning",
            "fe-sum-low",
            f"point {result.id}: the Faradaic efficiencies add up to {total.mean:.4g}: "
            f"{1 - total.mean:.3g} of the current forms no measured product",
            loc,
            [result.id],
            "products not measured (liquids such as formate, crossed-over gas) or a flow "
            "error; the unassigned current is counted as heat",
        )


def _membrane_findings(
    data: ElectrochemicalMeasurements, report: MeasurementReport, out: _Out
) -> None:
    membrane = data.cell.membrane
    if membrane is None or membrane.kind == "none":
        return
    measured = any(
        r.water_dissociation_efficiency is not None for p in report.points for r in p.replicates
    )
    if measured:
        return
    out.add(
        "warning",
        "crossover-assumed",
        f"a {membrane.kind.replace('_', '-')} membrane cell without a measured water "
        "dissociation efficiency: the ion transport across the membrane (co-ion crossover) is "
        "assumed",
        ["cell", "membrane"],
        [],
        "titrate the anolyte (titration: V0, V1, V2) or give water_dissociation_efficiency per "
        "replicate",
    )
    report.limitations.append("membrane ion transport not measured: crossover assumed")


def _heat_findings(
    data: ElectrochemicalMeasurements, report: MeasurementReport, ctx: _Context, out: _Out
) -> None:
    if not ctx.terminal:
        return
    with_fe = sorted(
        {n for p in report.points for r in p.replicates for n in r.faradaic_efficiency}
    )
    lacking = [n for n in with_fe if ctx.thermoneutral.get(n) is None]
    if lacking:
        out.add(
            "info",
            "heat",
            f"no thermoneutral_voltage for {', '.join(lacking)}: the heat at the boundary is not "
            "computed",
            ["products"],
            lacking,
            "give thermoneutral_voltage (dH / (n F) of the product's reaction, V) per product",
        )


def _validity(data: ElectrochemicalMeasurements, report: MeasurementReport, out: _Out) -> None:
    declared = data.validity or Validity()
    densities = [p.current_density_a_m2 for p in report.points if p.current_density_a_m2]
    durations = [p.duration_s for p in report.points if p.duration_s]
    span = (min(densities), max(densities)) if densities else None
    derived = []
    current = declared.current_density
    if current is None and span is not None:
        current = span
        derived.append("current_density")
    temperature = declared.temperature
    if temperature is None and report.temperature_k is not None:
        temperature = (report.temperature_k, report.temperature_k)
        derived.append("temperature")
    duration = declared.duration
    if duration is None and durations:
        duration = max(durations)
        derived.append("duration")
    electrolyte = declared.electrolyte
    if not electrolyte and data.cell.electrolyte is not None:
        electrolyte = data.cell.electrolyte.name
        derived.append("electrolyte")
    report.validity = {
        "current_density_a_m2": list(current) if current else None,
        "measured_current_density_a_m2": list(span) if span else None,
        "temperature_k": list(temperature) if temperature else None,
        "duration_s": duration,
        "electrolyte": electrolyte,
        "source": declared.source,
        "derived": derived,
    }
    if derived:
        out.add(
            "info",
            "validity",
            f"validity derived from the points: {', '.join(derived)}",
            ["validity"] if data.validity is not None else ["points"],
            [],
            "state validity: (current_density A/m2, temperature K, electrolyte, duration s) "
            "from the source of the data",
        )
    if declared.current_density is not None and span is not None:
        lo, hi = declared.current_density
        if lo < span[0] - 1e-9 or hi > span[1] + 1e-9:
            out.add(
                "warning",
                "validity",
                f"the declared current density range {lo:g}-{hi:g} A/m2 extends beyond the "
                f"measured points ({span[0]:g}-{span[1]:g} A/m2): nothing is extrapolated there",
                ["validity", "current_density"],
                [],
                "narrow the range to the measured points or add points",
            )


# -- loading ------------------------------------------------------------------------------------


def load(path: Path, name: str) -> tuple[ElectrochemicalMeasurements | None, Any, list[Finding]]:
    """The measurement file at *path* (*name*: its path in the findings), its YAML nodes and
    the schema findings."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as failure:
        return None, None, [Finding(name, "error", "cheme.electrochem-schema", str(failure))]
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as failure:
        return None, None, [syntax_finding(name, failure, text)]
    doc = _compose(path)
    try:
        return ElectrochemicalMeasurements.model_validate(raw or {}), doc, []
    except ValidationError as failure:
        return (
            None,
            doc,
            [
                Finding(
                    name,
                    "error",
                    "cheme.electrochem-schema",
                    f"{'.'.join(str(p) for p in e['loc']) or '(file)'}: {e['msg']}",
                    line=_yaml_line(doc, e["loc"]),
                    hint="see `cheme schema electrochemical-measurements`",
                )
                for e in failure.errors()
            ],
        )


def measurement_report(root: Path, path: str | Path) -> MeasurementReport:
    """The measurement file *path* (relative to *root*, or absolute inside it) processed, with
    the fingerprint of the file. Read-only; a file that does not load gives a report without
    points and its schema findings."""
    from chemeascode.foundation.provenance import source_revision

    root = Path(root)
    full = Path(path) if Path(path).is_absolute() else root / path
    try:
        name = full.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        name = Path(path).as_posix()
    data, doc, findings = load(full, name)
    if data is None:
        return MeasurementReport(name, findings=findings, source=source_revision(root, [name]))
    report = evaluate(data, name, doc)
    report.source = source_revision(root, [name])
    return report


def measurement_files(root: Path) -> list[str]:
    """The measurement files of the plant at *root*, by path from the root."""
    folder = Path(root) / MEASUREMENTS_DIR
    if not folder.is_dir():
        return []
    return sorted(f"{MEASUREMENTS_DIR}/{p.name}" for p in folder.glob("*.yaml"))


# -- the measured performance -------------------------------------------------------------------


@dataclass(frozen=True)
class PerformancePoint:
    """The measured performance at one current density, or why there is none (``reason``).
    Values are present only when ``in_range`` and not ``extrapolated``."""

    current_density_a_m2: float
    in_range: bool
    extrapolated: bool
    #: the measured points it lies between (one id twice at a measured point)
    bracket: tuple[str, str] | None
    #: the validity range of the current density, A/m2
    bounds: tuple[float, float] | None
    voltage_basis: str | None
    voltage_v: float | None = None
    voltage_sd_v: float | None = None
    faradaic_efficiency: dict[str, float] = field(default_factory=dict)
    faradaic_efficiency_sd: dict[str, float | None] = field(default_factory=dict)
    water_dissociation_efficiency: float | None = None
    water_dissociation_efficiency_sd: float | None = None
    co_ion_carbon_fraction: float | None = None
    reason: str = ""

    @property
    def available(self) -> bool:
        return self.in_range and not self.extrapolated


def _lerp(a: float | None, b: float | None, w: float) -> float | None:
    if a is None or b is None:
        return None
    return a + (b - a) * w


def _stat(s: Stat | None, sd: bool = False) -> float | None:
    if s is None:
        return None
    return s.sd if sd else s.mean


class MeasuredPerformance:
    """The point means of a :class:`MeasurementReport`, interpolated piecewise linearly in the
    current density; :meth:`at` refuses outside the validity range and beyond the measured
    points (no extrapolation). Standard deviations are interpolated like the means (a single
    replicate's is None). The interface for dynamic duties and stack sizing."""

    def __init__(self, report: MeasurementReport) -> None:
        self.report = report
        self.points = sorted(
            (p for p in report.points if p.current_density_a_m2 is not None),
            key=lambda p: p.current_density_a_m2,  # type: ignore[arg-type, return-value]
        )
        bounds = report.validity.get("current_density_a_m2")
        self.bounds: tuple[float, float] | None = tuple(bounds) if bounds else None  # type: ignore[assignment]
        self.validity = dict(report.validity)

    def at(self, current_density_a_m2: float) -> PerformancePoint:
        j = current_density_a_m2
        base = {
            "current_density_a_m2": j,
            "bounds": self.bounds,
            "voltage_basis": self.report.voltage_basis,
        }
        if self.bounds is None or not self.points:
            return PerformancePoint(
                **base, in_range=False, extrapolated=True, bracket=None, reason="no points"
            )
        lo, hi = self.bounds
        in_range = lo - 1e-9 * max(hi, 1.0) <= j <= hi + 1e-9 * max(hi, 1.0)
        first, last = self.points[0], self.points[-1]
        tol = 1e-9 * max(last.current_density_a_m2 or 1.0, 1.0)
        extrapolated = not (
            first.current_density_a_m2 - tol <= j <= last.current_density_a_m2 + tol  # type: ignore[operator]
        )
        if not in_range or extrapolated:
            reason = (
                f"{j:.6g} A/m2 outside the validity range {lo:g}-{hi:g} A/m2"
                if not in_range
                else f"{j:.6g} A/m2 beyond the measured points "
                f"({first.current_density_a_m2:g}-{last.current_density_a_m2:g} A/m2)"
            )
            return PerformancePoint(
                **base, in_range=in_range, extrapolated=extrapolated, bracket=None, reason=reason
            )
        below = first
        above = last
        for p in self.points:
            if p.current_density_a_m2 <= j + tol:  # type: ignore[operator]
                below = p
        for p in reversed(self.points):
            if p.current_density_a_m2 >= j - tol:  # type: ignore[operator]
                above = p
        span = (above.current_density_a_m2 or 0.0) - (below.current_density_a_m2 or 0.0)
        w = 0.0 if span <= 0 else (j - below.current_density_a_m2) / span  # type: ignore[operator]
        names = sorted(set(below.faradaic_efficiency) & set(above.faradaic_efficiency))
        fe = {}
        fe_sd = {}
        for n in names:
            fe[n] = _lerp(below.faradaic_efficiency[n].mean, above.faradaic_efficiency[n].mean, w)
            fe_sd[n] = _lerp(below.faradaic_efficiency[n].sd, above.faradaic_efficiency[n].sd, w)
        terminal = self.report.voltage_basis != "electrode_vs_reference"
        return PerformancePoint(
            **base,
            in_range=True,
            extrapolated=False,
            bracket=(below.id, above.id),
            voltage_v=_lerp(_stat(below.voltage_v), _stat(above.voltage_v), w)
            if terminal
            else None,
            voltage_sd_v=_lerp(_stat(below.voltage_v, True), _stat(above.voltage_v, True), w)
            if terminal
            else None,
            faradaic_efficiency=fe,  # type: ignore[arg-type]
            faradaic_efficiency_sd=fe_sd,
            water_dissociation_efficiency=_lerp(
                _stat(below.water_dissociation_efficiency),
                _stat(above.water_dissociation_efficiency),
                w,
            ),
            water_dissociation_efficiency_sd=_lerp(
                _stat(below.water_dissociation_efficiency, True),
                _stat(above.water_dissociation_efficiency, True),
                w,
            ),
            co_ion_carbon_fraction=_lerp(
                _stat(below.co_ion_carbon_fraction), _stat(above.co_ion_carbon_fraction), w
            ),
        )


# -- text and plots -----------------------------------------------------------------------------


def _pm(s: Stat | None, digits: str = ".4g", unit: str = "") -> str:
    if s is None:
        return "-"
    spread = f" +- {s.sd:{digits}}" if s.sd is not None else ""
    return f"{s.mean:{digits}}{spread}{unit} (n {s.n})"


def report_text(report: MeasurementReport) -> str:
    lines = [f"model {MODEL['id']} v{MODEL['version']} ({SCHEMA}), core {_version()}"]
    if report.id is not None:
        validity = report.validity.get("current_density_a_m2")
        span = f"{validity[0]:g}-{validity[1]:g} A/m2" if validity else "not known"
        lines.append(
            f"{report.file}: {report.id}"
            + (f" ({report.title})" if report.title else "")
            + f", voltage basis {report.voltage_basis}, valid {span}"
        )
    for p in report.points:
        j = f"{p.current_density_a_m2:g} A/m2" if p.current_density_a_m2 is not None else "j -"
        current = f", {p.current_a:.4g} A" if p.current_a is not None else ""
        lines.append(f"point {p.id}: {j}{current}, {len(p.replicates)} replicate(s)")
        if p.voltage_v is not None:
            lines.append(f"  voltage {_pm(p.voltage_v, unit=' V')}")
        for name, s in p.faradaic_efficiency.items():
            partial = p.partial_current_density_a_m2.get(name)
            lines.append(f"  FE {name} {_pm(s)}; partial j {_pm(partial, unit=' A/m2')}")
        if p.faradaic_sum is not None:
            lines.append(f"  FE sum {_pm(p.faradaic_sum)}")
        if p.water_dissociation_efficiency is not None:
            lines.append(
                f"  water dissociation efficiency {_pm(p.water_dissociation_efficiency)}"
                + (
                    f"; carbon share of the co-ion current {_pm(p.co_ion_carbon_fraction)}"
                    if p.co_ion_carbon_fraction is not None
                    else ""
                )
            )
        if p.power_w is not None:
            lines.append(
                f"  power {_pm(p.power_w, unit=' W')}; heat to remove {_pm(p.heat_w, unit=' W')}"
            )
    for text in [*LIMITATIONS, *report.limitations]:
        lines.append(f"limitation: {text}")
    lines += [f.format() for f in report.findings]
    return "\n".join(lines)


_SERIES = (
    ("#2a78d6", "#3987e5"),
    ("#eb6834", "#d95926"),
    ("#1baf7a", "#199e70"),
    ("#8a5cd6", "#9b72e0"),
    ("#52514e", "#c3c2b7"),
)
_W, _H = 640, 320
_LEFT, _RIGHT, _TOP, _BOTTOM = 64, 140, 36, 48


def _ticks(lo: float, hi: float) -> list[float]:
    """About five round ticks covering lo..hi."""
    if hi <= lo:
        hi = lo + (abs(lo) or 1.0)
    raw = (hi - lo) / 5
    power = 10 ** math.floor(math.log10(raw))
    step = next(m * power for m in (1, 2, 2.5, 5, 10) if m * power >= raw)
    start = math.floor(lo / step + 1e-9) * step
    out = [round(start, 12)]
    while out[-1] < hi - step * 1e-6 or len(out) < 2:
        out.append(round(start + len(out) * step, 12))
    return out


def _chart(
    title: str,
    xlabel: str,
    ylabel: str,
    series: list[tuple[str, list[tuple[float, float, float | None]]]],
    note: str,
    zero: bool = True,
) -> str:
    """One SVG chart: a line through each series' means, a dot per point and its +- 1 sd bar.
    Light and dark (prefers-color-scheme), tooltips on the dots."""
    xs = [x for _, pts in series for x, _, _ in pts]
    ys = [y + s * (sd or 0.0) for _, pts in series for _, y, sd in pts for s in (-1, 1)]
    xt = _ticks(0.0, max(xs))  # the current density from zero
    yt = _ticks(min(0.0, min(ys)) if zero else min(ys), max(ys))
    w = _W - _LEFT - _RIGHT
    h = _H - _TOP - _BOTTOM

    def px(x: float) -> float:
        return _LEFT + w * (x - xt[0]) / (xt[-1] - xt[0])

    def py(y: float) -> float:
        return _TOP + h * (1 - (y - yt[0]) / (yt[-1] - yt[0]))

    colours = "\n".join(
        f"  .s{k} {{ stroke: {pair[0]}; fill: {pair[0]}; }}" for k, pair in enumerate(_SERIES)
    )
    dark = "\n".join(
        f"    .s{k} {{ stroke: {pair[1]}; fill: {pair[1]}; }}" for k, pair in enumerate(_SERIES)
    )
    body = [
        "<style>",
        "  svg { background: #fcfcfb; font-family: system-ui, sans-serif; }",
        "  .title { font-size: 13px; font-weight: 600; fill: #0b0b0b; }",
        "  .label, .legend { font-size: 11px; fill: #52514e; }",
        "  .tick { font-size: 10px; fill: #52514e; }",
        "  .grid { stroke: #e5e4e0; stroke-width: 1; }",
        "  .axis { stroke: #a3a29b; stroke-width: 1; }",
        "  .line { fill: none !important; stroke-width: 2; stroke-linejoin: round; }",
        "  .bar { stroke-width: 1.5; }",
        colours,
        "  @media (prefers-color-scheme: dark) {",
        "    svg { background: #1a1a19; }",
        "    .title { fill: #f0efec; }",
        "    .label, .legend, .tick { fill: #c3c2b7; }",
        "    .grid { stroke: #33332f; }",
        "    .axis { stroke: #6e6d66; }",
        dark,
        "  }",
        "</style>",
        f'<text class="title" x="{_LEFT}" y="{_TOP - 16}">{title}</text>',
    ]
    for v in yt:
        body.append(
            f'<line class="grid" x1="{_LEFT}" x2="{_LEFT + w}" y1="{py(v):.1f}" y2="{py(v):.1f}"/>'
        )
        body.append(
            f'<text class="tick" x="{_LEFT - 6}" y="{py(v) + 4:.1f}" text-anchor="end">{v:g}</text>'
        )
    for v in xt:
        body.append(
            f'<text class="tick" x="{px(v):.1f}" y="{_TOP + h + 16}" '
            f'text-anchor="middle">{v:g}</text>'
        )
    body.append(
        f'<line class="axis" x1="{_LEFT}" x2="{_LEFT + w}" y1="{_TOP + h}" y2="{_TOP + h}"/>'
    )
    body.append(f'<line class="axis" x1="{_LEFT}" x2="{_LEFT}" y1="{_TOP}" y2="{_TOP + h}"/>')
    body.append(
        f'<text class="label" x="{_LEFT + w / 2:.1f}" y="{_H - 10}" '
        f'text-anchor="middle">{xlabel}</text>'
    )
    body.append(
        f'<text class="label" transform="translate({_LEFT - 46},{_TOP + h / 2:.1f}) '
        f'rotate(-90)" text-anchor="middle">{ylabel}</text>'
    )
    for k, (name, pts) in enumerate(series):
        slot = k % len(_SERIES)
        pts = sorted(pts)
        if len(pts) > 1:
            d = " ".join(
                f"{'M' if i == 0 else 'L'}{px(x):.1f},{py(y):.1f}"
                for i, (x, y, _) in enumerate(pts)
            )
            body.append(f'<path class="line s{slot}" d="{d}"/>')
        for x, y, sd in pts:
            if sd:
                top, bottom = py(y + sd), py(y - sd)
                body.append(
                    f'<path class="bar s{slot}" d="M{px(x):.1f},{top:.1f} V{bottom:.1f} '
                    f'M{px(x) - 4:.1f},{top:.1f} h8 M{px(x) - 4:.1f},{bottom:.1f} h8"/>'
                )
            spread = f" +- {sd:.4g}" if sd is not None else " (one replicate)"
            body.append(
                f'<circle class="s{slot}" cx="{px(x):.1f}" cy="{py(y):.1f}" r="3.5">'
                f"<title>{name}: {y:.4g}{spread} at {x:g}</title></circle>"
            )
        ly = _TOP + 8 + 18 * k
        lx = _LEFT + w + 20
        body.append(f'<line class="line s{slot}" x1="{lx}" x2="{lx + 18}" y1="{ly}" y2="{ly}"/>')
        body.append(f'<text class="legend" x="{lx + 24}" y="{ly + 4}">{name}</text>')
    body.append(
        f'<text class="tick" x="{_LEFT + w + 20}" y="{_TOP + 8 + 18 * len(series) + 6}">'
        "bars: +- 1 sd</text>"
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_W} {_H}" width="{_W}" '
        f'height="{_H}" role="img"><title>{title}: {note}</title>\n'
        + "\n".join(body)
        + "\n</svg>\n"
    )


def measurement_plots(report: MeasurementReport) -> dict[str, str]:
    """SVG figures of a report by file name, each only for the inputs that support it: the
    polarisation curve (a terminal voltage; an electrode-potential plot labelled as such for
    ``electrode_vs_reference``), the Faradaic efficiency per product and their sum, the partial
    current densities, and the water dissociation efficiency."""
    points = [p for p in report.points if p.current_density_a_m2 is not None]
    note = f"{report.id}, {report.file}"
    figures: dict[str, str] = {}

    def series(get) -> list[tuple[float, float, float | None]]:
        out = []
        for p in points:
            s = get(p)
            if s is not None:
                out.append((p.current_density_a_m2, s.mean, s.sd))
        return out

    voltage = series(lambda p: p.voltage_v)
    if voltage:
        if report.voltage_basis == "electrode_vs_reference":
            figures["electrode-potential.svg"] = _chart(
                "Electrode potential against the reference (not a cell voltage)",
                "current density / (A/m2)",
                "potential vs reference / V",
                [("potential", voltage)],
                note,
                zero=False,
            )
        else:
            label = "cell voltage" + (
                " (iR-corrected)" if report.voltage_basis == "cell_ir_corrected" else ""
            )
            figures["polarisation.svg"] = _chart(
                f"Polarisation curve: {label}",
                "current density / (A/m2)",
                f"{label} / V",
                [(label, voltage)],
                note,
                zero=False,
            )
    names = sorted({n for p in points for n in p.faradaic_efficiency})
    if names:
        fe = [(n, series(lambda p, n=n: p.faradaic_efficiency.get(n))) for n in names]
        fe.append(("sum", series(lambda p: p.faradaic_sum)))
        figures["faradaic-efficiency.svg"] = _chart(
            "Faradaic efficiency",
            "current density / (A/m2)",
            "Faradaic efficiency / -",
            fe,
            note,
        )
        partial = [(n, series(lambda p, n=n: p.partial_current_density_a_m2.get(n))) for n in names]
        if any(pts for _, pts in partial):
            figures["partial-current-density.svg"] = _chart(
                "Partial current density",
                "current density / (A/m2)",
                "partial current density / (A/m2)",
                [(n, pts) for n, pts in partial if pts],
                note,
            )
    wde = series(lambda p: p.water_dissociation_efficiency)
    if wde:
        figures["water-dissociation-efficiency.svg"] = _chart(
            "Water dissociation efficiency of the membrane (not a Faradaic efficiency)",
            "current density / (A/m2)",
            "water dissociation efficiency / -",
            [("WDE", wde)],
            note,
        )
    return figures
