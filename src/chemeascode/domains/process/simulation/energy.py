"""Energy checks of a solved simulation, independent of the simulator's own duty balance.

``cheme process simulate`` runs them on every converged result (:func:`audit`); the record
(``process/simulation-run.json``) keeps the audit under ``energy``. Rules
(``cheme.process-*``):

- ``sim-temperature-cross`` (warning): a two-stream or multi-stream exchanger whose hot and cold
  composite curves cross. The composites are built from the solved inlet and outlet
  temperatures and each stream's duty, counter-current, each stream at a constant heat capacity
  flow (:func:`chemeascode.domains.process.heat_integration.pinch.minimum_approach`). The
  simulator closes the exchanger's energy balance (DWSIM's heat exchanger; the multi-stream
  exchanger expanded into heaters); that alone does not show its temperatures are feasible.
- ``sim-exchanger-approach`` (warning): the least approach is below the declared ``min_approach``
  (the spec's, else the simulation's); ``sim-approach-undeclared`` (info): none is declared, so
  only crosses are reported.
- ``sim-exchanger-zones`` (info): a stream changes phase in the exchanger (its vapour fraction
  differs between inlet and outlet, or it leaves or enters two-phase). The simulator reports no
  zone or intermediate temperatures, so the internal approach is not checked: only the
  composites at constant heat capacity flow (exact at the terminals).
- ``sim-utility-level`` (warning): a heater, cooler, flash, reactor, column condenser or reboiler
  whose energy stream comes from (or goes to) a utility terminal with declared temperatures
  (``utility:`` on the terminal) cannot be served by it: the utility's supply/return
  temperatures cross the process side, or come closer than the utility's ``min_approach``.
- ``sim-energy-unbalanced`` (warning): a unit, or the simulated plant as a whole, whose stream
  enthalpy flows do not close with its heat and shaft work within :data:`ENERGY_TOLERANCE`.
- ``sim-energy-unsupported`` (info): the closure is not evaluated where the enthalpy reference
  does not allow it: a reactor whose property package's reference is not verified
  (:data:`FORMATION_PACKAGES`) or for which DWSIM's formation enthalpies were not reported, or a
  unit whose duty sign is not established (the component separator's energy imbalance, a
  column top without condenser).
- ``sim-energy-not-evaluable`` (info): the simulator returned no stream enthalpies (a record from
  before they were reported).
- ``sim-formation-data``: the reaction heat DWSIM simulates (its database's formation
  enthalpies) against the project's, judged on the data (:data:`DATA_TOLERANCE` of the
  reaction heat): a warning where values declared in process/materials.yaml differ beyond it;
  info listing the limitations otherwise (a nonzero difference within it, chemicals' fallback
  values that differ, a reacting component without a project value).

The enthalpies are the simulator's (``mass_enthalpy_kJ_kg``, DWSIM's own reference); they are
compared only with each other in one run, never with ``cheme process props`` values (thermo,
:data:`chemeascode.domains.process.props.ENTHALPY_REFERENCE`).

Reacting units (:data:`REACTORS`) close on a heat-of-formation basis. In DWSIM 9.0.5 with the
packages of :data:`FORMATION_PACKAGES` a stream's enthalpy is each component's ideal gas at
298.15 K = 0, without formation enthalpies: a conversion reactor isothermal at 298.15 K and
1 kPa has stream enthalpies near 0 and its duty is the formation term alone, for each of these
packages; with NRTL the stream enthalpies there are far from 0, so NRTL is not on this basis
(tests/test_process_simulate_energy.py). A liquid's enthalpy is its equation of state's
departure from that ideal gas (about minus its heat of vaporization at 298.15 K): DWSIM's pure
liquids agree with thermo's departure functions within 0.7 % for each of these packages, so
liquid streams are on the same basis and need no correction of their own
(tests/test_process_simulate_energy_liquid.py). The elements basis is then the stream's
enthalpy flow plus ``sum n_i dHf_i`` (ideal gas, 298.15 K); for a unit the formation term is
``sum (n_i,out - n_i,in) dHf_i`` over the components its reactions name whose flow changes (a
component no reaction names is taken as unchanged: what a recycle's tolerance leaves of it is
no reaction).

The closure is judged on DWSIM's own formation enthalpies (its compound database, which the
worker reports), which its reactor duty takes: it tests the simulation's energy conservation.
With them the closure reproduces DWSIM's duty to within 1e-3 kW for its conversion,
equilibrium and Gibbs reactors (ammonia synthesis, vapour, 10 bar, Peng-Robinson) and for the
conversion reactor with PR78 and SRK (the live tests assert 1e-2 kW), and for a liquid-phase
conversion reactor with each of the three (MTBE synthesis, 298.15 K, 2000 kPa). That liquid
reaction heat under Peng-Robinson, -33.1 kJ/mol against -65.5 as ideal gas, lies within 2 % of
a calorimetric value and 7 % of one from liquid formation enthalpies, but about 17 % from a
second calorimetric value (published values span -33.8 to -39.8 kJ/mol). The project's formation
enthalpies (``ideal_gas.dHf_298`` declared in process/materials.yaml with its provenance and
source, else chemicals' as a fallback, ``integrations.thermo.ideal_gas_formation``, its method
recorded) are compared with DWSIM's separately (``formation_data`` on each reactor row,
``sim-formation-data``): a simulated reaction heat that disagrees with the project's sourced
data is a finding of its own, not an energy imbalance. A kinetic_pfr's duty is DWSIM's duty of
the conversion reactor it is coupled as (:mod:`.coupling`): its closure is that conversion
reactor's, between the streams DWSIM solved; the bed's own ideal-gas energy balance is the
coupling's (``energy_residual_kW``). With a reactor in the plant the plant closure is on the
formation basis too (``sum (n_i,products - n_i,feeds) dHf_i`` over the reacting components).

The audit also classifies every duty once (``utilities``): hot and cold utility, power, and heat
recovered between process streams (two-stream exchangers with no utility side, the internal
part of a multi-stream exchanger, a condenser-reboiler). Recovered heat is never also counted as
utility.
"""

from __future__ import annotations

from typing import Any

from chemeascode.domains.process import MATERIALS_FILE
from chemeascode.domains.process.energy import ENERGY_TOLERANCE, tolerance
from chemeascode.domains.process.heat_integration.pinch import (
    PinchStream,
    Segment,
    minimum_approach,
)
from chemeascode.domains.process.simulation import SIMULATION_FILE
from chemeascode.domains.process.simulation.backends import IDAES_PACKAGES
from chemeascode.foundation.findings import Finding
from chemeascode.foundation.units import to_kelvin
from chemeascode.foundation.yamlsource import _yaml_line

#: The basis the closure uses, as the record states it.
REFERENCE = {
    "source": "simulator (DWSIM mass enthalpy, kJ/kg, its own reference state)",
    "formation_enthalpy_included": False,
    "comparable_with": "values of the same run only",
    "formation_basis": (
        "reacting units, and the plant with a reactor: plus sum n_i dHf_i (ideal gas, 298.15 K, "
        "DWSIM's database) of the reacting components whose flow changes (energy.formation)"
    ),
}
#: DWSIM property packages whose stream enthalpy is verified (DWSIM 9.0.5, live tests in
#: tests/test_process_simulate_energy.py) to be each component's ideal gas at 298.15 K = 0
#: without formation enthalpies, a liquid below it by its departure function
#: (tests/test_process_simulate_energy_liquid.py): the reacting closure's basis. NRTL is shown
#: not to be; the others (UNIQUAC, steam tables, CoolProp) are not verified.
FORMATION_PACKAGES = (
    "Peng-Robinson (PR)",
    "Peng-Robinson 1978 (PR78)",
    "Soave-Redlich-Kwong (SRK)",
)
#: The project's formation data against DWSIM's, judged on the data, not on a reactor's duty
#: (which an adiabatic reactor does not have): ``max(rel_reaction_heat x |formation term|,
#: abs_kW)``. 1 % of the reaction heat is about the spread between authoritative compilations:
#: ammonia's dHf_298 is -45558 kJ/kmol in ATcT (chemicals' ATCT_G) and -45898 kJ/kmol in
#: NIST-JANAF (Chase 1998; DWSIM's ChemSep value), 0.74 % of the synthesis heat. A nonzero
#: difference below it is recorded as a limitation, above it with declared values it fails.
DATA_TOLERANCE = {"rel_reaction_heat": 0.01, "abs_kW": 0.1}
#: A reacting component's molar flow change below this fraction of the flows through the unit
#: (or the plant) is none.
SMALL_DN = 1e-9
#: Temperature differences below this are taken as no change (K); vapour fractions below
#: this as no phase change.
SMALL_DT = 1e-6
SMALL_VF = 1e-4
#: Reacting units (a kinetic_pfr is solved by cheme-as-code and seen by DWSIM as a conversion
#: reactor: it reacts all the same).
REACTORS = ("conversion_reactor", "equilibrium_reactor", "gibbs_reactor", "kinetic_pfr")
#: Units whose single duty heats or cools one process stream (inlet 0 to outlet 0).
HEATED = ("heater", "cooler", "flash", *REACTORS)


def _finding(level: str, rule: str, message: str, line: int | None, ids: list[str], hint: str):
    return Finding(
        SIMULATION_FILE, level, f"cheme.process-{rule}", message, line=line, ids=ids, hint=hint
    )


def _flow(out: dict[str, Any], sid: str) -> dict[str, Any]:
    return (out.get("streams") or {}).get(sid) or {}


def _enthalpy_flow(out: dict[str, Any], sid: str) -> float | None:
    """kW (kg/s times kJ/kg) of stream *sid*, or None without both."""
    s = _flow(out, sid)
    m, h = s.get("mass_flow_kg_s"), s.get("mass_enthalpy_kJ_kg")
    return None if m is None or h is None else m * h


def _phase_changes(out: dict[str, Any], a: str, b: str) -> bool:
    va, vb = _flow(out, a).get("vapor_fraction"), _flow(out, b).get("vapor_fraction")
    if va is None or vb is None:
        return False
    two_phase = any(SMALL_VF < v < 1 - SMALL_VF for v in (va, vb))
    return two_phase or abs(va - vb) > SMALL_VF


def _side(t_in: float, t_out: float, duty: float, name: str, side: str | None = None):
    """A pinch stream for one exchanger side: constant heat capacity flow, or an isothermal
    load (temperatures equal) on *side*."""
    if abs(t_in - t_out) <= SMALL_DT:
        return PinchStream.piecewise([Segment.latent(t_in, duty)], name, side=side)  # type: ignore[arg-type]
    return PinchStream(t_in, t_out, duty / abs(t_in - t_out), name)


def _delta_k(q: Any) -> float | None:
    if q is None:
        return None
    return q.value if (q.unit or "K") in ("K", "°C") else None


def _ends(process: Any) -> dict[str, str]:
    """Stream id -> the terminal at its other end (feed or product id)."""
    fs = process.flowsheet
    feeds = {t.id for t in fs.feeds}
    products = {t.id for t in fs.products}
    found = {}
    for s in fs.streams:
        a, b = s.from_.split(".")[0], s.to.split(".")[0]
        if a in feeds:
            found[s.id] = a
        elif b in products:
            found[s.id] = b
    return found


def _terminals(process: Any) -> dict[str, Any]:
    fs = process.flowsheet
    return {t.id: t for t in [*fs.feeds, *fs.products]}


def audit(
    process: Any,
    sim: Any,
    sim_doc: Any,
    model: dict[str, Any],
    out: dict[str, Any],
) -> tuple[list[Finding], dict[str, Any], list[str]]:
    """The energy checks of one converged run: findings, the audit for the record and the
    summary lines. *out* is the simulator's result with the units as ``run`` reports them
    (``shaft_kW`` where a drive efficiency is given)."""
    findings: list[Finding] = []
    units = out.get("units") or {}
    ends = _ends(process)
    terminals = _terminals(process)
    temps = process.flowsheet.units.temperature

    def line(unit: str, *key: str) -> int | None:
        return _yaml_line(sim_doc, ["specs", unit, *key]) if unit in sim.specs else None

    exchangers = _exchangers(process, sim, model, out, units, ends, terminals, line)
    findings += exchangers.pop("findings")
    levels, found = _utility_levels(model, out, units, ends, terminals, temps, line)
    findings += found
    formation = (
        _formation_data(process, model, out)
        if any(u["type"] in REACTORS for u in model["units"])
        else None
    )
    closure, found = _closure(model, out, units, line, formation)
    findings += found
    utilities = _utilities(model, out, units, ends, terminals)
    lines = []
    for row in closure["units"]:
        if row.get("basis") == "formation":
            lines.append(
                f"energy closure ({row['id']}, formation basis): {row['status']}, residual "
                f"{row['residual_kW']:.4g} kW (tolerance {row['tolerance_kW']:.4g} kW)"
            )
    plant = closure["plant"]
    if plant["status"] in ("ok", "imbalance"):
        lines.append(
            f"energy closure (plant): {plant['status']}, residual {plant['residual_kW']:.4g} kW "
            f"(tolerance {plant['tolerance_kW']:.4g} kW)"
        )
    else:
        lines.append(f"energy closure (plant): {plant['status']} ({'; '.join(plant['reasons'])})")
    totals = utilities["totals_kW"]
    lines.append(
        "utilities: hot {hot:.4g} kW, cold {cold:.4g} kW, power in {pin:.4g} kW, power out "
        "{pout:.4g} kW; recovered between process streams {rec:.4g} kW".format(
            hot=totals["hot_utility"],
            cold=totals["cold_utility"],
            pin=totals["power_in"],
            pout=totals["power_out"],
            rec=totals["recovered"],
        )
    )
    entry = {
        "reference": dict(REFERENCE),
        "tolerance": dict(ENERGY_TOLERANCE),
        "closure": closure,
        "formation": formation,
        "exchangers": exchangers["rows"],
        "utility_levels": levels,
        "utilities": utilities,
    }
    return findings, entry, lines


# -- exchanger temperatures ---------------------------------------------------------------------


def _exchangers(process, sim, model, out, units, ends, terminals, line) -> dict[str, Any]:
    findings: list[Finding] = []
    rows = []
    for u in model["units"]:
        kind = u["type"]
        if kind not in ("heat_exchanger", "multi_stream_exchanger"):
            continue
        uid = u["id"]
        got = units.get(uid) or {}
        spec = sim.specs.get(uid)
        declared = _delta_k(getattr(spec, "min_approach", None)) or _delta_k(sim.min_approach)
        row: dict[str, Any] = {"id": uid, "unit": kind, "min_approach_K": declared}
        sides = []
        lacking = []
        if kind == "heat_exchanger":
            q = abs(got.get("duty_kW") or 0.0)
            duties = []
            for a, b in zip(u["inlets"], u["outlets"], strict=False):
                ha, hb = _enthalpy_flow(out, a), _enthalpy_flow(out, b)
                duties.append(abs(hb - ha) if ha is not None and hb is not None else q)
        else:
            duties = [abs(d) for d in got.get("side_duties_kW") or []]
            if len(duties) != len(u["inlets"]):
                duties = []
                for a, b in zip(u["inlets"], u["outlets"], strict=False):
                    ha, hb = _enthalpy_flow(out, a), _enthalpy_flow(out, b)
                    duties.append(None if ha is None or hb is None else abs(hb - ha))
        changing = []
        for k, (a, b) in enumerate(zip(u["inlets"], u["outlets"], strict=False)):
            t_in, t_out = _flow(out, a).get("temperature_K"), _flow(out, b).get("temperature_K")
            duty = duties[k] if k < len(duties) else None
            if t_in is None or t_out is None or duty is None:
                lacking.append(a)
                continue
            if duty <= 1e-9:
                continue  # a stream that exchanges nothing
            sides.append((a, t_in, t_out, duty))
            if _phase_changes(out, a, b):
                changing.append(a)
        if lacking:
            row["status"] = "not-evaluable"
            row["missing"] = lacking
            rows.append(row)
            continue
        streams = []
        moving = [s for s in sides if abs(s[1] - s[2]) > SMALL_DT]
        for a, t_in, t_out, duty in sides:
            if abs(t_in - t_out) > SMALL_DT:
                streams.append(_side(t_in, t_out, duty, a))
                continue
            # isothermal: the opposite side of the streams that do change temperature
            hot = any(s[1] < s[2] for s in moving) and not any(s[1] > s[2] for s in moving)
            streams.append(_side(t_in, t_out, duty, a, "hot" if hot else "cold"))
        try:
            found = minimum_approach(streams)
        except ValueError as failure:
            row["status"] = "not-evaluable"
            row["missing"] = [str(failure)]
            rows.append(row)
            continue
        utility_sides = [a for a in u["inlets"] if _is_utility(a, ends, terminals)]
        row.update(
            status="crossed" if found.crossed else "ok",
            approach_K=round(found.minimum, 6),
            at={
                "hot_K": round(found.hot_temperature, 6),
                "cold_K": round(found.cold_temperature, 6),
                "heat_kW": round(found.heat, 6),
            },
            phase_change=changing,
            utility_sides=utility_sides,
        )
        where = line(uid) or line(uid, "min_approach")
        if found.crossed:
            findings.append(
                _finding(
                    "warning",
                    "sim-temperature-cross",
                    f"{uid}: the hot and cold sides cross by {-found.minimum:.3g} K (hot "
                    f"{found.hot_temperature:.2f} K against cold {found.cold_temperature:.2f} K, "
                    f"{found.heat:.4g} kW from the cold end, counter-current)",
                    where,
                    [uid],
                    "the energy balance closes but no counter-current exchanger can do this: "
                    "change the outlet temperature specs or split the duty",
                )
            )
        elif declared is not None and found.minimum < declared:
            row["status"] = "below-min-approach"
            findings.append(
                _finding(
                    "warning",
                    "sim-exchanger-approach",
                    f"{uid}: least approach {found.minimum:.3g} K (hot {found.hot_temperature:.2f} "
                    f"K, cold {found.cold_temperature:.2f} K) is below min_approach "
                    f"{declared:g} K",
                    where,
                    [uid],
                    "relax the outlet temperature specs, or review min_approach",
                )
            )
        if declared is None:
            findings.append(
                _finding(
                    "info",
                    "sim-approach-undeclared",
                    f"{uid}: least approach {found.minimum:.3g} K; no min_approach declared, "
                    "only temperature crosses are checked",
                    where,
                    [uid],
                    f"give specs.{uid}.min_approach (or min_approach for all exchangers) in "
                    f"{SIMULATION_FILE}",
                )
            )
        if changing:
            findings.append(
                _finding(
                    "info",
                    "sim-exchanger-zones",
                    f"{uid}: {', '.join(changing)} change phase; the internal approach is not "
                    "checked (no zone temperatures), only the composites at constant heat "
                    "capacity flow",
                    where,
                    [uid],
                    "check the zones (condensing, boiling) in a rating tool or split the "
                    "exchanger at the phase change",
                )
            )
        rows.append(row)
    return {"findings": findings, "rows": rows}


def _is_utility(stream: str, ends: dict[str, str], terminals: dict[str, Any]) -> bool:
    terminal = terminals.get(ends.get(stream, ""))
    return getattr(terminal, "category", None) == "utility"


# -- utility levels -----------------------------------------------------------------------------


def _energy_terminal(u: dict[str, Any], role: str, ends, terminals) -> Any:
    stream = (u.get("energies") or {}).get(role)
    return terminals.get(ends.get(stream or "", "")), stream


def _utility_levels(model, out, units, ends, terminals, temps, line):
    """Each duty served by a utility terminal with declared temperatures, checked."""
    findings: list[Finding] = []
    rows = []
    for u in model["units"]:
        uid, kind = u["id"], u["type"]
        got = units.get(uid) or {}
        duties = []  # (role, process side as a pinch stream, utility is hot)
        if kind in HEATED and u["inlets"] and u["outlets"]:
            q = got.get("duty_kW")
            t_in = _flow(out, u["inlets"][0]).get("temperature_K")
            t_out = _flow(out, u["outlets"][0]).get("temperature_K")
            if q and t_in is not None and t_out is not None:
                heated = q > 0
                process = _side(t_in, t_out, abs(q), uid, "cold" if heated else "hot")
                duties.append(("energy", process, heated))
        elif kind == "distillation_column":
            top, bottom = got.get("top_temperature_K"), got.get("bottom_temperature_K")
            if got.get("condenser_kW") and top is not None:
                duties.append(
                    ("condenser", _side(top, top, got["condenser_kW"], uid, "hot"), False)
                )
            if got.get("reboiler_kW") and bottom is not None:
                duties.append(
                    ("reboiler", _side(bottom, bottom, got["reboiler_kW"], uid, "cold"), True)
                )
        for role, process, heated in duties:
            terminal, stream = _energy_terminal(u, role, ends, terminals)
            level = getattr(terminal, "utility", None)
            if level is None or level.supply_temperature is None:
                continue
            supply = to_kelvin(
                level.supply_temperature.value, level.supply_temperature.unit or temps
            )
            ret = level.return_temperature
            back = to_kelvin(ret.value, ret.unit or temps) if ret is not None else supply
            if supply is None or back is None:
                continue
            need = _delta_k(level.min_approach) or 0.0
            utility = _side(supply, back, process.duty, terminal.id, "hot" if heated else "cold")
            row = {
                "id": uid,
                "role": role,
                "terminal": terminal.id,
                "utility": level.kind,
                "supply_K": supply,
                "return_K": back,
                "min_approach_K": need,
            }
            try:
                found = minimum_approach([process, utility])
            except ValueError as failure:
                # the utility runs the wrong way for the duty (e.g. heats while it should cool)
                row.update(status="infeasible", reason=str(failure))
                findings.append(
                    _finding(
                        "warning",
                        "sim-utility-level",
                        f"{uid} ({role}): {terminal.id} ({level.kind}, {supply:.2f} -> "
                        f"{back:.2f} K) cannot {'heat' if heated else 'cool'} it",
                        line(uid),
                        [uid, terminal.id],
                        f"check {terminal.id}'s supply and return temperatures, or serve the "
                        "duty from another utility",
                    )
                )
                rows.append(row)
                continue
            row.update(approach_K=round(found.minimum, 6))
            if found.minimum < need or found.crossed:
                row["status"] = "infeasible"
                findings.append(
                    _finding(
                        "warning",
                        "sim-utility-level",
                        f"{uid} ({role}): {terminal.id} ({level.kind}, {supply:.2f} -> "
                        f"{back:.2f} K) comes within {found.minimum:.3g} K of the process side "
                        f"({found.cold_temperature if heated else found.hot_temperature:.2f} K)"
                        + (f", less than its min_approach {need:g} K" if need else ""),
                        line(uid),
                        [uid, terminal.id],
                        "use a hotter (or colder) utility level, or change the process "
                        "temperatures",
                    )
                )
            else:
                row["status"] = "ok"
            rows.append(row)
    return rows, findings


# -- energy closure -----------------------------------------------------------------------------


def _exchange(kind: str, got: dict[str, Any]) -> tuple[float, float, str]:
    """(heat into the process kW, shaft work into it kW, why not evaluable) of one unit."""
    if kind in ("compressor", "pump"):
        work = got.get("shaft_kW", got.get("duty_kW")) or 0.0
        cooling = abs(got.get("cooling_kW") or 0.0)  # intercooled compressor
        return -cooling, work, ""
    if kind == "expander":
        return 0.0, -(got.get("shaft_kW", got.get("duty_kW")) or 0.0), ""
    if kind in HEATED:
        return got.get("duty_kW") or 0.0, 0.0, ""
    if kind == "multi_stream_exchanger":
        return got.get("imbalance_kW") or 0.0, 0.0, ""
    if kind in ("distillation_column", "shortcut_column"):
        if abs(got.get("top_residual_kW") or 0.0) > ENERGY_TOLERANCE["abs_kW"]:
            return 0.0, 0.0, "the sign of the column top's residual duty is not established"
        return (got.get("reboiler_kW") or 0.0) - (got.get("condenser_kW") or 0.0), 0.0, ""
    if kind == "component_separator":
        return 0.0, 0.0, "the sign of the component separator's energy imbalance is not established"
    return 0.0, 0.0, ""  # heat_exchanger, valve, mixer, splitter: no external exchange


def _tolerance(q: float, w: float, h_in: float, h_out: float) -> float:
    return tolerance(abs(q) + abs(w), h_in, h_out)


def _formation_data(process: Any, model: dict[str, Any], out: dict[str, Any]) -> dict[str, Any]:
    """The formation enthalpies of the model's compounds: DWSIM's own (the worker reports its
    database's; the closure's basis) and the project's (declared in materials, else chemicals'
    as a fallback; compared with DWSIM's), each with its source, and whether the property
    package's reference is verified."""
    simulator = out.get("compounds") or {}
    package = model.get("property_package")
    components = _project_formation(process, model.get("compounds") or [])
    for cid, row in components.items():
        theirs = simulator.get(cid) or {}
        row["simulator_dHf_298_kJ_kmol"] = theirs.get("dHf_298_kJ_kmol")
        row["simulator_database"] = theirs.get("database") or None
        row["molar_mass"] = row["molar_mass"] or theirs.get("molar_mass")
    return {
        "property_package": package,
        "reference_verified": package in FORMATION_PACKAGES,
        "reference": (
            "each component's ideal gas at 298.15 K = 0, without formation enthalpies, a "
            "liquid below it by its departure function "
            f"(verified live for DWSIM 9.0.5: {', '.join(FORMATION_PACKAGES)})"
        ),
        "closure_basis": "DWSIM's formation enthalpies (simulator_dHf_298_kJ_kmol)",
        "components": components,
    }


def _project_formation(process: Any, compounds: list[dict[str, Any]]) -> dict[str, Any]:
    """Compound id -> the project's formation enthalpy as materials says it now: declared
    (``ideal_gas.dHf_298``, provenance and source), else chemicals' fallback, else why there is
    none (``missing``); with the declared molar mass."""
    materials = getattr(process, "materials", None)
    declared = {c.id: c for c in (getattr(materials, "components", None) or [])}
    found: dict[str, Any] = {}
    for c in compounds:
        comp = declared.get(c["id"])
        ig = getattr(comp, "ideal_gas", None)
        row: dict[str, Any] = {"dHf_298_kJ_kmol": None, "source": None, "origin": None}
        if ig is not None:
            row["dHf_298_kJ_kmol"] = ig.dHf_298
            row["origin"] = "declared"
            row["source"] = f"declared in {MATERIALS_FILE} ({ig.provenance}" + (
                f"; {ig.source})" if ig.source else ")"
            )
        else:
            row.update(_chemicals_formation(c))
        row["molar_mass"] = getattr(comp, "molar_mass", None)
        found[c["id"]] = row
    return found


def recompare(process: Any, audit: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Reactor id -> its formation-data comparison (:func:`_compare`) recomputed from a recorded
    audit's simulator values (DWSIM's formation enthalpies, each reactor's component changes
    and formation term) against the project's formation enthalpies in materials now. The
    declared values are not in the run's fingerprint: an edit to them after the run changes the
    verdict without simulating again. Empty for an audit without formation data."""
    formation = audit.get("formation") or {}
    recorded = formation.get("components") or {}
    if not recorded:
        return {}
    materials = getattr(process, "materials", None)
    known = {c.id: c for c in (getattr(materials, "components", None) or [])}
    compounds = [
        {
            "id": cid,
            "cas": getattr(known.get(cid), "cas", None),
            "title": getattr(known.get(cid), "name", None),
        }
        for cid in recorded
    ]
    now = _project_formation(process, compounds)
    data = {
        "components": {
            cid: {
                **row,
                **{k: v for k, v in now[cid].items() if k != "molar_mass"},
                "missing": now[cid].get("missing"),
            }
            for cid, row in recorded.items()
        }
    }
    found = {}
    for row in (audit.get("closure") or {}).get("units") or []:
        if row.get("basis") != "formation" or "changes_mol_s" not in row:
            continue
        term = {"formation_kW": row["formation_kW"], **_shares(row["changes_mol_s"], data)}
        found[row["id"]], _ = _compare(row["id"], term, data, lambda *_: None)
    return found


def _shares(changing: dict[str, float], formation: dict[str, Any]) -> dict[str, Any]:
    """The changing components without a project value (``project_missing``) and each other
    one's share (kW) of the difference between the project's and DWSIM's reaction heat."""
    data = formation["components"]

    def value(c: str, key: str) -> float | None:
        return (data.get(c) or {}).get(key)

    missing = [c for c in changing if value(c, "dHf_298_kJ_kmol") is None]
    return {
        "project_missing": missing,
        "shares_kW": {
            c: d * (value(c, "dHf_298_kJ_kmol") - value(c, "simulator_dHf_298_kJ_kmol")) / 1e3  # type: ignore[operator]
            for c, d in changing.items()
            if c not in missing
        },
    }


def _chemicals_formation(compound: dict[str, Any]) -> dict[str, Any]:
    """chemicals' ideal-gas formation enthalpy of a compound not declared in materials (a
    fallback), or why there is none (``missing``)."""
    identifier = compound.get("cas") or compound.get("title") or compound["id"]
    try:
        from chemeascode.integrations.thermo import ideal_gas_formation

        found = ideal_gas_formation(identifier)
    except ImportError:
        return {
            "missing": f"no ideal_gas in {MATERIALS_FILE} and chemicals is not installed (extra "
            "props)"
        }
    except ValueError as failure:
        return {"missing": f"no ideal_gas in {MATERIALS_FILE}; {failure}"}
    return {
        "dHf_298_kJ_kmol": found["dHf_298"],
        "origin": "chemicals",
        "source": f"chemicals fallback (nothing declared): dHf_298 {found['sources']['dHf_298']} "
        f"({found['cas']})",
    }


def _reacting(u: dict[str, Any]) -> set[str] | None:
    """The components reactor *u* can change: its reactions' stoichiometry, a Gibbs reactor's
    components; None when its spec names neither (every component then counts)."""
    spec = u.get("spec") or {}
    names = {c for r in spec.get("reactions") or [] for c in r.get("stoichiometry") or {}}
    names |= set(spec.get("components") or [])
    return names or None


def _moles(out: dict[str, Any], sid: str, formation: dict[str, Any]) -> dict[str, float] | None:
    """Component molar flows (mol/s) of stream *sid*: the simulator's molar flow, else its mass
    flow over the mean molar mass; None without them."""
    s = _flow(out, sid)
    x = s.get("mole_fractions")
    if not x:
        return None
    n = s.get("molar_flow_mol_s")
    if n is None:
        m = s.get("mass_flow_kg_s")
        masses = {c: (formation["components"].get(c) or {}).get("molar_mass") for c in x}
        if m is None or any(masses[c] is None for c, v in x.items() if v):
            return None
        mw = sum(v * (masses[c] or 0.0) for c, v in x.items())
        if mw <= 0:
            return None
        n = m / mw * 1000.0  # kmol/s to mol/s
    return {c: n * v for c, v in x.items()}


def _formation_term(
    out: dict[str, Any],
    inlets: list[str],
    outlets: list[str],
    formation: dict[str, Any],
    reacting: set[str] | None,
) -> dict[str, Any]:
    """``sum (n_out - n_in) dHf`` (kW) over the *reacting* components whose flow changes
    between *inlets* and *outlets* (a component no reaction names does not change: what a
    recycle's tolerance leaves of it is no reaction), on DWSIM's formation enthalpies
    (``formation_kW``) and on the project's (``project_formation_kW``, with each component's
    share of the difference); the streams without component flows (``lacking``) and the
    changing components without DWSIM's value (``missing``) or the project's
    (``project_missing``)."""
    change: dict[str, float] = {}
    through = 0.0
    lacking = []
    for streams, sign in ((inlets, -1.0), (outlets, 1.0)):
        for sid in streams:
            n = _moles(out, sid, formation)
            if n is None:
                lacking.append(sid)
                continue
            for c, v in n.items():
                change[c] = change.get(c, 0.0) + sign * v
                through += abs(v)
    changing = {
        c: d
        for c, d in change.items()
        if (reacting is None or c in reacting) and abs(d) > SMALL_DN * max(through, 1e-300)
    }
    data = formation["components"]

    def value(c: str, key: str) -> float | None:
        return (data.get(c) or {}).get(key)

    missing = [c for c in changing if value(c, "simulator_dHf_298_kJ_kmol") is None]
    term: dict[str, Any] = {"lacking": lacking, "missing": missing, "changes_mol_s": changing}
    if lacking or missing:
        return term
    # mol/s times kJ/kmol (= J/mol) is W
    term["formation_kW"] = (
        sum(d * value(c, "simulator_dHf_298_kJ_kmol") for c, d in changing.items()) / 1e3  # type: ignore[operator]
    )
    term.update(_shares(changing, formation))
    if not term["project_missing"]:
        term["project_formation_kW"] = term["formation_kW"] + sum(term["shares_kW"].values())
    return term


def _reactor_problem(formation: dict[str, Any] | None) -> str:
    """Why a reacting unit's closure is not evaluated at all, or ''."""
    if formation is None:
        return (
            "a reacting unit needs enthalpies on a heat-of-formation basis; no formation data "
            "was prepared"
        )
    if not formation["reference_verified"]:
        if formation["property_package"] in IDAES_PACKAGES:
            return (
                "a reacting unit needs enthalpies on a heat-of-formation basis; the closure is "
                f"not verified for the IDAES backend's {formation['property_package']!r} (it "
                "reports no formation enthalpies; its enthalpies include them)"
            )
        return (
            "a reacting unit needs enthalpies on a heat-of-formation basis; DWSIM's enthalpy "
            f"reference for {formation['property_package']!r} is not verified (verified: "
            f"{', '.join(FORMATION_PACKAGES)})"
        )
    return ""


def _differs(x: dict[str, Any]) -> bool:
    """Whether a component's project and DWSIM values differ beyond floating-point noise (DWSIM
    keeps kJ/kg: its value comes back through its molar mass)."""
    scale = max(abs(x["simulator_dHf_298_kJ_kmol"]), abs(x["dHf_298_kJ_kmol"]), 1.0)
    return abs(x["difference_kJ_kmol"]) > 1e-9 * scale


def data_tolerance(formation_kw: float) -> float:
    """The formation-data tolerance, kW, of a reactor whose reaction heat (formation term on
    DWSIM's values) is *formation_kw*: :data:`DATA_TOLERANCE`."""
    return max(DATA_TOLERANCE["rel_reaction_heat"] * abs(formation_kw), DATA_TOLERANCE["abs_kW"])


def _compare(
    uid: str, term: dict[str, Any], formation: dict[str, Any], line: Any
) -> tuple[dict[str, Any], list[Finding]]:
    """The project's formation enthalpies against DWSIM's for one reactor, judged on the data
    (:func:`data_tolerance` of the reaction heat), never on the reactor's duty or mode. Each
    component with both values gives its difference (kJ/kmol) and its share of the reaction
    heat (kW). Status:

    - ``declared-differs`` (warning, ``predictive.formation-data`` fails): the declared values'
      share exceeds the tolerance;
    - ``within-tolerance``: a nonzero difference below it (declared or chemicals' fallback),
      recorded as a limitation;
    - ``fallback-differs`` (info): the combined difference exceeds the tolerance while the
      declared values' share alone does not, so chemicals' fallback values make it a
      limitation (nothing declared to fail);
    - ``not-compared``: no reacting component has a project value (a limitation);
    - ``consistent``: every reacting component has a project value equal to DWSIM's.

    Reacting components without a project value are listed (``missing``, a limitation); the
    declared ones are compared all the same."""
    data = formation["components"]
    shares = term["shares_kW"]
    tol = data_tolerance(term["formation_kW"])
    declared = sum(v for c, v in shares.items() if data[c]["origin"] == "declared")
    fallback = sum(v for c, v in shares.items() if data[c]["origin"] != "declared")
    components = [
        {
            "id": c,
            "origin": data[c]["origin"],
            "source": data[c]["source"],
            "dHf_298_kJ_kmol": data[c]["dHf_298_kJ_kmol"],
            "simulator_dHf_298_kJ_kmol": data[c]["simulator_dHf_298_kJ_kmol"],
            "simulator_database": data[c].get("simulator_database"),
            "difference_kJ_kmol": data[c]["dHf_298_kJ_kmol"] - data[c]["simulator_dHf_298_kJ_kmol"],
            "share_kW": v,
        }
        for c, v in shares.items()
    ]
    row: dict[str, Any] = {
        "difference_kW": declared + fallback,
        "declared_difference_kW": declared,
        "fallback_difference_kW": fallback,
        "data_tolerance_kW": tol,
        "components": components,
        "missing": list(term["project_missing"]),
        "limitations": [],
    }
    if "project_formation_kW" in term:
        row["project_formation_kW"] = term["project_formation_kW"]

    def shown(declared_only: bool) -> str:
        return "; ".join(
            f"{x['id']} {x['dHf_298_kJ_kmol']:.6g} kJ/kmol {x['source']}, "
            f"{x['simulator_dHf_298_kJ_kmol']:.6g} in DWSIM "
            f"({x['simulator_database'] or 'its database'}): {x['difference_kJ_kmol']:+.6g} "
            f"kJ/kmol, {x['share_kW']:+.4g} kW"
            for x in components
            if (x["origin"] == "declared") == declared_only and _differs(x)
        )

    findings = []
    if abs(declared) > tol:
        row["status"] = "declared-differs"
        findings.append(
            _finding(
                "warning",
                "sim-formation-data",
                f"{uid}: the reaction heat DWSIM simulates differs from the formation enthalpies "
                f"declared in {MATERIALS_FILE} by {declared:.4g} kW (data tolerance {tol:.3g} "
                f"kW, {DATA_TOLERANCE['rel_reaction_heat']:.0%} of the reaction heat): "
                + shown(True),
                line(uid),
                [uid],
                "DWSIM's reactor duty takes its database's formation enthalpies, not the "
                "declared ones: check both sources and say which the design rests on (DWSIM "
                "takes declared data only as a user compound); never edit a value to pass",
            )
        )
    elif abs(declared + fallback) > tol:
        # the declared values alone stay within the tolerance: the rest is chemicals' fallback
        row["status"] = "fallback-differs"
        row["limitations"].append(
            f"{uid}: the simulated reaction heat differs by {declared + fallback:.4g} kW from "
            f"the project's formation enthalpies, beyond the data tolerance {tol:.3g} kW; the "
            f"declared values' share is {declared:.4g} kW (within it), chemicals' fallback "
            f"values (nothing declared) give {fallback:.4g} kW: "
            + "; ".join(t for t in (shown(True), shown(False)) if t)
        )
    elif any(_differs(x) for x in components):
        row["status"] = "within-tolerance"
        row["limitations"].append(
            f"{uid}: the simulated reaction heat differs by {declared + fallback:.4g} kW from "
            f"the project's formation enthalpies, within the data tolerance {tol:.3g} kW: "
            + "; ".join(t for t in (shown(True), shown(False)) if t)
        )
    elif not components:
        row["status"] = "not-compared"
    else:
        row["status"] = "consistent"
    if term["project_missing"]:
        row["limitations"].append(
            f"{uid}: no project formation enthalpy for {', '.join(term['project_missing'])} ("
            + "; ".join(data.get(c, {}).get("missing") or "?" for c in term["project_missing"])
            + "), not compared with DWSIM's"
        )
    if row["limitations"]:
        findings.append(
            _finding(
                "info",
                "sim-formation-data",
                "; ".join(row["limitations"]),
                line(uid),
                [uid],
                f"declare ideal_gas.dHf_298 with its source in {MATERIALS_FILE}; a difference "
                "within the tolerance is a limitation of the simulated reaction heat, say so in "
                "the review",
            )
        )
    return row, findings


def _closure(model, out, units, line, formation: dict[str, Any] | None = None):
    """The closure of every unit and of the plant. *formation* is :func:`_formation_data`'s
    (None: no reacting unit is evaluated). Reacting units close on DWSIM's own formation
    enthalpies (the simulation's energy conservation); the project's are compared with them
    separately (``formation_data`` on each reactor row, ``sim-formation-data``)."""
    findings: list[Finding] = []
    rows = []
    inlets = {s for u in model["units"] for s in u["inlets"]}
    outlets = {s for u in model["units"] for s in u["outlets"]}
    have_enthalpy = any(
        (s or {}).get("mass_enthalpy_kJ_kg") is not None
        for s in (out.get("streams") or {}).values()
    )
    total_q = total_w = 0.0
    unsupported: list[str] = []
    reacting: set[str] | None = set()
    any_reactor = False

    def refuse(row: dict[str, Any], uid: str, kind: str, why: str) -> None:
        row.update(status="unsupported", reason=why)
        unsupported.append(f"{uid}: {why}")
        findings.append(
            _finding(
                "info",
                "sim-energy-unsupported",
                f"{uid}: energy closure not evaluated: {why}",
                line(uid),
                [uid],
                (
                    "unsupported/inconsistent enthalpy reference or missing formation data"
                    if kind in REACTORS
                    else "the duty's sign is not established"
                )
                + ": no residual is reported (the plant closure is unsupported too)",
            )
        )
        rows.append(row)

    for u in model["units"]:
        uid, kind = u["id"], u["type"]
        q, w, why = _exchange(kind, units.get(uid) or {})
        total_q += q
        total_w += w
        row: dict[str, Any] = {"id": uid, "unit": kind, "heat_in_kW": q, "work_in_kW": w}
        if kind in REACTORS:
            any_reactor = True
            names = _reacting(u)
            reacting = None if names is None or reacting is None else reacting | names
            why = _reactor_problem(formation)
        if why:
            refuse(row, uid, kind, why)
            continue
        flows_in = [_enthalpy_flow(out, s) for s in u["inlets"]]
        flows_out = [_enthalpy_flow(out, s) for s in u["outlets"]]
        if not have_enthalpy or None in flows_in or None in flows_out:
            row["status"] = "not-evaluable"
            rows.append(row)
            continue
        h_in, h_out = sum(flows_in), sum(flows_out)  # type: ignore[arg-type]
        tol = _tolerance(q, w, sum(abs(x) for x in flows_in), sum(abs(x) for x in flows_out))  # type: ignore[arg-type]
        f = 0.0
        term: dict[str, Any] = {}
        row["basis"] = "simulator"
        if kind in REACTORS:
            term = _formation_term(out, u["inlets"], u["outlets"], formation, _reacting(u))  # type: ignore[arg-type]
            if term["lacking"]:
                row.update(status="not-evaluable", missing=term["lacking"])
                rows.append(row)
                continue
            if term["missing"]:
                why = (
                    f"DWSIM's formation enthalpy of {', '.join(term['missing'])} was not "
                    "reported (a run from before the worker reported them: simulate again)"
                )
                refuse(row, uid, kind, why)
                continue
            f = term["formation_kW"]
            # the formation term counts as an enthalpy flow in the tolerance, not as a duty
            tol += ENERGY_TOLERANCE["rel_enthalpy"] * abs(f)
            row.update(basis="formation", formation_kW=f, changes_mol_s=term["changes_mol_s"])
        residual = h_out - h_in + f - q - w
        ok = abs(residual) <= tol
        row.update(
            status="ok" if ok else "imbalance",
            enthalpy_in_kW=h_in,
            enthalpy_out_kW=h_out,
            residual_kW=residual,
            tolerance_kW=tol,
        )
        if kind in REACTORS:
            row["formation_data"], found = _compare(uid, term, formation, line)  # type: ignore[arg-type]
            findings += found
        if not ok:
            findings.append(
                _finding(
                    "warning",
                    "sim-energy-unbalanced",
                    f"{uid}: enthalpy out minus in ({h_out - h_in + f:.4g} kW"
                    + (", formation basis on DWSIM's data" if kind in REACTORS else "")
                    + f") differs from heat plus work in ({q + w:.4g} kW) by {residual:.4g} kW "
                    f"(tolerance {tol:.3g} kW)",
                    line(uid),
                    [uid],
                    "check the unit's specs and convergence (--save and open the flowsheet)",
                )
            )
        rows.append(row)

    feeds = sorted(inlets - outlets)
    products = sorted(outlets - inlets)
    plant: dict[str, Any] = {
        "feeds": feeds,
        "products": products,
        "heat_in_kW": total_q,
        "work_in_kW": total_w,
        "basis": "formation" if any_reactor else "simulator",
        "reasons": [],
    }
    if unsupported:
        plant.update(status="unsupported", reasons=unsupported)
    elif not have_enthalpy:
        plant.update(status="not-evaluable", reasons=["the simulator returned no enthalpies"])
        findings.append(
            _finding(
                "info",
                "sim-energy-not-evaluable",
                "energy closure not evaluated: the simulator returned no stream enthalpies",
                None,
                [],
                "run cheme process simulate again (the worker reports mass enthalpies)",
            )
        )
    else:
        f_in = [_enthalpy_flow(out, s) for s in feeds]
        f_out = [_enthalpy_flow(out, s) for s in products]
        lacking = [s for s, v in zip(feeds + products, f_in + f_out, strict=True) if v is None]
        term = {"formation_kW": 0.0}
        if not lacking and any_reactor:
            term = _formation_term(out, feeds, products, formation, reacting)  # type: ignore[arg-type]
            lacking = term["lacking"]
        if lacking:
            plant.update(status="not-evaluable", reasons=[f"no enthalpy for {', '.join(lacking)}"])
        elif term.get("missing"):
            names = ", ".join(term["missing"])
            plant.update(
                status="unsupported",
                reasons=[f"plant: DWSIM's formation enthalpy of {names} was not reported"],
            )
        else:
            h_in, h_out = sum(f_in), sum(f_out)  # type: ignore[arg-type]
            f = term["formation_kW"]
            residual = h_out - h_in + f - total_q - total_w
            tol = _tolerance(
                total_q,
                total_w,
                sum(abs(x) for x in f_in),  # type: ignore[arg-type]
                sum(abs(x) for x in f_out),  # type: ignore[arg-type]
            ) + ENERGY_TOLERANCE["rel_enthalpy"] * abs(f)
            ok = abs(residual) <= tol
            plant.update(
                status="ok" if ok else "imbalance",
                enthalpy_in_kW=h_in,
                enthalpy_out_kW=h_out,
                residual_kW=residual,
                tolerance_kW=tol,
            )
            if any_reactor:
                plant["formation_kW"] = f
                if "project_formation_kW" in term:
                    plant["project_formation_kW"] = term["project_formation_kW"]
            if not ok:
                findings.append(
                    _finding(
                        "warning",
                        "sim-energy-unbalanced",
                        f"plant: boundary enthalpy out minus in ({h_out - h_in + f:.4g} kW"
                        + (", formation basis on DWSIM's data" if any_reactor else "")
                        + f") differs from the heat plus work of the units "
                        f"({total_q + total_w:.4g} kW) by {residual:.4g} kW (tolerance "
                        f"{tol:.3g} kW)",
                        None,
                        [],
                        "find the unit whose closure fails (the record's energy.closure.units); "
                        "check recycle convergence",
                    )
                )
    return {"units": rows, "plant": plant}, findings


# -- utility classification ---------------------------------------------------------------------


def _utilities(model, out, units, ends, terminals) -> dict[str, Any]:
    """Every duty classified once: hot or cold utility, power, or recovered between process
    streams. A condenser-reboiler's duty and a process-process exchanger's are recovered heat,
    never utility."""
    totals = dict.fromkeys(
        ("hot_utility", "cold_utility", "power_in", "power_out", "recovered"), 0.0
    )
    rows = []
    linked_condensers = {
        u["spec"]["heat_integration"]["condenser_of"]
        for u in model["units"]
        if u["spec"].get("heat_integration")
    }

    def add(uid: str, role: str, bucket: str, kw: float, stream: str | None = None) -> None:
        if abs(kw) <= 1e-12:
            return
        totals[bucket] += abs(kw)
        terminal = ends.get(stream or "")
        rows.append({"id": uid, "role": role, "class": bucket, "kW": abs(kw), "terminal": terminal})

    for u in model["units"]:
        uid, kind = u["id"], u["type"]
        got = units.get(uid) or {}
        energy = (u.get("energies") or {}).get("energy")
        if kind in ("compressor", "pump"):
            add(uid, "power", "power_in", got.get("duty_kW") or 0.0, energy)
            add(uid, "intercooling", "cold_utility", got.get("cooling_kW") or 0.0)
        elif kind == "expander":
            add(uid, "power", "power_out", got.get("duty_kW") or 0.0, energy)
        elif kind in HEATED:
            q = got.get("duty_kW") or 0.0
            add(uid, "heat", "hot_utility" if q > 0 else "cold_utility", q, energy)
        elif kind == "heat_exchanger":
            q = got.get("duty_kW") or 0.0
            utility = [s for s in u["inlets"] if _is_utility(s, ends, terminals)]
            if not utility:
                add(uid, "exchange", "recovered", q)
            else:
                # a utility on a material stream: which side it is decides hot or cold
                rows.append(
                    {
                        "id": uid,
                        "role": "exchange",
                        "class": "utility-stream",
                        "kW": abs(q),
                        "terminal": ends.get(utility[0]),
                    }
                )
                totals["hot_utility" if _hotter(u, utility[0], out) else "cold_utility"] += abs(q)
        elif kind == "multi_stream_exchanger":
            net = got.get("imbalance_kW") or 0.0
            add(uid, "exchange", "recovered", (got.get("duty_kW") or 0.0) - max(net, 0.0))
            add(uid, "net", "hot_utility" if net > 0 else "cold_utility", net)
        elif kind in ("distillation_column", "shortcut_column"):
            roles = u.get("energies") or {}
            link = u["spec"].get("heat_integration")
            reboil = got.get("reboiler_kW") or 0.0
            if link:
                add(uid, "reboiler", "recovered", reboil)
            else:
                add(uid, "reboiler", "hot_utility", reboil, roles.get("reboiler"))
            if uid not in linked_condensers:
                add(
                    uid,
                    "condenser",
                    "cold_utility",
                    got.get("condenser_kW") or 0.0,
                    roles.get("condenser"),
                )
    return {"totals_kW": totals, "duties": rows}


def _hotter(u: dict[str, Any], stream: str, out: dict[str, Any]) -> bool:
    """Whether the utility *stream* is the hot side of exchanger *u*: its inlet is the hotter."""
    mine = _flow(out, stream).get("temperature_K")
    others = [_flow(out, s).get("temperature_K") for s in u["inlets"] if s != stream]
    return mine is not None and all(t is not None and mine > t for t in others)
