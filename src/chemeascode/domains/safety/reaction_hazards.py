"""Thermal screening of reactors: the adiabatic temperature rise, the maximum temperature of the
synthesis reaction (MTSR) after a cooling failure, Stoessel's criticality class and, for cooled
fixed beds, the parametric sensitivity of the hot spot (``cheme process reactor-hazards``).

Per reactor (a block or step that names reactions or a reactor model), from its inlet stream:

- ``T_p``, the process temperature: a batch's charge temperature, a CSTR's solved temperature,
  else the outlet's given temperature or the inlet's;
- ``dT_ad``, the adiabatic rise: the largest heat of one reaction run to completion of its
  limiting reactant, over the heat capacity of the feed (a liquid's ``liquid_heat_capacity``,
  a gas's ideal-gas cp; ``heat_of_reaction``, else the ideal-gas data's);
- the accumulation ``X_ac``: 1 for a batch (all charged; cooling fails at the start) and for
  a plug-flow or conversion reactor (fresh feed at its inlet), the unconverted fraction of the
  key for a CSTR; ``MTSR = T_p + X_ac dT_ad``;
- a semi-batch (Stoessel's treatment of dosing-controlled reactions): ``X_ac`` the largest
  accumulation of the dosed reactant over the run, the MTSR the cooling-failure temperature at
  its worst moment (the dosing stopped; :mod:`.process.stirred_tank`), ``T_p`` the temperature
  then and ``dT_ad`` of the whole batch, charge and doses;
- ``MTT`` from the reactor's ``hazard.mtt``, else the lowest normal boiling point of a
  liquid-phase reactor's components at about atmospheric pressure (110 kPa(a) at most);
  ``TD24`` from ``hazard.td24`` only (calorimetry; never estimated);
- the criticality class (Stoessel, Chem. Eng. Prog. 89 (1993) 68): 1 MTSR < MTT < TD24,
  2 MTSR < TD24 < MTT, 3 MTT < MTSR < TD24, 4 MTT < TD24 < MTSR, 5 TD24 < MTSR with
  TD24 < MTT;
- for a cooled fixed bed: the hot spot's sensitivity ``d T_hot / d T_coolant`` (1 K steps);
  above 5 the bed is near runaway (parametric sensitivity, Morbidelli and Varma).

Phase changes are not reactions (ADR 0056): a step whose reactions are all phase changes
(``kind: phase-change``, or one component into one other of the same formula, one of them
``phase: solid``, e.g. a precipitation ``NBS -> NBS_S`` written as a conversion) is not
screened; a step with reactions
and phase changes is screened on its reactions alone.

Rules (``cheme.reactor-hazard-*``, findings on ``process/flowsheet.yaml``): ``-class``
(info for classes 1 and 2, warning for 3 to 5), ``-mtsr`` (warning: the MTSR above the MTT or
the TD24 where the class cannot be given), ``-sensitivity`` (warning), ``-missing`` (info: what
the screening lacks), ``-phase-change`` (info: a step not screened, its reactions all phase
changes). These are screening values for a concept or basic design: they do not replace
calorimetry or a reaction-hazard study, and decide nothing.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from chemeascode.foundation.findings import Finding
from chemeascode.foundation.provenance import SourceRevision, source_revision
from chemeascode.foundation.yamlsource import _yaml_line

FLOWSHEET = "process/flowsheet.yaml"
#: kPa(a): up to this pressure the normal boiling point stands for the MTT.
ATMOSPHERIC = 110.0
#: K/K: a hot spot this sensitive to the coolant temperature is near runaway.
SENSITIVE = 5.0


@dataclass
class HazardEntry:
    node: str
    model: str
    process_temperature: float | None = None  # K
    adiabatic_rise: float | None = None  # K
    accumulation: float | None = None
    mtsr: float | None = None  # K
    mtt: float | None = None  # K
    mtt_basis: str = ""
    td24: float | None = None  # K
    criticality: int | None = None
    sensitivity: float | None = None  # K/K
    missing: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class PhaseChangeStep:
    """A step not screened: its reactions are all phase changes (reaction id -> why)."""

    node: str
    reactions: dict[str, str]


@dataclass
class HazardReport:
    entries: list[HazardEntry]
    findings: list[Finding]
    source: SourceRevision | None = None
    phase_changes: list[PhaseChangeStep] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(
            {
                "reactors": [asdict(e) for e in self.entries],
                "phase_changes": [asdict(p) for p in self.phase_changes],
                "findings": [
                    {
                        "file": f.file,
                        "line": f.line,
                        "level": f.level,
                        "rule": f.rule,
                        "message": f.message,
                        "ids": f.ids,
                        "hint": f.hint,
                        "id": f.id,
                    }
                    for f in self.findings
                ],
                "source": self.source.as_dict() if self.source else None,
            },
            indent=2,
        )


def criticality(mtsr: float, mtt: float, td24: float) -> int:
    """Stoessel's criticality class (see the module docstring)."""
    if td24 < mtsr:
        return 4 if mtt < td24 else 5
    if mtsr < mtt:
        return 1 if mtt < td24 else 2
    return 3


def _location(process: Any, node: str) -> list[Any]:
    for key in ("blocks", "steps"):
        for i, item in enumerate(getattr(process.flowsheet, key)):
            if item.id == node:
                return [key, i]
    return []


def _adiabatic_rise(
    reactions: list[Any], moles: dict[str, float], t: float, comps: dict[str, Any], data: Any
) -> tuple[float | None, list[str]]:
    """K: the largest heat of one reaction run to completion, over the feed's heat capacity."""
    from chemeascode.domains.chemistry.thermochemistry import missing, reaction_enthalpy

    lacking: list[str] = []
    liquid = any(r.phase == "liquid" for r in reactions)
    present = {n: v for n, v in moles.items() if v > 0}
    if liquid:
        no_cp = sorted(n for n in present if not getattr(comps.get(n), "liquid_heat_capacity", 0))
        if no_cp:
            return None, ["liquid_heat_capacity of " + ", ".join(no_cp)]
        capacity = sum(v * comps[n].liquid_heat_capacity for n, v in present.items())
    else:
        if lack := missing(list(present), data):
            return None, ["ideal_gas data of " + ", ".join(lack)]
        capacity = sum(v * data[n].cp(t) for n, v in present.items())
    best = 0.0
    for r in reactions:
        if r.heat_of_reaction is not None:
            heat = r.heat_of_reaction.value
        elif not liquid and not missing(list(r.stoichiometry), data):
            heat = reaction_enthalpy(r.stoichiometry, data, t)
        else:
            lacking.append(f"heat_of_reaction of {r.id}")
            continue
        extent = min(
            (moles.get(n, 0.0) / -nu for n, nu in r.stoichiometry.items() if nu < 0),
            default=0.0,
        )
        best = max(best, -heat * extent)
    if lacking and best == 0.0:
        return None, lacking
    return best / capacity if capacity > 0 else None, lacking


def phase_changes(process: Any, node: str) -> dict[str, str]:
    """Reaction id -> why it is a phase change, of the reactions of *node* that are."""
    from chemeascode.domains.chemistry.reactions import phase_change
    from chemeascode.domains.process.solids import solid_components

    reactions, _ = process.reactions_of(node)
    formulas = process.formulas()
    solids = solid_components(process)
    found = {r.id: phase_change(r, formulas, solids) for r in reactions}
    return {k: v for k, v in found.items() if v}


def screen_node(process: Any, node: str, case: str) -> HazardEntry:
    """The screening of reactor *node* in *case* (see the module docstring); its phase
    changes take no part (the screening of its reactions alone)."""
    from chemeascode.domains.process.model import stream_flows
    from chemeascode.foundation.units import to_kelvin, to_kpa_abs

    fs = process.flowsheet
    item = process.nodes[node]
    model = getattr(item, "reactor", None) or "conversion"
    entry = HazardEntry(node, model)
    reactions, _ = process.reactions_of(node)
    if changes := phase_changes(process, node):
        reactions = [r for r in reactions if r.id not in changes]
        entry.notes.append("phase changes not screened as reactions: " + ", ".join(sorted(changes)))
    inlets = [s for s in fs.streams if (e := process.ends(s)[1]) is not None and e.node == node]
    if model == "semibatch":  # its charge and doses: the material inlets
        inlets = [s for s in inlets if s.kind == "material"]
        return _screen_semibatch(process, item, entry, reactions, inlets, case)
    if len(inlets) != 1:
        entry.missing.append("one inlet stream")
        return entry
    inlet = inlets[0]
    state = inlet.state.get(case)
    t = getattr(state, "temperature", None)
    p = getattr(state, "pressure", None)
    t_in = to_kelvin(t.value, t.unit or fs.units.temperature) if t is not None else None
    p_in = to_kpa_abs(p.value, p.unit or fs.units.pressure) if p is not None else None
    if t_in is None:
        entry.missing.append(f"the temperature of {inlet.id}")
        return entry
    flows = stream_flows(process, inlet, case)
    comps = process.components()
    if flows.components is None:
        entry.missing.append(f"the composition and flow of {inlet.id}")
        return entry
    moles = {
        n: kg / comps[n].molar_mass
        for n, kg in flows.components.items()
        if kg and getattr(comps.get(n), "molar_mass", None)
    }
    t_p = t_in
    accumulation = 1.0
    if model == "cstr":
        from chemeascode.domains.process.stirred_tank import TankError, solve_node

        try:
            solved, _ = solve_node(process, item, inlet, case)
        except TankError as failure:
            entry.missing.append(f"the tank: {failure}")
        else:
            # the first tank of a series holds the most unconverted key: its temperature and
            # accumulation give the largest MTSR
            first = solved.tanks[0]
            t_p = first["temperature_K"]
            key = next(
                (
                    n
                    for r in reactions
                    for n, v in r.stoichiometry.items()
                    if v < 0 and moles.get(n, 0) > 0
                ),
                None,
            )
            if key is not None:
                accumulation = 1.0 - first["conversion"].get(key, 0.0)
            entry.notes.append("accumulation: the unconverted key in the (first) tank")
    if model == "batch":
        entry.notes.append("accumulation 1: all charged, cooling fails at the start")
    elif model != "cstr":
        entry.notes.append("accumulation 1: the fresh feed, at the inlet's temperature")
    entry.process_temperature = t_p
    entry.accumulation = accumulation
    rise, lacking = _adiabatic_rise(reactions, moles, t_p, comps, process.ideal_gas())
    entry.missing += lacking
    entry.adiabatic_rise = rise
    if rise is not None:
        entry.mtsr = t_p + accumulation * rise
    _limits(entry, item, reactions, moles, comps, p_in)
    bed = getattr(item, "bed", None)
    if model == "pfr" and bed is not None and bed.heat == "cooled" and bed.coolant_temperature:
        entry.sensitivity = _sensitivity(process, item, inlet, case)
    return entry


def _screen_semibatch(
    process: Any, item: Any, entry: HazardEntry, reactions: list[Any], inlets: list[Any], case: str
) -> HazardEntry:
    """A semi-batch (Stoessel's treatment): ``X_ac`` the largest accumulation of the dosed
    reactant over the run, the MTSR the cooling-failure temperature at the worst moment (the
    dosing stopped, the content then reacting to completion adiabatically), ``T_p`` the
    process temperature then; ``dT_ad`` of the whole batch, charge and doses."""
    from chemeascode.domains.process.stirred_tank import TankError, solve_node, stream_moles

    comps = process.components()
    moles: dict[str, float] = {}
    p_in = None
    try:
        for stream in inlets:
            found, t_in, kpa = stream_moles(process, stream, case)
            for n, v in found.items():
                if v > 0:  # a template's component the stream does not carry is not there
                    moles[n] = moles.get(n, 0.0) + v
            p_in = kpa if p_in is None else min(p_in, kpa)
        solved, _ = solve_node(process, item, inlets, case)
    except TankError as failure:
        entry.missing.append(f"the semibatch: {failure}")
        return entry
    worst = solved.cooling_failure
    entry.process_temperature = worst[1] if worst else solved.profile[0][1]
    rise, lacking = _adiabatic_rise(
        reactions, moles, entry.process_temperature, comps, process.ideal_gas()
    )
    entry.missing += lacking
    entry.adiabatic_rise = rise
    entry.accumulation = solved.max_accumulation
    if worst is not None:
        entry.mtsr = worst[2]
        entry.notes.append(
            f"accumulation: the dosed reactant's largest, {solved.max_accumulation or 0:.3g} at "
            f"{solved.max_accumulation_time or 0:.6g} s; MTSR at the worst moment, {worst[0]:.6g} "
            "s (dosing stopped, the content's heat capacity then)"
        )
    elif rise is not None and solved.max_accumulation is not None:
        entry.mtsr = entry.process_temperature + solved.max_accumulation * rise
        entry.notes.append("MTSR: T_p + X_ac dT_ad (no cooling-failure temperature over the run)")
    else:
        entry.missing.append("the accumulation of a dosed reactant")
    _limits(entry, item, reactions, moles, comps, p_in)
    return entry


def _limits(
    entry: HazardEntry,
    item: Any,
    reactions: list[Any],
    moles: dict[str, float],
    comps: dict[str, Any],
    p_in: float | None,
) -> None:
    """The MTT and TD24 of *entry*, and its class once the MTSR is known."""
    hazard = getattr(item, "hazard", None)
    if hazard is not None and hazard.mtt:
        entry.mtt, entry.mtt_basis = hazard.mtt, "hazard.mtt"
    elif any(r.phase == "liquid" for r in reactions) and (p_in or 101.325) <= ATMOSPHERIC:
        boiling = [
            (comps[n].normal_boiling_point, n)
            for n in moles
            if getattr(comps.get(n), "normal_boiling_point", None)
        ]
        if boiling:
            entry.mtt, name = min(boiling)
            entry.mtt_basis = f"normal boiling point of {name}"
        else:
            entry.missing.append("the MTT (hazard.mtt, or normal_boiling_point)")
    else:
        entry.missing.append("the MTT (hazard.mtt)")
    if hazard is not None and hazard.td24:
        entry.td24 = hazard.td24
    else:
        entry.missing.append("TD24 of the decomposition (hazard.td24, from calorimetry)")
    if entry.mtsr is not None and entry.mtt is not None and entry.td24 is not None:
        entry.criticality = criticality(entry.mtsr, entry.mtt, entry.td24)


def _sensitivity(process: Any, item: Any, inlet: Any, case: str) -> float | None:
    """K/K: the hot spot's change per kelvin of coolant temperature (central, 1 K steps)."""
    from chemeascode.domains.process.fixed_bed import BedError, solve_node

    spots = []
    for delta in (-1.0, 1.0):
        bed = item.bed.model_copy(
            update={"coolant_temperature": item.bed.coolant_temperature + delta}
        )
        try:
            solved, _ = solve_node(process, item.model_copy(update={"bed": bed}), inlet, case)
        except BedError:
            return None
        spots.append(solved.hot_spot)
    return (spots[1] - spots[0]) / 2.0


def screen(root: Path, case: str | None = None) -> HazardReport:
    """Every reactor of the plant at *root* screened in *case* (default: the default case), with
    the ``cheme.reactor-hazard-*`` findings. A process that does not load gives its findings."""
    from chemeascode.domains.process.model import load

    root = Path(root)
    process, found = load(root)
    if process is None:
        return HazardReport([], found)
    case = case or process.flowsheet.default_case()
    fs = process.flowsheet
    entries: list[HazardEntry] = []
    skipped: list[PhaseChangeStep] = []
    for n in [*fs.blocks, *fs.steps]:
        if not (process.reactive(n.id) and (n.reactions or getattr(n, "reactor", None))):
            continue
        reactions, _ = process.reactions_of(n.id)
        changes = phase_changes(process, n.id)
        if reactions and len(changes) == len(reactions):
            skipped.append(PhaseChangeStep(n.id, dict(sorted(changes.items()))))
        else:
            entries.append(screen_node(process, n.id, case))
    findings: list[Finding] = []
    for p in skipped:
        findings.append(
            Finding(
                FLOWSHEET,
                "info",
                "cheme.reactor-hazard-phase-change",
                f"{p.node}: not screened: its reactions are phase changes ("
                + ", ".join(f"{r}: {why}" for r, why in p.reactions.items())
                + "), no reaction heat to run away",
                line=_yaml_line(process.flowsheet_doc, _location(process, p.node)),
                ids=[p.node],
                hint="model a precipitation or a reslurry wash as a crystallizer: (spectators, "
                "a solubility in the liquor) rather than conversion reactions; a phase change "
                "that stays a reaction says kind: phase-change in process/reactions.yaml",
            )
        )
    for e in entries:
        line = _yaml_line(process.flowsheet_doc, _location(process, e.node))

        def add(
            level: str, rule: str, message: str, hint: str, e: HazardEntry = e, line: Any = line
        ) -> None:
            findings.append(
                Finding(
                    FLOWSHEET,
                    level,
                    f"cheme.reactor-hazard-{rule}",  # type: ignore[arg-type]
                    message,
                    line=line,
                    ids=[e.node],
                    hint=hint,
                )
            )

        temps = (
            f"T_p {e.process_temperature:.1f} K, MTSR {e.mtsr:.1f} K"
            if e.mtsr is not None and e.process_temperature is not None
            else ""
        )
        if e.criticality is not None:
            add(
                "info" if e.criticality <= 2 else "warning",
                "class",
                f"{e.node}: criticality class {e.criticality} ({temps}, MTT {e.mtt:.1f} K, "
                f"TD24 {e.td24:.1f} K)",
                "screening values (Stoessel); classes 3 to 5 need a reaction-hazard study and "
                "technical measures (feed control, emergency cooling, relief)",
            )
        elif e.mtsr is not None:
            above = [
                n for n, v in (("MTT", e.mtt), ("TD24", e.td24)) if v is not None and e.mtsr > v
            ]
            if above:
                add(
                    "warning",
                    "mtsr",
                    f"{e.node}: {temps} above the {' and the '.join(above)}",
                    "a cooling failure takes the reaction beyond it: limit the accumulation, "
                    "or plan emergency cooling or relief",
                )
        if e.sensitivity is not None and e.sensitivity > SENSITIVE:
            add(
                "warning",
                "sensitivity",
                f"{e.node}: the hot spot moves {e.sensitivity:.1f} K per K of coolant "
                "temperature (parametric sensitivity: near runaway)",
                "lower the coolant temperature, dilute the feed, or use smaller tubes",
            )
        if e.missing:
            add(
                "info",
                "missing",
                f"{e.node}: no full screening without " + "; ".join(dict.fromkeys(e.missing)),
                "give them in process/ and on the reactor's hazard:",
            )
    from chemeascode.domains.process import FLOWSHEET_FILE, MATERIALS_FILE

    paths = [FLOWSHEET_FILE, MATERIALS_FILE, "process/reactions.yaml", "process/catalysts.yaml"]
    return HazardReport(entries, findings, source_revision(root, paths), skipped)


def hazard_text(report: HazardReport) -> str:
    """The screening as text, one block per reactor, then its findings."""

    def num(v: float | None, unit: str) -> str:
        return "?" if v is None else f"{v:.1f} {unit}"

    lines = []
    for e in report.entries:
        lines.append(
            f"{e.node} ({e.model}): T_p {num(e.process_temperature, 'K')}, dT_ad "
            f"{num(e.adiabatic_rise, 'K')}, accumulation "
            f"{'?' if e.accumulation is None else f'{e.accumulation:.3g}'}, "
            f"MTSR {num(e.mtsr, 'K')}, "
            f"MTT {num(e.mtt, 'K')}{f' ({e.mtt_basis})' if e.mtt_basis else ''}, TD24 "
            f"{num(e.td24, 'K')}, class {e.criticality or '?'}"
            + (
                f", hot spot sensitivity {e.sensitivity:.2f} K/K"
                if e.sensitivity is not None
                else ""
            )
        )
        lines += [f"  note: {n}" for n in e.notes]
    for p in report.phase_changes:
        lines.append(f"{p.node}: not screened (phase changes: {', '.join(p.reactions)})")
    if not report.entries and not report.phase_changes:
        lines.append("no reactors")
    lines += [f.format() for f in report.findings]
    lines.append("screening values: they do not replace calorimetry or a reaction-hazard study")
    return "\n".join(lines)
