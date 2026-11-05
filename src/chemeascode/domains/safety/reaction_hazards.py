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
- a vented batch or semi-batch (``batch.vent``, ADR 0054): the vented gas leaves as it forms,
  so it adds nothing to the content's heat capacity nor to the MTSR, and a dosed gas counts
  only with its absorbed share. The notes give the vent's peak gas rate over the run;
- ``MTT`` from the reactor's ``hazard.mtt``, else the lowest boiling point of a liquid-phase
  reactor's components at its pressure (ADR 0058): the normal boiling point at about
  atmospheric pressure (90 to 110 kPa(a)), else ``1/T = 1/T_b - R ln(P/P0)/dH_vap``
  (Clausius-Clapeyron, the component's ``heat_of_vaporization``; without it a note, and above
  atmospheric no MTT where the component could set it). Left out: a batch's vent components,
  a dosed gas (a dose that declares ``absorbed``) and dissolved gases, a minor share of the
  liquid (below :data:`DISSOLVED` of the charge and doses) boiling below ``T_p`` (they boil off
  rather than boil the batch: a note names them, and with nothing else left the MTT needs
  ``hazard.mtt``). A larger share boiling below ``T_p`` is the liquor at its boiling point (at
  reflux): it sets the MTT, at or below ``T_p``, with a note; ``TD24`` from ``hazard.td24``
  only (calorimetry; never estimated);
- ``hazard.reactions`` names the reactions whose heat counts (default: every reaction, the
  largest run to completion); with more than one reaction, or that choice, the output gives
  ``dT_ad`` and the MTSR of each reaction alone (an endothermic one: its MTSR is ``T_p``) and
  the reactions counted (ADR 0058);
- a semi-batch's MTSR profile: time, ``X_ac`` and the MTSR (of the reactions counted) at
  :data:`PROFILE_POINTS` moments over the batch;
- a vented batch or semi-batch's gas release at the MTSR: the vent's components forming at the
  rate laws of every reaction at the MTSR, the larger with two contents: the worst moment's
  (the accumulated reactant) and the content once the reaction setting the MTSR ran to
  completion (gas formed from its products, a consecutive decomposition); gas from a longer
  chain is not covered. In kmol/s per batch (``process/recipe.yaml``'s batch size, else per
  hour of the flowsheet's flows) and m3/h at the MTSR and the vessel's pressure, and the most
  gas one reaction forms run to completion: of the counted reactions (``hazard.reactions``,
  else every one) from the worst moment's content, or of a reaction consuming a product of the
  one setting the MTSR from the content after it; compared with ``hazard.vent_capacity``;
- the criticality class (Stoessel, Chem. Eng. Prog. 89 (1993) 68): 1 MTSR < MTT < TD24,
  2 MTSR < TD24 < MTT, 3 MTT < MTSR < TD24, 4 MTT < TD24 < MTSR, 5 TD24 < MTSR with
  TD24 < MTT;
- for a cooled fixed bed: the hot spot's sensitivity ``d T_hot / d T_coolant`` (1 K steps);
  above 5 the bed is near runaway (parametric sensitivity, Morbidelli and Varma).

Phase changes are not reactions (ADR 0056): a step whose reactions are all phase changes
(``kind: phase-change``, or one component into one other of the same formula, one of them
``phase: solid``, e.g. a precipitation ``NBS -> NBS_S`` written as a conversion, that declares
no heat of reaction) is not screened; a step with reactions and phase changes takes its dT_ad
and MTT from its reactions alone, but a semi-batch's cooling-failure MTSR from its whole model,
the phase changes' kinetics and heat included (a note says so). A phase change detected by its
formula that declares a heat of reaction (a caustic dissolution) is screened as a reaction: its
heat counts in dT_ad.

Rules (``cheme.reactor-hazard-*``, findings on ``process/flowsheet.yaml``): ``-class``
(info for classes 1 and 2, warning for 3 to 5), ``-mtsr`` (warning: the MTSR above the MTT or
the TD24 where the class cannot be given), ``-sensitivity`` (warning), ``-missing`` (info: what
the screening lacks), ``-phase-change`` (info: a step not screened, its reactions all phase
changes), ``-reactions`` (warning: ``hazard.reactions`` names a reaction not screened in the
step), ``-vent`` (a vented batch's gas release at the MTSR: a warning without
``hazard.vent_capacity`` or above it, info within it). With the vent blocked the gas
pressurises the vessel: that pressure is not screened (no head space or relief model). These
are screening values for a concept or basic design: they do not replace calorimetry or a
reaction-hazard study, and decide nothing.
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
#: kPa(a): from this pressure up; below it a component boils lower (Clausius-Clapeyron).
BELOW_ATMOSPHERIC = 90.0
#: Moments of a semi-batch's MTSR profile in the JSON (and its worst); the text line takes
#: TEXT_POINTS of them evenly, and the worst.
PROFILE_POINTS = 21
TEXT_POINTS = 6
#: Mole fraction of the liquid (charge and doses) below which a component boiling below T_p is
#: a dissolved gas, left out of the default MTT; a larger share is the liquor itself boiling
#: (at reflux): it sets the MTT, at or below T_p (ADR 0058).
DISSOLVED = 0.05
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
    #: ADR 0058, in the JSON only when given: the reactions dT_ad and the MTSR are taken from
    #: and why (hazard.reactions, or every reaction), set with more than one reaction or that
    #: choice; each reaction alone (reaction id -> adiabatic_rise K, mtsr K, a semi-batch's
    #: time s of its worst moment); names of hazard.reactions not screened here
    counted_reactions: list[str] = field(default_factory=list)
    counted_basis: str = ""
    per_reaction: dict[str, dict[str, float | None]] = field(default_factory=dict)
    unknown_reactions: list[str] = field(default_factory=list)
    #: a semi-batch: time_s, accumulation, temperature_K and mtsr_K at PROFILE_POINTS moments
    mtsr_profile: list[dict[str, float | None]] = field(default_factory=list)
    #: a vented batch: the gas release at the MTSR (see the module docstring)
    gas_release: dict[str, Any] | None = None
    #: component -> why the default MTT leaves it out
    mtt_left_out: dict[str, str] = field(default_factory=dict)


#: HazardEntry's fields the JSON gives only when they hold something (ADR 0058): a reactor
#: without them reports as before.
OPTIONAL = (
    "counted_reactions",
    "counted_basis",
    "per_reaction",
    "unknown_reactions",
    "mtsr_profile",
    "gas_release",
    "mtt_left_out",
)


def _entry_json(entry: HazardEntry) -> dict[str, Any]:
    return {k: v for k, v in asdict(entry).items() if k not in OPTIONAL or v}


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
                "reactors": [_entry_json(e) for e in self.entries],
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


def _reaction_rises(
    reactions: list[Any], moles: dict[str, float], t: float, comps: dict[str, Any], data: Any
) -> tuple[dict[str, float] | None, list[str]]:
    """K of each reaction whose heat is known: its heat run to completion of its limiting
    reactant, over the feed's heat capacity (negative: endothermic), and what is lacking.
    None when the heat capacity is not known."""
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
    if capacity <= 0:
        return None, lacking
    rises: dict[str, float] = {}
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
        rises[r.id] = -heat * extent / capacity
    return rises, lacking


def _adiabatic_rise(
    reactions: list[Any],
    moles: dict[str, float],
    t: float,
    comps: dict[str, Any],
    data: Any,
    counted: list[str] | None = None,
) -> tuple[float | None, list[str], dict[str, float]]:
    """K: the largest heat of one reaction (of the *counted*, default every one) run to
    completion, over the feed's heat capacity; what is lacking; each reaction's rise."""
    if counted is not None:
        reactions = [r for r in reactions if r.id in counted]
    rises, lacking = _reaction_rises(reactions, moles, t, comps, data)
    if rises is None:
        return None, lacking, {}
    best = max([0.0, *rises.values()])
    if lacking and best == 0.0:
        return None, lacking, rises
    return best, lacking, rises


def _counted(
    item: Any, entry: HazardEntry, known: list[str], screened: list[str]
) -> list[str] | None:
    """The reactions ``hazard.reactions`` names among *known* (None: every reaction counts),
    recorded on *entry* with the choice when it matters (more than one reaction, or named);
    a named one not among *known* goes to ``entry.unknown_reactions``."""
    hazard = getattr(item, "hazard", None)
    named = list(getattr(hazard, "reactions", None) or [])
    entry.unknown_reactions = [n for n in named if n not in known]
    counted = [n for n in named if n in known] or None
    if counted is not None:
        entry.counted_reactions, entry.counted_basis = counted, "hazard.reactions"
    elif len(screened) > 1:
        entry.counted_reactions = list(screened)
        entry.counted_basis = "every reaction, the largest"
    return counted


def _uncounted(entry: HazardEntry) -> HazardEntry:
    """*entry* without its choice of reactions where it gives no reaction's values."""
    if not entry.per_reaction:
        entry.counted_reactions, entry.counted_basis = [], ""
    return entry


def _declared_heat(reaction: Any) -> float:
    """kJ/kmol: the reaction's declared heat of reaction (0 when none is declared)."""
    return reaction.heat_of_reaction.value if reaction.heat_of_reaction is not None else 0.0


def _phase_changes(process: Any, node: str) -> dict[str, str]:
    """Reaction id -> why it is a phase change, of every reaction of *node* that is one."""
    from chemeascode.domains.chemistry.reactions import phase_change
    from chemeascode.domains.process.solids import solid_components

    reactions, _ = process.reactions_of(node)
    formulas = process.formulas()
    solids = solid_components(process)
    found = {r.id: phase_change(r, formulas, solids) for r in reactions}
    return {k: v for k, v in found.items() if v}


def phase_changes(process: Any, node: str) -> dict[str, str]:
    """Reaction id -> why it is a phase change, of the reactions of *node* not screened as
    reactions: those declared ``kind: phase-change``, and those detected by their formula that
    declare no heat of reaction. A detected one with a heat of reaction stays screened (a
    dissolution of caustic or a dilution of acid can boil a batch): the author never said it
    is no reaction, and its heat counts in dT_ad."""
    reactions, _ = process.reactions_of(node)
    heat = {r.id: _declared_heat(r) for r in reactions}
    return {
        k: why
        for k, why in _phase_changes(process, node).items()
        if why == "declared" or not heat.get(k)
    }


def heated_phase_changes(process: Any, node: str) -> list[str]:
    """The reactions of *node* detected as phase changes by their formula that declare a heat
    of reaction, so are screened as reactions."""
    skipped = phase_changes(process, node)
    return sorted(k for k in _phase_changes(process, node) if k not in skipped)


def screen_node(process: Any, node: str, case: str) -> HazardEntry:
    """The screening of reactor *node* in *case* (see the module docstring); its phase
    changes take no part in dT_ad and the MTT (a semi-batch's MTSR is its model's, phase
    changes included)."""
    from chemeascode.domains.process.model import stream_flows
    from chemeascode.foundation.units import to_kelvin, to_kpa_abs

    fs = process.flowsheet
    item = process.nodes[node]
    model = getattr(item, "reactor", None) or "conversion"
    entry = HazardEntry(node, model)
    reactions, _ = process.reactions_of(node)
    every = [r.id for r in reactions]
    if changes := phase_changes(process, node):
        reactions = [r for r in reactions if r.id not in changes]
        entry.notes.append("phase changes not screened as reactions: " + ", ".join(sorted(changes)))
    if heated := heated_phase_changes(process, node):
        entry.notes.append(
            "phase changes screened for their declared heat of reaction (it counts in dT_ad): "
            + ", ".join(heated)
        )
    # the material inlets (a semi-batch's charge and doses): a heat or power stream into the
    # reactor is no feed, as the tank and reactor models count it (stirred_tank.tank_inlet)
    inlets = [
        s
        for s in fs.streams
        if s.kind == "material" and (e := process.ends(s)[1]) is not None and e.node == node
    ]
    if model == "semibatch":
        # the semi-batch model's potential holds its phase changes too
        counted = _counted(item, entry, every, [r.id for r in reactions])
        return _uncounted(_screen_semibatch(process, item, entry, reactions, inlets, case, counted))
    counted = _counted(item, entry, [r.id for r in reactions], [r.id for r in reactions])
    if len(inlets) != 1:
        entry.missing.append("one inlet stream")
        return _uncounted(entry)
    inlet = inlets[0]
    state = inlet.state.get(case)
    t = getattr(state, "temperature", None)
    p = getattr(state, "pressure", None)
    t_in = to_kelvin(t.value, t.unit or fs.units.temperature) if t is not None else None
    p_in = to_kpa_abs(p.value, p.unit or fs.units.pressure) if p is not None else None
    if t_in is None:
        entry.missing.append(f"the temperature of {inlet.id}")
        return _uncounted(entry)
    flows = stream_flows(process, inlet, case)
    comps = process.components()
    if flows.components is None:
        entry.missing.append(f"the composition and flow of {inlet.id}")
        return _uncounted(entry)
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
        _vent_note(process, item, entry, inlet, case)
    elif model != "cstr":
        entry.notes.append("accumulation 1: the fresh feed, at the inlet's temperature")
    entry.process_temperature = t_p
    entry.accumulation = accumulation
    rise, lacking, rises = _adiabatic_rise(
        reactions, moles, t_p, comps, process.ideal_gas(), counted
    )
    entry.missing += lacking
    entry.adiabatic_rise = rise
    if rise is not None:
        entry.mtsr = t_p + accumulation * rise
    if entry.counted_reactions:
        everyone, _ = _reaction_rises(reactions, moles, t_p, comps, process.ideal_gas())
        # an endothermic reaction alone does not heat the content: its MTSR is T_p, as in
        # the semi-batch's model
        entry.per_reaction = {
            r: {"adiabatic_rise": x, "mtsr": t_p + accumulation * max(x, 0.0)}
            for r, x in (everyone or {}).items()
        }
    _limits(entry, item, reactions, moles, comps, p_in, _left_out(item, []))
    if model == "batch" and _vented(item) and entry.mtsr is not None:
        _gas(process, item, entry, case, moles, entry.mtsr, p_in or 101.325, rises, counted)
    _uncounted(entry)
    bed = getattr(item, "bed", None)
    if model == "pfr" and bed is not None and bed.heat == "cooled" and bed.coolant_temperature:
        entry.sensitivity = _sensitivity(process, item, inlet, case)
    return entry


def _screen_semibatch(
    process: Any,
    item: Any,
    entry: HazardEntry,
    reactions: list[Any],
    inlets: list[Any],
    case: str,
    counted: list[str] | None = None,
) -> HazardEntry:
    """A semi-batch (Stoessel's treatment): ``X_ac`` the largest accumulation of the dosed
    reactant over the run, the MTSR the cooling-failure temperature at the worst moment (the
    dosing stopped, the content then reacting to completion adiabatically, the *counted*
    reactions' largest), ``T_p`` the process temperature then; ``dT_ad`` of the whole batch,
    charge and doses."""
    from chemeascode.domains.process.stirred_tank import TankError, solve_node, stream_moles

    comps = process.components()
    moles: dict[str, float] = {}
    p_in = None
    # a dosed gas counts with the share the liquid takes up; the rest passes to the vent
    absorbed = {d.stream: d.absorbed for d in item.batch.dosing if d.absorbed is not None}
    gases: list[str] = []  # the components of a dosed gas
    try:
        for stream in inlets:
            found, t_in, kpa = stream_moles(process, stream, case)
            share = absorbed.get(stream.id, 1.0)
            for n, v in found.items():
                if v > 0:  # a template's component the stream does not carry is not there
                    moles[n] = moles.get(n, 0.0) + v * share
                    if stream.id in absorbed:
                        gases.append(n)
            p_in = kpa if p_in is None else min(p_in, kpa)
        solved, _ = solve_node(process, item, inlets, case)
    except TankError as failure:
        entry.missing.append(f"the semibatch: {failure}")
        return entry
    points = solved.cooling_profile
    # the worst moment of the counted reactions (all: the model's own cooling failure)
    worst = max(points, key=lambda q: q.mtsr(counted)) if points else None
    entry.process_temperature = worst.temperature if worst else solved.profile[0][1]
    rise, lacking, _ = _adiabatic_rise(
        reactions, moles, entry.process_temperature, comps, process.ideal_gas(), counted
    )
    entry.missing += lacking
    entry.adiabatic_rise = rise
    entry.accumulation = solved.max_accumulation
    if worst is not None:
        entry.mtsr = worst.mtsr(counted)
        entry.notes.append(
            f"accumulation: the dosed reactant's largest, {solved.max_accumulation or 0:.3g} at "
            f"{solved.max_accumulation_time or 0:.6g} s; MTSR at the worst moment, "
            f"{worst.time:.6g} s (dosing stopped, the content's heat capacity then"
            + (f"; of {', '.join(counted)}, hazard.reactions" if counted else "")
            + ")"
        )
        entry.mtsr_profile = _profile(points, counted)
    elif rise is not None and solved.max_accumulation is not None:
        entry.mtsr = entry.process_temperature + solved.max_accumulation * rise
        entry.notes.append("MTSR: T_p + X_ac dT_ad (no cooling-failure temperature over the run)")
    else:
        entry.missing.append("the accumulation of a dosed reactant")
    if entry.counted_reactions:
        everyone, _ = _reaction_rises(
            reactions, moles, entry.process_temperature, comps, process.ideal_gas()
        )
        entry.per_reaction = _per_reaction(everyone or {}, points)
    if changes := phase_changes(process, item.id):
        entry.notes.append(
            "the MTSR from the semibatch model includes the kinetics and heat of its phase "
            "changes (" + ", ".join(sorted(changes)) + "); dT_ad and the MTT its reactions' alone"
        )
    if item.batch.vent is not None:
        _vent_note(process, item, entry, inlets, case, solved)
    # what boils in the liquid sets the MTT: the charge and the absorbed share of each dose,
    # but no vent component, dosed gas or dissolved gas (ADR 0058)
    _limits(entry, item, reactions, moles, comps, p_in, _left_out(item, gases))
    if _vented(item) and worst is not None and entry.mtsr is not None:
        _gas(
            process,
            item,
            entry,
            case,
            worst.moles,
            entry.mtsr,
            solved.pressure,
            worst.rises,
            counted,
        )
    return entry


def _profile(points: list[Any], counted: list[str] | None) -> list[dict[str, float | None]]:
    """The MTSR at the model's steps nearest PROFILE_POINTS moments evenly over the run, each
    step once, and the worst moment: values at a step, never interpolated."""
    end = points[-1].time
    picked = {
        min(
            range(len(points)),
            key=lambda k, m=end * i / (PROFILE_POINTS - 1): abs(points[k].time - m),
        )
        for i in range(PROFILE_POINTS)
    }
    picked.add(max(range(len(points)), key=lambda k: points[k].mtsr(counted)))
    return [
        {
            "time_s": points[k].time,
            "accumulation": points[k].accumulation,
            "temperature_K": points[k].temperature,
            "mtsr_K": points[k].mtsr(counted),
        }
        for k in sorted(picked)
    ]


def _per_reaction(rises: dict[str, float], points: list[Any]) -> dict[str, dict[str, Any]]:
    """Reaction id -> its dT_ad over the whole batch and the MTSR at its own worst moment."""
    found: dict[str, dict[str, Any]] = {r: {"adiabatic_rise": x} for r, x in rises.items()}
    heated = [r for r in (points[0].rises if points else {}) if any(q.rises[r] > 0 for q in points)]
    names = list(dict.fromkeys([*rises, *heated]))
    for r in names:
        if not points:
            continue
        worst = max(points, key=lambda q, r=r: q.mtsr([r]))
        found.setdefault(r, {"adiabatic_rise": None})
        found[r] |= {"mtsr": worst.mtsr([r]), "time_s": worst.time}
    return found


def _vented(item: Any) -> bool:
    batch = getattr(item, "batch", None)
    return batch is not None and batch.vent is not None


def _extent(reaction: Any, moles: dict[str, float]) -> float:
    """kmol: the extent of *reaction* run to completion of its limiting reactant in *moles*."""
    return min(
        (max(moles.get(n, 0.0), 0.0) / -nu for n, nu in reaction.stoichiometry.items() if nu < 0),
        default=0.0,
    )


def _vent_gas(reaction: Any, shares: dict[str, float]) -> float:
    """kmol of vent gas per kmol of extent of *reaction*: the share of each vent component."""
    return sum(f * max(reaction.stoichiometry.get(g, 0.0), 0.0) for g, f in shares.items())


def _formed(
    reactions: list[Any], moles: dict[str, float], shares: dict[str, float]
) -> dict[str, float]:
    """Reaction id -> kmol (the batch's basis) of vent gas it forms run to completion of
    *moles* alone: its limiting reactant times the share of each vent component it forms."""
    found = {}
    for r in reactions:
        if (gas := _vent_gas(r, shares)) > 0:
            found[r.id] = _extent(r, moles) * gas
    return found


def _after(reaction: Any, moles: dict[str, float], shares: dict[str, float]) -> dict[str, float]:
    """The content once *reaction* ran to completion of its limiting reactant in *moles*: the
    vented share of a vent component it forms has left."""
    extent = _extent(reaction, moles)
    after = dict(moles)
    for n, nu in reaction.stoichiometry.items():
        kept = nu if nu < 0 else nu * (1.0 - shares.get(n, 0.0))
        after[n] = max(after.get(n, 0.0) + kept * extent, 0.0)
    return after


def _gas(
    process: Any,
    item: Any,
    entry: HazardEntry,
    case: str,
    moles: dict[str, float],
    temperature: float,
    pressure: float,
    rises: dict[str, float] | None = None,
    counted: list[str] | None = None,
) -> None:
    """``entry.gas_release`` (see the module docstring): the vent gas forming at the MTSR, the
    larger of two contents, *moles* (the worst moment's) and what is in the vessel once the
    reaction setting the MTSR (the largest of *rises*, of the *counted*) ran to completion, so
    that gas formed from its products counts; and the most one reaction forms run to completion,
    of the counted ones from *moles*, or of a reaction consuming a product of the one setting
    the MTSR from the content after it."""
    from chemeascode.domains.chemistry.thermochemistry import R
    from chemeascode.domains.process.recipe import hours_per_batch
    from chemeascode.domains.process.stirred_tank import TankError, vent_gas_rate

    every, _ = process.reactions_of(item.id)
    by_id = {r.id: r for r in every}
    shares = item.batch.vent.shares()
    picked = {r: x for r, x in (rises or {}).items() if counted is None or r in counted}
    setter = max(picked, key=lambda r: picked[r]) if picked else None
    if setter is not None and (picked[setter] <= 0 or setter not in by_id):
        setter = None
    after = _after(by_id[setter], moles, shares) if setter else None
    try:
        rate = vent_gas_rate(process, item, moles, temperature, pressure)
        rate_after = vent_gas_rate(process, item, after, temperature, pressure) if after else 0.0
    except TankError as failure:
        entry.missing.append(f"the gas release at the MTSR: {failure}")
        return
    try:
        hours = hours_per_batch(process, case)
    except ValueError:
        hours = None
    # from the worst moment's content: the counted reactions (hazard.reactions, else all)
    formed = _formed([r for r in every if counted is None or r.id in counted], moles, shares)
    source = dict.fromkeys(formed, "the worst moment's content")
    if setter and after is not None:
        products = {n for n, nu in by_id[setter].stoichiometry.items() if nu > 0}
        chain = [
            r
            for r in every
            if r.id != setter and any(nu < 0 and n in products for n, nu in r.stoichiometry.items())
        ]
        for r, kmol in _formed(chain, after, shares).items():
            if kmol > formed.get(r, 0.0):
                formed[r], source[r] = kmol, f"the content after {setter}"
    largest = max(formed, key=lambda r: formed[r]) if formed else None
    scale = hours or 1.0
    volume = R * temperature / pressure  # m3/kmol
    top = max(rate, rate_after)
    gas: dict[str, Any] = {
        "rate_kmol_s": top * scale,
        "rate_m3_h": top * scale * volume * 3600.0,
        "rate_from": (
            f"the content after {setter}"
            if setter and rate_after > rate
            else "the worst moment's content"
        ),
        "temperature_K": temperature,
        "pressure_kPa": pressure,
        "formed_by": largest,
        "formed_kmol": formed.get(largest or "", 0.0) * scale,
        "formed_m3": formed.get(largest or "", 0.0) * scale * volume,
        "formed_from": source.get(largest or ""),
        "basis": (
            f"per batch ({hours:.6g} h of the flowsheet's flows, process/recipe.yaml)"
            if hours
            else "per hour of the flowsheet's flows (no process/recipe.yaml batch size)"
        ),
        "per_batch": bool(hours),
    }
    capacity = getattr(getattr(item, "hazard", None), "vent_capacity", None)
    if capacity:
        gas["vent_capacity_m3_h"] = capacity
        if hours:
            gas["capacity_ratio"] = gas["rate_m3_h"] / capacity
    entry.gas_release = gas


def _vent_note(
    process: Any, item: Any, entry: HazardEntry, inlet: Any, case: str, solved: Any = None
) -> None:
    """The notes of a vented batch or semi-batch (ADR 0054): its gas leaves as it forms, adds
    nothing to the MTSR; its peak rate over the run."""
    vent = getattr(item.batch, "vent", None) if item.batch is not None else None
    if vent is None:
        return
    if solved is None:
        from chemeascode.domains.process.stirred_tank import TankError, solve_node

        try:
            solved, _ = solve_node(process, item, inlet, case)
        except TankError as failure:
            entry.missing.append(f"the vented batch: {failure}")
            return
    rate = solved.peak_vent_rate
    entry.notes.append(
        f"vent {vent.stream}: {', '.join(vent.components)} leave(s) as formed, no part of the "
        "heat capacity or the MTSR"
        + (
            f"; peak gas rate {rate:.4g} kmol/(s m3) at {solved.peak_vent_time:.6g} s"
            if rate
            else ""
        )
        + " (the gas release at a cooling failure: gas_release, cheme.reactor-hazard-vent)"
    )


def _left_out(item: Any, gases: list[str]) -> dict[str, str]:
    """Component -> why the default MTT leaves it out: a batch's vent components and the
    components of a dosed gas (*gases*)."""
    found = dict.fromkeys(gases, "dosed gas")
    if _vented(item):
        found |= dict.fromkeys(item.batch.vent.components, "vent component")
    return found


def boiling_point(normal: float, heat_of_vaporization: float, pressure: float) -> float:
    """K at *pressure* kPa(a) from the normal boiling point *normal* K and the heat of
    vaporization kJ/kmol: Clausius-Clapeyron, ``1/T = 1/T_b - R ln(P/101.325)/dH_vap``."""
    from math import log

    from chemeascode.domains.chemistry.thermochemistry import R

    return 1.0 / (1.0 / normal - R * log(pressure / 101.325) / heat_of_vaporization)


def _limits(
    entry: HazardEntry,
    item: Any,
    reactions: list[Any],
    moles: dict[str, float],
    comps: dict[str, Any],
    p_in: float | None,
    left_out: dict[str, str] | None = None,
) -> None:
    """The MTT and TD24 of *entry*, and its class once the MTSR is known."""
    hazard = getattr(item, "hazard", None)
    if hazard is not None and hazard.mtt:
        entry.mtt, entry.mtt_basis = hazard.mtt, "hazard.mtt"
    elif any(r.phase == "liquid" for r in reactions):
        _default_mtt(entry, moles, comps, p_in, left_out or {})
    else:
        entry.missing.append("the MTT (hazard.mtt)")
    if hazard is not None and hazard.td24:
        entry.td24 = hazard.td24
    else:
        entry.missing.append("TD24 of the decomposition (hazard.td24, from calorimetry)")
    if entry.mtsr is not None and entry.mtt is not None and entry.td24 is not None:
        entry.criticality = criticality(entry.mtsr, entry.mtt, entry.td24)


def _default_mtt(
    entry: HazardEntry,
    moles: dict[str, float],
    comps: dict[str, Any],
    p_in: float | None,
    left_out: dict[str, str],
) -> None:
    """The lowest boiling point at the vessel's pressure of what boils in the liquid (see the
    module docstring)."""
    pressure = p_in if p_in is not None else 101.325
    above = pressure > ATMOSPHERIC
    atmospheric = BELOW_ATMOSPHERIC <= pressure <= ATMOSPHERIC
    t_p = entry.process_temperature
    boiling: dict[str, tuple[float, str]] = {}
    unknown: list[str] = []  # no heat_of_vaporization: the normal boiling point stands in
    out: dict[str, str] = {}
    total = sum(v for v in moles.values() if v > 0)
    for n in moles:
        comp = comps.get(n)
        normal = getattr(comp, "normal_boiling_point", None)
        if not normal:
            continue
        if n in left_out:
            out[n] = left_out[n]
            continue
        heat = getattr(comp, "heat_of_vaporization", None)
        if atmospheric:
            found = (normal, f"normal boiling point of {n}")
        elif heat:
            found = (
                boiling_point(normal, heat, pressure),
                f"boiling point of {n} at {pressure:.4g} kPa(a), Clausius-Clapeyron with its "
                "heat_of_vaporization",
            )
        else:
            unknown.append(n)
            found = (normal, f"normal boiling point of {n}")
        share = moles[n] / total if total > 0 else 0.0
        if (
            t_p is not None
            and found[0] < t_p
            and share < DISSOLVED
            and not (above and n in unknown)
        ):
            out[n] = (
                f"dissolved gas ({share:.2%} of the liquid, boils at {found[0]:.1f} K, below "
                f"T_p {t_p:.1f} K)"
            )
            continue
        boiling[n] = found
    entry.mtt_left_out = out
    if out:
        entry.notes.append(
            "MTT: left out "
            + ", ".join(f"{n} ({why})" for n, why in out.items())
            + ": they leave or boil off rather than boil the batch"
        )
    if not boiling:
        if out:
            entry.missing.append(
                "the MTT (hazard.mtt): nothing else boils in the liquid than vent "
                "components, dosed or dissolved gases"
            )
        else:
            entry.missing.append(
                "the MTT (hazard.mtt)" if above else "the MTT (hazard.mtt, or normal_boiling_point)"
            )
        return
    mtt, basis = min(boiling.values())
    # above atmospheric a component without heat_of_vaporization boils above its normal
    # boiling point: it cannot set the MTT if that is at or above the lowest known boiling
    # point; every one below it could (each needs its heat_of_vaporization)
    known = [v for n, v in boiling.items() if n not in unknown]
    lowest = min(known)[0] if known else None
    open_ = [n for n in unknown if lowest is None or boiling[n][0] < lowest] if above else []
    if above and (open_ or not known):
        lacking = open_ or unknown
        entry.missing.append("the MTT (hazard.mtt)")
        entry.notes.append(
            f"the MTT at {pressure:.4g} kPa(a) needs heat_of_vaporization of "
            + ", ".join(lacking)
            + " (Clausius-Clapeyron from the normal boiling point)"
        )
        return
    if above:
        mtt, basis = min(known)
    elif unknown and not atmospheric:
        entry.notes.append(
            f"at {pressure:.4g} kPa(a) " + ", ".join(unknown) + " boil(s) below the normal "
            "boiling point taken (no heat_of_vaporization): the MTT is lower"
        )
    if t_p is not None and mtt < t_p:
        entry.notes.append(
            f"MTT {mtt:.1f} K ({basis}) below T_p {t_p:.1f} K: the liquor is at its boiling "
            "point (at reflux); a cooling failure boils it at once"
        )
    entry.mtt, entry.mtt_basis = mtt, basis


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
    heats: dict[str, dict[str, float]] = {}
    for n in [*fs.blocks, *fs.steps]:
        if not (process.reactive(n.id) and (n.reactions or getattr(n, "reactor", None))):
            continue
        reactions, _ = process.reactions_of(n.id)
        changes = phase_changes(process, n.id)
        if reactions and len(changes) == len(reactions):
            skipped.append(PhaseChangeStep(n.id, dict(sorted(changes.items()))))
            heats[n.id] = {r.id: h for r in reactions if (h := _declared_heat(r))}
        else:
            entries.append(screen_node(process, n.id, case))
    findings: list[Finding] = []
    for p in skipped:
        heat = heats.get(p.node) or {}
        reason = (
            "declared kind: phase-change, their declared heat ("
            + ", ".join(f"{r} {h:g} kJ/kmol" for r, h in sorted(heat.items()))
            + ") is not screened as a reaction"
            if heat
            else "no reaction heat declared to run away"
        )
        findings.append(
            Finding(
                FLOWSHEET,
                "info",
                "cheme.reactor-hazard-phase-change",
                f"{p.node}: not screened: its reactions are phase changes ("
                + ", ".join(f"{r}: {why}" for r, why in p.reactions.items())
                + f"), {reason}",
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
        if e.unknown_reactions:
            add(
                "warning",
                "reactions",
                f"{e.node}: hazard.reactions names "
                + ", ".join(e.unknown_reactions)
                + ", not a reaction screened here"
                + (
                    f" (counted: {', '.join(e.counted_reactions)})"
                    if e.counted_basis == "hazard.reactions"
                    else " (every reaction counts)"
                ),
                "name reactions of the step's reactions: (a phase change is not screened)",
            )
        if (gas := e.gas_release) is not None:
            release = (
                f"{e.node}: gas release at the MTSR {gas['rate_kmol_s']:.4g} kmol/s, "
                f"{gas['rate_m3_h']:.4g} m3/h at {gas['temperature_K']:.1f} K and "
                f"{gas['pressure_kPa']:.4g} kPa(a), {gas['basis']}"
            )
            capacity = gas.get("vent_capacity_m3_h")
            if capacity is None:
                add(
                    "warning",
                    "vent",
                    release + ": no vent capacity stated",
                    "give hazard.vent_capacity (m3/h the vent and its line pass at the "
                    "vessel's pressure, from the vent sizing); with the vent blocked the gas "
                    "pressurises the vessel",
                )
            elif not gas["per_batch"]:
                add(
                    "warning",
                    "vent",
                    release + f": not compared with the vent capacity {capacity:.4g} m3/h",
                    "give process/recipe.yaml a batch_size: the rate per batch needs it",
                )
            else:
                ratio = gas["capacity_ratio"]
                add(
                    "warning" if ratio > 1 else "info",
                    "vent",
                    release
                    + f", {ratio:.3g} times the vent capacity {capacity:.4g} m3/h "
                    + ("(above it)" if ratio > 1 else "(within it)"),
                    "a gas release above the vent's capacity pressurises the vessel: limit "
                    "the accumulation, or size the vent and relief for it"
                    if ratio > 1
                    else "screening values: the rate is the larger of the worst moment's "
                    "content and the content after the reaction setting the MTSR, at the MTSR; "
                    "gas from a longer chain of consecutive reactions is not covered",
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
        if e.per_reaction:
            lines.append(
                f"  reactions ({e.counted_basis}: {', '.join(e.counted_reactions)}): "
                + "; ".join(
                    f"{r} dT_ad {num(v.get('adiabatic_rise'), 'K')}"
                    + (" (endothermic)" if (v.get("adiabatic_rise") or 0.0) < 0 else "")
                    + f", MTSR {num(v.get('mtsr'), 'K')}"
                    for r, v in e.per_reaction.items()
                )
            )
        if e.mtsr_profile:
            profile = e.mtsr_profile
            step = max((len(profile) - 1) / (TEXT_POINTS - 1), 1.0)
            picked = [profile[round(i * step)] for i in range(min(TEXT_POINTS, len(profile)))]
            worst = max(profile, key=lambda q: q["mtsr_K"] or 0.0)
            if worst not in picked:
                picked = sorted([*picked, worst], key=lambda q: q["time_s"] or 0.0)
            lines.append(
                "  MTSR over the batch (h: X_ac, MTSR K): "
                + "; ".join(
                    f"{q['time_s'] / 3600:.3g}: "
                    + ("?" if q["accumulation"] is None else f"{q['accumulation']:.3g}")
                    + f", {q['mtsr_K']:.1f}"
                    for q in picked
                )
            )
        if (gas := e.gas_release) is not None:
            lines.append(
                f"  gas release at the MTSR: {gas['rate_kmol_s']:.4g} kmol/s, "
                f"{gas['rate_m3_h']:.4g} m3/h at {gas['temperature_K']:.1f} K and "
                f"{gas['pressure_kPa']:.4g} kPa(a) ({gas['basis']}; {gas['rate_from']}); "
                f"{gas['formed_kmol']:.4g} kmol ({gas['formed_m3']:.4g} m3) formed by "
                f"{gas['formed_by'] or 'no reaction'} run to completion"
                + (f" ({gas['formed_from']})" if gas.get("formed_from") else "")
                + (
                    f"; vent capacity {gas['vent_capacity_m3_h']:.4g} m3/h"
                    if "vent_capacity_m3_h" in gas
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
