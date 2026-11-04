"""Schema ``cheme/electrolysis-duties/v1`` (``process/duties.yaml``) and the dynamic duty of an
electrochemical cell feeding an anolyte reservoir: current or power schedules, the cell's
voltage and efficiencies at each instant, the reservoir's inventory and pH, the product formed,
dosing and bleed, and the time to a stated pH threshold.

A duty names a cell of ``process/cells.yaml``. A measured cell (``performance: measured``)
gives the voltage ``U(j)``, the Faradaic efficiency of its product ``FE(j)``, the water
dissociation efficiency ``WDE(j)`` and the carbon share of the co-ion current ``C_x(j)``
through :meth:`MeasuredPerformance.at <chemeascode.domains.experiments.electrochemistry.
MeasuredPerformance.at>` at the current density ``j = I / A``, never extrapolated; a
specified cell gives them as constants (its ``voltage``, ``faradaic_efficiency`` and
``membrane:`` block), held within its ``operating_range``. The schedule gives the current per
cell (``constant_current``, ``piecewise`` [(t, I)] held or linear, ``on_off`` with a period and
duty fraction) or the power of all its cells (``power`` [(t, P)]: ``P = N U(j) j A`` is solved
for ``j`` inside the measured range; outside it there is no current, never an extrapolated
one). ``N`` is the cells in series times the stacks, all feeding the one reservoir.

Per cell and instant, with the current ``I`` (Faraday constant F): the membrane produces
``WDE I / F`` of OH- into the anolyte, the anode consumes ``I / F`` (oxygen evolution, one
OH- per electron), and the co-ion current ``(1 - WDE) I / F`` is carried by the cation leaving
the anolyte (share ``1 - C_x``) and by carbon entering it as HCO3- (share ``C_x``) (or by the
co-ions and shares of the cell's ``membrane.co_ion_crossover``). These fluxes, times N, the
dosing (cation and OH- of a hydroxide solution, its volume), the make-up water and the bleed go
to the reservoir's anolyte model (:mod:`chemeascode.domains.chemistry.anolyte`, chosen by id:
``well-mixed-carbonate`` v1), which carries the inventory and gives the pH. The product forms
at ``N FE I nu / (n F)`` (``n`` electrons per extent of the cell's reaction, ``nu`` the
product's stoichiometric coefficient); the power is ``N U I``.

:func:`simulate_duty` integrates one duty (no plant needed) with the adaptive Dormand-Prince
integrator of :mod:`chemeascode.foundation.ode` and events: the stated pH threshold (terminal;
"time to a specified pH threshold", a stated design criterion, not a corrosion onset), the
minimum inventory, dosing on and off, the product target of a comparison. The schedule's
breakpoints and the times where the current density leaves the measured range split the
integration. The transient stops at the first exit from the measured range (nothing is
extrapolated); the scheduled operating time outside the range is summed (up to the horizon
when the transient stopped at an exit, else up to its end) and such a duty is never feasible.
:func:`duty_report` evaluates every duty of a plant,
:func:`compare_duties` compares duties at equal delivered product, :func:`operating_map` gives
the time to the threshold over water dissociation efficiency and reservoir volume, and
:func:`duty_plots` draws the aligned time plots and the map as SVG.

A duty is **feasible** when it runs to its horizon (or delivers the target of a comparison)
without reaching the threshold or the minimum inventory, with the whole of it inside the
measured range and inside the anolyte model's validity, and the integration converged.

Rules (``cheme.duty-*``), each finding naming the file, line, rule and a hint:

- ``schema`` (error): the file does not follow the schema, a duplicate id, a unit the quantity
  does not take, a value out of its range (a non-positive volume, a dosing trigger not above
  the threshold, an on/off schedule of more than :data:`MAX_PERIODS` periods);
- ``cell-missing`` (error, refused): the cell is not in ``process/cells.yaml``, or it lacks
  what the duty needs (voltage, Faradaic efficiency, a bipolar membrane with a water
  dissociation efficiency and co-ion split, from the membrane block or, for a measured cell,
  its measurement; the active area, the product and its reaction), its membrane block is
  invalid (co-ion shares not each in 0..1 or not adding up to 1, a WDE outside 0..1), or its
  measurement file has errors;
- ``model-unknown`` (error, refused): no anolyte model of that id (there is no default);
  ``model-species`` (error, refused): a co-ion or the anode reaction the model does not carry,
  or a model whose state names no ``cation`` (mol) and ``volume`` (L);
- ``out-of-range`` (warning): operation outside the measured range (current density,
  temperature), with the time of the first exit and the time outside; the state outside the
  anolyte model's validity (pH, ionic strength, temperature), with the time outside;
- ``threshold-reached`` (info): the time to the stated pH threshold;
- ``inventory-low`` (warning): the reservoir reached its minimum inventory, emptied, or
  exhausted a conserved inventory of the model (its cation or carbon: more left than it held);
- ``dosing-saturated`` (warning): the threshold was reached while dosing, or dosing ran to
  the end without reaching its stop pH;
- ``dosing-chatter`` (warning): threshold dosing switched on and off more than
  :data:`MAX_DOSING_SWITCHES` times (a band ``stop_ph - trigger_ph`` too narrow for the dosing
  rate); the transient stops there;
- ``horizon-reached`` (info): the threshold was not reached within the horizon;
- ``not-converged`` (error): the integration failed (step size, step count);
- ``degassing`` (info): no CO2 degassing (no ``k_L a`` stated): it is off;
- ``compare`` (error): duties compared at equal product that form different products or
  cannot give one; ``target-not-reached`` (warning): a compared duty ended before the target.
"""

from __future__ import annotations

import bisect
import json
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field, ValidationError, model_validator

from chemeascode.domains.chemistry.anolyte import (
    ReservoirFluxes,
    Speciation,
    UnknownAnolyteModel,
    anolyte_model,
)
from chemeascode.domains.experiments.electrochemistry import FARADAY
from chemeascode.foundation.findings import Finding
from chemeascode.foundation.ode import Event, Solution, solve
from chemeascode.foundation.schema_base import Strict, unsupported_schema
from chemeascode.foundation.units import to_kelvin
from chemeascode.foundation.yamlsource import _compose, _yaml_line

SCHEMA = "cheme/electrolysis-duties/v1"
DUTIES_FILE = "process/duties.yaml"
#: The model this module evaluates, as recorded with every result.
MODEL = {"id": "electrolysis-duty", "version": 1, "schema": SCHEMA}
#: Relative tolerance of the integration when a duty states none.
DEFAULT_RTOL = 1e-8
#: Relative tolerance on the delivered product of a comparison at equal product: a duty
#: reaches the target when it delivers it to within this fraction of the target.
DEFAULT_PRODUCT_TOLERANCE = 1e-3
#: Uniform samples of the time series (besides the events and the schedule's breakpoints).
SAMPLES = 240
#: K: a measurement's temperature range counts as the duty's within this (thermostatted cell)
_TEMPERATURE_SLACK = 0.5
#: The most on/off periods a duty's horizon may hold (each is two integration pieces); more is
#: a schema error, never a silent truncation.
MAX_PERIODS = 100_000
#: The most dosing switches (on or off) a duty integrates; past it the transient stops with a
#: ``dosing-chatter`` warning.
MAX_DOSING_SWITCHES = 20_000
#: Co-ion shares and a water dissociation efficiency are checked to this.
_SHARE_TOLERANCE = 1e-6

ASSUMPTIONS = (
    "the cell's voltage, Faradaic efficiency, water dissociation efficiency and co-ion split "
    "at each instant are those measured (or specified) at its current density at that "
    "instant: quasi-steady, no dynamics of the cell itself, no ageing",
    "per cell: OH- into the anolyte WDE I / F from the bipolar membrane, I / F consumed at the "
    "anode (oxygen evolution, one OH- per electron), the co-ion current (1 - WDE) I / F "
    "carried by the cation leaving the anolyte and carbon entering as HCO3- in the measured "
    "(or stated) shares; F = 96485.33212 C/mol",
    "N = cells in series x stacks, all fed from and returning to the one reservoir, each at the "
    "same current",
    "product formed N FE I nu / (n F); power N U I at the cell terminals; the anode's "
    "Faradaic efficiency for oxygen is 1",
    "dosing adds the cation and OH- of a hydroxide solution and its volume; the bleed removes "
    "reservoir solution at its composition; make-up water adds volume only",
    "integrated by Dormand-Prince 5(4) with step control (chemeascode.foundation.ode); events "
    "located on the dense output",
)
LIMITATIONS = (
    "nothing is extrapolated: outside the measured current density or temperature range the "
    "transient stops; the scheduled time outside is reported, not simulated",
    "the electrolyte the performance was measured in is not tracked: the reservoir's changing "
    "composition does not change the cell's voltage or efficiencies",
    "the threshold is a stated design criterion on the anolyte model's (concentration-basis) "
    "pH, not a corrosion or failure onset",
)

_TIME = {"s": 1.0, "min": 60.0, "h": 3600.0, "d": 86400.0}
_CURRENT = {"A": 1.0, "mA": 1e-3, "kA": 1e3}
_CURRENT_DENSITY = {"A/m2": 1.0, "kA/m2": 1e3, "mA/cm2": 10.0, "A/cm2": 1e4}
_POWER = {"W": 1.0, "kW": 1e3, "MW": 1e6}
_VOLUME = {"L": 1.0, "mL": 1e-3, "m3": 1e3}
_CONCENTRATION = {"mol/L": 1.0, "M": 1.0, "mmol/L": 1e-3, "mol/m3": 1e-3}
_FLOW = {"L/s": 1.0, "L/min": 1 / 60, "L/h": 1 / 3600, "mL/min": 1e-3 / 60, "mL/h": 1e-3 / 3600}
_FLOW["m3/h"] = 1 / 3.6
_DENSITY = {"kg/L": 1.0, "g/mL": 1.0, "kg/m3": 1e-3}
_KLA = {"1/s": 1.0, "1/min": 1 / 60, "1/h": 1 / 3600}
_PRESSURE = {"atm": 1.0, "bar": 1 / 1.01325, "kPa": 1 / 101.325, "Pa": 1 / 101325}
_AMOUNT = {"mol": 1.0, "mmol": 1e-3, "kmol": 1e3}
_AREA = {"m2": 1.0, "cm2": 1e-4}
_VOLTAGE = {"V": 1.0, "mV": 1e-3}
_FRACTION = {None: 1.0, "-": 1.0, "1": 1.0, "%": 0.01}
_CARBON_IONS = {"HCO3-": 1, "CO3-2": 2, "CO3--": 2}


# -- schema -------------------------------------------------------------------------------------


class Value(Strict):
    """A number with its unit and, where it is not the file's, its source."""

    value: float
    unit: str | None = None
    source: str = ""


def _points_ordered(points: list[tuple[float, float]]) -> None:
    times = [t for t, _ in points]
    if times[0] != 0:
        raise ValueError("the first point is at t = 0")
    if any(b <= a for a, b in zip(times, times[1:], strict=False)):
        raise ValueError("the times of the points increase strictly")
    if any(v < 0 for _, v in points):
        raise ValueError("the values of the points are not negative")


class ConstantCurrent(Strict):
    kind: Literal["constant_current"]
    current: Value | None = Field(default=None, description="Per cell: A, mA, kA.")
    current_density: Value | None = Field(default=None, description="A/m2, mA/cm2, kA/m2.")

    @model_validator(mode="after")
    def _one(self) -> ConstantCurrent:
        if (self.current is None) == (self.current_density is None):
            raise ValueError("give current or current_density, not both")
        return self


class Piecewise(Strict):
    """Current per cell (or current density) at the given times, held to the next point
    (``step``) or linear between them; the last value holds to the horizon."""

    kind: Literal["piecewise"]
    points: list[tuple[float, float]] = Field(min_length=1, description="[[t, I], ...]")
    time_unit: Literal["s", "min", "h", "d"] = "h"
    unit: str = Field(default="A", description="A, mA, kA, or A/m2, mA/cm2, kA/m2.")
    interpolation: Literal["step", "linear"] = "step"

    @model_validator(mode="after")
    def _ordered(self) -> Piecewise:
        _points_ordered(self.points)
        return self


class PowerSchedule(Strict):
    """The DC power of all the duty's cells at the given times (``P = N U(j) j A``), held or
    linear between them."""

    kind: Literal["power"]
    points: list[tuple[float, float]] = Field(min_length=1, description="[[t, P], ...]")
    time_unit: Literal["s", "min", "h", "d"] = "h"
    unit: str = Field(default="W", description="W, kW, MW.")
    interpolation: Literal["step", "linear"] = "step"

    @model_validator(mode="after")
    def _ordered(self) -> PowerSchedule:
        _points_ordered(self.points)
        return self


class OnOff(Strict):
    """On for ``duty_fraction`` of every ``period`` at the current given, off (no current)
    for the rest."""

    kind: Literal["on_off"]
    period: Value = Field(description="s, min, h, d.")
    duty_fraction: float = Field(gt=0, le=1)
    current: Value | None = Field(default=None, description="Per cell when on: A, mA, kA.")
    current_density: Value | None = Field(default=None, description="When on: A/m2, mA/cm2.")
    start: Literal["on", "off"] = "on"

    @model_validator(mode="after")
    def _one(self) -> OnOff:
        if (self.current is None) == (self.current_density is None):
            raise ValueError("give current or current_density, not both")
        return self


Schedule = Annotated[
    ConstantCurrent | Piecewise | PowerSchedule | OnOff, Field(discriminator="kind")
]


class Composition(Strict):
    """The initial anolyte, mol/L of each salt (M, mmol/L, mol/m3)."""

    hydroxide: Value | None = Field(default=None, description="The cation hydroxide (KOH).")
    carbonate: Value | None = Field(default=None, description="The cation carbonate (K2CO3).")
    bicarbonate: Value | None = Field(default=None, description="The bicarbonate (KHCO3).")
    co2: Value | None = Field(default=None, description="Dissolved CO2.")


class Degassing(Strict):
    """CO2 degassing above saturation: ``k_L a V ([CO2] - H p_CO2)``."""

    kla: Value = Field(description="Volumetric mass transfer coefficient: 1/s, 1/min, 1/h.")
    co2_partial_pressure: Value = Field(description="Over the reservoir: atm, bar, kPa, Pa.")
    source: str = ""


class Reservoir(Strict):
    volume: Value = Field(description="L, mL, m3.")
    composition: Composition
    cation: str = Field(default="K+", description="The cation of the hydroxide.")
    model: str = Field(description="The anolyte model id, e.g. well-mixed-carbonate.")
    temperature: Value | None = Field(default=None, description="Default: the cell's.")
    degassing: Degassing | None = None


class NoDosing(Strict):
    kind: Literal["none"]


class ThresholdDosing(Strict):
    """Dose a hydroxide solution at ``rate`` from when the pH falls to ``trigger_ph`` until it
    rises to ``stop_ph``."""

    kind: Literal["on_threshold"]
    trigger_ph: float
    stop_ph: float
    concentration: Value = Field(description="Of the hydroxide in the solution: mol/L.")
    rate: Value = Field(description="Of the solution: L/h, L/min, mL/min, L/s.")
    density: Value | None = Field(default=None, description="Of the solution: kg/L, kg/m3.")

    @model_validator(mode="after")
    def _ordered(self) -> ThresholdDosing:
        if not self.trigger_ph < self.stop_ph:
            raise ValueError("trigger_ph is below stop_ph")
        return self


class ContinuousDosing(Strict):
    kind: Literal["continuous"]
    concentration: Value = Field(description="Of the hydroxide in the solution: mol/L.")
    rate: Value = Field(description="Of the solution: L/h, L/min, mL/min, L/s.")
    density: Value | None = Field(default=None, description="Of the solution: kg/L, kg/m3.")


Dosing = Annotated[NoDosing | ThresholdDosing | ContinuousDosing, Field(discriminator="kind")]


class Flow(Strict):
    rate: Value = Field(description="L/h, L/min, mL/min, L/s.")


class Threshold(Strict):
    """The stated pH threshold: a design criterion (time to a specified pH threshold)."""

    ph: float
    source: str = Field(default="", description="Why this threshold (the design criterion).")


class MinimumInventory(Strict):
    volume: Value | None = Field(default=None, description="L, mL, m3.")
    cation: Value | None = Field(default=None, description="mol, mmol, kmol.")


class OperatingMap(Strict):
    """Axes of the operating map (time to the threshold over WDE and reservoir volume)."""

    wde: tuple[float, float] | None = Field(default=None, description="Default 0.5-0.995.")
    volume: tuple[float, float] | None = Field(
        default=None, description="In volume_unit; default 0.1 to 10 times the reservoir."
    )
    volume_unit: Literal["L", "mL", "m3"] = "L"
    resolution: tuple[int, int] = (16, 10)

    @model_validator(mode="after")
    def _ordered(self) -> OperatingMap:
        if self.wde is not None and not 0 <= self.wde[0] < self.wde[1] <= 1:
            raise ValueError("wde is (min, max) with 0 <= min < max <= 1")
        if self.volume is not None and not 0 < self.volume[0] < self.volume[1]:
            raise ValueError("volume is (min, max) with 0 < min < max")
        if not (2 <= self.resolution[0] <= 200 and 2 <= self.resolution[1] <= 200):
            raise ValueError("resolution is (columns, rows), 2 to 200 each")
        return self


class Duty(Strict):
    id: str
    title: str = ""
    cell: str = Field(description="A cell id of process/cells.yaml.")
    cells_in_series: int | None = Field(default=None, ge=1, description="Default: the cell's.")
    stacks: int = Field(default=1, ge=1, description="Stacks in parallel feeding the reservoir.")
    product: str | None = Field(
        default=None, description="Default: the measured product; a specified cell names it."
    )
    schedule: Schedule
    reservoir: Reservoir
    dosing: Dosing = Field(default_factory=lambda: NoDosing(kind="none"))
    bleed: Flow | None = None
    makeup_water: Flow | None = None
    threshold: Threshold
    horizon: Value = Field(description="The longest time integrated: s, min, h, d.")
    minimum_inventory: MinimumInventory | None = None
    tolerance: float | None = Field(
        default=None, gt=0, le=1e-3, description=f"Relative, default {DEFAULT_RTOL:g}."
    )
    operating_map: OperatingMap | None = None
    sources: list[str] = Field(default_factory=list)


class Duties(Strict):
    """The dynamic duties of the process's electrochemical cells."""

    schema_: str = Field(alias="schema", description=f"Always {SCHEMA}.")
    kind: Literal["electrolysis_duties"]
    duties: list[Duty] = Field(default_factory=list)

    @model_validator(mode="after")
    def _version(self) -> Duties:
        if self.schema_ != SCHEMA:
            raise ValueError(unsupported_schema(self.schema_, SCHEMA))
        return self


# -- the cell's performance ---------------------------------------------------------------------


@dataclass(frozen=True)
class OperatingPoint:
    """The cell's performance at one current density, or why there is none (``reason``)."""

    current_density_a_m2: float | None
    available: bool
    voltage_v: float | None = None
    faradaic_efficiency: float | None = None
    water_dissociation_efficiency: float | None = None
    #: ion -> its share of the current not carried by water dissociation (cations leave the
    #: anolyte, anions enter it)
    co_ions: dict[str, float] = field(default_factory=dict)
    reason: str = ""


class SpecifiedPerformance:
    """Constants (a specified cell), held within the current density range when one is given
    (outside it: no value)."""

    basis = "specified"

    def __init__(
        self,
        voltage_v: float,
        faradaic_efficiency: float,
        water_dissociation_efficiency: float,
        co_ions: dict[str, float],
        current_density_range: tuple[float, float] | None = None,
        temperature_range: tuple[float, float] | None = None,
        source: str = "",
    ) -> None:
        self.voltage_v = voltage_v
        self.faradaic_efficiency = faradaic_efficiency
        self.water_dissociation_efficiency = water_dissociation_efficiency
        self.co_ions = dict(co_ions)
        self.bounds = current_density_range
        self.temperature_range = temperature_range
        self.source = source
        self.knots: list[float] = list(current_density_range or ())
        self.measured_wde: list[tuple[float, float, float | None, str]] = []
        self.file: str | None = None

    def at(self, current_density_a_m2: float | None) -> OperatingPoint:
        j = current_density_a_m2
        if self.bounds is not None and j is not None:
            lo, hi = self.bounds
            tol = 1e-9 * max(hi, 1.0)
            if not lo - tol <= j <= hi + tol:
                return OperatingPoint(
                    j,
                    False,
                    reason=f"{j:.6g} A/m2 outside the operating range {lo:g}-{hi:g} A/m2",
                )
        return OperatingPoint(
            j,
            True,
            self.voltage_v,
            self.faradaic_efficiency,
            self.water_dissociation_efficiency,
            dict(self.co_ions),
        )


class MeasuredCellPerformance:
    """A measured series (:class:`MeasuredPerformance`) for one product: its Faradaic
    efficiency (scaled when the measured efficiencies at its electrode add up to more than 1,
    as the cell does), the WDE and the carbon share of the co-ion current (as HCO3-, with the
    *cation* leaving); *wde_fallback* and *co_ions_fallback* (the cell's membrane block) where
    the measurement gives none."""

    basis = "measured"

    def __init__(
        self,
        report: Any,
        product: str,
        cation: str = "K+",
        wde_fallback: float | None = None,
        co_ions_fallback: dict[str, float] | None = None,
    ) -> None:
        from chemeascode.domains.experiments.electrochemistry import MeasuredPerformance

        self.measured = MeasuredPerformance(report)
        self.report = report
        self.file = report.file
        self.product = product
        self.cation = cation
        self.wde_fallback = wde_fallback
        self.co_ions_fallback = dict(co_ions_fallback or {})
        electrode = report.electrodes.get(product)
        self._electrode = [p for p in report.products if report.electrodes.get(p) == electrode]
        knots = [p.current_density_a_m2 for p in self.measured.points]
        span = (min(knots), max(knots)) if knots else None
        bounds = self.measured.bounds
        if bounds is not None and span is not None:
            lo, hi = max(bounds[0], span[0]), min(bounds[1], span[1])
            self.bounds: tuple[float, float] | None = (lo, hi) if lo <= hi else None
        else:
            self.bounds = None
        lo, hi = self.bounds or (0.0, 0.0)
        self.knots = sorted({lo, hi, *(k for k in knots if lo < k < hi)})
        temperature = report.validity.get("temperature_k")
        self.temperature_range = tuple(temperature) if temperature else None
        self.measured_wde = [
            (
                p.current_density_a_m2,
                p.water_dissociation_efficiency.mean,
                p.water_dissociation_efficiency.sd,
                p.id,
            )
            for p in self.measured.points
            if p.water_dissociation_efficiency is not None
        ]
        self.electrolyte = report.validity.get("electrolyte") or ""

    def at(self, current_density_a_m2: float | None) -> OperatingPoint:
        j = current_density_a_m2
        if j is None:
            return OperatingPoint(None, False, reason="no current density (no active area)")
        p = self.measured.at(j)
        if not p.available:
            return OperatingPoint(j, False, reason=p.reason)
        fe = p.faradaic_efficiency.get(self.product)
        if fe is not None:
            total = sum(p.faradaic_efficiency.get(n, 0.0) for n in self._electrode)
            if total > 1:
                fe /= total
        wde = p.water_dissociation_efficiency
        if wde is None:
            wde = self.wde_fallback
        cx = p.co_ion_carbon_fraction
        co_ions = {self.cation: 1 - cx, "HCO3-": cx} if cx is not None else self.co_ions_fallback
        missing = [
            name
            for name, value in (
                ("voltage", p.voltage_v),
                (f"Faradaic efficiency of {self.product}", fe),
                ("water dissociation efficiency", wde),
                ("co-ion split", co_ions or None),
            )
            if value is None
        ]
        if missing:
            return OperatingPoint(
                j, False, reason=f"{self.file} gives no {', '.join(missing)} at {j:.6g} A/m2"
            )
        return OperatingPoint(j, True, p.voltage_v, fe, wde, dict(co_ions))


class _FixedWde:
    """A performance with its water dissociation efficiency replaced (the operating map)."""

    def __init__(self, inner: Any, wde: float) -> None:
        self.inner = inner
        self.wde = wde
        self.basis = inner.basis
        self.bounds = inner.bounds
        self.knots = inner.knots
        self.temperature_range = inner.temperature_range
        self.measured_wde = inner.measured_wde
        self.file = inner.file

    def at(self, current_density_a_m2: float | None) -> OperatingPoint:
        p = self.inner.at(current_density_a_m2)
        if not p.available:
            return p
        return OperatingPoint(
            p.current_density_a_m2,
            True,
            p.voltage_v,
            p.faradaic_efficiency,
            self.wde,
            dict(p.co_ions),
        )


@dataclass
class DutyCell:
    """What a duty takes from its cell: the performance, the reaction's electrons and the
    product, the area, the cells and the temperature."""

    id: str
    performance: Any  # SpecifiedPerformance | MeasuredCellPerformance
    electrons: float
    product: str
    product_per_extent: float = 1.0
    product_molar_mass_kg_mol: float | None = None
    area_m2: float | None = None
    cells_in_series: int = 1
    stacks: int = 1
    temperature_k: float | None = None
    limitations: list[str] = field(default_factory=list)

    @property
    def cells(self) -> int:
        return self.cells_in_series * self.stacks


# -- results ------------------------------------------------------------------------------------


@dataclass
class DutyResult:
    """One duty's transient, events and totals; ``refused`` when an input is missing (the
    numbers are then absent)."""

    id: str
    cell: str
    line: int | None = None
    title: str = ""
    refused: bool = False
    reasons: list[str] = field(default_factory=list)
    performance: str | None = None
    measurement: str | None = None
    #: the range the duty was checked against: current density (A/m2) and temperature (K) of
    #: the measurement (or the specified cell's operating range), the power of all cells over
    #: it for a power schedule, and the measured WDE; None where unbounded
    measured_range: dict[str, Any] | None = None
    anolyte_model: dict[str, Any] | None = None
    cells_in_series: int | None = None
    stacks: int | None = None
    product: str | None = None
    schedule: str | None = None
    threshold_ph: float | None = None
    threshold_source: str = ""
    horizon_h: float | None = None
    rtol: float | None = None
    #: why the transient ended: threshold, horizon, measured-range-exit, minimum-inventory,
    #: product-target, dosing-switch-limit, not-converged
    ended: str | None = None
    simulated_h: float | None = None
    time_to_threshold_h: float | None = None
    operating_time_h: float | None = None
    time_outside_measured_range_h: float | None = None
    first_exit_h: float | None = None
    time_outside_model_range_h: float | None = None
    feasible: bool = False
    totals: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    series: dict[str, Any] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)
    _inputs: tuple[Any, Any] | None = field(default=None, repr=False)

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}


@dataclass
class DutyReport:
    duties: list[DutyResult]
    findings: list[Finding]
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
            "limitations": list(LIMITATIONS),
            "duties": [d.as_dict() for d in self.duties],
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
                f"cheme.duty-{rule}",
                message,
                line=_yaml_line(self.doc, loc),
                ids=ids,
                hint=hint,
            )
        )

    def value(self, q: Value | None, units: dict[Any, float], what: str, loc, ids) -> float | None:
        if q is None:
            return None
        factor = units.get(q.unit)
        if factor is None:
            self.add(
                "error",
                "schema",
                f"{what} in unit {q.unit!r}",
                loc,
                ids,
                "use one of " + ", ".join(str(u) for u in units if u is not None),
            )
            return None
        return q.value * factor


# -- the plan: a duty in SI numbers -------------------------------------------------------------


@dataclass
class _Plan:
    kind: str
    #: "current" (A per cell), "density" (A/m2) or "power" (W of all cells)
    quantity: str
    times: list[float]
    values: list[float]
    interpolation: str
    period: float | None
    on_fraction: float | None
    start_on: bool
    volume_l: float
    composition: dict[str, float]
    cation: str
    model_id: str
    model_parameters: dict[str, Any]
    temperature_k: float | None
    dosing: str
    dosing_concentration: float
    dosing_rate_l_s: float
    dosing_density_kg_l: float | None
    trigger_ph: float | None
    stop_ph: float | None
    bleed_l_s: float
    makeup_l_s: float
    threshold_ph: float
    horizon_s: float
    min_volume_l: float | None
    min_cation_mol: float | None
    rtol: float


def _plan(duty: Duty, cell: DutyCell, out: _Out, loc: list[Any]) -> _Plan | None:
    """The duty's inputs in SI units (a unit or range error is a schema finding: None)."""
    before = len(out.findings)
    ids = [duty.id]
    s = duty.schedule
    at = [*loc, "schedule"]
    period = on = None
    start_on = True
    if isinstance(s, ConstantCurrent | OnOff):
        if s.current is not None:
            quantity = "current"
            value = out.value(s.current, _CURRENT, "current", [*at, "current"], ids)
        else:
            quantity = "density"
            value = out.value(
                s.current_density,
                _CURRENT_DENSITY,
                "current_density",
                [*at, "current_density"],
                ids,
            )
        times, values = [0.0], [value if value is not None else 0.0]
        interpolation = "step"
        if isinstance(s, OnOff):
            period = out.value(s.period, _TIME, "period", [*at, "period"], ids)
            on = s.duty_fraction
            start_on = s.start == "on"
    else:
        factor_t = _TIME[s.time_unit]
        if isinstance(s, PowerSchedule):
            quantity = "power"
            factor = _POWER.get(s.unit)
        elif s.unit in _CURRENT:
            quantity, factor = "current", _CURRENT[s.unit]
        else:
            quantity, factor = "density", _CURRENT_DENSITY.get(s.unit)
        if factor is None:
            units = _POWER if quantity == "power" else {**_CURRENT, **_CURRENT_DENSITY}
            out.add(
                "error",
                "schema",
                f"duty {duty.id}: schedule unit {s.unit!r}",
                [*at, "unit"],
                ids,
                "use one of " + ", ".join(units),
            )
            factor = 1.0
        times = [t * factor_t for t, _ in s.points]
        values = [v * factor for _, v in s.points]
        interpolation = s.interpolation
    if quantity == "density" and not cell.area_m2:
        out.add(
            "error",
            "cell-missing",
            f"duty {duty.id}: a current density schedule, but cell {cell.id} has no active_area",
            [*loc, "cell"],
            ids,
            "give the cell's active_area in process/cells.yaml",
        )
    if period is not None and period <= 0:
        out.add(
            "error",
            "schema",
            f"duty {duty.id}: period not positive",
            [*at, "period"],
            ids,
            "give the on-off period",
        )
    r = duty.reservoir
    rat = [*loc, "reservoir"]
    volume = out.value(r.volume, _VOLUME, "reservoir volume", [*rat, "volume"], ids)
    if volume is not None and volume <= 0:
        out.add(
            "error",
            "schema",
            f"duty {duty.id}: reservoir volume not positive",
            [*rat, "volume"],
            ids,
            "give the anolyte volume in the reservoir",
        )
    composition: dict[str, float] = {}
    for key in ("hydroxide", "carbonate", "bicarbonate", "co2"):
        given = getattr(r.composition, key)
        c = out.value(given, _CONCENTRATION, key, [*rat, "composition", key], ids)
        if c is not None:
            if c < 0:
                out.add(
                    "error",
                    "schema",
                    f"duty {duty.id}: {key} concentration negative",
                    [*rat, "composition", key],
                    ids,
                    "a concentration is not negative",
                )
            composition[key] = c
    temperature = cell.temperature_k
    if r.temperature is not None:
        temperature = to_kelvin(r.temperature.value, r.temperature.unit or "")
        if temperature is None:
            out.add(
                "error",
                "schema",
                f"duty {duty.id}: temperature unit {r.temperature.unit!r}",
                [*rat, "temperature"],
                ids,
                "use K or °C",
            )
    parameters: dict[str, Any] = {"cation": r.cation, "temperature_k": temperature}
    if r.degassing is not None:
        d = r.degassing
        parameters["kla_per_s"] = out.value(d.kla, _KLA, "kla", [*rat, "degassing", "kla"], ids)
        parameters["co2_partial_pressure_atm"] = out.value(
            d.co2_partial_pressure,
            _PRESSURE,
            "co2_partial_pressure",
            [*rat, "degassing", "co2_partial_pressure"],
            ids,
        )
        if (parameters["kla_per_s"] or 0) < 0 or (parameters["co2_partial_pressure_atm"] or 0) < 0:
            out.add(
                "error",
                "schema",
                f"duty {duty.id}: degassing values negative",
                [*rat, "degassing"],
                ids,
                "k_L a and p_CO2 are not negative",
            )
    dosing = duty.dosing
    dat = [*loc, "dosing"]
    concentration = rate = 0.0
    density = trigger = stop = None
    if isinstance(dosing, ThresholdDosing | ContinuousDosing):
        concentration = (
            out.value(
                dosing.concentration,
                _CONCENTRATION,
                "dosing concentration",
                [*dat, "concentration"],
                ids,
            )
            or 0.0
        )
        rate = out.value(dosing.rate, _FLOW, "dosing rate", [*dat, "rate"], ids) or 0.0
        density = out.value(dosing.density, _DENSITY, "dosing density", [*dat, "density"], ids)
        if concentration <= 0 or rate <= 0:
            out.add(
                "error",
                "schema",
                f"duty {duty.id}: dosing concentration and rate are positive",
                dat,
                ids,
                "give the solution's concentration and dosing rate",
            )
        if isinstance(dosing, ThresholdDosing):
            trigger, stop = dosing.trigger_ph, dosing.stop_ph
            if trigger <= duty.threshold.ph:
                out.add(
                    "error",
                    "schema",
                    f"duty {duty.id}: dosing trigger pH {trigger:g} is not above the threshold "
                    f"pH {duty.threshold.ph:g}: the threshold is reached before dosing starts",
                    [*dat, "trigger_ph"],
                    ids,
                    "set trigger_ph above threshold.ph",
                )
    bleed = makeup = 0.0
    if duty.bleed is not None:
        bleed = out.value(duty.bleed.rate, _FLOW, "bleed rate", [*loc, "bleed", "rate"], ids) or 0
    if duty.makeup_water is not None:
        makeup = (
            out.value(
                duty.makeup_water.rate,
                _FLOW,
                "make-up water rate",
                [*loc, "makeup_water", "rate"],
                ids,
            )
            or 0.0
        )
    if bleed < 0 or makeup < 0:
        out.add(
            "error",
            "schema",
            f"duty {duty.id}: a negative bleed or make-up rate",
            loc,
            ids,
            "rates are not negative",
        )
    horizon = out.value(duty.horizon, _TIME, "horizon", [*loc, "horizon"], ids)
    if horizon is not None and horizon <= 0:
        out.add(
            "error",
            "schema",
            f"duty {duty.id}: horizon not positive",
            [*loc, "horizon"],
            ids,
            "give the longest time to integrate",
        )
    if (
        period is not None
        and period > 0
        and on is not None
        and on < 1
        and horizon is not None
        and horizon / period > MAX_PERIODS
    ):
        out.add(
            "error",
            "schema",
            f"duty {duty.id}: the on/off schedule has {horizon / period:.6g} periods over the "
            f"horizon, more than the {MAX_PERIODS} a duty integrates",
            [*at, "period"],
            ids,
            "lengthen the period, shorten the horizon, or give the mean current as "
            "constant_current where the period is short against the reservoir's time scale",
        )
    minimum = duty.minimum_inventory
    min_volume = min_cation = None
    if minimum is not None:
        mat = [*loc, "minimum_inventory"]
        min_volume = out.value(minimum.volume, _VOLUME, "minimum volume", [*mat, "volume"], ids)
        min_cation = out.value(minimum.cation, _AMOUNT, "minimum cation", [*mat, "cation"], ids)
    if any(f.level == "error" for f in out.findings[before:]):
        return None
    return _Plan(
        kind=s.kind,
        quantity=quantity,
        times=times,
        values=values,
        interpolation=interpolation,
        period=period,
        on_fraction=on,
        start_on=start_on,
        volume_l=volume or 0.0,
        composition=composition,
        cation=r.cation,
        model_id=r.model,
        model_parameters=parameters,
        temperature_k=temperature,
        dosing=dosing.kind,
        dosing_concentration=concentration,
        dosing_rate_l_s=rate,
        dosing_density_kg_l=density,
        trigger_ph=trigger,
        stop_ph=stop,
        bleed_l_s=bleed,
        makeup_l_s=makeup,
        threshold_ph=duty.threshold.ph,
        horizon_s=horizon or 0.0,
        min_volume_l=min_volume,
        min_cation_mol=min_cation,
        rtol=duty.tolerance or DEFAULT_RTOL,
    )


# -- the operation: current and performance in time ---------------------------------------------


@dataclass(frozen=True)
class _Op:
    current_a: float
    current_density_a_m2: float | None
    point: OperatingPoint | None
    in_range: bool
    reason: str = ""
    power_w: float | None = None


class _Operation:
    """The schedule of a duty against its cell: the current, the current density and the
    cell's performance at any time, the breakpoints and the times outside the measured
    range."""

    def __init__(self, plan: _Plan, cell: DutyCell, performance: Any) -> None:
        self.plan = plan
        self.cell = cell
        self.performance = performance
        self.temperature_reason = ""
        bounds = performance.temperature_range
        t = plan.temperature_k
        if bounds is not None and t is not None:
            lo, hi = bounds
            if not lo - _TEMPERATURE_SLACK <= t <= hi + _TEMPERATURE_SLACK:
                where = performance.file or "the cell's operating range"
                self.temperature_reason = (
                    f"temperature {t:.6g} K outside the measured {lo:g}-{hi:g} K of {where}"
                )
        self._power_range: tuple[float, float] | None = None
        self._memo: dict[float, float | None] = {}

    # the schedule's value

    def _index(self, t: float) -> int:
        return max(bisect.bisect_right(self.plan.times, t) - 1, 0)

    def _value(self, t: float, index: int) -> float:
        p = self.plan
        if p.interpolation == "step" or index >= len(p.times) - 1:
            return p.values[index]
        t0, t1 = p.times[index], p.times[index + 1]
        v0, v1 = p.values[index], p.values[index + 1]
        return v0 + (v1 - v0) * (t - t0) / (t1 - t0)

    def _on(self, t: float) -> bool:
        p = self.plan
        if p.period is None or p.on_fraction is None or p.on_fraction >= 1:
            return True
        phase = math.fmod(t, p.period)
        if p.start_on:
            return phase < p.on_fraction * p.period
        return phase >= (1 - p.on_fraction) * p.period

    def breakpoints(self, horizon: float) -> list[float]:
        """Every schedule point and on/off switch in (0, *horizon*): all of them (the plan
        holds at most :data:`MAX_PERIODS` periods; more raises ValueError, never truncates)."""
        p = self.plan
        found = {t for t in p.times if 0 < t < horizon}
        if p.period is not None and p.on_fraction is not None and p.on_fraction < 1:
            if horizon / p.period > MAX_PERIODS + 1:
                raise ValueError(f"more than {MAX_PERIODS} on/off periods over the horizon")
            switch = p.on_fraction if p.start_on else 1 - p.on_fraction
            k = 0
            while k * p.period < horizon:
                for t in (k * p.period, (k + switch) * p.period):
                    if 0 < t < horizon:
                        found.add(t)
                k += 1
        return sorted(found)

    # the current and the performance

    def _power_to_density(self, power_cell: float) -> float | None:
        """The current density at which one cell takes *power_cell* (W): the lowest root of
        U(j) j A = P inside the measured range; None when there is none."""
        if power_cell in self._memo:
            return self._memo[power_cell]
        area = self.cell.area_m2 or 0.0
        perf = self.performance
        found: float | None = None
        if perf.bounds is None:
            u = perf.at(None).voltage_v
            found = power_cell / (u * area) if u and area else None
        else:

            def g(j: float) -> float | None:
                u = perf.at(j).voltage_v
                return None if u is None else u * j * area - power_cell

            knots = perf.knots
            for a, b in zip(knots, knots[1:], strict=False):
                ga, gb = g(a), g(b)
                if ga is None or gb is None:
                    continue
                if ga == 0:
                    found = a
                    break
                if gb == 0:
                    found = b
                    break
                if (ga < 0) != (gb < 0):
                    for _ in range(100):
                        m = 0.5 * (a + b)
                        gm = g(m)
                        if gm is None:
                            break
                        if (gm < 0) == (ga < 0):
                            a, ga = m, gm
                        else:
                            b = m
                        if b - a <= 1e-13 * max(b, 1.0):
                            break
                    found = 0.5 * (a + b)
                    break
        if len(self._memo) < 10000:
            self._memo[power_cell] = found
        return found

    def power_range(self) -> tuple[float, float] | None:
        """(min, max) of the power of all cells over the measured range (None: unbounded)."""
        if self._power_range is not None or self.performance.bounds is None:
            return self._power_range
        area = self.cell.area_m2 or 0.0
        values = []
        knots = self.performance.knots
        for a, b in zip(knots, knots[1:], strict=False):
            for k in range(65):
                j = a + (b - a) * k / 64
                u = self.performance.at(j).voltage_v
                if u is not None:
                    values.append(u * j * area * self.cell.cells)
        self._power_range = (min(values), max(values)) if values else (math.inf, -math.inf)
        return self._power_range

    def op(self, t: float, index: int | None = None, on: bool | None = None) -> _Op:
        """The operation at *t*; *index* and *on* fix the schedule's segment and on-off state
        (a step's own values at its ends)."""
        p = self.plan
        i = self._index(t) if index is None else index
        value = self._value(t, i)
        if not (self._on(t) if on is None else on):
            value = 0.0
        area = self.cell.area_m2
        if value <= 0:
            return _Op(0.0, 0.0, None, True, power_w=0.0)
        power = None
        if p.quantity == "power":
            power = value
            per_cell = value / self.cell.cells
            if not area:  # a specified cell without an area or a range: constant voltage
                u = self.performance.at(None).voltage_v
                current, j_or = per_cell / u, None
            else:
                j = self._power_to_density(per_cell)
                if j is None:
                    return _Op(
                        0.0,
                        None,
                        None,
                        False,
                        f"no current density in the measured range takes {value:.6g} W",
                        power_w=value,
                    )
                current, j_or = j * area, j
        elif p.quantity == "density":
            j_or = value
            current = value * (area or 0.0)
        else:
            current = value
            j_or = value / area if area else None
        point = self.performance.at(j_or)
        if self.temperature_reason:
            return _Op(current, j_or, point, False, self.temperature_reason, power)
        return _Op(current, j_or, point, point.available, point.reason, power)

    def within(self, a: float, b: float) -> Callable[[float], _Op]:
        """The operation on [a, b] with the segment and on-off state of its midpoint."""
        mid = 0.5 * (a + b)
        index, on = self._index(mid), self._on(mid)
        if self.plan.interpolation == "step" or index >= len(self.plan.times) - 1:
            fixed = self.op(mid, index, on)  # constant on the segment
            return lambda t: fixed
        return lambda t: self.op(t, index, on)

    def critical(self, horizon: float) -> list[float]:
        """The breakpoints and, on linear segments, the times the operation crosses the range
        bounds (and the measured knots): between two of them it is in range, out or idle."""
        p = self.plan
        found = set(self.breakpoints(horizon))
        if p.interpolation == "linear" and len(p.times) > 1:
            levels: list[float] = [0.0]
            area = self.cell.area_m2 or 0.0
            if p.quantity == "power":
                span = self.power_range()
                if span is not None and math.isfinite(span[0]):
                    levels += list(span)
            elif self.performance.bounds is not None:
                scale = 1.0 if p.quantity == "density" else area
                levels += [k * scale for k in self.performance.knots]
            for k in range(len(p.times) - 1):
                t0, t1 = p.times[k], p.times[k + 1]
                v0, v1 = p.values[k], p.values[k + 1]
                if v1 == v0:
                    continue
                for level in levels:
                    w = (level - v0) / (v1 - v0)
                    if 0 < w < 1:
                        t = t0 + w * (t1 - t0)
                        if 0 < t < horizon:
                            found.add(t)
        return sorted(found)

    def intervals(self, horizon: float) -> list[tuple[float, float, str]]:
        """[a, b) intervals over [0, horizon], each ``in``, ``out`` or ``idle``."""
        cuts = [0.0, *self.critical(horizon), horizon]
        rows = []
        for a, b in zip(cuts, cuts[1:], strict=False):
            if b <= a:
                continue
            op = self.op(0.5 * (a + b))
            state = (
                "idle" if op.current_a <= 0 and op.in_range else ("in" if op.in_range else "out")
            )
            if rows and rows[-1][2] == state and rows[-1][1] == a:
                rows[-1] = (rows[-1][0], b, state)
            else:
                rows.append((a, b, state))
        return rows


# -- the integration ----------------------------------------------------------------------------


@dataclass
class _Piece:
    a: float
    b: float
    solution: Solution
    op: Callable[[float], _Op]
    dosing_on: bool


#: the accumulators after the model's state
_ACCUMULATORS = (
    "charge_c",
    "energy_j",
    "product_mol",
    "hydroxide_deficit_mol",
    "dosing_mol",
    "dosing_l",
    "bleed_l",
    "makeup_l",
    "co2_degassed_mol",
)


def _fluxes(
    op: _Op, plan: _Plan, cell: DutyCell, dosing_on: bool
) -> tuple[ReservoirFluxes, dict[str, float]]:
    """The reservoir's fluxes at one operation, and the accumulators' rates."""
    n = cell.cells
    current = op.current_a * n  # A through all cells together (each carries op.current_a)
    ions: dict[str, float] = {}
    rates = dict.fromkeys(_ACCUMULATORS, 0.0)
    point = op.point
    if current > 0 and point is not None and point.available:
        wde = point.water_dissociation_efficiency or 0.0
        electrons = current / FARADAY
        ions["OH-"] = (wde - 1.0) * electrons
        co = (1.0 - wde) * electrons
        for ion, share in point.co_ions.items():
            z = _CARBON_IONS.get(ion)
            if z is not None:
                ions[ion] = ions.get(ion, 0.0) + share * co / z
            else:  # the cation leaves the anolyte
                ions[ion] = ions.get(ion, 0.0) - share * co
        rates["charge_c"] = current
        rates["energy_j"] = (point.voltage_v or 0.0) * current
        rates["product_mol"] = (
            (point.faradaic_efficiency or 0.0) * current * cell.product_per_extent
        ) / (cell.electrons * FARADAY)
        rates["hydroxide_deficit_mol"] = co
    dosing: dict[str, float] = {}
    volume_in = plan.makeup_l_s
    if dosing_on and plan.dosing != "none":
        mol = plan.dosing_concentration * plan.dosing_rate_l_s
        dosing = {plan.cation: mol, "OH-": mol}
        volume_in += plan.dosing_rate_l_s
        rates["dosing_mol"] = mol
        rates["dosing_l"] = plan.dosing_rate_l_s
    rates["bleed_l"] = plan.bleed_l_s
    rates["makeup_l"] = plan.makeup_l_s
    return ReservoirFluxes(ions, dosing, volume_in, plan.bleed_l_s), rates


@dataclass(frozen=True)
class _Layout:
    """Where the duty finds what it needs in a model's state vector, by the names of
    ``model.state`` (never by position): the volume (L), the cation (mol), the carbon (mol, if
    the model carries it) and every conserved inventory (mol) that must not go negative."""

    k: int
    volume: int
    cation: int
    carbon: int | None
    inventories: tuple[tuple[int, str], ...]


def _layout(model: Any) -> _Layout:
    """The :class:`_Layout` of *model*; ValueError when its state names no ``cation`` in mol
    and ``volume`` in L."""
    names = [(str(n), str(u)) for n, u in model.state]
    index = {n: i for i, (n, _) in enumerate(names)}
    lacking = [
        f"{name} ({unit})"
        for name, unit in (("cation", "mol"), ("volume", "L"))
        if name not in index or names[index[name]][1] != unit
    ]
    if lacking:
        raise ValueError(f"its state declares no {' and no '.join(lacking)}")
    carbon = index.get("carbon")
    return _Layout(
        len(names),
        index["volume"],
        index["cation"],
        carbon if carbon is not None and names[carbon][1] == "mol" else None,
        tuple((i, n) for i, (n, u) in enumerate(names) if u == "mol"),
    )


class _Speciator:
    """The model's speciation with a one-entry cache (events and samples ask twice)."""

    def __init__(self, model: Any, layout: _Layout) -> None:
        self.model = model
        self.k = layout.k
        self.volume = layout.volume
        self._key: tuple[float, ...] | None = None
        self._value: Speciation | None = None

    def __call__(self, y: Sequence[float]) -> Speciation:
        key = tuple(y[: self.k])
        if key != self._key:
            self._value = self.model.speciate(key) if key[self.volume] > 0 else None
            self._key = key
        if self._value is None:
            raise ValueError("the reservoir is empty")
        return self._value


def _scales(plan: _Plan, cell: DutyCell, y0: list[float], k: int) -> list[float]:
    """Absolute tolerances: rtol times a typical size of each component."""
    current = max(plan.values) if plan.quantity != "power" else max(plan.values) / 3.0
    if plan.quantity == "density":
        current *= cell.area_m2 or 1.0
    charge = max(current * cell.cells * plan.horizon_s, 1e-6)
    largest = max((abs(v) for v in y0[:k]), default=1.0)
    typical = [max(abs(v), 1e-3 * largest, 1e-12) for v in y0[:k]]
    typical += [
        charge,
        charge * 5.0,
        charge / FARADAY,
        charge / FARADAY,
        max(plan.dosing_concentration * plan.dosing_rate_l_s * plan.horizon_s, 1e-9),
        max(plan.dosing_rate_l_s * plan.horizon_s, 1e-9),
        max(plan.bleed_l_s * plan.horizon_s, 1e-9),
        max(plan.makeup_l_s * plan.horizon_s, 1e-9),
        max(charge / FARADAY, 1e-9),
    ]
    return [max(plan.rtol * 1e-3 * t, 1e-300) for t in typical]


@dataclass
class _Run:
    pieces: list[_Piece]
    ended: str
    events: list[dict[str, Any]]
    validity_cuts: list[float]
    message: str = ""
    model: Any = None
    layout: _Layout | None = None
    dosing_starts: list[tuple[float, float]] = field(default_factory=list)

    @property
    def k(self) -> int:
        return self.layout.k if self.layout is not None else 0


def _integrate(
    plan: _Plan,
    cell: DutyCell,
    operation: _Operation,
    model: Any,
    stop_at: float,
    product_target_mol: float | None = None,
    track_validity: bool = True,
) -> _Run:
    layout = _layout(model)
    k = layout.k
    iv, ic = layout.volume, layout.cation
    y0 = list(model.initial(plan.composition, plan.volume_l)) + [0.0] * len(_ACCUMULATORS)
    atol = _scales(plan, cell, y0, k)
    speciate = _Speciator(model, layout)
    events: list[dict[str, Any]] = []
    pieces: list[_Piece] = []
    validity_cuts: list[float] = []
    dosing_starts: list[tuple[float, float]] = []

    def ph(y: Sequence[float]) -> float:
        return speciate(y).ph

    initial = speciate(y0)
    dosing_on = plan.dosing == "continuous" or (
        plan.dosing == "on_threshold"
        and plan.trigger_ph is not None
        and initial.ph <= plan.trigger_ph
    )
    if dosing_on and plan.dosing == "on_threshold":
        events.append({"kind": "dosing-on", "t_h": 0.0, "ph": initial.ph})
        dosing_starts.append((0.0, initial.ph))
    if initial.ph <= plan.threshold_ph:
        events.append({"kind": "threshold", "t_h": 0.0, "ph": initial.ph})
        return _Run([], "threshold", events, [], model=model, layout=layout)
    validity = model.validity if track_validity else None
    volume_floor = 1e-9 * plan.volume_l

    def make_events(on: bool) -> list[Event]:
        found = [
            Event(lambda t, y: ph(y) - plan.threshold_ph, "threshold", True, -1),
            Event(lambda t, y: y[iv] - volume_floor, "empty", True, -1),
        ]
        # a conserved inventory (the cation, the carbon) that falls to zero: more has left than
        # the reservoir held, the model's state is no longer physical
        for i, name in layout.inventories:
            found.append(Event(lambda t, y, i=i: y[i], f"exhausted:{name}", True, -1))
        if plan.min_volume_l is not None:
            found.append(
                Event(lambda t, y: y[iv] - plan.min_volume_l, "minimum-inventory", True, -1)
            )
        if plan.min_cation_mol is not None:
            found.append(
                Event(lambda t, y: y[ic] - plan.min_cation_mol, "minimum-inventory", True, -1)
            )
        if plan.dosing == "on_threshold":
            if on:
                found.append(Event(lambda t, y: ph(y) - plan.stop_ph, "dosing-off", True, 1))
            else:
                found.append(Event(lambda t, y: ph(y) - plan.trigger_ph, "dosing-on", True, -1))
        if product_target_mol is not None:
            index = k + _ACCUMULATORS.index("product_mol")
            found.append(
                Event(lambda t, y: y[index] - product_target_mol, "product-target", True, 1)
            )
        if validity is not None and validity.ph is not None:
            for bound in validity.ph:
                found.append(Event(lambda t, y, b=bound: ph(y) - b, "model-range"))
        if validity is not None and validity.ionic_strength_mol_l is not None:
            top = validity.ionic_strength_mol_l[1]
            found.append(Event(lambda t, y: speciate(y).ionic_strength_mol_l - top, "model-range"))
        return found

    def rhs(op_of: Callable[[float], _Op], on: bool):
        def f(t: float, y: Sequence[float]) -> list[float]:
            op = op_of(t)
            fluxes, acc = _fluxes(op, plan, cell, on)
            state = list(y[:k])
            if state[iv] <= 0:
                return [math.nan] * len(y)
            d = list(model.rates(state, fluxes, t))
            acc["co2_degassed_mol"] = model.losses(state).get("CO2", 0.0)
            return d + [acc[name] for name in _ACCUMULATORS]

        return f

    cuts = [0.0, *[c for c in operation.critical(stop_at) if c < stop_at], stop_at]
    y = y0
    ended = ""
    message = ""
    restarts = 0
    for a, b in zip(cuts, cuts[1:], strict=False):
        while b - a > 1e-12 * max(b, 1.0):
            op_of = operation.within(a, b)
            try:
                sol = solve(
                    rhs(op_of, dosing_on),
                    a,
                    y,
                    b,
                    rtol=plan.rtol,
                    atol=atol,
                    events=make_events(dosing_on),
                    max_steps=200_000,
                )
            except ValueError as failure:  # the model refused a state (an empty reservoir)
                ended, message = "not-converged", str(failure)
                break
            pieces.append(_Piece(a, sol.t_final, sol, op_of, dosing_on))
            for hit in sol.events:
                if hit.name == "model-range":
                    validity_cuts.append(hit.t)
            y = sol.y_final
            if sol.status == "failed":
                ended, message = "not-converged", sol.message
                break
            if sol.status == "event":
                hit = sol.events[-1]
                t = hit.t
                current = ph(y)
                if hit.name in ("dosing-on", "dosing-off"):
                    dosing_on = hit.name == "dosing-on"
                    events.append({"kind": hit.name, "t_h": t / 3600, "ph": current})
                    if dosing_on:
                        dosing_starts.append((t, current))
                    restarts += 1
                    if restarts > MAX_DOSING_SWITCHES:
                        ended = "dosing-switch-limit"
                        message = f"{restarts} dosing switches by {t / 3600:.6g} h"
                        events.append(
                            {"kind": "dosing-switch-limit", "t_h": t / 3600, "ph": current}
                        )
                        break
                    a = t
                    continue
                event: dict[str, Any] = {"kind": hit.name, "t_h": t / 3600, "ph": current}
                if hit.name == "empty":
                    event.update(kind="minimum-inventory", detail="the reservoir is empty")
                elif hit.name.startswith("exhausted:"):
                    name = hit.name.split(":", 1)[1]
                    event.update(
                        kind="minimum-inventory",
                        detail=f"the {name} inventory is exhausted (more {name} left the "
                        "reservoir than it held)",
                    )
                elif hit.name == "minimum-inventory":
                    event["detail"] = "the stated minimum inventory"
                events.append(event)
                ended = event["kind"]
                message = event.get("detail", "")
                break
            a = b
        if ended:
            break
    if not ended:
        ended = "horizon" if stop_at >= plan.horizon_s else "measured-range-exit"
    return _Run(pieces, ended, events, validity_cuts, message, model, layout, dosing_starts)


def _locate_piece(pieces: list[_Piece], t: float, left: bool = False) -> _Piece | None:
    if not pieces:
        return None
    starts = [p.a for p in pieces]
    index = (bisect.bisect_left(starts, t) - 1) if left else (bisect.bisect_right(starts, t) - 1)
    return pieces[max(index, 0)]


def _state_at(run: _Run, t: float, left: bool = False) -> tuple[list[float], _Piece | None]:
    piece = _locate_piece(run.pieces, t, left)
    if piece is None:
        return [], None
    return piece.solution.sample(min(max(t, piece.a), piece.b)), piece


# -- one duty -----------------------------------------------------------------------------------


def _refuse(result: DutyResult, out: _Out, rule: str, reason: str, loc, hint: str) -> DutyResult:
    result.refused = True
    result.reasons.append(reason)
    out.add("error", rule, f"duty {result.id}: {reason}: refused", loc, [result.id], hint)
    return result


def _model_for(plan: _Plan, result: DutyResult, out: _Out, loc: list[Any]) -> Any:
    from chemeascode.domains.chemistry.anolyte import anolyte_models

    try:
        model = anolyte_model(plan.model_id, **plan.model_parameters)
    except UnknownAnolyteModel:
        _refuse(
            result,
            out,
            "model-unknown",
            f"no anolyte model {plan.model_id!r}",
            [*loc, "reservoir", "model"],
            "name one of " + ", ".join(anolyte_models()) + " (there is no default)",
        )
        return None
    except (TypeError, ValueError) as failure:
        _refuse(
            result,
            out,
            "model-species",
            f"anolyte model {plan.model_id}: {failure}",
            [*loc, "reservoir"],
            "check the cation and the degassing parameters",
        )
        return None
    try:
        _layout(model)
    except ValueError as failure:
        _refuse(
            result,
            out,
            "model-species",
            f"anolyte model {plan.model_id}: {failure}",
            [*loc, "reservoir", "model"],
            "a duty needs the model's cation inventory (mol) and volume (L) by name in its state",
        )
        return None
    try:
        model.initial(plan.composition, plan.volume_l)
    except ValueError as failure:
        _refuse(
            result,
            out,
            "schema",
            f"composition: {failure}",
            [*loc, "reservoir"],
            "give " + ", ".join(model.composition_keys) + " in mol/L",
        )
        return None
    return model


def _co_ion_names(performance: Any) -> set[str]:
    if isinstance(performance, MeasuredCellPerformance):
        return {performance.cation, "HCO3-", *performance.co_ions_fallback}
    return set(getattr(performance, "co_ions", {}))


def _check_species(cell: DutyCell, model: Any, plan: _Plan, result: DutyResult, out: _Out, loc):
    """Every co-ion of the cell is one the model carries, and it is the reservoir's cation or
    a carbon anion (the fluxes treat every other ion as the cation leaving)."""
    names = _co_ion_names(cell.performance)
    unknown = sorted(n for n in names if n not in model.species)
    cations = sorted(n for n in names if n != plan.cation and n not in _CARBON_IONS)
    if unknown or cations:
        _refuse(
            result,
            out,
            "model-species",
            f"co-ion(s) {', '.join(sorted({*unknown, *cations}))} not carried by anolyte model "
            f"{model.id} with cation {plan.cation}",
            [*loc, "reservoir", "cation"],
            "the membrane's co-ions are the reservoir's cation and HCO3- or CO3-2",
        )
        return False
    return True


def _prepare(
    duty: Duty, cell: DutyCell, result: DutyResult, out: _Out, loc: list[Any]
) -> tuple[_Plan, Any] | None:
    """The checks that need no integration: the plan (units and ranges), the anolyte model
    and the species it carries; None (the result refused, findings in *out*) when one fails.
    :func:`simulate_duty` and :func:`duty_findings` (``cheme validate``) share them."""
    plan = _plan(duty, cell, out, loc)
    if plan is None:
        result.refused = True
        result.reasons.append("schema or unit errors")
        return None
    result.horizon_h = plan.horizon_s / 3600
    result.rtol = plan.rtol
    model = _model_for(plan, result, out, loc)
    if model is None:
        return None
    result.anolyte_model = model.describe()  # its assumptions and limitations included
    if not _check_species(cell, model, plan, result, out, loc):
        return None
    return plan, model


def _measured_range(cell: DutyCell, plan: _Plan, operation: _Operation) -> dict[str, Any]:
    """The range the duty is checked against (:attr:`DutyResult.measured_range`)."""
    perf = cell.performance
    bounds = perf.bounds
    temperature = perf.temperature_range
    power = operation.power_range() if plan.quantity == "power" else None
    measured = [m[1] for m in perf.measured_wde]
    return {
        "basis": perf.basis,
        "source": perf.file,
        "current_density_a_m2": list(bounds) if bounds else None,
        "temperature_k": list(temperature) if temperature else None,
        "power_w": list(power) if power and math.isfinite(power[0]) else None,
        "water_dissociation_efficiency": [min(measured), max(measured)] if measured else None,
    }


def _probe_density(cell: DutyCell, plan: _Plan) -> float | None:
    if plan.quantity == "density":
        return plan.values[0] or None
    if plan.quantity == "current" and cell.area_m2:
        return (max(plan.values) or 0.0) / cell.area_m2
    lo_hi = cell.performance.bounds
    return 0.5 * (lo_hi[0] + lo_hi[1]) if lo_hi else None


def simulate_duty(
    duty: Duty,
    cell: DutyCell,
    *,
    product_target_mol: float | None = None,
    out: _Out | None = None,
    index: int = 0,
    samples: int = SAMPLES,
) -> DutyResult:
    """One duty against its cell (see the module docstring); no plant repository needed.
    *product_target_mol* ends it at that cumulative product (a comparison at equal product).
    Findings go to *out* (default: a fresh one on ``process/duties.yaml``)."""
    out = out if out is not None else _Out(DUTIES_FILE, None)
    loc = ["duties", index]
    result = DutyResult(duty.id, cell.id, line=_yaml_line(out.doc, loc), title=duty.title)
    result.performance = cell.performance.basis
    result.measurement = cell.performance.file
    result.cells_in_series = cell.cells_in_series
    result.stacks = cell.stacks
    result.product = cell.product
    result.schedule = duty.schedule.kind
    result.threshold_ph = duty.threshold.ph
    result.threshold_source = duty.threshold.source
    result.limitations = list(cell.limitations)
    prepared = _prepare(duty, cell, result, out, loc)
    if prepared is None:
        return result
    plan, model = prepared
    if not getattr(model, "degassing", True):
        out.add(
            "info",
            "degassing",
            f"duty {duty.id}: no CO2 degassing stated: it is off",
            [*loc, "reservoir"],
            [duty.id],
            "give reservoir.degassing: {kla, co2_partial_pressure} with their source to include it",
        )
    operation = _Operation(plan, cell, cell.performance)
    result.measured_range = _measured_range(cell, plan, operation)
    rows = operation.intervals(plan.horizon_s)
    first_exit = next((a for a, _, s in rows if s == "out"), None)
    stop_at = plan.horizon_s if first_exit is None else min(first_exit, plan.horizon_s)
    try:
        run = _integrate(plan, cell, operation, model, stop_at, product_target_mol)
    except ValueError as failure:
        return _refuse(
            result,
            out,
            "not-converged",
            str(failure),
            loc,
            "check the reservoir's composition and volume",
        )
    _report(result, run, plan, cell, operation, rows, first_exit, out, loc, samples)
    result._inputs = (duty, cell)
    return result


def _outside_model(run: _Run, t_end: float, temperature_k: float | None) -> float:
    """Seconds of the transient outside the anolyte model's validity."""
    if t_end <= 0:
        return 0.0
    cuts = sorted({0.0, *[c for c in run.validity_cuts if 0 < c < t_end], t_end})
    total = 0.0
    for a, b in zip(cuts, cuts[1:], strict=False):
        y, _ = _state_at(run, 0.5 * (a + b))
        state = y[: run.k]
        if run.layout is None or state[run.layout.volume] <= 0:
            continue
        if run.model.speciate(state).outside(run.model.validity, temperature_k):
            total += b - a
    return total


def _report(
    result: DutyResult,
    run: _Run,
    plan: _Plan,
    cell: DutyCell,
    operation: _Operation,
    rows: list[tuple[float, float, str]],
    first_exit: float | None,
    out: _Out,
    loc: list[Any],
    samples: int,
) -> None:
    did = result.id
    model = run.model
    t_end = run.pieces[-1].solution.t_final if run.pieces else 0.0
    result.ended = run.ended
    result.simulated_h = t_end / 3600
    result.events = list(run.events)
    window = plan.horizon_s if run.ended == "measured-range-exit" else t_end
    outside = sum(min(b, window) - a for a, b, s in rows if s == "out" and a < window)
    operating = sum(min(b, window) - a for a, b, s in rows if s != "idle" and a < window)
    result.operating_time_h = operating / 3600
    result.time_outside_measured_range_h = outside / 3600
    result.first_exit_h = first_exit / 3600 if first_exit is not None else None
    if first_exit is not None and first_exit < window + 1e-9:
        op = operation.op(first_exit + 1e-9 * max(first_exit, 1.0))
        result.events.append(
            {"kind": "measured-range-exit", "t_h": first_exit / 3600, "detail": op.reason}
        )
        result.events.sort(key=lambda e: e["t_h"])
        result.limitations.append(
            "the transient stops at the first exit from the measured range: the state after "
            f"{first_exit / 3600:.6g} h is not computed"
        )
        out.add(
            "warning",
            "out-of-range",
            f"duty {did}: outside the measured range from {first_exit / 3600:.6g} h ({op.reason})"
            f"; {outside / 3600:.6g} h of the scheduled {operating / 3600:.6g} h of operation "
            "outside it; the transient stops there (no extrapolation)",
            [*loc, "schedule"],
            [did],
            "keep the schedule inside the measured current density and temperature, or measure "
            "the missing points",
        )
    model_outside = _outside_model(run, t_end, plan.temperature_k) if run.pieces else 0.0
    result.time_outside_model_range_h = model_outside / 3600
    if model_outside > 0:
        out.add(
            "warning",
            "out-of-range",
            f"duty {did}: {model_outside / 3600:.6g} h of the transient outside the validity of "
            f"anolyte model {model.id} v{model.version} ({_validity_text(model.validity)})",
            [*loc, "reservoir", "model"],
            [did, model.id],
            "treat the pH there as outside the model's claim; use a model that covers it",
        )
    if run.ended == "not-converged":
        out.add(
            "error",
            "not-converged",
            f"duty {did}: the integration failed at {t_end / 3600:.6g} h: {run.message}",
            loc,
            [did],
            "loosen the tolerance, shorten the horizon or check the inputs",
        )
    threshold = next((e for e in run.events if e["kind"] == "threshold"), None)
    if threshold is not None:
        result.time_to_threshold_h = threshold["t_h"]
        out.add(
            "info",
            "threshold-reached",
            f"duty {did}: time to the specified pH threshold {plan.threshold_ph:g}: "
            f"{threshold['t_h']:.6g} h",
            [*loc, "threshold"],
            [did],
            "a stated design criterion, not a corrosion onset; dose, enlarge the reservoir or "
            "change the schedule to meet it",
        )
    elif run.ended == "horizon":
        out.add(
            "info",
            "horizon-reached",
            f"duty {did}: the pH threshold {plan.threshold_ph:g} is not reached within the "
            f"horizon of {plan.horizon_s / 3600:.6g} h",
            [*loc, "horizon"],
            [did],
            "extend the horizon to find the time to the threshold",
        )
    if run.ended == "minimum-inventory":
        exhausted = "exhausted" in run.message
        stated = run.message == "the stated minimum inventory"
        out.add(
            "warning",
            "inventory-low",
            f"duty {did}: the reservoir reached its minimum inventory at {t_end / 3600:.6g} h"
            + (f" ({run.message})" if run.message else "")
            + ("; the transient stops there" if exhausted else ""),
            [*loc, "minimum_inventory" if stated else "reservoir"],
            [did],
            "dose the cation's hydroxide, enlarge the reservoir or shorten the duty"
            if exhausted
            else "balance the bleed with make-up water or dosing, or enlarge the reservoir",
        )
    if run.ended == "dosing-switch-limit":
        band = (plan.stop_ph or 0.0) - (plan.trigger_ph or 0.0)
        out.add(
            "warning",
            "dosing-chatter",
            f"duty {did}: the dosing switched on and off more than {MAX_DOSING_SWITCHES} times "
            f"({run.message}): the band from trigger pH {plan.trigger_ph:g} to stop pH "
            f"{plan.stop_ph:g} ({band:.3g}) is narrow for the dosing rate; the transient stops "
            "there (the integration itself converged)",
            [*loc, "dosing"],
            [did],
            "widen stop_ph - trigger_ph, or lower the dosing rate or concentration",
        )
    # the series, sampled on the dense output
    times = [t_end * i / samples for i in range(samples + 1)] if t_end > 0 else [0.0]
    marks = sorted({e["t_h"] * 3600 for e in result.events if e["t_h"] * 3600 <= t_end})
    breaks = [c for c in operation.critical(t_end) if 0 < c < t_end] if t_end > 0 else []
    # the schedule's breakpoints with the values on both sides (a step), when there are few
    left = set(breaks) if len(breaks) <= 200 else set()
    points = sorted({*times, *marks, *left})
    rows_out = []
    if not run.pieces:  # ended at t = 0: the initial state only
        rows_out = [_initial_row(run, plan, operation)]
    for t in points if run.pieces else []:
        for side in (True, False) if t in left else (False,):
            rows_out.append(_sample(run, plan, cell, t, side))
    result.series = _series(rows_out, model)
    final = rows_out[-1]
    deficit = final["hydroxide_deficit_mol"]
    hydroxide_mass = _hydroxide_molar_mass(plan.cation)
    dose_mol = final["dosing_mol"]
    density = plan.dosing_density_kg_l
    result.totals = {
        "charge_c": final["charge_c"],
        "charge_ah": final["charge_c"] / 3600,
        "energy_kwh": final["energy_kwh"],
        "product": cell.product,
        "product_mol": final["product_mol"],
        "product_kg": final["product_kg"],
        "specific_energy_kwh_per_kg": final["energy_kwh"] / final["product_kg"]
        if final["product_kg"]
        else None,
        "hydroxide_deficit_mol": deficit,
        "dosing_mol": dose_mol,
        "dosing_solution_l": final["dosing_l"],
        "dosing_hydroxide_kg": dose_mol * hydroxide_mass if hydroxide_mass else None,
        "dosing_solution_kg": final["dosing_l"] * density if density else None,
        "bleed_l": final["bleed_l"],
        "makeup_water_l": final["makeup_l"],
        "co2_degassed_mol": final["co2_degassed_mol"],
        "final_ph": final["ph"],
        "minimum_ph": min(r["ph"] for r in rows_out),
        "final_cation_mol": final["cation_mol"],
        "final_carbon_mol": final["carbon_mol"],
        "final_volume_l": final["volume_l"],
    }
    if plan.dosing != "none" and density is None:
        result.limitations.append(
            "no density of the dosing solution: its mass is not given (the hydroxide's is)"
        )
    _dosing_saturation(result, run, plan, final, out, loc)
    concentrations = [r["cation_mol"] / r["volume_l"] for r in rows_out if r["volume_l"] > 0]
    electrolyte = getattr(cell.performance, "electrolyte", "")
    if electrolyte and concentrations:
        result.limitations.append(
            f"the performance was measured in {electrolyte}; the reservoir's {plan.cation} "
            f"concentration ranges {min(concentrations):.4g}-{max(concentrations):.4g} mol/L "
            "over the duty and is not checked against it"
        )
    result.feasible = (
        not result.refused
        and run.ended in ("horizon", "product-target")
        and outside == 0
        and model_outside == 0
    )


def _validity_text(validity: Any) -> str:
    parts = []
    if validity.ph:
        parts.append(f"pH {validity.ph[0]:g}-{validity.ph[1]:g}")
    if validity.ionic_strength_mol_l:
        lo, hi = validity.ionic_strength_mol_l
        parts.append(f"ionic strength {lo:g}-{hi:g} mol/L")
    if validity.temperature_k:
        parts.append(f"{validity.temperature_k[0]:g}-{validity.temperature_k[1]:g} K")
    return ", ".join(parts) or "unbounded"


def _dosing_saturation(
    result: DutyResult, run: _Run, plan: _Plan, final: dict[str, Any], out: _Out, loc
) -> None:
    if plan.dosing == "none":
        return
    reason = ""
    if run.ended == "threshold" and final["dosing_on"]:
        reason = "the threshold was reached while dosing at the full rate"
    elif (
        plan.dosing == "on_threshold"
        and final["dosing_on"]
        and run.ended == "horizon"
        and run.dosing_starts
        and final["ph"] < run.dosing_starts[-1][1]
    ):
        reason = (
            f"dosing ran from {run.dosing_starts[-1][0] / 3600:.6g} h to the horizon without "
            f"reaching its stop pH {plan.stop_ph:g}; the pH still fell"
        )
    if reason:
        out.add(
            "warning",
            "dosing-saturated",
            f"duty {result.id}: {reason}",
            [*loc, "dosing"],
            [result.id],
            "raise the dosing rate or concentration (the hydroxide dosed must exceed the "
            "deficit (1 - WDE) N I / F plus the carbon taken up)",
        )


def _hydroxide_molar_mass(cation: str) -> float | None:
    """kg/mol of the cation's hydroxide (K+ -> KOH)."""
    from chemeascode.domains.chemistry.formulas import molar_mass

    mass = molar_mass(cation.rstrip("+") + "OH")
    return mass / 1000 if mass else None


def _initial_row(run: _Run, plan: _Plan, operation: _Operation) -> dict[str, Any]:
    model = run.model
    state = model.initial(plan.composition, plan.volume_l)
    s = model.speciate(state)
    row = _empty_row(0.0)
    row.update(
        ph=s.ph,
        species=dict(s.concentrations),
        ionic_strength_mol_l=s.ionic_strength_mol_l,
        **_inventory(run.layout, state),
    )
    op = operation.op(0.0)
    row.update(
        current_a=op.current_a,
        current_density_a_m2=op.current_density_a_m2,
        in_measured_range=op.in_range,
    )
    return row


def _inventory(layout: _Layout | None, y: Sequence[float]) -> dict[str, float | None]:
    """The cation, carbon and volume of state *y*, by the model's state names."""
    assert layout is not None
    carbon = layout.carbon
    return {
        "cation_mol": y[layout.cation],
        "carbon_mol": y[carbon] if carbon is not None else None,
        "volume_l": y[layout.volume],
    }


def _empty_row(t: float) -> dict[str, Any]:
    return {
        "t_h": t / 3600,
        "current_a": 0.0,
        "current_density_a_m2": None,
        "voltage_v": None,
        "power_w": 0.0,
        "in_measured_range": True,
        "ph": None,
        "species": {},
        "ionic_strength_mol_l": None,
        "cation_mol": None,
        "carbon_mol": None,
        "volume_l": None,
        "product_rate_mol_s": 0.0,
        "product_rate_kg_h": None,
        "dosing_on": False,
        "dosing_rate_l_h": 0.0,
        "bleed_rate_l_h": 0.0,
        "charge_c": 0.0,
        "energy_kwh": 0.0,
        "product_mol": 0.0,
        "product_kg": None,
        "hydroxide_deficit_mol": 0.0,
        "dosing_mol": 0.0,
        "dosing_l": 0.0,
        "bleed_l": 0.0,
        "makeup_l": 0.0,
        "co2_degassed_mol": 0.0,
    }


def _sample(run: _Run, plan: _Plan, cell: DutyCell, t: float, left: bool) -> dict[str, Any]:
    y, piece = _state_at(run, t, left)
    assert piece is not None
    k = run.k
    op = piece.op(t)
    fluxes, acc = _fluxes(op, plan, cell, piece.dosing_on)
    s = run.model.speciate(y[:k])
    mass = cell.product_molar_mass_kg_mol
    totals = dict(zip(_ACCUMULATORS, y[k:], strict=True))
    row = _empty_row(t)
    point = op.point
    row.update(
        current_a=op.current_a,
        current_density_a_m2=op.current_density_a_m2,
        voltage_v=point.voltage_v if point is not None and op.current_a > 0 else None,
        power_w=(point.voltage_v or 0.0) * op.current_a * cell.cells if point else 0.0,
        in_measured_range=op.in_range,
        ph=s.ph,
        species=dict(s.concentrations),
        ionic_strength_mol_l=s.ionic_strength_mol_l,
        **_inventory(run.layout, y),
        product_rate_mol_s=acc["product_mol"],
        product_rate_kg_h=acc["product_mol"] * mass * 3600 if mass else None,
        dosing_on=piece.dosing_on and plan.dosing != "none",
        dosing_rate_l_h=acc["dosing_l"] * 3600,
        bleed_rate_l_h=plan.bleed_l_s * 3600,
        charge_c=totals["charge_c"],
        energy_kwh=totals["energy_j"] / 3.6e6,
        product_mol=totals["product_mol"],
        product_kg=totals["product_mol"] * mass if mass else None,
        hydroxide_deficit_mol=totals["hydroxide_deficit_mol"],
        dosing_mol=totals["dosing_mol"],
        dosing_l=totals["dosing_l"],
        bleed_l=totals["bleed_l"],
        makeup_l=totals["makeup_l"],
        co2_degassed_mol=totals["co2_degassed_mol"],
    )
    del fluxes
    return row


def _series(rows: list[dict[str, Any]], model: Any) -> dict[str, Any]:
    keys = [k for k in rows[0] if k != "species"]
    series: dict[str, Any] = {key: [r[key] for r in rows] for key in keys}
    names = sorted({n for r in rows for n in r["species"]})
    series["species_mol_l"] = {n: [r["species"].get(n) for r in rows] for n in names}
    return series


# -- the plant: loading and resolving the cells -------------------------------------------------


def _load_yaml[T](root: Path, name: str, model: type[T], rule: str) -> tuple[T | None, Any, list]:
    from chemeascode.domains.process.model import _read

    path = root / name
    if not path.is_file():
        return None, None, []
    data, found = _read(path, name)
    doc = _compose(path) if not found else None
    if data is None:
        return None, doc, found
    try:
        return model.model_validate(data), doc, found  # type: ignore[attr-defined]
    except ValidationError as failure:
        return (
            None,
            doc,
            [
                Finding(
                    name,
                    "error",
                    rule,
                    f"{'.'.join(str(p) for p in e['loc']) or '(file)'}: {e['msg']}",
                    line=_yaml_line(doc, e["loc"]),
                    hint="see `cheme schema process-duties`"
                    if name == DUTIES_FILE
                    else f"see `cheme process cell` for {name}",
                )
                for e in failure.errors()
            ],
        )


def has_duties(root: Path) -> bool:
    return (Path(root) / DUTIES_FILE).is_file()


@dataclass
class _Context:
    cells: dict[str, Any]
    reactions: dict[str, Any]
    masses: dict[str, float]
    measurements: dict[str, Any]
    root: Path
    inputs: list[str]


def _context(root: Path) -> _Context:
    from chemeascode.domains.chemistry.reactions import REACTIONS_FILE, Reactions
    from chemeascode.domains.process import MATERIALS_FILE
    from chemeascode.domains.process.electrochemical_cell import CELLS_FILE, Cells, _molar_masses
    from chemeascode.domains.process.schema import Materials

    cells, _, _ = _load_yaml(root, CELLS_FILE, Cells, "cheme.cell-schema")
    materials, _, _ = _load_yaml(root, MATERIALS_FILE, Materials, "cheme.process-schema")
    reactions, _, _ = _load_yaml(root, REACTIONS_FILE, Reactions, "cheme.reaction-schema")
    inputs = [DUTIES_FILE, CELLS_FILE, MATERIALS_FILE, REACTIONS_FILE]
    found = {c.id: c for c in cells.cells} if cells is not None else {}
    inputs += sorted({c.measurements.file for c in found.values() if c.measurements is not None})
    return _Context(
        found,
        reactions.by_id() if reactions is not None else {},
        _molar_masses(materials),
        {},
        root,
        inputs,
    )


def _fraction(q: Any) -> float | None:
    if q is None:
        return None
    factor = _FRACTION.get(q.unit)
    return None if factor is None else q.value * factor


def _membrane_errors(wde: float | None, shares: dict[str, float]) -> list[str]:
    """What makes a membrane block unusable for the anolyte balance: the checks of
    ``cheme.cell-membrane`` (each share in 0..1, adding up to 1; the WDE in 0..1)."""
    errors = []
    tol = _SHARE_TOLERANCE
    if shares and (
        abs(sum(shares.values()) - 1) > tol
        or any(not -tol <= v <= 1 + tol for v in shares.values())
    ):
        listed = ", ".join(f"{ion} {share:g}" for ion, share in shares.items())
        errors.append(
            f"the co-ion shares ({listed}) add up to {sum(shares.values()):.6g}, not 1 with each "
            "in 0..1"
        )
    if wde is not None and not -tol <= wde <= 1 + tol:
        errors.append(f"the water dissociation efficiency {wde:g} is outside 0..1")
    return errors


def resolve_cell(
    duty: Duty, ctx: _Context, out: _Out, index: int
) -> tuple[DutyCell | None, list[str]]:
    """The :class:`DutyCell` of *duty* from the plant's cells, reactions and measurements;
    (None, reasons) with a ``cell-missing`` finding when it lacks what the duty needs."""
    from chemeascode.domains.experiments.electrochemistry import measurement_report

    loc = ["duties", index, "cell"]
    cid = duty.cell
    cell = ctx.cells.get(cid)
    reasons: list[str] = []

    def missing(reason: str, hint: str) -> None:
        reasons.append(reason)
        out.add("error", "cell-missing", f"duty {duty.id}: {reason}: refused", loc, [duty.id], hint)

    if cell is None:
        missing(
            f"cell {cid} is not in process/cells.yaml (or that file does not load)",
            "name a cell id of process/cells.yaml (`cheme process cell`)",
        )
        return None, reasons
    area = None
    if cell.active_area is not None:
        factor = _AREA.get(cell.active_area.unit)
        area = cell.active_area.value * factor if factor else None
    temperature = None
    if cell.thermal is not None:
        temperature = to_kelvin(cell.thermal.temperature.value, cell.thermal.temperature.unit or "")
    membrane = cell.membrane
    if membrane is None or membrane.kind != "bipolar":
        missing(
            f"cell {cid} has no bipolar membrane block: the anolyte balance needs its water "
            "dissociation efficiency and co-ion split",
            "give membrane: {kind: bipolar, water_dissociation_efficiency, co_ion_crossover} "
            "(or measure the WDE)",
        )
        return None, reasons
    wde_given = _fraction(membrane.water_dissociation_efficiency)
    shares = dict(membrane.co_ion_crossover)
    invalid = _membrane_errors(wde_given, shares)
    if invalid:
        missing(
            f"the membrane block of cell {cid} is invalid: {'; '.join(invalid)} (the anolyte "
            "balance would not be electroneutral)",
            "fix membrane: in process/cells.yaml (`cheme validate` reports cheme.cell-membrane)",
        )
        return None, reasons
    reaction = ctx.reactions.get(cell.reaction)
    limitations: list[str] = []
    if cell.performance == "measured":
        link = cell.measurements
        if link is None or not (ctx.root / link.file).is_file():
            missing(
                f"cell {cid} is measured but its measurement file "
                f"{link.file if link else '(none)'} does not exist",
                "give measurements.file from the repository root",
            )
            return None, reasons
        if link.file not in ctx.measurements:
            ctx.measurements[link.file] = measurement_report(ctx.root, link.file)
        report = ctx.measurements[link.file]
        if report.errors:
            missing(
                f"the measurement {link.file} of cell {cid} has {len(report.errors)} error "
                "finding(s)",
                f"run `cheme experiments electrochem {link.file}` and fix them",
            )
            return None, reasons
        if report.voltage_basis == "electrode_vs_reference":
            missing(
                f"{link.file} gives electrode potentials, not a cell voltage",
                "measure the cell voltage at the terminals",
            )
            return None, reasons
        if not area:
            missing(
                f"measured cell {cid} has no active_area (the current density)",
                "give the cell's active_area",
            )
            return None, reasons
        product = duty.product or link.product
        if product not in report.products:
            missing(
                f"{product} is not a product of {link.file}",
                f"name one of {', '.join(report.products)}",
            )
            return None, reasons
        if report.voltage_basis == "cell_ir_corrected":
            limitations.append(
                f"the measured voltage ({link.file}) is iR-corrected: power and energy leave "
                "out the ohmic loss"
            )
        performance: Any = MeasuredCellPerformance(
            report, product, duty.reservoir.cation, wde_given, shares or None
        )
        points = performance.measured.points
        absent = [
            name
            for name, given in (
                (
                    "a water dissociation efficiency (no titration or WDE at any point, no "
                    "membrane.water_dissociation_efficiency)",
                    wde_given is not None or bool(performance.measured_wde),
                ),
                (
                    "a co-ion split (no titrated C_x at any point, no membrane.co_ion_crossover)",
                    bool(shares) or any(p.co_ion_carbon_fraction is not None for p in points),
                ),
            )
            if not given
        ]
        if absent:
            missing(
                f"measured cell {cid} ({link.file}) gives {' nor '.join(absent)}",
                "titrate the anolyte in the measurement, or give membrane."
                "water_dissociation_efficiency and co_ion_crossover with their source",
            )
            return None, reasons
    else:
        if cell.performance != "specified":
            missing(f"cell {cid} is {cell.performance}", "a specified or measured cell")
            return None, reasons
        voltage = None
        if cell.voltage is not None and _VOLTAGE.get(cell.voltage.unit):
            voltage = cell.voltage.value * _VOLTAGE[cell.voltage.unit]
        fe = _fraction(cell.faradaic_efficiency)
        absent = [
            name
            for name, value in (
                ("voltage", voltage),
                ("faradaic_efficiency", fe),
                ("membrane.water_dissociation_efficiency", wde_given),
                ("membrane.co_ion_crossover", shares or None),
            )
            if value is None
        ]
        if absent:
            missing(
                f"specified cell {cid} lacks {', '.join(absent)}",
                "give them in process/cells.yaml with their source",
            )
            return None, reasons
        product = duty.product
        if product is None:
            missing(
                f"specified cell {cid}: the duty names no product",
                "give product: (a product of the cell's reaction)",
            )
            return None, reasons
        rng = cell.operating_range
        density = rng.current_density if rng is not None else None
        if density is not None and not area:
            missing(
                f"cell {cid} has a current density range but no active_area",
                "give the cell's active_area",
            )
            return None, reasons
        if density is None:
            limitations.append(
                f"specified cell {cid} states no current density range: its constants are "
                "applied at every current of the schedule"
            )
            out.add(
                "info",
                "out-of-range",
                f"duty {duty.id}: cell {cid} states no current density range; nothing is "
                "flagged as outside it",
                loc,
                [duty.id],
                "give operating_range.current_density in process/cells.yaml",
            )
        performance = SpecifiedPerformance(
            voltage,  # type: ignore[arg-type]
            fe,  # type: ignore[arg-type]
            wde_given,  # type: ignore[arg-type]
            shares,
            tuple(density) if density else None,
            tuple(rng.temperature) if rng is not None and rng.temperature else None,
        )
    nu = reaction.stoichiometry.get(product, 0.0) if reaction is not None else 0.0
    if nu <= 0:
        missing(
            f"{product} is not a product of the cell's reaction {cell.reaction} (or "
            "process/reactions.yaml does not declare it)",
            "name a product of the cell's overall reaction",
        )
        return None, reasons
    mass = ctx.masses.get(product)
    if mass is None:
        limitations.append(f"no molar mass of {product}: its mass is not given")
    if cell.electrodes is not None:
        anode = cell.electrodes.anode.species
        per_electron = (-anode.get("OH-", 0.0) + anode.get("H+", 0.0)) / anode.get("e-", 1.0)
        if abs(per_electron - 1.0) > 1e-9:
            reasons.append(f"the anode of cell {cid} is no oxygen evolution")
            out.add(
                "error",
                "model-species",
                f"duty {duty.id}: the anode of cell {cid} consumes {per_electron:g} OH- per "
                "electron: the anolyte balance needs oxygen evolution (one OH- or H+ per "
                "electron): refused",
                loc,
                [duty.id],
                "use an anolyte model for that anode reaction",
            )
            return None, reasons
    return (
        DutyCell(
            cid,
            performance,
            cell.electrons,
            product,
            nu,
            mass / 1000 if mass else None,
            area,
            duty.cells_in_series or cell.cells,
            duty.stacks,
            temperature,
            limitations,
        ),
        reasons,
    )


def _load_duties(root: Path) -> tuple[Duties | None, Any, list[Finding]]:
    duties, doc, findings = _load_yaml(root, DUTIES_FILE, Duties, "cheme.duty-schema")
    if doc is None and (root / DUTIES_FILE).is_file():
        doc = _compose(root / DUTIES_FILE)
    return duties, doc, findings


def load_duties(root: Path) -> tuple[Duties | None, Any, list[Finding]]:
    """``process/duties.yaml`` under *root*: the model (None when missing or invalid), its
    composed YAML document (for line numbers) and the schema findings."""
    return _load_duties(Path(root))


def _duplicates(duties: Duties, out: _Out) -> None:
    seen: set[str] = set()
    for index, duty in enumerate(duties.duties):
        if duty.id in seen:
            out.add(
                "error",
                "schema",
                f"duty {duty.id} is declared twice",
                ["duties", index],
                [duty.id],
                "give each duty its own id",
            )
        seen.add(duty.id)


def duty_findings(root: Path) -> list[Finding]:
    """The findings of ``process/duties.yaml`` that need no integration (for ``cheme
    validate``): the schema, the cells (:func:`resolve_cell`), and for a duty whose cell
    resolves the units and ranges, the anolyte model and its species (:func:`_prepare`), the
    error findings :func:`duty_report` gives before it integrates."""
    from chemeascode.domains.chemistry.anolyte import anolyte_models

    root = Path(root)
    duties, doc, findings = _load_duties(root)
    if duties is None:
        return findings
    out = _Out(DUTIES_FILE, doc)
    out.findings += findings
    _duplicates(duties, out)
    ctx = _context(root)
    for index, duty in enumerate(duties.duties):
        cell, _ = resolve_cell(duty, ctx, out, index)
        if duty.reservoir.model not in anolyte_models():
            out.add(
                "error",
                "model-unknown",
                f"duty {duty.id}: no anolyte model {duty.reservoir.model!r}: refused",
                ["duties", index, "reservoir", "model"],
                [duty.id],
                "name one of " + ", ".join(anolyte_models()) + " (there is no default)",
            )
            if cell is None:
                continue
            # the plan's unit and range findings still apply; the model's are reported above
            _plan(duty, cell, out, ["duties", index])
            continue
        if cell is not None:
            _prepare(duty, cell, DutyResult(duty.id, cell.id), out, ["duties", index])
    return out.findings


def duty_report(root: Path, ids: Sequence[str] | None = None) -> DutyReport:
    """Every duty of ``process/duties.yaml`` under *root* (or those in *ids*) integrated (see
    the module docstring). Read-only. A missing file gives an empty report; an unknown id in
    *ids* raises KeyError."""
    from chemeascode.foundation.provenance import source_revision

    root = Path(root)
    duties, doc, findings = _load_duties(root)
    ctx = _context(root)
    source = source_revision(root, ctx.inputs)
    if duties is None:
        return DutyReport([], findings, source)
    unknown = [i for i in ids or [] if i not in {d.id for d in duties.duties}]
    if unknown:
        raise KeyError(f"no duty {', '.join(unknown)} in {DUTIES_FILE}")
    out = _Out(DUTIES_FILE, doc)
    out.findings += findings
    _duplicates(duties, out)
    results = []
    for index, duty in enumerate(duties.duties):
        if ids is not None and duty.id not in ids:
            continue
        results.append(_one(duty, ctx, out, index))
    return DutyReport(results, out.findings, source)


def run_duty(
    root: Path,
    duty_id: str,
    cells_in_series: int | None = None,
    stacks: int | None = None,
) -> DutyReport:
    """Duty *duty_id* of the plant at *root* integrated (as :func:`duty_report`), with its
    arrangement replaced where given: *cells_in_series* per stack and *stacks* on the one
    reservoir (the arrangement a stack sizing chose; the duty's own are then not used).
    Read-only; an unknown id raises KeyError, a missing file gives an empty report."""
    from chemeascode.foundation.provenance import source_revision

    root = Path(root)
    duties, doc, findings = _load_duties(root)
    ctx = _context(root)
    source = source_revision(root, ctx.inputs)
    if duties is None:
        return DutyReport([], findings, source)
    known = {d.id: (i, d) for i, d in enumerate(duties.duties)}
    if duty_id not in known:
        raise KeyError(f"no duty {duty_id} in {DUTIES_FILE}")
    out = _Out(DUTIES_FILE, doc)
    out.findings += findings
    index, duty = known[duty_id]
    cell, reasons = resolve_cell(duty, ctx, out, index)
    if cell is None:
        result = DutyResult(duty.id, duty.cell, line=_yaml_line(out.doc, ["duties", index]))
        result.title, result.refused, result.reasons = duty.title, True, reasons
        return DutyReport([result], out.findings, source)
    if cells_in_series is not None:
        cell.cells_in_series = cells_in_series
    if stacks is not None:
        cell.stacks = stacks
    result = simulate_duty(duty, cell, out=out, index=index)
    return DutyReport([result], out.findings, source)


def _one(
    duty: Duty, ctx: _Context, out: _Out, index: int, target: float | None = None
) -> DutyResult:
    cell, reasons = resolve_cell(duty, ctx, out, index)
    if cell is None:
        result = DutyResult(duty.id, duty.cell, line=_yaml_line(out.doc, ["duties", index]))
        result.title = duty.title
        result.refused = True
        result.reasons = reasons
        return result
    return simulate_duty(duty, cell, product_target_mol=target, out=out, index=index)


# -- comparison at equal delivered product ------------------------------------------------------


@dataclass
class ComparisonRow:
    id: str
    reached: bool
    ended: str | None
    delivered_kg: float | None
    elapsed_h: float | None
    charge_c: float | None
    energy_kwh: float | None
    time_outside_measured_range_h: float | None
    final_ph: float | None
    dosing_mol: float | None
    dosing_hydroxide_kg: float | None
    hydroxide_deficit_mol: float | None
    feasible: bool = False
    reason: str = ""


@dataclass
class Comparison:
    product: str | None
    target_kg: float
    tolerance: float
    rows: list[ComparisonRow]
    findings: list[Finding]
    duties: list[DutyResult] = field(default_factory=list)
    source: Any = None

    def as_dict(self) -> dict[str, Any]:
        from chemeascode.foundation.schemas.run import finding_dict

        return {
            "model": MODEL,
            "core_version": _version(),
            "basis": "equal delivered product",
            "product": self.product,
            "target_kg": self.target_kg,
            "tolerance": self.tolerance,
            "rows": [dict(r.__dict__) for r in self.rows],
            "duties": [d.as_dict() for d in self.duties],
            "findings": [finding_dict(f) for f in self.findings],
            "source": self.source.as_dict() if self.source is not None else None,
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), indent=2)


def compare(
    duties: Sequence[tuple[Duty, DutyCell]],
    target_kg: float,
    tolerance: float = DEFAULT_PRODUCT_TOLERANCE,
    out: _Out | None = None,
    indices: Sequence[int] | None = None,
) -> Comparison:
    """*duties* compared at equal delivered product: each integrated until its cumulative
    product is *target_kg* (or until its horizon, threshold, minimum inventory or the measured
    range ends it first: not reaching the target). A duty reaches the target when it delivers
    it to within *tolerance* times the target (default 1e-3)."""
    out = out if out is not None else _Out(DUTIES_FILE, None)
    if not target_kg > 0 or not 0 < tolerance < 1:
        raise ValueError("the target is positive and the tolerance in (0, 1)")
    products = {cell.product for _, cell in duties}
    product = next(iter(products)) if len(products) == 1 else None
    if len(products) > 1:
        out.add(
            "error",
            "compare",
            "the compared duties form different products: " + ", ".join(sorted(products)),
            [],
            [d.id for d, _ in duties],
            "compare duties of one product",
        )
    rows: list[ComparisonRow] = []
    results: list[DutyResult] = []
    for n, (duty, cell) in enumerate(duties):
        index = indices[n] if indices is not None else n
        mass = cell.product_molar_mass_kg_mol
        if mass is None:
            out.add(
                "error",
                "compare",
                f"duty {duty.id}: no molar mass of {cell.product}",
                ["duties", index],
                [duty.id],
                "give the product's formula in materials.yaml",
            )
            rows.append(_row(duty.id, None, False, "no molar mass of the product"))
            continue
        result = simulate_duty(
            duty, cell, product_target_mol=target_kg / mass, out=out, index=index
        )
        results.append(result)
        delivered = result.totals.get("product_kg") if not result.refused else None
        reached = (
            delivered is not None
            and abs(delivered - target_kg) <= tolerance * target_kg
            and result.ended == "product-target"
        )
        reason = "" if reached else f"ended by {result.ended or 'refusal'}"
        if not reached and not result.refused:
            out.add(
                "warning",
                "target-not-reached",
                f"duty {duty.id}: {delivered or 0:.6g} kg of {cell.product} of the target "
                f"{target_kg:.6g} kg: {reason} at {result.simulated_h or 0:.6g} h",
                ["duties", index],
                [duty.id],
                "extend the horizon, dose, or compare at a smaller target",
            )
        rows.append(_row(duty.id, result, reached, reason))
    return Comparison(product, target_kg, tolerance, rows, out.findings, results)


def _row(did: str, result: DutyResult | None, reached: bool, reason: str) -> ComparisonRow:
    t = result.totals if result is not None else {}
    return ComparisonRow(
        did,
        reached,
        result.ended if result else None,
        t.get("product_kg"),
        result.simulated_h if result else None,
        t.get("charge_c"),
        t.get("energy_kwh"),
        result.time_outside_measured_range_h if result else None,
        t.get("final_ph"),
        t.get("dosing_mol"),
        t.get("dosing_hydroxide_kg"),
        t.get("hydroxide_deficit_mol"),
        bool(result and result.feasible and reached),
        reason,
    )


def compare_duties(
    root: Path, ids: Sequence[str], target_kg: float, tolerance: float = DEFAULT_PRODUCT_TOLERANCE
) -> Comparison:
    """The duties *ids* of the plant at *root* compared at *target_kg* of delivered product
    (see :func:`compare`). Read-only; an unknown id raises KeyError."""
    from chemeascode.foundation.provenance import source_revision

    root = Path(root)
    duties, doc, findings = _load_duties(root)
    ctx = _context(root)
    out = _Out(DUTIES_FILE, doc)
    out.findings += findings
    if duties is None:
        return Comparison(None, target_kg, tolerance, [], out.findings)
    known = {d.id: (i, d) for i, d in enumerate(duties.duties)}
    unknown = [i for i in ids if i not in known]
    if unknown:
        raise KeyError(f"no duty {', '.join(unknown)} in {DUTIES_FILE}")
    pairs = []
    indices = []
    refused: list[ComparisonRow] = []
    for did in ids:
        index, duty = known[did]
        cell, reasons = resolve_cell(duty, ctx, out, index)
        if cell is None:
            refused.append(_row(did, None, False, "; ".join(reasons)))
            continue
        pairs.append((duty, cell))
        indices.append(index)
    comparison = compare(pairs, target_kg, tolerance, out, indices)
    comparison.rows = refused + comparison.rows
    comparison.rows.sort(key=lambda r: list(ids).index(r.id))
    comparison.source = source_revision(root, ctx.inputs)
    return comparison


# -- the operating map --------------------------------------------------------------------------


@dataclass
class OperatingMapResult:
    """Time to the threshold (h; None: not reached within the horizon or the measured range)
    over water dissociation efficiency (columns) and reservoir volume (rows, L)."""

    duty: str
    wde: list[float]
    volume_l: list[float]
    time_h: list[list[float | None]]
    threshold_ph: float
    horizon_h: float
    measured_wde: list[tuple[float, float, float | None, str]]
    duty_wde: float | None
    duty_volume_l: float
    measured_wde_range: tuple[float, float] | None

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def operating_map(
    duty: Duty,
    cell: DutyCell,
    wde: tuple[float, float] | None = None,
    volume_l: tuple[float, float] | None = None,
    resolution: tuple[int, int] | None = None,
) -> OperatingMapResult:
    """The time to the duty's pH threshold with its schedule, dosing and composition, at a
    constant water dissociation efficiency (the columns) and reservoir volume (the rows, log
    spaced). Axis ranges default to the duty's ``operating_map``, else 0.5-0.995 and 0.1 to 10
    times the reservoir. The measured WDE points are returned apart (``measured_wde``)."""
    spec = duty.operating_map or OperatingMap()
    factor = _VOLUME[spec.volume_unit]
    out = _Out(DUTIES_FILE, None)
    plan = _plan(duty, cell, out, ["duties", 0])
    if plan is None:
        raise ValueError("; ".join(f.message for f in out.findings))
    base_volume = plan.volume_l
    w_lo, w_hi = wde or spec.wde or (0.5, 0.995)
    if volume_l is not None:
        v_lo, v_hi = volume_l
    elif spec.volume is not None:
        v_lo, v_hi = spec.volume[0] * factor, spec.volume[1] * factor
    else:
        v_lo, v_hi = base_volume / 10, base_volume * 10
    columns, rows = resolution or spec.resolution
    wdes = [w_lo + (w_hi - w_lo) * i / (columns - 1) for i in range(columns)]
    volumes = [v_lo * (v_hi / v_lo) ** (i / (rows - 1)) for i in range(rows)]
    model = anolyte_model(plan.model_id, **plan.model_parameters)
    grid: list[list[float | None]] = []
    for v in volumes:
        line: list[float | None] = []
        for w in wdes:
            performance = _FixedWde(cell.performance, w)
            scaled = DutyCell(**{**cell.__dict__, "performance": performance})
            sub = _Plan(**{**plan.__dict__, "volume_l": v, "rtol": max(plan.rtol, 1e-7)})
            operation = _Operation(sub, scaled, performance)
            exits = [a for a, _, s in operation.intervals(sub.horizon_s) if s == "out"]
            stop_at = min([sub.horizon_s, *exits])
            run = (
                _integrate(sub, scaled, operation, model, stop_at, track_validity=False)
                if stop_at > 0
                else None
            )
            hit = next((e for e in run.events if e["kind"] == "threshold"), None) if run else None
            line.append(hit["t_h"] if hit else None)
        grid.append(line)
    probe = cell.performance.at(_probe_density(cell, plan))
    measured = list(cell.performance.measured_wde)
    span = (min(m[1] for m in measured), max(m[1] for m in measured)) if measured else None
    return OperatingMapResult(
        duty.id,
        wdes,
        volumes,
        grid,
        plan.threshold_ph,
        plan.horizon_s / 3600,
        measured,
        probe.water_dissociation_efficiency if probe.available else None,
        base_volume,
        span,
    )


# -- text ---------------------------------------------------------------------------------------


def _g(value: float | None, digits: str = ".4g") -> str:
    return "-" if value is None else f"{value:{digits}}"


def _range_text(rng: dict[str, Any]) -> str:
    def span(key: str, unit: str, digits: str = ".6g") -> str:
        value = rng.get(key)
        return f"{value[0]:{digits}}-{value[1]:{digits}} {unit}" if value else "unbounded"

    text = (
        f"{rng['basis']} range: current density {span('current_density_a_m2', 'A/m2')}, "
        f"temperature {span('temperature_k', 'K')}"
    )
    if rng.get("power_w"):
        text += f", power of all cells {span('power_w', 'W')}"
    if rng.get("water_dissociation_efficiency"):
        text += f", measured WDE {span('water_dissociation_efficiency', '', '.4g').strip()}"
    return text


def report_text(report: DutyReport) -> str:
    lines = [f"model {MODEL['id']} v{MODEL['version']} ({SCHEMA}), core {_version()}"]
    for d in report.duties:
        if d.refused:
            lines.append(f"{d.id}: refused ({'; '.join(d.reasons)})")
            continue
        model = d.anolyte_model or {}
        lines.append(
            f"{d.id}: cell {d.cell} ({d.performance}"
            + (f", {d.measurement}" if d.measurement else "")
            + f"), {d.cells_in_series} cell(s) x {d.stacks} stack(s), schedule {d.schedule}, "
            f"anolyte {model.get('id')} v{model.get('version')}"
        )
        t = d.totals
        threshold = (
            f"reached after {d.time_to_threshold_h:.6g} h"
            if d.time_to_threshold_h is not None
            else "not reached"
        )
        if d.measured_range:
            lines.append("  " + _range_text(d.measured_range))
        lines.append(
            f"  time to the specified pH threshold {d.threshold_ph:g}"
            + (f" ({d.threshold_source})" if d.threshold_source else "")
            + f": {threshold}; ended by {d.ended} at {d.simulated_h:.6g} h of {d.horizon_h:.6g} h"
        )
        lines.append(
            f"  charge {t['charge_ah']:.6g} Ah, energy {t['energy_kwh']:.6g} kWh, "
            f"{t['product']} {_g(t['product_kg'], '.6g')} kg ({t['product_mol']:.6g} mol), "
            f"{_g(t['specific_energy_kwh_per_kg'])} kWh/kg"
        )
        lines.append(
            f"  final pH {t['final_ph']:.4f} (minimum {t['minimum_ph']:.4f}), cation "
            f"{t['final_cation_mol']:.6g} mol, carbon {_g(t['final_carbon_mol'], '.6g')} mol, "
            f"volume {t['final_volume_l']:.6g} L; hydroxide deficit "
            f"{t['hydroxide_deficit_mol']:.6g} mol"
        )
        lines.append(
            f"  dosing {t['dosing_mol']:.6g} mol ({t['dosing_solution_l']:.6g} L, hydroxide "
            f"{_g(t['dosing_hydroxide_kg'])} kg, solution {_g(t['dosing_solution_kg'])} kg); "
            f"bleed {t['bleed_l']:.6g} L; make-up water {t['makeup_water_l']:.6g} L"
        )
        lines.append(
            f"  outside the measured range {d.time_outside_measured_range_h:.6g} h of "
            f"{d.operating_time_h:.6g} h operating; outside the anolyte model's validity "
            f"{d.time_outside_model_range_h:.6g} h; feasible: {'yes' if d.feasible else 'no'}"
        )
        for event in d.events:
            lines.append(
                f"  event {event['kind']} at {event['t_h']:.6g} h"
                + (f", pH {event['ph']:.4f}" if event.get("ph") is not None else "")
                + (f" ({event['detail']})" if event.get("detail") else "")
            )
        for text in d.limitations:
            lines.append(f"  limitation: {text}")
    for text in LIMITATIONS:
        lines.append(f"limitation: {text}")
    models = {(m["id"], m["version"]): m for d in report.duties if (m := d.anolyte_model)}
    for (mid, version), m in models.items():
        for text in m["limitations"]:
            lines.append(f"limitation (anolyte model {mid} v{version}): {text}")
    lines += [f.format() for f in report.findings]
    return "\n".join(lines)


def comparison_text(comparison: Comparison) -> str:
    lines = [
        f"model {MODEL['id']} v{MODEL['version']}: duties at equal delivered "
        f"{comparison.product or 'product'} {comparison.target_kg:.6g} kg (tolerance "
        f"{comparison.tolerance:g} of the target)"
    ]
    for r in comparison.rows:
        if r.reached:
            head = f"{r.id}: reached in {r.elapsed_h:.6g} h"
        else:
            head = f"{r.id}: not reached ({r.reason})"
        lines.append(
            head + f"; charge {_g(r.charge_c, '.6g')} C, energy {_g(r.energy_kwh, '.6g')} kWh, "
            f"outside the measured range {_g(r.time_outside_measured_range_h, '.6g')} h, final "
            f"pH {_g(r.final_ph)}, dosing {_g(r.dosing_mol, '.6g')} mol "
            f"({_g(r.dosing_hydroxide_kg)} kg hydroxide), hydroxide deficit "
            f"{_g(r.hydroxide_deficit_mol, '.6g')} mol"
        )
    lines += [f.format() for f in comparison.findings]
    return "\n".join(lines)
