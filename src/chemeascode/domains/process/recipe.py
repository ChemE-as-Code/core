"""Schema ``cheme/recipe/v1`` (``process/recipe.yaml``): the batch basis and recipe of a batch
plant, and the cycle it gives (``cheme process recipe``).

A batch plant's flowsheet holds its rates averaged over the operating year: a stream's kg/h is
the amount one batch makes of it times the batches per year over the hours. The recipe says what
that rests on:

- ``batch_size``: the amount of one stream per batch (kg, t or m3; m3 from the liquid's molar
  volumes, ideal mixing);
- ``hours_per_year`` the batches fit in;
- the unit procedures (ISA-88 names only, no S88 model): per unit (a flowsheet block or step),
  how many run in parallel and its ordered operations (charge, heat, dose, react, cool,
  transfer, filter, dry, clean, hold, other), each with its ``duration`` or, for ``dose`` and
  ``react``, ``from:`` the step's batch or semi-batch model (its dosing time, its reaction time;
  :mod:`.stirred_tank`).

A unit procedure on a batch or semi-batch step may size its ``vessel``: the batch's largest
content (the model's volume per hour of flows times the hours of flows one batch makes, batch
size / the flowsheet's rate of the batch-size stream) over the fill fraction, rounded up to the
R10 preferred numbers (ISO 3) of m3, or a given volume; its ``jacket`` (U, area or the wetted
shell and flat bottom of a vessel of the given aspect ratio, the media's temperatures) is checked
against the model's peak duty, and a ``heat`` or ``cool`` operation may give ``temperatures``
instead of a duration: ``t = C / (U A) ln((T_m - T_0) / (T_m - T_1))`` with the medium at a
constant temperature, the content's heat capacity C (the charge's before a dose, else the
end's).

Derived (:func:`evaluate`): each unit's occupancy per batch, its cycle (occupancy over its
parallel units), the plant's cycle time (the slowest unit: the bottleneck), the batches per
year (hours over cycle time), each unit's utilisation, one batch's timeline from start to end
(a unit procedure starts when the previous one starts its ``transfer``, else when it ends; or
at its own ``start``) and the rate of the batch-size stream that follows. :func:`gantt_svg`
draws one batch.

Rules (``cheme.recipe-*``), each finding naming the file, line, rule and a hint:

- ``recipe-schema``: the file does not follow ``cheme/recipe/v1``;
- ``recipe-reference``: a unit, stream or ``from:`` step that is not in the flowsheet, a
  ``from:`` on a step that is no batch or semi-batch, a ``dose`` from a step without dosing,
  a ``start.after`` that is no earlier unit procedure, a duplicate id;
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
from dataclasses import asdict, dataclass, field
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
OPERATIONS = (
    "charge",
    "heat",
    "dose",
    "react",
    "cool",
    "transfer",
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
        "duration (its dosing time; its reaction time, the post-reaction of a semi-batch).",
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
        if self.from_ is not None and self.kind not in ("dose", "react"):
            raise ValueError(
                f"operation {self.id}: from: gives a dose's or a reaction's time only; give "
                "the duration of a " + self.kind
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
    """A unit's vessel, sized from its batch volume (the unit's batch or semi-batch model):
    the working volume over the fill fraction, rounded up to a preferred size."""

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
    jacket: Jacket | None = None
    provenance: Provenance
    source: str = ""


class UnitProcedure(Strict):
    """What one unit (a flowsheet block or step) does per batch."""

    id: str
    unit: str = Field(description="The flowsheet block or step.")
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
        "semibatch step).",
    )


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


def _content(process: Any, recipe: Recipe, up: UnitProcedure, case: str) -> _Content:
    """The batch content of unit procedure *up*'s unit, a batch or semibatch step: its model's
    figures (per hour of the flowsheet's flows) times the hours of flows one batch makes,
    batch size / the flowsheet's rate of the batch-size stream. Raises ValueError."""
    from chemeascode.domains.process.model import stream_flows
    from chemeascode.domains.process.stirred_tank import (
        solve_node,
        split_inlets,
        stream_moles,
        tank_inlet,
    )

    node = process.nodes.get(up.unit)
    model = getattr(node, "reactor", None)
    if model not in ("batch", "semibatch") or node.batch is None:
        raise _Reference(f"{up.unit} is no batch or semibatch: no batch content to size")
    size = recipe.batch_size
    stream = next((x for x in process.flowsheet.streams if x.id == size.stream), None)
    flows = stream_flows(process, stream, case) if stream is not None else None
    rate = None
    if flows is not None:
        rate = _volume_flow(process, flows.components) if size.unit == "m3" else flows.total
    if not rate:
        raise ValueError(f"no flow of {size.stream}: the batch's hours of flows are not known")
    hours = size.value * (1000.0 if size.unit == "t" else 1.0) / rate
    inlets = [
        s for s in process.flowsheet.streams if (e := process.ends(s)[1]) and e.node == up.unit
    ]
    inlet = tank_inlet(node, inlets)
    solved, _ = solve_node(process, node, inlet, case)
    charge = split_inlets(node, inlets)[0] if model == "semibatch" else inlet
    comps = process.components()

    def capacity(moles: dict[str, float]) -> float | None:
        cps = [(v, getattr(comps.get(n), "liquid_heat_capacity", None)) for n, v in moles.items()]
        if any(v > 0 and not cp for v, cp in cps):
            return None
        return sum(v * (cp or 0.0) for v, cp in cps) * hours

    charged, _, _ = stream_moles(process, charge, case)
    end_volume = (solved.volume or 0.0) * hours
    charge_volume = (solved.charge_volume or solved.volume or 0.0) * hours
    if node.batch.heat != "isothermal":
        peak = None
    elif model == "semibatch":
        peak = (solved.peak_cooling_duty or 0.0) * end_volume
    else:
        peak = (solved.peak_heat_rate or 0.0) * end_volume
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
        up.unit,
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
    volume = content.charge_volume if before_dose else content.end_volume
    diameter = _diameter(_vessel(up, content).volume, up.vessel.aspect_ratio)
    area = jacket.area or wetted_area(volume, diameter)
    ua = jacket.u * area / 1000.0  # kW/K
    return capacity / ua * math.log((medium - start) / (medium - end)) / 3600.0


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
    findings: list[Finding] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        found = asdict(self)
        found["findings"] = [f.format() for f in self.findings]
        return found


def load_recipe(root: Path) -> tuple[Recipe | None, Any, list[Finding]]:
    """process/recipe.yaml: its model, YAML nodes and schema findings (None without it)."""
    from chemeascode.domains.process.model import _load_optional

    return _load_optional(root, RECIPE_FILE, Recipe, SCHEMA, "cheme.recipe-schema", "recipe")


class _Reference(ValueError):
    """A ``from:`` that names no step whose model gives the duration."""


def _duration_from(process: Any, step_id: str, kind: str, case: str) -> float:
    """h: the dosing time (dose) or reaction time (react) of batch or semi-batch *step_id*.
    Raises _Reference, or ValueError (TankError) when the model does not solve."""
    from chemeascode.domains.process.stirred_tank import solve_node, tank_inlet

    node = process.nodes.get(step_id)
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
    process: Any, recipe: Recipe, doc: Any = None, case: str | None = None
) -> RecipeResult:
    """The cycle of *recipe* on *process* in *case* (default: the default case) with its
    ``cheme.recipe-*`` findings (see the module docstring)."""
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
    timeline: dict[str, list[Step]] = {}
    clock_end = 0.0
    failed = False
    for k, up in enumerate(recipe.unit_procedures):
        at = ["unit_procedures", k]
        if up.id in seen:
            add("error", "reference", f"unit procedure {up.id} twice", [*at, "id"], "one id each")
        seen.add(up.id)
        if process.kinds.get(up.unit) not in ("block", "step"):
            add(
                "error",
                "reference",
                f"{up.id}: unit {up.unit} is no block or step of the flowsheet",
                [*at, "unit"],
                "name the flowsheet block or step the unit procedure runs in",
                [up.id],
            )
        ops: list[tuple[Operation, float, str]] = []
        names: set[str] = set()
        content: _Content | None = None
        if up.vessel is not None or any(op.temperatures for op in up.operations):
            try:
                content = _content(process, recipe, up, case)
            except ValueError as failure:
                failed |= any(op.temperatures for op in up.operations)
                add(
                    "error",
                    "reference" if isinstance(failure, _Reference) else "duration",
                    f"{up.id}: no batch content of {up.unit}: {failure}",
                    [*at, "vessel" if up.vessel is not None else "operations"],
                    "a vessel or a jacket time needs a batch or semibatch unit that solves, and "
                    "the batch-size stream's flow",
                    [up.id],
                )
        dosed = False
        for j, op in enumerate(up.operations):
            dosed |= op.kind == "dose"
            if op.temperatures is not None:
                if content is None:
                    continue
                try:
                    hours = _jacket_time(
                        up,
                        op,
                        content,
                        before_dose=not dosed and any(o.kind == "dose" for o in up.operations),
                    )
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
                continue
            if op.id in names:
                add(
                    "error",
                    "reference",
                    f"{up.id}: operation {op.id} twice",
                    [*at, "operations", j, "id"],
                    "one id each",
                )
            names.add(op.id)
            if op.duration is not None:
                ops.append((op, op.duration.hours(), op.duration.provenance))
                continue
            try:
                hours = _duration_from(process, op.from_ or "", op.kind, case)
            except ValueError as failure:
                failed = True
                add(
                    "error",
                    "reference" if isinstance(failure, _Reference) else "duration",
                    f"{up.id}.{op.id}: no {op.kind} time from {op.from_}: {failure}",
                    [*at, "operations", j, "from"],
                    "from: names a batch or semibatch step (a dose: a semibatch); else give "
                    "the duration",
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
            steps.append(Step(up.id, up.unit, op.id, op.kind, clock, clock + hours, basis))
            clock += hours
        timeline[up.id] = steps or [Step(up.id, up.unit, "", "other", begin, begin, "")]
        result.steps += steps
        occupancy = sum(h for _, h, _ in ops)
        result.units.append(
            UnitCycle(up.id, up.unit, up.parallel, occupancy, occupancy / up.parallel)
        )
        if up.vessel is not None and content is not None:
            found = _vessel(up, content)
            result.vessels.append(found)
            _vessel_findings(up, found, at, add)
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
    result.rate = size.value * (1000.0 if size.unit == "t" else 1.0) * result.batches_per_year
    result.rate /= recipe.hours_per_year.value
    _basis(process, recipe, result, case, add)
    return result


def _vessel_findings(up: UnitProcedure, found: VesselResult, at: list[Any], add: Any) -> None:
    """An overfilled given vessel; a jacket that cannot remove the peak duty."""
    vessel = up.vessel
    if vessel.volume is not None and found.fill > vessel.fill_fraction * (1 + 1e-9):
        add(
            "warning",
            "vessel",
            f"{up.id}: {found.working_volume:.4g} m3 of batch in the {found.volume:g} m3 vessel "
            f"of {up.unit}, {found.fill:.0%} full (fill fraction {vessel.fill_fraction:g})",
            [*at, "vessel", "volume"],
            "a larger vessel, a smaller batch or more parallel units",
            [up.id],
        )
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
        add(
            "warning",
            "basis",
            f"{size.stream}: {given:.6g} {unit} in the flowsheet (case {case}); the recipe gives "
            f"{size.value:g} {size.unit} x {result.batches_per_year:.6g} batches / "
            f"{recipe.hours_per_year.value:g} h = {rate:.6g} {unit}",
            at,
            "scale the flowsheet's feeds to the recipe, or change the batch size or the "
            "recipe: the balance, the LCI per kg and the TEA must share one basis",
            [size.stream],
        )


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
        lines.append(
            f"  vessel of {v.unit} ({v.procedure}): {v.working_volume:.4g} m3 of batch in "
            f"{v.volume:.4g} m3{' (preferred size)' if v.rounded else ''}, {v.fill:.0%} full, "
            f"D {v.diameter:.3g} m"
            + (
                f"; peak duty {v.peak_duty:.4g} kW, jacket removes {v.removable:.4g} kW "
                f"({v.jacket_area:.3g} m2 at the charge)"
                if v.removable is not None and v.peak_duty is not None
                else ""
            )
        )
    lines += [f.format() for f in result.findings]
    if not lines:
        lines.append("no recipe (process/recipe.yaml)")
    return "\n".join(lines)


#: Bar colours (light, dark) by operation kind: the reaction warm, the work-up cool, the
#: rest neutral.
_KINDS = {
    "charge": ("#7c8aa3", "#9aa8c2"),
    "heat": ("#c46a3a", "#e08a5a"),
    "dose": ("#b8452f", "#e0664f"),
    "react": ("#8f2f3a", "#d05a66"),
    "cool": ("#3a7ca5", "#64a6cf"),
    "transfer": ("#6b6b66", "#a3a29b"),
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

    left, top, row, right = 170, 46, 30, 30
    width = 760
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
        name = f"{u.procedure} ({u.unit})" + (f" x{u.parallel}" if u.parallel > 1 else "")
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
