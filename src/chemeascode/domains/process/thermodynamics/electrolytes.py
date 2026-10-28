"""Aqueous electrolytes: the qualified systems of ``electrolytes.yml`` through Pitzer's equations.

``electrolytes.yml`` (package data next to this module, version in ``meta.version``) is the
contract of the electrolyte route: per system, the apparent components and the species they
dissociate into, the composition, speciation and activity basis, the model (Cantera's
``HMW-electrolyte`` phase, Pitzer's equations) with its parameters and their source, the
application range, the properties claimed in it with their tolerances, the benchmark and what
is not claimed. Today one system: ``NaCl-H2O`` (273.15-373.15 K, up to 1000 kPa(a) and 6 mol/kg;
the relative enthalpy from 313.15 K), benchmarked in ``tests/test_electrolytes.py`` against
Hamer and Wu (1972) and Pitzer, Peiper and Busey (1984).

:func:`electrolyte_state` converts the composition to species, checks the charge and the
element closure, and returns the mean ionic activity coefficient, the osmotic coefficient, the
water activity, the water vapour pressure over the solution and the relative apparent molar
enthalpy, with the contract's provenance. Everything outside the contract is refused with an
:class:`ElectrolyteError` (a ``ValueError`` with a rule id and a hint), never computed with a
neutral-fluid model: an unknown system or species, a charge imbalance, a state outside the
range, a solution that boils at the given pressure. The phase and simulation routes refuse ions
and, with water, the apparent electrolytes the contract lists or its ``ionic_elements`` identify
by formula (:func:`dissolved_electrolytes`).

Needs the extras ``cantera`` (the solver, imported in ``integrations.cantera``) and ``props``
(``chemicals``: the IAPWS-95 saturation pressure of water); both are imported inside the
functions.
"""

from __future__ import annotations

import importlib.util
import math
import re
from collections.abc import Iterable, Mapping
from functools import cache
from importlib.resources import files
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

#: The contract, package data next to this module.
ELECTROLYTES_FILE = files("chemeascode.domains.process.thermodynamics") / "electrolytes.yml"
#: CAS number of water, the solvent of every system.
WATER_CAS = "7732-18-5"
EXTRAS = "pip install 'cheme-as-code[cantera,props]'"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Species(_Model):
    id: str
    charge: int
    elements: dict[str, int]


class ApparentComponent(_Model):
    id: str
    name: str
    cas: str
    elements: dict[str, int] = Field(description="The formula, element -> number")
    molar_mass_g_per_mol: float
    dissociation: dict[str, int] = Field(description="Species -> stoichiometric number")


class Solvent(_Model):
    species: str
    cas: str
    name: str


class Interaction(_Model):
    model_config = ConfigDict(extra="allow")
    species: list[str]


class Model(_Model):
    thermo: str
    temperature_model: str
    A_Debye: str
    interactions: list[Interaction]
    parameter_source: str
    water: str
    standard_states: str


class ApplicationRange(_Model):
    temperature_K: tuple[float, float]
    pressure_kPa: tuple[float | None, float]
    molality_mol_per_kg: tuple[float, float]
    enthalpy_temperature_K: tuple[float, float]


class Benchmark(_Model):
    test: str
    reference: list[str]
    notes: list[str] = Field(default_factory=list)


class ReferenceConditions(_Model):
    temperature_K: float
    pressure_kPa: float
    note: str = ""


class System(_Model):
    """One qualified electrolyte system."""

    id: str
    name: str
    method: str = Field(description="The methods.yml row whose liquid model this executes")
    solvent: Solvent
    apparent_components: list[ApparentComponent]
    species: list[Species]
    speciation: str
    basis: dict[str, str]
    reference_conditions: ReferenceConditions
    model: Model
    application_range: ApplicationRange
    properties: list[str]
    tolerances: dict[str, float]
    tolerance_basis: str
    not_claimed: list[str]
    benchmark: Benchmark

    @property
    def salt(self) -> ApparentComponent:
        return self.apparent_components[0]

    def charges(self) -> dict[str, int]:
        return {s.id: s.charge for s in self.species}

    def species_elements(self, species_id: str) -> dict[str, int]:
        """The elements of species *species_id* (its charge is not an element)."""
        return next(s.elements for s in self.species if s.id == species_id)


class Route(_Model):
    title: str
    solver: str
    solver_version: str = Field(description="The version the benchmark ran on")
    extras: list[str]
    water_vapour_pressure: str
    limitations: list[str]


class ApparentElectrolyte(_Model):
    cas: str
    name: str
    system: str | None = Field(default=None, description="The system that runs it, if any")


class ElectrolyteTable(_Model):
    meta: dict[str, Any]
    route: Route
    systems: list[System]
    apparent_electrolytes: list[ApparentElectrolyte]
    ionic_elements: list[str] = Field(
        description="A component with one of these elements dissociates in water (by formula)"
    )

    def system(self, system_id: str) -> System:
        for s in self.systems:
            if s.id == system_id:
                return s
        raise ElectrolyteError(
            "electrolyte-system",
            f"no electrolyte system {system_id!r}",
            "the qualified systems are "
            + ", ".join(s.id for s in self.systems)
            + " (electrolytes.yml); any other electrolyte is unsupported",
        )


class ElectrolyteError(ValueError):
    """A request outside the electrolyte contract; ``rule`` and ``hint`` say which and why."""

    def __init__(self, rule: str, message: str, hint: str) -> None:
        super().__init__(f"{message} -- {hint}")
        self.rule = f"cheme.process-{rule}"
        self.message = message
        self.hint = hint


class Closure(_Model):
    """The apparent components against the species the solver was given, per kg of water."""

    charge_mol_per_kg: float = Field(description="Sum of charge times molality of the species")
    elements: dict[str, tuple[float, float]] = Field(
        description="Element -> (mol in the apparent components, mol in the species)"
    )
    max_relative_deviation: float
    closed: bool


class ElectrolyteState(_Model):
    """The state of a qualified electrolyte solution, with the contract's provenance."""

    system: str
    name: str
    method: str = Field(description="The methods.yml row whose liquid model this executes")
    contract_version: int
    temperature_K: float
    pressure_kPa: float = Field(description="Absolute")
    composition_basis: Literal["molality", "mass_fraction", "species"]
    molality_mol_per_kg: float = Field(description="Of the apparent salt, mol per kg of water")
    mass_fraction: float = Field(description="Of the apparent salt in the solution")
    species_molalities: dict[str, float] = Field(description="Solute species, mol per kg water")
    ionic_strength_mol_per_kg: float
    closure: Closure
    phase: Literal["liquid"] = "liquid"
    mean_activity_coefficient: float = Field(description="Molality scale (unsymmetric)")
    osmotic_coefficient: float = Field(description="Molal")
    water_activity: float = Field(description="Mole-fraction scale, pure water at T and P")
    water_vapour_pressure_kPa: float = Field(description="a_w times the IAPWS-95 p_sat")
    pure_water_vapour_pressure_kPa: float
    relative_apparent_molar_enthalpy_J_per_mol: float | None = Field(
        description="phi_L of the salt, J/mol; None outside the enthalpy range (see notes)"
    )
    solver: str
    solver_version: str
    benchmarked_solver_version: str
    parameter_source: str
    basis: dict[str, str]
    speciation: str
    tolerances: dict[str, float]
    benchmark: Benchmark
    limitations: list[str]
    not_claimed: list[str]
    notes: list[str] = Field(default_factory=list)


@cache
def electrolyte_table() -> ElectrolyteTable:
    """The packaged contract (validated, cached)."""
    return ElectrolyteTable.model_validate(
        yaml.safe_load(ELECTROLYTES_FILE.read_text(encoding="utf-8"))
    )


def dissolved_electrolytes(
    cas_numbers: Iterable[str | None],
    formulas: Mapping[str, str | None] | None = None,
    names: Mapping[str, str | None] | None = None,
) -> list[ApparentElectrolyte]:
    """The apparent electrolytes among *cas_numbers* when water is among them too: a component
    that dissociates in water and that a neutral-fluid model would compute as a molecule.
    Those the contract lists, and any other whose formula (*formulas*: CAS -> formula, where
    known) contains one of its ``ionic_elements``, named from *names* (CAS -> name). Empty
    without water."""
    present = [c for c in dict.fromkeys(cas_numbers) if c]
    if WATER_CAS not in present:
        return []
    table = electrolyte_table()
    found = [e for e in table.apparent_electrolytes if e.cas in present]
    listed = {e.cas for e in found}
    for cas in present:
        formula = (formulas or {}).get(cas)
        if cas in listed or not formula:
            continue
        if set(re.findall(r"[A-Z][a-z]?", formula)) & set(table.ionic_elements):
            name = (names or {}).get(cas) or formula
            found.append(ApparentElectrolyte(cas=cas, name=f"{name} ({formula})"))
    return found


def refusal_hint(found: Iterable[ApparentElectrolyte]) -> str:
    """Where the electrolytes in *found* can be computed, if anywhere."""
    runs = sorted({e.system for e in found if e.system})
    if runs:
        return (
            f"electrolyte system {', '.join(runs)}: cheme process electrolyte (one liquid phase, "
            "the range of electrolytes.yml); anything else is unsupported"
        )
    return "no route models this electrolyte (methods.yml regime electrolytes)"


def cantera_input(system: System) -> str:
    """The Cantera YAML input of *system*: an ``HMW-electrolyte`` phase with the contract's
    parameters; the species' standard states are zero (no reported quantity uses them)."""
    zero = {"model": "constant-cp", "T0": 298.15, "h0": 0.0, "s0": 0.0, "cp0": 0.0}
    elements: list[str] = []
    species = []
    for s in system.species:
        composition = dict(s.elements)
        if s.charge:
            composition["E"] = -s.charge
        elements += [e for e in composition if e not in elements]
        eos = (
            {"model": "liquid-water-IAPWS95"}
            if s.id == system.solvent.species
            else {"model": "constant-volume", "molar-volume": 0.0}
        )
        species.append(
            {"name": s.id, "composition": composition, "thermo": zero, "equation-of-state": eos}
        )
    phase = {
        "name": system.id,
        "elements": elements,
        "species": [s.id for s in system.species],
        "thermo": system.model.thermo,
        "activity-data": {
            "temperature-model": system.model.temperature_model,
            "A_Debye": system.model.A_Debye,
            "interactions": [i.model_dump() for i in system.model.interactions],
        },
    }
    return yaml.safe_dump({"phases": [phase], "species": species}, sort_keys=False)


def _composition(
    system: System,
    molality: float | None,
    mass_fraction: float | None,
    species: Mapping[str, float] | None,
) -> tuple[str, float]:
    """(basis, molality of the salt) of the one composition given."""
    inputs = {"molality": molality, "mass_fraction": mass_fraction, "species": species}
    given = [name for name, value in inputs.items() if value is not None]
    if len(given) != 1:
        raise ElectrolyteError(
            "electrolyte-composition",
            f"give one composition: molality, mass_fraction or species (got {given or 'none'})",
            f"e.g. molality of {system.salt.id} in mol per kg of water",
        )
    salt = system.salt
    if molality is not None:
        return "molality", float(molality)
    if mass_fraction is not None:
        w = float(mass_fraction)
        if not 0.0 <= w < 1.0:
            raise ElectrolyteError(
                "electrolyte-composition",
                f"mass fraction of {salt.id} {w:g} is not between 0 and 1",
                "give the mass of the salt per mass of solution",
            )
        return "mass_fraction", w / (salt.molar_mass_g_per_mol / 1000.0 * (1.0 - w))
    assert species is not None
    solutes = {s.id for s in system.species if s.id != system.solvent.species}
    unknown = sorted(set(species) - solutes)
    if unknown:
        raise ElectrolyteError(
            "electrolyte-unsupported",
            f"species {', '.join(unknown)} not in electrolyte system {system.id} "
            f"(species {', '.join(sorted(solutes))})",
            "another ion or a mixture of electrolytes is unsupported (electrolytes.yml)",
        )
    charges = system.charges()
    values = {s: float(species.get(s, 0.0)) for s in solutes}
    charge = sum(charges[s] * m for s, m in values.items())
    scale = sum(abs(charges[s] * m) for s, m in values.items())
    if abs(charge) > system.tolerances["closure_rel"] * max(scale, 1e-300):
        raise ElectrolyteError(
            "electrolyte-charge-balance",
            f"the species are not electroneutral: sum of charge times molality {charge:+.6g} "
            "mol/kg",
            "give molalities that balance in charge; an excess ion is a second electrolyte, "
            "which is unsupported",
        )
    ratios = {values[s] / n for s, n in salt.dissociation.items()}
    if max(ratios) - min(ratios) > system.tolerances["closure_rel"] * max(ratios, default=1.0):
        raise ElectrolyteError(
            "electrolyte-charge-balance",
            f"the species are not in the ratio of {salt.id}: {salt.dissociation}",
            "the system has one apparent salt",
        )
    return "species", min(ratios)


def _check_range(system: System, temperature_K: float, pressure_kPa: float, m: float) -> None:
    box = system.application_range
    t_lo, t_hi = box.temperature_K
    m_lo, m_hi = box.molality_mol_per_kg
    p_hi = box.pressure_kPa[1]
    problems = []
    if not m_lo < m <= m_hi:
        problems.append(
            f"molality of {system.salt.id} {m:.6g} mol/kg is outside ({m_lo:g}, {m_hi:g}]"
        )
    if not t_lo <= temperature_K <= t_hi:
        problems.append(f"{temperature_K:.6g} K is outside {t_lo:g}-{t_hi:g} K")
    if not 0.0 < pressure_kPa <= p_hi:
        problems.append(f"{pressure_kPa:.6g} kPa(a) is outside 0-{p_hi:g} kPa(a)")
    if problems:
        raise ElectrolyteError(
            "electrolyte-range",
            f"{system.id}: " + "; ".join(problems),
            f"the claimed range (electrolytes.yml): {t_lo:g}-{t_hi:g} K, up to {p_hi:g} kPa(a) "
            f"and {m_hi:g} mol/kg; beyond it the system is unsupported",
        )


def _water_saturation_kpa(temperature_K: float) -> float:
    from chemicals.iapws import iapws95_Psat

    return float(iapws95_Psat(temperature_K)) / 1000.0


def electrolyte_state(
    temperature_K: float,
    pressure_kPa: float,
    *,
    system: str = "NaCl-H2O",
    molality: float | None = None,
    mass_fraction: float | None = None,
    species: Mapping[str, float] | None = None,
) -> ElectrolyteState:
    """The state of electrolyte *system* at *temperature_K*, *pressure_kPa* (absolute) and one
    composition: *molality* of the apparent salt (mol per kg of water), its *mass_fraction* in
    the solution, or the solute *species* molalities (which must balance in charge).

    Raises :class:`ElectrolyteError` for a request outside the contract (``rule``:
    ``cheme.process-electrolyte-system``, ``-composition``, ``-unsupported``,
    ``-charge-balance``, ``-range``, ``-phase``) and ``ImportError`` naming the extras without
    cantera or chemicals."""
    table = electrolyte_table()
    sys_ = table.system(system)
    basis, m = _composition(sys_, molality, mass_fraction, species)
    _check_range(sys_, temperature_K, pressure_kPa, m)
    missing = [name for name in ("cantera", "chemicals") if importlib.util.find_spec(name) is None]
    if missing:
        raise ImportError(f"the electrolyte route needs {' and '.join(missing)}: {EXTRAS}")
    from chemeascode.integrations.cantera import hmw_state

    salt = sys_.salt
    solutes = {s: n * m for s, n in salt.dissociation.items()}
    state = hmw_state(cantera_input(sys_), temperature_K, pressure_kPa * 1000.0, solutes)

    # closure: the apparent components (per kg water) against the species the solver holds
    # (the salt's own formula, not its dissociation: this also checks that the dissociation
    # conserves the elements)
    water = sys_.solvent.species
    n_water = state["amounts"][water]
    expected = {e: k * n_water for e, k in sys_.species_elements(water).items()}
    for e, k in salt.elements.items():
        expected[e] = expected.get(e, 0.0) + k * m
    held = {e: state["elements"].get(e, 0.0) for e in expected}
    deviation = max(abs(held[e] - v) / v for e, v in expected.items() if v)
    charge = sum(state["charges"][s] * n for s, n in state["amounts"].items())
    tolerance = sys_.tolerances["closure_rel"]
    closed = deviation <= tolerance and abs(charge) <= tolerance * m
    closure = Closure(
        charge_mol_per_kg=charge,
        elements={e: (v, held[e]) for e, v in expected.items()},
        max_relative_deviation=deviation,
        closed=closed,
    )
    if not closed:  # the translation to the solver lost or invented matter or charge
        raise ElectrolyteError(
            "electrolyte-closure",
            f"species or charge do not close: element deviation {deviation:.3g}, net charge "
            f"{charge:.3g} mol/kg",
            "a defect of the electrolyte route; report it",
        )

    nu = sum(salt.dissociation.values())
    activity = state["activities"]
    ln_gamma = sum(n * math.log(activity[s] / (n * m)) for s, n in salt.dissociation.items()) / nu
    m_total = sum(solutes.values())
    a_w = activity[water]
    phi = -math.log(a_w) / (state["solvent_molar_mass"] * m_total)
    p_sat = _water_saturation_kpa(temperature_K)
    p_w = a_w * p_sat
    if pressure_kPa < p_w:
        raise ElectrolyteError(
            "electrolyte-phase",
            f"{sys_.id} at {temperature_K:.6g} K and {m:.6g} mol/kg boils at {pressure_kPa:.6g} "
            f"kPa(a): its vapour pressure is {p_w:.6g} kPa(a)",
            "the route computes one liquid phase; no vapour-liquid flash of electrolytes",
        )
    relative = state["relative_enthalpies"]
    phi_l = sum(relative[s] * n for s, n in state["amounts"].items()) / m
    e_lo, e_hi = sys_.application_range.enthalpy_temperature_K
    notes = []
    if not e_lo <= temperature_K <= e_hi:
        phi_l_out = None
        notes.append(
            f"relative apparent molar enthalpy not claimed at {temperature_K:.6g} K (claimed "
            f"{e_lo:g}-{e_hi:g} K): {sys_.not_claimed[0]}"
        )
    else:
        phi_l_out = phi_l
    if state["version"] != table.route.solver_version:
        notes.append(
            f"Cantera {state['version']} is not the version benchmarked "
            f"({table.route.solver_version}); rerun {sys_.benchmark.test}"
        )
    charges = sys_.charges()
    ionic = 0.5 * sum(charges[s] ** 2 * v for s, v in solutes.items())
    mass_salt = m * salt.molar_mass_g_per_mol / 1000.0
    return ElectrolyteState(
        system=sys_.id,
        name=sys_.name,
        method=sys_.method,
        contract_version=int(table.meta["version"]),
        temperature_K=temperature_K,
        pressure_kPa=pressure_kPa,
        composition_basis=basis,  # type: ignore[arg-type]
        molality_mol_per_kg=m,
        mass_fraction=mass_salt / (1.0 + mass_salt),
        species_molalities=solutes,
        ionic_strength_mol_per_kg=ionic,
        closure=closure,
        mean_activity_coefficient=math.exp(ln_gamma),
        osmotic_coefficient=phi,
        water_activity=a_w,
        water_vapour_pressure_kPa=p_w,
        pure_water_vapour_pressure_kPa=p_sat,
        relative_apparent_molar_enthalpy_J_per_mol=phi_l_out,
        solver=f"{table.route.solver} {state['version']}, {sys_.model.thermo}",
        solver_version=state["version"],
        benchmarked_solver_version=table.route.solver_version,
        parameter_source=sys_.model.parameter_source,
        basis=dict(sys_.basis),
        speciation=sys_.speciation,
        tolerances=dict(sys_.tolerances),
        benchmark=sys_.benchmark,
        limitations=list(table.route.limitations),
        not_claimed=list(sys_.not_claimed),
        notes=notes,
    )
