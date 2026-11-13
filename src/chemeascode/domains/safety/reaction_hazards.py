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
- a semi-batch's doses with ``heat_of_solution`` (ADR 0063): their heat over the batch's heat
  capacity counts in ``dT_ad`` (``heat_of_solution``), not in the MTSR: it is released as each
  dose mixes in, so a cooling failure that stops the dosing finds none of it accumulated;
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
- ADR 0069 (:mod:`.reaction_network`): the counted reactions as a network, their largest heat
  together from the content (a consecutive reaction on a product counts), reported for a batch
  or semi-batch with a consecutive pair and setting dT_ad and the MTSR with ``hazard.potential:
  network``; a semi-batch's accumulation of each dosed reactant and the share of it that can
  still react (a deliberate excess cannot); a vented semi-batch's largest gas release over the
  batch (every step's content at its MTSR, with the liquid's vapour), compared with the vent
  capacity where larger than the release at the MTSR; a content boiling at the MTSR, its
  boil-up at its bubble point (the reactions' heat there over the vapour's latent heat); the
  dosed, dissolved and vented gases held in the liquid a cooling failure can release, at their
  largest over the batch, with what the gas release strips of them; the products a counted
  reaction forms in the liquid as candidates for the default MTT, and with ``hazard.mtt_from:
  bubble-point`` the MTT from the content's bubble point (Raoult's law);
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
step), ``-vent`` (a vented batch's gas release at the MTSR, or a semi-batch's largest over
the batch: a warning without ``hazard.vent_capacity`` or above it, info within it),
``-dissolved`` (info: the gases held in the liquid a cooling failure can release, ADR 0069),
``-initiation`` (a semi-batch with ``batch.initiation``, ADR 0074: the uninitiated scenario,
the dosing going on into a charge that never initiates, its doses that wait for the initiation
left out; a warning where its MTSR is above the MTT or the TD24, info otherwise). With
the vent blocked the gas
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
    #: a semi-batch whose doses give heat_of_solution (ADR 0063): the heat they release as they
    #: mix in (kJ per hour of flows, the batch's basis) and its adiabatic rise, in dT_ad and not
    #: in the MTSR (released on mixing, not accumulated)
    heat_of_solution: dict[str, Any] | None = None
    #: ADR 0069, in the JSON only when given: the counted reactions as a network (their
    #: largest heat together, :mod:`.reaction_network`), with hazard.potential: network or a
    #: consecutive reaction among them; each dosed reactant's accumulation and what of it can
    #: still react (a semi-batch with more than one dosed reactant, or an excess); the
    #: content's bubble point (hazard.mtt_from: bubble-point); the dissolved and dosed gases a
    #: cooling failure can boil off or strip
    network: dict[str, Any] | None = None
    accumulations: dict[str, dict[str, float]] = field(default_factory=dict)
    bubble_point: dict[str, Any] | None = None
    dissolved_release: dict[str, Any] | None = None
    #: ADR 0074, a semi-batch with batch.initiation: the uninitiated scenario (the dosing going
    #: on into a charge that never initiates, the doses that wait for it left out): until when,
    #: its largest accumulation and the MTSR at its worst moment (the model's reactions)
    initiation: dict[str, Any] | None = None


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
    "heat_of_solution",
    "network",
    "accumulations",
    "bubble_point",
    "dissolved_release",
    "initiation",
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


def _heats(
    reactions: list[Any], moles: dict[str, float], t: float, comps: dict[str, Any], data: Any
) -> tuple[float | None, dict[str, float], list[str]]:
    """The feed's heat capacity kJ/K (None when not known), each reaction's heat of reaction
    kJ/kmol whose heat is known (``heat_of_reaction``, else a gas's ideal-gas data) and what
    is lacking."""
    from chemeascode.domains.chemistry.thermochemistry import missing, reaction_enthalpy

    lacking: list[str] = []
    liquid = any(r.phase == "liquid" for r in reactions)
    present = {n: v for n, v in moles.items() if v > 0}
    if liquid:
        no_cp = sorted(n for n in present if not getattr(comps.get(n), "liquid_heat_capacity", 0))
        if no_cp:
            return None, {}, ["liquid_heat_capacity of " + ", ".join(no_cp)]
        capacity = sum(v * comps[n].liquid_heat_capacity for n, v in present.items())
    else:
        if lack := missing(list(present), data):
            return None, {}, ["ideal_gas data of " + ", ".join(lack)]
        capacity = sum(v * data[n].cp(t) for n, v in present.items())
    if capacity <= 0:
        return None, {}, lacking
    heats: dict[str, float] = {}
    for r in reactions:
        if r.heat_of_reaction is not None:
            heats[r.id] = r.heat_of_reaction.value
        elif not liquid and not missing(list(r.stoichiometry), data):
            heats[r.id] = reaction_enthalpy(r.stoichiometry, data, t)
        else:
            lacking.append(f"heat_of_reaction of {r.id}")
    return capacity, heats, lacking


def _reaction_rises(
    reactions: list[Any], moles: dict[str, float], t: float, comps: dict[str, Any], data: Any
) -> tuple[dict[str, float] | None, list[str]]:
    """K of each reaction whose heat is known: its heat run to completion of its limiting
    reactant, over the feed's heat capacity (negative: endothermic), and what is lacking.
    None when the heat capacity is not known."""
    capacity, heats, lacking = _heats(reactions, moles, t, comps, data)
    if capacity is None:
        return None, lacking
    rises: dict[str, float] = {}
    for r in reactions:
        if r.id not in heats:
            continue
        extent = min(
            (moles.get(n, 0.0) / -nu for n, nu in r.stoichiometry.items() if nu < 0),
            default=0.0,
        )
        rises[r.id] = -heats[r.id] * extent / capacity
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
    from chemeascode.domains.process.stirred_tank import pad_stream

    # a batch's head space's pad is no feed of the liquid (ADR 0071)
    inlets = [s for s in inlets if s.id != pad_stream(item)]
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
    batch = getattr(item, "batch", None) if model == "batch" else None
    if batch is not None and (batch.program is not None or batch.heat == "reflux"):
        # ADR 0074: the batch's temperature moves; X_ac = 1 holds at the start only
        entry.notes.append(
            "the batch's temperature follows "
            + ("its programme" if batch.program is not None else "its bubble point (reflux)")
            + ": T_p is the charge's, the MTSR that of a cooling failure at the start; the "
            "process reactors profile gives the temperature over the batch"
        )
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
    shares = item.batch.vent.shares() if _vented(item) else {}
    counted_rx = [r for r in reactions if counted is None or r.id in counted]
    extents = _batch_network(entry, item, counted_rx, moles, t_p, accumulation, comps, process)
    if entry.counted_reactions:
        everyone, _ = _reaction_rises(reactions, moles, t_p, comps, process.ideal_gas())
        # an endothermic reaction alone does not heat the content: its MTSR is T_p, as in
        # the semi-batch's model
        entry.per_reaction = {
            r: {"adiabatic_rise": x, "mtsr": t_p + accumulation * max(x, 0.0)}
            for r, x in (everyone or {}).items()
        }
    label, end = _end_state(counted_rx, moles, rises, shares, extents)
    _limits(
        entry,
        item,
        reactions,
        moles,
        comps,
        p_in,
        _left_out(item, []),
        _products(counted_rx, moles, shares, extents),
        [
            ("the charge" if model == "batch" else "the feed", moles),
            *([(label, end)] if end else []),
        ],
    )
    stripped: dict[str, float] = {}
    if model == "batch" and _releases(item) and entry.mtsr is not None:
        stripped = _gas(
            process,
            item,
            entry,
            case,
            moles,
            entry.mtsr,
            p_in or 101.325,
            rises,
            counted,
            after_network=end if extents else None,
        )
    if model == "batch" and entry.mtsr is not None:
        _dissolved_release(
            process,
            item,
            entry,
            case,
            moles,
            [(0.0, moles, entry.mtsr)],
            p_in or 101.325,
            _left_out(item, []),
            stripped,
        )
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
    solutions = {d.stream: d.heat_of_solution for d in item.batch.dosing if d.heat_of_solution}
    gases: list[str] = []  # the components of a dosed gas
    mixing = 0.0  # kJ the doses release as they mix in (ADR 0063)
    # a vent's inerts never dissolve, a head space's pad is no liquid (ADR 0071)
    vent = item.batch.vent
    inerts = set(vent.inerts) if vent is not None else set()
    pad = vent.head_space.stream if vent is not None and vent.head_space is not None else None
    try:
        for stream in inlets:
            if stream.id == pad:
                continue
            found, t_in, kpa = stream_moles(process, stream, case)
            share = absorbed.get(stream.id, 1.0)
            for n, v in found.items():
                if v > 0 and n not in inerts:  # a template's component it does not carry is not
                    moles[n] = moles.get(n, 0.0) + v * share
                    if stream.id in absorbed:
                        gases.append(n)
            if (heat := solutions.get(stream.id)) is not None:
                mixing -= sum(found.get(n, 0.0) * share * h for n, h in heat.values.items())
            p_in = kpa if p_in is None else min(p_in, kpa)
        solved, _ = solve_node(process, item, inlets, case)
    except TankError as failure:
        entry.missing.append(f"the semibatch: {failure}")
        return entry
    points = solved.cooling_profile
    _initiation(entry, solved)
    every_rx, _ = process.reactions_of(item.id)
    shares = item.batch.vent.shares() if _vented(item) else {}
    # the model's reactions counted (phase changes too, as the model's cooling failure), and
    # the screened ones (the network's consecutive pairs, the products, dT_ad)
    model_rx = [r for r in every_rx if counted is None or r.id in counted]
    counted_rx = [r for r in reactions if counted is None or r.id in counted]
    values, network = _semibatch_network(entry, item, points, model_rx, counted_rx, shares, counted)
    # the worst moment of the counted reactions (all: the model's own cooling failure)
    worst_k = max(range(len(points)), key=lambda k: values[k]) if points else None
    worst = points[worst_k] if worst_k is not None else None
    entry.process_temperature = worst.temperature if worst else solved.profile[0][1]
    rise, lacking, _ = _adiabatic_rise(
        reactions, moles, entry.process_temperature, comps, process.ideal_gas(), counted
    )
    entry.missing += lacking
    entry.adiabatic_rise = rise
    extents = None
    if entry.network is not None:
        extents = _semibatch_network_rise(entry, counted_rx, moles, comps, process, shares, network)
    if solutions:
        _solution_rise(entry, moles, comps, mixing)
    entry.accumulation = solved.max_accumulation
    if worst is not None and worst_k is not None:
        entry.mtsr = values[worst_k]
        entry.notes.append(
            f"accumulation: the dosed reactant's largest, {solved.max_accumulation or 0:.3g} at "
            f"{solved.max_accumulation_time or 0:.6g} s; MTSR at the worst moment, "
            f"{worst.time:.6g} s (dosing stopped, the content's heat capacity then"
            + (f"; of {', '.join(counted)}, hazard.reactions" if counted else "")
            + ("; the counted reactions as a network, hazard.potential" if network else "")
            + ")"
        )
        entry.mtsr_profile = _profile(points, values)
        _accumulations(entry, solved, points, reactions, shares)
    elif rise is not None and solved.max_accumulation is not None:
        entry.mtsr = entry.process_temperature + solved.max_accumulation * rise
        entry.notes.append("MTSR: T_p + X_ac dT_ad (no cooling-failure temperature over the run)")
    else:
        entry.missing.append("the accumulation of a dosed reactant")
    if entry.network is not None and not network:
        _network_note(entry, entry.network["mtsr_K"])
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
    # the content once the cooling failure ran its course from the worst moment
    label, end = ("", None)
    if worst is not None:
        net_end = _network_end(model_rx, worst, shares) if network else None
        label, end = _end_state(model_rx, worst.moles, worst.rises, shares, net_end)
    # what boils in the liquid sets the MTT: the charge and the absorbed share of each dose,
    # but no vent component, dosed gas or dissolved gas (ADR 0058); the products a counted
    # reaction forms (ADR 0069)
    left_out = _left_out(item, gases)
    _limits(
        entry,
        item,
        reactions,
        moles,
        comps,
        p_in,
        left_out,
        _products(counted_rx, moles, shares, extents),
        [
            *([("the worst moment's content", worst.moles)] if worst is not None else []),
            *([(label, end)] if end else []),
        ],
    )
    stripped: dict[str, float] = {}
    if _releases(item) and worst is not None and entry.mtsr is not None:
        stripped = _gas(
            process,
            item,
            entry,
            case,
            worst.moles,
            entry.mtsr,
            solved.pressure,
            worst.rises,
            counted,
            after_network=end if network else None,
            points=points,
            values=values,
        )
    if points:
        _dissolved_release(
            process,
            item,
            entry,
            case,
            moles,
            [(q.time, q.moles, v) for q, v in zip(points, values, strict=True)],
            solved.pressure,
            left_out,
            stripped,
        )
    return entry


def _initiation(entry: HazardEntry, solved: Any) -> None:
    """A semi-batch's uninitiated scenario (ADR 0074, :func:`.stirred_tank._uninitiated`) into
    *entry*: the dosing going on into a charge that never initiates, its largest accumulation
    and the cooling-failure temperature at its worst moment (every reaction of the model, run
    to completion of what accumulated)."""
    start = solved.initiation
    scenario = start.get("uninitiated") if start else None
    if scenario is None:
        return
    worst = scenario.get("cooling_failure")
    entry.initiation = {
        "time_s": start["time_s"],
        "doses_waiting": start["doses_waiting"],
        "until_s": scenario["until_s"],
        "max_accumulation": scenario.get("max_accumulation"),
        "worst_time_s": worst["time_s"] if worst else None,
        "mtsr_K": worst["mtsr_K"] if worst else None,
    }
    if scenario.get("missing"):
        entry.missing.append(f"the uninitiated scenario: {scenario['missing']}")


def _point_network(q: Any, reactions: list[Any], shares: dict[str, float]) -> float | None:
    """K: the cooling-failure temperature at the step *q* of the counted *reactions* as a
    network (their largest heat together from its content over its heat capacity), None
    without its heat capacity or with an unbounded network."""
    from chemeascode.domains.safety.reaction_network import network_heat

    if not q.capacity:
        return None
    heats = {r.id: q.heats[r.id] for r in reactions if r.id in q.heats}
    solved = network_heat(reactions, q.moles, heats, shares)
    if solved is None:
        return None
    return q.temperature + max(solved[0], 0.0) / q.capacity


def _network_end(reactions: list[Any], q: Any, shares: dict[str, float]) -> dict[str, float] | None:
    """The network's extents from the step *q*'s content."""
    from chemeascode.domains.safety.reaction_network import network_heat

    heats = {r.id: q.heats[r.id] for r in reactions if r.id in q.heats}
    solved = network_heat(reactions, q.moles, heats, shares)
    return solved[1] if solved is not None else None


def _semibatch_network(
    entry: HazardEntry,
    item: Any,
    points: list[Any],
    model_rx: list[Any],
    counted_rx: list[Any],
    shares: dict[str, float],
    counted: list[str] | None,
) -> tuple[list[float], bool]:
    """The cooling-failure temperature at each step (the counted reactions' largest, or with
    hazard.potential: network the network's), and whether the network counts. With a
    consecutive pair among the counted reactions, or hazard.potential: network,
    ``entry.network`` gives the network's worst moment (ADR 0069)."""
    largest = [q.mtsr(counted) for q in points]
    potential = _potential(item)
    pairs = _pairs(counted_rx)
    if not points or (not pairs and potential != "network"):
        return largest, False
    net = [_point_network(q, model_rx, shares) for q in points]
    if any(v is None for v in net):
        if potential == "network":
            entry.missing.append(
                "the network's potential (hazard.potential: network): the content's heat "
                "capacity at every step, and a bounded heat"
            )
        return largest, False
    values = [float(v) for v in net if v is not None]
    k = max(range(len(points)), key=lambda i: values[i])
    use = potential == "network"
    entry.network = {
        "mtsr_K": values[k],
        "time_s": points[k].time,
        "consecutive": pairs,
        "in_mtsr": use,
    }
    return (values, True) if use else (largest, False)


NETWORK_LACKING = (
    "the network's potential (hazard.potential: network): the heat_of_reaction of every "
    "counted reaction (the known ones release no heat together)"
)


def _semibatch_network_rise(
    entry: HazardEntry,
    counted_rx: list[Any],
    moles: dict[str, float],
    comps: dict[str, Any],
    process: Any,
    shares: dict[str, float],
    use: bool,
) -> dict[str, float] | None:
    """dT_ad of the whole batch (charge and doses) as the counted reactions' network
    (``entry.network``'s; with hazard.potential: network, *use*, the entry's too, and the
    network's extents are returned)."""
    from chemeascode.domains.safety.reaction_network import network_heat

    t = entry.process_temperature or 298.15
    capacity, heats, lacking = _heats(counted_rx, moles, t, comps, process.ideal_gas())
    solved = network_heat(counted_rx, moles, heats, shares) if capacity else None
    if solved is None or not capacity:
        return None
    if lacking and solved[0] <= 0.0:
        # no known heat, or only endothermic ones: what is lacking may be exothermic, so the
        # network's dT_ad is not known (as _adiabatic_rise's)
        if use:
            entry.missing.append(NETWORK_LACKING)
        return None
    rise = max(solved[0], 0.0) / capacity
    if entry.network is not None:
        entry.network = {"adiabatic_rise_K": rise, **entry.network}
    if not use:
        return None
    entry.adiabatic_rise = rise
    return solved[1]


def _accumulations(
    entry: HazardEntry,
    solved: Any,
    points: list[Any],
    reactions: list[Any],
    shares: dict[str, float],
) -> None:
    """``entry.accumulations`` (ADR 0069): each dosed reactant's largest accumulation over the
    batch, ``n_i(t) / (charged + dosed)``, and of it the share the screened reactions can still
    consume from the content then (:func:`.reaction_network.reactive`): a deliberate excess
    with nothing left to react with is not reactive. Given with more than one dosed reactant,
    or when the reactive share is below the plain one (an excess)."""
    from chemeascode.domains.safety.reaction_network import reactive

    found: dict[str, dict[str, float]] = {}
    differs = False
    for n, total in solved.dosed_reactants.items():
        plain = [max(q.moles.get(n, 0.0), 0.0) / total for q in points]
        able = [reactive(reactions, q.moles, n, shares) / total for q in points]
        i = max(range(len(points)), key=lambda k: plain[k])
        j = max(range(len(points)), key=lambda k: able[k])
        found[n] = {
            "max": plain[i],
            "time_s": points[i].time,
            "reactive_max": able[j],
            "reactive_time_s": points[j].time,
        }
        if able[j] < plain[i] * (1.0 - 1e-6) - 1e-12:
            differs = True
    if len(found) > 1 or differs:
        entry.accumulations = found


def _solution_rise(
    entry: HazardEntry, moles: dict[str, float], comps: dict[str, Any], mixing: float
) -> None:
    """The doses' heat of solution in dT_ad (ADR 0063): *mixing* kJ (per hour of flows) over the
    heat capacity of the whole batch, charge and doses (as the reactions' dT_ad). It is
    released as each dose mixes in, so a cooling failure with the dosing stopped finds none of
    it left: it counts in dT_ad (all of it dosed at once, a dosing error) and not in the
    MTSR."""
    lacking = sorted(
        n
        for n, v in moles.items()
        if v > 0 and not getattr(comps.get(n), "liquid_heat_capacity", 0)
    )
    if lacking:
        entry.missing.append(
            "the heat of solution's rise: liquid_heat_capacity of " + ", ".join(lacking)
        )
        return
    capacity = sum(v * comps[n].liquid_heat_capacity for n, v in moles.items() if v > 0)
    rise = mixing / capacity if capacity > 0 else 0.0
    entry.heat_of_solution = {
        "kJ_per_hour_of_flows": mixing,
        "adiabatic_rise_K": rise,
        "in_mtsr": False,
    }
    if entry.adiabatic_rise is not None:
        entry.adiabatic_rise += rise
    entry.notes.append(
        f"dT_ad includes the doses' heat of solution, {rise:.3g} K (released as they mix in, "
        "not accumulated: not in the MTSR)"
    )


def _profile(points: list[Any], values: list[float]) -> list[dict[str, float | None]]:
    """The MTSR (*values*, one per step) at the model's steps nearest PROFILE_POINTS moments
    evenly over the run, each step once, and the worst moment: values at a step, never
    interpolated."""
    end = points[-1].time
    picked = {
        min(
            range(len(points)),
            key=lambda k, m=end * i / (PROFILE_POINTS - 1): abs(points[k].time - m),
        )
        for i in range(PROFILE_POINTS)
    }
    picked.add(max(range(len(points)), key=lambda k: values[k]))
    return [
        {
            "time_s": points[k].time,
            "accumulation": points[k].accumulation,
            "temperature_K": points[k].temperature,
            "mtsr_K": values[k],
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


def _hours(process: Any, case: str) -> float | None:
    """h of the flowsheet's flows per batch (process/recipe.yaml's batch size), else None."""
    from chemeascode.domains.process.recipe import hours_per_batch

    try:
        return hours_per_batch(process, case)
    except ValueError:
        return None


def _basis(hours: float | None) -> str:
    return (
        f"per batch ({hours:.6g} h of the flowsheet's flows, process/recipe.yaml)"
        if hours
        else "per hour of the flowsheet's flows (no process/recipe.yaml batch size)"
    )


def _potential(item: Any) -> str | None:
    return getattr(getattr(item, "hazard", None), "potential", None)


def _pairs(reactions: list[Any]) -> list[str]:
    """Each consecutive pair of *reactions*, as text (ADR 0069)."""
    from chemeascode.domains.safety.reaction_network import consecutive

    return [f"{a} on a product of {b}" for a, b in consecutive(reactions)]


def _network_note(entry: HazardEntry, mtsr: float) -> None:
    if entry.mtsr is not None and mtsr > entry.mtsr + 0.05:
        entry.notes.append(
            f"the counted reactions as a network ({'; '.join(entry.network['consecutive'])}) "
            f"reach an MTSR of {mtsr:.1f} K, above the largest single reaction's "
            f"{entry.mtsr:.1f} K: hazard.potential: network counts it"
        )


def _batch_network(
    entry: HazardEntry,
    item: Any,
    counted_rx: list[Any],
    moles: dict[str, float],
    t_p: float,
    accumulation: float,
    comps: dict[str, Any],
    process: Any,
) -> dict[str, float] | None:
    """``entry.network`` of a batch, CSTR, PFR or conversion step (ADR 0069), given with
    hazard.potential: network or a consecutive reaction among the counted ones: the counted
    reactions' largest heat together from the feed over its heat capacity. With
    hazard.potential: network it sets dT_ad and the MTSR (its extents are returned)."""
    from chemeascode.domains.safety.reaction_network import network_heat

    potential = _potential(item)
    pairs = _pairs(counted_rx)
    # without hazard.potential the network is reported for a batch's cooling failure only
    if potential != "network" and not (pairs and getattr(item, "reactor", None) == "batch"):
        return None
    shares = item.batch.vent.shares() if _vented(item) else {}
    capacity, heats, lacking = _heats(counted_rx, moles, t_p, comps, process.ideal_gas())
    solved = network_heat(counted_rx, moles, heats, shares) if capacity else None
    if solved is None or capacity is None:
        if potential == "network":
            entry.missing.append(
                "the network's potential (hazard.potential: network): "
                + ("the feed's heat capacity" if not capacity else "a bounded heat (a cycle)")
            )
        return None
    heat, extents = solved
    if lacking and heat <= 0.0:
        # no known heat, or only endothermic ones: what is lacking may be exothermic, so the
        # network's rise is not known and dT_ad and the MTSR stay unset (as _adiabatic_rise's)
        if potential == "network":
            entry.missing.append(NETWORK_LACKING)
        return None
    rise = max(heat, 0.0) / capacity
    mtsr = t_p + accumulation * rise
    use = potential == "network"
    entry.network = {
        "adiabatic_rise_K": rise,
        "mtsr_K": mtsr,
        "consecutive": pairs,
        "in_mtsr": use,
    }
    if not use:
        _network_note(entry, mtsr)
        return None
    entry.adiabatic_rise, entry.mtsr = rise, mtsr
    entry.notes.append(
        "dT_ad and the MTSR: the counted reactions as a network (hazard.potential: network), "
        "their largest heat together"
    )
    return extents


def _end_state(
    counted_rx: list[Any],
    content: dict[str, float],
    rises: dict[str, float] | None,
    shares: dict[str, float],
    extents: dict[str, float] | None,
) -> tuple[str, dict[str, float] | None]:
    """The content once the cooling failure ran its course, and its label: the counted
    reactions' network end state (*extents*), else the content once the reaction setting the
    MTSR (the largest of *rises*) ran to completion; None without one."""
    from chemeascode.domains.safety.reaction_network import after

    if extents:
        return "the content after the counted reactions as a network", after(
            counted_rx, content, extents, shares
        )
    ids = {r.id: r for r in counted_rx}
    picked = {r: x for r, x in (rises or {}).items() if x > 0 and r in ids}
    if not picked:
        return "", None
    setter = max(picked, key=lambda r: picked[r])
    return f"the content after {setter}", _after(ids[setter], content, shares)


def _products(
    counted_rx: list[Any],
    moles: dict[str, float],
    shares: dict[str, float],
    extents: dict[str, float] | None,
) -> dict[str, tuple[float, str]]:
    """Product -> its largest share of the liquid once a counted reaction alone ran to
    completion of *moles* (or the network, *extents*), and after which: the products that are
    candidates for the default MTT (ADR 0069)."""
    from chemeascode.domains.safety.reaction_network import after

    found: dict[str, tuple[float, str]] = {}

    def take(content: dict[str, float], where: str, made: list[str]) -> None:
        total = sum(v for v in content.values() if v > 0)
        if total <= 0:
            return
        for n in made:
            share = max(content.get(n, 0.0), 0.0) / total
            if share > 0 and share > found.get(n, (0.0, ""))[0]:
                found[n] = (share, where)

    for r in counted_rx:
        made = [n for n, nu in r.stoichiometry.items() if nu > 0]
        if made and _extent(r, moles) > 0:
            take(_after(r, moles, shares), f"after {r.id}", made)
    if extents:
        made = list(
            dict.fromkeys(n for r in counted_rx for n, nu in r.stoichiometry.items() if nu > 0)
        )
        take(after(counted_rx, moles, extents, shares), "after the network", made)
    return found


def _dissolved_release(
    process: Any,
    item: Any,
    entry: HazardEntry,
    case: str,
    moles: dict[str, float],
    samples: list[tuple[float, dict[str, float], float]],
    pressure: float,
    left_out: dict[str, str],
    stripped: dict[str, float],
) -> None:
    """``entry.dissolved_release`` (ADR 0069, core#178 item 5): each dosed gas, dissolved gas
    and vent component boiling below the MTSR (as the default MTT leaves them out) held in the
    liquid, at its largest
    over *samples* (time s, content, the MTSR then): what a cooling failure can boil off or
    strip, per batch; its boiling point at the vessel's pressure against the MTSR then, and
    the most the gas release strips of it (*stripped*, kmol/s, with ``vent.vapour``)."""
    comps = process.components()
    candidates = dict(left_out) | _dissolved(
        moles, comps, pressure, entry.process_temperature, left_out
    )
    hours = _hours(process, case)
    scale = hours or 1.0
    found: dict[str, dict[str, Any]] = {}
    for n, why in candidates.items():
        when, content, mtsr = max(samples, key=lambda q, n=n: q[1].get(n, 0.0))
        amount = max(content.get(n, 0.0), 0.0) * scale
        strip = stripped.get(n, 0.0)
        if amount <= 0 and strip <= 0:
            continue
        mass = getattr(comps.get(n), "molar_mass", None)
        at = _boiling_at(comps.get(n), n, pressure)
        if why == "vent component" and at is not None and mtsr < at[0] and n not in stripped:
            continue  # a vented liquid (a product partly vented) that does not boil off
        row: dict[str, Any] = {
            "why": why,
            "kmol": amount,
            "kg": amount * mass if mass else None,
            "time_s": when,
            "mtsr_K": mtsr,
            "boiling_point_K": at[0] if at else None,
            "mtsr_above_boiling_point": bool(at and mtsr >= at[0]),
        }
        if n in stripped:
            row["stripped_kmol_s"] = strip
            row["stripped_kg_h"] = strip * mass * 3600.0 if mass else None
        found[n] = row
    if found:
        entry.dissolved_release = {
            "basis": _basis(hours),
            "pressure_kPa": pressure,
            "components": found,
        }


def _vented(item: Any) -> bool:
    batch = getattr(item, "batch", None)
    return batch is not None and batch.vent is not None


def _forms_gas(item: Any) -> bool:
    """A vented batch whose vent takes gas the reactions form: a vent of inerts only (a sweep,
    a head space's pad, ADR 0071) forms none at a cooling failure, the dosing stopped."""
    return _vented(item) and bool(item.batch.vent.components)


def _releases(item: Any) -> bool:
    """A vented batch the screening asks for a gas release: one that forms gas, or one with
    ``vent.vapour`` whose content may boil at the MTSR (its boil-up leaves by the same vent,
    ADR 0069), a vent of inerts only included (ADR 0071)."""
    return _forms_gas(item) or (_vented(item) and item.batch.vent.vapour is not None)


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
    after_network: dict[str, float] | None = None,
    points: list[Any] | None = None,
    values: list[float] | None = None,
) -> dict[str, float]:
    """``entry.gas_release`` (see the module docstring): the vent gas forming at the MTSR, the
    larger of two contents, *moles* (the worst moment's) and what is in the vessel once the
    reaction setting the MTSR (the largest of *rises*, of the *counted*; with hazard.potential:
    network the network's end state, *after_network*) ran to completion, so that gas formed
    from its products counts; and the most one reaction forms run to completion, of the counted
    ones from *moles*, or of a reaction consuming a product of the one setting the MTSR from the
    content after it. A semi-batch's *points* with their MTSR (*values*) give the largest
    release over the batch (ADR 0069). Returns the most of each volatile component the gas
    strips off the liquid over the batch (kmol/s, the gas release's basis). A vent of inerts
    only (ADR 0071) forms no gas at a cooling failure, the dosing stopped: it keeps a gas
    release only where its content boils at the MTSR (``boils``, ``boil_up``), with no
    release over the batch."""
    from chemeascode.domains.chemistry.thermochemistry import R
    from chemeascode.domains.process.stirred_tank import TankError, vent_gas_rate

    inerts_only = not item.batch.vent.components
    missing = len(entry.missing)
    every, _ = process.reactions_of(item.id)
    by_id = {r.id: r for r in every}
    shares = item.batch.vent.shares()
    picked = {r: x for r, x in (rises or {}).items() if counted is None or r in counted}
    setter = max(picked, key=lambda r: picked[r]) if picked else None
    if setter is not None and (picked[setter] <= 0 or setter not in by_id):
        setter = None
    after = _after(by_id[setter], moles, shares) if setter else None
    after_label = f"the content after {setter}" if setter else ""
    if after_network is not None:
        after, after_label = after_network, "the content after the counted reactions as a network"
    try:
        rate = vent_gas_rate(process, item, moles, temperature, pressure, case)
        rate_after = (
            vent_gas_rate(process, item, after, temperature, pressure, case) if after else 0.0
        )
    except TankError as failure:
        if not inerts_only:
            entry.missing.append(f"the gas release at the MTSR: {failure}")
        return {}
    hours = _hours(process, case)
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
        for r, kmol in _formed(chain, _after(by_id[setter], moles, shares), shares).items():
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
            after_label if after_label and rate_after > rate else "the worst moment's content"
        ),
        "temperature_K": temperature,
        "pressure_kPa": pressure,
        "formed_by": largest,
        "formed_kmol": formed.get(largest or "", 0.0) * scale,
        "formed_m3": formed.get(largest or "", 0.0) * scale * volume,
        "formed_from": source.get(largest or ""),
        "basis": _basis(hours),
        "per_batch": bool(hours),
    }
    _vapour_laden(process, item, entry, gas, moles, temperature, pressure, scale, case)
    if inerts_only and not gas.get("boils"):
        del entry.missing[missing:]  # no gas release, so nothing it lacks
        return {}
    stripped = (
        _over_batch(process, item, entry, gas, points, values, pressure, scale, case)
        if points and values and not inerts_only
        else {}
    )
    capacity = getattr(getattr(item, "hazard", None), "vent_capacity", None)
    if capacity:
        gas["vent_capacity_m3_h"] = capacity
        if hours:
            gas["capacity_ratio"] = gas["rate_m3_h"] / capacity
            if (over := gas.get("largest_over_batch")) is not None:
                over["capacity_ratio"] = over["rate_m3_h"] / capacity
            if (boil := gas.get("boil_up")) is not None:
                boil["capacity_ratio"] = boil["vapour_m3_h"] / capacity
    entry.gas_release = gas
    return stripped


def _saturation(phase: Any, moles: dict[str, float], t: float, p: float) -> dict[str, float]:
    """``y_i = K_i x_i`` of the vent's volatile components over *moles*: ``K_i = gamma_i
    P_i^sat(t) / p``, or ``H_i(t) / p`` of a gas that degasses by Henry's law (``vent.vapour.
    henry``, ADR 0071), as the vent's own phase takes them."""
    total = sum(v for v in moles.values() if v > 0)
    if total <= 0:
        return {}
    k = phase.k_values(t, p)
    return {n: k[n] * max(moles.get(n, 0.0), 0.0) / total for n in phase.volatile}


def _over_batch(
    process: Any,
    item: Any,
    entry: HazardEntry,
    gas: dict[str, Any],
    points: list[Any],
    values: list[float],
    pressure: float,
    scale: float,
    case: str | None = None,
) -> dict[str, float]:
    """``gas_release.largest_over_batch`` (ADR 0069): at every step of a semi-batch, the gas
    its content forms at that moment's MTSR (every reaction at its rate law, the vent's shares)
    with the liquid's vapour it carries (``vent.vapour``: ``G Y / (1 - Y)`` at that MTSR), the
    largest in m3/h; and the most of each volatile component stripped off the liquid over the
    batch (returned, kmol/s). The vapour takes its latent heat from the reactions' heat there,
    ``Q = sum_j (-dHr_j) M_j r_j``: it is at most ``Q / sum_i y_i dHvap_i`` (``heat_limited``),
    which bounds it as ``Y`` nears 1 and is a content's boil-up where it boils at that MTSR
    (without the heats, a boiling content counts its non-condensables only)."""
    from chemeascode.domains.chemistry.thermochemistry import R
    from chemeascode.domains.process.stirred_tank import TankError, extent_rates
    from chemeascode.domains.process.vent_vapour import VentError, phase_of

    vent = item.batch.vent
    phase = None
    if vent.vapour is not None:
        try:
            phase = phase_of(process, vent, list(points[0].moles), process.ideal_gas())
        except VentError:
            phase = None  # _vapour_laden named it
    every, _ = process.reactions_of(item.id)
    shares = vent.shares()
    try:
        rates = extent_rates(process, item, list(points[0].moles), case)
        extents = [rates(q.moles, t, pressure) for q, t in zip(points, values, strict=True)]
    except TankError as failure:
        entry.missing.append(f"the gas release over the batch: {failure}")
        return {}
    heats = (
        {r.id: -r.heat_of_reaction.value for r in every}
        if all(r.heat_of_reaction is not None for r in every)
        else None
    )
    stripped: dict[str, float] = {}
    best: dict[str, Any] | None = None
    for q, t, xi in zip(points, values, extents, strict=True):
        by = {
            g: f * sum(max(r.stoichiometry.get(g, 0.0) * xi[r.id], 0.0) for r in every)
            for g, f in shares.items()
        }
        made = sum(by.values())
        vapour: dict[str, float] = {}
        share = None
        limited = False
        if phase is not None and made > 0:
            ys = _saturation(phase, q.moles, t, pressure)
            share = sum(ys.values())
            carried = (
                {n: made * y / (1.0 - share) for n, y in ys.items() if y > 0}
                if share < 1.0
                else None
            )
            ceiling = None
            latent = sum(y * (phase.heat_of_vaporization.get(n) or 0.0) for n, y in ys.items())
            if (
                heats is not None
                and share > 0
                and latent > 0  # not with an endothermic absorption outweighing the rest
                and all(
                    phase.heat_of_vaporization.get(n) is not None for n, y in ys.items() if y > 0
                )
            ):
                heat = max(sum(heats[r.id] * xi[r.id] for r in every), 0.0)
                ceiling = {n: heat / latent * y for n, y in ys.items() if y > 0}
            if ceiling is not None and (
                carried is None or sum(ceiling.values()) < sum(carried.values())
            ):
                vapour, limited = ceiling, True
            elif carried is not None:
                vapour = carried
        for n, v in vapour.items():
            stripped[n] = max(stripped.get(n, 0.0), v * scale)
        m3_h = (made + sum(vapour.values())) * scale * R * t / pressure * 3600.0
        if best is None or m3_h > best["rate_m3_h"]:
            best = {
                "time_s": q.time,
                "temperature_K": t,
                "rate_kmol_s": made * scale,
                "rate_m3_h": m3_h,
                "by_component_kmol_s": {n: v * scale for n, v in {**by, **vapour}.items() if v > 0},
            }
            if share is not None:
                best["vapour_share"] = share
                if share >= 1.0:
                    best["boils"] = True
            if limited:
                best["heat_limited"] = True
    if best is not None:
        gas["largest_over_batch"] = best
    return stripped


def _vapour_laden(
    process: Any,
    item: Any,
    entry: HazardEntry,
    gas: dict[str, Any],
    moles: dict[str, float],
    temperature: float,
    pressure: float,
    scale: float = 1.0,
    case: str | None = None,
) -> None:
    """A vent with ``vapour`` (ADR 0062): the gas release leaves the vessel saturated with the
    liquid's volatile components at the MTSR, so its volume is the non-condensables' over
    ``1 - Y``, ``Y = sum_i gamma_i x_i P_i^sat(MTSR) / P`` over the content *moles* (a vent
    condenser is not credited: its cooling may fail too). ``Y >= 1``: the content boils at the
    MTSR, and its boil-up, not the gas, sets the release (``boils``; its vapour load at the
    content's bubble point, ``boil_up``, ADR 0069)."""
    from chemeascode.domains.process.vent_vapour import VentError, phase_of

    vent = item.batch.vent
    if vent.vapour is None:
        return
    try:
        phase = phase_of(process, vent, list(moles), process.ideal_gas())
    except VentError as failure:
        entry.missing.append(f"the vapour in the gas release: {failure}")
        return
    total = sum(v for v in moles.values() if v > 0)
    if not phase.volatile or total <= 0:
        return
    share = sum(_saturation(phase, moles, temperature, pressure).values())
    gas["vapour_share"] = share
    gas["noncondensable_m3_h"] = gas["rate_m3_h"]
    if share >= 1.0:
        gas["boils"] = True
        _boil_up(process, item, entry, gas, phase, moles, temperature, pressure, scale, case)
        boil = gas.get("boil_up")
        entry.notes.append(
            f"the content boils at the MTSR ({temperature:.1f} K): its vapour pressure "
            f"{share * pressure:.4g} kPa reaches the vessel's {pressure:.4g} kPa(a); "
            + (
                f"its boil-up at the bubble point {boil['temperature_K']:.1f} K is "
                f"{boil['vapour_m3_h']:.4g} m3/h of vapour (gas_release.boil_up: the reaction's "
                "heat there boils the content, a tempered reaction; no two-phase relief load)"
                if boil
                else "the gas release is the boil-up, which the screening does not size "
                "(gas_release.boils)"
            )
        )
        return
    gas["rate_m3_h"] /= 1.0 - share
    # formed_kmol and formed_m3 stay the gas formed (the non-condensables, one basis); the
    # volume it leaves with, the liquid's vapour included, is a key of its own
    gas["formed_m3_with_vapour"] = gas["formed_m3"] / (1.0 - share)


def _boil_up(
    process: Any,
    item: Any,
    entry: HazardEntry,
    gas: dict[str, Any],
    phase: Any,
    moles: dict[str, float],
    mtsr: float,
    pressure: float,
    scale: float,
    case: str | None = None,
) -> None:
    """``gas_release.boil_up`` (ADR 0069, a content boiling at the MTSR): the content (*moles*)
    boils at its bubble point ``T_b`` (the vent's volatile components, Raoult's law), where the
    reactions' heat at their rate laws, ``Q = sum_j (-dHr_j) M_j r_j(T_b)``, goes into its
    vapour (a tempered reaction at the vessel's pressure): ``V = Q / sum_i y_i dHvap_i``,
    ``y_i`` the vapour's composition at ``T_b``. The volume at ``T_b`` and the vessel's
    pressure. Not a two-phase relief load (no level swell, no head space)."""
    from chemeascode.domains.chemistry.thermochemistry import R
    from chemeascode.domains.process.stirred_tank import TankError, extent_rates

    low, high = 1.0, mtsr
    for _ in range(200):
        mid = 0.5 * (low + high)
        if sum(_saturation(phase, moles, mid, pressure).values()) < 1.0:
            low = mid
        else:
            high = mid
        if high - low < 1e-10:
            break
    t_b = 0.5 * (low + high)
    y = _saturation(phase, moles, t_b, pressure)
    norm = sum(y.values()) or 1.0
    y = {n: v / norm for n, v in y.items() if v > 0}
    if lack := sorted(n for n in y if phase.heat_of_vaporization.get(n) is None):
        # a degassing gas's latent heat is its heat of desorption, -vent.heat_of_absorption
        # (ADR 0071): the materials' heat_of_vaporization does not stand in for it
        liquids = [n for n in lack if n not in phase.degassing]
        gases = [n for n in lack if n in phase.degassing]
        parts = ["heat_of_vaporization of " + ", ".join(liquids)] if liquids else []
        if gases:
            parts.append(
                "vent.heat_of_absorption of "
                + ", ".join(gases)
                + " (its heat of desorption, vent.vapour.henry)"
            )
        entry.missing.append("the boil-up at the MTSR: " + "; ".join(parts))
        return
    every, _ = process.reactions_of(item.id)
    if lack := [r.id for r in every if r.heat_of_reaction is None]:
        entry.missing.append("the boil-up at the MTSR: heat_of_reaction of " + ", ".join(lack))
        return
    try:
        rates = extent_rates(process, item, list(moles), case)(moles, t_b, pressure)
    except TankError as failure:
        entry.missing.append(f"the boil-up at the MTSR: {failure}")
        return
    heat = sum(-r.heat_of_reaction.value * rates[r.id] for r in every) * scale  # kW
    latent = sum(v * phase.heat_of_vaporization[n] for n, v in y.items())  # kJ/kmol
    if latent <= 0:
        # a degassing gas's latent heat is -vent.heat_of_absorption, which may be negative (an
        # endothermic absorption): a vapour taking no heat to form has no boil-up
        gases = [n for n in y if n in phase.degassing and phase.heat_of_vaporization[n] <= 0]
        liquids = [n for n in y if n not in phase.degassing and phase.heat_of_vaporization[n] <= 0]
        parts = ["heat_of_vaporization of " + ", ".join(liquids)] if liquids else []
        if gases:
            parts.append(
                "vent.heat_of_absorption of "
                + ", ".join(gases)
                + ": an endothermic absorption, its desorption releases heat"
            )
        entry.missing.append(
            "the boil-up at the MTSR: the vapour's latent heat is not positive ("
            + "; ".join(parts)
            + ")"
        )
        return
    vapour = max(heat, 0.0) / latent
    gas["boil_up"] = {
        "temperature_K": t_b,
        "heat_kW": heat,
        "vapour_kmol_s": vapour,
        "vapour_m3_h": vapour * R * t_b / pressure * 3600.0,
        "by_component_kmol_s": {n: vapour * v for n, v in y.items()},
    }


def _vapour_text(gas: dict[str, Any]) -> str:
    """The vapour's part of a gas release (ADR 0062), '' without one."""
    if "vapour_share" not in gas:
        return ""
    if gas.get("boils"):
        return f" (the non-condensables; the content boils, vapour share {gas['vapour_share']:.3g})"
    return (
        f" with the liquid's vapour ({gas['vapour_share']:.3g} of the gas; the non-condensables "
        f"{gas['noncondensable_m3_h']:.4g} m3/h)"
    )


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
    gone = f"{', '.join(vent.components)} leave(s) as formed"
    if vent.inerts:  # ADR 0071
        gone = ", ".join(
            [*([gone] if vent.components else []), f"{', '.join(vent.inerts)} pass(es) through"]
        )
    entry.notes.append(
        f"vent {vent.stream}: {gone}, no part of the heat capacity or the MTSR"
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
        found |= dict.fromkeys(item.batch.vent.inerts, "vent inert")  # ADR 0071
        # a gas held in solution that degasses by Henry's law (ADR 0071): a dissolved gas
        # whatever its share of the liquid or its boiling point, dosed or not (the schema keeps
        # it apart from the vent's components and inerts, so only a dosed gas's reason yields)
        found |= dict.fromkeys(_henry_gases(item), HENRY_GAS)
    return found


#: why the default MTT and the bubble point leave out a ``vent.vapour.henry`` gas (ADR 0071)
HENRY_GAS = "dissolved gas (vent.vapour.henry)"


def _henry_gases(item: Any) -> list[str]:
    """The gases a vented batch's ``vent.vapour.henry`` declares held in solution (ADR 0071)."""
    if not _vented(item) or (vapour := item.batch.vent.vapour) is None:
        return []
    return list(vapour.henry)


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
    products: dict[str, tuple[float, str]] | None = None,
    contents: list[tuple[str, dict[str, float]]] | None = None,
) -> None:
    """The MTT and TD24 of *entry*, and its class once the MTSR is known. *products*: product
    -> its largest share of the liquid once a counted reaction ran to completion, and after
    which (ADR 0069); *contents*: the (label, content) whose bubble point hazard.mtt_from:
    bubble-point takes."""
    hazard = getattr(item, "hazard", None)
    if hazard is not None and hazard.mtt:
        entry.mtt, entry.mtt_basis = hazard.mtt, "hazard.mtt"
    elif getattr(hazard, "mtt_from", None) == "bubble-point":
        _bubble_mtt(entry, item, moles, comps, p_in, left_out or {}, contents or [])
    elif any(r.phase == "liquid" for r in reactions):
        _default_mtt(entry, moles, comps, p_in, left_out or {}, products or {})
    else:
        entry.missing.append("the MTT (hazard.mtt)")
    if hazard is not None and hazard.td24:
        entry.td24 = hazard.td24
    else:
        entry.missing.append("TD24 of the decomposition (hazard.td24, from calorimetry)")
    if entry.mtsr is not None and entry.mtt is not None and entry.td24 is not None:
        entry.criticality = criticality(entry.mtsr, entry.mtt, entry.td24)


def _boiling_at(comp: Any, name: str, pressure: float) -> tuple[float, str, bool] | None:
    """*comp*'s boiling point K at *pressure* kPa(a), its basis and whether its
    heat_of_vaporization was lacking away from atmospheric pressure (the normal boiling point
    then stands in); None without a normal boiling point."""
    normal = getattr(comp, "normal_boiling_point", None)
    if not normal:
        return None
    if BELOW_ATMOSPHERIC <= pressure <= ATMOSPHERIC:
        return normal, f"normal boiling point of {name}", False
    heat = getattr(comp, "heat_of_vaporization", None)
    if heat:
        return (
            boiling_point(normal, heat, pressure),
            f"boiling point of {name} at {pressure:.4g} kPa(a), Clausius-Clapeyron with its "
            "heat_of_vaporization",
            False,
        )
    return normal, f"normal boiling point of {name}", True


def _dissolved(
    moles: dict[str, float],
    comps: dict[str, Any],
    pressure: float,
    t_p: float | None,
    left_out: dict[str, str],
) -> dict[str, str]:
    """Component -> why it is a dissolved gas: a minor share of the liquid (below DISSOLVED)
    boiling below *t_p* at *pressure* (ADR 0058); above atmospheric a component without
    heat_of_vaporization is never one (its boiling point there is not known)."""
    found: dict[str, str] = {}
    total = sum(v for v in moles.values() if v > 0)
    if t_p is None or total <= 0:
        return found
    for n, v in moles.items():
        if n in left_out or (at := _boiling_at(comps.get(n), n, pressure)) is None:
            continue
        share = v / total
        if at[0] < t_p and share < DISSOLVED and not (pressure > ATMOSPHERIC and at[2]):
            found[n] = (
                f"dissolved gas ({share:.2%} of the liquid, boils at {at[0]:.1f} K, below "
                f"T_p {t_p:.1f} K)"
            )
    return found


def _default_mtt(
    entry: HazardEntry,
    moles: dict[str, float],
    comps: dict[str, Any],
    p_in: float | None,
    left_out: dict[str, str],
    products: dict[str, tuple[float, str]] | None = None,
) -> None:
    """The lowest boiling point at the vessel's pressure of what boils in the liquid (see the
    module docstring), the products a counted reaction forms in it among the candidates."""
    pressure = p_in if p_in is not None else 101.325
    above = pressure > ATMOSPHERIC
    atmospheric = BELOW_ATMOSPHERIC <= pressure <= ATMOSPHERIC
    t_p = entry.process_temperature
    boiling: dict[str, tuple[float, str]] = {}
    unknown: list[str] = []  # no heat_of_vaporization: the normal boiling point stands in
    out: dict[str, str] = {}
    dissolved = _dissolved(moles, comps, pressure, t_p, left_out)
    for n in moles:
        if left_out.get(n) == HENRY_GAS:  # named with or without a boiling point (ADR 0071)
            out[n] = HENRY_GAS
            continue
        at = _boiling_at(comps.get(n), n, pressure)
        if at is None:
            continue
        if n in left_out:
            out[n] = left_out[n]
            continue
        if at[2]:
            unknown.append(n)
        if n in dissolved:
            out[n] = dissolved[n]
            continue
        boiling[n] = (at[0], at[1])
    # ADR 0069: a product a counted reaction forms in the liquid boils too; a minor one (below
    # DISSOLVED) or one boiling below T_p (it leaves as it forms, or the vessel is pressurised)
    # does not boil the batch, and is named only where it would have set the MTT
    passed: dict[str, tuple[float, str]] = {}
    vacuum: list[str] = []
    for n, (share, where) in (products or {}).items():
        # a vented product the liquid keeps in part (its share after the vent's) boils too
        if moles.get(n, 0.0) > 0 or left_out.get(n, "vent component") != "vent component":
            continue
        if (at := _boiling_at(comps.get(n), n, pressure)) is None:
            continue
        if share < DISSOLVED or (t_p is not None and at[0] < t_p):
            continue  # a minor product, or one that leaves as it forms: no candidate
        if above and at[2]:
            # its boiling point here is not known: no candidate (a product never leaves the
            # MTT missing), named where its normal boiling point is below the MTT
            passed[n] = (
                at[0],
                f"product without heat_of_vaporization (normal boiling point {at[0]:.1f} K; "
                f"its boiling point at {pressure:.4g} kPa(a) is not known)",
            )
        else:
            if at[2]:  # under vacuum: named below where it could set the MTT
                vacuum.append(n)
            boiling[n] = (at[0], f"{at[1]}, a product ({share:.0%} of the liquid {where})")

    def named(mtt: float | None) -> None:
        for n, (bp, why) in passed.items():
            if mtt is None or bp < mtt:
                out[n] = why
        entry.mtt_left_out = out
        if out:
            entry.notes.append(
                "MTT: left out "
                + ", ".join(f"{n} ({why})" for n, why in out.items())
                + ": they leave or boil off rather than boil the batch"
            )

    if not boiling:
        named(None)
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
        named(None)
        lacking = open_ or [n for n in unknown if n in boiling]
        entry.missing.append("the MTT (hazard.mtt)")
        entry.notes.append(
            f"the MTT at {pressure:.4g} kPa(a) needs heat_of_vaporization of "
            + ", ".join(lacking)
            + " (Clausius-Clapeyron from the normal boiling point)"
        )
        return
    if above:
        mtt, basis = min(known)
    named(mtt)
    unknown += [n for n in vacuum if boiling[n][0] <= mtt]
    if not above and unknown and not atmospheric:
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


def _bubble_mtt(
    entry: HazardEntry,
    item: Any,
    moles: dict[str, float],
    comps: dict[str, Any],
    p_in: float | None,
    left_out: dict[str, str],
    contents: list[tuple[str, dict[str, float]]],
) -> None:
    """hazard.mtt_from: bubble-point (ADR 0069): the MTT is the lowest bubble point at the
    vessel's pressure of *contents* (the worst moment's, and once the reaction setting the
    MTSR ran to completion), leaving out the vent components, dosed gases and dissolved gases
    (they leave or boil off), with ``vent.vapour.activity`` where given."""
    from chemeascode.domains.process.batch_kinetics import bubble_point

    pressure = p_in if p_in is not None else 101.325
    t_p = entry.process_temperature
    # a gas held in solution does not follow Raoult's law: a vent component or dosed gas boiling
    # below T_p is left out, as a dissolved gas; one boiling above it is a volatile liquid
    # a vent.vapour.henry gas (ADR 0071) is a gas held in solution whatever its boiling point
    out = {
        n: why
        for n, why in left_out.items()
        if why == HENRY_GAS
        or t_p is None
        or (at := _boiling_at(comps.get(n), n, pressure)) is None
        or at[0] < t_p
    } | _dissolved(moles, comps, pressure, t_p, left_out)
    # a product a counted reaction forms (not in the charge or feed) boiling below T_p leaves as
    # it forms, a gas held in solution: left out as the default MTT leaves it out (ADR 0069)
    for _, content in contents:
        for n, v in content.items():
            if v <= 0 or n in out or moles.get(n, 0.0) > 0:
                continue
            at = _boiling_at(comps.get(n), n, pressure)
            if (
                t_p is not None
                and at is not None
                and at[0] < t_p
                and not (pressure > ATMOSPHERIC and at[2])
            ):
                out[n] = f"product boiling at {at[0]:.1f} K, below T_p {t_p:.1f} K"
    vent = getattr(getattr(item, "batch", None), "vent", None)
    vapour = getattr(vent, "vapour", None)
    activity = dict(getattr(vapour, "activity", None) or {})
    found: dict[str, float | None] = {}
    lacking: list[str] = []
    for label, content in contents:
        t, lack = bubble_point(content, comps, pressure, activity, list(out))
        found[label] = t
        lacking += [n for n in lack if n not in lacking]
    entry.bubble_point = {
        "pressure_kPa": pressure,
        "contents": found,
        "left_out": sorted(out),
    }
    if lacking:
        entry.missing.append(
            "the MTT (hazard.mtt): the bubble point needs vapour_pressure (or "
            "heat_of_vaporization) of " + ", ".join(lacking)
        )
        return
    known = {k: v for k, v in found.items() if v is not None}
    if not known:
        entry.missing.append("the MTT (hazard.mtt): nothing in the content boils")
        return
    label = min(known, key=lambda k: known[k])
    entry.mtt = known[label]
    entry.mtt_basis = f"bubble point of {label} at {pressure:.4g} kPa(a)"
    if out:
        entry.notes.append(
            "bubble point: left out " + ", ".join(sorted(out)) + " (vent components, dosed or "
            "dissolved gases and products boiling below T_p: gases held in solution, they boil "
            "off rather than boil the batch)"
        )
    if t_p is not None and entry.mtt < t_p:
        entry.notes.append(
            f"MTT {entry.mtt:.1f} K ({entry.mtt_basis}) below T_p {t_p:.1f} K: the content "
            "boils at once on a cooling failure"
        )


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
                f"{gas['pressure_kPa']:.4g} kPa(a)" + _vapour_text(gas) + f", {gas['basis']}"
            )
            capacity = gas.get("vent_capacity_m3_h")
            # ADR 0069: the largest release over a semi-batch where it is above the MTSR's
            over = gas.get("largest_over_batch")
            if over is not None and over["rate_m3_h"] > gas["rate_m3_h"] * (1 + 1e-9):
                release += (
                    f"; over the batch up to {over['rate_m3_h']:.4g} m3/h at "
                    f"{over['time_s'] / 3600:.3g} h (its MTSR {over['temperature_K']:.1f} K)"
                )
            else:
                over = None
            if gas.get("boils"):
                boil = gas.get("boil_up")
                add(
                    "warning",
                    "vent",
                    release + ": the content boils at the MTSR (its vapour pressure reaches "
                    "the vessel's)"
                    + (
                        f"; its boil-up at the bubble point {boil['temperature_K']:.1f} K is "
                        f"{boil['vapour_m3_h']:.4g} m3/h of vapour ({boil['heat_kW']:.4g} kW "
                        "of reaction heat)"
                        + (
                            f", {boil['capacity_ratio']:.3g} times the vent capacity "
                            f"{capacity:.4g} m3/h"
                            if "capacity_ratio" in boil
                            else ""
                        )
                        if boil
                        else ""
                    ),
                    "the boil-up at a cooling failure sets the vent's and relief's load: size "
                    "them for it (a two-phase relief study), or lower the MTSR",
                )
            elif capacity is None:
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
                ratio = max(gas["capacity_ratio"], over["capacity_ratio"] if over else 0.0)
                add(
                    "warning" if ratio > 1 else "info",
                    "vent",
                    release
                    + f", {ratio:.3g} times the vent capacity {capacity:.4g} m3/h "
                    + ("(above it)" if ratio > 1 else "(within it)"),
                    "a gas release above the vent's capacity pressurises the vessel: limit "
                    "the accumulation, or size the vent and relief for it"
                    if ratio > 1
                    else (
                        "screening values: the rate is the largest release over the batch, "
                        "each step's content at its own MTSR (every reaction at its rate law, "
                        "with the liquid's vapour, at most what the reactions' heat there "
                        "evaporates)"
                        if over is not None
                        else "screening values: the rate is the larger of the worst moment's "
                        "content and the content after the reaction setting the MTSR, at the "
                        "MTSR; gas from a longer chain of consecutive reactions is not covered"
                    ),
                )
        if (start := e.initiation) is not None and start["mtsr_K"] is not None:
            above = [
                n
                for n, v in (("MTT", e.mtt), ("TD24", e.td24))
                if v is not None and start["mtsr_K"] > v
            ]
            add(
                "warning" if above else "info",
                "initiation",
                f"{e.node}: uninitiated (the initiation due at {start['time_s']:.6g} s never "
                f"coming), the dosing going on to {start['until_s']:.6g} s accumulates "
                + (
                    f"{start['max_accumulation']:.3g} of the dosed reactant"
                    if start["max_accumulation"] is not None
                    else "its doses"
                )
                + f"; a cooling failure or a late initiation then reaches {start['mtsr_K']:.1f} K"
                + (f", above the {' and the '.join(above)}" if above else ""),
                "interlock the dosing on a positive initiation (dosing.after_initiation) and "
                "limit the initiation charge: what is dosed before it initiates accumulates",
            )
        if (held := e.dissolved_release) is not None:
            add(
                "info",
                "dissolved",
                f"{e.node}: a cooling failure can release the gases held in the liquid: "
                + "; ".join(_held_text(n, row) for n, row in held["components"].items())
                + f" ({held['basis']})",
                "a toxic or flammable one needs its release screened: hold the scrubber or "
                "catch tank for the inventory, dose it against its consumption (limit its "
                "accumulation) and check its dispersion",
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


def _held_text(name: str, row: dict[str, Any]) -> str:
    """One dissolved or dosed gas of ``dissolved_release`` (ADR 0069), as text."""
    mass = f" ({row['kg']:.4g} kg)" if row.get("kg") is not None else ""
    text = f"{name} up to {row['kmol']:.4g} kmol{mass} at {row['time_s'] / 3600:.3g} h"
    if row.get("boiling_point_K") is not None:
        text += (
            f", boiling at {row['boiling_point_K']:.1f} K "
            + ("below" if row["mtsr_above_boiling_point"] else "above")
            + f" the MTSR {row['mtsr_K']:.1f} K then"
        )
    if row.get("stripped_kg_h") is not None:
        text += f", stripped into the gas release at most {row['stripped_kg_h']:.4g} kg/h"
    return text


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
        if (net := e.network) is not None:
            lines.append(
                "  network of the counted reactions"
                + (f" ({'; '.join(net['consecutive'])})" if net.get("consecutive") else "")
                + f": dT_ad {num(net.get('adiabatic_rise_K'), 'K')}, MTSR {num(net['mtsr_K'], 'K')}"
                + (f" at {net['time_s'] / 3600:.3g} h" if net.get("time_s") is not None else "")
                + (
                    " (counted: hazard.potential: network)"
                    if net["in_mtsr"]
                    else " (not counted; hazard.potential: network counts it)"
                )
            )
        if e.accumulations:
            lines.append(
                "  accumulation of each dosed reactant (largest; of it still able to react): "
                + "; ".join(
                    f"{n} {v['max']:.3g} at {v['time_s'] / 3600:.3g} h ({v['reactive_max']:.3g}"
                    f" at {v['reactive_time_s'] / 3600:.3g} h)"
                    for n, v in e.accumulations.items()
                )
            )
        if (start := e.initiation) is not None:
            lines.append(
                f"  uninitiated to {start['until_s'] / 3600:.3g} h (initiation due at "
                f"{start['time_s'] / 3600:.3g} h, {start['doses_waiting']} dose(s) waiting for "
                "it): "
                + (
                    f"X_ac {start['max_accumulation']:.3g}, MTSR {start['mtsr_K']:.1f} K"
                    if start["mtsr_K"] is not None
                    else "nothing dosed accumulates"
                )
            )
        if (bubble := e.bubble_point) is not None:
            lines.append(
                f"  bubble point at {bubble['pressure_kPa']:.4g} kPa(a): "
                + "; ".join(f"{label} {num(t, 'K')}" for label, t in bubble["contents"].items())
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
                f"{gas['pressure_kPa']:.4g} kPa(a){_vapour_text(gas)} ({gas['basis']}; "
                f"{gas['rate_from']}); "
                f"{gas['formed_kmol']:.4g} kmol ({gas['formed_m3']:.4g} m3"
                + (
                    f"; {gas['formed_m3_with_vapour']:.4g} m3 with the liquid's vapour"
                    if "formed_m3_with_vapour" in gas
                    else ""
                )
                + f") formed by {gas['formed_by'] or 'no reaction'} run to completion"
                + (f" ({gas['formed_from']})" if gas.get("formed_from") else "")
                + (
                    f"; vent capacity {gas['vent_capacity_m3_h']:.4g} m3/h"
                    if "vent_capacity_m3_h" in gas
                    else ""
                )
            )
            if (over := gas.get("largest_over_batch")) is not None:
                lines.append(
                    f"  largest gas release over the batch: {over['rate_kmol_s']:.4g} kmol/s, "
                    f"{over['rate_m3_h']:.4g} m3/h at {over['time_s'] / 3600:.3g} h (its MTSR "
                    f"{over['temperature_K']:.1f} K"
                    + (
                        f", vapour share {over['vapour_share']:.3g}"
                        if "vapour_share" in over
                        else ""
                    )
                    + (", the content boils" if over.get("boils") else "")
                    + (
                        ", the vapour limited by the reactions' heat"
                        if over.get("heat_limited")
                        else ""
                    )
                    + ")"
                    + (
                        ": "
                        + ", ".join(f"{n} {v:.4g}" for n, v in over["by_component_kmol_s"].items())
                        + " kmol/s"
                        if over["by_component_kmol_s"]
                        else ""
                    )
                    + (
                        f"; {over['capacity_ratio']:.3g} times the vent capacity"
                        if "capacity_ratio" in over
                        else ""
                    )
                )
            if (boil := gas.get("boil_up")) is not None:
                lines.append(
                    f"  boil-up at the bubble point {boil['temperature_K']:.1f} K: "
                    f"{boil['vapour_kmol_s']:.4g} kmol/s, {boil['vapour_m3_h']:.4g} m3/h of "
                    f"vapour from {boil['heat_kW']:.4g} kW of reaction heat"
                    + (
                        f"; {boil['capacity_ratio']:.3g} times the vent capacity"
                        if "capacity_ratio" in boil
                        else ""
                    )
                )
        if (held := e.dissolved_release) is not None:
            lines.append(
                "  gases held in the liquid a cooling failure can release: "
                + "; ".join(_held_text(n, row) for n, row in held["components"].items())
                + f" ({held['basis']})"
            )
        lines += [f"  note: {n}" for n in e.notes]
    for p in report.phase_changes:
        lines.append(f"{p.node}: not screened (phase changes: {', '.join(p.reactions)})")
    if not report.entries and not report.phase_changes:
        lines.append("no reactors")
    lines += [f.format() for f in report.findings]
    lines.append("screening values: they do not replace calorimetry or a reaction-hazard study")
    return "\n".join(lines)
