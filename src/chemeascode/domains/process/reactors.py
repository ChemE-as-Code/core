"""``cheme process reactors``: what each reactor of the flowsheet does, from its streams and the
ideal-gas thermochemistry of its components.

For every block or step that is reactive (``reactions:``, ``reactor:`` or
``balance_scope: reactive``), in one case: its model, the extents of its reactions (fitted to
its streams, as ``validate`` does), the heat of each reaction and its equilibrium constant at
the outlet temperature (plus the approach), how far the outlet is from equilibrium
(``ln(Q / K)``: 0 at equilibrium, negative short of it for the reaction as written), the rate
at the outlet where the reaction has a rate law, and the duty ``H(out) - H(in)`` on the
elements basis (ideal gas: positive is heat added). In a Gibbs reactor an inert (in no
independent reaction) needs no formation data: with its heat capacity it adds its sensible
heat, without one its sensible heat is left out and ``duty_assumptions`` says so (ASSUMED). A
value that cannot be computed is None,
and ``missing`` says why.
"""

from __future__ import annotations

import contextlib
import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from chemeascode.domains.chemistry.equilibrium import reaction_ln_k
from chemeascode.domains.chemistry.rates import rate
from chemeascode.domains.chemistry.reactions import REACTIONS_FILE, k_basis
from chemeascode.domains.chemistry.thermochemistry import (
    P_STANDARD,
    inert_species,
    missing,
    mixture_enthalpy,
    outside,
    reaction_enthalpy,
)
from chemeascode.domains.process import FLOWSHEET_FILE, MATERIALS_FILE
from chemeascode.domains.process.duties import (
    batch_duty,
    conversion_duty,
    duty_model,
    report_entry,
    report_lines,
    vent_condenser_duty,
)
from chemeascode.domains.process.model import Process, balance_of, stream_flows
from chemeascode.foundation.findings import Finding
from chemeascode.foundation.provenance import SourceRevision, source_revision
from chemeascode.foundation.units import to_kelvin, to_kpa_abs
from chemeascode.foundation.workspace import PLANT_FILE, NotAPlantRepository

REPORT_INPUTS = (MATERIALS_FILE, FLOWSHEET_FILE, REACTIONS_FILE, PLANT_FILE)


class UnknownCase(ValueError):
    """The case asked for is not declared in the flowsheet."""


@dataclass
class ReactorReport:
    root: Path
    case: str | None
    process: Process | None
    findings: list[Finding] = field(default_factory=list)
    #: One entry per reactive block or step (see :func:`reactor_entry`).
    reactors: list[dict[str, Any]] = field(default_factory=list)
    source: SourceRevision = field(default_factory=lambda: SourceRevision(None))

    @property
    def loaded(self) -> bool:
        return self.process is not None and not any(f.level == "error" for f in self.findings)

    def payload(self) -> dict[str, Any]:
        return {"case": self.case, "reactors": self.reactors}

    def to_json(self) -> str:
        return json.dumps(self.payload(), indent=2)

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.payload(),
            "findings": [{**asdict(f), "id": f.id} for f in self.findings],
            "source": self.source.as_dict(),
        }


def equilibrium_conditions(units: Any, case: str, ins: list[Any], out: Any) -> tuple[float, float]:
    """Temperature (K, the outlet's) and pressure (kPa(a): the outlet's, else the inlets'
    lowest absolute one) an equilibrium is taken at; ValueError naming what is missing. One
    helper for cheme process propagate and this report, so both use the same conditions."""
    state = out.state.get(case)
    t = getattr(state, "temperature", None)
    if t is None:
        raise ValueError(f"no outlet temperature ({out.id}) to take the equilibrium at")
    kelvin = to_kelvin(t.value, t.unit or units.temperature)
    if kelvin is None:
        raise ValueError(f"temperature unit {t.unit or units.temperature} of {out.id} is not known")
    own = getattr(state, "pressure", None)
    kpa = to_kpa_abs(own.value, own.unit or units.pressure) if own is not None else None
    if kpa is None:
        inlet = [
            to_kpa_abs(q.value, q.unit or units.pressure)
            for s in ins
            if (q := getattr(s.state.get(case), "pressure", None)) is not None
        ]
        kpa = min((v for v in inlet if v is not None), default=None)
    if kpa is None or kpa <= 0:
        raise ValueError(f"no absolute pressure of {out.id} or its inlets")
    return kelvin, kpa


def _state_value(process: Process, stream: Any, case: str, name: str) -> float | None:
    state = stream.state.get(case)
    q = getattr(state, name, None) if state is not None else None
    if q is None:
        return None
    units = process.flowsheet.units
    if name == "temperature":
        return to_kelvin(q.value, q.unit or units.temperature)
    return to_kpa_abs(q.value, q.unit or units.pressure)


def _moles(process: Process, stream: Any, case: str) -> dict[str, float] | None:
    flows = stream_flows(process, stream, case)
    if flows.components is None:
        return None
    comps = process.components()
    out = {}
    for name, kg in flows.components.items():
        mw = getattr(comps.get(name), "molar_mass", None)
        if kg and not mw:
            return None
        if kg:
            out[name] = kg / mw  # type: ignore[operator]
    return out


def _without(moles: dict[str, float], names: list[str]) -> dict[str, float]:
    return {n: v for n, v in moles.items() if n not in names}


def _model(item: Any) -> str | None:
    """The reactor model of *item* itself (None for a block that only holds reactors)."""
    if getattr(item, "reactor", None):
        return item.reactor
    own = getattr(item, "reactions", [])
    return "conversion" if own else None


def reactor_entry(process: Process, node: str, case: str, with_bed: bool = True) -> dict[str, Any]:
    """What reactor *node* does in *case* (see the module docstring)."""
    item = process.nodes[node]
    balance = balance_of(process, node, case)
    reactions, _ = process.reactions_of(node)
    streams = {s.id: s for s in process.flowsheet.streams}
    ins = [streams[s] for s in balance.streams_in]
    outs = [streams[s] for s in balance.streams_out]
    data = process.ideal_gas()
    lacking: list[str] = []
    t_in = [_state_value(process, s, case, "temperature") for s in ins]
    t_out = [_state_value(process, s, case, "temperature") for s in outs]
    # a vented batch (ADR 0054): its liquid outlet is the reactor's outlet, the vent the other;
    # a vent condenser's condensate to a stream of its own (ADR 0062) is no liquid outlet either
    vent = getattr(getattr(item, "batch", None), "vent", None)
    condenser = getattr(vent, "condenser", None)
    skip = set() if vent is None else {vent.stream}
    if condenser is not None and condenser.returns != "vessel":
        skip.add(condenser.returns)
    liquid_outs = [s for s in outs if s.id not in skip]
    t_liquid = [_state_value(process, s, case, "temperature") for s in liquid_outs]
    p_liquid = [_state_value(process, s, case, "pressure") for s in liquid_outs]
    t = t_liquid[0] if len(t_liquid) == 1 else None
    p = p_liquid[0] if len(p_liquid) == 1 else None
    if len(liquid_outs) == 1:
        with contextlib.suppress(ValueError):  # what is missing is reported below
            t, p = equilibrium_conditions(process.flowsheet.units, case, ins, liquid_outs[0])
    approach = getattr(item, "approach", 0.0) or 0.0
    if t is None:
        lacking.append("one outlet with a temperature")
    entries = []
    moles_out = [_moles(process, s, case) for s in outs]
    y = None
    moles_liquid = [_moles(process, s, case) for s in liquid_outs]
    if len(liquid_outs) == 1 and moles_liquid[0] is not None:
        total = sum(moles_liquid[0].values())
        y = {n: v / total for n, v in moles_liquid[0].items()} if total > 0 else None
    phi = None
    real_gas_unknown = False
    if getattr(item, "fugacity", "ideal") == "peng_robinson" and y and t is not None and p:
        from chemeascode.domains.chemistry.eos import fugacity_coefficients

        critical = {n: getattr(process.components().get(n), "critical", None) for n in y}
        try:
            # at the gas's outlet temperature, as propagate takes them
            phi = fugacity_coefficients(y, t, p, critical)
        except ValueError as failure:
            lacking.append(f"the fugacity coefficients: {failure}")
            real_gas_unknown = True
    liquid = None
    if any(r.phase == "liquid" for r in reactions):
        from chemeascode.domains.process.liquid_phase import liquid_of

        liquid = liquid_of(process)
    for reaction in reactions:
        on_liquid = liquid if reaction.phase == "liquid" else None
        basis = k_basis(reaction)
        entry: dict[str, Any] = {
            "id": reaction.id,
            "extent_kmol_h": balance.extents.get(reaction.id),
            "heat_of_reaction_kJ_kmol": None,
            "ln_k": None,
            "ln_q_over_k": None,
            "rate": None,
            "rate_unit": None,
        }
        names = list(reaction.stoichiometry)
        if t is not None:
            if not missing(names, data) and not outside(names, data, t):
                entry["heat_of_reaction_kJ_kmol"] = reaction_enthalpy(
                    reaction.stoichiometry, data, t
                )
            try:
                entry["ln_k"] = reaction_ln_k(reaction, data, t + approach, basis)
            except ValueError as failure:
                lacking.append(str(failure))
        # a real-gas reactor whose fugacities are not known has no ln(Q/K) (not the ideal one)
        known = (
            entry["ln_k"] is not None and y is not None and p is not None and not real_gas_unknown
        )
        liquid_known = entry["ln_k"] is not None and y is not None and on_liquid is not None
        if liquid_known and all(y.get(n, 0.0) > 0 for n in names):  # type: ignore[union-attr]
            from chemeascode.domains.chemistry.liquid import ln_quotient

            try:  # on the basis K is written on, the activities at the outlet temperature
                ln_q = ln_quotient(reaction.stoichiometry, basis, y, t, on_liquid)  # type: ignore[arg-type]
                entry["ln_q_over_k"] = ln_q - entry["ln_k"]
                entry["basis"] = basis
            except ValueError as failure:
                lacking.append(f"ln(Q/K) of {reaction.id}: {failure}")
        elif on_liquid is None and known and all(y.get(n, 0.0) > 0 for n in names):  # type: ignore[union-attr]
            ln_q = sum(
                nu * math.log(y[n] * p / P_STANDARD)  # type: ignore[index,operator]
                for n, nu in reaction.stoichiometry.items()
            )
            if phi is not None:  # on fugacities, as the reactor took its equilibrium
                ln_q += sum(
                    nu * math.log(phi.get(n, 1.0)) for n, nu in reaction.stoichiometry.items()
                )
            entry["ln_q_over_k"] = ln_q - entry["ln_k"]
        law = reaction.rate
        if law is not None and y is not None and t is not None and p is not None:
            if not law.covers(t):
                lacking.append(f"a temperature inside the rate's range of {reaction.id}")
            else:
                # the rate is at the outlet temperature (ln K too, not at T + approach)
                try:
                    k_out = (
                        reaction_ln_k(reaction, data, t, basis)
                        if law.reverse == "equilibrium"
                        else None
                    )
                    entry["rate"] = rate(
                        law, reaction.stoichiometry, y, t, p, k_out, on_liquid, basis
                    )
                    entry["rate_unit"] = (
                        "kmol/(kg s)" if law.basis == "catalyst_mass" else "kmol/(m3 s)"
                    )
                    if phi is not None and law.reverse == "equilibrium":
                        entry["rate_note"] = (
                            "(1 - Q/K) of the rate law on partial pressures, the equilibrium on "
                            "fugacities"
                        )
                except ValueError as failure:
                    lacking.append(f"the rate of {reaction.id}: {failure}")
        entries.append(entry)
    duty = None
    duty_assumptions: list[str] = []
    moles_in = [_moles(process, s, case) for s in ins]
    every = [m for m in moles_in + moles_out if m is not None]
    names = sorted({n for m in every for n in m})
    bare: list[str] = []  # inerts of a Gibbs reactor without ideal-gas data
    if getattr(item, "reactor", None) == "gibbs":
        with contextlib.suppress(ValueError):  # no formula: every species needs its data
            bare = missing(inert_species(names, process.formulas()), data)
    # an inert passes through: the same amount in and out, so its formation enthalpy cancels
    # and, without its heat capacity, only its sensible heat is not known
    counted_in = [m if m is None else _without(m, bare) for m in moles_in]
    counted_out = [m if m is None else _without(m, bare) for m in moles_out]
    if any(m is None for m in moles_in + moles_out):
        lacking.append("compositions and molar masses of its streams")
    elif None in t_in or None in t_out:
        lacking.append("the temperature of every stream")
    elif lack := missing([n for n in names if n not in bare], data):
        lacking.append("ideal_gas data for " + ", ".join(lack))
    elif beyond := [
        n
        for m, tt in zip(counted_in + counted_out, t_in + t_out, strict=True)
        for n in outside(list(m), data, tt)  # type: ignore[arg-type]
    ]:
        lacking.append(
            "a temperature inside the ideal_gas range of " + ", ".join(sorted(set(beyond)))
        )
    else:
        h_out = sum(mixture_enthalpy(m, data, tt) for m, tt in zip(counted_out, t_out, strict=True))  # type: ignore[arg-type]
        h_in = sum(mixture_enthalpy(m, data, tt) for m, tt in zip(counted_in, t_in, strict=True))  # type: ignore[arg-type]
        duty = h_out - h_in
        for name in bare:  # at one temperature throughout, its sensible heat is 0 exactly
            temperatures = {
                tt
                for m, tt in zip(moles_in + moles_out, t_in + t_out, strict=True)
                if m.get(name, 0.0) > 0  # type: ignore[union-attr]
            }
            if len(temperatures) > 1:
                duty_assumptions.append(
                    f"ASSUMED: the sensible heat of inert {name} is left out (no ideal_gas "
                    f"heat capacity), {min(temperatures):.6g} to {max(temperatures):.6g} K"
                )
    bed_entry = None
    if with_bed and getattr(item, "reactor", None) == "pfr":
        from chemeascode.domains.process.fixed_bed import BedError, solve_node

        try:
            if len(ins) != 1:
                raise BedError("a fixed bed takes one inlet stream")
            solved, _ = solve_node(process, item, ins[0], case)
            bed_entry = {
                "catalyst_mass_kg": solved.catalyst_mass,
                "catalyst_volume_m3": solved.catalyst_volume,
                "outlet_temperature_K": solved.temperature,
                "outlet_pressure_kPa": solved.pressure,
                "pressure_drop_kPa": solved.pressure_drop,
                "hot_spot_K": solved.hot_spot,
                "profile": [
                    {"catalyst_mass_kg": w, "temperature_K": tt, "pressure_kPa": pp}
                    for w, tt, pp in solved.profile
                ],
                "notes": solved.notes,
                "transport": solved.transport,
            }
        except BedError as failure:
            lacking.append(f"the bed: {failure}")
    tank_entry = None
    model_duty = None
    if with_bed and getattr(item, "reactor", None) in ("cstr", "batch", "semibatch"):
        from chemeascode.domains.process.stirred_tank import TankError, tank_inlet
        from chemeascode.domains.process.stirred_tank import solve_node as solve_tank

        try:
            solved_tank, _ = solve_tank(process, item, tank_inlet(item, ins), case)
            tank_entry = {
                "kind": solved_tank.kind,
                "volume_m3": solved_tank.volume,
                "time_s": solved_tank.time,
                "outlet_temperature_K": solved_tank.temperature,
                "outlet_pressure_kPa": solved_tank.pressure,
                "duty_kW": solved_tank.duty,
                "tanks": solved_tank.tanks,
                "heat_released_kJ_kmol": solved_tank.heat_released,
                "peak_heat_rate_kW_m3": solved_tank.peak_heat_rate,
                "profile": [
                    {"time_s": tt, "temperature_K": temp, "pressure_kPa": pp, "conversion": x}
                    for tt, temp, pp, x in solved_tank.profile
                ],
                "notes": solved_tank.notes,
            }
            if solved_tank.kind == "semibatch":
                tank_entry |= semibatch_entry(solved_tank)
            if vent is not None:
                tank_entry |= vent_entry(solved_tank, vent.stream)
            if item.reactor in ("batch", "semibatch"):
                model_duty = report_entry(
                    process, item, case, batch_duty(item, solved_tank, process, case)
                )
                if vent is not None and vent.condenser is not None:
                    # the vent condenser's duty on its own stream (ADR 0062)
                    tank_entry["vent"]["condenser_duty"] = report_entry(
                        process,
                        item,
                        case,
                        vent_condenser_duty(item, solved_tank),
                        vent_condenser=True,
                    )
        except TankError as failure:
            lacking.append(f"the {item.reactor}: {failure}")
    if with_bed and duty_model(item) == "conversion" and not process.inside(node):
        model_duty = report_entry(process, item, case, conversion_duty(process, item, case)[0])
    found = {
        "node": node,
        "kind": process.kinds.get(node),
        "bed": bed_entry,
        "tank": tank_entry,
        "model": _model(item),
        "balance": balance.status,
        "streams_in": balance.streams_in,
        "streams_out": balance.streams_out,
        "temperature_out_K": t,
        "pressure_out_kPa": p,
        "approach_K": approach,
        "fugacity": getattr(item, "fugacity", "ideal"),
        "reactions": entries,
        "duty_kW": duty,
        "duty_assumptions": duty_assumptions,
        "duty_basis": (
            "ideal gas: the heats of vaporization of the components the liquid-phase "
            "reactions change are not included"
            if liquid is not None
            else "ideal gas"
        ),
        "missing": lacking,
    }
    # ADR 0059: only where the model knows a duty or a stream wants one; other reactors'
    # entries stay as they were
    if model_duty is not None and (
        model_duty["heat_in_kW"] is not None
        or model_duty["stream"] is not None
        or model_duty["stream_note"]
    ):
        found["model_duty"] = model_duty
    return found


def reactor_report(root: Path, case: str | None = None) -> ReactorReport:
    """Every reactor of the plant repository at *root* in *case* (default: the default case).
    Raises :class:`NotAPlantRepository` and :class:`UnknownCase`; a process that does not load
    is reported through ``findings`` (``loaded`` False)."""
    from chemeascode.domains.process.model import load

    root = Path(root)
    if not (root / PLANT_FILE).is_file():
        raise NotAPlantRepository(f"No {PLANT_FILE} in {root}.")
    source = source_revision(root, REPORT_INPUTS)
    process, findings = load(root)
    report = ReactorReport(root, None, process, findings, source=source)
    if not report.loaded:
        return report
    assert process is not None
    case = case or process.flowsheet.default_case()
    if case not in {c.id for c in process.flowsheet.cases}:
        raise UnknownCase(f"unknown case {case!r}")
    report.case = case
    fs = process.flowsheet
    report.reactors = [
        reactor_entry(process, n.id, case)
        for n in [*fs.blocks, *fs.steps]
        if process.reactive(n.id)
    ]
    return report


def reactor_text(report: ReactorReport) -> str:
    """The report as ``cheme process reactors`` prints it."""

    def num(v: float | None, unit: str = "", fmt: str = ".6g") -> str:
        return "?" if v is None else f"{v:{fmt}}{unit}"

    lines = []
    for r in report.reactors:
        lines.append(
            f"{r['kind']} {r['node']} ({r['model'] or 'holds reactors'}): balance {r['balance']}; "
            f"T out {num(r['temperature_out_K'], ' K')}, P out {num(r['pressure_out_kPa'], ' kPa')}"
            + (f", approach {r['approach_K']:g} K" if r["approach_K"] else "")
            + f"; duty {_duty_shown(r, num)}"
            + "".join(f" ({note})" for note in r.get("duty_assumptions", []))
        )
        for e in r["reactions"]:
            lines.append(
                f"  {e['id']}: extent {num(e['extent_kmol_h'], ' kmol/h')}, "
                f"dHr {num(e['heat_of_reaction_kJ_kmol'], ' kJ/kmol')}, ln K {num(e['ln_k'])}, "
                f"ln(Q/K) {num(e['ln_q_over_k'], fmt='.3g')}"
                + (f", rate {e['rate']:.4g} {e['rate_unit']}" if e["rate"] is not None else "")
            )
        bed = r.get("bed")
        if bed:
            lines.append(
                f"  bed: {bed['catalyst_mass_kg']:.6g} kg catalyst "
                f"({bed['catalyst_volume_m3']:.4g} m3), "
                f"outlet {bed['outlet_temperature_K']:.6g} K, "
                f"pressure drop {bed['pressure_drop_kPa']:.4g} kPa, "
                f"hot spot {bed['hot_spot_K']:.6g} K"
                + (f"; {'; '.join(bed['notes'])}" if bed["notes"] else "")
            )
        tank = r.get("tank")
        if tank and tank["kind"] == "cstr":
            last = tank["tanks"][-1] if tank["tanks"] else {}
            conversion = ", ".join(f"{n} {x:.4g}" for n, x in last.get("conversion", {}).items())
            lines.append(
                f"  cstr: {len(tank['tanks'])} x {tank['volume_m3']:.4g} m3, space time "
                f"{tank['time_s']:.4g} s each, outlet {tank['outlet_temperature_K']:.6g} K, "
                f"duty {num(tank['duty_kW'], ' kW')}; conversion {conversion or 'none'}"
                + (f"; {'; '.join(tank['notes'])}" if tank["notes"] else "")
            )
        elif tank:
            end = tank["profile"][-1]["conversion"] if tank["profile"] else 0.0
            heat = tank["heat_released_kJ_kmol"]
            semi = tank["kind"] == "semibatch"
            lines.append(
                f"  {tank['kind']}: {tank['time_s']:.6g} s to conversion {end:.4g}, outlet "
                f"{tank['outlet_temperature_K']:.6g} K"
                + (
                    f", heat released {heat:.6g} kJ/kmol of charge{' and doses' if semi else ''}"
                    if heat is not None
                    else ""
                )
                + (f"; {'; '.join(tank['notes'])}" if tank["notes"] and not semi else "")
            )
            if tank.get("vent"):
                gas = tank["vent"]
                lines.append(
                    f"    vent {gas['stream']}: "
                    + ", ".join(f"{n} {v:.4g}" for n, v in gas["kmol_h"].items())
                    + " kmol/h; peak "
                    + num(gas["peak_rate_kmol_s_m3"], " kmol/(s m3)", ".4g")
                    + (f" at {gas['peak_time_s']:.6g} s" if gas["peak_time_s"] is not None else "")
                )
                lines += _vent_lines(gas)
            if semi:
                worst = tank["cooling_failure"]
                x = tank["max_accumulation"]
                lines.append(
                    f"    dosing {tank['dosing_time_s']:.6g} s; accumulation of the dosed "
                    + (
                        f"reactant at most {x:.3g} (at {tank['max_accumulation_time_s']:.6g} s)"
                        if x is not None
                        else "reactant unknown"
                    )
                    + (
                        f"; cooling failure at worst {worst['mtsr_K']:.6g} K "
                        f"(at {worst['time_s']:.6g} s)"
                        if worst
                        else ""
                    )
                    + f"; peak cooling duty {num(tank['peak_cooling_duty_kW_m3'], ' kW/m3')}"
                    + (f"; {'; '.join(tank['notes'])}" if tank["notes"] else "")
                )
        if r.get("model_duty"):
            lines += report_lines(r["model_duty"])
        if r["missing"]:
            lines.append("  missing: " + "; ".join(dict.fromkeys(r["missing"])))
    if not report.reactors:
        lines.append("no reactors (no block or step names reactions or a reactor model)")
    return "\n".join(lines)


def _vent_lines(gas: dict[str, Any]) -> list[str]:
    """The lines of a vent's vapour, condenser and Henry split (ADR 0062)."""
    lines = []
    if gas.get("vapour_kmol_h"):
        share = gas.get("vapour_share")
        lines.append(
            "      vapour carried off the liquid: "
            + ", ".join(f"{n} {v:.4g}" for n, v in gas["vapour_kmol_h"].items())
            + " kmol/h"
            + (f" (the vapour {share:.3g} of the gas over the liquid at the end)" if share else "")
        )
    if gas.get("condensate_kmol_h"):
        lines.append(
            f"      condenser at {gas['temperature_K']:.6g} K condenses "
            + ", ".join(f"{n} {v:.4g}" for n, v in gas["condensate_kmol_h"].items())
            + " kmol/h"
        )
    if gas.get("condenser_duty"):
        lines += ["    " + line for line in report_lines(gas["condenser_duty"])]
    for n, h in (gas.get("henry") or {}).items():
        lines.append(
            f"      {n} dissolved {h['dissolved_kmol_h']:.4g} kmol/h "
            f"(x {h['solubility_mole_fraction']:.4g} "
            f"at {h['partial_pressure_kPa']:.4g} kPa, H {h['henry_kPa']:.4g} kPa), "
            f"{h['share_vented']:.4g} of what formed vented; {h['state']}"
        )
    return lines


def _duty_shown(r: dict[str, Any], num: Any) -> str:
    """The header's duty: the ideal-gas H(out) - H(in), else the model's year-average duty
    (ADR 0059), else ?."""
    model = (r.get("model_duty") or {}).get("heat_in_kW")
    if r["duty_kW"] is None and model is not None:
        return f"{model:.6g} kW ({r['model_duty']['model']} model, year average)"
    return num(r["duty_kW"], " kW")


def vent_entry(solved: Any, stream: str) -> dict[str, Any]:
    """What ``process reactors`` adds for a vented batch or semi-batch (ADR 0054): what left by
    the vent (kmol/h, the flowsheet's basis) and its peak rate per m3 of the content at the end,
    for sizing the off-gas line and its scrubber (per batch: ``cheme process recipe``). With
    the vent's vapour, condenser or Henry split (ADR 0062) also what the gas carried off the
    liquid, what the condenser condensed, the vent's temperature and each gas's solubility."""
    found: dict[str, Any] = {
        "stream": stream,
        "kmol_h": dict(solved.vent),
        "peak_rate_kmol_s_m3": solved.peak_vent_rate,
        "peak_time_s": solved.peak_vent_time,
    }
    if solved.vapour:
        found["vapour_kmol_h"] = dict(solved.vapour)
        found["vapour_share"] = solved.vapour_share
        found["temperature_K"] = solved.vent_temperature
    if solved.condensate:
        found["condensate_kmol_h"] = dict(solved.condensate)
    if solved.henry:
        found["henry"] = {n: dict(v) for n, v in solved.henry.items()}
    return {"vent": found}


def semibatch_entry(solved: Any) -> dict[str, Any]:
    """What ``process reactors`` adds for a semi-batch (:func:`.stirred_tank.solve_batch`):
    the dosing, the accumulation of the dosed reactant, the worst cooling failure and the peak
    cooling duty."""
    worst = solved.cooling_failure
    return {
        "dosing_time_s": solved.dosing_time,
        "charge_volume_m3": solved.charge_volume,
        "max_accumulation": solved.max_accumulation,
        "max_accumulation_time_s": solved.max_accumulation_time,
        "cooling_failure": (
            {"time_s": worst[0], "temperature_K": worst[1], "mtsr_K": worst[2]} if worst else None
        ),
        "peak_cooling_duty_kW_m3": solved.peak_cooling_duty,
        "accumulation": [{"time_s": t, "accumulation": x} for t, x in solved.accumulation],
    }
