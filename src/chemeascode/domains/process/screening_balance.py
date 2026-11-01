"""A screening balance of a process that has no flowsheet yet: the reactants
a reaction scheme consumes and the products it forms per kg of the main product, from the
stoichiometry of ``process/reactions.yaml`` and the formulas of ``process/materials.yaml``.

Over the whole scheme an *efficiency* applies: the fraction of each reactant fed that reacts as
the scheme says, the rest leaving unconverted (the screening approach of Hischier et al. 2005,
Int J LCA 10:59, section 2.3: "an efficiency of 95% is assumed" over the entire stoichiometric
equation, unless a source gives the yield). With several reactions, the selectivities (kmol of
each product per kmol of the key reactant converted) fix the extents
(:func:`.chemistry.reactions.selectivity_extents`).

Molar masses come from the formulas (IUPAC atomic weights), so the balance closes in every
element by construction; :func:`element_masses` gives the kg of each element of a set of flows,
for the check of a dataset written from it (``assessment.lca.balance``).

The functions take plain inputs and never print; :func:`load_chemistry` reads the two files.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError

from chemeascode.domains.chemistry.formulas import ATOMIC_MASS, molar_mass, parse_formula
from chemeascode.domains.chemistry.reactions import (
    REACTIONS_FILE,
    Reaction,
    selectivity_extents,
)
from chemeascode.domains.process import MATERIALS_FILE
from chemeascode.domains.process.schema import Component, Materials
from chemeascode.foundation.findings import Finding


@dataclass
class Chemistry:
    """The reactions and components a screening balance reads, and the problems reading them."""

    reactions: dict[str, Reaction] = field(default_factory=dict)
    components: dict[str, Component] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)

    def formulas(self) -> dict[str, str]:
        return {c.id: c.formula for c in self.components.values() if c.formula}


def load_chemistry(root: Path) -> Chemistry:
    """The reactions (``process/reactions.yaml``) and components (``process/materials.yaml``)
    of the repository at *root*; a missing or invalid file is a finding."""
    from chemeascode.domains.process.model import _load_reactions, _read, _schema_findings
    from chemeascode.foundation.yamlsource import _compose

    chemistry = Chemistry()
    reactions, _, found = _load_reactions(Path(root))
    chemistry.findings += found
    if reactions is not None:
        chemistry.reactions = reactions.by_id()
    elif not found:
        chemistry.findings.append(
            Finding(
                REACTIONS_FILE,
                "error",
                "cheme.lci-estimate-input",
                f"no {REACTIONS_FILE}: a stoichiometric estimate starts from the reactions",
                hint="write the reactions (cheme schema process-reactions)",
            )
        )
    path = Path(root) / MATERIALS_FILE
    if not path.is_file():
        chemistry.findings.append(
            Finding(
                MATERIALS_FILE,
                "error",
                "cheme.lci-estimate-input",
                f"no {MATERIALS_FILE}: the components' formulas give the molar masses",
                hint="write the components with their formulas (cheme schema process-materials)",
            )
        )
        return chemistry
    data, found = _read(path, MATERIALS_FILE)
    chemistry.findings += found
    if data is None:
        return chemistry
    try:
        materials = Materials.model_validate(data)
    except ValidationError as failure:
        chemistry.findings += _schema_findings(MATERIALS_FILE, "materials", failure, _compose(path))
        return chemistry
    chemistry.components = {c.id: c for c in materials.components}
    return chemistry


@dataclass
class ScreeningBalance:
    """Per kg of *product*: what the scheme consumes and forms, what is fed at the efficiency,
    and what leaves unconverted (kg per kg of product; extents in kmol per kg)."""

    product: str
    efficiency: float
    extents: dict[str, float]
    consumed: dict[str, float]
    formed: dict[str, float]
    fed: dict[str, float]
    unconverted: dict[str, float]
    molar_masses: dict[str, float]


def stoichiometric_balance(
    reactions: list[Reaction],
    formulas: Mapping[str, str],
    product: str,
    efficiency: float,
    key: str | None = None,
    selectivity: Mapping[str, float] | None = None,
) -> ScreeningBalance:
    """The screening balance of *reactions* per kg of *product* at *efficiency* (0 < e <= 1).

    One reaction needs nothing more. Several need the *key* reactant and the *selectivity*
    (kmol of each product per kmol of the key converted) that fixes every extent. Raises
    ValueError when a formula is missing, the scheme does not form the product, or the
    selectivities do not determine the extents."""
    if not 0 < efficiency <= 1:
        raise ValueError(f"the efficiency is a fraction in (0, 1], not {efficiency:g}")
    if not reactions:
        raise ValueError("no reaction to balance")
    names = sorted({n for r in reactions for n in r.stoichiometry})
    masses: dict[str, float] = {}
    for name in names:
        mass = molar_mass(formulas.get(name, ""))
        if mass is None:
            raise ValueError(f"component {name} has no readable formula (process/materials.yaml)")
        masses[name] = mass
    if len(reactions) == 1:
        relative = {reactions[0].id: 1.0}
    else:
        if key is None or not selectivity:
            raise ValueError(
                "several reactions: give the key reactant and the selectivity to the products "
                "(kmol per kmol of the key converted)"
            )
        relative = selectivity_extents(reactions, key, 1.0, selectivity, {key: 1.0})
    net = {n: sum(r.stoichiometry.get(n, 0.0) * relative[r.id] for r in reactions) for n in names}
    if net.get(product, 0.0) <= 1e-12:
        raise ValueError(f"the reactions do not form {product}")
    scale = 1.0 / (net[product] * masses[product])
    extents = {rid: x * scale for rid, x in relative.items()}
    consumed = {n: -v * scale * masses[n] for n, v in net.items() if v < -1e-12}
    formed = {n: v * scale * masses[n] for n, v in net.items() if v > 1e-12}
    fed = {n: v / efficiency for n, v in consumed.items()}
    unconverted = {n: fed[n] - consumed[n] for n in fed}
    return ScreeningBalance(
        product=product,
        efficiency=efficiency,
        extents=extents,
        consumed=consumed,
        formed=formed,
        fed=fed,
        unconverted=unconverted,
        molar_masses=masses,
    )


def element_masses(
    flows: Mapping[str, float], formulas: Mapping[str, str]
) -> tuple[dict[str, float], list[str]]:
    """kg of each element in *flows* (name -> kg) whose formula (*formulas*, name -> formula)
    is readable, and the names whose formula is not."""
    masses: dict[str, float] = {}
    unreadable: list[str] = []
    for name, kg in flows.items():
        formula = formulas.get(name, "")
        atoms, mass = parse_formula(formula), molar_mass(formula)
        if atoms is None or not mass:
            unreadable.append(name)
            continue
        for element, count in atoms.items():
            masses[element] = masses.get(element, 0.0) + kg / mass * count * ATOMIC_MASS[element]
    return masses, unreadable
