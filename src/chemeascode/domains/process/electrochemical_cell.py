"""Schema ``cheme/electrochemical-cells/v1`` (``process/cells.yaml``) and the steady-state
Faraday balance of an electrochemical cell: products, charge, electricity and heat.

A cell names an overall reaction of ``process/reactions.yaml`` (stoichiometry over the
components of ``process/materials.yaml``, with its ``heat_of_reaction``), the electrons
transferred per extent of it, its electrode half-reactions, the current through each of its
cells in series, the Faradaic (current) efficiency, the cell voltage, where formed products
cross over or are purged, its thermal boundary and the operating range its data hold for.
The performance is **specified**: the voltage and the efficiencies are inputs (measured,
vendor or literature figures); no polarisation curve, Nernst or Butler-Volmer model predicts
them, and a cell asking for ``performance: predictive`` is refused.

:func:`cell_report` evaluates every cell (model :data:`MODEL`):

- extent ``xi = FE * N * I / (n F)`` of the overall reaction, and of each declared side
  reaction with its current fraction; the current no reaction is given (``1 - FE - sum f``)
  causes no net chemical change (recombination of crossed-over products, shunt currents) and
  becomes heat;
- the charge balance (the charge the extents carry plus the unassigned current equals
  ``N * I``), the element balance of every reaction and of the formed flows, and, with
  electrode reactions, the element and charge balance of each half-reaction and that they add
  up to the overall reaction (components dissociated into ions by ``dissociation:``);
- the electric power ``P = N * U * I`` at the cell terminals (DC), counted once; the
  thermoneutral voltage ``U_tn = dH / (n F)``; the heat to be removed at the isothermal
  boundary ``Q = P - sum xi dH`` (negative: heat to be supplied), so that electricity in equals
  reaction enthalpy plus heat out; and the electricity per kg of each product (formed and
  delivered), which never includes ``Q``;
- with a ``flowsheet:`` link, the step's electricity and heat streams against ``P`` and ``Q``,
  and no further energy stream at the step (it would count electricity or heat twice).

Rules (``cheme.cell-*``), each finding naming the file, line, rule and a hint:

- ``cell-schema``: the file does not follow the schema; ``cell-duplicate-id``;
- ``cell-reaction``: the reaction (or a side reaction) is not in ``process/reactions.yaml``,
  or a component it names is not declared;
- ``cell-input-missing`` (error, the cell is refused): no current, no Faradaic efficiency, no
  voltage, no thermal boundary, or a reaction without ``heat_of_reaction``;
- ``cell-unsupported`` (error, refused): ``performance: predictive`` or an ``adiabatic``
  boundary (no stream enthalpies in v1);
- ``cell-charge``: the current fractions add up to more than 1;
- ``cell-element-balance``: a reaction, a half-reaction or a dissociation does not balance its
  atoms; ``cell-charge-balance``: a half-reaction or dissociation does not balance its charge;
- ``cell-electrodes``: the anode does not release electrons, the cathode does not take them,
  or the half-reactions scaled to ``electrons`` do not add up to the overall reaction (with a
  balance error of a half-reaction or dissociation, the cell is refused: its electron count is
  in doubt);
- ``cell-crossover``: a crossover or purge for a component that is no product, without a home
  electrode, or fractions above 1;
- ``cell-voltage`` (warning): the voltage is below the reversible voltage given;
- ``cell-operating-range`` (warning): the temperature or current density lies outside the
  declared range; (info) no range declared;
- ``cell-unsourced`` (info): the voltage or an efficiency is assumed or has no source;
- ``cell-temperature`` (info): the heat of reaction is taken at another temperature than the
  cell's (sensible heat and the temperature dependence of dH are left out);
- ``cell-flowsheet``: the linked step or stream does not exist or does not touch the step;
  ``cell-flowsheet-duty`` (warning): a linked stream's duty differs from ``P`` or ``Q``;
  ``cell-double-count``: one stream named as electricity and heat (error), or another energy
  stream at the step (warning).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, ValidationError, model_validator

from chemeascode.domains.chemistry.formulas import molar_mass, parse_formula
from chemeascode.domains.chemistry.reactions import (
    REACTIONS_FILE,
    Reaction,
    Reactions,
    element_change,
    element_flows,
)
from chemeascode.domains.process import FLOWSHEET_FILE, MATERIALS_FILE
from chemeascode.domains.process.schema import DUTY_UNITS, Materials, Quantity
from chemeascode.foundation.findings import Finding
from chemeascode.foundation.schema_base import Strict, unsupported_schema
from chemeascode.foundation.units import to_kelvin
from chemeascode.foundation.yamlsource import _compose, _yaml_line

SCHEMA = "cheme/electrochemical-cells/v1"
CELLS_FILE = "process/cells.yaml"
#: C/mol, CODATA 2018 (exact since the 2019 SI redefinition: N_A e).
FARADAY = 96485.33212
#: The model this module evaluates, as recorded with every result.
MODEL = {"id": "faraday-balance", "version": 1, "schema": SCHEMA}

ASSUMPTIONS = (
    "steady state; Faraday's law: extent = current efficiency x N x I / (n F), "
    "F = 96485.33212 C/mol (CODATA 2018)",
    "specified performance: cell voltage and current efficiencies are inputs; no polarisation "
    "curve, Nernst or Butler-Volmer model (no predictive electrochemistry)",
    "current not assigned to a reaction (1 - FE - side fractions) causes no net chemical "
    "change (recombination of crossed-over products, shunt currents): its electricity becomes "
    "heat",
    "isothermal boundary: feeds and products at the temperature of the heats of reaction; "
    "Q = P - sum(extent x dH); electricity counted once, as the DC power at the cell terminals "
    "(rectifier, transformer and busbar losses are outside the cell)",
    "crossover and purge divide the formed products between outlets; they do not change the "
    "extents (no further reaction of a crossed-over product)",
)
LIMITATIONS = (
    "electrolyte properties (activities, heats of dilution, conductivity) are not modelled: "
    "the heats of reaction are those of process/reactions.yaml, on their own standard states "
    "(a linked dependency on electrolyte thermodynamics, pre-release issue 364)",
    "no adiabatic boundary, temperature rise or stream enthalpies (v1)",
    "one current efficiency for the overall reaction: below 1 it reduces every product alike, "
    "and the current lost is heat, not chemistry; in a chlor-alkali cell the cathode forms H2 "
    "at about 100 % while hydroxide back-migration forms hypochlorite, chlorate and O2 "
    "(EU BREF 2014, 1.4.2: 1.070-1.128 t NaOH/t Cl2), so H2 and NaOH below a current "
    "efficiency of 1 are approximate (the electricity per t Cl2 is not affected); declare side "
    "reactions with their current fractions to include them",
    "no polarisation curve: a voltage or efficiency outside the declared operating range is "
    "flagged, never extrapolated",
    "not a unit of the DWSIM simulation (process/simulation.yaml): a linked flowsheet step is "
    "balanced with the cell's specified values",
)
#: The reference cases this model is qualified against (tests/test_electrochemical_cell.py).
QUALIFIED = (
    {
        "case": "water electrolysis, H2O(l) -> H2 + 1/2 O2, n = 2 (PEM half-reactions)",
        "test": "tests/test_electrochemical_cell.py::test_water_electrolysis_reference",
        "checks": "thermoneutral voltage from CODATA dfH(H2O, l); electricity per kg H2 "
        "against the US DOE PEM stack targets at 1.9, 1.8 and 1.6 V (rounded to 1 kWh/kg); "
        "at U_tn the electricity per kg equals the HHV of H2 and Q = 0",
        "range": "1.6-1.9 V per cell, current efficiency 0.975-1, enthalpy basis 298.15 K",
    },
    {
        "case": "chlor-alkali membrane cell, 2 NaCl + 2 H2O -> Cl2 + H2 + 2 NaOH, n = 2",
        "test": "tests/test_electrochemical_cell.py::test_chlor_alkali_reference",
        "checks": "thermoneutral voltage from CODATA ion enthalpies (infinite dilution); "
        "products per t Cl2 against the EU BREF's electrochemical unit (1.128 t NaOH, 28 kg H2); "
        "electricity per t Cl2 at 3.0 V and 95 % against the BREF's bipolar membrane range",
        "range": "3.0 V at 6 kA/m2, current efficiency 0.95, enthalpy basis 298.15 K",
    },
)

_CURRENT = {"A": 1.0, "kA": 1e3, "MA": 1e6}
_VOLTAGE = {"V": 1.0, "mV": 1e-3}
_AREA = {"m2": 1.0, "cm2": 1e-4}
_FRACTION = {None: 1.0, "-": 1.0, "1": 1.0, "%": 0.01}
#: K: a heat of reaction this far from the cell temperature is reported (cell-temperature).
_TEMPERATURE_GAP = 5.0
_ELECTRON = "e-"
_ION = re.compile(r"^(?P<formula>.+?)(?P<sign>[+-])(?P<n>\d*)$")


# -- schema -------------------------------------------------------------------------------------


class HalfReaction(Strict):
    """One electrode's reaction: species are component ids, ions (``OH-``, ``Na+``, ``SO4-2``)
    or ``e-``; negative for reactants, positive for products."""

    equation: str = Field(default="", description="As text, for readers (not parsed).")
    species: dict[str, float] = Field(min_length=2)


class Electrodes(Strict):
    anode: HalfReaction = Field(description="The oxidation: releases electrons (e- > 0).")
    cathode: HalfReaction = Field(description="The reduction: takes electrons (e- < 0).")


class SideReaction(Strict):
    """A reaction of ``process/reactions.yaml`` that takes part of the current (a Faradaic
    loss that forms something, e.g. oxygen at a chlorine anode)."""

    reaction: str
    electrons: float = Field(gt=0, description="Electrons per extent of the reaction.")
    current_fraction: Quantity = Field(description="Of the current, 0..1 (or %).")


class ThermalBoundary(Strict):
    kind: Literal["isothermal", "adiabatic"] = Field(
        default="isothermal",
        description="isothermal: the heat duty Q = P - sum(extent dH) is removed (or supplied) "
        "at the cell temperature; adiabatic: not supported in v1.",
    )
    temperature: Quantity = Field(description="The cell's operating temperature (K or °C).")


class OperatingRange(Strict):
    """Where the specified voltage and efficiencies hold (from the source of the data)."""

    temperature: tuple[float, float] | None = Field(default=None, description="K, min and max")
    current_density: tuple[float, float] | None = Field(
        default=None, description="A/m2, min and max (needs active_area)"
    )
    source: str = ""

    @model_validator(mode="after")
    def _ordered(self) -> OperatingRange:
        for name in ("temperature", "current_density"):
            value = getattr(self, name)
            if value is not None and not 0 <= value[0] < value[1]:
                raise ValueError(f"{name} is (min, max) with 0 <= min < max")
        return self


class FlowsheetLink(Strict):
    """The flowsheet block or step this cell is, and its energy streams."""

    step: str = Field(description="A step id, or a block without steps, of the flowsheet.")
    case: str | None = Field(default=None, description="Default: the flowsheet's default case.")
    electricity: str | None = Field(
        default=None, description="The energy stream into the step carrying P."
    )
    heat: str | None = Field(
        default=None, description="The energy stream carrying Q (out of the step when Q > 0)."
    )


class Cell(Strict):
    id: str
    title: str = ""
    performance: Literal["specified", "predictive"] = Field(
        default="specified",
        description="specified: voltage and efficiencies are given; predictive (a polarisation "
        "model) is not supported and refused.",
    )
    reaction: str = Field(description="The overall reaction: an id of process/reactions.yaml.")
    electrons: float = Field(gt=0, description="Electrons per extent of the overall reaction.")
    electrodes: Electrodes | None = None
    dissociation: dict[str, dict[str, float]] = Field(
        default_factory=dict,
        description="Component id -> its ions in the electrolyte (NaCl: {Na+: 1, Cl-: 1}), to "
        "check the half-reactions against the overall reaction.",
    )
    cells: int = Field(default=1, ge=1, description="Cells in series carrying the current.")
    current: Quantity | None = Field(default=None, description="Through each cell (A, kA).")
    active_area: Quantity | None = Field(
        default=None, description="Of one cell (m2, cm2): the current density."
    )
    faradaic_efficiency: Quantity | None = Field(
        default=None, description="Fraction of the current forming the overall reaction."
    )
    voltage: Quantity | None = Field(default=None, description="Per cell, at the terminals (V).")
    reversible_voltage: Quantity | None = Field(
        default=None, description="Per cell (V), from dG / (n F): the voltage efficiency."
    )
    side_reactions: list[SideReaction] = Field(default_factory=list)
    crossover: dict[str, float] = Field(
        default_factory=dict,
        description="Product -> fraction of it formed that leaves with the other electrode's "
        "outlet.",
    )
    purge: dict[str, float] = Field(
        default_factory=dict, description="Product -> fraction of it formed that is purged."
    )
    thermal: ThermalBoundary | None = None
    operating_range: OperatingRange | None = None
    electrolyte: str = Field(
        default="", description="The electrolyte (free text); its properties are not modelled."
    )
    flowsheet: FlowsheetLink | None = None
    sources: list[str] = Field(default_factory=list)


class Cells(Strict):
    """The electrochemical cells of the process."""

    schema_: str = Field(alias="schema", description=f"Always {SCHEMA}.")
    kind: Literal["electrochemical_cells"]
    cells: list[Cell] = Field(default_factory=list)

    @model_validator(mode="after")
    def _version(self) -> Cells:
        if self.schema_ != SCHEMA:
            raise ValueError(unsupported_schema(self.schema_, SCHEMA))
        return self


# -- results ------------------------------------------------------------------------------------


@dataclass
class CellResult:
    """One cell's Faraday balance; ``refused`` when an input it needs is missing or unsupported
    (the numbers are then absent)."""

    id: str
    reaction: str
    line: int | None = None
    refused: bool = False
    reasons: list[str] = field(default_factory=list)
    current_a: float | None = None
    cells: int = 1
    current_density_a_m2: float | None = None
    temperature_k: float | None = None
    voltage_v: float | None = None
    faradaic_efficiency: float | None = None
    unassigned_current_fraction: float | None = None
    #: kmol/h by reaction id
    extents: dict[str, float] = field(default_factory=dict)
    #: component -> kmol/h formed (negative: consumed) and kg/h
    formed_kmol_h: dict[str, float] = field(default_factory=dict)
    formed_kg_h: dict[str, float] = field(default_factory=dict)
    #: product -> {home, outlet_kg_h, crossover_kg_h, purge_kg_h}
    products: dict[str, dict[str, Any]] = field(default_factory=dict)
    charge: dict[str, float] = field(default_factory=dict)
    elements_residual_kmol_h: dict[str, float] = field(default_factory=dict)
    thermoneutral_voltage_v: float | None = None
    reversible_voltage_v: float | None = None
    power_kw: float | None = None
    reaction_enthalpy_kw: float | None = None
    heat_duty_kw: float | None = None
    energy_residual_kw: float | None = None
    #: product -> kWh of electricity per kg formed / delivered (the home outlet)
    electricity_kwh_per_kg: dict[str, dict[str, float | None]] = field(default_factory=dict)
    voltage_efficiency: dict[str, float] = field(default_factory=dict)
    sourced: bool = False
    sources: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    step: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class CellReport:
    cells: list[CellResult]
    findings: list[Finding]
    source: Any = None

    def as_dict(self) -> dict[str, Any]:
        from chemeascode.foundation.schemas.run import finding_dict

        return {
            "model": MODEL,
            "core_version": _version(),
            "assumptions": list(ASSUMPTIONS),
            "limitations": list(LIMITATIONS),
            "qualified": list(QUALIFIED),
            "cells": [c.as_dict() for c in self.cells],
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


# -- species ------------------------------------------------------------------------------------


def species_atoms(name: str, formulas: dict[str, str]) -> tuple[dict[str, int] | None, int | None]:
    """The atoms and charge of an electrode species: a declared component (its formula,
    neutral), ``e-`` (no atoms, charge -1) or an ion written as formula and charge (``OH-``,
    ``Na+``, ``SO4-2``); (None, None) when neither reads."""
    if name == _ELECTRON:
        return {}, -1
    if name in formulas:
        return parse_formula(formulas[name]), 0
    match = _ION.match(name)
    if match is None:
        return None, None
    atoms = parse_formula(match["formula"])
    if atoms is None:
        return None, None
    n = int(match["n"] or 1)
    return atoms, n if match["sign"] == "+" else -n


def _balance(species: dict[str, float], formulas: dict[str, str]) -> tuple[dict, float] | None:
    """(atoms created by element, charge created) of *species*; None when one is unreadable."""
    atoms: dict[str, float] = {}
    charge = 0.0
    for name, nu in species.items():
        found, z = species_atoms(name, formulas)
        if found is None or z is None:
            return None
        for element, n in found.items():
            atoms[element] = atoms.get(element, 0.0) + nu * n
        charge += nu * z
    return {e: v for e, v in atoms.items() if abs(v) > 1e-9}, charge


def _add(into: dict[str, float], species: dict[str, float], factor: float) -> None:
    for name, nu in species.items():
        into[name] = into.get(name, 0.0) + factor * nu


# -- evaluation ---------------------------------------------------------------------------------


class _Out:
    def __init__(self, doc: Any) -> None:
        self.doc = doc
        self.findings: list[Finding] = []

    def add(self, level: str, rule: str, message: str, loc: list[Any], ids: list[str], hint: str):
        self.findings.append(
            Finding(
                CELLS_FILE,
                level,  # type: ignore[arg-type]
                f"cheme.cell-{rule}",
                message,
                line=_yaml_line(self.doc, loc),
                ids=ids,
                hint=hint,
            )
        )


def _value(
    quantity: Quantity | None, units: dict[Any, float], what: str, out: _Out, loc, cid
) -> float | None:
    if quantity is None:
        return None
    factor = units.get(quantity.unit)
    if factor is None:
        out.add(
            "error",
            "schema",
            f"cell {cid}: {what} in unit {quantity.unit!r}",
            loc,
            [cid],
            "use one of " + ", ".join(str(u) for u in units if u is not None),
        )
        return None
    return quantity.value * factor


def _sourced(quantity: Quantity | None) -> bool:
    return quantity is not None and quantity.provenance == "given" and bool(quantity.source.strip())


def _molar_masses(materials: Materials | None) -> dict[str, float]:
    masses: dict[str, float] = {}
    for c in materials.components if materials is not None else []:
        mass = c.molar_mass or (molar_mass(c.formula) if c.formula else None)
        if mass:
            masses[c.id] = mass
    return masses


def _homes(cell: Cell, products: list[str]) -> dict[str, str]:
    """The electrode each product of the overall reaction is formed at: where it (or one of its
    ions, by ``dissociation:``) is a product of a half-reaction."""
    homes: dict[str, str] = {}
    if cell.electrodes is None:
        return homes
    for product in products:
        names = [product, *cell.dissociation.get(product, {})]
        for side in ("anode", "cathode"):
            half = getattr(cell.electrodes, side).species
            if any(half.get(n, 0.0) > 0 for n in names):
                homes[product] = side
                break
    return homes


def _check_electrodes(cell: Cell, reaction: Reaction, formulas: dict, out: _Out, loc) -> None:
    electrodes = cell.electrodes
    if electrodes is None:
        return
    cid = cell.id
    for component, ions in cell.dissociation.items():
        where = [*loc, "dissociation", component]
        if component not in formulas:
            out.add(
                "error",
                "reaction",
                f"cell {cid}: dissociated component {component} is not declared",
                where,
                [cid, component],
                "name a component of process/materials.yaml",
            )
            continue
        found = _balance({component: -1.0, **ions}, formulas)
        if found is None:
            out.add(
                "error",
                "element-balance",
                f"cell {cid}: the ions of {component} are not readable",
                where,
                [cid, component],
                "write ions as formula and charge, e.g. Na+, OH-, SO4-2",
            )
        elif found[0] or abs(found[1]) > 1e-9:
            out.add(
                "error",
                "element-balance" if found[0] else "charge-balance",
                f"cell {cid}: {component} does not dissociate into {ions} (atoms "
                f"{found[0] or {}}, charge {found[1]:+g})",
                where,
                [cid, component],
                "give the ions with their counts",
            )
    scaled: dict[str, float] = {}
    for side, sign in (("anode", 1), ("cathode", -1)):
        half = getattr(electrodes, side)
        where = [*loc, "electrodes", side]
        electrons = half.species.get(_ELECTRON, 0.0)
        if electrons * sign <= 0:
            out.add(
                "error",
                "electrodes",
                f"cell {cid}: the {side} "
                + ("releases no electrons" if sign > 0 else "takes no electrons"),
                where,
                [cid],
                "an anode's e- is positive (a product), a cathode's negative (a reactant)",
            )
            return
        found = _balance(half.species, formulas)
        if found is None:
            unread = [n for n in half.species if species_atoms(n, formulas)[0] is None]
            out.add(
                "error",
                "element-balance",
                f"cell {cid}: {side} species not readable: {', '.join(unread)}",
                where,
                [cid],
                "a species is a component id, an ion (OH-, Na+, SO4-2) or e-",
            )
            return
        atoms, charge = found
        if atoms:
            text = ", ".join(f"{e} {v:+g}" for e, v in sorted(atoms.items()))
            out.add(
                "error",
                "element-balance",
                f"cell {cid}: the {side} reaction does not balance: atoms created {text}",
                where,
                [cid],
                "correct the coefficients",
            )
        if abs(charge) > 1e-9:
            out.add(
                "error",
                "charge-balance",
                f"cell {cid}: the {side} reaction creates charge {charge:+g}",
                where,
                [cid],
                "count the electrons and the ions' charges",
            )
        _add(scaled, half.species, cell.electrons / abs(electrons))
    overall: dict[str, float] = {}
    for name, nu in reaction.stoichiometry.items():
        _add(overall, cell.dissociation.get(name, {name: 1.0}), nu)
    names = sorted({*scaled, *overall})
    scale = max(abs(v) for v in overall.values()) or 1.0
    differ = {
        n: scaled.get(n, 0.0) - overall.get(n, 0.0)
        for n in names
        if abs(scaled.get(n, 0.0) - overall.get(n, 0.0)) > 1e-9 * scale
    }
    if differ:
        text = ", ".join(f"{n} {v:+g}" for n, v in differ.items())
        out.add(
            "error",
            "electrodes",
            f"cell {cid}: the half-reactions scaled to {cell.electrons:g} electrons do not add "
            f"up to reaction {reaction.id} (difference {text})",
            [*loc, "electrodes"],
            [cid, reaction.id],
            "check the electrons per extent, the half-reactions and dissociation: (ions of "
            "dissolved components)",
        )


def _evaluate(
    cell: Cell,
    index: int,
    reactions: dict[str, Reaction],
    formulas: dict[str, str],
    masses: dict[str, float],
    out: _Out,
) -> CellResult:
    loc = ["cells", index]
    cid = cell.id
    result = CellResult(cid, cell.reaction, line=_yaml_line(out.doc, loc), cells=cell.cells)
    result.step = cell.flowsheet.step if cell.flowsheet is not None else None
    result.sources = list(cell.sources)

    def refuse(rule: str, reason: str, at: list[Any], hint: str) -> None:
        result.refused = True
        result.reasons.append(reason)
        out.add("error", rule, f"cell {cid}: {reason}: refused", at, [cid], hint)

    if cell.performance == "predictive":
        refuse(
            "unsupported",
            "performance: predictive (a polarisation model) is not supported",
            [*loc, "performance"],
            "give the voltage and Faradaic efficiency as specified data with their source",
        )
    reaction = reactions.get(cell.reaction)
    if reaction is None:
        refuse(
            "reaction",
            f"reaction {cell.reaction} is not in {REACTIONS_FILE} (or that file does not load)",
            [*loc, "reaction"],
            f"declare it in {REACTIONS_FILE}",
        )
    side: list[tuple[SideReaction, Reaction | None, int]] = [
        (s, reactions.get(s.reaction), j) for j, s in enumerate(cell.side_reactions)
    ]
    for s, found, j in side:
        if found is None:
            refuse(
                "reaction",
                f"side reaction {s.reaction} is not in {REACTIONS_FILE}",
                [*loc, "side_reactions", j, "reaction"],
                f"declare it in {REACTIONS_FILE}",
            )
    everything = [r for r in [reaction, *(f for _, f, _ in side)] if r is not None]
    for r in everything:
        unknown = [n for n in r.stoichiometry if n not in formulas]
        if unknown:
            refuse(
                "reaction",
                f"reaction {r.id} names undeclared component {', '.join(unknown)}",
                [*loc, "reaction"],
                f"declare it in {MATERIALS_FILE}",
            )
            continue
        change = element_change(r, formulas)
        if change is None:
            refuse(
                "element-balance",
                f"reaction {r.id} has a component without a readable formula",
                [*loc, "reaction"],
                f"give formula: in {MATERIALS_FILE}",
            )
        elif change:
            text = ", ".join(f"{e} {v:+g}" for e, v in sorted(change.items()))
            refuse(
                "element-balance",
                f"reaction {r.id} does not balance (atoms created {text})",
                [*loc, "reaction"],
                f"correct it in {REACTIONS_FILE}",
            )
        if r.heat_of_reaction is None:
            refuse(
                "input-missing",
                f"reaction {r.id} has no heat_of_reaction (thermoneutral voltage, heat duty)",
                [*loc, "reaction"],
                f"give heat_of_reaction (kJ/kmol, with its source) in {REACTIONS_FILE}",
            )
        lacking = [n for n in r.stoichiometry if n not in masses]
        if lacking:
            refuse(
                "input-missing",
                f"no molar mass for {', '.join(lacking)}",
                [*loc, "reaction"],
                f"give formula: or molar_mass: in {MATERIALS_FILE}",
            )
    if reaction is not None and not result.refused:
        before = len(out.findings)
        _check_electrodes(cell, reaction, formulas, out, loc)
        if any(f.level == "error" for f in out.findings[before:]):
            # the electron count the extents rest on is in doubt
            result.refused = True
            result.reasons.append("the electrode reactions are inconsistent")
    if cell.electrodes is None:
        result.limitations.append(
            "no electrode reactions: the charge per electrode, the overall reaction's electron "
            "count and the products' outlets are not checked"
        )
        out.add(
            "info",
            "electrodes",
            f"cell {cid}: no electrode reactions declared",
            loc,
            [cid],
            "give electrodes: anode and cathode half-reactions to check the electron count",
        )

    current = _value(cell.current, _CURRENT, "current", out, [*loc, "current"], cid)
    efficiency = _value(
        cell.faradaic_efficiency,
        _FRACTION,
        "faradaic_efficiency",
        out,
        [*loc, "faradaic_efficiency"],
        cid,
    )
    voltage = _value(cell.voltage, _VOLTAGE, "voltage", out, [*loc, "voltage"], cid)
    missing = {
        "current": (current, "the current through each cell (A or kA)"),
        "faradaic_efficiency": (efficiency, "the Faradaic (current) efficiency, 0..1"),
        "voltage": (voltage, "the cell voltage at the terminals (V)"),
    }
    for name, (value, what) in missing.items():
        if value is None and getattr(cell, name) is None:
            refuse(
                "input-missing",
                f"no {name}",
                loc,
                f"give {name}: {what}, with its provenance and source; it is never assumed",
            )
        elif value is None:
            result.refused = True
            result.reasons.append(f"{name} unreadable")
    if efficiency is not None and not 0 < efficiency <= 1:
        refuse(
            "charge",
            f"faradaic_efficiency {efficiency:g} is not in (0, 1]",
            [*loc, "faradaic_efficiency"],
            "a fraction of the current, 0 < FE <= 1",
        )
    if current is not None and current <= 0:
        refuse("input-missing", "the current is not positive", [*loc, "current"], "give I > 0")
    if voltage is not None and voltage <= 0:
        refuse("input-missing", "the voltage is not positive", [*loc, "voltage"], "give U > 0")
    fractions: list[float] = []
    for s, _, j in side:
        f = _value(
            s.current_fraction,
            _FRACTION,
            "current_fraction",
            out,
            [*loc, "side_reactions", j, "current_fraction"],
            cid,
        )
        fractions.append(f if f is not None else 0.0)
        if f is None or not 0 < f <= 1:
            refuse(
                "charge",
                f"side reaction {s.reaction}: current fraction not in (0, 1]",
                [*loc, "side_reactions", j],
                "a fraction of the current",
            )
    unassigned = 1.0 - (efficiency or 0.0) - sum(fractions)
    if efficiency is not None and unassigned < -1e-9:
        refuse(
            "charge",
            f"the current fractions add up to {1 - unassigned:.6g} > 1",
            loc,
            "faradaic_efficiency plus the side reactions' fractions is at most 1",
        )

    thermal = cell.thermal
    if thermal is None:
        refuse(
            "input-missing",
            "no thermal boundary",
            loc,
            "give thermal: {kind: isothermal, temperature: {value, unit, provenance}}",
        )
    else:
        if thermal.kind == "adiabatic":
            refuse(
                "unsupported",
                "an adiabatic boundary needs stream enthalpies (not in v1)",
                [*loc, "thermal", "kind"],
                "use kind: isothermal and remove Q with a cooling (or heating) stream",
            )
        t = thermal.temperature
        result.temperature_k = to_kelvin(t.value, t.unit or "")
        if result.temperature_k is None:
            refuse(
                "schema",
                f"thermal temperature in unit {t.unit!r}",
                [*loc, "thermal", "temperature"],
                "K or °C",
            )

    area = _value(cell.active_area, _AREA, "active_area", out, [*loc, "active_area"], cid)
    if current is not None and area:
        result.current_density_a_m2 = current / area
    for name, quantity in (
        ("voltage", cell.voltage),
        ("faradaic_efficiency", cell.faradaic_efficiency),
        *((f"side_reactions.{s.reaction}", s.current_fraction) for s, _, _ in side),
    ):
        if quantity is not None and not _sourced(quantity):
            out.add(
                "info",
                "unsourced",
                f"cell {cid}: {name} is {quantity.provenance}"
                + ("" if quantity.source.strip() else " without a source"),
                [*loc, *name.split(".")[:1]],
                [cid],
                "give provenance: given with the source (measured, vendor or literature data)",
            )
    result.sourced = all(
        _sourced(q)
        for q in (cell.voltage, cell.faradaic_efficiency, *(s.current_fraction for s, _, _ in side))
    )
    result.sources += [
        q.source
        for q in (cell.voltage, cell.faradaic_efficiency, cell.current)
        if q is not None and q.source.strip() and q.source not in result.sources
    ]
    _operating_range(cell, result, out, loc)
    if result.refused or reaction is None:
        return result

    assert current is not None and efficiency is not None and voltage is not None
    charge_rate = cell.cells * current  # C/s through the stack
    result.current_a = current
    result.voltage_v = voltage
    result.faradaic_efficiency = efficiency
    result.unassigned_current_fraction = max(unassigned, 0.0)
    shares = [(reaction, cell.electrons, efficiency)] + [
        (r, s.electrons, f) for (s, r, _), f in zip(side, fractions, strict=True) if r is not None
    ]
    formed: dict[str, float] = {}
    enthalpy_w = 0.0
    carried = 0.0
    for r, n, share in shares:
        xi = share * charge_rate / (n * FARADAY)  # mol/s
        result.extents[r.id] = xi * 3.6  # kmol/h
        carried += xi * n * FARADAY
        _add(formed, r.stoichiometry, xi * 3.6)
        hor = r.heat_of_reaction
        assert hor is not None
        enthalpy_w += xi * hor.value  # kJ/kmol == J/mol
        if abs(hor.temperature - (result.temperature_k or hor.temperature)) > _TEMPERATURE_GAP:
            text = (
                f"heat of reaction {r.id} at {hor.temperature:g} K, the cell at "
                f"{result.temperature_k:g} K: the sensible heat of feeds and products and the "
                "temperature dependence of dH are not included"
            )
            result.limitations.append(text)
            out.add(
                "info",
                "temperature",
                f"cell {cid}: {text}",
                [*loc, "thermal", "temperature"],
                [cid, r.id],
                "give heat_of_reaction at the cell temperature to include them",
            )
    unassigned_charge = result.unassigned_current_fraction * charge_rate
    result.charge = {
        "stack_current_a": charge_rate,
        "carried_by_reactions_a": carried,
        "unassigned_a": unassigned_charge,
        "residual_a": charge_rate - carried - unassigned_charge,
    }
    result.formed_kmol_h = {n: v for n, v in formed.items() if v}
    result.formed_kg_h = {n: v * masses[n] for n, v in result.formed_kmol_h.items()}
    in_flows = element_flows({n: -v for n, v in formed.items() if v < 0}, formulas) or {}
    out_flows = element_flows({n: v for n, v in formed.items() if v > 0}, formulas) or {}
    result.elements_residual_kmol_h = {
        e: out_flows.get(e, 0.0) - in_flows.get(e, 0.0) for e in sorted({*in_flows, *out_flows})
    }

    power_w = charge_rate * voltage
    hor = reaction.heat_of_reaction
    assert hor is not None
    result.thermoneutral_voltage_v = hor.value / (cell.electrons * FARADAY)
    result.power_kw = power_w / 1000
    result.reaction_enthalpy_kw = enthalpy_w / 1000
    result.heat_duty_kw = (power_w - enthalpy_w) / 1000
    result.energy_residual_kw = result.power_kw - result.reaction_enthalpy_kw - result.heat_duty_kw
    result.voltage_efficiency["thermoneutral"] = result.thermoneutral_voltage_v / voltage
    reversible = _value(
        cell.reversible_voltage,
        _VOLTAGE,
        "reversible_voltage",
        out,
        [*loc, "reversible_voltage"],
        cid,
    )
    if reversible is not None:
        result.reversible_voltage_v = reversible
        result.voltage_efficiency["reversible"] = reversible / voltage
        if voltage < reversible:
            out.add(
                "warning",
                "voltage",
                f"cell {cid}: voltage {voltage:g} V is below the reversible voltage "
                f"{reversible:g} V: no electrolysis",
                [*loc, "voltage"],
                [cid],
                "check the voltage per cell (not per stack) and the reversible voltage",
            )

    products = [n for n, v in reaction.stoichiometry.items() if v > 0]
    homes = _homes(cell, products)
    for what, split in (("crossover", cell.crossover), ("purge", cell.purge)):
        for name, fraction in split.items():
            problem = ""
            if name not in products:
                problem = f"{name} is no product of reaction {reaction.id}"
            elif what == "crossover" and name not in homes:
                problem = f"{name} has no home electrode (no electrode reaction forms it)"
            elif not 0 <= fraction <= 1:
                problem = f"fraction {fraction:g} not in [0, 1]"
            if problem:
                out.add(
                    "error",
                    "crossover",
                    f"cell {cid}: {what} {problem}",
                    [*loc, what, name],
                    [cid, name],
                    "a fraction of a product formed; crossover needs the electrode reactions",
                )
    for name in products:
        kg = result.formed_kg_h.get(name, 0.0)
        cross = min(max(cell.crossover.get(name, 0.0), 0.0), 1.0)
        purge = min(max(cell.purge.get(name, 0.0), 0.0), 1.0)
        outlet = max(kg * (1 - cross - purge), 0.0)
        result.products[name] = {
            "home": homes.get(name),
            "formed_kg_h": kg,
            "outlet_kg_h": outlet,
            "crossover_kg_h": kg * cross,
            "purge_kg_h": kg * purge,
        }
        if cross + purge > 1 + 1e-9:
            out.add(
                "error",
                "crossover",
                f"cell {cid}: crossover and purge of {name} add up to more than 1",
                [*loc, "crossover", name],
                [cid, name],
                "fractions of the product formed",
            )
        result.electricity_kwh_per_kg[name] = {
            "formed": result.power_kw / kg if kg else None,
            "delivered": result.power_kw / outlet if outlet else None,
        }
    return result


def _operating_range(cell: Cell, result: CellResult, out: _Out, loc: list[Any]) -> None:
    span = cell.operating_range
    cid = cell.id
    if span is None:
        result.limitations.append("no operating range declared for the specified performance")
        out.add(
            "info",
            "operating-range",
            f"cell {cid}: no operating range declared",
            loc,
            [cid],
            "give operating_range: (temperature, current_density) from the source of the data",
        )
        return
    checks = [
        ("temperature", result.temperature_k, span.temperature, "K"),
        ("current_density", result.current_density_a_m2, span.current_density, "A/m2"),
    ]
    for name, value, bounds, unit in checks:
        if bounds is None:
            continue
        if value is None:
            result.limitations.append(f"{name} not known: its operating range is not checked")
            continue
        if not bounds[0] <= value <= bounds[1]:
            out.add(
                "warning",
                "operating-range",
                f"cell {cid}: {name} {value:.6g} {unit} outside the declared range "
                f"{bounds[0]:g}-{bounds[1]:g} {unit}",
                [*loc, "operating_range", name],
                [cid],
                "the specified voltage and efficiency do not hold there: give data for this "
                "operating point",
            )


def _flowsheet_checks(root: Path, cells: Cells, results: list[CellResult], out: _Out) -> None:
    linked = [(i, c) for i, c in enumerate(cells.cells) if c.flowsheet is not None]
    if not linked or not (root / FLOWSHEET_FILE).is_file():
        for i, c in linked:
            out.add(
                "error",
                "flowsheet",
                f"cell {c.id}: links step {c.flowsheet.step}, but there is no {FLOWSHEET_FILE}",
                ["cells", i, "flowsheet"],
                [c.id],
                "remove flowsheet: or add the flowsheet",
            )
        return
    from chemeascode.domains.process.model import load

    process, _ = load(root)
    if process is None:
        return  # the flowsheet's own findings say why
    by_id = {r.id: r for r in results}
    fs = process.flowsheet
    nodes = {n.id: n for n in [*fs.steps, *fs.blocks]}
    streams = {s.id: s for s in fs.streams}
    first: dict[str, str] = {}
    for i, cell in linked:
        step = cell.flowsheet.step  # type: ignore[union-attr]
        if step in first:
            out.add(
                "warning",
                "flowsheet",
                f"cell {cell.id}: step {step} is also linked by cell {first[step]}",
                ["cells", i, "flowsheet", "step"],
                [cell.id, first[step], step],
                "link each cell to its own step; the step is sourced only if every cell is",
            )
        first.setdefault(step, cell.id)
    for i, cell in linked:
        link = cell.flowsheet
        assert link is not None
        loc = ["cells", i, "flowsheet"]
        node = nodes.get(link.step)
        if node is None:
            out.add(
                "error",
                "flowsheet",
                f"cell {cell.id}: step {link.step} is not in {FLOWSHEET_FILE}",
                [*loc, "step"],
                [cell.id, link.step],
                "name a step or block of the flowsheet",
            )
            continue
        if node.reactions and cell.reaction not in node.reactions:
            out.add(
                "warning",
                "flowsheet",
                f"cell {cell.id}: step {link.step} lists reactions {node.reactions}, not "
                f"{cell.reaction}",
                [*loc, "step"],
                [cell.id, link.step],
                "list the cell's reaction on the step",
            )
        case = link.case or fs.default_case()
        if case not in {c.id for c in fs.cases}:
            out.add(
                "error",
                "flowsheet",
                f"cell {cell.id}: case {case} is not declared",
                [*loc, "case"],
                [cell.id],
                "name a case of the flowsheet",
            )
            continue
        if link.electricity and link.electricity == link.heat:
            out.add(
                "error",
                "double-count",
                f"cell {cell.id}: stream {link.electricity} is named as electricity and heat",
                loc,
                [cell.id, link.electricity],
                "electricity and heat are separate energy streams; each is counted once",
            )
            continue
        result = by_id.get(cell.id)
        for what, sid in (("electricity", link.electricity), ("heat", link.heat)):
            if sid is None:
                continue
            stream = streams.get(sid)
            start, end = process.ends(stream) if stream is not None else (None, None)
            at_step = (getattr(start, "node", None), getattr(end, "node", None))
            if stream is None or stream.kind != "energy" or link.step not in at_step:
                out.add(
                    "error",
                    "flowsheet",
                    f"cell {cell.id}: {what} stream {sid} is not an energy stream of step "
                    f"{link.step}",
                    [*loc, what],
                    [cell.id, sid],
                    "name an energy stream that starts or ends at the step",
                )
                continue
            if what == "electricity" and at_step[1] != link.step:
                out.add(
                    "error",
                    "flowsheet",
                    f"cell {cell.id}: electricity stream {sid} does not flow into {link.step}",
                    [*loc, what],
                    [cell.id, sid],
                    "the electricity stream ends at the cell",
                )
                continue
            state = stream.state.get(case)
            duty = state.duty if state is not None else None
            if result is None or result.refused or duty is None:
                continue
            factor = DUTY_UNITS.get(duty.unit or fs.units.duty)
            if factor is None:
                continue
            kw = duty.value * factor
            if what == "electricity":
                expected = result.power_kw
            else:  # heat leaving the step counts positive
                expected = result.heat_duty_kw if at_step[0] == link.step else -result.heat_duty_kw
            assert expected is not None
            from chemeascode.domains.process.energy import ENERGY_TOLERANCE

            tol = ENERGY_TOLERANCE["abs_kW"] + ENERGY_TOLERANCE["rel_duty"] * abs(expected)
            if abs(kw - expected) > tol:
                out.add(
                    "warning",
                    "flowsheet-duty",
                    f"cell {cell.id}: {what} stream {sid} carries {kw:.6g} kW in case {case}, "
                    f"the cell {expected:.6g} kW",
                    [*loc, what],
                    [cell.id, sid],
                    "write the cell's power (electricity) and heat duty (Q = P - extent dH) on "
                    "the streams",
                )
        named = {link.electricity, link.heat} - {None}
        for stream in fs.streams:
            if stream.kind != "energy" or stream.id in named:
                continue
            start, end = process.ends(stream)
            if link.step in (getattr(start, "node", None), getattr(end, "node", None)):
                out.add(
                    "warning",
                    "double-count",
                    f"cell {cell.id}: energy stream {stream.id} at step {link.step} is neither "
                    "its electricity nor its heat stream",
                    loc,
                    [cell.id, stream.id],
                    "the cell's power and heat duty account for all its energy; name the "
                    "stream as electricity: or heat:, or remove it",
                )


# -- loading ------------------------------------------------------------------------------------


def _load[T](root: Path, name: str, model: type[T], rule: str) -> tuple[T | None, Any, list]:
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
                    hint="see `cheme schema process-cells`",
                )
                for e in failure.errors()
            ],
        )


def has_cells(root: Path) -> bool:
    return (Path(root) / CELLS_FILE).is_file()


def cell_report(root: Path) -> CellReport:
    """Every cell of ``process/cells.yaml`` under *root* (see the module docstring). Read-only.
    A missing or invalid materials or reactions file refuses the cells that need it; a missing
    cells file gives an empty report."""
    from chemeascode.foundation.provenance import source_revision

    root = Path(root)
    inputs = [CELLS_FILE, MATERIALS_FILE, REACTIONS_FILE, FLOWSHEET_FILE]
    cells, doc, findings = _load(root, CELLS_FILE, Cells, "cheme.cell-schema")
    source = source_revision(root, inputs)
    if cells is None:
        return CellReport([], findings, source)
    materials, _, _ = _load(root, MATERIALS_FILE, Materials, "cheme.cell-schema")
    reactions, _, _ = _load(root, REACTIONS_FILE, Reactions, "cheme.cell-schema")
    formulas = {c.id: c.formula for c in materials.components} if materials else {}
    masses = _molar_masses(materials)
    known = reactions.by_id() if reactions is not None else {}
    out = _Out(doc)
    out.findings += findings
    seen: set[str] = set()
    results = []
    for index, cell in enumerate(cells.cells):
        if cell.id in seen:
            out.add(
                "error",
                "duplicate-id",
                f"cell {cell.id} is declared twice",
                ["cells", index],
                [cell.id],
                "give each cell its own id",
            )
        seen.add(cell.id)
        results.append(_evaluate(cell, index, known, formulas, masses, out))
    _flowsheet_checks(root, cells, results, out)
    return CellReport(results, out.findings, source)


def cell_bases(report: CellReport) -> dict[str, Any]:
    """The model basis (:class:`~.model_basis.UnitBasis`) of each flowsheet step a cell is
    linked to, by step id: ``electrochemical-cell``, specified (never predictive), sourced
    when the voltage and current efficiencies are given with a source and the cell is not
    refused. A step several cells are linked to is sourced only when every one of them is."""
    from chemeascode.domains.process.model_basis import UnitBasis

    bases: dict[str, Any] = {}
    for cell in report.cells:
        if cell.step is None:
            continue
        problems = list(cell.reasons)
        if not cell.sourced:
            problems.append("voltage or current efficiency assumed or without a source")
        if cell.step in bases and (not bases[cell.step].sourced or not problems):
            continue  # the step keeps the basis of its first unsourced (or first) cell
        bases[cell.step] = UnitBasis(
            cell.step,
            "reactor",
            "electrochemical-cell",
            False,
            not problems,
            file=CELLS_FILE,
            line=cell.line,
            detail=f"specified electrochemical cell {cell.id} (voltage, current efficiency): "
            f"Faraday balance {MODEL['id']} v{MODEL['version']}"
            + (": " + "; ".join(problems) if problems else ""),
            sources=list(cell.sources),
            assumptions=list(ASSUMPTIONS),
            limitations=[
                "specified cell performance: voltage and current efficiency are not predicted",
                *cell.limitations,
            ],
        )
    return bases


def _g(value: float | None) -> str:
    return "-" if value is None else f"{value:.4g}"


def report_text(report: CellReport) -> str:
    lines = [f"model {MODEL['id']} v{MODEL['version']} ({SCHEMA}), core {_version()}"]
    for c in report.cells:
        if c.refused:
            lines.append(f"{c.id}: refused ({'; '.join(c.reasons)})")
            continue
        lines.append(
            f"{c.id}: reaction {c.reaction}, {c.cells} cell(s) x {c.current_a:g} A at "
            f"{c.voltage_v:g} V, current efficiency {c.faradaic_efficiency:g}"
        )
        lines.append(
            f"  power {c.power_kw:.6g} kW = reaction enthalpy {c.reaction_enthalpy_kw:.6g} kW "
            f"+ heat to remove {c.heat_duty_kw:.6g} kW (U_tn {c.thermoneutral_voltage_v:.4f} V)"
        )
        for name, row in c.products.items():
            specific = c.electricity_kwh_per_kg[name]
            lines.append(
                f"  {name}: formed {row['formed_kg_h']:.6g} kg/h, outlet {row['outlet_kg_h']:.6g}"
                f" kg/h ({row['home'] or 'electrode not known'}); "
                f"{_g(specific['formed'])} kWh/kg formed, {_g(specific['delivered'])} kWh/kg "
                "delivered (all the cell's electricity, not allocated)"
            )
        for text in c.limitations:
            lines.append(f"  limitation: {text}")
    lines += [f.format() for f in report.findings]
    return "\n".join(lines)
