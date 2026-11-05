"""The model basis of every reactor and separator: predicted, specified, or not declared.

A balanced flowsheet can close on numbers nobody predicted. This module says, per reactor and
separator (a step, or a block without steps), what its outlet rests on, so that a maturity check
(:mod:`chemeascode.project.maturity`) can keep specified models visibly apart from predictive
ones and never promote either on convergence alone:

- reactors: ``kinetic`` (``reactor: pfr``, a fixed bed, or ``cstr`` / ``batch``, stirred tanks:
  the reactions' rate laws, see :mod:`.fixed_bed` and :mod:`.stirred_tank` for their
  assumptions), ``equilibrium`` (``reactor: equilibrium`` or ``gibbs``: ideal-gas formation data
  or an equilibrium constant; a Gibbs reactor's components are those of its streams'
  compositions and templates, and only those in an independent reaction need the data: an
  inert passes through, see :func:`~chemeascode.domains.chemistry.thermochemistry.inert_species`),
  ``conversion`` (a specified conversion per reaction: the node's
  ``conversion:`` or the reaction's own, or the node's ``selectivity:``);
- separators (a ``Separating`` class with two or more material outlets) in
  ``process/simulation.yaml``, from the translation's basis (``translate.UNIT_BASIS``, the
  spec's ``basis``): ``equilibrium-stage`` (predictive: a flash or rigorous column),
  ``shortcut`` (a Fenske-Underwood-Gilliland column), ``component-split`` (specified: a
  component separator's recoveries, sourced when the spec gives ``basis_source``);
- crystallizers and filters (``crystallizer:``, ``solid_separation:``; :mod:`.crystallization`):
  ``solubility-equilibrium`` (predictive within its solubility data: the mother liquor leaves
  saturated), ``imposed-yield`` and ``solid-split`` (specified); solved by ``cheme process
  propagate``, never simulated; a dryer (``dryer:``; :mod:`.dryer`): ``residual-moisture``
  (specified), solved the same way;
- an adsorber with an entry in ``process/adsorption.yaml`` (:mod:`.separations.adsorption`):
  ``adsorption-equilibrium`` (predictive, not simulated: core's equilibrium TSA cycle gives the
  recoveries, inside every isotherm's range, meeting the specification, and the simulator's
  split agrees with them) or ``external-performance`` (specified: an external model's results,
  the feed inside its stated range, the simulator's split agreeing); otherwise its basis stays
  as above, with the reason listed as a limitation;
- a fixed bed or stirred tank counts as simulated only when the run record shows it coupled to
  the DWSIM solve as an external unit with a converged outer loop (:mod:`.simulation.coupling`);
- an electrochemical cell (a step a cell of ``process/cells.yaml`` names,
  :mod:`.electrochemical_cell`): ``electrochemical-cell``, specified (the voltage and current
  efficiency are given; the Faraday balance follows from them), never predictive;
- either, not modelled: ``stream-values`` (the outlet values as written in the flowsheet, given
  or assumed) or ``undeclared`` (an outlet value is missing).

``predictive`` is True for kinetic, equilibrium, equilibrium-stage, shortcut and
solubility-equilibrium bases. ``sourced``
says whether the model's own data carry a source: a rate law, a conversion or a selectivity
given with a source, a recovery with a ``basis_source``, ideal-gas data given, stream values
given with a source. A splitter (``SplittingMaterial``) divides a stream by a design decision
and is not classified.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from chemeascode.domains.chemistry.thermochemistry import inert_species
from chemeascode.domains.process import FLOWSHEET_FILE
from chemeascode.domains.process.fixed_bed import ASSUMPTIONS as BED_ASSUMPTIONS
from chemeascode.domains.process.fixed_bed import bed_limitations
from chemeascode.domains.process.model import Process
from chemeascode.domains.process.simulation import SIMULATION_FILE
from chemeascode.domains.process.stirred_tank import ASSUMPTIONS as TANK_ASSUMPTIONS
from chemeascode.foundation.provenance import written_by
from chemeascode.foundation.yamlsource import _yaml_line

PREDICTIVE = (
    "kinetic",
    "equilibrium",
    "equilibrium-stage",
    "shortcut",
    "solubility-equilibrium",
    "adsorption-equilibrium",
)
#: The propagate tool's source: its values follow from others and decide nothing here.
_PROPAGATE = "cheme process propagate"


@dataclass
class UnitBasis:
    """What one reactor or separator's outlet rests on."""

    id: str
    role: str  # reactor or separator
    basis: str
    predictive: bool
    sourced: bool
    simulated: bool = False
    file: str = FLOWSHEET_FILE
    line: int | None = None
    detail: str = ""
    sources: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    #: A conversion reactor's values against process/reaction-evidence.yaml (.evidence_basis)
    evidence: list[dict[str, Any]] = field(default_factory=list)

    def entry(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "role": self.role,
            "basis": self.basis,
            "predictive": self.predictive,
            "sourced": self.sourced,
            "simulated": self.simulated,
            "file": self.file,
            "line": self.line,
            "detail": self.detail,
            "sources": self.sources,
            "assumptions": self.assumptions,
            "limitations": self.limitations,
            "evidence": self.evidence,
        }


def _is_separator(process: Process, node: Any) -> bool:
    from chemeascode.domains.process.build import C, step_class

    cls = step_class(getattr(node, "class_", "") or "")
    separating = getattr(C, "Separating", None)
    if cls is None or separating is None or not issubclass(cls, separating):
        return False
    outlets = [p for p in node.ports if p.direction == "out" and p.kind == "material"]
    return len(outlets) >= 2


def _units(process: Process) -> list[tuple[str, int, Any]]:
    """(list key, index, node) of every step, and of every block without steps inside."""
    fs = process.flowsheet
    found = [("steps", i, s) for i, s in enumerate(fs.steps)]
    found += [("blocks", i, b) for i, b in enumerate(fs.blocks) if not process.inside(b.id)]
    return found


def _outlet_values(process: Process, node_id: str) -> tuple[list[str], list[str], list[str]]:
    """The outlet flow and composition values of *node_id* in every case: (missing, assumed
    or unsourced, sources), each as ``stream field (case)`` text."""
    missing: list[str] = []
    unsourced: list[str] = []
    sources: list[str] = []
    cases = [c.id for c in process.flowsheet.cases]
    for stream in process.flowsheet.streams:
        if stream.kind != "material":
            continue
        start, _ = process.ends(stream)
        if start is None or start.node != node_id:
            continue
        for case in cases:
            state = stream.state.get(case)
            for name in ("flow", "composition"):
                value = getattr(state, name, None) if state is not None else None
                where = f"{stream.id} {name} ({case})"
                if value is None:
                    missing.append(where)
                elif written_by(value, _PROPAGATE):
                    continue
                elif value.provenance == "given" and value.source.strip():
                    if value.source not in sources:
                        sources.append(value.source)
                else:
                    unsourced.append(where)
    return missing, unsourced, sources


def _stream_basis(process: Process, node_id: str, role: str) -> UnitBasis:
    missing, unsourced, sources = _outlet_values(process, node_id)
    if missing:
        return UnitBasis(
            node_id,
            role,
            "undeclared",
            False,
            False,
            detail="no model and outlet values missing: " + ", ".join(missing[:6]),
        )
    detail = "outlet values as written in the flowsheet (specified, no model)"
    if unsourced:
        detail += "; assumed or without a source: " + ", ".join(unsourced[:6])
        if len(unsourced) > 6:
            detail += f" and {len(unsourced) - 6} more"
    return UnitBasis(
        node_id, role, "stream-values", False, not unsourced, detail=detail, sources=sources
    )


def _gibbs_species(process: Process, node_id: str) -> list[str]:
    """The components a Gibbs reactor *node_id* can form or carry: those of the compositions and
    templates of its inlets and outlets (as :mod:`.propagate` takes them), so that a reactor
    whose outlet is not calculated yet still names the data it needs."""
    names: list[str] = []
    templates = process.templates()
    for stream in process.flowsheet.streams:
        if stream.kind != "material":
            continue
        start, end = process.ends(stream)
        if node_id not in (getattr(start, "node", None), getattr(end, "node", None)):
            continue
        for state in stream.state.values():
            if state.composition is not None:
                names += [n for n in state.composition.values if n not in names]
        template = templates.get(stream.template or "")
        names += [n for n in (template.components if template else []) if n not in names]
    return names


def _coupled(runs: list[dict[str, Any]]) -> str:
    """How the recorded runs coupled a fixed bed to the DWSIM solve, as text, when every one
    did so as an external unit with a converged outer loop; "" otherwise."""
    if not runs:
        return ""
    texts = []
    for row in runs:
        loop = row.get("outer_loop") or {}
        if row.get("coupling") != "external-unit" or loop.get("converged") is not True:
            return ""
        last = (loop.get("residuals") or [{}])[-1]
        texts.append(
            f"{loop.get('iterations')} DWSIM solves, last flow residual {last.get('flow', 0):.2g}"
        )
    return "coupled to DWSIM as an external unit, outer loop converged (" + "; ".join(texts) + ")"


def _reactor_basis(
    process: Process, node: Any, simulated: bool, runs: list[dict[str, Any]] | None = None
) -> UnitBasis:
    reactions, unknown = process.reactions_of(node.id)
    model = node.reactor
    if model in ("pfr", "cstr", "batch", "semibatch"):
        lacking = [r.id for r in reactions if r.rate is None]
        unsourced = [
            r.id
            for r in reactions
            if r.rate is not None and (r.rate.provenance != "given" or not r.rate.source.strip())
        ]
        if model == "pfr":
            catalysts = process.catalysts.by_id() if process.catalysts else {}
            catalyst = catalysts.get(node.catalyst or "")
            limitations = (
                bed_limitations(node.bed, catalyst) if node.bed is not None else ["no bed declared"]
            )
            what, assumptions = "fixed bed (pseudo-homogeneous plug flow)", list(BED_ASSUMPTIONS)
        else:
            spec = node.tank if model == "cstr" else node.batch
            declared = "tank" if model == "cstr" else "batch"
            limitations = [] if spec is not None else [f"no {declared} declared"]
            what = {
                "cstr": "stirred tank (CSTR)",
                "batch": "batch (stirred, well mixed)",
                "semibatch": "semi-batch (stirred, well mixed, dosed feeds)",
            }[model]
            assumptions = list(TANK_ASSUMPTIONS[model])
        coupled = _coupled(runs)
        if coupled:
            coupling = coupled
        elif not simulated:
            coupling = ""
            limitations.append(
                "not in a simulation: solved by cheme process propagate on its own, not coupled "
                "to a converged flowsheet with its recycles"
            )
        else:
            coupling = ""
            limitations.append(
                "no run record shows its external-unit coupling to the DWSIM solve converged "
                "(cheme process simulate --fill records the outer loop)"
            )
        problems = [f"no rate law for {', '.join(lacking)}"] if lacking else []
        if unsourced:
            problems.append(f"rate law of {', '.join(unsourced)} assumed or without a source")
        if unknown:
            problems.append(f"undeclared reaction {', '.join(unknown)}")
        if not reactions:
            problems.append("no reactions")
        return UnitBasis(
            node.id,
            "reactor",
            "kinetic",
            True,
            not problems,
            simulated=bool(coupling),
            detail=what
            + (f", {coupling}" if coupling else "")
            + (": " + "; ".join(problems) if problems else ""),
            sources=[r.rate.source for r in reactions if r.rate is not None and r.rate.source],
            assumptions=assumptions,
            limitations=limitations,
        )
    if model in ("equilibrium", "gibbs"):
        comps = process.components()
        names: list[str] = []
        inerts: list[str] = []
        bare: list[str] = []
        if model == "gibbs":
            names = _gibbs_species(process, node.id)
            try:  # as propagate solves it: inerts need no formation data
                inerts = inert_species(names, process.formulas())
            except ValueError:  # no formula: which species react is not known, all need data
                inerts = []
            names = [n for n in names if n not in inerts]
            bare = [n for n in inerts if getattr(comps.get(n), "ideal_gas", None) is None]
        else:
            for r in reactions:
                if r.equilibrium_constant is None:
                    names += [n for n in r.stoichiometry if n not in names]
        gaps = [n for n in names if getattr(comps.get(n), "ideal_gas", None) is None]
        unsourced = [n for n in names if n not in gaps and comps[n].ideal_gas.provenance != "given"]
        unsourced += [
            r.id
            for r in reactions
            if r.equilibrium_constant is not None and r.equilibrium_constant.provenance != "given"
        ]
        problems = [f"no ideal-gas data for {', '.join(gaps)}"] if gaps else []
        if unsourced:
            problems.append(f"data of {', '.join(unsourced)} not given")
        if unknown:
            problems.append(f"undeclared reaction {', '.join(unknown)}")
        if model == "equilibrium" and not reactions:
            problems.append("no reactions")
        if model == "gibbs" and not names and not inerts:
            problems.append(
                "no ideal-gas data: no components known on its streams (no composition or template)"
            )
        fugacity = (
            "ideal gas" if node.fugacity == "ideal" else "Peng-Robinson fugacity coefficients"
        )
        assumptions = [f"chemical equilibrium at the outlet temperature, {fugacity}"]
        if node.approach:
            assumptions.append(f"approach to equilibrium {node.approach:g} K")
        if bare:
            assumptions.append(
                f"ASSUMED: {', '.join(bare)} (inert) has no ideal-gas heat capacity, its sensible "
                "heat is left out of the duty"
            )
        limitations = ["equilibrium limit: no kinetics, the approach is not predicted"]
        if simulated and any(r.equilibrium_constant is None for r in reactions):
            limitations.append("in the simulation, K comes from DWSIM's own formation data")
        return UnitBasis(
            node.id,
            "reactor",
            "equilibrium",
            True,
            not problems,
            simulated=simulated,
            detail=f"{model} reactor"
            + (f" (inert, in no independent reaction: {', '.join(inerts)})" if inerts else "")
            + (": " + "; ".join(problems) if problems else ""),
            sources=sorted(
                (
                    {comps[n].ideal_gas.source for n in names if n not in gaps}
                    | {r.equilibrium_constant.source for r in reactions if r.equilibrium_constant}
                )
                - {""}
            ),
            assumptions=assumptions,
            limitations=limitations,
        )
    if node.selectivity is not None:  # the key's conversion and selectivities, not per reaction
        spec = node.selectivity
        sourced = spec.provenance == "given" and bool(spec.source.strip())
        problems = [] if sourced else [f"unsourced: selectivity ({spec.provenance})"]
        if unknown:
            problems.append(f"undeclared reaction {', '.join(unknown)}")
        return UnitBasis(
            node.id,
            "reactor",
            "conversion",
            False,
            not problems,
            simulated=simulated,
            detail=f"specified conversion of {spec.key} and selectivities"
            + (": " + "; ".join(problems) if problems else ""),
            sources=[spec.source] if spec.source.strip() else [],
            limitations=["specified conversion: selectivity and approach are not predicted"],
        )
    conversions = []
    unsourced = []
    for r in reactions:
        if r.id in node.conversion:
            conversions.append(r.id)
            unsourced.append(f"{r.id} (conversion on the node, no provenance)")
        elif r.conversion is not None:
            conversions.append(r.id)
            if r.conversion.provenance != "given" or not r.conversion.source.strip():
                unsourced.append(f"{r.id} (conversion {r.conversion.provenance})")
    if model == "conversion" or (reactions and len(conversions) == len(reactions)):
        lacking = [r.id for r in reactions if r.id not in conversions]
        problems = [f"no conversion for {', '.join(lacking)}"] if lacking else []
        if unsourced:
            problems.append("unsourced: " + ", ".join(unsourced))
        return UnitBasis(
            node.id,
            "reactor",
            "conversion",
            False,
            not problems,
            simulated=simulated,
            detail="specified conversion" + (": " + "; ".join(problems) if problems else ""),
            sources=[
                r.conversion.source
                for r in reactions
                if r.conversion is not None and r.conversion.source and r.id not in node.conversion
            ],
            limitations=["specified conversion: selectivity and approach are not predicted"],
        )
    return _stream_basis(process, node.id, "reactor")


def _separator_basis(
    process: Process, node: Any, sim: Any, simulated: bool, bases: dict[str, Any] | None
) -> UnitBasis:
    if simulated:
        from chemeascode.domains.process.simulation.translate import unit_of

        spec = sim.specs.get(node.id)
        inlets = len([p for p in node.ports if p.direction == "in" and p.kind == "material"])
        unit = (spec.unit if spec is not None else None) or unit_of(node.class_, inlets)
        if unit == "distillation_column" or (
            unit == "shortcut_column" and spec is not None and spec.stages
        ):
            unit = "distillation_column"
        from chemeascode.domains.process.simulation.translate import UNIT_BASIS

        package = f"{sim.simulator} {sim.property_package}"
        # the translation's basis (predictive, shortcut, specified) where it
        # made one
        given = (bases or {}).get(node.id) or {}
        kind = given.get("basis") or (spec.basis if spec is not None else None)
        kind = kind or UNIT_BASIS.get(unit or "")
        source = given.get("source") or (spec.basis_source if spec is not None else None) or ""
        if kind == "specified":
            sourced = bool(source.strip())
            operating = given.get("operating_basis") or (
                spec.operating_basis if spec is not None else None
            )
            return UnitBasis(
                node.id,
                "separator",
                "component-split",
                False,
                sourced,
                simulated=True,
                file=SIMULATION_FILE,
                detail="specified component recoveries"
                + (f" ({operating})" if operating else "")
                + ("" if sourced else " (no basis_source: assumed)"),
                sources=[source] if sourced else [],
                limitations=["specified split: the separation is not predicted"],
            )
        if kind == "shortcut":
            unit = "shortcut_column"
        if unit in ("flash", "distillation_column"):
            return UnitBasis(
                node.id,
                "separator",
                "equilibrium-stage",
                True,
                True,
                simulated=True,
                file=SIMULATION_FILE,
                detail=f"{unit} with {package}",
                sources=[package],
                assumptions=["equilibrium stages (no efficiency or rate-based model)"],
            )
        if unit == "shortcut_column":
            return UnitBasis(
                node.id,
                "separator",
                "shortcut",
                True,
                True,
                simulated=True,
                file=SIMULATION_FILE,
                detail=f"shortcut column with {package}",
                sources=[package],
                assumptions=[
                    "Fenske-Underwood-Gilliland: key-component recoveries specified, "
                    "constant relative volatility"
                ],
            )
    return _stream_basis(process, node.id, "separator")


def _sourced(value: Any) -> bool:
    return value is not None and value.provenance == "given" and bool(value.source.strip())


def solids_basis(process: Process, node: Any) -> UnitBasis:
    """The basis of a crystallizer (``solubility-equilibrium``, predictive within its
    solubility data; ``imposed-yield``, specified) or of a filter or centrifuge on its own
    (``solid-split``, specified); :mod:`.crystallization`. Neither is part of a simulation:
    ``cheme process propagate`` solves them."""
    from chemeascode.domains.process.crystallization import (
        ASSUMPTIONS,
        LIQUOR_ASSUMPTIONS,
        SEPARATION_ASSUMPTIONS,
    )

    outside = "not part of a converged simulation: solved by cheme process propagate"
    dryer = node.dryer
    if dryer is not None:
        from chemeascode.domains.process.dryer import ASSUMPTIONS as DRYER_ASSUMPTIONS

        moisture = dryer.residual_moisture
        sourced = _sourced(moisture)
        return UnitBasis(
            node.id,
            "separator",
            "residual-moisture",
            False,
            sourced,
            detail=f"dryer at {dryer.temperature:g} K: residual moisture {moisture.value:g} "
            f"({moisture.basis}) of {', '.join(dryer.volatiles)}"
            + ("" if sourced else " (not given with a source: assumed)"),
            sources=[moisture.source] if sourced else [],
            assumptions=list(DRYER_ASSUMPTIONS),
            limitations=["specified moisture: no drying curve or sorption isotherm", outside],
        )
    sep = node.solid_separation
    if sep is not None:
        sourced = _sourced(sep)
        return UnitBasis(
            node.id,
            "separator",
            "solid-split",
            False,
            sourced,
            detail=f"filter or centrifuge: solid recovery {sep.solid_recovery:g}, cake liquid "
            f"{sep.cake_liquid.value:g} ({sep.cake_liquid.basis})"
            + ("" if sourced else " (not given with a source: assumed)"),
            sources=[sep.source] if sourced else [],
            assumptions=list(SEPARATION_ASSUMPTIONS),
            limitations=["specified separation: no filtration or centrifuge model", outside],
        )
    spec = node.crystallizer
    sources: list[str] = []
    lacking: list[str] = []
    limitations = [outside, "no population balance (crystal size distribution not modelled)"]
    parts = [spec.solubility if spec.basis == "solubility" else spec.yield_, spec.separation]
    whats = [spec.basis, "separation"]
    salting = spec.solubility.salting_out if spec.solubility is not None else None
    if spec.basis == "solubility" and salting is not None:
        parts.append(salting)
        whats.append("salting_out")
    for part, what in zip(parts, whats, strict=True):
        if part is None:
            continue
        if _sourced(part):
            if part.source not in sources:
                sources.append(part.source)
        else:
            lacking.append(what)
    if spec.basis == "solubility":
        sol = spec.solubility
        basis, predictive = "solubility-equilibrium", True
        if sol.points:
            low, high = sol.points[0][0], sol.points[-1][0]
            t = spec.temperature
            detail = f"saturated mother liquor at {t:g} K, solubility data {low:g}-{high:g} K"
            if t is None or not low <= t <= high:
                lacking.append("temperature outside the solubility data")
        else:
            detail = "saturated mother liquor, solubility given at the operating conditions"
            limitations.append(
                "solubility given at the operating conditions only: no temperature dependence"
            )
    else:
        basis, predictive = "imposed-yield", False
        detail = f"imposed yield {spec.yield_.value:g} of the solute entering"
        limitations.append("imposed yield: the crystallization is not predicted")
    if spec.separation is not None:
        detail += (
            f"; filter or centrifuge: recovery {spec.separation.solid_recovery:g}, cake liquid "
            f"{spec.separation.cake_liquid.value:g} ({spec.separation.cake_liquid.basis})"
        )
        limitations.append("specified separation: no filtration or centrifuge model")
    if spec.recycle is not None:
        detail += f"; mother liquor recycle {spec.recycle.fraction:g}"
    assumptions = list(ASSUMPTIONS)
    if spec.spectators:
        sol = spec.solubility
        how = (
            "solubility measured in the mother liquor"
            if sol is not None and sol.measured_in == "mother_liquor"
            else "pure-solvent solubility with Setschenow salting-out"
            if salting is not None
            else "no solubility in the liquor"
        )
        detail += f"; spectators {', '.join(spec.spectators)} ({how})"
        if sol is not None and sol.measured_in == "pure_solvent" and salting is None:
            lacking.append("a solubility in the mixed liquor")
        assumptions += LIQUOR_ASSUMPTIONS
        limitations.append(
            "mixed liquor: the solubility data hold at the liquor composition their source "
            "states; no electrolyte activity model"
        )
    if lacking:
        detail += "; not sourced: " + ", ".join(lacking)
    return UnitBasis(
        node.id,
        "separator",
        basis,
        predictive,
        not lacking,
        detail=detail,
        sources=sources,
        assumptions=assumptions,
        limitations=limitations,
    )


def apply_adsorption(unit: UnitBasis, result: Any) -> None:
    """*unit*'s basis from its evaluated ``process/adsorption.yaml`` entry *result*
    (:class:`~.separations.adsorption.AdsorberResult`): calculated or external performance when
    it qualifies and the simulator's split follows from it; else a limitation saying why not."""
    from chemeascode.domains.process.separations.adsorption import ADSORPTION_FILE

    if not result.consistent or result.unsourced:
        why = (
            f"status {result.status}"
            if result.status != "qualified"
            else f"the simulated split {result.split.get('status', 'is not compared')}"
            if not result.consistent
            else f"inputs without a source: {', '.join(result.unsourced[:3])}"
        )
        unit.limitations.append(f"{ADSORPTION_FILE}: not used as the basis ({why})")
        return
    calculated = result.performance == "calculated"
    unit.basis = "adsorption-equilibrium" if calculated else "external-performance"
    unit.predictive = calculated
    unit.sourced = True
    unit.simulated = False
    unit.file, unit.line = ADSORPTION_FILE, result.line
    unit.detail = (
        f"{result.technique.upper()} {result.model}: recoveries "
        + (
            "calculated by core from the isotherms and the cycle"
            if calculated
            else "of an external model"
        )
        + "; the simulator closes the balance around them as a specified split"
    )
    unit.sources = list(result.sources)
    unit.assumptions = list(result.assumptions)
    unit.limitations = [*result.limitations, "calculated outside the simulation"]


def model_bases(
    process: Process,
    sim: Any = None,
    bases: dict[str, dict[str, Any]] | None = None,
    runs: dict[str, list[dict[str, Any]]] | None = None,
    evidence: Any = None,
    evidence_errors: Any = None,
    cells: dict[str, UnitBasis] | None = None,
    adsorption: dict[str, Any] | None = None,
) -> list[UnitBasis]:
    """The basis of every reactor and separator of *process*; *sim* is the parsed
    ``process/simulation.yaml`` (None: no simulation), whose excluded nodes are not simulated.
    *bases* is a translation's :attr:`~.simulation.translate.Translation.bases` (unit id ->
    ``basis``, ``source``, ``operating_basis``); *runs* the run-record rows of each unit, one per
    recorded case: a fixed bed counts as simulated only when every one shows a converged
    external-unit coupling (:mod:`.simulation.coupling`). *evidence* is the parsed
    ``process/reaction-evidence.yaml``: a conversion reactor's values its decided model basis
    covers count as sourced (:mod:`.evidence_basis`); *evidence_errors* are the error findings
    that block support (:class:`~chemeascode.domains.chemistry.evidence.Blocking`). *cells*
    are the bases of the steps an electrochemical cell of ``process/cells.yaml`` is linked to
    (:func:`.electrochemical_cell.cell_bases`): specified, never predictive.
    *adsorption* maps a separator id to its evaluated ``process/adsorption.yaml`` entry
    (:func:`apply_adsorption`)."""
    excluded: dict[str, str] = {}
    if sim is not None:
        from chemeascode.domains.process.simulation.record import excluded as left_out

        excluded = left_out(process, sim)
    found = []
    for key, index, node in _units(process):
        simulated = sim is not None and node.id not in excluded
        reacting = bool(getattr(node, "reactions", None)) or getattr(node, "reactor", None)
        if cells and node.id in cells:
            unit = cells[node.id]
        elif (
            node.crystallizer is not None
            or node.solid_separation is not None
            or node.dryer is not None
        ):
            unit = solids_basis(process, node)
        elif reacting:
            unit = _reactor_basis(process, node, simulated, (runs or {}).get(node.id, []))
            if evidence is not None:
                from chemeascode.domains.process.evidence_basis import apply_evidence

                apply_evidence(unit, process, node, evidence, evidence_errors)
        elif _is_separator(process, node):
            unit = _separator_basis(process, node, sim, simulated, bases)
            if adsorption and node.id in adsorption:
                apply_adsorption(unit, adsorption[node.id])
        else:
            continue
        if unit.file == FLOWSHEET_FILE:
            unit.line = _yaml_line(process.flowsheet_doc, [key, index])
        found.append(unit)
    return found
