"""Schema ``cheme/recipe/v1`` (``process/recipe.yaml``): the batch basis and recipe of a batch
plant, and the cycle it gives (``cheme process recipe``).

A batch plant's flowsheet holds its rates averaged over the operating year: a stream's kg/h is
the amount one batch makes of it times the batches per year over the hours. The recipe says what
that rests on:

- ``batch_size``: the amount of one stream per batch (kg, t or m3; m3 from the liquid's molar
  volumes, ideal mixing);
- ``hours_per_year`` the batches fit in;
- the unit procedures (ISA-88 names only, no S88 model): per unit (a flowsheet block or step,
  or ``units:`` several steps that run in one vessel, a filter-dryer's filter, wash and dry,
  whose occupancy is counted once), how many run in parallel and its ordered operations
  (charge, heat, dose, react, cool, transfer, distil, filter, dry, clean, hold, other), each
  with its ``duration`` or, for ``dose`` and ``react``, ``from:`` the step's batch or
  semi-batch model (its dosing time, its reaction time; :mod:`.stirred_tank`), for ``distil``
  ``from:`` a still step (its boil-up time; :mod:`.batch_still`), for ``dry`` ``from:`` a dryer
  (one batch's vapour over its drying rate times the vessel's heated area, or its drying time)
  and for ``filter`` ``from:`` a filter with ``filtration:`` (Ruth's time; :mod:`.dryer`).
  A filter-dryer's vessel is the dryer's wet cake over its cake density, rounded up like a
  reactor's (ADR 0057).

A unit procedure on a batch or semi-batch step may size its ``vessel``: the batch's largest
content (the model's volume per hour of flows times the hours of flows one batch makes, batch
size / the flowsheet's rate of the batch-size stream) over the fill fraction, rounded up to the
R10 preferred numbers (ISO 3) of m3, or a given volume; its ``jacket`` (U, area or the wetted
shell and flat bottom of a vessel of the given aspect ratio, the media's temperatures) is checked
against the model's peak duty, and a ``heat`` or ``cool`` operation may give ``temperatures``
instead of a duration: ``t = C / (U A) ln((T_m - T_0) / (T_m - T_1))`` with the medium at a
constant temperature, the content's heat capacity C (the charge's before a dose, else the
end's).

A vessel's ``metal_heat_capacity`` (kJ/K, ADR 0063) heats and cools with the content: in the
jacket times (``C + C_m``) and each of its jacket-timed operations' heat per batch (``heats``,
reported only for a vessel with metal, so a recipe without reports as in 1.9.0), and in
the duty of each model in the vessel (:func:`metal_of`). A still's unit may give a vessel too,
sized from what its steps take in.

A vented batch or semi-batch unit (``batch.vent``, ADR 0054) reports its off-gas per batch:
the model's peak gas rate (kmol/s, and m3/h at the vessel's temperature and pressure) and
what one batch gives off, for sizing the off-gas line and scrubber.

Derived (:func:`evaluate`): each unit's occupancy per batch, its cycle (occupancy over its
parallel units), the plant's cycle time (the slowest unit: the bottleneck), the batches per
year (hours over cycle time), each unit's utilisation, one batch's timeline from start to end
(a unit procedure starts when the previous one starts its ``transfer``, else when it ends; or
at its own ``start``) and the rate of the batch-size stream that follows. :func:`gantt_svg`
draws one batch.

Rules (``cheme.recipe-*``), each finding naming the file, line, rule and a hint:

- ``recipe-schema``: the file does not follow ``cheme/recipe/v1``;
- ``recipe-reference``: a unit, stream or ``from:`` step that is not in the flowsheet, a
  ``from:`` on a step that is no batch or semi-batch (a ``distil``: no still; a ``dry``: no
  dryer; a ``filter``: no filter with filtration), a ``dose`` from a step without dosing, a
  ``start.after`` that is no earlier unit procedure, a duplicate id, a step in the ``units`` of
  one vessel and named by another unit procedure, a vessel or vent of a unit (a block, or
  ``units``) that holds several batch or semi-batch steps;
- ``recipe-duration``: a ``from:`` duration the model cannot give (it does not solve);
- ``recipe-vessel`` (warning): a given vessel the batch fills beyond its fill fraction;
- ``recipe-jacket`` (warning): the peak duty to remove (the unit's model, isothermal) exceeds
  ``U A (T - T_coolant)`` of the jacket at the charge (the smallest wetted area); info without a
  coolant temperature;
- ``recipe-basis`` (warning): the flowsheet's flow of the batch-size stream differs from batch
  size x batches per year / hours by more than 1 % (the balance, the LCI per kg and the TEA
  then rest on different bases); info when the flow cannot be compared.
"""

from __future__ import annotations

import math
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from chemeascode.foundation.findings import Finding
from chemeascode.foundation.schema_base import Provenance, Strict, unsupported_schema
from chemeascode.foundation.yamlsource import _yaml_line

SCHEMA = "cheme/recipe/v1"
RECIPE_FILE = "process/recipe.yaml"
#: A flowsheet rate within this share of the recipe's agrees with it.
TOLERANCE = 0.01
#: Hours per unit of a duration.
HOURS = {"h": 1.0, "min": 1 / 60, "s": 1 / 3600}
#: The operations whose duration may come ``from:`` a step's model.
FROM_KINDS = ("dose", "react", "distil", "filter", "dry")
OPERATIONS = (
    "charge",
    "heat",
    "dose",
    "react",
    "cool",
    "transfer",
    "distil",
    "filter",
    "dry",
    "clean",
    "hold",
    "other",
)


class Duration(Strict):
    value: float = Field(ge=0)
    unit: Literal["h", "min", "s"] = "h"
    provenance: Provenance
    source: str = ""

    def hours(self) -> float:
        return self.value * HOURS[self.unit]


class Operation(Strict):
    """One operation of a unit procedure, its duration given or from the step's model."""

    id: str
    kind: Literal[
        "charge",
        "heat",
        "dose",
        "react",
        "cool",
        "transfer",
        "distil",
        "filter",
        "dry",
        "clean",
        "hold",
        "other",
    ]
    title: str = ""
    duration: Duration | None = None
    from_: str | None = Field(
        default=None,
        alias="from",
        description="dose and react: the batch or semi-batch step whose model gives the "
        "duration (its dosing time; its reaction time, the post-reaction of a semi-batch); "
        "distil: the still step whose model gives its boil-up time (ADR 0055; with its "
        "heat_up_time, the heat-up's time too, ADR 0068); "
        "dry: a dryer step (its drying time); filter: a solid_separation step with "
        "filtration (Ruth's filtration time).",
    )
    temperatures: tuple[float, float] | None = Field(
        default=None,
        description="heat and cool: (start K, end K) of the content; the duration follows "
        "from the unit's vessel.jacket (UA, the medium's temperature).",
    )

    @model_validator(mode="after")
    def _duration(self) -> Operation:
        given = [n for n in ("duration", "from_", "temperatures") if getattr(self, n) is not None]
        if len(given) != 1:
            raise ValueError(
                f"operation {self.id}: give duration, from or temperatures, one of them"
            )
        if self.temperatures is not None:
            if self.kind not in ("heat", "cool"):
                raise ValueError(
                    f"operation {self.id}: temperatures give a heat-up's or a cool-down's time only"
                )
            start, end = self.temperatures
            if min(start, end) <= 0 or (end > start) != (self.kind == "heat"):
                raise ValueError(
                    f"operation {self.id}: temperatures in K, rising to heat, falling to cool"
                )
        if self.from_ is not None and self.kind not in FROM_KINDS:
            raise ValueError(
                f"operation {self.id}: from: gives a dose's or a reaction's time only (and a "
                "distil's boil-up, a filtration's or a drying time); give the duration of a "
                + self.kind
            )
        return self


class Start(Strict):
    """When a unit procedure starts in the batch: with an operation of an earlier one."""

    after: str = Field(description="An earlier unit procedure's id.")
    operation: str | None = Field(
        default=None, description="Its operation this one starts with (default: its end)."
    )


class Jacket(Strict):
    """The jacket (or coil) of a unit's vessel: its overall coefficient, its area (else the
    wetted area of the vessel's shell and bottom) and the medium's temperatures."""

    u: float = Field(gt=0, description="W/(m2 K), overall, content to the jacket's medium.")
    area: float | None = Field(
        default=None, gt=0, description="m2; else the wetted shell and flat bottom."
    )
    coolant_temperature: float | None = Field(
        default=None, gt=0, description="K of the cooling medium (taken as constant)."
    )
    heating_temperature: float | None = Field(
        default=None, gt=0, description="K of the heating medium (taken as constant)."
    )
    provenance: Provenance
    source: str = ""


class Vessel(Strict):
    """A unit's vessel, sized from its batch volume (the unit's batch, semi-batch or still
    model): the working volume over the fill fraction, rounded up to a preferred size."""

    fill_fraction: float = Field(
        default=0.8, gt=0, le=1, description="Largest working volume over the vessel's."
    )
    aspect_ratio: float = Field(
        default=1.0, gt=0, description="Straight-side height over diameter (the jacket's area)."
    )
    nominal: bool = Field(
        default=True, description="Round up to the R10 preferred numbers (ISO 3) in m3."
    )
    volume: float | None = Field(
        default=None, gt=0, description="m3: an existing vessel's, instead of sizing one."
    )
    heated_area: float | None = Field(
        default=None,
        gt=0,
        description="m2 heating the cake of a dryer (wall and plate); default: the jacket's "
        "area, else the shell and bottom wetted by the cake (the dryer's cake_density).",
        exclude_if=lambda value: value is None,  # a reactor's vessel stays as it was
    )
    jacket: Jacket | None = None
    metal_heat_capacity: float | None = Field(
        default=None,
        gt=0,
        description="kJ/K of the vessel's metal (its mass x cp) heated and cooled with the "
        "content: in the heat and cool times and duties, and in the duty of each model in the "
        "vessel (ADR 0063).",
        exclude_if=lambda value: value is None,  # a vessel stays as it was
    )
    provenance: Provenance
    source: str = ""


class UnitProcedure(Strict):
    """What one unit (a flowsheet block or step, or several steps in one vessel) does per
    batch."""

    id: str
    unit: str | None = Field(default=None, description="The flowsheet block or step.")
    units: list[str] | None = Field(
        default=None,
        min_length=1,
        description="Instead of unit: the flowsheet steps (or blocks) that run in one vessel, "
        "e.g. a filter-dryer's filter, wash, filter and dry; its occupancy is counted once.",
        exclude_if=lambda value: value is None,  # a one-unit procedure stays as it was
    )
    title: str = ""
    parallel: int = Field(
        default=1, ge=1, description="Units that take batches in turn (staggered)."
    )
    start: Start | None = Field(
        default=None,
        description="Default: when the previous unit procedure's transfer starts, else when "
        "it ends.",
    )
    operations: list[Operation] = Field(min_length=1)
    vessel: Vessel | None = Field(
        default=None,
        description="Size the unit's vessel and check its jacket (the unit: a batch or "
        "semibatch step, or a block or units holding exactly one), or a still's pot (sized from "
        "what its steps take in, or its volume; no jacket check; ADR 0063), or a dryer's vessel "
        "(its heated area, the filter's plate).",
    )

    @model_validator(mode="after")
    def _one_unit(self) -> UnitProcedure:
        if (self.unit is None) == (self.units is None):
            raise ValueError(f"unit procedure {self.id}: give unit or units, one of them")
        if self.units is not None and len(set(self.units)) != len(self.units):
            raise ValueError(f"unit procedure {self.id}: units: each step once")
        return self

    def members(self) -> list[str]:
        """The flowsheet blocks or steps the procedure runs in (one vessel)."""
        return list(self.units) if self.units is not None else [self.unit or ""]

    @property
    def label(self) -> str:
        """The unit, or the units joined with +."""
        return "+".join(self.members())


class BatchSize(Strict):
    value: float = Field(gt=0)
    unit: Literal["kg", "t", "m3"]
    stream: str = Field(description="The stream this is the amount of, per batch.")
    provenance: Provenance
    source: str = ""


class Hours(Strict):
    value: float = Field(gt=0, le=8784)
    provenance: Provenance
    source: str = ""


class Recipe(Strict):
    """The batch basis and recipe of the plant."""

    schema_: str = Field(alias="schema", description=f"Always {SCHEMA}.")
    kind: Literal["recipe"]
    title: str = ""
    batch_size: BatchSize
    hours_per_year: Hours
    unit_procedures: list[UnitProcedure] = Field(min_length=1)

    @model_validator(mode="after")
    def _version(self) -> Recipe:
        if self.schema_ != SCHEMA:
            raise ValueError(unsupported_schema(self.schema_, SCHEMA))
        return self


@dataclass
class Step:
    """One operation in the timeline of a batch."""

    procedure: str
    unit: str
    operation: str
    kind: str
    start: float  # h from the batch's start
    end: float
    basis: str  # given, assumed, calculated (from the step's model)


@dataclass
class UnitCycle:
    procedure: str
    unit: str
    parallel: int
    occupancy: float  # h per batch
    cycle: float  # h: occupancy / parallel
    utilisation: float = 0.0  # cycle over the plant's cycle time


@dataclass
class VesselResult:
    """A unit's vessel sized for one batch, and its jacket against the peak duty."""

    procedure: str
    unit: str
    working_volume: float  # m3: the batch's largest content
    volume: float  # m3: the vessel's
    rounded: bool  # to a preferred size
    fill: float  # working volume over the vessel's
    diameter: float  # m
    process_temperature: float  # K
    peak_duty: float | None = None  # kW to remove at the peak (isothermal)
    jacket_area: float | None = None  # m2 at the smallest content (the charge)
    removable: float | None = None  # kW: U A (T - T_coolant) there
    coolant_temperature: float | None = None


@dataclass
class HeatResult:
    """A heat-up's or cool-down's heat per batch (ADR 0063): an operation with
    ``temperatures`` in a vessel with ``metal_heat_capacity``, the content's heat capacity and
    the vessel's metal times the change."""

    procedure: str
    unit: str
    operation: str
    kind: str  # heat or cool
    temperatures: tuple[float, float]  # K, start and end
    content_kJ: float  # kJ per batch into the content (negative: removed)
    metal_kJ: float  # kJ per batch into the vessel's metal
    hours: float  # h the operation takes
    year_average_kW: float | None = None  # its kJ per batch x batches per year / hours

    @property
    def kJ(self) -> float:
        return self.content_kJ + self.metal_kJ

    @property
    def mean_kW(self) -> float | None:
        """kW over the operation: its heat over its time."""
        return self.kJ / (self.hours * 3600.0) if self.hours > 0 else None


@dataclass
class VentResult:
    """A vented unit's off-gas per batch (ADR 0054), for sizing its line and scrubber."""

    procedure: str
    unit: str
    stream: str
    peak_rate: float  # kmol/s at the peak, one batch
    peak_volume_flow: float  # m3/h at the vessel's (or vent condenser's) temperature, pressure
    peak_time: float | None  # s from the batch's start (the step's model)
    kmol: dict[str, float]  # given off per batch, by component
    kg: float  # given off per batch
    temperature: float  # K
    pressure: float  # kPa(a)


@dataclass
class _Content:
    """What a unit's batch model gives per batch: kJ/K and m3 of the charge and of the content
    at the end, the peak duty (kW) and the process temperature (K)."""

    charge_capacity: float | None
    end_capacity: float | None
    charge_volume: float
    end_volume: float
    peak_duty: float | None
    temperature: float


#: The R10 preferred numbers (ISO 3) of one decade: the vessel sizes a volume is rounded to.
R10 = (1.0, 1.25, 1.6, 2.0, 2.5, 3.15, 4.0, 5.0, 6.3, 8.0)


def preferred(volume: float) -> float:
    """The smallest R10 preferred number (ISO 3) of m3 at or above *volume*."""
    decade = 10.0 ** math.floor(math.log10(volume))
    for _ in range(2):
        for r in R10:
            if r * decade >= volume * (1 - 1e-12):
                return r * decade
        decade *= 10.0
    return 10.0 * decade


def _diameter(volume: float, aspect: float) -> float:
    """m: the diameter of a cylinder of *volume* m3 with height = *aspect* x diameter."""
    return (4.0 * volume / (math.pi * aspect)) ** (1.0 / 3.0)


def wetted_area(content: float, diameter: float) -> float:
    """m2: the shell and flat bottom wetted by *content* m3 in a vessel of *diameter* m (a
    dished head's area is somewhat larger: a lower bound)."""
    bottom = math.pi * diameter**2 / 4.0
    return math.pi * diameter * content / bottom + bottom


def batch_hours(process: Any, recipe: Recipe, case: str) -> float:
    """h of the flowsheet's flows one batch makes: the batch size over the flowsheet's rate of
    the batch-size stream. Raises ValueError without that rate."""
    from chemeascode.domains.process.model import stream_flows

    size = recipe.batch_size
    stream = next((x for x in process.flowsheet.streams if x.id == size.stream), None)
    flows = stream_flows(process, stream, case) if stream is not None else None
    rate = None
    if flows is not None:
        rate = _volume_flow(process, flows.components) if size.unit == "m3" else flows.total
    if not rate:
        raise ValueError(f"no flow of {size.stream}: the batch's hours of flows are not known")
    trial = _TRIAL_BATCH.get()
    value = size.value if trial is None else trial
    return value * (1000.0 if size.unit == "t" else 1.0) / rate


def hours_per_batch(process: Any, case: str) -> float | None:
    """h of the flowsheet's flows one batch of ``process/recipe.yaml`` makes (its batch size
    over the flowsheet's rate of that stream); None without a recipe that loads. Raises
    ValueError when the batch-size stream has no flow. A batch still scales its boil-up time
    and energy per batch with it (:mod:`.batch_still`)."""
    recipe, _, _ = load_recipe(process.root)
    if recipe is None:
        return None
    return batch_hours(process, recipe, case)


def _vent(process: Any, recipe: Recipe, up: UnitProcedure, case: str) -> VentResult | None:
    """The vent of *up*'s batch or semibatch step per batch (ADR 0054): its model's peak gas
    rate (kmol/s per m3 of the content at the end) times the content one batch ends with, and
    what one batch gives off. None when the step has no vent or does not solve (its own findings
    say why)."""
    from chemeascode.domains.chemistry.thermochemistry import R
    from chemeascode.domains.process.stirred_tank import TankError, solve_node, tank_inlet

    try:
        unit = _tank(process, up)
    except _Reference:
        return None  # evaluate reports it
    node = process.nodes.get(unit)
    vent = getattr(getattr(node, "batch", None), "vent", None)
    if vent is None or getattr(node, "reactor", None) not in ("batch", "semibatch"):
        return None
    try:
        hours = batch_hours(process, recipe, case)
        solved, _ = solve_node(process, node, tank_inlet(node, _inlets(process, unit)), case)
    except (TankError, ValueError):
        return None
    comps = process.components()
    peak = (solved.peak_vent_flow or 0.0) * hours  # kmol/s of one batch
    # the gas leaves at the vessel's temperature, or a vent condenser's outlet (ADR 0062)
    leaving = solved.vent_temperature or solved.temperature
    return VentResult(
        up.id,
        unit,
        vent.stream,
        peak,
        peak * R * leaving / solved.pressure * 3600.0,
        solved.peak_vent_time,
        {n: v * hours for n, v in solved.vent.items()},
        sum(
            v * hours * (getattr(comps.get(n), "molar_mass", None) or 0.0)
            for n, v in solved.vent.items()
        ),
        leaving,
        solved.pressure,
    )


def _nodes(process: Any, up: UnitProcedure) -> list[Any]:
    """The flowsheet blocks and steps of *up*: its members and what is drawn inside them."""
    members = up.members()
    return [
        node
        for n, node in process.nodes.items()
        if process.kinds.get(n) in ("block", "step")
        and any(m in process.kinds and process.within(n, m) for m in members)
    ]


def _tank(process: Any, up: UnitProcedure) -> str:
    """The batch or semibatch step of *up* (its unit, when it has none). Raises _Reference
    when *up* (a block, or its units) holds several: which one's batch sizes the vessel is
    not said."""
    tanks = [
        node.id
        for node in _nodes(process, up)
        if getattr(node, "reactor", None) in ("batch", "semibatch") and node.batch is not None
    ]
    if len(tanks) > 1:
        raise _Reference(
            f"{up.label} holds {', '.join(tanks)}: several batch or semibatch steps, name one "
            "as unit: to size its vessel"
        )
    return tanks[0] if tanks else up.members()[0]


def batch_vessel(process: Any, recipe: Recipe, result: Any, node_id: str) -> Any:
    """The vessel *result* (of :func:`evaluate`) sizes from batch or semibatch step
    *node_id*'s batch: a unit procedure's unit, or the one batch step of its block or units;
    None when none does."""
    procedures = {up.id: up for up in recipe.unit_procedures}
    for vessel in result.vessels:
        up = procedures.get(vessel.procedure)
        if up is None:
            continue
        try:
            if _tank(process, up) == node_id:
                return vessel
        except _Reference:
            continue
    return None


def _inlets(process: Any, node_id: str) -> list[Any]:
    return [s for s in process.flowsheet.streams if (e := process.ends(s)[1]) and e.node == node_id]


def _content(process: Any, recipe: Recipe, up: UnitProcedure, case: str) -> _Content:
    """The batch content of unit procedure *up*'s unit, a batch or semibatch step: its model's
    figures (per hour of the flowsheet's flows) times the hours of flows one batch makes,
    batch size / the flowsheet's rate of the batch-size stream. Raises ValueError."""
    from chemeascode.domains.process.stirred_tank import (
        solve_node,
        split_inlets,
        stream_moles,
        tank_inlet,
    )

    unit = _tank(process, up)
    node = process.nodes.get(unit)
    model = getattr(node, "reactor", None)
    if model not in ("batch", "semibatch") or node.batch is None:
        raise _Reference(f"{unit} is no batch or semibatch: no batch content to size")
    hours = batch_hours(process, recipe, case)
    inlets = _inlets(process, unit)
    inlet = tank_inlet(node, inlets)
    solved, _ = solve_node(process, node, inlet, case)
    # a semi-batch's, or a batch's with a head space's pad (ADR 0071): the charge stream
    charge = split_inlets(node, inlets)[0] if isinstance(inlet, list) else inlet
    comps = process.components()

    def capacity(moles: dict[str, float]) -> float | None:
        cps = [(v, getattr(comps.get(n), "liquid_heat_capacity", None)) for n, v in moles.items()]
        if any(v > 0 and not cp for v, cp in cps):
            return None
        return sum(v * (cp or 0.0) for v, cp in cps) * hours

    charged, _, _ = stream_moles(process, charge, case)
    end_volume = (solved.volume or 0.0) * hours
    charge_volume = (solved.charge_volume or solved.volume or 0.0) * hours
    rate = solved.peak_cooling_duty if model == "semibatch" else solved.peak_heat_rate
    # None: not isothermal, or the heat released is not known (no heat of reaction)
    peak = rate * end_volume if node.batch.heat == "isothermal" and rate is not None else None
    return _Content(
        capacity(charged),
        capacity(solved.outlet),
        charge_volume,
        end_volume,
        peak,
        solved.temperature,
    )


def _vessel(up: UnitProcedure, content: _Content) -> VesselResult:
    """The vessel of *up* for *content*: its volume (given, or the working volume over the
    fill fraction, rounded up), and its jacket at the charge against the peak duty."""
    vessel = up.vessel
    working = max(content.charge_volume, content.end_volume)
    if vessel.volume is not None:
        volume, rounded = vessel.volume, False
    else:
        volume = working / vessel.fill_fraction
        rounded = vessel.nominal
        if rounded:
            volume = preferred(volume)
    diameter = _diameter(volume, vessel.aspect_ratio)
    found = VesselResult(
        up.id,
        up.label,
        working,
        volume,
        rounded,
        working / volume,
        diameter,
        content.temperature,
        content.peak_duty,
    )
    jacket = vessel.jacket
    if jacket is not None:
        found.jacket_area = jacket.area or wetted_area(content.charge_volume, diameter)
        found.coolant_temperature = jacket.coolant_temperature
        if jacket.coolant_temperature is not None:
            found.removable = (
                jacket.u * found.jacket_area * (content.temperature - jacket.coolant_temperature)
            ) / 1000.0
    return found


def _jacket_time(up: UnitProcedure, op: Operation, content: _Content, before_dose: bool) -> float:
    """h to heat or cool the content by *op*'s temperatures in *up*'s jacketed vessel: ``t = C
    / (U A) ln((T_m - T_0) / (T_m - T_1))``, the medium at its constant temperature, the
    charge's content before the dose, else the end's. Raises ValueError."""
    jacket = up.vessel.jacket if up.vessel is not None else None
    if jacket is None:
        raise ValueError(f"{up.id} has no vessel.jacket for a {op.kind} time")
    medium = jacket.heating_temperature if op.kind == "heat" else jacket.coolant_temperature
    if medium is None:
        raise ValueError(
            f"vessel.jacket has no {'heating' if op.kind == 'heat' else 'coolant'}_temperature"
        )
    start, end = op.temperatures or (0.0, 0.0)
    if (medium - end) * (end - start) <= 0:
        raise ValueError(f"the medium at {medium:g} K cannot {op.kind} the content to {end:g} K")
    capacity = content.charge_capacity if before_dose else content.end_capacity
    if capacity is None:
        raise ValueError("no liquid_heat_capacity of the content")
    capacity += up.vessel.metal_heat_capacity or 0.0  # the metal heats and cools with it
    volume = content.charge_volume if before_dose else content.end_volume
    diameter = _diameter(_vessel(up, content).volume, up.vessel.aspect_ratio)
    area = jacket.area or wetted_area(volume, diameter)
    ua = jacket.u * area / 1000.0  # kW/K
    return capacity / ua * math.log((medium - start) / (medium - end)) / 3600.0


def _jacket_heat(
    up: UnitProcedure, op: Operation, content: _Content, before_dose: bool, hours: float
) -> HeatResult:
    """The heat of *op* (a heat or cool with temperatures) per batch: the content's (the
    charge's before the dose, else the end's) and the vessel's metal times the change."""
    start, end = op.temperatures or (0.0, 0.0)
    capacity = (content.charge_capacity if before_dose else content.end_capacity) or 0.0
    metal = (up.vessel.metal_heat_capacity if up.vessel is not None else None) or 0.0
    return HeatResult(
        up.id,
        up.label,
        op.id,
        op.kind,
        (start, end),
        capacity * (end - start),
        metal * (end - start) if metal else 0.0,  # no -0.0 for a cool-down
        hours,
    )


def vessel_metal(process: Any, node_id: str) -> tuple[float, str, Recipe] | None:
    """The metal of the vessel step or block *node_id* runs in (ADR 0063): (kJ/K of the
    vessel's ``metal_heat_capacity``, the unit procedure's id, the recipe); None without a
    recipe, or a vessel with metal holding *node_id*."""
    recipe, _, _ = load_recipe(process.root)
    if recipe is None:
        return None
    for up in recipe.unit_procedures:
        metal = up.vessel.metal_heat_capacity if up.vessel is not None else None
        if metal is None:
            continue
        if any(node.id == node_id for node in _nodes(process, up)):
            return metal, up.id, recipe
    return None


def metal_of(process: Any, node_id: str, case: str) -> tuple[float, float, str] | None:
    """The metal of the vessel step or block *node_id* runs in (ADR 0063): (kJ/K of the
    vessel's ``metal_heat_capacity``, h of the flowsheet's flows one batch makes, the unit
    procedure's id); None without a recipe, or a vessel with metal holding *node_id*. Raises
    ValueError when the batch's hours are not known."""
    found = vessel_metal(process, node_id)
    if found is None:
        return None
    metal, procedure, recipe = found
    return metal, batch_hours(process, recipe, case), procedure


def _stills(process: Any, up: UnitProcedure) -> list[Any]:
    """The still steps among *up*'s steps."""
    return [n for n in _nodes(process, up) if getattr(n, "still", None) is not None]


def _solids(process: Any, up: UnitProcedure) -> tuple[Any, Any]:
    """(the dryer, the filter with a filtration) among *up*'s steps, either None."""
    nodes = _nodes(process, up)
    dryer = next((n for n in nodes if getattr(n, "dryer", None) is not None), None)
    separation = next(
        (n for n in nodes if getattr(getattr(n, "solid_separation", None), "filtration", None)),
        None,
    )
    return dryer, separation


def _one_inlet(process: Any, node: Any) -> Any:
    from chemeascode.domains.process.dryer import DryerError

    inlets = [s for s in _inlets(process, node.id) if s.kind == "material"]
    if len(inlets) != 1:
        raise DryerError(f"{node.id}: {len(inlets)} material inlet streams, one needed")
    return inlets[0]


def _step_contents(
    process: Any, recipe: Recipe, up: UnitProcedure, case: str, skip: str | None = None
) -> float | None:
    """m3: the largest material that one batch brings into a step of *up* (the slurry a
    filter-dryer takes, the reslurry wash), each member's material inlets per batch from their
    components' liquid molar volumes; None when none can be calculated. *skip*: a step whose
    content is known otherwise (the dryer with a cake_density)."""
    from chemeascode.domains.process.model import stream_flows

    try:
        hours = batch_hours(process, recipe, case)
    except ValueError:
        return None
    found = None
    for node in _nodes(process, up):
        if node.id == skip:
            continue
        flow = 0.0
        known = False
        for stream in _inlets(process, node.id):
            if stream.kind != "material":
                continue
            volume = _volume_flow(process, stream_flows(process, stream, case).components)
            if volume is not None:
                flow += volume
                known = True
        if known:
            found = max(found or 0.0, flow * hours)
    return found


def _wet_cake(process: Any, recipe: Recipe, dryer: Any, case: str) -> float | None:
    """m3: dryer step *dryer*'s wet cake of one batch (its inlet over its cake_density); None
    without a cake_density. Raises ValueError."""
    from chemeascode.domains.process.model import stream_flows

    density = dryer.dryer.cake_density
    if density is None:
        return None
    wet = stream_flows(process, _one_inlet(process, dryer), case).total
    if wet is None:
        raise ValueError(f"no flow of {dryer.id}'s wet cake")
    return wet * batch_hours(process, recipe, case) / density.value


def _heated_area(
    process: Any, recipe: Recipe, up: UnitProcedure, case: str, diameter: float
) -> float | None:
    """m2 heating the cake in *up*'s vessel of *diameter*: ``vessel.heated_area``, else the
    jacket's area, else the shell and bottom the dryer's wet cake wets; None when none is
    known. Raises ValueError."""
    vessel = up.vessel
    heated = vessel.heated_area or (vessel.jacket.area if vessel.jacket else None)
    dryer, _ = _solids(process, up)
    if heated is None and dryer is not None:
        cake = _wet_cake(process, recipe, dryer, case)
        if cake:
            heated = wetted_area(cake, diameter)
    return heated


def _cake_vessel(process: Any, recipe: Recipe, up: UnitProcedure, case: str) -> VesselResult:
    """The vessel of a filter-dryer or dryer procedure *up*: its largest content of one batch
    over the fill fraction, rounded up, or the given volume. The content is the largest of the
    wet cake (the dryer's inlet over its cake_density) and what each of its steps takes in (the
    slurry, the reslurry wash: :func:`_step_contents`). Its heated area is given, the jacket's,
    or the shell and bottom the cake wets (in ``jacket_area``). Raises ValueError."""

    vessel = up.vessel
    dryer, _ = _solids(process, up)
    cake = None
    temperature = 0.0
    measured = None
    if dryer is not None:
        temperature = dryer.dryer.temperature
        cake = _wet_cake(process, recipe, dryer, case)
        if cake is not None:
            measured = dryer.id
    contents = _step_contents(process, recipe, up, case, skip=measured)
    working = max(cake or 0.0, contents or 0.0) or None
    if vessel.volume is not None:
        volume, rounded = vessel.volume, False
    elif working:
        volume = working / vessel.fill_fraction
        rounded = vessel.nominal
        if rounded:
            volume = preferred(volume)
    else:
        raise ValueError(
            "no vessel volume: give vessel.volume, or the dryer's cake_density (or the "
            "liquid_molar_volume of what the steps take in) to size it"
        )
    diameter = _diameter(volume, vessel.aspect_ratio)
    heated = vessel.heated_area or (vessel.jacket.area if vessel.jacket else None)
    if heated is None and cake:
        heated = wetted_area(cake, diameter)
    return VesselResult(
        up.id,
        up.label,
        working or 0.0,
        volume,
        rounded,
        (working or 0.0) / volume,
        diameter,
        temperature,
        jacket_area=heated,
    )


def _solids_time(
    process: Any,
    recipe: Recipe,
    op: Operation,
    vessel: VesselResult | None,
    case: str,
) -> float:
    """h: the drying time (dry) of dryer *op.from_*, or the filtration time (filter, Ruth) of
    filter *op.from_*, of one batch in the unit procedure's *vessel*. Raises _Reference, or
    ValueError when it cannot be calculated."""
    from chemeascode.domains.process import dryer as drying
    from chemeascode.domains.process.crystallization import separate_node
    from chemeascode.domains.process.solids import solid_components

    node = process.nodes.get(op.from_ or "")
    if op.kind == "dry":
        spec = getattr(node, "dryer", None)
        if spec is None:
            raise _Reference(f"{op.from_} is no dryer (dryer:)")
        if spec.drying_time is not None:
            return drying.drying_hours(spec, 0.0, None)
        result, _ = drying.solve_node(process, node, _one_inlet(process, node), case)
        evaporated = result.evaporated_kg_h * batch_hours(process, recipe, case)
        return drying.drying_hours(spec, evaporated, vessel.jacket_area if vessel else None)
    sep = getattr(node, "solid_separation", None)
    if sep is None or sep.filtration is None:
        raise _Reference(f"{op.from_} is no solid_separation with filtration:")
    ports, _ = separate_node(process, node, _one_inlet(process, node), case)
    hours = batch_hours(process, recipe, case)
    cake, filtrate = ports[sep.outlets["cake"]], ports[sep.outlets["filtrate"]]
    solid = sum(v for n, v in cake.items() if n in solid_components(process)) * hours
    volume = drying.filtrate_volume(process, filtrate, sep.filtration) * hours
    area = sep.filtration.area or (drying.filter_area(vessel.diameter) if vessel else None)
    if area is None:
        raise ValueError("no filter area: give filtration.area or the unit procedure's vessel")
    return drying.ruth_hours(sep.filtration, solid, volume, area)


@dataclass
class RecipeResult:
    title: str
    batch_size: float
    batch_unit: str
    stream: str
    hours_per_year: float
    cycle_time: float | None = None  # h
    bottleneck: str | None = None
    batches_per_year: float | None = None
    makespan: float | None = None  # h, one batch from start to end
    rate: float | None = None  # of the batch-size stream, kg/h (m3/h for m3)
    flowsheet_rate: float | None = None
    units: list[UnitCycle] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)
    vessels: list[VesselResult] = field(default_factory=list)
    vents: list[VentResult] = field(default_factory=list)
    #: the heat-ups' and cool-downs' heat per batch (ADR 0063), operations with temperatures
    heats: list[HeatResult] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        found = asdict(self)
        found["findings"] = [f.format() for f in self.findings]
        if self.heats:
            for entry, heat in zip(found["heats"], self.heats, strict=True):
                entry["kJ"], entry["mean_kW"] = heat.kJ, heat.mean_kW
        else:
            del found["heats"]  # a recipe without a vessel's metal reports as in 1.9.0
        return found


def load_recipe(root: Path) -> tuple[Recipe | None, Any, list[Finding]]:
    """process/recipe.yaml: its model, YAML nodes and schema findings (None without it)."""
    from chemeascode.domains.process.model import _load_optional

    return _load_optional(root, RECIPE_FILE, Recipe, SCHEMA, "cheme.recipe-schema", "recipe")


class _Reference(ValueError):
    """A ``from:`` that names no step whose model gives the duration."""


def _duration_from(process: Any, step_id: str, kind: str, case: str) -> float:
    """h: the dosing time (dose) or reaction time (react) of batch or semi-batch *step_id*, or
    the boil-up time (distil) of still *step_id*. Raises _Reference, or ValueError (TankError,
    StillError) when the model does not solve."""
    from chemeascode.domains.process.stirred_tank import solve_node, tank_inlet

    node = process.nodes.get(step_id)
    still = getattr(node, "still", None)
    if kind == "distil" or still is not None:
        from chemeascode.domains.process.batch_still import inlets_of
        from chemeascode.domains.process.batch_still import solve_node as solve_still

        if still is None:
            raise _Reference(f"{step_id} is no still (still:): no boil-up time")
        if kind != "distil":
            raise _Reference(f"{step_id} is a still: from: it on a distil operation")
        solved, _ = solve_still(process, node, inlets_of(process, node), case)
        if getattr(still, "heat_up_time", False):  # the heat-up's time too (ADR 0068)
            if solved.heat_up_time is None:
                raise ValueError(f"{step_id}'s heat_up_time: no {solved.heat_up_time_missing}")
            return (solved.time + solved.heat_up_time) / 3600.0
        return solved.time / 3600.0
    model = getattr(node, "reactor", None)
    if model not in ("batch", "semibatch") or node.batch is None:
        raise _Reference(f"{step_id} is no batch or semibatch with batch:")
    batch = node.batch
    if kind == "dose":
        if model != "semibatch":
            raise _Reference(f"{step_id} doses nothing (reactor {model})")
        return batch.dosing_end() / 3600.0
    if batch.time is not None:
        return batch.time / 3600.0
    if batch.target is None:
        return 0.0  # a semi-batch that ends with its dosing
    inlets = [
        s for s in process.flowsheet.streams if (e := process.ends(s)[1]) and e.node == step_id
    ]
    solved, _ = solve_node(process, node, tank_inlet(node, inlets), case)
    return ((solved.time or 0.0) - (solved.dosing_time or 0.0)) / 3600.0


def evaluate(
    process: Any,
    recipe: Recipe,
    doc: Any = None,
    case: str | None = None,
    *,
    check_basis: bool = True,
) -> RecipeResult:
    """The cycle of *recipe* on *process* in *case* (default: the default case) with its
    ``cheme.recipe-*`` findings (see the module docstring); without the basis check unless
    *check_basis*."""
    case = case or process.flowsheet.default_case()
    size = recipe.batch_size
    result = RecipeResult(
        recipe.title, size.value, size.unit, size.stream, recipe.hours_per_year.value
    )

    def add(level: str, rule: str, message: str, loc: list[Any], hint: str, ids=()) -> None:
        result.findings.append(
            Finding(
                RECIPE_FILE,
                level,  # type: ignore[arg-type]
                f"cheme.recipe-{rule}",
                message,
                line=_yaml_line(doc, loc) if doc is not None else None,
                ids=list(ids),
                hint=hint,
            )
        )

    seen: set[str] = set()
    claimed: dict[str, tuple[str, bool]] = {}  # step -> (its unit procedure, in a units: list)
    timeline: dict[str, list[Step]] = {}
    clock_end = 0.0
    failed = False
    for k, up in enumerate(recipe.unit_procedures):
        at = ["unit_procedures", k]
        if up.id in seen:
            add("error", "reference", f"unit procedure {up.id} twice", [*at, "id"], "one id each")
        seen.add(up.id)
        many = up.units is not None
        for i, member in enumerate(up.members()):
            where = [*at, "units", i] if many else [*at, "unit"]
            if process.kinds.get(member) not in ("block", "step"):
                add(
                    "error",
                    "reference",
                    f"{up.id}: unit {member} is no block or step of the flowsheet",
                    where,
                    "name the flowsheet block or step the unit procedure runs in",
                    [up.id],
                )
                continue
            other = claimed.get(member)
            if other is not None and other[0] != up.id and (many or other[1]):
                add(
                    "error",
                    "reference",
                    f"{up.id}: {member} is in the vessel of {other[0]} already",
                    where,
                    "a step runs in one vessel: list it in one unit procedure's units",
                    [up.id],
                )
            claimed.setdefault(member, (up.id, many))
        ops: list[tuple[Operation, float, str]] = []
        names: set[str] = set()
        content: _Content | None = None
        cake: VesselResult | None = None  # a filter-dryer's vessel
        found: VesselResult | None = None  # a batch or semibatch step's vessel
        several: _Reference | None = None
        try:
            tank = _tank(process, up)
        except _Reference as failure:
            tank, several = None, failure
        reacts = several is not None or getattr(process.nodes.get(tank), "reactor", None) in (
            "batch",
            "semibatch",
        )
        solids = _solids(process, up) if up.vessel is not None else (None, None)
        if any(solids) and not reacts:
            try:
                cake = _cake_vessel(process, recipe, up, case)
            except ValueError as failure:
                add(
                    "error",
                    "duration",
                    f"{up.id}: no vessel of {up.label}: {failure}",
                    [*at, "vessel"],
                    "give vessel.volume (and heated_area), or the dryer's cake_density",
                    [up.id],
                )
            if any(op.temperatures for op in up.operations):
                failed = True
                add(
                    "error",
                    "duration",
                    f"{up.id}: a jacket time needs a batch or semibatch unit, {up.label} holds "
                    "a dryer or filter",
                    [*at, "operations"],
                    "give the heat-up's or cool-down's duration",
                    [up.id],
                )
        elif (
            up.vessel is not None
            and not reacts
            and _stills(process, up)
            and not any(op.temperatures for op in up.operations)
        ):
            # a still's pot (ADR 0063): sized from what its steps take in, its metal heated
            # with the charge in the still's duty; no jacket check (no peak duty to remove)
            try:
                cake = _cake_vessel(process, recipe, up, case)
            except ValueError:
                add(
                    "error",
                    "duration",
                    f"{up.id}: no vessel of {up.label}: no volume of what its still takes in",
                    [*at, "vessel"],
                    "give vessel.volume, or the liquid_molar_volume of the still's charge",
                    [up.id],
                )
        elif up.vessel is not None or any(op.temperatures for op in up.operations):
            try:
                content = _content(process, recipe, up, case)
            except ValueError as failure:
                failed |= any(op.temperatures for op in up.operations)
                add(
                    "error",
                    "reference" if isinstance(failure, _Reference) else "duration",
                    f"{up.id}: no batch content of {up.label}: {failure}",
                    [*at, "vessel" if up.vessel is not None else "operations"],
                    "a vessel or a jacket time needs a batch or semibatch unit that solves, and "
                    "the batch-size stream's flow",
                    [up.id],
                )
        elif several is not None and any(
            getattr(getattr(node, "batch", None), "vent", None) is not None
            for node in _nodes(process, up)
        ):
            add(
                "error",
                "reference",
                f"{up.id}: no vent of {up.label}: {several}",
                [*at, "units" if many else "unit"],
                "name the vented batch or semibatch step as the unit procedure's unit:",
                [up.id],
            )
        solids_vessel = cake
        if content is not None and up.vessel is not None:
            found = _vessel(up, content)
            if any(solids):  # a filter or dryer in the reactor's vessel: its area, its plate
                try:
                    heated = _heated_area(process, recipe, up, case, found.diameter)
                except ValueError:
                    heated = None  # the dry operation says what is missing
                solids_vessel = replace(found, jacket_area=heated)
        dosed = False
        for j, op in enumerate(up.operations):
            dosed |= op.kind == "dose"
            if op.id in names:
                add(
                    "error",
                    "reference",
                    f"{up.id}: operation {op.id} twice",
                    [*at, "operations", j, "id"],
                    "one id each",
                )
            names.add(op.id)
            if op.temperatures is not None:
                if content is None:
                    continue
                before = not dosed and any(o.kind == "dose" for o in up.operations)
                try:
                    hours = _jacket_time(up, op, content, before_dose=before)
                except ValueError as failure:
                    failed = True
                    add(
                        "error",
                        "duration",
                        f"{up.id}.{op.id}: no {op.kind} time: {failure}",
                        [*at, "operations", j, "temperatures"],
                        "give vessel.jacket (u, the medium's temperature), or the duration",
                        [up.id],
                    )
                    continue
                ops.append((op, hours, "calculated"))
                if up.vessel is not None and up.vessel.metal_heat_capacity is not None:
                    # a vessel with its metal (ADR 0063): the heat of its heat-up or cool-down;
                    # a recipe without reports as in 1.9.0
                    result.heats.append(_jacket_heat(up, op, content, before, hours))
                continue
            if op.duration is not None:
                ops.append((op, op.duration.hours(), op.duration.provenance))
                continue
            try:
                if op.kind in ("dry", "filter"):
                    hours = _solids_time(process, recipe, op, solids_vessel, case)
                else:
                    hours = _duration_from(process, op.from_ or "", op.kind, case)
            except ValueError as failure:
                failed = True
                add(
                    "error",
                    "reference" if isinstance(failure, _Reference) else "duration",
                    f"{up.id}.{op.id}: no {op.kind} time from {op.from_}: {failure}",
                    [*at, "operations", j, "from"],
                    "from: names a dryer with drying_rate (and the vessel's heated area) or "
                    "drying_time; else give the duration"
                    if op.kind == "dry"
                    else "from: names a solid_separation with filtration (and its area or "
                    "the vessel); else give the duration"
                    if op.kind == "filter"
                    else "from: names a batch or semibatch step (a dose: a semibatch; a distil: a "
                    "still); else give the duration",
                    [up.id],
                )
                continue
            ops.append((op, hours, "calculated"))
        # when it starts in the batch
        begin = 0.0
        if up.start is not None:
            earlier = timeline.get(up.start.after)
            if earlier is None:
                add(
                    "error",
                    "reference",
                    f"{up.id}: start.after {up.start.after} is no earlier unit procedure",
                    [*at, "start", "after"],
                    "name a unit procedure listed before this one",
                    [up.id],
                )
            elif up.start.operation is None:
                begin = max(s.end for s in earlier)
            else:
                match = [s for s in earlier if s.operation == up.start.operation]
                if not match:
                    add(
                        "error",
                        "reference",
                        f"{up.id}: {up.start.after} has no operation {up.start.operation}",
                        [*at, "start", "operation"],
                        "name one of its operations",
                        [up.id],
                    )
                begin = match[0].start if match else max(s.end for s in earlier)
        elif k > 0:
            previous = timeline.get(recipe.unit_procedures[k - 1].id) or []
            transfer = [s for s in previous if s.kind == "transfer"]
            begin = transfer[0].start if transfer else max((s.end for s in previous), default=0)
        steps = []
        clock = begin
        for op, hours, basis in ops:
            steps.append(Step(up.id, up.label, op.id, op.kind, clock, clock + hours, basis))
            clock += hours
        timeline[up.id] = steps or [Step(up.id, up.label, "", "other", begin, begin, "")]
        result.steps += steps
        # one vessel, one occupancy: the operations of all its steps in turn
        occupancy = sum(h for _, h, _ in ops)
        result.units.append(
            UnitCycle(up.id, up.label, up.parallel, occupancy, occupancy / up.parallel)
        )
        if up.vessel is not None and found is not None:
            result.vessels.append(found)
            _vessel_findings(up, found, at, add)
        elif cake is not None:
            result.vessels.append(cake)
            _vessel_findings(up, cake, at, add, jacket=False)
        if (gas := _vent(process, recipe, up, case)) is not None:
            result.vents.append(gas)
        clock_end = max(clock_end, clock)
    if failed:
        return result
    slowest = max(result.units, key=lambda u: u.cycle)
    if slowest.cycle <= 0:
        add(
            "error", "duration", "the cycle time is zero", ["unit_procedures"], "give the durations"
        )
        return result
    result.cycle_time = slowest.cycle
    result.bottleneck = slowest.procedure
    result.batches_per_year = recipe.hours_per_year.value / slowest.cycle
    result.makespan = clock_end
    for u in result.units:
        u.utilisation = u.cycle / slowest.cycle
    for heat in result.heats:
        heat.year_average_kW = (
            heat.kJ * result.batches_per_year / recipe.hours_per_year.value / 3600.0
        )
    result.rate = size.value * (1000.0 if size.unit == "t" else 1.0) * result.batches_per_year
    result.rate /= recipe.hours_per_year.value
    if check_basis:
        _basis(process, recipe, result, case, add)
    return result


def _vessel_findings(
    up: UnitProcedure, found: VesselResult, at: list[Any], add: Any, jacket: bool = True
) -> None:
    """An overfilled given vessel; a jacket that cannot remove the peak duty (*jacket*: a
    reactor's vessel, not a dryer's)."""
    vessel = up.vessel
    if vessel.volume is not None and found.fill > vessel.fill_fraction * (1 + 1e-9):
        add(
            "warning",
            "vessel",
            f"{up.id}: {found.working_volume:.4g} m3 of batch in the {found.volume:g} m3 vessel "
            f"of {up.label}, {found.fill:.0%} full (fill fraction {vessel.fill_fraction:g})",
            [*at, "vessel", "volume"],
            "a larger vessel, a smaller batch or more parallel units",
            [up.id],
        )
    if not jacket:
        return
    if found.removable is not None and found.peak_duty is not None:
        if found.peak_duty > found.removable:
            add(
                "warning",
                "jacket",
                f"{up.id}: the peak duty {found.peak_duty:.4g} kW exceeds what the jacket removes "
                f"at the charge, {found.removable:.4g} kW (U A {found.jacket_area:.3g} m2 x "
                f"{found.process_temperature - (found.coolant_temperature or 0):.3g} K)",
                [*at, "vessel", "jacket"],
                "dose more slowly, a colder coolant, a coil or an external loop, or a smaller "
                "batch",
                [up.id],
            )
    elif vessel.jacket is not None and found.peak_duty is None:
        add(
            "info",
            "jacket",
            f"{up.id}: no jacket check: the model of {up.label} gives no peak duty (not "
            "isothermal, or no heat of reaction)",
            [*at, "vessel", "jacket"],
            "give the reactions' heat_of_reaction (an isothermal batch)",
            [up.id],
        )
    elif vessel.jacket is not None and found.peak_duty is not None:
        add(
            "info",
            "jacket",
            f"{up.id}: no jacket check without vessel.jacket.coolant_temperature",
            [*at, "vessel", "jacket"],
            "give the coolant's temperature",
            [up.id],
        )


def _basis(process: Any, recipe: Recipe, result: RecipeResult, case: str, add: Any) -> None:
    """The batch-size stream's flow in the flowsheet against the recipe's rate."""
    from chemeascode.domains.process.model import stream_flows

    size = recipe.batch_size
    at = ["batch_size", "stream"]
    stream = next((s for s in process.flowsheet.streams if s.id == size.stream), None)
    if stream is None:
        add(
            "error",
            "reference",
            f"batch_size.stream {size.stream} is no stream of the flowsheet",
            at,
            "name the stream the batch size is the amount of",
        )
        return
    flows = stream_flows(process, stream, case)
    unit = "m3/h" if size.unit == "m3" else "kg/h"
    if size.unit == "m3":
        volume = _volume_flow(process, flows.components)
        given = volume
    else:
        given = flows.total
    if given is None:
        add(
            "info",
            "basis",
            f"{size.stream}: no flow in case {case} to compare with the recipe's "
            f"{result.rate:.6g} {unit}",
            at,
            "give or propagate the stream's flow (and for m3 its components' liquid_molar_volume)",
            [size.stream],
        )
        return
    result.flowsheet_rate = given
    rate = result.rate or 0.0
    if abs(given - rate) > TOLERANCE * rate:
        fit = batch_for_rate(process, recipe, given, case)
        if fit.batch is not None and fit.cycle is not None:
            found = (
                f"; at the flowsheet's rate, a batch of {fit.batch:.6g} {size.unit} closes it "
                f"(cycle {fit.cycle:.4g} h at that batch: batch = rate x cycle, ADR 0070)"
            )
        elif fit.best_rate is not None and fit.best_batch is not None:
            found = (
                f"; no batch size makes the flowsheet's rate: the cycle grows about as fast as "
                f"the batch, and the batches tried made {fit.best_rate:.6g} {unit} at most (a "
                f"batch of {fit.best_batch:.6g} {size.unit}, ADR 0070)"
            )
        else:
            found = ""
        add(
            "warning",
            "basis",
            f"{size.stream}: {given:.6g} {unit} in the flowsheet (case {case}); the recipe gives "
            f"{size.value:g} {size.unit} x {result.batches_per_year:.6g} batches / "
            f"{recipe.hours_per_year.value:g} h = {rate:.6g} {unit}{found}",
            at,
            "scale the flowsheet's feeds to the recipe (a design specification, specs:), or "
            "change the batch size or the recipe: the balance, the LCI per kg and the TEA must "
            "share one basis",
            [size.stream],
        )


#: The batch size every batch model's hours of flows are taken from while
#: :func:`batch_for_rate` tries one (None: the recipe's).
_TRIAL_BATCH: ContextVar[float | None] = ContextVar("trial_batch", default=None)
#: Cycles :func:`batch_for_rate` evaluates at most.
BATCH_ITERATIONS = 16
#: :func:`batch_for_rate` closes ``batch = rate x cycle(batch)`` to this share of the batch.
BATCH_TOLERANCE = 1e-6
#: :func:`batch_for_rate`'s secant step stays within this factor of the batches tried.
BATCH_STEP = 2.0


@dataclass
class BatchFit:
    """The batch size that makes a rate (:func:`batch_for_rate`)."""

    #: The batch size (the recipe's unit) and its cycle (h); None when none was found.
    batch: float | None = None
    cycle: float | None = None
    #: The largest rate (kg/h, or m3/h) of the batch sizes tried, and that batch size: what
    #: the train makes at most, as far as the iterations saw, when no batch size was found.
    best_rate: float | None = None
    best_batch: float | None = None


def batch_for_rate(process: Any, recipe: Recipe, rate: float, case: str) -> BatchFit:
    """The batch size (the recipe's unit) whose cycle makes *rate* (kg/h, or m3/h for m3) of
    the batch-size stream, ``batch = rate x cycle(batch)``, and the cycle at it (ADR 0070). The
    cycle depends on the batch through the jacket and dosing times, a still's boil-up and a
    filter's or dryer's time, so the batch is solved by secant iterations on
    ``batch - rate x cycle(batch)`` from the recipe's batch size (one substitution first), every
    batch model's hours of flows taken from the batch tried. None found (:attr:`BatchFit.batch`)
    within :data:`BATCH_ITERATIONS` cycles: a unit whose time grows about as fast as its batch
    caps the train's rate below *rate*; :attr:`BatchFit.best_rate` is the most the batches tried
    made."""
    size = recipe.batch_size
    factor = 1000.0 if size.unit == "t" else 1.0
    fit = BatchFit()

    def residual(batch: float) -> tuple[float, float] | None:
        if batch <= 0:
            return None
        trial = recipe.model_copy(update={"batch_size": size.model_copy(update={"value": batch})})
        token = _TRIAL_BATCH.set(batch)
        try:
            found = evaluate(process, trial, None, case, check_basis=False)
        except ValueError:
            return None
        finally:
            _TRIAL_BATCH.reset(token)
        if not found.cycle_time or any(f.level == "error" for f in found.findings):
            return None
        made = batch * factor / found.cycle_time
        if fit.best_rate is None or made > fit.best_rate:
            fit.best_rate, fit.best_batch = made, batch
        return batch - rate * found.cycle_time / factor, found.cycle_time

    a = size.value
    first = residual(a)
    if first is None:
        return fit
    fa, cycle = first
    if abs(fa) <= BATCH_TOLERANCE * a:
        fit.batch, fit.cycle = a, cycle
        return fit
    b = rate * cycle / factor  # one substitution, then secants
    for _ in range(BATCH_ITERATIONS):
        second = residual(b)
        if second is None:
            return fit
        fb, cycle = second
        if abs(fb) <= BATCH_TOLERANCE * b:
            fit.batch, fit.cycle = b, cycle
            return fit
        if fb == fa:
            return fit
        # a secant step stays within a factor BATCH_STEP of the batches tried: an unbounded
        # one extrapolates far from the recipe's batch, to one its units cannot run (a still
        # that boils dry before a time end)
        step = b - fb * (b - a) / (fb - fa)
        a, fa, b = b, fb, min(max(step, min(a, b) / BATCH_STEP), BATCH_STEP * max(a, b))
    return fit


def _volume_flow(process: Any, components: dict[str, float] | None) -> float | None:
    """m3/h of a liquid of *components* (kg/h), ideal mixing; None without the data."""
    if components is None:
        return None
    comps = process.components()
    total = 0.0
    for n, kg in components.items():
        c = comps.get(n)
        if not kg:
            continue
        if not getattr(c, "molar_mass", None) or not getattr(c, "liquid_molar_volume", None):
            return None
        total += kg / c.molar_mass * c.liquid_molar_volume
    return total


def recipe_report(root: Path, case: str | None = None) -> RecipeResult | None:
    """The recipe of the plant at *root* evaluated (None without process/recipe.yaml); its
    schema and the process's load findings in ``findings``."""
    from chemeascode.domains.process.model import load

    process, found = load(Path(root))
    recipe, doc, schema = load_recipe(Path(root))
    if recipe is None:
        if not schema:
            return None
        empty = RecipeResult("", 0.0, "", "", 0.0)
        empty.findings = schema
        return empty
    if process is None:
        empty = RecipeResult(recipe.title, 0.0, "", "", 0.0)
        empty.findings = found
        return empty
    return evaluate(process, recipe, doc, case)


def rules(process: Any) -> list[Finding]:
    """The ``cheme.recipe-*`` findings of the plant's recipe (none without one)."""
    recipe, doc, found = load_recipe(process.root)
    if recipe is None:
        return found
    return found + evaluate(process, recipe, doc).findings


def recipe_text(result: RecipeResult) -> str:
    """The cycle as text: the plant's figures, then each unit and its operations."""
    lines = []
    if result.cycle_time is not None:
        lines.append(
            f"recipe{f' {result.title}' if result.title else ''}: batch {result.batch_size:g} "
            f"{result.batch_unit} of {result.stream}; cycle time {result.cycle_time:.4g} h "
            f"(bottleneck {result.bottleneck}), {result.batches_per_year:.4g} batches/a in "
            f"{result.hours_per_year:g} h; one batch takes {result.makespan:.4g} h"
        )
        unit = "m3/h" if result.batch_unit == "m3" else "kg/h"
        lines.append(
            f"  {result.stream}: {result.rate:.6g} {unit} averaged over the year"
            + (
                f" (flowsheet: {result.flowsheet_rate:.6g} {unit})"
                if result.flowsheet_rate is not None
                else ""
            )
        )
    for u in result.units:
        lines.append(
            f"  {u.procedure} on {u.unit}"
            + (f" (x{u.parallel})" if u.parallel > 1 else "")
            + f": occupied {u.occupancy:.4g} h per batch, cycle {u.cycle:.4g} h"
            + (f", utilisation {u.utilisation:.0%}" if result.cycle_time else "")
        )
        for s in result.steps:
            if s.procedure == u.procedure:
                lines.append(
                    f"    {s.operation} ({s.kind}) {s.start:.4g}-{s.end:.4g} h"
                    + (" (from the model)" if s.basis == "calculated" else "")
                )
    for v in result.vessels:
        held = (
            f"{v.working_volume:.4g} m3 of batch in "
            if v.working_volume
            else "batch volume not known, "
        )
        fill = f"{v.fill:.0%} full" if v.working_volume else "fill not known"
        lines.append(
            f"  vessel of {v.unit} ({v.procedure}): {held}"
            f"{v.volume:.4g} m3{' (preferred size)' if v.rounded else ''}, {fill}, "
            f"D {v.diameter:.3g} m"
            + (
                f"; peak duty {v.peak_duty:.4g} kW, jacket removes {v.removable:.4g} kW "
                f"({v.jacket_area:.3g} m2 at the charge)"
                if v.removable is not None and v.peak_duty is not None
                else f"; heated area {v.jacket_area:.3g} m2"
                if v.jacket_area is not None and v.coolant_temperature is None and _dries(result, v)
                else ""
            )
        )
    for q in result.heats:
        lines.append(
            f"  {'heat-up' if q.kind == 'heat' else 'cool-down'} {q.operation} of {q.unit} "
            f"({q.procedure}) {q.temperatures[0]:.5g} -> {q.temperatures[1]:.5g} K: "
            f"{q.kJ / 1000:.4g} MJ per batch"
            + (
                f" (content {q.content_kJ / 1000:.4g}, vessel metal {q.metal_kJ / 1000:.4g} MJ)"
                if q.metal_kJ
                else ""
            )
            + (f", {q.mean_kW:.4g} kW over {q.hours:.3g} h" if q.mean_kW is not None else "")
            + (
                f", year average {q.year_average_kW:.4g} kW"
                if q.year_average_kW is not None
                else ""
            )
        )
    for g in result.vents:
        lines.append(
            f"  vent of {g.unit} ({g.procedure}) by {g.stream}: peak {g.peak_rate:.4g} kmol/s "
            f"({g.peak_volume_flow:.4g} m3/h at {g.temperature:.5g} K, {g.pressure:.5g} kPa)"
            + (f" at {g.peak_time / 3600:.4g} h" if g.peak_time is not None else "")
            + f"; {g.kg:.4g} kg per batch ("
            + ", ".join(f"{n} {v:.4g} kmol" for n, v in g.kmol.items())
            + ")"
        )
    lines += [f.format() for f in result.findings]
    if not lines:
        lines.append("no recipe (process/recipe.yaml)")
    return "\n".join(lines)


def _dries(result: RecipeResult, vessel: VesselResult) -> bool:
    """Whether *vessel*'s unit procedure dries or filters (a filter-dryer's vessel)."""
    return any(
        s.procedure == vessel.procedure and s.kind in ("dry", "filter") for s in result.steps
    )


#: Bar colours (light, dark) by operation kind: the reaction warm, the work-up cool, the
#: rest neutral.
_KINDS = {
    "charge": ("#7c8aa3", "#9aa8c2"),
    "heat": ("#c46a3a", "#e08a5a"),
    "dose": ("#b8452f", "#e0664f"),
    "react": ("#8f2f3a", "#d05a66"),
    "cool": ("#3a7ca5", "#64a6cf"),
    "transfer": ("#6b6b66", "#a3a29b"),
    "distil": ("#2f7f8a", "#5ab0bb"),
    "filter": ("#4b8a5c", "#73b384"),
    "dry": ("#a38a3a", "#cdb25e"),
    "clean": ("#8a6fa8", "#b29ad0"),
    "hold": ("#b5b3ab", "#5a5954"),
    "other": ("#9a9890", "#77766f"),
}


def gantt_svg(result: RecipeResult) -> str:
    """One batch as a Gantt chart: a row per unit procedure, a bar per operation (coloured by
    kind, its times in the tooltip), the bottleneck marked. Light and dark
    (prefers-color-scheme)."""
    from html import escape

    def label(u: UnitCycle) -> str:
        return f"{u.procedure} ({u.unit})" + (f" x{u.parallel}" if u.parallel > 1 else "")

    # the label column fits the longest name (11 px semibold, capitals and digits about 7 px
    # each; a units: list joined with +)
    longest = max((len(label(u)) for u in result.units), default=0)
    left, top, row, right = max(170, 12 + 7 * longest), 46, 30, 30
    width = 760 + left - 170
    span = max((s.end for s in result.steps), default=1.0) or 1.0
    scale = (width - left - right) / span

    def x(hours: float) -> float:
        return left + hours * scale

    def colours(column: int, indent: str) -> str:
        return "\n".join(
            f"{indent}.bar.{kind} {{ fill: {pair[column]}; }}" for kind, pair in _KINDS.items()
        )

    height = top + row * len(result.units) + 60
    style = f"""<style>
  svg {{ background: #fcfcfb; font-family: system-ui, sans-serif; }}
  .title {{ font-size: 13px; font-weight: 600; fill: #0b0b0b; }}
  .label, .legend {{ font-size: 11px; fill: #52514e; }}
  .tick {{ font-size: 10px; fill: #52514e; }}
  .grid {{ stroke: #e5e4e0; stroke-width: 1; }}
  .bar {{ stroke: #fcfcfb; stroke-width: 1; }}
  .neck {{ font-weight: 600; fill: #0b0b0b; }}
{colours(0, "  ")}
  @media (prefers-color-scheme: dark) {{
    svg {{ background: #1a1a19; }}
    .title, .neck {{ fill: #f0efec; }}
    .label, .legend, .tick {{ fill: #c3c2b7; }}
    .grid {{ stroke: #33332f; }}
    .bar {{ stroke: #1a1a19; }}
{colours(1, "    ")}
  }}
</style>"""
    body = []
    heading = f"One batch: {result.makespan or span:.3g} h"
    if result.cycle_time is not None:
        heading += (
            f"; cycle time {result.cycle_time:.3g} h (bottleneck {result.bottleneck}), "
            f"{result.batches_per_year:.4g} batches/a"
        )
    body.append(f'<text class="title" x="{left}" y="20">{escape(heading)}</text>')
    ticks = _ticks(span)
    bottom = top + row * len(result.units)
    for t in ticks:
        body.append(
            f'<line class="grid" x1="{x(t):.1f}" x2="{x(t):.1f}" y1="{top - 6}" y2="{bottom}"/>'
        )
        body.append(
            f'<text class="tick" x="{x(t):.1f}" y="{bottom + 14}" text-anchor="middle">{t:g}</text>'
        )
    body.append(
        f'<text class="label" x="{(left + width - right) / 2:.0f}" y="{bottom + 30}" '
        'text-anchor="middle">h from the start of the batch</text>'
    )
    for i, u in enumerate(result.units):
        y = top + row * i
        name = label(u)
        css = "label neck" if u.procedure == result.bottleneck else "label"
        body.append(
            f'<text class="{css}" x="{left - 8}" y="{y + row / 2 + 4:.0f}" '
            f'text-anchor="end">{escape(name)}</text>'
        )
        for s in (s for s in result.steps if s.procedure == u.procedure):
            w = max((s.end - s.start) * scale, 0.5)
            tip = f"{u.procedure} {s.operation} ({s.kind}): {s.start:.3g} to {s.end:.3g} h"
            if s.basis == "calculated":
                tip += ", from the model"
            body.append(
                f'<rect class="bar {s.kind}" x="{x(s.start):.1f}" y="{y + 4}" width="{w:.1f}" '
                f'height="{row - 8}"><title>{escape(tip)}</title></rect>'
            )
    kinds = list(dict.fromkeys(s.kind for s in result.steps))
    lx = left
    for kind in kinds:
        body.append(f'<rect class="bar {kind}" x="{lx}" y="{bottom + 40}" width="12" height="10"/>')
        body.append(f'<text class="legend" x="{lx + 16}" y="{bottom + 49}">{kind}</text>')
        lx += 22 + 7 * len(kind)
    total = max(width, lx + 20)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total} {height}" '
        f'width="{total}" height="{height}" role="img">'
        f"<title>{escape(heading)}</title>\n{style}\n" + "\n".join(body) + "\n</svg>\n"
    )


def _ticks(span: float) -> list[float]:
    """Round tick positions from 0 to *span* h, about 6 of them."""
    raw = span / 6
    step = next(s for s in (0.25, 0.5, 1, 2, 4, 6, 12, 24, 48, 96, 1e9) if s >= raw)
    count = int(span / step + 1e-9)
    return [k * step for k in range(count + 1)]
