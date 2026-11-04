"""Schema ``cheme/electrochemical-cells/v1`` (``process/cells.yaml``) and the steady-state
Faraday balance of an electrochemical cell: products, charge, electricity and heat.

A cell names an overall reaction of ``process/reactions.yaml`` (stoichiometry over the
components of ``process/materials.yaml``, with its ``heat_of_reaction``), the electrons
transferred per extent of it, its electrode half-reactions, the current through each of its
cells in series, the Faradaic (current) efficiency, the cell voltage, where formed products
cross over or are purged, its thermal boundary and the operating range its data hold for.
The performance is **specified**: the voltage and the efficiencies are inputs (measured,
vendor or literature figures); no polarisation curve, Nernst or Butler-Volmer model predicts
them, and a cell asking for ``performance: predictive`` is refused. A cell with
``performance: measured`` takes them from a measured series
(``experiments/electrochemistry/<id>.yaml``, :mod:`chemeascode.domains.experiments.
electrochemistry`) at its current density ``I / A``, interpolated between the measured points
and refused outside the series' validity range (never extrapolated); the Faradaic efficiencies
of the measurement's side products become the current fractions of the side reactions they
name. An optional ``membrane:`` block reports the membrane's water dissociation efficiency
(given, or measured), the co-ion fluxes ``f_i (1 - WDE) N I / (|z_i| F)`` and the anolyte
hydroxide deficit ``(1 - WDE) N I / F``, apart from the Faradaic efficiency, which it never
changes.

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
- ``cell-measurement`` (error, refused): a measured cell's measurement file is missing, has
  error findings, or lacks the product named; the product is formed by another reaction than
  the cell's (or, with no ``reaction:`` in the measurement, is no product of it); a side
  product forms at the other electrode than the product; a side product's measured Faradaic
  efficiency is outside [0, 1]; ``measurements:`` on a cell that is not
  ``performance: measured``; (info) a side product that forms none of the cell's side
  reactions (its current is unassigned); (info) measured Faradaic efficiencies that add up to
  more than 1 (within the measurement's tolerance) are scaled to add up to 1;
  ``cell-measured-conflict`` (warning): a voltage, efficiency or water dissociation efficiency
  stated in the cell differs from the measured one by more than the replicates' standard
  deviation (the measured value is used); a measured cell outside the measurement's current
  density or temperature range is refused with ``cell-operating-range`` (error);
- ``cell-membrane``: co-ion shares that do not add up to 1, an unreadable ion or a water
  dissociation efficiency outside [0, 1] (error); no water dissociation efficiency (info);
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
from chemeascode.domains.experiments.electrochemistry import FARADAY as _FARADAY
from chemeascode.domains.process import FLOWSHEET_FILE, MATERIALS_FILE
from chemeascode.domains.process.schema import DUTY_UNITS, Materials, Quantity
from chemeascode.foundation.findings import Finding
from chemeascode.foundation.schema_base import Strict, unsupported_schema
from chemeascode.foundation.units import to_kelvin
from chemeascode.foundation.yamlsource import _compose, _yaml_line

SCHEMA = "cheme/electrochemical-cells/v1"
CELLS_FILE = "process/cells.yaml"
#: C/mol, CODATA 2018 (exact since the 2019 SI redefinition: N_A e); one constant with the
#: measurement processing.
FARADAY = _FARADAY
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
    "(a linked dependency on electrolyte thermodynamics)",
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
    current_fraction: Quantity | None = Field(
        default=None,
        description="Of the current, 0..1 (or %); a measured cell takes it from the "
        "measurement's side product that names this reaction.",
    )


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


class MeasurementLink(Strict):
    """The measured series a cell's voltage and efficiencies are looked up in."""

    file: str = Field(description="experiments/electrochemistry/<id>.yaml, from the root.")
    product: str = Field(description="The measurement's product the overall reaction forms.")
    side_products: list[str] = Field(
        default_factory=list,
        description="Products whose Faradaic efficiency becomes the current fraction of the "
        "side reaction their measurement entry names (reaction:).",
    )


class CellMembrane(Strict):
    """The membrane between the electrodes and the ions it carries: what is not water
    dissociation (bipolar membrane) is carried by co-ions."""

    kind: Literal["bipolar", "cation_exchange", "anion_exchange", "diaphragm", "none"]
    bias: Literal["forward", "reverse"] | None = None
    water_dissociation_efficiency: Quantity | None = Field(
        default=None,
        description="Share of the current carried by water dissociation, 0..1 (a measured "
        "cell takes it from the measurement).",
    )
    co_ion_crossover: dict[str, float] = Field(
        default_factory=dict,
        description="Ion (K+, HCO3-, CO3-2) -> its share of the current not carried by water "
        "dissociation; the shares add up to 1.",
    )
    source: str = ""


class Cell(Strict):
    id: str
    title: str = ""
    performance: Literal["specified", "predictive", "measured"] = Field(
        default="specified",
        description="specified: voltage and efficiencies are given; measured: they are looked "
        "up in a measured series (measurements:) at the cell's current density, never "
        "extrapolated; predictive (a polarisation model) is not supported and refused.",
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
    measurements: MeasurementLink | None = None
    membrane: CellMembrane | None = None
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
    #: specified or measured; a measured cell's lookup (file, current density, bracket, sd)
    performance: str = "specified"
    measurement: dict[str, Any] | None = None
    #: the membrane's water dissociation efficiency, co-ion fluxes and hydroxide deficit
    membrane: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        data = dict(self.__dict__)
        # a specified cell without a membrane is reported as before these fields existed
        defaults = (("performance", "specified"), ("measurement", None), ("membrane", None))
        for name, default in defaults:
            if data[name] == default:
                del data[name]
        return data


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


# -- measured performance and the membrane -----------------------------------------------------


@dataclass
class _Lookup:
    """What a measured cell takes from its measurement at its current density."""

    file: str
    citation: str
    point: Any  # experiments.electrochemistry.PerformancePoint
    validity: dict[str, Any]
    voltage: float | None
    efficiency: float | None
    #: side reaction id -> its current fraction (the Faradaic efficiency of its side product)
    fractions: dict[str, float] = field(default_factory=dict)


def _conflict(
    quantity: Quantity | None,
    units: dict[Any, float],
    measured: float,
    sd: float | None,
    what: str,
    at: list[Any],
    cid: str,
    out: _Out,
) -> None:
    """A cell value stated beside the measured one: a warning unless it lies within the
    replicates' standard deviation (one replicate: equal to 1e-9)."""
    if quantity is None:
        return
    given = _value(quantity, units, what, out, at, cid)
    if given is None:
        return
    tolerance = sd if sd else 1e-9 * max(abs(measured), 1.0)
    if abs(given - measured) > tolerance * (1 + 1e-9):
        spread = f" +- {sd:.3g}" if sd else " (one replicate)"
        out.add(
            "warning",
            "measured-conflict",
            f"cell {cid}: {what} {given:.6g} differs from the measured {measured:.6g}{spread}: "
            "the measured value is used",
            at,
            [cid],
            f"remove {what} from the cell (the measurement gives it), or check the measurement",
        )


def _lookup(
    cell: Cell,
    reaction: Reaction | None,
    loc: list[Any],
    root: Path | None,
    cache: dict[str, Any] | None,
    current: float | None,
    area: float | None,
    result: CellResult,
    out: _Out,
    refuse,
) -> _Lookup | None:
    """The voltage and efficiencies of a measured cell at its current density (refused
    outside the measurement's validity range: never extrapolated)."""
    from chemeascode.domains.experiments.electrochemistry import (
        MeasuredPerformance,
        measurement_report,
    )

    cid = cell.id
    link = cell.measurements
    if cell.performance != "measured":
        refuse(
            "measurement",
            f"measurements: given, but performance is {cell.performance}",
            [*loc, "measurements"],
            "set performance: measured (voltage and efficiencies then come from the "
            "measurement), or remove measurements:",
        )
        return None
    if link is None:
        refuse(
            "input-missing",
            "performance: measured without measurements:",
            [*loc, "performance"],
            "give measurements: {file: experiments/electrochemistry/<id>.yaml, product: <id>}",
        )
        return None
    where = [*loc, "measurements", "file"]
    if root is None or not (Path(root) / link.file).is_file():
        refuse(
            "measurement",
            f"measurement file {link.file} does not exist",
            where,
            "give the path from the repository root (experiments/electrochemistry/<id>.yaml)",
        )
        return None
    cache = {} if cache is None else cache
    if link.file not in cache:
        cache[link.file] = measurement_report(Path(root), link.file)
    report = cache[link.file]
    if report.errors:
        refuse(
            "measurement",
            f"measurement file {link.file} has {len(report.errors)} error finding(s)",
            where,
            f"run `cheme experiments electrochem {link.file}` and fix them",
        )
        return None
    if report.voltage_basis == "electrode_vs_reference":
        refuse(
            "input-missing",
            f"{link.file} gives electrode potentials against a reference, not a cell voltage",
            where,
            "measure the cell voltage at the terminals (voltage_basis: cell)",
        )
        return None
    unknown = [p for p in [link.product, *link.side_products] if p not in report.products]
    if unknown:
        refuse(
            "measurement",
            f"{', '.join(unknown)} not a product of {link.file}",
            [*loc, "measurements"],
            f"name products of the measurement: {', '.join(report.products) or 'none'}",
        )
        return None
    # the product's Faradaic efficiency becomes the current efficiency of the cell's reaction
    named = report.reactions.get(link.product)
    if named is not None and named != cell.reaction:
        refuse(
            "measurement",
            f"{link.file} forms {link.product} by reaction {named}, not by the cell's reaction "
            f"{cell.reaction}",
            [*loc, "measurements", "product"],
            f"name the product of {cell.reaction} as measurements.product ({link.product} may "
            "be a side product), or correct the product's reaction: in the measurement",
        )
        return None
    if named is None and reaction is not None and reaction.stoichiometry.get(link.product, 0) <= 0:
        refuse(
            "measurement",
            f"{link.product} is no product of the cell's reaction {cell.reaction}",
            [*loc, "measurements", "product"],
            f"name a product of {cell.reaction} as measurements.product, or give it "
            f"reaction: {cell.reaction} in the measurement",
        )
        return None
    # the current fractions of the cell are of one electrode: the full current passes each
    electrode = report.electrodes.get(link.product)
    elsewhere = [p for p in link.side_products if report.electrodes.get(p, electrode) != electrode]
    if elsewhere:
        refuse(
            "measurement",
            f"side product {', '.join(elsewhere)} forms at the other electrode than "
            f"{link.product} ({electrode}) in {link.file}: their current fractions do not add up",
            [*loc, "measurements", "side_products"],
            f"name side products formed at the {electrode} only",
        )
        return None
    if current is None:
        return None  # refused as missing below
    if not area:
        refuse(
            "input-missing",
            "no active_area: the current density the measurement is looked up at",
            loc,
            "give active_area: (cm2 or m2) of one cell",
        )
        return None
    j = current / area
    point = MeasuredPerformance(report).at(j)
    if not point.available:
        lo, hi = point.bounds or (0.0, 0.0)
        refuse(
            "operating-range",
            f"current density {j:.6g} A/m2: {point.reason}; a measured cell is never extrapolated",
            [*loc, "current"],
            f"operate within the measured {lo:g}-{hi:g} A/m2, or measure the point",
        )
        return None
    lookup = _Lookup(link.file, report.citation, point, dict(report.validity), None, None)
    result.measurement = {
        "file": link.file,
        "current_density_a_m2": j,
        "bracket": list(point.bracket or ()),
        "voltage_basis": point.voltage_basis,
        "voltage_sd_v": point.voltage_sd_v,
        "faradaic_efficiency": dict(point.faradaic_efficiency),
        "faradaic_efficiency_sd": dict(point.faradaic_efficiency_sd),
        "validity": dict(report.validity),
    }
    if point.voltage_basis == "cell_ir_corrected":
        result.limitations.append(
            f"the measured voltage ({link.file}) is iR-corrected: the power and heat leave out "
            "the ohmic loss"
        )
    lookup.voltage = point.voltage_v
    lookup.efficiency = point.faradaic_efficiency.get(link.product)
    for name, value in (("voltage", lookup.voltage), (link.product, lookup.efficiency)):
        if value is None:
            refuse(
                "input-missing",
                f"{link.file} gives no "
                + ("voltage" if name == "voltage" else f"Faradaic efficiency of {name}")
                + f" at {j:.6g} A/m2",
                [*loc, "measurements"],
                "measure it at the bracketing points",
            )
    if lookup.voltage is not None:
        _conflict(
            cell.voltage,
            _VOLTAGE,
            lookup.voltage,
            point.voltage_sd_v,
            "voltage",
            [*loc, "voltage"],
            cid,
            out,
        )
    if lookup.efficiency is not None:
        _conflict(
            cell.faradaic_efficiency,
            _FRACTION,
            lookup.efficiency,
            point.faradaic_efficiency_sd.get(link.product),
            "faradaic_efficiency",
            [*loc, "faradaic_efficiency"],
            cid,
            out,
        )
    sides = {s.reaction: (j_, s) for j_, s in enumerate(cell.side_reactions)}
    for product in link.side_products:
        fe = point.faradaic_efficiency.get(product)
        reaction = report.reactions.get(product)
        if fe is None:
            refuse(
                "input-missing",
                f"{link.file} gives no Faradaic efficiency of {product} at {j:.6g} A/m2",
                [*loc, "measurements", "side_products"],
                "measure it at the bracketing points, or remove it from side_products",
            )
            continue
        if reaction is None or reaction not in sides:
            text = (
                f"side product {product} (FE {fe:.4g}) forms no side reaction of the cell: its "
                "current is counted as unassigned (heat)"
            )
            result.limitations.append(text)
            out.add(
                "info",
                "measurement",
                f"cell {cid}: {text}",
                [*loc, "measurements", "side_products"],
                [cid, product],
                "give the product's reaction: in the measurement and list it under side_reactions",
            )
            continue
        k, side = sides[reaction]
        if not 0 <= fe <= 1:
            refuse(
                "measurement",
                f"{link.file} gives side product {product} a Faradaic efficiency of {fe:.4g} at "
                f"{j:.6g} A/m2 (points {' and '.join(dict.fromkeys(point.bracket or ()))}), "
                "not in [0, 1]",
                [*loc, "measurements", "side_products"],
                f"check the measurement of {product}: run `cheme experiments electrochem "
                f"{link.file}`",
            )
            return None
        lookup.fractions[reaction] = fe
        _conflict(
            side.current_fraction,
            _FRACTION,
            fe,
            point.faradaic_efficiency_sd.get(product),
            f"side_reactions.{reaction}.current_fraction",
            [*loc, "side_reactions", k, "current_fraction"],
            cid,
            out,
        )
    _normalise(lookup, result, out, loc, cid, j)
    return lookup


def _normalise(
    lookup: _Lookup, result: CellResult, out: _Out, loc: list[Any], cid: str, j: float
) -> None:
    """Measured Faradaic efficiencies that add up to more than 1 (within the measurement's
    own ``fe-sum-high`` tolerance, since a file with errors refuses the cell): scaled to add up
    to 1, as the current cannot carry more charge than it has."""
    if lookup.efficiency is None:
        return
    total = lookup.efficiency + sum(lookup.fractions.values())
    if total <= 1 + 1e-9:
        return
    lookup.efficiency /= total
    lookup.fractions = {r: f / total for r, f in lookup.fractions.items()}
    if result.measurement is not None:
        result.measurement["normalised_from"] = total
    bracket = " and ".join(dict.fromkeys(lookup.point.bracket or ()))
    text = (
        f"the measured Faradaic efficiencies of {lookup.file} add up to {total:.6g} at "
        f"{j:.6g} A/m2 (points {bracket}): scaled to add up to 1"
    )
    result.limitations.append(text)
    out.add(
        "info",
        "measurement",
        f"cell {cid}: {text}",
        [*loc, "measurements"],
        [cid],
        "within the measurement's tolerance (calibration of the GC and the flow meter); "
        f"check the flow and fractions of {lookup.file} if it is more than expected",
    )


#: K: a measurement's temperature counts as the cell's within this (a thermostatted bench cell)
_TEMPERATURE_SLACK = 0.5


def _measured_temperature(cell: Cell, lookup: _Lookup, result: CellResult, loc, refuse) -> None:
    bounds = lookup.validity.get("temperature_k")
    t = result.temperature_k
    if bounds is None:
        result.limitations.append(
            f"{lookup.file} states no temperature: the cell's is not checked against it"
        )
        return
    if t is not None and not bounds[0] - _TEMPERATURE_SLACK <= t <= bounds[1] + _TEMPERATURE_SLACK:
        refuse(
            "operating-range",
            f"temperature {t:.6g} K outside the measured {bounds[0]:g}-{bounds[1]:g} K of "
            f"{lookup.file}; a measured cell is never extrapolated",
            [*loc, "thermal", "temperature"],
            "operate at the measured temperature, or measure at this one",
        )


def _membrane(
    cell: Cell,
    result: CellResult,
    lookup: _Lookup | None,
    formulas: dict[str, str],
    out: _Out,
    loc: list[Any],
) -> None:
    """The membrane's water dissociation efficiency (given, or measured), the co-ion fluxes
    ``f_i (1 - WDE) N I / (|z_i| F)`` and the anolyte hydroxide deficit ``(1 - WDE) N I / F``.
    Reported apart from the Faradaic efficiency, which it never changes."""
    membrane = cell.membrane
    assert membrane is not None
    cid = cell.id
    at = [*loc, "membrane"]
    row: dict[str, Any] = {
        "kind": membrane.kind,
        "bias": membrane.bias,
        "water_dissociation_efficiency": None,
        "water_dissociation_efficiency_sd": None,
        "basis": None,
        "co_ion_current_fraction": None,
        "co_ion_flux_mol_s": {},
        "co_ion_flux_kmol_h": {},
        "hydroxide_deficit_mol_s": None,
        "hydroxide_deficit_kmol_h": None,
        "measured_co_ion_carbon_fraction": None,
        "source": membrane.source,
    }
    result.membrane = row
    if membrane.kind == "none":
        return
    charges: dict[str, int] = {}
    for ion in membrane.co_ion_crossover:
        _, z = species_atoms(ion, formulas)
        if not z:
            out.add(
                "error",
                "membrane",
                f"cell {cid}: co-ion {ion} is no ion (formula and charge, e.g. K+, HCO3-)",
                [*at, "co_ion_crossover", ion],
                [cid, ion],
                "write the ion with its charge",
            )
            continue
        charges[ion] = abs(z)
    shares = membrane.co_ion_crossover
    if shares and (
        abs(sum(shares.values()) - 1) > 1e-6 or any(not 0 <= v <= 1 for v in shares.values())
    ):
        out.add(
            "error",
            "membrane",
            f"cell {cid}: the co-ion shares add up to {sum(shares.values()):.6g}, not 1",
            [*at, "co_ion_crossover"],
            [cid],
            "give each ion's share (0..1) of the current not carried by water dissociation",
        )
        charges = {}
    wde = _value(
        membrane.water_dissociation_efficiency,
        _FRACTION,
        "water_dissociation_efficiency",
        out,
        [*at, "water_dissociation_efficiency"],
        cid,
    )
    measured = lookup.point.water_dissociation_efficiency if lookup is not None else None
    if measured is not None:
        sd = lookup.point.water_dissociation_efficiency_sd  # type: ignore[union-attr]
        _conflict(
            membrane.water_dissociation_efficiency,
            _FRACTION,
            measured,
            sd,
            "water_dissociation_efficiency",
            [*at, "water_dissociation_efficiency"],
            cid,
            out,
        )
        wde = measured
        row.update(water_dissociation_efficiency_sd=sd, basis="measured")
        row["measured_co_ion_carbon_fraction"] = lookup.point.co_ion_carbon_fraction  # type: ignore[union-attr]
    elif wde is not None:
        row["basis"] = "given"
    if wde is None:
        if lookup is None and (cell.performance == "measured" or cell.measurements is not None):
            return  # the measurement was refused (cell-measurement): it is not read
        out.add(
            "info",
            "membrane",
            f"cell {cid}: {membrane.kind} membrane without a water dissociation efficiency: no "
            "co-ion fluxes or hydroxide deficit",
            at,
            [cid],
            "give membrane.water_dissociation_efficiency, or measure it (titration of the "
            "anolyte) in the cell's measurement",
        )
        return
    if not 0 <= wde <= 1:
        out.add(
            "error",
            "membrane",
            f"cell {cid}: water dissociation efficiency {wde:g} not in [0, 1]",
            [*at, "water_dissociation_efficiency"],
            [cid],
            "a fraction of the current",
        )
        return
    row["water_dissociation_efficiency"] = wde
    row["co_ion_current_fraction"] = 1 - wde
    if result.refused or result.current_a is None:
        return
    stack = result.cells * result.current_a  # A
    deficit = (1 - wde) * stack / FARADAY  # mol/s
    row["hydroxide_deficit_mol_s"] = deficit
    row["hydroxide_deficit_kmol_h"] = deficit * 3.6
    for ion, z in charges.items():
        flux = shares[ion] * (1 - wde) * stack / (z * FARADAY)
        row["co_ion_flux_mol_s"][ion] = flux
        row["co_ion_flux_kmol_h"][ion] = flux * 3.6


def _evaluate(
    cell: Cell,
    index: int,
    reactions: dict[str, Reaction],
    formulas: dict[str, str],
    masses: dict[str, float],
    out: _Out,
    root: Path | None = None,
    measured: dict[str, Any] | None = None,
) -> CellResult:
    """One cell's Faraday balance and, with a ``membrane:``, its membrane transport;
    *measured* caches the measurement reports by file (read from *root*)."""
    result, lookup = _faraday(cell, index, reactions, formulas, masses, out, root, measured)
    if cell.membrane is not None:
        _membrane(cell, result, lookup, formulas, out, ["cells", index])
    return result


def _faraday(
    cell: Cell,
    index: int,
    reactions: dict[str, Reaction],
    formulas: dict[str, str],
    masses: dict[str, float],
    out: _Out,
    root: Path | None,
    measured: dict[str, Any] | None,
) -> tuple[CellResult, _Lookup | None]:
    loc = ["cells", index]
    cid = cell.id
    result = CellResult(cid, cell.reaction, line=_yaml_line(out.doc, loc), cells=cell.cells)
    result.step = cell.flowsheet.step if cell.flowsheet is not None else None
    result.sources = list(cell.sources)
    result.performance = cell.performance

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
    lookup: _Lookup | None = None
    area: float | None = None
    if cell.performance == "measured" or cell.measurements is not None:
        area = _value(cell.active_area, _AREA, "active_area", out, [*loc, "active_area"], cid)
        lookup = _lookup(cell, reaction, loc, root, measured, current, area, result, out, refuse)
        efficiency = lookup.efficiency if lookup is not None else None
        voltage = lookup.voltage if lookup is not None else None
        missing = {"current": (current, "the current through each cell (A or kA)")}
    else:
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
        if lookup is not None and s.reaction in lookup.fractions:
            f: float | None = lookup.fractions[s.reaction]
        elif s.current_fraction is None:
            fractions.append(0.0)
            if lookup is not None or cell.performance != "measured":
                refuse(
                    "input-missing",
                    f"side reaction {s.reaction}: no current fraction",
                    [*loc, "side_reactions", j],
                    "give current_fraction (0..1, with its source)"
                    + (
                        ", or name a side product of the measurement that forms it"
                        if lookup is not None
                        else ""
                    ),
                )
            continue
        else:
            f = _value(
                s.current_fraction,
                _FRACTION,
                "current_fraction",
                out,
                [*loc, "side_reactions", j, "current_fraction"],
                cid,
            )
        fractions.append(f if f is not None else 0.0)
        if lookup is not None and s.reaction in lookup.fractions:
            continue  # measured: in [0, 1] (_lookup); a product below detection forms nothing
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
            (
                f"the Faradaic efficiencies measured in {lookup.file} plus the current_fraction "
                "stated for the other side reactions is at most 1: lower the stated fractions"
            )
            if lookup is not None
            else "faradaic_efficiency plus the side reactions' fractions is at most 1",
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

    if lookup is None and cell.performance != "measured" and cell.measurements is None:
        area = _value(cell.active_area, _AREA, "active_area", out, [*loc, "active_area"], cid)
    if current is not None and area:
        result.current_density_a_m2 = current / area
    # a measured cell's voltage and efficiencies come from its measurement, not these entries
    stated = (
        []
        if cell.performance == "measured"
        else [
            ("voltage", cell.voltage),
            ("faradaic_efficiency", cell.faradaic_efficiency),
        ]
    )
    taken = lookup.fractions if lookup is not None else {}
    for name, quantity in (
        *stated,
        *(
            (f"side_reactions.{s.reaction}", s.current_fraction)
            for s, _, _ in side
            if s.reaction not in taken
        ),
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
    if cell.performance == "measured":
        result.sourced = (
            lookup is not None
            and bool(lookup.citation.strip())
            and all(_sourced(s.current_fraction) for s, _, _ in side if s.reaction not in taken)
        )
        if lookup is not None:
            cited = f"{lookup.file}: {lookup.citation}" if lookup.citation else lookup.file
            result.sources.append(cited)
        quantities: tuple[Quantity | None, ...] = (cell.current,)
    else:
        result.sourced = all(
            _sourced(q)
            for q in (
                cell.voltage,
                cell.faradaic_efficiency,
                *(s.current_fraction for s, _, _ in side),
            )
        )
        quantities = (cell.voltage, cell.faradaic_efficiency, cell.current)
    result.sources += [
        q.source
        for q in quantities
        if q is not None and q.source.strip() and q.source not in result.sources
    ]
    _operating_range(cell, result, out, loc, lookup)
    if lookup is not None and result.temperature_k is not None:
        _measured_temperature(cell, lookup, result, loc, refuse)
    if result.refused or reaction is None:
        return result, lookup

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
    return result, lookup


def _operating_range(
    cell: Cell, result: CellResult, out: _Out, loc: list[Any], lookup: _Lookup | None = None
) -> None:
    span = cell.operating_range
    cid = cell.id
    if span is None and cell.performance == "measured":
        return  # the measurement's validity range is the operating range (_lookup)
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
    if cells is not None:
        inputs += [c.measurements.file for c in cells.cells if c.measurements is not None]
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
    measured: dict[str, Any] = {}
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
        results.append(_evaluate(cell, index, known, formulas, masses, out, root, measured))
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
            problems.append(
                "the measurement has no source"
                if cell.performance == "measured"
                else "voltage or current efficiency assumed or without a source"
            )
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
            detail=f"{_performance_text(cell)}: "
            f"Faraday balance {MODEL['id']} v{MODEL['version']}"
            + (": " + "; ".join(problems) if problems else ""),
            sources=list(cell.sources),
            assumptions=list(ASSUMPTIONS),
            limitations=[
                "measured cell performance: voltage and current efficiency interpolated "
                "between measured points, not predicted"
                if cell.performance == "measured"
                else "specified cell performance: voltage and current efficiency are not predicted",
                *cell.limitations,
            ],
        )
    return bases


def _performance_text(cell: CellResult) -> str:
    if cell.performance != "measured":
        return f"specified electrochemical cell {cell.id} (voltage, current efficiency)"
    at = cell.measurement or {}
    j = at.get("current_density_a_m2")
    return (
        f"measured electrochemical cell {cell.id} (voltage, current efficiency from "
        f"{at.get('file', 'its measurement')}"
        + (f" at {j:.6g} A/m2" if j is not None else "")
        + ")"
    )


def _g(value: float | None) -> str:
    return "-" if value is None else f"{value:.4g}"


def _sd(value: float | None) -> str:
    return "" if not value else f" +- {value:.2g}"


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
        if c.measurement is not None:
            m = c.measurement
            fe = ", ".join(
                f"{n} {v:.4g}{_sd(m['faradaic_efficiency_sd'].get(n))}"
                for n, v in m["faradaic_efficiency"].items()
            )
            lines.append(
                f"  measured: {m['file']} at {m['current_density_a_m2']:.6g} A/m2 (between "
                f"{' and '.join(m['bracket'])}): voltage {c.voltage_v:.4g}"
                f"{_sd(m['voltage_sd_v'])} V ({m['voltage_basis']}), FE {fe}"
            )
        if c.membrane is not None:
            lines.append(_membrane_text(c.membrane))
        for text in c.limitations:
            lines.append(f"  limitation: {text}")
    lines += [f.format() for f in report.findings]
    return "\n".join(lines)


def _membrane_text(row: dict[str, Any]) -> str:
    kind = row["kind"].replace("_", "-") + (f", {row['bias']} bias" if row["bias"] else "")
    wde = row["water_dissociation_efficiency"]
    if wde is None:
        return f"  membrane ({kind}): no water dissociation efficiency"
    text = (
        f"  membrane ({kind}): water dissociation efficiency {wde:.4g}"
        f"{_sd(row['water_dissociation_efficiency_sd'])} ({row['basis']}; apart from the "
        "Faradaic efficiency)"
    )
    if row["hydroxide_deficit_kmol_h"] is not None:
        fluxes = ", ".join(f"{n} {v:.4g}" for n, v in row["co_ion_flux_kmol_h"].items())
        text += (
            f"; co-ions {fluxes or 'not split'} kmol/h; anolyte hydroxide deficit "
            f"{row['hydroxide_deficit_kmol_h']:.4g} kmol/h"
        )
    return text
