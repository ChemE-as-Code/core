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
- ``MTT`` from the reactor's ``hazard.mtt``, else the lowest normal boiling point of a
  liquid-phase reactor's components at about atmospheric pressure (110 kPa(a) at most);
  ``TD24`` from ``hazard.td24`` only (calorimetry; never estimated);
- the criticality class (Stoessel, Chem. Eng. Prog. 89 (1993) 68): 1 MTSR < MTT < TD24,
  2 MTSR < TD24 < MTT, 3 MTT < MTSR < TD24, 4 MTT < TD24 < MTSR, 5 TD24 < MTSR with
  TD24 < MTT;
- for a cooled fixed bed: the hot spot's sensitivity ``d T_hot / d T_coolant`` (1 K steps);
  above 5 the bed is near runaway (parametric sensitivity, Morbidelli and Varma).

Rules (``cheme.reactor-hazard-*``, findings on ``process/flowsheet.yaml``): ``-class``
(info for classes 1 and 2, warning for 3 to 5), ``-mtsr`` (warning: the MTSR above the MTT or
the TD24 where the class cannot be given), ``-sensitivity`` (warning), ``-missing`` (info: what
the screening lacks). These are screening values for a concept or basic design: they do not
replace calorimetry or a reaction-hazard study, and decide nothing.
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
class HazardReport:
    entries: list[HazardEntry]
    findings: list[Finding]
    source: SourceRevision | None = None

    def to_json(self) -> str:
        return json.dumps(
            {
                "reactors": [asdict(e) for e in self.entries],
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


def screen_node(process: Any, node: str, case: str) -> HazardEntry:
    """The screening of reactor *node* in *case* (see the module docstring)."""
    from chemeascode.domains.process.model import stream_flows
    from chemeascode.foundation.units import to_kelvin, to_kpa_abs

    fs = process.flowsheet
    item = process.nodes[node]
    model = getattr(item, "reactor", None) or "conversion"
    entry = HazardEntry(node, model)
    reactions, _ = process.reactions_of(node)
    inlets = [s for s in fs.streams if (e := process.ends(s)[1]) is not None and e.node == node]
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
    bed = getattr(item, "bed", None)
    if model == "pfr" and bed is not None and bed.heat == "cooled" and bed.coolant_temperature:
        entry.sensitivity = _sensitivity(process, item, inlet, case)
    return entry


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
    entries = [
        screen_node(process, n.id, case)
        for n in [*fs.blocks, *fs.steps]
        if process.reactive(n.id) and (n.reactions or getattr(n, "reactor", None))
    ]
    findings: list[Finding] = []
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
    return HazardReport(entries, findings, source_revision(root, paths))


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
    if not report.entries:
        lines.append("no reactors")
    lines += [f.format() for f in report.findings]
    lines.append("screening values: they do not replace calorimetry or a reaction-hazard study")
    return "\n".join(lines)
