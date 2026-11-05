"""Schema ``cheme/reactions/v1`` (``process/reactions.yaml``) and the checks of a reaction.

A reaction is stoichiometry over the component ids of ``process/materials.yaml``: a coefficient
per component, negative for reactants and positive for products. A reaction may give the
conversion of its key component (``conversion:``), which ``cheme process propagate`` uses for
a conversion reactor, the heat of reaction, the catalyst and its sources.

Rules (``cheme.reaction-*``), each finding naming the file, line, rule and a hint:

- ``reaction-schema``: the file does not follow ``cheme/reactions/v1``;
- ``reaction-duplicate-id``: two reactions with one id;
- ``reaction-component``: a coefficient of a component that is not declared;
- ``reaction-element-balance``: the atoms of the reactants and products differ;
  ``reaction-element-balance-not-evaluable``: a component without a formula, or with a formula
  this parser does not read;
- ``reaction-conversion``: the conversion's key component is not a reactant of the reaction;
- ``reaction-rate``: a rate law naming a component that is not declared, or (warning) one
  with ``reverse: equilibrium`` for an irreversible reaction;
- ``reaction-mechanism``: an elementary step that does not balance its atoms or its sites, or
  names a gas component that is not declared;
- ``reaction-phase-basis`` (warning): an equilibrium constant or rate law on a basis that does
  not fit the reaction's ``phase`` (partial pressures for a liquid; a liquid's mole fractions or
  activities for a gas), or on a liquid's basis without ``phase: liquid``.

The functions take components as plain ``id -> formula`` mappings, so that they need nothing
from the process domain.
"""

from __future__ import annotations

import math
from collections.abc import Collection, Mapping
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from chemeascode.domains.chemistry.formulas import ATOMIC_MASS as ATOMIC_MASS
from chemeascode.domains.chemistry.formulas import molar_mass as molar_mass
from chemeascode.domains.chemistry.formulas import parse_formula
from chemeascode.domains.chemistry.microkinetics import Mechanism, site_change, step_atoms
from chemeascode.domains.chemistry.rates import RateLaw
from chemeascode.foundation.findings import Finding
from chemeascode.foundation.schema_base import Provenance, Strict, unsupported_schema
from chemeascode.foundation.uncertainty import Uncertainty
from chemeascode.foundation.yamlsource import _yaml_line

SCHEMA = "cheme/reactions/v1"
REACTIONS_FILE = "process/reactions.yaml"

# -- schema -------------------------------------------------------------------------------------


class Conversion(Strict):
    """The fraction of the key component's inlet flow a reactor converts by this reaction."""

    key: str = Field(description="A reactant (negative coefficient) of the reaction.")
    value: float = Field(gt=0, le=1)
    provenance: Literal["given", "assumed"]
    source: str = ""
    uncertainty: Uncertainty | None = Field(
        default=None,
        description="Relative to the value: sampled by cheme process reactor-uncertainty.",
        exclude_if=lambda value: value is None,
    )


class HeatOfReaction(Strict):
    """Per kmol of extent of the reaction as written: negative when exothermic."""

    value: float
    unit: Literal["kJ/kmol"] = "kJ/kmol"
    temperature: float = Field(default=298.15, gt=0, description="K")
    provenance: Provenance
    source: str = ""
    uncertainty: Uncertainty | None = Field(
        default=None,
        description="Relative to the value: sampled by cheme process reactor-uncertainty.",
        exclude_if=lambda value: value is None,
    )


class EquilibriumConstant(Strict):
    """``ln K = a + b / T + c ln T + d T`` (T in K) for the reaction as written, on ``basis``:
    partial pressures in bar (a gas), or a liquid's mole fractions, activities or
    concentrations in kmol/m3 (domains/chemistry/liquid.py); instead of the components'
    ideal-gas data."""

    basis: Literal["partial_pressure", "mole_fraction", "activity", "concentration"] = Field(
        default="partial_pressure",
        description="What K is written on: partial_pressure (bar, a gas); mole_fraction, "
        "activity or concentration (kmol/m3) for a liquid-phase reaction.",
        # left out of dumps at the default: the reactors' input fingerprints stay as they were
        exclude_if=lambda value: value == "partial_pressure",
    )
    a: float = 0.0
    b: float = 0.0
    c: float = 0.0
    d: float = 0.0
    temperature_range: tuple[float, float] | None = Field(default=None, description="K")
    provenance: Literal["given", "assumed"]
    source: str = ""
    uncertainty: Uncertainty | None = Field(
        default=None,
        description="Of K, relative (a multiplier on K): cheme process reactor-uncertainty.",
        exclude_if=lambda value: value is None,
    )

    @field_validator("temperature_range")
    @classmethod
    def _range(cls, value: tuple[float, float] | None) -> tuple[float, float] | None:
        if value is not None and not 0 < value[0] < value[1]:
            raise ValueError("temperature_range is (min, max) in K, 0 < min < max")
        return value

    def ln_k(self, temperature: float) -> float:
        return self.a + self.b / temperature + self.c * math.log(temperature) + self.d * temperature

    def covers(self, temperature: float) -> bool:
        lo, hi = self.temperature_range or (0.0, math.inf)
        return lo <= temperature <= hi


#: What :meth:`Reaction.inputs_dump` leaves out.
INPUTS_EXCLUDE = {
    "mechanism": True,
    "kind": True,
    "conversion": {"uncertainty"},
    "heat_of_reaction": {"uncertainty"},
    "equilibrium_constant": {"uncertainty"},
    "rate": {"uncertainty"},
}


class Reaction(Strict):
    id: str
    title: str = ""
    equation: str = Field(default="", description="As text, for readers (not parsed).")
    stoichiometry: dict[str, float] = Field(
        min_length=2,
        description="Component id -> coefficient: negative reactants, positive products.",
    )
    phase: Literal["vapor", "liquid", "mixed"] | None = None
    kind: Literal["reaction", "phase-change"] = Field(
        default="reaction",
        description="phase-change: no chemical change, a component going from one phase to "
        "another (a precipitation NBS(aq) -> NBS(s), a dissolution, a hydrate forming): the "
        "thermal screening (cheme process reactor-hazards) does not screen it as a reaction. "
        "A reaction of one component into one other of the same formula, one of them phase: "
        "solid, counts as one unless it declares a heat_of_reaction (then it is screened).",
        exclude_if=lambda value: value == "reaction",
    )
    reversible: bool = False
    conversion: Conversion | None = None
    heat_of_reaction: HeatOfReaction | None = None
    equilibrium_constant: EquilibriumConstant | None = None
    rate: RateLaw | None = Field(
        default=None, description="Kinetics: power law or LHHW (domains/chemistry/rates.py)."
    )
    mechanism: Mechanism | None = Field(
        default=None,
        description="Its elementary surface steps (domains/chemistry/microkinetics.py).",
    )
    catalyst: str = Field(
        default="",
        description="The catalyst: an id of process/catalysts.yaml (a catalyst's name or free "
        "text is accepted; with that file, validate hints at the id or warns).",
    )
    sources: list[str] = Field(default_factory=list, description="DOIs or references.")

    def inputs_dump(self) -> dict[str, Any]:
        """The reaction as a reactor's result depends on it (for the outlet's fingerprint):
        without its mechanism (its rates enter) and without uncertainties (they describe the
        values, they do not change the result)."""
        return self.model_dump(mode="json", exclude=INPUTS_EXCLUDE)  # type: ignore[arg-type]

    @model_validator(mode="after")
    def _sides(self) -> Reaction:
        if 0 in self.stoichiometry.values():
            raise ValueError(f"reaction {self.id}: a coefficient is 0; leave the component out")
        if not any(v < 0 for v in self.stoichiometry.values()) or not any(
            v > 0 for v in self.stoichiometry.values()
        ):
            raise ValueError(
                f"reaction {self.id}: needs reactants (negative) and products (positive)"
            )
        return self

    def reaction_smiles(self, components: Mapping[str, str | None]) -> str | None:
        """The reaction SMILES ``reactants>>products`` of the stoichiometry: the reaction's
        external identifier, derived and never stored. *components* maps a component id to its
        SMILES (``process/materials.yaml``). Each molecule is repeated as often as its
        coefficient says (water-gas shift: ``[C-]#[O+].O>>O=C=O.[H][H]``), so the identifier
        is None unless every component has a SMILES and every coefficient is a whole number."""
        sides: dict[bool, list[str]] = {True: [], False: []}
        for name, coefficient in self.stoichiometry.items():
            smiles = components.get(name)
            if not smiles or coefficient != int(coefficient):
                return None
            sides[coefficient < 0] += [smiles] * abs(int(coefficient))
        return f"{'.'.join(sides[True])}>>{'.'.join(sides[False])}"


class Reactions(Strict):
    """The reactions of the process."""

    schema_: str = Field(alias="schema", description=f"Always {SCHEMA}.")
    kind: Literal["reactions"]
    activity_model: Literal["unifac", "ideal"] = Field(
        default="unifac",
        description="Activity coefficients of liquid-phase reactions on an activity basis: "
        "UNIFAC from the components' CAS numbers (extra props), or 1 (ideal).",
    )
    reactions: list[Reaction] = Field(default_factory=list)

    @model_validator(mode="after")
    def _version(self) -> Reactions:
        if self.schema_ != SCHEMA:
            raise ValueError(unsupported_schema(self.schema_, SCHEMA))
        return self

    def by_id(self) -> dict[str, Reaction]:
        return {r.id: r for r in self.reactions}


# -- checks -------------------------------------------------------------------------------------


def phase_change(
    reaction: Reaction, formulas: Mapping[str, str], solids: Collection[str] = ()
) -> str | None:
    """Why *reaction* is a phase change, not a chemical reaction: ``declared`` (``kind:
    phase-change``) or ``same formula`` (one component into one other, coefficient for
    coefficient, with the same atoms, one of them a solid component of *solids* and the other
    not: ``A(aq) -> A(s)``, never an isomerisation); None for a reaction."""
    if reaction.kind == "phase-change":
        return "declared"
    stoich = reaction.stoichiometry
    if len(stoich) != 2:
        return None
    (a, nu_a), (b, nu_b) = stoich.items()
    if nu_a != -nu_b or (a in solids) == (b in solids):
        return None
    atoms = [parse_formula(formulas.get(n) or "") for n in (a, b)]
    if atoms[0] and atoms[0] == atoms[1]:
        return "same formula"
    return None


def key_component(reaction: Reaction) -> str | None:
    """The component a conversion of *reaction* refers to: its ``conversion.key``, else its only
    reactant; None when neither says."""
    if reaction.conversion is not None:
        return reaction.conversion.key
    reactants = [n for n, v in reaction.stoichiometry.items() if v < 0]
    return reactants[0] if len(reactants) == 1 else None


def convert(
    reactions: list[Reaction], conversions: Mapping[str, float], moles: Mapping[str, float]
) -> tuple[dict[str, float], dict[str, float]]:
    """A conversion reactor: the outlet (component id -> kmol/h) of inlet *moles*, every
    reaction converting its fraction (*conversions*, by reaction id) of its key component's
    *inlet* flow, all at once (Aspen RStoic's default); and the extents (kmol/h). Raises
    ValueError when a reaction has no key component, its key is not one of its reactants, or
    the reactions together consume more of a component than is fed."""
    out = dict(moles)
    extents: dict[str, float] = {}
    for reaction in reactions:
        key = key_component(reaction)
        if key is None:
            raise ValueError(f"reaction {reaction.id} has no key component (conversion.key)")
        if reaction.stoichiometry.get(key, 0) >= 0:
            raise ValueError(f"reaction {reaction.id}: key component {key} is not a reactant")
        xi = conversions[reaction.id] * moles.get(key, 0.0) / -reaction.stoichiometry[key]
        extents[reaction.id] = xi
        for name, nu in reaction.stoichiometry.items():
            out[name] = out.get(name, 0.0) + nu * xi
    short = [n for n, v in out.items() if v < -1e-9 * max(1.0, abs(moles.get(n, 0.0)))]
    if short:
        raise ValueError(
            "the conversions consume more "
            + ", ".join(f"{n} ({-out[n]:.6g} kmol/h short)" for n in short)
            + " than is fed"
        )
    return {n: max(v, 0.0) for n, v in out.items()}, extents


def element_change(reaction: Reaction, formulas: Mapping[str, str]) -> dict[str, float] | None:
    """Atoms of each element the reaction as written creates (non-zero: unbalanced); None when
    a component's formula is missing or unreadable."""
    change: dict[str, float] = {}
    for name, nu in reaction.stoichiometry.items():
        atoms = parse_formula(formulas.get(name, ""))
        if atoms is None:
            return None
        for element, n in atoms.items():
            change[element] = change.get(element, 0.0) + nu * n
    return {e: v for e, v in change.items() if abs(v) > 1e-9}


def element_flows(
    moles: Mapping[str, float], formulas: Mapping[str, str]
) -> dict[str, float] | None:
    """kmol/h of each element in *moles* (component id -> kmol/h); None when a component with a
    flow has no readable formula."""
    flows: dict[str, float] = {}
    for name, n in moles.items():
        if not n:
            continue
        atoms = parse_formula(formulas.get(name, ""))
        if atoms is None:
            return None
        for element, count in atoms.items():
            flows[element] = flows.get(element, 0.0) + n * count
    return flows


def fit_extents(
    reactions: list[Reaction], change: Mapping[str, float]
) -> tuple[dict[str, float], dict[str, float]]:
    """The extents (kmol/h, by reaction id) that best explain *change* (component id -> kmol/h
    out minus in) in the least-squares sense, and what they leave unexplained per component.
    Reactions that depend on the others linearly get extent 0."""
    names = sorted({*change, *(n for r in reactions for n in r.stoichiometry)})
    a = [[r.stoichiometry.get(n, 0.0) for r in reactions] for n in names]
    b = [change.get(n, 0.0) for n in names]
    m = len(reactions)
    # normal equations (A^T A) x = A^T b, Gauss-Jordan with partial pivoting
    rows = [
        [sum(a[k][i] * a[k][j] for k in range(len(names))) for j in range(m)]
        + [sum(a[k][i] * b[k] for k in range(len(names)))]
        for i in range(m)
    ]
    pivots: list[int | None] = [None] * m
    row = 0
    for col in range(m):
        best = max(range(row, m), key=lambda r: abs(rows[r][col]), default=None)
        if best is None or abs(rows[best][col]) < 1e-12:
            continue
        rows[row], rows[best] = rows[best], rows[row]
        p = rows[row][col]
        rows[row] = [v / p for v in rows[row]]
        for r in range(m):
            if r != row and rows[r][col]:
                f = rows[r][col]
                rows[r] = [v - f * w for v, w in zip(rows[r], rows[row], strict=True)]
        pivots[col] = row
        row += 1
    x = [rows[pivots[j]][m] if pivots[j] is not None else 0.0 for j in range(m)]  # type: ignore[index]
    residual = {n: b[k] - sum(a[k][j] * x[j] for j in range(m)) for k, n in enumerate(names)}
    return {r.id: x[j] for j, r in enumerate(reactions)}, residual


#: The bases only a liquid is measured on.
LIQUID_ONLY = ("mole_fraction", "activity")


def phase_basis_problem(phase: str | None, basis: str) -> str:
    """What is wrong with a K or rate law on *basis* for a reaction of *phase*; empty if
    nothing (``concentration`` fits both phases)."""
    if phase == "liquid" and basis == "partial_pressure":
        return "is on partial pressures, but the reaction is liquid-phase"
    if phase == "vapor" and basis in LIQUID_ONLY:
        return f"is on {basis}, a liquid's measure, but the reaction is vapor-phase"
    if phase is None and basis in LIQUID_ONLY:
        return f"is on {basis}, a liquid's measure, but the reaction gives no phase: liquid"
    return ""


def _bases(reaction: Reaction, loc: list[Any]) -> list[tuple[str, str, list[Any]]]:
    found = []
    if reaction.equilibrium_constant is not None:
        found.append(
            (
                "equilibrium_constant",
                reaction.equilibrium_constant.basis,
                [*loc, "equilibrium_constant"],
            )
        )
    if reaction.rate is not None:
        found.append(("rate", reaction.rate.driving, [*loc, "rate", "driving"]))
    return found


def k_basis(reaction: Reaction) -> str:
    """The basis of *reaction*'s equilibrium constant: its own, else partial pressures (the
    ideal-gas data's)."""
    given = reaction.equilibrium_constant
    return given.basis if given is not None else "partial_pressure"


def is_liquid(reaction: Reaction) -> bool:
    return reaction.phase == "liquid"


def rules(reactions: Reactions, doc: Any, formulas: Mapping[str, str]) -> list[Finding]:
    """Every ``cheme.reaction-*`` finding of *reactions*; *formulas* are the declared
    components (id -> formula, empty when not given)."""
    findings: list[Finding] = []

    def add(level: str, rule: str, message: str, loc: list[Any], ids: list[str], hint: str):
        findings.append(
            Finding(
                REACTIONS_FILE,
                level,  # type: ignore[arg-type]
                f"cheme.reaction-{rule}",
                message,
                line=_yaml_line(doc, loc),
                ids=ids,
                hint=hint,
            )
        )

    seen: set[str] = set()
    for i, reaction in enumerate(reactions.reactions):
        loc = ["reactions", i]
        if reaction.id in seen:
            add(
                "error",
                "duplicate-id",
                f"reaction {reaction.id} is declared twice",
                loc,
                [reaction.id],
                "give each reaction its own id",
            )
        seen.add(reaction.id)
        unknown = [n for n in reaction.stoichiometry if n not in formulas]
        for name in unknown:
            add(
                "error",
                "component",
                f"reaction {reaction.id}: component {name} is not declared",
                [*loc, "stoichiometry", name],
                [reaction.id, name],
                "add it to process/materials.yaml components:",
            )
        if (
            reaction.conversion is not None
            and reaction.stoichiometry.get(reaction.conversion.key, 0) >= 0
        ):
            add(
                "error",
                "conversion",
                f"reaction {reaction.id}: conversion key {reaction.conversion.key} is not a "
                "reactant",
                [*loc, "conversion", "key"],
                [reaction.id],
                "name a component with a negative coefficient",
            )
        law = reaction.rate
        if law is not None:
            for name in law.species():
                if name not in formulas:
                    add(
                        "error",
                        "rate",
                        f"reaction {reaction.id}: its rate names component {name}, which is not "
                        "declared",
                        [*loc, "rate"],
                        [reaction.id, name],
                        "name components of process/materials.yaml",
                    )
            if law.reverse == "equilibrium" and not reaction.reversible:
                add(
                    "warning",
                    "rate",
                    f"reaction {reaction.id}: rate with reverse: equilibrium, but the reaction "
                    "is not reversible",
                    [*loc, "rate", "reverse"],
                    [reaction.id],
                    "set reversible: true, or reverse: none",
                )
        for what, basis, at in _bases(reaction, loc):
            problem = phase_basis_problem(reaction.phase, basis)
            gas_k = what == "equilibrium_constant" and reaction.phase != "liquid"
            if not problem and gas_k and basis != "partial_pressure":
                problem = (
                    f"is on {basis}, but a gas-phase equilibrium is taken on partial pressures"
                )
            if problem:
                add(
                    "warning",
                    "phase-basis",
                    f"reaction {reaction.id}: {what} {problem}",
                    at,
                    [reaction.id],
                    "write K and the rate on the measure of the reaction's phase "
                    "(partial_pressure for a gas; mole_fraction, activity or concentration for "
                    "a liquid), and give phase:",
                )
        mech = reaction.mechanism
        for j, step in enumerate(mech.steps if mech is not None else []):
            where = [*loc, "mechanism", "steps", j]
            undeclared = [n for n in step.gas() if n not in formulas]
            if undeclared:
                add(
                    "error",
                    "mechanism",
                    f"reaction {reaction.id}, step {step.id}: component "
                    f"{', '.join(undeclared)} is not declared",
                    where,
                    [reaction.id, step.id],
                    "add it to process/materials.yaml components:",
                )
                continue
            atoms = step_atoms(step, formulas)
            if atoms is None:
                add(
                    "info",
                    "mechanism",
                    f"reaction {reaction.id}, step {step.id}: no element balance (a formula is "
                    "missing or unreadable)",
                    where,
                    [reaction.id, step.id],
                    "give the formulas; an adsorbate's formula is its id without the *",
                )
            elif atoms:
                text = ", ".join(f"{e} {v:+g}" for e, v in sorted(atoms.items()))
                add(
                    "error",
                    "mechanism",
                    f"reaction {reaction.id}, step {step.id} does not balance: atoms created "
                    f"{text}",
                    where,
                    [reaction.id, step.id],
                    "correct the coefficients",
                )
            if abs(site_change(step)) > 1e-9:
                add(
                    "error",
                    "mechanism",
                    f"reaction {reaction.id}, step {step.id} creates {site_change(step):+g} sites",
                    where,
                    [reaction.id, step.id],
                    "every adsorbate takes one site: count the free sites * in and out",
                )
        if unknown:
            continue
        change = element_change(reaction, formulas)
        if change is None:
            lacking = [
                n for n in reaction.stoichiometry if parse_formula(formulas.get(n, "")) is None
            ]
            add(
                "info",
                "element-balance-not-evaluable",
                f"reaction {reaction.id}: no element balance, no readable formula for "
                + ", ".join(lacking),
                [*loc, "stoichiometry"],
                [reaction.id],
                "give formula: (e.g. C2H6O) in process/materials.yaml",
            )
        elif change:
            text = ", ".join(f"{e} {v:+g}" for e, v in sorted(change.items()))
            add(
                "error",
                "element-balance",
                f"reaction {reaction.id} does not balance: atoms created {text}",
                [*loc, "stoichiometry"],
                [reaction.id],
                "correct the coefficients or the formulas",
            )
    return findings


def selectivity_extents(
    reactions: list[Reaction],
    key: str,
    conversion: float,
    products: Mapping[str, float],
    moles: Mapping[str, float],
) -> dict[str, float]:
    """The extents (kmol/h, by reaction id) that convert *conversion* of the *key*'s inlet flow
    (*moles*, kmol/h) and form ``S_p`` kmol of each product per kmol of the key converted
    (*products*): the stoichiometric equations solved exactly. Raises ValueError when they do
    not determine every extent (too few selectivities for the reactions) or the reactions cannot
    give them (the selectivities and the stoichiometry disagree)."""
    converted = conversion * moles.get(key, 0.0)
    if converted <= 0:
        raise ValueError(f"no {key} in the feed to convert")
    rows = [(key, -converted)] + [(p, s * converted) for p, s in products.items()]
    a = [[r.stoichiometry.get(name, 0.0) for r in reactions] for name, _ in rows]
    b = [value for _, value in rows]
    m = len(reactions)
    # Gaussian elimination with full rank check (rows may exceed reactions: overdetermined)
    work = [[*row, rhs] for row, rhs in zip(a, b, strict=True)]
    pivots: list[int] = []
    r = 0
    for col in range(m):
        best = max(range(r, len(work)), key=lambda i: abs(work[i][col]), default=None)
        if best is None or abs(work[best][col]) < 1e-12:
            continue
        work[r], work[best] = work[best], work[r]
        p = work[r][col]
        work[r] = [v / p for v in work[r]]
        for i in range(len(work)):
            if i != r and work[i][col]:
                f = work[i][col]
                work[i] = [v - f * w for v, w in zip(work[i], work[r], strict=True)]
        pivots.append(col)
        r += 1
        if r == len(work):
            break
    if len(pivots) < m:
        free = [reactions[j].id for j in range(m) if j not in pivots]
        raise ValueError(
            "the selectivities do not determine the extent of "
            + ", ".join(free)
            + ": give the selectivity to a product of it"
        )
    scale = max(abs(v) for v in b)
    if any(abs(row[m]) > 1e-9 * scale for row in work[r:]):
        raise ValueError(
            "the reactions cannot give these selectivities together (check that the "
            "selectivities to the products account for the key converted)"
        )
    extents = [0.0] * m
    for i, col in enumerate(pivots):
        extents[col] = work[i][m]
    backwards = [
        rx.id
        for rx, x in zip(reactions, extents, strict=True)
        if x < -1e-9 * scale and not rx.reversible
    ]
    if backwards:
        raise ValueError(
            "these selectivities need the irreversible reaction(s) "
            + ", ".join(backwards)
            + " to run backwards: a selectivity is above what the reactions can give"
        )
    return {rx.id: x for rx, x in zip(reactions, extents, strict=True)}


def selectivity_outlet(
    reactions: list[Reaction],
    key: str,
    conversion: float,
    products: Mapping[str, float],
    moles: Mapping[str, float],
) -> dict[str, float]:
    """The outlet (kmol/h by component) of a conversion reactor given by the *key*'s
    *conversion* and the selectivities to its *products*, fed *moles* (kmol/h): the extents of
    :func:`selectivity_extents` applied to the feed (cheme process propagate's outlet, and each
    draw of cheme process reactor-uncertainty). Raises ValueError as that does, and when the
    extents consume more of a component than is fed."""
    extents = selectivity_extents(reactions, key, conversion, products, moles)
    outlet = dict(moles)
    for r in reactions:
        for n, nu in r.stoichiometry.items():
            outlet[n] = outlet.get(n, 0.0) + nu * extents[r.id]
    short = [n for n, v in outlet.items() if v < -1e-9 * max(1.0, abs(moles.get(n, 0.0)))]
    if short:
        raise ValueError(
            "the selectivities consume more than is fed of " + ", ".join(sorted(short))
        )
    return {n: max(v, 0.0) for n, v in outlet.items()}
