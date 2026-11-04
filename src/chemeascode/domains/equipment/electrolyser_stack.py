"""Electrolyser stacks sized from a cell's operating point for a product duty, and the skid
equipment inputs from a dynamic duty (``cheme process stack``).

The optional ``stacks:`` section of ``process/cells.yaml`` (schema
``cheme/electrochemical-cells/v1``; its models live with the file's in
:mod:`chemeascode.domains.process.electrochemical_cell`) names, per stack design, a cell of the
same file, the product duty at the skid boundary, the electrical limits, the assumed stack
envelope, access clearances, the replacement interval and the skid equipment a duty of
``process/duties.yaml`` sizes. :func:`stack_report` evaluates each (model :data:`MODEL`):

- the cell's operating point from
  :func:`~chemeascode.domains.process.electrochemical_cell.cell_report`: the current density
  ``j = I / A_cell``, the voltage ``U`` and the Faradaic efficiency ``FE`` of the product (a
  measured cell's looked up at ``j`` and refused outside its validity range; a specified cell
  outside its declared operating range is not sized on): nothing is extrapolated;
- the total active area ``A = n F Ndot / (nu FE j)`` for the product duty ``Ndot`` (mol/s),
  ``nu`` the product's coefficient and ``n`` the electrons per extent of the cell's reaction;
  the cells required ``ceil(A / A_cell)``;
- at most ``floor(U_max / U)`` cells in series per stack, the stacks
  ``ceil(cells / that)``, the cells shared evenly (``ceil(cells / stacks)`` per stack): the
  cells of a stack in series, the stacks in parallel on the DC bus;
- the reconciled stack voltage (cells x ``U``) and current (the cell's ``I``), the bus current,
  the DC power ``P = sum N U I``, the AC power over a stated rectifier efficiency, the
  rectifiers for a stated rectifier current, the product output of the integer arrangement
  (never below the duty) with its margin, the electricity per kg of product (all the DC power)
  and the heat to remove (the cell's ``Q`` per cell times the cells);
- the stack envelope ``L x W x H`` from the cells per stack and the assumed cell pitch, end
  plates and frame margin around a square active area; the footprint with the access
  clearances; the cells replaced per interval and per year;
- with ``equipment:``, the duty named, run at the sized arrangement (the cells per stack in
  series, the stacks on its one reservoir;
  :func:`~chemeascode.domains.process.electrolysis_duty.run_duty`) over its horizon, the
  campaign: the reservoir's working volume (the largest over the duty) with the stated margin
  as a vertical cylinder of the stated H/D; the recirculation pump's flow (the anolyte flow per
  active area or per cell times the cells) as a mass flow at the anolyte density, with the
  suction and discharge pressures from the reservoir pressure and the stack's pressure drop: the
  inputs of the existing pump sizing (``cheme datasheets fill``,
  :func:`~chemeascode.domains.equipment.pumps.size_pump`); the dosing pump's capacity (the
  duty's dosing rate times one plus the margin); the dosing tank (the solution dosed over the
  campaign, with the margin) and the bleed tank (the bleed over the campaign).

Every value carries its provenance (``given``, ``assumed``, ``calculated``, or ``tbd`` with the
reason) and its source. The equipment inputs go where the existing tools read them: the
equipment-list ``dimensions`` of the stacks' and tanks' tags (with ``source``, ``assumed`` and
``fingerprint``), from which ``cheme layout build`` shapes the 3D model and ``cheme datasheets
draft`` and ``fill`` take the main dimensions
(:func:`~chemeascode.domains.equipment.outline.derived_dimensions`); the pumps' datasheet
``type_specific`` parameters the pump fill reads. :func:`write_stack_inputs` (``--write``)
writes a value only where it is missing, TBD or written by this tool before (its source
starts with :data:`STACK_MARK`), never over one written by hand.

Rules (``cheme.stack-*``), each finding naming the file, line, rule and a hint:

- ``stack-schema`` (error): a unit a quantity does not take, a duplicate stack id, a value out
  of its range (a margin below 0, an H/D or a duty not above 0);
- ``stack-cell`` (error, the stack is refused): the cell is not in the file, its Faraday
  balance refuses it (outside the measured range among others), it has no active area, its
  reaction does not form the product or the product has no molar mass, or a specified cell lies
  outside its declared operating range; (info) a specified cell declares no current density
  range; (warning) the cell has other warnings;
- ``stack-electrical`` (error, refused): the cell voltage is above the stack voltage limit, or
  the cell current above the stack current limit;
- ``stack-envelope`` (info): an envelope value is missing: the stack's dimensions stay TBD;
- ``stack-input-missing`` (info): an equipment input is missing: that value stays TBD;
- ``stack-unsourced`` (info): an assumed input without a source;
- ``stack-tags`` (warning): fewer or more tags than stacks, or a tag not in the equipment list;
- ``stack-duty`` (error): the duty is not in ``process/duties.yaml``, is refused, or is not
  feasible at the sized arrangement over its horizon (the equipment inputs from it are not
  given); (warning) the duty runs the cell at another current density than the stack; (info)
  the duty states another arrangement, replaced by the sized one;
- ``stack-outdated`` (warning): an equipment-list dimension or datasheet input this tool would
  write differs from the file (or is not there): ``cheme process stack --write``;
- ``stack-kept`` (warning): a value written by hand differs from the calculated one: kept;
- ``stack-target`` (info): an equipment-list item or datasheet the value would go to does not
  exist.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from chemeascode.domains.process.electrochemical_cell import (
    CELLS_FILE,
    FARADAY,
    Quantity,
    SkidTank,
    Stack,
)
from chemeascode.foundation.findings import Finding
from chemeascode.foundation.yamlsource import _yaml_line

#: The model this module evaluates, as recorded with every result.
MODEL = {"id": "electrolyser-stack", "version": 1, "section": f"{CELLS_FILE} stacks"}
#: The start of the source of every value this tool writes (and may rewrite).
STACK_MARK = "cheme process stack"
EQUIPMENT_LIST = "equipment/equipment-list.yaml"
DATASHEET_DIR = "equipment/datasheets"

ASSUMPTIONS = (
    "the plant cell runs at the operating point of process/cells.yaml (its current density, "
    "voltage and Faradaic efficiency; a measured cell's looked up there, never extrapolated): "
    "every cell of every stack alike, no ageing, no shunt currents between cells",
    "Faraday's law: A = n F Ndot / (nu FE j), F = 96485.33212 C/mol; the cells of a stack in "
    "series (one current), the stacks in parallel on the DC bus (one voltage)",
    "the cells are shared evenly between the stacks: ceil(cells required / stacks) per stack, "
    "so the integer arrangement makes at least the duty",
    "the stack envelope is the cells' pitch plus the end plates along the axis, and a square "
    "active area plus the frame margin on each side across it (the assumed envelope, not the "
    "vendor's drawing)",
    "a tank is a vertical cylinder of the stated H/D holding the working volume plus the margin "
    "(flat ends: heads, wall thickness and supports are not added)",
    "the duty's horizon is the campaign: the reservoir's working volume is the largest over it, "
    "the dosing and bleed tanks hold what is dosed and bled over it",
)
LIMITATIONS = (
    "the stack voltage counts the cells only: busbars, end-plate contact and cable losses are "
    "not added; the rectifier is an efficiency, not a design",
    "the anolyte flow per area or per cell is a declared value (the measured series states "
    "none); the pump head is the stack's declared pressure drop, the routed lines are added by "
    "the pump sizing",
    "the stack envelope, clearances and replacement interval are declared (assumed) values, not "
    "a vendor's; a tank's outline is its working volume's cylinder",
    "no hazardous area, gas handling (H2, CO) or venting of the stacks is sized here",
)

_RATE_MASS = {"kg/h": 1.0, "g/h": 1e-3, "kg/d": 1 / 24, "t/d": 1000 / 24, "t/h": 1000.0}
_RATE_MOLAR = {"mol/s": 1.0, "mol/h": 1 / 3600, "kmol/h": 1000 / 3600}
_VOLTAGE = {"V": 1.0, "mV": 1e-3, "kV": 1e3}
_CURRENT = {"A": 1.0, "kA": 1e3, "mA": 1e-3}
_LENGTH = {"mm": 1e-3, "cm": 1e-2, "m": 1.0}
_HOURS = {"h": 1.0, "d": 24.0, "kh": 1000.0}
_HOURS_PER_YEAR = {"h": 1.0, "h/a": 1.0, "h/y": 1.0, "h/yr": 1.0}
_FRACTION = {None: 1.0, "-": 1.0, "1": 1.0, "%": 0.01}
_DENSITY = {"kg/m3": 1.0, "kg/L": 1000.0, "g/mL": 1000.0, "g/cm3": 1000.0}
_VISCOSITY = {"mPa s": 1.0, "mPa.s": 1.0, "cP": 1.0, "Pa s": 1000.0, "Pa.s": 1000.0}
_PRESSURE = {
    "kPa": 1.0,
    "kPa(a)": 1.0,
    "bar": 100.0,
    "bar(a)": 100.0,
    "bara": 100.0,
    "Pa": 1e-3,
    "MPa": 1000.0,
    "atm": 101.325,
}
_PRESSURE_DROP = {"kPa": 1.0, "bar": 100.0, "mbar": 0.1, "Pa": 1e-3}
#: to L/h per cell
_FLOW_CELL = {"mL/min": 0.06, "L/min": 60.0, "L/h": 1.0, "mL/h": 1e-3, "m3/h": 1000.0}
#: to L/h per m2 of active area
_FLOW_AREA = {
    "mL/(min cm2)": 600.0,
    "mL/min/cm2": 600.0,
    "L/(h m2)": 1.0,
    "L/h/m2": 1.0,
    "L/(min m2)": 60.0,
    "m3/(h m2)": 1000.0,
}
#: the duty's flow units (process/duties.yaml), to L/h
_DUTY_FLOW = {"L/s": 3600.0, "L/min": 60.0, "L/h": 1.0, "mL/min": 0.06, "mL/h": 1e-3}
_DUTY_FLOW["m3/h"] = 1000.0
_DUTY_DENSITY = {"kg/L": 1.0, "g/mL": 1.0, "kg/m3": 1e-3}
#: Dimension keys an equipment-list item keeps when this tool rewrites its sizes.
_KEEP = ("head", "support", "weight", "lift_weight", "orientation", "variant")
#: The size keys this tool writes into equipment-list dimensions.
_SIZE_KEYS = ("diameter", "height", "length", "width", "depth")
_TOL = 1e-9


# -- results ------------------------------------------------------------------------------------


@dataclass
class Sized:
    """One value with its unit, provenance (``given``, ``assumed``, ``calculated``, ``tbd``) and
    source (for ``tbd``: the reason); ``assumed`` when an input it rests on is assumed."""

    value: Any
    unit: str
    provenance: str
    source: str
    assumed: bool = False

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class CellPoint:
    """What the sizing takes from the cell, per cell at its operating point."""

    cell: str
    performance: str
    current_a: float
    current_density_a_m2: float
    area_m2: float
    voltage_v: float
    faradaic_efficiency: float
    electrons: float
    coefficient: float
    molar_mass: float  # kg/kmol
    heat_kw: float | None = None
    measurement: dict[str, Any] | None = None
    sources: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class EquipmentInput:
    """What one equipment-list item or datasheet gets: ``target`` ``dimensions`` (the item's
    equipment-list sizes) or ``type_specific`` (its datasheet's parameters). ``values`` maps
    each key to its :class:`Sized`; a TBD value is not written. ``status`` (after the files
    were compared): ``current``, ``outdated``, ``kept`` (written by hand), ``no-target``,
    ``tbd`` (nothing to write), ``written``."""

    tag: str
    role: str
    target: str
    file: str
    values: dict[str, Sized] = field(default_factory=dict)
    source: str = ""
    assumed: bool = False
    fingerprint: str | None = None
    status: str = ""
    detail: str = ""

    @property
    def complete(self) -> bool:
        return bool(self.values) and all(v.provenance != "tbd" for v in self.values.values())

    def as_dict(self) -> dict[str, Any]:
        data = dict(self.__dict__)
        data["values"] = {k: v.as_dict() for k, v in self.values.items()}
        return data


@dataclass
class StackResult:
    """One stack design; ``refused`` when an input it needs is missing (no numbers then)."""

    id: str
    cell: str
    line: int | None = None
    title: str = ""
    refused: bool = False
    reasons: list[str] = field(default_factory=list)
    point: CellPoint | None = None
    #: the product duty, the arrangement, power, output, envelope, replacements
    values: dict[str, Sized] = field(default_factory=dict)
    arrangement: str = ""
    #: the duty the equipment inputs come from: id, run fingerprint, ended, feasible, campaign
    duty: dict[str, Any] | None = None
    equipment: list[EquipmentInput] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)

    def number(self, key: str) -> Any:
        found = self.values.get(key)
        return found.value if found is not None and found.provenance != "tbd" else None

    def as_dict(self) -> dict[str, Any]:
        data = dict(self.__dict__)
        data["point"] = self.point.as_dict() if self.point is not None else None
        data["values"] = {k: v.as_dict() for k, v in self.values.items()}
        data["equipment"] = [e.as_dict() for e in self.equipment]
        return data


@dataclass
class StackReport:
    stacks: list[StackResult]
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
            "stacks": [s.as_dict() for s in self.stacks],
            "findings": [finding_dict(f) for f in self.findings],
            "source": self.source.as_dict() if self.source is not None else None,
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), indent=2)


@dataclass
class WriteResult:
    """What :func:`write_stack_inputs` wrote: the files, and per file the tags."""

    written: dict[str, list[str]] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)


def _version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("cheme-as-code")
    except PackageNotFoundError:
        return "unknown"


class _Out:
    def __init__(self, doc: Any) -> None:
        self.doc = doc
        self.findings: list[Finding] = []

    def add(
        self,
        level: str,
        rule: str,
        message: str,
        loc: list[Any],
        ids: list[str],
        hint: str,
        file: str = CELLS_FILE,
    ) -> None:
        self.findings.append(
            Finding(
                file,
                level,  # type: ignore[arg-type]
                f"cheme.stack-{rule}",
                message,
                line=_yaml_line(self.doc, loc) if file == CELLS_FILE else None,
                ids=ids,
                hint=hint,
            )
        )


class _Inputs:
    """Reads the stack's quantities in SI with their provenance, recording unit errors and
    unsourced assumptions as findings."""

    def __init__(self, sid: str, out: _Out, loc: list[Any]) -> None:
        self.sid = sid
        self.out = out
        self.loc = loc
        self.unsourced: list[str] = []

    def get(
        self, q: Quantity | None, units: dict[Any, float], what: str, at: list[Any]
    ) -> tuple[float, Quantity] | None:
        if q is None:
            return None
        factor = units.get(q.unit)
        if factor is None:
            self.out.add(
                "error",
                "schema",
                f"stack {self.sid}: {what} in unit {q.unit!r}",
                [*self.loc, *at],
                [self.sid],
                "use one of " + ", ".join(str(u) for u in units if u is not None),
            )
            return None
        if q.provenance == "assumed" and not q.source.strip():
            self.unsourced.append(what)
            self.out.add(
                "info",
                "unsourced",
                f"stack {self.sid}: {what} is assumed without a source",
                [*self.loc, *at],
                [self.sid],
                "give the source of the assumption (a vendor enquiry, a rule of thumb, "
                "DESIGN.md D-NNN)",
            )
        return q.value * factor, q


def _text(q: Quantity, value: float, unit: str) -> str:
    mark = "ASSUMED: " if q.provenance == "assumed" else ""
    source = " ".join(q.source.split()) or "no source given"
    return f"{value:.6g}{' ' + unit if unit else ''} ({q.provenance}; {mark}{source})"


def _assumed(*qs: Quantity | None) -> bool:
    return any(q is not None and q.provenance == "assumed" for q in qs)


def _ceil(x: float) -> int:
    return max(1, math.ceil(x - _TOL * max(abs(x), 1.0)))


def _floor(x: float) -> int:
    return math.floor(x + _TOL * max(abs(x), 1.0))


def _up(x: float) -> float:
    """*x* m rounded up to the millimetre."""
    return math.ceil(x * 1000 - 1e-6) / 1000


# -- the cell's operating point -----------------------------------------------------------------


def _cell_point(
    stack: Stack, index: int, cells: Any, report: Any, root: Path, out: _Out
) -> tuple[CellPoint | None, list[str], list[str]]:
    """The :class:`CellPoint` of *stack*'s cell from the cell report; (None, reasons,
    limitations) with a ``stack-cell`` finding when it cannot be sized on."""
    from chemeascode.domains.process.electrochemical_cell import cell_product

    sid = stack.id
    loc = ["stacks", index, "cell"]
    reasons: list[str] = []
    limitations: list[str] = []

    def refuse(reason: str, hint: str) -> None:
        reasons.append(reason)
        out.add("error", "cell", f"stack {sid}: {reason}: refused", loc, [sid], hint)

    defined = {c.id: c for c in cells.cells}
    cell = defined.get(stack.cell)
    result = next((c for c in report.cells if c.id == stack.cell), None)
    if cell is None or result is None:
        refuse(
            f"cell {stack.cell} is not in {CELLS_FILE}",
            "name a cell id of the cells: section",
        )
        return None, reasons, limitations
    own = [f for f in report.findings if f.ids and f.ids[0] == cell.id]
    if result.refused:
        refuse(
            f"cell {cell.id} is refused by its Faraday balance ({'; '.join(result.reasons)})",
            f"run `cheme process cell` and fix cell {cell.id}; a stack is never sized outside "
            "the cell's measured or declared range",
        )
        return None, reasons, limitations
    outside = [
        f for f in own if f.rule == "cheme.cell-operating-range" and f.level in ("warning", "error")
    ]
    if outside:
        refuse(
            f"cell {cell.id}: {outside[0].message.removeprefix(f'cell {cell.id}: ')}",
            "operate the cell within the range its specified performance holds for, or give "
            "data for this operating point; a stack is never sized on an extrapolation",
        )
        return None, reasons, limitations
    if cell.performance == "specified" and (
        cell.operating_range is None or cell.operating_range.current_density is None
    ):
        text = (
            f"cell {cell.id} states no current density range: its specified voltage and "
            "efficiency are not checked against the stack's operating point"
        )
        limitations.append(text)
        out.add(
            "info",
            "cell",
            f"stack {sid}: {text}",
            loc,
            [sid],
            "give operating_range.current_density of the cell's data source",
        )
    others = sorted({f.rule for f in own if f.level == "warning"})
    if others:
        out.add(
            "warning",
            "cell",
            f"stack {sid}: cell {cell.id} has warnings ({', '.join(others)})",
            loc,
            [sid],
            "run `cheme process cell` and resolve them before relying on the stack",
        )
    if result.current_density_a_m2 is None or not result.current_a:
        refuse(
            f"cell {cell.id} has no active_area (the current density and the cell area)",
            "give the plant cell's active_area (cm2 or m2) in process/cells.yaml",
        )
        return None, reasons, limitations
    product = stack.product.component
    basis = cell_product(root, cell, product)
    if basis is None:
        refuse(
            f"{product} is no product of the cell's reaction {cell.reaction}",
            "name a product of the cell's overall reaction as product.component",
        )
        return None, reasons, limitations
    if not basis.molar_mass:
        refuse(
            f"no molar mass of {product} in process/materials.yaml",
            "give its formula or molar_mass",
        )
        return None, reasons, limitations
    if cell.cells != 1:
        limitations.append(
            f"cell {cell.id} states cells: {cell.cells} for its own Faraday balance; the stack "
            "takes its values per cell and sizes its own arrangement"
        )
    heat = result.heat_duty_kw / result.cells if result.heat_duty_kw is not None else None
    j = result.current_density_a_m2
    assert result.voltage_v is not None and result.faradaic_efficiency is not None
    measurement = None
    if result.measurement is not None:
        m = result.measurement
        measurement = {
            "file": m["file"],
            "current_density_a_m2": m["current_density_a_m2"],
            "bracket": list(m.get("bracket") or []),
            "current_density_range_a_m2": (m.get("validity") or {}).get("current_density_a_m2"),
            "temperature_range_k": (m.get("validity") or {}).get("temperature_k"),
        }
    elif cell.operating_range is not None and cell.operating_range.current_density:
        measurement = {
            "file": None,
            "current_density_a_m2": j,
            "current_density_range_a_m2": list(cell.operating_range.current_density),
            "temperature_range_k": list(cell.operating_range.temperature)
            if cell.operating_range.temperature
            else None,
        }
    return (
        CellPoint(
            cell.id,
            cell.performance,
            result.current_a,
            j,
            result.current_a / j,
            result.voltage_v,
            result.faradaic_efficiency,
            basis.electrons,
            basis.coefficient,
            basis.molar_mass,
            heat,
            measurement,
            list(result.sources),
        ),
        reasons,
        limitations,
    )


# -- sizing -------------------------------------------------------------------------------------


def size_stack(
    stack: Stack, point: CellPoint, out: _Out | None = None, index: int = 0
) -> StackResult:
    """The stacks of *stack* at the cell's operating point *point* (see the module text); no
    plant repository needed. Findings go to *out* (default: a fresh one on
    ``process/cells.yaml``)."""
    out = out if out is not None else _Out(None)
    sid = stack.id
    loc: list[Any] = ["stacks", index]
    result = StackResult(sid, stack.cell, line=_yaml_line(out.doc, loc), title=stack.title)
    result.point = point
    result.sources = [*stack.sources, *point.sources]
    read = _Inputs(sid, out, loc)
    v = result.values

    def refuse(rule: str, reason: str, at: list[Any], hint: str, report: bool = True):
        result.refused = True
        result.reasons.append(reason)
        if report:
            out.add("error", rule, f"stack {sid}: {reason}: refused", [*loc, *at], [sid], hint)
        return result

    # the product duty
    p = stack.product
    rate = p.rate
    kmol = point.molar_mass  # kg/kmol == g/mol
    if rate.unit in _RATE_MASS:
        kg_h = rate.value * _RATE_MASS[rate.unit]
        mol_s = kg_h / kmol * 1000 / 3600
    elif rate.unit in _RATE_MOLAR:
        mol_s = rate.value * _RATE_MOLAR[rate.unit]
        kg_h = mol_s * kmol * 3600 / 1000
    else:
        return refuse(
            "schema",
            f"product rate in unit {rate.unit!r}",
            ["product", "rate"],
            "use one of " + ", ".join([*_RATE_MASS, *_RATE_MOLAR]),
        )
    if not kg_h > 0:
        return refuse(
            "schema", "the product rate is not positive", ["product", "rate"], "give a duty > 0"
        )
    duty_text = _text(rate, rate.value, rate.unit or "")
    v["product_duty_kg_h"] = Sized(kg_h, "kg/h", rate.provenance, duty_text, _assumed(rate))
    v["product_duty_mol_s"] = Sized(
        mol_s, "mol/s", "calculated", f"{kg_h:.6g} kg/h / M {kmol:.6g} g/mol", _assumed(rate)
    )
    for name in ("purity", "pressure"):
        q = getattr(p, name)
        if q is not None:
            v[f"product_{name}"] = Sized(q.value, q.unit or "", q.provenance, q.source, _assumed(q))

    # the electrical limits
    e = stack.electrical
    umax = read.get(e.max_stack_voltage, _VOLTAGE, "max_stack_voltage", ["electrical"])
    imax = read.get(e.max_stack_current, _CURRENT, "max_stack_current", ["electrical"])
    eta = read.get(e.rectifier_efficiency, _FRACTION, "rectifier_efficiency", ["electrical"])
    irect = read.get(e.rectifier_max_current, _CURRENT, "rectifier_max_current", ["electrical"])
    if umax is None:  # its unit error is reported
        return refuse("schema", "max_stack_voltage unreadable", [], "", report=False)
    u, i, j, fe = (
        point.voltage_v,
        point.current_a,
        point.current_density_a_m2,
        point.faradaic_efficiency,
    )
    if u > umax[0] * (1 + _TOL):
        return refuse(
            "electrical",
            f"the cell voltage {u:.4g} V is above the stack voltage limit {umax[0]:.4g} V",
            ["electrical", "max_stack_voltage"],
            "a higher DC bus voltage, or a cell operating point at a lower voltage",
        )
    if imax is not None and i > imax[0] * (1 + _TOL):
        return refuse(
            "electrical",
            f"the cell current {i:.6g} A (j {j:.6g} A/m2 on {point.area_m2 * 1e4:.6g} cm2) is "
            f"above the stack current limit {imax[0]:.6g} A: a series stack carries its cells' "
            "current",
            ["electrical", "max_stack_current"],
            "a smaller cell (active_area), a lower current density, or a stack rated for it",
        )
    if eta is not None and not 0 < eta[0] <= 1:
        return refuse(
            "schema",
            f"rectifier_efficiency {eta[0]:g} is not in (0, 1]",
            ["electrical", "rectifier_efficiency"],
            "a fraction",
        )

    # the cells and the arrangement
    n, nu = point.electrons, point.coefficient
    cell_text = (
        f"cell {point.cell} ({point.performance}"
        + (
            f", {point.measurement['file']}"
            if point.measurement and point.measurement.get("file")
            else ""
        )
        + f"): j {j:.6g} A/m2, U {u:.6g} V, FE({p.component}) {fe:.6g}, n {n:g}, nu {nu:g}"
    )
    current_total = n * FARADAY * mol_s / (nu * fe)
    area = current_total / j
    v["total_current_a"] = Sized(
        current_total,
        "A",
        "calculated",
        f"I = n F Ndot / (nu FE): {cell_text}; Ndot {mol_s:.6g} mol/s",
        _assumed(rate),
    )
    v["total_active_area_m2"] = Sized(
        area, "m2", "calculated", f"A = n F Ndot / (nu FE j): {cell_text}", _assumed(rate)
    )
    required = _ceil(area / point.area_m2)
    v["cells_required"] = Sized(
        required,
        "",
        "calculated",
        f"ceil(A / A_cell) = ceil({area:.6g} / {point.area_m2:.6g} m2)",
        _assumed(rate),
    )
    most = _floor(umax[0] / u)
    v["max_cells_per_stack"] = Sized(
        most,
        "",
        "calculated",
        f"floor(U_max / U) = floor({_text(umax[1], umax[0], 'V')} / {u:.6g} V)",
        _assumed(umax[1]),
    )
    stacks = _ceil(required / most)
    per_stack = _ceil(required / stacks)
    total = stacks * per_stack
    basis = _assumed(rate, umax[1])
    v["stacks"] = Sized(
        stacks, "", "calculated", f"ceil({required} cells / {most} per stack)", basis
    )
    v["cells_per_stack"] = Sized(
        per_stack,
        "",
        "calculated",
        f"ceil({required} cells / {stacks} stacks): the cells shared evenly, in series",
        basis,
    )
    v["cells_total"] = Sized(total, "", "calculated", f"{stacks} x {per_stack}", basis)
    result.arrangement = (
        f"{stacks} stack(s) in parallel on the DC bus, {per_stack} cells in series each "
        f"({total} cells, {required} required)"
    )
    stack_voltage = per_stack * u
    v["stack_voltage_v"] = Sized(
        stack_voltage,
        "V",
        "calculated",
        f"{per_stack} cells x {u:.6g} V (limit {umax[0]:.6g} V)",
        basis,
    )
    v["stack_current_a"] = Sized(
        i, "A", "calculated", f"the cell current, j {j:.6g} A/m2 x {point.area_m2:.6g} m2", False
    )
    v["bus_current_a"] = Sized(stacks * i, "A", "calculated", f"{stacks} stacks x {i:.6g} A", basis)
    power = total * u * i / 1000
    v["dc_power_kw"] = Sized(
        power, "kW", "calculated", f"P = sum N U I = {total} x {u:.6g} V x {i:.6g} A", basis
    )
    if eta is not None:
        v["ac_power_kw"] = Sized(
            power / eta[0],
            "kW",
            "calculated",
            f"P / eta_rectifier {_text(eta[1], eta[0], '')}",
            _assumed(rate, umax[1], eta[1]),
        )
    if irect is not None:
        v["rectifiers"] = Sized(
            _ceil(stacks * i / irect[0]),
            "",
            "calculated",
            f"ceil(bus current {stacks * i:.6g} A / {_text(irect[1], irect[0], 'A')})",
            _assumed(rate, umax[1], irect[1]),
        )
    output_mol_s = total * fe * i * nu / (n * FARADAY)
    output = output_mol_s * kmol * 3600 / 1000
    v["product_output_kg_h"] = Sized(
        output,
        "kg/h",
        "calculated",
        f"N FE I nu / (n F) x M = {total} x {fe:.6g} x {i:.6g} A x {nu:g} / ({n:g} F) x "
        f"{kmol:.6g} g/mol",
        basis,
    )
    v["output_margin"] = Sized(
        output / kg_h - 1, "", "calculated", f"{output:.6g} / {kg_h:.6g} kg/h - 1", basis
    )
    v["electricity_kwh_per_kg"] = Sized(
        power / output,
        "kWh/kg",
        "calculated",
        f"P / output: the stacks' DC power over the {p.component} delivered (not allocated "
        "to side products)",
        False,
    )
    if point.heat_kw is not None:
        v["heat_duty_kw"] = Sized(
            point.heat_kw * total,
            "kW",
            "calculated",
            f"Q per cell {point.heat_kw:.6g} kW (cheme process cell) x {total} cells",
            basis,
        )

    _envelope(stack, result, read, per_stack, stacks, total, out, loc)
    return result


def _envelope(
    stack: Stack,
    result: StackResult,
    read: _Inputs,
    per_stack: int,
    stacks: int,
    total: int,
    out: _Out,
    loc: list[Any],
) -> None:
    """The stack's L x W x H, the footprint with its clearances and the replacements."""
    sid = stack.id
    v = result.values
    point = result.point
    assert point is not None
    env = stack.envelope
    names = ("cell_pitch", "end_plates", "frame_margin")
    got = {
        name: read.get(getattr(env, name) if env else None, _LENGTH, name, ["envelope", name])
        for name in names
    }
    missing = [name for name in names if got[name] is None]
    dims = ("stack_length_m", "stack_width_m", "stack_height_m")
    if missing:
        reason = f"no envelope {', '.join(missing)} (the vendor's, or ASSUMED with a source)"
        for key in dims:
            v[key] = Sized("TBD", "m", "tbd", reason)
        out.add(
            "info",
            "envelope",
            f"stack {sid}: {reason}: the stack's dimensions stay TBD",
            [*loc, "envelope"],
            [sid],
            "give envelope: {cell_pitch, end_plates, frame_margin} (mm) with their source",
        )
    else:
        pitch, plates, margin = (got[name] for name in names)  # type: ignore[misc]
        assumed = _assumed(pitch[1], plates[1], margin[1])
        side = math.sqrt(point.area_m2)
        length = per_stack * pitch[0] + plates[0]
        across = side + 2 * margin[0]
        v["stack_length_m"] = Sized(
            _up(length),
            "m",
            "calculated",
            f"{per_stack} cells x pitch {_text(pitch[1], pitch[0] * 1000, 'mm')} + end plates "
            f"{_text(plates[1], plates[0] * 1000, 'mm')}",
            assumed,
        )
        for key, what in (("stack_width_m", "width"), ("stack_height_m", "height")):
            v[key] = Sized(
                _up(across),
                "m",
                "calculated",
                f"square active area {side:.4g} m (sqrt {point.area_m2:.6g} m2) + 2 x frame "
                f"margin {_text(margin[1], margin[0] * 1000, 'mm')} ({what})",
                assumed,
            )
        access = stack.access
        ends = read.get(access.end if access else None, _LENGTH, "access end", ["access", "end"])
        sides = read.get(
            access.side if access else None, _LENGTH, "access side", ["access", "side"]
        )
        if ends is not None and sides is not None:
            l_all, w_all = length + 2 * ends[0], across + 2 * sides[0]
            v["footprint_per_stack_m2"] = Sized(
                l_all * w_all,
                "m2",
                "calculated",
                f"({length:.4g} + 2 x {_text(ends[1], ends[0], 'm')}) x ({across:.4g} + 2 x "
                f"{_text(sides[1], sides[0], 'm')}): the stack with its clearances",
                assumed or _assumed(ends[1], sides[1]),
            )
            v["footprint_m2"] = Sized(
                l_all * w_all * stacks,
                "m2",
                "calculated",
                f"{stacks} stacks side by side, clearances not shared",
                assumed or _assumed(ends[1], sides[1]),
            )
    replacement = stack.replacement
    if replacement is not None:
        interval = read.get(
            replacement.interval, _HOURS, "replacement interval", ["replacement", "interval"]
        )
        hours = read.get(
            replacement.operating_hours,
            _HOURS_PER_YEAR,
            "operating_hours",
            ["replacement", "operating_hours"],
        )
        if interval is not None and interval[0] > 0:
            v["replacement_interval_h"] = Sized(
                interval[0],
                "h",
                interval[1].provenance,
                _text(interval[1], interval[0], "h"),
                _assumed(interval[1]),
            )
            if hours is not None:
                per_year = total * hours[0] / interval[0]
                v["cells_replaced_per_year"] = Sized(
                    per_year,
                    "1/a",
                    "calculated",
                    f"{total} cells x {_text(hours[1], hours[0], 'h/a')} / {interval[0]:.6g} h",
                    _assumed(interval[1], hours[1]),
                )
                v["membrane_area_replaced_m2_per_year"] = Sized(
                    per_year * point.area_m2,
                    "m2/a",
                    "calculated",
                    f"{per_year:.6g} cells/a x {point.area_m2:.6g} m2",
                    _assumed(interval[1], hours[1]),
                )


# -- the skid equipment from the duty -----------------------------------------------------------


def _tank(
    tank: SkidTank,
    role: str,
    volume_l: float,
    what: str,
    read: _Inputs,
    sid: str,
    out: _Out,
    loc: list[Any],
) -> EquipmentInput:
    """A vertical cylinder holding *volume_l* times one plus the margin, at the stated H/D."""
    entry = EquipmentInput(tank.tag, role, "dimensions", EQUIPMENT_LIST)
    margin = read.get(tank.margin, _FRACTION, f"{role} margin", [role, "margin"])
    aspect = read.get(tank.aspect_ratio, _FRACTION, f"{role} aspect_ratio", [role, "aspect_ratio"])
    absent = [n for n, q in (("margin", margin), ("aspect_ratio", aspect)) if q is None]
    if margin is not None and margin[0] < 0 or aspect is not None and aspect[0] <= 0:
        out.add(
            "error",
            "schema",
            f"stack {sid}: {role} margin below 0 or aspect_ratio not above 0",
            [*loc, role],
            [sid],
            "a margin >= 0 (fraction or %) and H/D > 0",
        )
        absent = absent or ["a valid margin and aspect_ratio"]
    if absent:
        reason = f"no {role} {' or '.join(absent)}"
        entry.values = {k: Sized("TBD", "m", "tbd", reason) for k in ("diameter", "height")}
        out.add(
            "info",
            "input-missing",
            f"stack {sid}: {reason}: the dimensions of {tank.tag} stay TBD",
            [*loc, role],
            [sid, tank.tag],
            f"give {role}: {{margin, aspect_ratio}} with their source (ASSUMED until the "
            "vessel design)",
        )
        return entry
    assert margin is not None and aspect is not None
    held = volume_l * (1 + margin[0]) / 1000  # m3
    d = (4 * held / (math.pi * aspect[0])) ** (1 / 3)
    d_m, h_m = _up(d), _up(aspect[0] * d)
    entry.assumed = _assumed(margin[1], aspect[1])
    basis = (
        f"{what} {volume_l:.6g} L x (1 + margin {_text(margin[1], margin[0], '')}) = "
        f"{held * 1000:.6g} L; vertical cylinder H/D {_text(aspect[1], aspect[0], '')}"
    )
    entry.values = {
        "diameter": Sized(
            d_m, "m", "calculated", f"D = (4 V / (pi H/D))^(1/3): {basis}", entry.assumed
        ),
        "height": Sized(h_m, "m", "calculated", f"H = H/D x D: {basis}", entry.assumed),
    }
    entry.detail = f"{held * 1000:.6g} L ({what} {volume_l:.6g} L with its margin)"
    return entry


def _skid(
    stack: Stack,
    index: int,
    result: StackResult,
    root: Path,
    out: _Out,
    read: _Inputs,
    duties: bool = True,
) -> None:
    """The equipment inputs of *stack*'s skid: the recirculation pump from the arrangement,
    and with *duties* the reservoir, dosing and bleed from its duty run at the arrangement."""
    from chemeascode.domains.process.electrolysis_duty import DUTIES_FILE, load_duties, run_duty
    from chemeascode.foundation.provenance import value_fingerprint

    skid = stack.equipment
    assert skid is not None
    sid = stack.id
    loc: list[Any] = ["stacks", index, "equipment"]
    point = result.point
    assert point is not None
    per_stack, stacks = result.number("cells_per_stack"), result.number("stacks")
    total = per_stack * stacks
    arrangement = f"{per_stack} cells x {stacks} stacks"
    sizing_fp = value_fingerprint(
        {
            "model": MODEL,
            "stack": stack.model_dump(mode="json", exclude={"equipment"}),
            "point": point.as_dict(),
        }
    )
    pump = skid.recirculation_pump
    if pump is not None:
        result.equipment.append(
            _recirculation(pump, point, total, arrangement, read, sid, out, loc)
        )
        result.equipment[-1].fingerprint = value_fingerprint(
            {"sizing": sizing_fp, "pump": pump.model_dump(mode="json")}
        )
    if not duties:
        return
    loaded, _, _ = load_duties(root)
    known = {d.id: d for d in loaded.duties} if loaded is not None else {}
    duty = known.get(skid.duty)
    if duty is None:
        out.add(
            "error",
            "duty",
            f"stack {sid}: duty {skid.duty} is not in {DUTIES_FILE}: the reservoir, dosing and "
            "bleed inputs are not given",
            [*loc, "duty"],
            [sid],
            f"name a duty of {DUTIES_FILE} (`cheme process duty`)",
        )
        _duty_tbd(stack, result, f"no duty {skid.duty}")
        return
    if duty.cell != stack.cell:
        out.add(
            "warning",
            "duty",
            f"stack {sid}: duty {duty.id} runs cell {duty.cell}, the stack is of cell {stack.cell}",
            [*loc, "duty"],
            [sid],
            "a skid duty runs the stack's cell",
        )
    stated = (duty.cells_in_series, duty.stacks)
    if stated != (per_stack, stacks) and stated != (None, 1):
        out.add(
            "info",
            "duty",
            f"stack {sid}: duty {duty.id} states {duty.cells_in_series or 'the cell'}'s cells "
            f"x {duty.stacks} stacks; it is run at the sized {arrangement}",
            [*loc, "duty"],
            [sid],
            "the arrangement comes from the stack sizing (one design basis); drop "
            "cells_in_series and stacks from the duty",
        )
    report = run_duty(root, duty.id, per_stack, stacks)
    run = report.duties[0] if report.duties else None
    run_fp = value_fingerprint(
        {
            "model": MODEL,
            "duty": duty.id,
            "inputs": report.source.fingerprints if report.source is not None else {},
            "arrangement": [per_stack, stacks],
        }
    )
    result.duty = {
        "id": duty.id,
        "run_fingerprint": run_fp,
        "arrangement": arrangement,
        "ended": run.ended if run else None,
        "feasible": bool(run and run.feasible),
        "campaign_h": run.horizon_h if run else None,
        "simulated_h": run.simulated_h if run else None,
        "time_to_threshold_h": run.time_to_threshold_h if run else None,
        "findings": [f.rule for f in report.findings if f.level in ("warning", "error")],
    }
    if run is None or run.refused or not run.feasible:
        if run is None:
            why = "no result"
        elif run.refused:
            why = "; ".join(run.reasons)
        else:
            why = f"ended by {run.ended} at {run.simulated_h:.6g} h of {run.horizon_h:.6g} h"
            for hours, where in (
                (run.time_outside_measured_range_h, "the measured range"),
                (run.time_outside_model_range_h, "the anolyte model's validity"),
            ):
                if hours:
                    why += f", {hours:.4g} h outside {where}"
        hint = "make the duty feasible at the sized arrangement (`cheme process duty`)"
        need = _volume_needed(duty, run)
        if need is not None:
            hint = (
                f"a reservoir of {need:.4g} L reaches the horizon without dosing (the time to "
                "the threshold scales with the volume at these fluxes); or dose"
            )
        out.add(
            "error",
            "duty",
            f"stack {sid}: duty {duty.id} is not feasible at the sized {arrangement} ({why}): "
            "the reservoir, dosing and bleed inputs are not given",
            [*loc, "duty"],
            [sid],
            hint,
        )
        _duty_tbd(stack, result, f"duty {duty.id} not feasible at {arrangement} ({why})")
        return
    _current_check(stack, run, point, out, loc)
    series = run.series
    totals = run.totals
    campaign = run.horizon_h
    head = f"{STACK_MARK}: stack {sid}, duty {duty.id} at {arrangement}, campaign {campaign:.6g} h"
    if skid.reservoir is not None:
        working = max(x for x in series.get("volume_l", []) if x is not None)
        entry = _tank(
            skid.reservoir,
            "reservoir",
            working,
            "working volume (the largest over the duty)",
            read,
            sid,
            out,
            loc,
        )
        _finish(entry, head, run_fp)
        result.equipment.append(entry)
    dosing = duty.dosing
    rate = getattr(dosing, "rate", None)
    if skid.dosing_pump is not None:
        entry = EquipmentInput(skid.dosing_pump.tag, "dosing_pump", "type_specific", "")
        margin = read.get(
            skid.dosing_pump.margin, _FRACTION, "dosing_pump margin", ["dosing_pump", "margin"]
        )
        density = getattr(dosing, "density", None)
        rate_l_h = (
            rate.value * _DUTY_FLOW[rate.unit]
            if rate is not None and rate.unit in _DUTY_FLOW
            else None
        )
        rho = (
            density.value * _DUTY_DENSITY[density.unit] * 1000
            if density is not None and density.unit in _DUTY_DENSITY
            else None
        )
        reason = (
            f"duty {duty.id} doses nothing"
            if rate is None
            else f"duty {duty.id}: dosing rate in unit {rate.unit!r}"
            if rate_l_h is None
            else "no dosing_pump margin"
            if margin is None
            else f"no density of the dosing solution in duty {duty.id}"
            if rho is None
            else ""
        )
        if reason:
            entry.values = {
                "mass_flow_kg_h": Sized("TBD", "kg/h", "tbd", reason),
                "density_kg_m3": Sized("TBD", "kg/m3", "tbd", reason),
            }
            out.add(
                "info",
                "input-missing",
                f"stack {sid}: {reason}: the dosing pump {entry.tag} inputs stay TBD",
                [*loc, "dosing_pump"],
                [sid, entry.tag],
                "give the duty's dosing (rate, density) and the pump's margin",
            )
        else:
            assert margin is not None and rate_l_h is not None and rho is not None
            capacity = rate_l_h * (1 + margin[0])
            entry.assumed = _assumed(margin[1])
            entry.values = {
                "mass_flow_kg_h": Sized(
                    capacity * rho / 1000,
                    "kg/h",
                    "calculated",
                    f"the duty's dosing rate {rate_l_h:.6g} L/h x (1 + margin "
                    f"{_text(margin[1], margin[0], '')}) x density {rho:.6g} kg/m3",
                    entry.assumed,
                ),
                "density_kg_m3": Sized(
                    rho, "kg/m3", "given", f"duty {duty.id} dosing.density", False
                ),
            }
            entry.detail = f"{capacity:.6g} L/h"
        _finish(entry, head, run_fp)
        result.equipment.append(entry)
    for role, tank, key, what in (
        ("dosing_tank", skid.dosing_tank, "dosing_solution_l", "solution dosed over the campaign"),
        ("bleed_tank", skid.bleed_tank, "bleed_l", "bleed over the campaign"),
    ):
        if tank is None:
            continue
        volume = totals.get(key) or 0.0
        if volume <= 0:
            entry = EquipmentInput(tank.tag, role, "dimensions", EQUIPMENT_LIST)
            reason = f"duty {duty.id} has no {what.split(' over')[0]} (0 L)"
            entry.values = {k: Sized("TBD", "m", "tbd", reason) for k in ("diameter", "height")}
            out.add(
                "info",
                "input-missing",
                f"stack {sid}: {reason}: the dimensions of {tank.tag} stay TBD",
                [*loc, role],
                [sid, tank.tag],
                "remove the tank or give the duty its dosing or bleed",
            )
        else:
            entry = _tank(tank, role, volume, what, read, sid, out, loc)
        _finish(entry, head, run_fp)
        result.equipment.append(entry)
    result.values["campaign_h"] = Sized(
        campaign, "h", "given", f"{DUTIES_FILE} duty {duty.id} horizon", False
    )
    result.values["reservoir_working_volume_l"] = Sized(
        max(x for x in series.get("volume_l", []) if x is not None),
        "L",
        "calculated",
        f"the largest volume over duty {duty.id} at {arrangement}",
        False,
    )
    result.values["dosing_solution_l"] = Sized(
        totals.get("dosing_solution_l") or 0.0,
        "L",
        "calculated",
        f"dosed over duty {duty.id} ({campaign:.6g} h)",
        False,
    )
    result.values["bleed_l"] = Sized(
        totals.get("bleed_l") or 0.0, "L", "calculated", f"bled over duty {duty.id}", False
    )
    if getattr(duty.bleed, "rate", None) is not None and duty.bleed.rate.unit in _DUTY_FLOW:  # type: ignore[union-attr]
        result.values["bleed_rate_l_h"] = Sized(
            duty.bleed.rate.value * _DUTY_FLOW[duty.bleed.rate.unit],  # type: ignore[union-attr]
            "L/h",
            "given",
            f"{DUTIES_FILE} duty {duty.id} bleed.rate",
            False,
        )


def _finish(entry: EquipmentInput, head: str, fingerprint: str) -> None:
    entry.source = f"{head}: {entry.detail}" if entry.detail else head
    entry.fingerprint = fingerprint


def _duty_tbd(stack: Stack, result: StackResult, reason: str) -> None:
    """The duty's equipment inputs left TBD with *reason*."""
    skid = stack.equipment
    assert skid is not None
    for role in ("reservoir", "dosing_tank", "bleed_tank"):
        tank = getattr(skid, role)
        if tank is not None:
            entry = EquipmentInput(tank.tag, role, "dimensions", EQUIPMENT_LIST)
            entry.values = {k: Sized("TBD", "m", "tbd", reason) for k in ("diameter", "height")}
            result.equipment.append(entry)
    if skid.dosing_pump is not None:
        entry = EquipmentInput(skid.dosing_pump.tag, "dosing_pump", "type_specific", "")
        entry.values = {"mass_flow_kg_h": Sized("TBD", "kg/h", "tbd", reason)}
        result.equipment.append(entry)


def _volume_needed(duty: Any, run: Any) -> float | None:
    """The reservoir volume (L) that reaches the horizon, where the time to the threshold scales
    with the volume: no dosing, bleed, make-up or degassing (the fluxes do not depend on the
    volume), the transient ended by the threshold."""
    if run is None or run.refused or run.ended != "threshold" or not run.time_to_threshold_h:
        return None
    if duty.dosing.kind != "none" or duty.bleed or duty.makeup_water or duty.reservoir.degassing:
        return None
    volume = run.series.get("volume_l") or [None]
    if volume[0] is None:
        return None
    return volume[0] * run.horizon_h / run.time_to_threshold_h


def _current_check(stack: Stack, run: Any, point: CellPoint, out: _Out, loc: list[Any]) -> None:
    """The duty's current density against the stack's (a warning when they differ)."""
    found = [
        x
        for x, current in zip(
            run.series.get("current_density_a_m2") or [],
            run.series.get("current_a") or [],
            strict=False,
        )
        if x is not None and current
    ]
    if not found:
        return
    lo, hi = min(found), max(found)
    j = point.current_density_a_m2
    if abs(lo - j) <= 1e-6 * j and abs(hi - j) <= 1e-6 * j:
        return
    span = f"{lo:.6g} A/m2" if abs(hi - lo) <= 1e-9 * hi else f"{lo:.6g}-{hi:.6g} A/m2"
    out.add(
        "warning",
        "duty",
        f"stack {stack.id}: duty {run.id} runs the cell at {span}, the stack is sized at "
        f"{j:.6g} A/m2",
        [*loc, "duty"],
        [stack.id],
        "a skid duty runs the cell at the stack's current density (or the stack is sized at "
        "the duty's)",
    )


def _recirculation(
    pump: Any,
    point: CellPoint,
    total: int,
    arrangement: str,
    read: _Inputs,
    sid: str,
    out: _Out,
    loc: list[Any],
) -> EquipmentInput:
    """The anolyte recirculation pump's inputs to the pump sizing."""
    role = "recirculation_pump"
    entry = EquipmentInput(pump.tag, role, "type_specific", "")
    per_area = read.get(pump.flow_per_area, _FLOW_AREA, "flow_per_area", [role, "flow_per_area"])
    per_cell = read.get(pump.flow_per_cell, _FLOW_CELL, "flow_per_cell", [role, "flow_per_cell"])
    rho = read.get(pump.density, _DENSITY, "density", [role, "density"])
    mu = read.get(pump.viscosity, _VISCOSITY, "viscosity", [role, "viscosity"])
    p_res = read.get(pump.reservoir_pressure, _PRESSURE, "reservoir_pressure", [role])
    dp = read.get(pump.stack_pressure_drop, _PRESSURE_DROP, "stack_pressure_drop", [role])
    head = f"{STACK_MARK}: stack {sid} at {arrangement}"
    values: dict[str, Sized] = {}
    if per_area is not None:
        q_cell = per_area[0] * point.area_m2
        flow_basis = (
            f"{_text(per_area[1], per_area[1].value, per_area[1].unit or '')} x "
            f"{point.area_m2 * 1e4:.6g} cm2"
        )
        flow_q = per_area[1]
    elif per_cell is not None:
        q_cell = per_cell[0]
        flow_basis = _text(per_cell[1], per_cell[1].value, per_cell[1].unit or "")
        flow_q = per_cell[1]
    else:
        q_cell, flow_basis, flow_q = None, "", None
    flow = q_cell * total if q_cell is not None else None  # L/h
    if flow is None or rho is None:
        reason = "no " + " and no ".join(
            n
            for n, missing in (
                ("anolyte flow_per_area or flow_per_cell", flow is None),
                ("density", rho is None),
            )
            if missing
        )
        values["mass_flow_kg_h"] = Sized("TBD", "kg/h", "tbd", reason)
        out.add(
            "info",
            "input-missing",
            f"stack {sid}: {reason}: the recirculation pump {pump.tag} flow stays TBD",
            [*loc, role],
            [sid, pump.tag],
            "give the anolyte flow per area (or per cell) and its density with their source",
        )
    else:
        assumed = _assumed(flow_q, rho[1])
        values["mass_flow_kg_h"] = Sized(
            flow * rho[0] / 1000,
            "kg/h",
            "calculated",
            f"{flow_basis} per cell x {total} cells = {flow:.6g} L/h x density "
            f"{_text(rho[1], rho[0], 'kg/m3')}",
            assumed,
        )
        entry.detail = f"{flow:.6g} L/h"
    if rho is not None:
        values["density_kg_m3"] = Sized(
            rho[0], "kg/m3", rho[1].provenance, _text(rho[1], rho[0], "kg/m3"), _assumed(rho[1])
        )
    if mu is not None:
        values["viscosity_mpa_s"] = Sized(
            mu[0], "mPa s", mu[1].provenance, _text(mu[1], mu[0], "mPa s"), _assumed(mu[1])
        )
    if p_res is not None:
        values["suction_pressure_kpa"] = Sized(
            p_res[0],
            "kPa(a)",
            p_res[1].provenance,
            f"the reservoir pressure {_text(p_res[1], p_res[0], 'kPa(a)')} (at suction_from)",
            _assumed(p_res[1]),
        )
        if dp is not None:
            values["discharge_pressure_kpa"] = Sized(
                p_res[0] + dp[0],
                "kPa(a)",
                "calculated",
                f"the reservoir pressure {p_res[0]:.6g} kPa(a) + the stack's pressure drop "
                f"{_text(dp[1], dp[0], 'kPa')} (at discharge_to: the stack inlet; the return "
                "line is not added)",
                _assumed(p_res[1], dp[1]),
            )
    entry.values = values
    entry.assumed = any(x.assumed for x in values.values())
    entry.source = f"{head}: {entry.detail}" if entry.detail else head
    return entry


def _stack_tags(stack: Stack, index: int, result: StackResult, out: _Out) -> None:
    """The stack envelope as each stack tag's equipment-list dimensions."""
    sid = stack.id
    stacks = result.number("stacks")
    if not stack.tags:
        return
    if len(stack.tags) != stacks:
        out.add(
            "warning",
            "tags",
            f"stack {sid}: {len(stack.tags)} tag(s) for {stacks} sized stack(s)",
            ["stacks", index, "tags"],
            [sid],
            "list one equipment-list tag per stack (add or remove items in the equipment list "
            "and here)",
        )
    keys = (("length", "stack_length_m"), ("width", "stack_width_m"), ("height", "stack_height_m"))
    values = {name: result.values[key] for name, key in keys}
    assumed = any(x.assumed for x in values.values())
    source = (
        f"{STACK_MARK}: stack {sid}, {result.number('cells_per_stack')} cells per stack, the "
        "envelope of process/cells.yaml"
    )
    from chemeascode.foundation.provenance import value_fingerprint

    fp = value_fingerprint(
        {
            "model": MODEL,
            "stack": stack.model_dump(mode="json", exclude={"equipment", "tags"}),
            "point": result.point.as_dict() if result.point else None,
        }
    )
    for tag in stack.tags:
        entry = EquipmentInput(tag, "stack", "dimensions", EQUIPMENT_LIST, dict(values))
        entry.source, entry.assumed, entry.fingerprint = source, assumed, fp
        result.equipment.append(entry)


# -- the plant ----------------------------------------------------------------------------------


def stack_report(root: Path, ids: list[str] | None = None, duties: bool = True) -> StackReport:
    """Every stack of the ``stacks:`` section of ``process/cells.yaml`` under *root* (or those
    in *ids*) sized, with the equipment inputs of its skid from its duty when *duties* (which
    integrates the duty), compared with the equipment list and the datasheets. Read-only. A
    missing file gives an empty report; an unknown id in *ids* raises KeyError."""
    from chemeascode.domains.process.electrochemical_cell import cell_report, load_cells
    from chemeascode.domains.process.electrolysis_duty import DUTIES_FILE
    from chemeascode.foundation.provenance import source_revision

    root = Path(root)
    cells, doc, findings = load_cells(root)
    inputs = [
        CELLS_FILE,
        "process/materials.yaml",
        "process/reactions.yaml",
        EQUIPMENT_LIST,
    ]
    if cells is not None:
        inputs += [c.measurements.file for c in cells.cells if c.measurements is not None]
        if duties and any(s.equipment is not None for s in cells.stacks):
            inputs.append(DUTIES_FILE)
        inputs += [
            f"{DATASHEET_DIR}/{tag}.yaml"
            for s in cells.stacks
            if s.equipment is not None
            for tag in _pump_tags(s)
        ]
    source = source_revision(root, inputs)
    if cells is None:
        return StackReport([], findings, source)
    known = {s.id for s in cells.stacks}
    unknown = [i for i in ids or [] if i not in known]
    if unknown:
        raise KeyError(f"no stack {', '.join(unknown)} in {CELLS_FILE}")
    out = _Out(doc)
    report = cell_report(root) if cells.stacks else None
    seen: set[str] = set()
    results = []
    for index, stack in enumerate(cells.stacks):
        if stack.id in seen:
            out.add(
                "error",
                "schema",
                f"stack {stack.id} is declared twice",
                ["stacks", index],
                [stack.id],
                "give each stack its own id",
            )
        seen.add(stack.id)
        if ids is not None and stack.id not in ids:
            continue
        point, reasons, limitations = _cell_point(stack, index, cells, report, root, out)
        if point is None:
            result = StackResult(
                stack.id, stack.cell, line=_yaml_line(doc, ["stacks", index]), title=stack.title
            )
            result.refused, result.reasons = True, reasons
            results.append(result)
            continue
        result = size_stack(stack, point, out, index)
        result.limitations = limitations + result.limitations
        if result.refused:
            results.append(result)
            continue
        _stack_tags(stack, index, result, out)
        if stack.equipment is not None:
            read = _Inputs(stack.id, out, ["stacks", index, "equipment"])
            _skid(stack, index, result, root, out, read, duties)
        _compare(root, result, out, index)
        results.append(result)
    return StackReport(results, out.findings, source)


def stack_findings(root: Path) -> list[Finding]:
    """The findings of the ``stacks:`` section that need no duty integration (for ``cheme
    validate``): the sizing, the cells, the tags and the equipment list's stack dimensions."""
    from chemeascode.domains.process.electrochemical_cell import load_cells

    cells, _, _ = load_cells(Path(root))
    if cells is None or not cells.stacks:
        return []  # the cells' schema findings come with the cells
    return stack_report(Path(root), duties=False).findings


def has_stacks(root: Path) -> bool:
    from chemeascode.domains.process.electrochemical_cell import load_cells

    cells, _, _ = load_cells(Path(root))
    return cells is not None and bool(cells.stacks)


def _pump_tags(stack: Stack) -> list[str]:
    skid = stack.equipment
    if skid is None:
        return []
    return [p.tag for p in (skid.recirculation_pump, skid.dosing_pump) if p is not None]


# -- the equipment list and the datasheets ------------------------------------------------------


def _equipment_data(root: Path) -> dict[str, Any] | None:
    path = root / EQUIPMENT_LIST
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def _numbers_equal(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, int | float) and isinstance(b, int | float):
        return abs(a - b) <= 1e-9 * max(abs(a), abs(b), 1.0)
    return a == b


def _ours(entry: Any) -> bool:
    return isinstance(entry, dict) and str(entry.get("source") or "").startswith(STACK_MARK)


def _is_tbd(entry: Any) -> bool:
    value = entry.get("value") if isinstance(entry, dict) else entry
    return isinstance(value, str) and value.strip().upper().startswith("TBD")


def list_dimensions(entry: EquipmentInput, old: dict[str, Any] | None) -> dict[str, Any]:
    """The equipment-list ``dimensions`` mapping *entry* gives an item whose dimensions are
    *old*: the calculated sizes with their source, marking and fingerprint, and the keys of
    *old* that say how the item stands or what it weighs (head, support, weight, ...). A tank
    gets ``head: flat`` unless *old* states its head, so that its shell holds the calculated
    volume over the whole height."""
    kept = {k: v for k, v in (old or {}).items() if k in _KEEP}
    new: dict[str, Any] = {k: s.value for k, s in entry.values.items()}
    if "diameter" in entry.values:
        # the cylinder holds the volume over its whole height (a stated head is kept)
        new["head"] = kept.pop("head", "flat")
    else:
        kept.pop("head", None)
    new.update(kept)
    new["source"] = entry.source
    if entry.assumed:
        new["assumed"] = True
    if entry.fingerprint:
        new["fingerprint"] = entry.fingerprint
    return new


def type_specific(entry: EquipmentInput) -> dict[str, dict[str, Any]]:
    """The datasheet ``type_specific`` entries *entry* gives its pump."""
    found = {}
    for key, s in entry.values.items():
        if s.provenance == "tbd":
            continue
        value: dict[str, Any] = {
            "value": float(f"{s.value:.6g}"),
            "unit": s.unit,
            "source": f"{STACK_MARK}: {s.source}",
        }
        if s.assumed:
            value["assumed"] = True
        if entry.fingerprint:
            value["fingerprint"] = entry.fingerprint
        found[key] = value
    return found


def _compare(root: Path, result: StackResult, out: _Out, index: int) -> None:
    """Each equipment input against the file it goes to: its ``status``, and the
    ``stack-outdated``, ``stack-kept`` and ``stack-target`` findings."""
    data = _equipment_data(root) or {}
    items = {
        str(i.get("tag")).strip(): i for i in data.get("equipment") or [] if isinstance(i, dict)
    }
    sid = result.id
    for entry in result.equipment:
        loc = (
            ["stacks", index, "tags"]
            if entry.role == "stack"
            else ["stacks", index, "equipment", entry.role]
        )
        if not entry.complete:
            entry.status = "tbd"
            continue
        if entry.target == "dimensions":
            item = items.get(entry.tag)
            if item is None:
                entry.status = "no-target"
                out.add(
                    "warning" if entry.role == "stack" else "info",
                    "tags" if entry.role == "stack" else "target",
                    f"stack {sid}: {entry.tag} is not in {EQUIPMENT_LIST}",
                    loc,
                    [sid, entry.tag],
                    f"add {entry.tag} to the equipment list (skill lists-sync), then "
                    "`cheme process stack --write`",
                )
                continue
            old = item.get("dimensions") if isinstance(item.get("dimensions"), dict) else None
            new = list_dimensions(entry, old)
            if old is not None and not str(old.get("source") or "").startswith(STACK_MARK):
                same = all(_numbers_equal(old.get(k), new.get(k)) for k in entry.values)
                entry.status = "current" if same else "kept"
                if not same:
                    out.add(
                        "warning",
                        "kept",
                        f"stack {sid}: {entry.tag} has dimensions written by hand "
                        f"({_dims_text(old)}); the calculated {_dims_text(new)} is not written",
                        loc,
                        [sid, entry.tag],
                        "remove them from the equipment list to let `cheme process stack "
                        "--write` write the calculated ones, or keep them with their source",
                    )
                continue
            same = old is not None and all(
                _numbers_equal(old.get(k), new.get(k)) for k in [*_SIZE_KEYS, "source", "assumed"]
            )
            entry.status = (
                "current"
                if same and old.get("fingerprint") == new.get("fingerprint")
                else "outdated"
            )
            if not same:
                out.add(
                    "warning",
                    "outdated",
                    f"stack {sid}: {EQUIPMENT_LIST} {entry.tag} dimensions "
                    + (f"{_dims_text(old)}" if old else "missing")
                    + f", calculated {_dims_text(new)}",
                    loc,
                    [sid, entry.tag],
                    "`cheme process stack --write` writes them; then `cheme layout build` and "
                    f"`cheme datasheets fill --tag {entry.tag}`",
                )
            continue
        path = root / DATASHEET_DIR / f"{entry.tag}.yaml"
        entry.file = f"{DATASHEET_DIR}/{entry.tag}.yaml"
        if not path.is_file():
            entry.status = "no-target"
            out.add(
                "info",
                "target",
                f"stack {sid}: no datasheet of {entry.tag}",
                loc,
                [sid, entry.tag],
                f"`cheme datasheets draft` (with {entry.tag} in the equipment list), then "
                "`cheme process stack --write`",
            )
            continue
        try:
            sheet = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            entry.status = "no-target"
            continue
        specific = sheet.get("type_specific") if isinstance(sheet, dict) else None
        specific = specific if isinstance(specific, dict) else {}
        changed, refresh, kept = [], [], []
        for key, new in type_specific(entry).items():
            old = specific.get(key)
            if old is None or _is_tbd(old) or _ours(old):
                same = (
                    isinstance(old, dict)
                    and _numbers_equal(old.get("value"), new["value"])
                    and old.get("source") == new["source"]
                    and bool(old.get("assumed")) == bool(new.get("assumed"))
                )
                if not same:
                    changed.append(key)
                elif old.get("fingerprint") != new.get("fingerprint"):
                    refresh.append(key)
            else:
                value = old.get("value") if isinstance(old, dict) else old
                if not _numbers_equal(value, new["value"]):
                    kept.append(key)
        entry.status = "outdated" if changed or refresh else "kept" if kept else "current"
        if changed:
            out.add(
                "warning",
                "outdated",
                f"stack {sid}: {entry.file} type_specific {', '.join(changed)} differ from the "
                "calculated (or are missing)",
                loc,
                [sid, entry.tag],
                "`cheme process stack --write` writes them; then `cheme datasheets fill --tag "
                f"{entry.tag}` sizes the pump",
            )
        if kept:
            out.add(
                "warning",
                "kept",
                f"stack {sid}: {entry.file} type_specific {', '.join(kept)} written by hand "
                "differ from the calculated: kept",
                loc,
                [sid, entry.tag],
                "remove them to let `cheme process stack --write` write the calculated ones",
            )


def _dims_text(dims: dict[str, Any] | None) -> str:
    if not dims:
        return "none"
    order = ("diameter", "length", "width", "depth", "height")
    sizes = [f"{k} {dims[k]:g}" for k in order if isinstance(dims.get(k), int | float)]
    return " x ".join(sizes) + " m"


def write_stack_inputs(root: Path, report: StackReport) -> WriteResult:
    """Write the equipment inputs of *report* (from :func:`stack_report` on *root*) whose
    status is ``outdated``: the equipment-list dimensions of the stack and tank tags (edited in
    place, the rest of the file as it is) and the pumps' datasheet ``type_specific`` values
    (missing, TBD or written by this tool before; never one written by hand). Raises ValueError
    when the edited equipment list would not be the old one with only those dimensions changed
    (nothing is written then)."""
    root = Path(root)
    written = WriteResult()
    dims: dict[str, EquipmentInput] = {}
    sheets: dict[str, list[EquipmentInput]] = {}
    for result in report.stacks:
        for entry in result.equipment:
            if entry.status != "outdated":
                continue
            if entry.target == "dimensions":
                dims[entry.tag] = entry
            else:
                sheets.setdefault(entry.tag, []).append(entry)
    if dims:
        path = root / EQUIPMENT_LIST
        text = path.read_text(encoding="utf-8")
        data = yaml.safe_load(text)
        new_text = text
        for tag, entry in dims.items():
            item = next(i for i in data["equipment"] if str(i.get("tag")).strip() == tag)
            old = item.get("dimensions") if isinstance(item.get("dimensions"), dict) else None
            new_text = set_dimensions(new_text, tag, list_dimensions(entry, old))
        _check_list(text, new_text, {t: list_dimensions(e, _old(data, t)) for t, e in dims.items()})
        path.write_text(new_text, encoding="utf-8")
        for entry in dims.values():
            entry.status = "written"
        written.written[EQUIPMENT_LIST] = sorted(dims)
    for tag, entries in sheets.items():
        path = root / DATASHEET_DIR / f"{tag}.yaml"
        text = path.read_text(encoding="utf-8")
        data = yaml.safe_load(text) or {}
        specific = data.setdefault("type_specific", {}) or {}
        data["type_specific"] = specific
        for entry in entries:
            for key, new in type_specific(entry).items():
                old = specific.get(key)
                if old is None or _is_tbd(old) or _ours(old):
                    specific[key] = new
            entry.status = "written"
        header = "".join(line for line in text.splitlines(keepends=True)[: _header_lines(text)])
        path.write_text(
            header + yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100),
            encoding="utf-8",
        )
        written.written[f"{DATASHEET_DIR}/{tag}.yaml"] = [tag]
    return written


def _header_lines(text: str) -> int:
    count = 0
    for line in text.splitlines():
        if not line.startswith("#"):
            break
        count += 1
    return count


def _old(data: dict[str, Any], tag: str) -> dict[str, Any] | None:
    item = next(i for i in data["equipment"] if str(i.get("tag")).strip() == tag)
    found = item.get("dimensions")
    return found if isinstance(found, dict) else None


def _check_list(old_text: str, new_text: str, changes: dict[str, dict[str, Any]]) -> None:
    """The edited equipment list is valid and is the old one with *changes* only."""
    from chemeascode.domains.equipment.schemas.equipment import EquipmentList

    expected = yaml.safe_load(old_text)
    for item in expected["equipment"]:
        tag = str(item.get("tag")).strip()
        if tag in changes:
            item["dimensions"] = changes[tag]
    try:
        found = yaml.safe_load(new_text)
        EquipmentList.model_validate(found)
    except (yaml.YAMLError, ValueError) as failure:
        raise ValueError(
            f"{EQUIPMENT_LIST}: the edit does not give a valid file ({failure})"
        ) from failure
    if found != expected:
        raise ValueError(
            f"{EQUIPMENT_LIST}: the edit changes more than the dimensions of "
            f"{', '.join(sorted(changes))}; nothing written (write them by hand)"
        )


# -- editing the equipment list as text ---------------------------------------------------------


def _scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(round(value, 6))
    text = str(value)
    if text and all(c.isalnum() or c in "-_." for c in text) and not text[0].isdigit():
        return text
    return json.dumps(text, ensure_ascii=False)


def _flow(mapping: dict[str, Any]) -> str:
    return "{" + ", ".join(f"{k}: {_scalar(v)}" for k, v in mapping.items()) + "}"


def _end(node: Any) -> int:
    """The index just after *node*'s own text (a block collection: after its last value)."""
    if isinstance(node, yaml.MappingNode) and not node.flow_style and node.value:
        return _end(node.value[-1][1])
    if isinstance(node, yaml.SequenceNode) and not node.flow_style and node.value:
        return _end(node.value[-1])
    return node.end_mark.index


def set_dimensions(text: str, tag: str, dimensions: dict[str, Any]) -> str:
    """*text* of an equipment list with item *tag*'s ``dimensions`` replaced by (or given)
    *dimensions*, in the item's own style (a block mapping, or a flow mapping on one line);
    the rest of the text, comments included, as it was. Raises ValueError when the item is not
    there."""
    root = yaml.compose(text)
    if not isinstance(root, yaml.MappingNode):
        raise ValueError(f"{EQUIPMENT_LIST} is no mapping")
    seq = next((v for k, v in root.value if getattr(k, "value", None) == "equipment"), None)
    if not isinstance(seq, yaml.SequenceNode):
        raise ValueError(f"{EQUIPMENT_LIST} has no equipment: list")
    item = next(
        (
            node
            for node in seq.value
            if isinstance(node, yaml.MappingNode)
            and any(
                getattr(k, "value", None) == "tag" and str(getattr(v, "value", "")).strip() == tag
                for k, v in node.value
            )
        ),
        None,
    )
    if item is None:
        raise ValueError(f"{EQUIPMENT_LIST} has no item {tag}")
    found = next(((k, v) for k, v in item.value if getattr(k, "value", None) == "dimensions"), None)
    if item.flow_style:
        body = _flow(dimensions)
        if found is not None:
            key, value = found
            return text[: key.end_mark.index] + ": " + body + text[_end(value) :]
        close = item.end_mark.index - 1  # the closing brace
        return text[:close].rstrip() + f", dimensions: {body}" + text[close:]
    indent = " " * item.value[0][0].start_mark.column
    block = "\n".join(f"{indent}  {k}: {_scalar(v)}" for k, v in dimensions.items())
    if found is not None:
        key, value = found
        return text[: key.end_mark.index] + ":\n" + block + text[_line_end(text, _end(value)) :]
    # after the item's last line, its trailing comment kept on it
    end = _line_end(text, _end(item.value[-1][1]))
    return text[:end] + f"\n{indent}dimensions:\n" + block + text[end:]


def _line_end(text: str, index: int) -> int:
    """*index*, or the end of its line when only blanks or a comment follow it there."""
    newline = text.find("\n", index)
    newline = len(text) if newline < 0 else newline
    rest = text[index:newline].strip()
    return newline if not rest or rest.startswith("#") else index


# -- text ---------------------------------------------------------------------------------------


def _v(result: StackResult, key: str, digits: str = ".4g") -> str:
    found = result.values.get(key)
    if found is None:
        return "-"
    if found.provenance == "tbd":
        return "TBD"
    mark = " ASSUMED" if found.assumed else ""
    unit = f" {found.unit}" if found.unit else ""
    return f"{found.value:{digits}}{unit}{mark}"


def report_text(report: StackReport) -> str:
    lines = [f"model {MODEL['id']} v{MODEL['version']} ({MODEL['section']}), core {_version()}"]
    for s in report.stacks:
        if s.refused:
            lines.append(f"{s.id}: refused ({'; '.join(s.reasons)})")
            continue
        p = s.point
        assert p is not None
        where = f", {p.measurement['file']}" if p.measurement and p.measurement.get("file") else ""
        product = s.values["product_duty_kg_h"]
        lines.append(
            f"{s.id}: cell {p.cell} ({p.performance}{where}) at {p.current_density_a_m2:.6g} A/m2,"
            f" U {p.voltage_v:.4g} V, FE {p.faradaic_efficiency:.4g}, {p.area_m2 * 1e4:.6g} cm2"
        )
        if p.measurement and p.measurement.get("current_density_range_a_m2"):
            lo, hi = p.measurement["current_density_range_a_m2"]
            lines.append(f"  inside the {'measured' if where else 'declared'} {lo:g}-{hi:g} A/m2")
        lines.append(
            f"  duty {product.value:.6g} kg/h: active area {_v(s, 'total_active_area_m2')}, "
            f"{_v(s, 'cells_required')} cells required, at most {_v(s, 'max_cells_per_stack')} "
            "per stack"
        )
        lines.append(
            f"  {s.arrangement}: stack {_v(s, 'stack_voltage_v')} x {_v(s, 'stack_current_a')},"
            f" bus {_v(s, 'bus_current_a')}"
        )
        lines.append(
            f"  DC power {_v(s, 'dc_power_kw')}"
            + (f" (AC {_v(s, 'ac_power_kw')})" if "ac_power_kw" in s.values else "")
            + f", output {_v(s, 'product_output_kg_h')} (margin "
            f"{s.values['output_margin'].value:+.2%}), {_v(s, 'electricity_kwh_per_kg')}"
            + (f", heat to remove {_v(s, 'heat_duty_kw')}" if "heat_duty_kw" in s.values else "")
        )
        lines.append(
            f"  stack envelope {_v(s, 'stack_length_m')} x {_v(s, 'stack_width_m')} x "
            f"{_v(s, 'stack_height_m')}"
            + (
                f"; footprint {_v(s, 'footprint_m2')} with clearances"
                if "footprint_m2" in s.values
                else ""
            )
            + (
                f"; {_v(s, 'cells_replaced_per_year')} cells replaced"
                if "cells_replaced_per_year" in s.values
                else ""
            )
        )
        if s.duty is not None:
            d = s.duty
            lines.append(
                f"  duty {d['id']} at {d['arrangement']} (run {d['run_fingerprint']}): ended by "
                f"{d['ended']} at {_g(d['simulated_h'])} h of {_g(d['campaign_h'])} h, "
                f"feasible: {'yes' if d['feasible'] else 'no'}"
            )
            if d["feasible"]:
                lines.append(
                    f"  reservoir working volume {_v(s, 'reservoir_working_volume_l')}, dosed "
                    f"{_v(s, 'dosing_solution_l')}, bled {_v(s, 'bleed_l')} over the campaign"
                )
        for e in s.equipment:
            values = ", ".join(
                f"{k} {'TBD' if x.provenance == 'tbd' else f'{x.value:.4g}'}"
                + (f" {x.unit}" if x.unit and x.provenance != "tbd" else "")
                for k, x in e.values.items()
            )
            target = (
                f"{EQUIPMENT_LIST} dimensions"
                if e.target == "dimensions"
                else f"{DATASHEET_DIR}/{e.tag}.yaml type_specific"
            )
            mark = " ASSUMED" if e.assumed else ""
            lines.append(
                f"  {e.tag} ({e.role.replace('_', ' ')}) -> {target}: {values}{mark}"
                f" [{e.status or 'not compared'}]"
            )
        for text in s.limitations:
            lines.append(f"  limitation: {text}")
    for text in LIMITATIONS:
        lines.append(f"limitation: {text}")
    lines += [f.format() for f in report.findings]
    return "\n".join(lines)


def _g(value: float | None) -> str:
    return "-" if value is None else f"{value:.6g}"
