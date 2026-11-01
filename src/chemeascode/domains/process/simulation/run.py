"""``cheme process simulate --fill/--check``: the flowsheet solved by DWSIM, or by the optional
IDAES backend where ``process/simulation.yaml`` says ``simulator: idaes`` (ADR 0039).

The feeds (temperature, pressure, flow, composition) and the specifications in
``process/simulation.yaml`` go to the simulator; every other material stream comes back with its
temperature, pressure, mass flow and composition, every energy stream attached to a unit with
its duty. ``--fill`` writes the values a stream lacks with provenance ``calculated``, ``origin:
simulated``, source ``cheme process simulate: DWSIM <version>, <property package>`` (``IDAES
<version>`` with the IDAES backend) and the
fingerprint of the simulator model; it rewrites only values it wrote itself, never a given,
assumed or otherwise calculated one. Where such a value differs from the simulated one beyond
the tolerance, ``cheme.process-sim-deviation`` says so. ``--check`` writes nothing and reports
what is not filled, stale (``cheme.process-sim-stale``: the model changed since) or deviating.

A converged run's conversion reactors are checked against their declared conversions
(:mod:`.conversion`: DWSIM converts a reaction's key in the inlet's reaction phase only), and
the run is checked for energy independently of the simulator's duty balance
(:mod:`.energy`): exchanger temperature crosses and approaches, utility temperature levels,
per-unit and plant enthalpy closure, and a classification of every duty (utility, power,
recovered).

``--fill`` also records the run in ``process/simulation-run.json`` (:mod:`.record`): simulator
and version, property package, the input fingerprints, convergence, the result of each unit and
the values of each stream, the energy audit, for the viewer; also a run that did not converge
(its stream values are then not written). ``--check`` reports a record made from other inputs.

Phase and calculated properties stay with ``cheme process props``, which works on the
temperatures and pressures written here.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from chemeascode.domains.process import FLOWSHEET_FILE
from chemeascode.domains.process.fill import PropsResult, _sig
from chemeascode.domains.process.model import Process, stream_flows
from chemeascode.domains.process.propagate import _write
from chemeascode.domains.process.schema import (
    DUTY_UNITS,
    FLOW_UNITS,
    CompositionValue,
    Quantity,
)
from chemeascode.domains.process.simulation import (
    SIMULATION_FILE,
    SOURCE,
    conversion,
    coupling,
    record,
)
from chemeascode.domains.process.simulation import energy as energy_checks
from chemeascode.domains.process.simulation.backends import IDAES, TITLES
from chemeascode.domains.process.simulation.translate import (
    _mole_fractions,
    load,
    ours,
    translate,
)
from chemeascode.foundation.findings import Finding
from chemeascode.foundation.units import convert_units, pressure_kind, to_kelvin, to_kpa_abs
from chemeascode.foundation.yamlsource import _yaml_line

FIELDS = ("temperature", "pressure", "flow", "composition")


def run(
    workspace: Any,
    process: Process,
    case: str,
    *,
    write: bool,
    save: Path | None = None,
    solver: Any = None,
) -> PropsResult:
    """Fill (*write*) or check the simulated stream values of *case*. *solver* stands in for
    the simulator's ``solve`` (``chemeascode.integrations.dwsim`` or ``.idaes``; tests)."""
    from chemeascode.integrations import dwsim, idaes

    result = PropsResult()
    fs = process.flowsheet
    doc = process.flowsheet_doc

    def add(level: str, rule: str, message: str, loc: list[Any], ids: list[str], hint: str = ""):
        result.findings.append(
            Finding(
                FLOWSHEET_FILE,
                level,  # type: ignore[arg-type]
                f"cheme.process-{rule}",
                message,
                line=_yaml_line(doc, loc),
                ids=ids,
                hint=hint,
            )
        )

    sim, sim_doc, found = load(workspace.root)
    result.findings += found
    if sim is None:
        if not found:
            result.findings.append(
                Finding(
                    SIMULATION_FILE,
                    "error",
                    "cheme.process-sim-missing",
                    f"{SIMULATION_FILE} does not exist",
                    hint="write it (kind: simulation): the property package and the specs of "
                    "every step; see `cheme schema process-simulation`",
                )
            )
        return result
    found_model = translate(process, sim, sim_doc, case)
    result.findings += found_model.findings
    model = found_model.model
    if model is None:
        result.refused.append(case)
        return result
    if not write:
        result.findings += _record_check(workspace.root, case, found_model.fingerprint)

    kinetic = [u["id"] for u in coupling.kinetic_units(model)]
    backend = idaes if sim.simulator == IDAES else dwsim
    try:
        if kinetic:
            # fixed beds: solved by cheme-as-code, coupled to DWSIM by an outer loop (the IDAES
            # backend refuses them at translation, backends.model_findings)
            out = coupling.solve(process, model, case, solver or dwsim.solve, save)
        else:
            out = (solver or backend.solve)(model, save)
    except (dwsim.DwsimUnavailable, idaes.IdaesUnavailable) as failure:
        add("error", "sim-unavailable", str(failure), [], [], backend.HINT)
        return result
    except (dwsim.DwsimFailed, idaes.IdaesFailed) as failure:
        add(
            "error",
            "sim-failed",
            str(failure),
            [],
            [],
            "check the specs and feeds; --save writes the flowsheet to open in DWSIM"
            if backend is dwsim
            else "check the specs and feeds, and the first guesses of the tear streams "
            "(guesses: in process/simulation.yaml)",
        )
        return result
    title = TITLES[sim.simulator]
    source = f"{SOURCE}: {title} {out.get('version', '?')}, {sim.property_package}"
    if kinetic:
        models = {u["id"]: u["spec"].get("model", "") for u in coupling.kinetic_units(model)}
        source += "; " + ", ".join(
            f"{uid} coupled as external unit ({models[uid].split(' (')[0]})" for uid in kinetic
        )
    result.lines.append(f"{source}; case {case}")
    result.findings += _coupling_findings(out.get("coupling") or {}, sim_doc)
    if out.get("save_error"):
        add(
            "warning",
            "sim-not-saved",
            f"the flowsheet was not saved to {save}: {out['save_error']}",
            [],
            [],
            "give a writable --save path",
        )
    elif save is not None:
        result.lines.append(f"flowsheet saved: {save}")
    if not out.get("converged", False):
        add(
            "warning",
            "sim-not-converged",
            f"case {case}: the simulation did not converge: "
            + "; ".join(out.get("messages") or ["no message"]),
            [],
            [],
            "check the specs and the feeds; no stream value is written",
        )
        result.refused.append(case)
        if write:
            units = out.get("units", {})
            _record(workspace.root, case, sim, process, found_model, out, units, result, [])
        return result
    drives = {
        u["id"]: (u["type"], u["spec"]["drive_efficiency"])
        for u in model["units"]
        if "drive_efficiency" in u["spec"]
    }
    # electric power where a drive efficiency is given: a motor takes more than the shaft, a
    # generator gives less; the energy streams and the summary take it, DWSIM keeps the shaft
    solved = {}
    for unit, values in out.get("units", {}).items():
        values = dict(values)
        bed = (out.get("coupling") or {}).get(unit, {}).get("bed")
        if bed:  # the bed's own results, not the conversion reactor's (it keeps no extents)
            values["extents_kmol_h"] = bed["extents_kmol_h"]
            values["hot_spot_K"] = bed["hot_spot_K"]
            values["pressure_drop_kPa"] = bed["pressure_drop_kPa"]
        if unit in drives and values.get("duty_kW") is not None:
            kind, eta = drives[unit]
            shaft = values["duty_kW"]
            values["shaft_kW"] = shaft
            values["duty_kW"] = shaft * eta if kind == "expander" else shaft / eta
        solved[unit] = values
    # conversion reactors: the conversion DWSIM reached against the declared one;
    # one whose liquid left by a missing outlet (the worker's message) is
    # not comparable
    named = {m.split(":")[0] for m in out.get("messages") or []}
    reached = conversion.achieved(model, out, skip=named)
    for unit, info in reached.items():
        values = solved.setdefault(unit, {})
        if not values.get("extents_kmol_h") and "extents_kmol_h" in info:
            values["extents_kmol_h"] = info["extents_kmol_h"]
            values["conversions"] = info["conversions"]
    out = {**out, "units": solved}
    for unit, values in solved.items():
        shown = [_shown(k, v) for k, v in values.items() if v is not None and v != {}]
        if (found_model.bases.get(unit) or {}).get("basis") == "specified" and unit in {
            u["id"] for u in model["units"] if u["type"] == "component_separator"
        }:
            shown.append("specified split (recoveries given, not predicted)")
        if shown:
            result.lines.append(f"{unit}: {', '.join(shown)}")
        off, duty = values.get("imbalance_kW"), values.get("duty_kW") or 0.0
        if off is not None and abs(off) > max(0.01 * duty, 0.1):
            result.findings.append(
                Finding(
                    SIMULATION_FILE,
                    "warning",
                    "cheme.process-sim-unbalanced",
                    f"{unit}: the outlet temperatures do not balance the exchanger: {off:.4g} kW "
                    f"of {duty:.4g} kW transferred",
                    line=_yaml_line(sim_doc, ["specs", unit, "outlet_temperatures"]),
                    ids=[unit],
                    hint="leave one stream's outlet temperature out of "
                    f"specs.{unit}.outlet_temperatures, so the energy balance sets it",
                )
            )

    result.findings += conversion.findings(reached, sim_doc)
    result.findings += _column_checks(model, out.get("units", {}), sim_doc)
    found_energy, energy_audit, energy_lines = energy_checks.audit(
        process, sim, sim_doc, model, out
    )
    result.findings += found_energy
    result.lines += energy_lines
    new = _values(process, found_model, out, case, source, add)
    edits: dict[int, dict[str, Any]] = {}
    #: stream id -> the fields holding the simulated value, and those simulate leaves alone
    filled: dict[str, list[str]] = {}
    kept: dict[str, dict[str, str]] = {}
    for i, stream in enumerate(fs.streams):
        state = stream.state.get(case)
        loc = ["streams", i, "state", case]
        for name in (*FIELDS, "duty"):
            value = new.get((stream.id, name))
            if value is None:
                continue
            old = getattr(state, name) if state is not None else None
            if old is None or ours(old):
                # same inputs: current, even where an iterative solve (a recycle started from
                # the last result) lands a digit apart
                if old is not None and old.fingerprint == value.fingerprint:
                    filled.setdefault(stream.id, []).append(name)
                    continue
                if write:
                    edits.setdefault(i, {})[name] = value
                    filled.setdefault(stream.id, []).append(name)
                elif old is None:
                    add(
                        "info",
                        "sim-not-filled",
                        f"stream {stream.id} ({case}): {name} simulated, not filled",
                        loc,
                        [stream.id],
                        "run cheme process simulate --fill",
                    )
                else:
                    add(
                        "warning",
                        "sim-stale",
                        f"stream {stream.id} ({case}): simulated {name} no longer matches the "
                        "simulation (feeds, specs, property package or simulator changed)",
                        loc,
                        [stream.id],
                        "run cheme process simulate --fill",
                    )
                continue
            kept.setdefault(stream.id, {})[name] = old.provenance
            off = _deviation(process, sim, stream, case, name, old, value)
            if off:
                add(
                    "warning",
                    "sim-deviation",
                    f"stream {stream.id} ({case}): {name} {off}",
                    loc,
                    [stream.id],
                    f"review the {old.provenance} value against the simulation (or the specs "
                    f"in {SIMULATION_FILE}); simulate never overwrites it",
                )
    if write:
        if edits:
            _write(workspace.root / FLOWSHEET_FILE, doc, case, edits)
        result.written = len(edits)
        result.lines.append(
            f"{FLOWSHEET_FILE}: simulated values written for {len(edits)} stream(s)"
        )
        shown = record.stream_values(process, new)
        streams = [
            {
                "id": sid,
                "values": shown[sid],
                "filled": filled.get(sid, []),
                "kept": kept.get(sid, {}),
            }
            for sid in [s.id for s in fs.streams]
            if sid in shown
        ]
        _record(
            workspace.root,
            case,
            sim,
            process,
            found_model,
            out,
            solved,
            result,
            streams,
            energy_audit,
        )
    return result


def _record(
    root: Path,
    case: str,
    sim: Any,
    process: Process,
    translation: Any,
    out: dict[str, Any],
    solved: dict[str, Any],
    result: PropsResult,
    streams: list[dict[str, Any]],
    energy_audit: dict[str, Any] | None = None,
) -> None:
    """Write the run record of *case* (:mod:`.record`) after a run the simulator finished;
    *energy_audit* is :func:`.energy.audit`'s (converged runs only)."""
    units = record.unit_rows(
        translation.model,
        solved,
        bool(out.get("converged", False)),
        list(out.get("messages") or []),
        result.findings,
        record.excluded(process, sim),
        bases=translation.bases,
        coupled=out.get("coupling") or {},
    )
    entry = record.make_entry(
        root=root,
        case=case,
        sim=sim,
        model=translation.model,
        fingerprint=translation.fingerprint,
        out=out,
        units=units,
        streams=streams,
        findings=result.findings,
        energy=energy_audit,
    )
    record.write(root, entry)
    result.lines.append(f"{record.RUN_FILE}: run of case {case} recorded")


def _record_check(root: Path, case: str, fingerprint: str) -> list[Finding]:
    """--check: the run record of *case* is missing (info) or was made from other inputs."""
    entry = record.entry_of(record.read(root), case)
    if entry is None:
        return [
            Finding(
                record.RUN_FILE,
                "info",
                "cheme.process-sim-run-missing",
                f"case {case}: no run recorded in {record.RUN_FILE}",
                ids=[case],
                hint="run cheme process simulate --fill (it records the run)",
            )
        ]
    if entry.get("model_fingerprint") != fingerprint:
        return [
            Finding(
                record.RUN_FILE,
                "warning",
                "cheme.process-sim-run-stale",
                f"case {case}: the recorded run was simulated from other inputs (feeds, specs, "
                "property package or simulator model changed)",
                ids=[case],
                hint="run cheme process simulate --fill",
            )
        ]
    return []


#: Result keys of the units as the summary shows them.
_LABELS = {
    "duty_kW": ("", "kW"),
    "condenser_kW": ("condenser ", "kW"),
    "reboiler_kW": ("reboiler ", "kW"),
    "stages": ("stages ", ""),
    "min_stages": ("minimum stages ", ""),
    "min_reflux": ("minimum reflux ratio ", ""),
    "reflux_ratio": ("reflux ratio ", ""),
    "imbalance_kW": ("imbalance ", "kW"),
    "cooling_kW": ("cooling ", "kW"),
    "shaft_kW": ("shaft ", "kW"),
    "top_residual_kW": ("top residual ", "kW"),
    "top_temperature_K": ("top ", "K"),
    "bottom_temperature_K": ("bottom ", "K"),
    "extents_kmol_h": ("extents ", "kmol/h"),
    "conversions": ("conversions ", ""),
    "hot_spot_K": ("hot spot ", "K"),
    "pressure_drop_kPa": ("pressure drop ", "kPa"),
    "side_duties_kW": ("side duties ", "kW"),
}


def _shown(key: str, value: Any) -> str:
    label, unit = _LABELS.get(key, (f"{key} ", ""))
    if isinstance(value, list):  # a value per stream, e.g. a multi-stream exchanger's sides
        return f"{label}{', '.join(f'{v:.6g}' for v in value)}{' ' + unit if unit else ''}"
    if isinstance(value, dict):  # a value per item, e.g. a reactor's extents by reaction
        text = ", ".join(f"{k} {v:.6g}" for k, v in value.items())
        return f"{label}{text}{' ' + unit if unit else ''}"
    return f"{label}{value:.6g}{' ' + unit if unit else ''}"


def _coupling_findings(beds: dict[str, Any], sim_doc: Any) -> list[Finding]:
    """Kinetic reactors coupled as external units (:mod:`.coupling`): how each converged
    (info), and an adiabatic bed whose outlet temperature DWSIM's property package reaches
    only with a duty beyond 5 % of the reaction heat (1 kW at least)."""
    found = []
    for uid, info in beds.items():
        last = info["residuals"][-1] if info["residuals"] else None
        state = (
            f"converged in {info['iterations']} DWSIM solve(s)"
            if info["converged"]
            else f"not converged after {info['iterations']} DWSIM solve(s)"
        )
        if last:
            state += (
                f" (bed outlet against DWSIM's: flow {last['flow']:.2g}, pressure "
                f"{last['pressure']:.2g} relative, temperature {last['temperature_K']:.2g} K)"
            )
        found.append(
            Finding(
                SIMULATION_FILE,
                "info",
                "cheme.process-sim-coupling",
                f"{uid}: kinetic reactor coupled as an external unit, {state}: the reactor model "
                "is solved by cheme-as-code at the inlet DWSIM gives, DWSIM sees a conversion "
                "reactor",
                line=_yaml_line(sim_doc, ["specs", uid]),
                ids=[uid],
                hint=f"specs.{uid}.coupling sets the tolerance and the iterations; no native "
                "DWSIM kinetic reactor is used",
            )
        )
        bed = info.get("bed") or {}
        rest, heat = bed.get("energy_residual_kW"), bed.get("reaction_heat_kW")
        if rest is not None and abs(rest) > max(0.05 * abs(heat or 0.0), 1.0):
            found.append(
                Finding(
                    SIMULATION_FILE,
                    "warning",
                    "cheme.process-sim-coupling-energy",
                    f"{uid}: the adiabatic bed's outlet temperature takes {rest:.4g} kW in DWSIM's "
                    f"property package (reaction heat {heat or 0.0:.4g} kW): the ideal-gas bed and "
                    "the property package disagree on the enthalpies",
                    line=_yaml_line(sim_doc, ["specs", uid]),
                    ids=[uid],
                    hint="review the components' ideal_gas data against the property package; "
                    "at high pressure the bed's ideal gas is an approximation",
                )
            )
    return found


def _column_checks(model: dict[str, Any], units: dict[str, Any], sim_doc: Any) -> list[Finding]:
    """Rigorous columns: a top without condenser that still condenses (over 3 % of the reboiler
    duty), and condenser-reboilers whose duties differ (over 5 %) or whose temperature
    difference is below the least approach."""
    found = []

    def warn(rule: str, unit: str, message: str, hint: str, loc: list[Any]) -> None:
        found.append(
            Finding(
                SIMULATION_FILE,
                "warning",
                f"cheme.process-{rule}",
                message,
                line=_yaml_line(sim_doc, loc),
                ids=[unit],
                hint=hint,
            )
        )

    for u in model["units"]:
        if u["type"] != "distillation_column":
            continue
        name, spec, got = u["id"], u["spec"], units.get(u["id"]) or {}
        rest, duty = got.get("top_residual_kW"), got.get("reboiler_kW")
        if rest is not None and abs(rest) > (0.03 * duty if duty else 10.0):
            share = f" ({abs(rest) / duty:.1%} of the reboiler duty)" if duty else ""
            warn(
                "sim-top-residual",
                name,
                f"{name}: the top without condenser still exchanges {rest:.4g} kW{share}",
                "check the top feed: it should be liquid enough to give the reflux",
                ["specs", name],
            )
        link = spec.get("heat_integration")
        if not link:
            continue
        other = units.get(link["condenser_of"]) or {}
        given, taken = other.get("condenser_kW"), got.get("reboiler_kW")
        if (
            given is not None
            and taken is not None
            and abs(given - taken) > 0.05 * max(given, taken)
        ):
            warn(
                "sim-reboiler-unbalanced",
                name,
                f"{name}: the condenser-reboiler does not balance: {link['condenser_of']} "
                f"condenses {given:.4g} kW, {name} reboils {taken:.4g} kW",
                "the difference is liquid the columns can make or must not make: review the "
                "liquid products, the feeds' vapour fraction and the column specs",
                ["specs", name, "heat_integration"],
            )
        hot, cold = other.get("top_temperature_K"), got.get("bottom_temperature_K")
        if hot is not None and cold is not None and hot - cold < link["min_approach_K"]:
            warn(
                "sim-approach",
                name,
                f"{name}: the condenser-reboiler has {hot - cold:.3g} K between "
                f"{link['condenser_of']}'s top ({hot:.2f} K) and {name}'s bottom ({cold:.2f} K), "
                f"less than {link['min_approach_K']:g} K",
                "raise the pressure of the condensing column or lower that of the boiling one",
                ["specs", name, "heat_integration"],
            )
    return found


def _values(
    process: Process,
    model: Any,
    out: dict[str, Any],
    case: str,
    source: str,
    add: Callable[..., None],
) -> dict[tuple[str, str], Any]:
    """(stream id, field) -> the simulated value, in the flowsheet's units. A duty is written
    only where its sign agrees with its energy stream's direction (:func:`_into_unit`); *add*
    reports one that does not."""
    fs = process.flowsheet
    units = fs.units
    stamp = {
        "provenance": "calculated",
        "origin": "simulated",
        "source": source,
        "fingerprint": model.fingerprint,
    }
    templates = process.templates()
    values: dict[tuple[str, str], Any] = {}
    streams = {s.id: s for s in fs.streams}
    for sid, solved in out.get("streams", {}).items():
        stream = streams.get(sid)
        if stream is None or sid not in model.outlets:
            continue
        if solved.get("temperature_K") is not None:
            value = convert_units(solved["temperature_K"], "K", units.temperature)
            values[(sid, "temperature")] = Quantity(value=_sig(value), **stamp)
        if solved.get("pressure_Pa") is not None:
            kpa = solved["pressure_Pa"] / 1000.0
            if pressure_kind(units.pressure)[1] == "absolute":
                value = convert_units(kpa, "kPa(a)", units.pressure)
                values[(sid, "pressure")] = Quantity(value=_sig(value), **stamp)
            else:
                values[(sid, "pressure")] = Quantity(value=_sig(kpa), unit="kPa(a)", **stamp)
        if solved.get("mass_flow_kg_s") is not None:
            kg_h = solved["mass_flow_kg_s"] * 3600.0
            basis, factor = FLOW_UNITS.get(units.flow, ("", 1.0))
            if basis == "mass":
                values[(sid, "flow")] = Quantity(value=_sig(kg_h / factor), **stamp)
            else:
                values[(sid, "flow")] = Quantity(value=_sig(kg_h), unit="kg/h", **stamp)
        fractions = solved.get("mole_fractions") or {}
        template = templates.get(stream.template or "")
        names = list(template.components) if template else []
        names += [n for n, x in fractions.items() if x > 1e-12 and n not in names]
        if fractions and names:
            values[(sid, "composition")] = CompositionValue(
                basis="mole_fraction",
                values={n: _sig(fractions.get(n, 0.0)) for n in names},
                **stamp,
            )
    kinds = {u["id"]: u["type"] for u in (model.model or {}).get("units", [])}

    def refuse(energy: str, unit: str, why: str, hint: str) -> None:
        i, stream = next((i, s) for i, s in enumerate(fs.streams) if s.id == energy)
        state = stream.state.get(case)
        held = state.duty if state is not None else None
        if held is not None and ours(held):
            # written by an earlier simulate (before the direction was checked): simulate
            # never writes it again, so it would stay in place as if it were current
            why += (
                f"; the duty {energy} holds ({held.value:g}, written by an earlier simulate) "
                "is wrong: remove it"
            )
            hint = f"delete state.{case}.duty of {energy}; " + hint
        add("warning", "sim-energy-direction", why, ["streams", i], [unit, energy], hint)

    for energy, (unit, key) in model.energies.items():
        duty = (out.get("units", {}).get(unit) or {}).get(key)
        if duty is None:
            continue
        entering = energy in model.entering
        into = _into_unit(kinds.get(unit, ""), key, duty)
        if into is None:
            refuse(
                energy,
                unit,
                f"energy stream {energy} ({case}): the sign of {unit}'s energy imbalance "
                f"({duty:.4g} kW) is not established; no duty written",
                "give the duty yourself (a component separator's imbalance is a bookkeeping "
                "residual of its specified split)",
            )
            continue
        if (into < 0 and entering) or (into > 0 and not entering):
            refuse(
                energy,
                unit,
                f"energy stream {energy} ({case}) runs {'into' if entering else 'out of'} "
                f"{unit}, but the simulated duty is {abs(into):.4g} kW "
                f"{'out of' if into < 0 else 'into'} it ({key} {duty:.4g}); no duty written",
                f"reverse {energy} (from and to), or check the specs of {unit}",
            )
            continue
        factor = DUTY_UNITS.get(units.duty, 1.0)
        values[(energy, "duty")] = Quantity(value=_sig(abs(into) / factor), **stamp)
    return values


def _into_unit(kind: str, key: str, value: float) -> float | None:
    """The simulated result *key* of a unit of *kind* as energy into the unit, kW (negative:
    out of it), or None where its sign is not established. The signs are the solver's
    (:mod:`chemeascode.integrations.dwsim_worker`): ``duty_kW`` is heat added (heater, cooler,
    flash, reactors) or power taken (compressor, pump), but power produced for an expander;
    the column duties and a compressor's intercooling are magnitudes, the reboiler's in, the
    condenser's and the cooling out."""
    if key == "reboiler_kW":
        return abs(value)
    if key in ("condenser_kW", "cooling_kW"):
        return -abs(value)
    if kind == "component_separator":
        return None  # EnergyImb: its sign is not established (simulation/energy.py)
    return -value if kind == "expander" else value


def _deviation(
    process: Process, sim: Any, stream: Any, case: str, name: str, old: Any, new: Any
) -> str:
    """Why *old* (given, assumed or calculated elsewhere) and the simulated *new* differ beyond
    the tolerance; empty when they agree or cannot be compared."""
    fs = process.flowsheet
    tol = sim.tolerance
    if name == "temperature":
        a = to_kelvin(old.value, old.unit or fs.units.temperature)
        b = to_kelvin(new.value, new.unit or fs.units.temperature)
        if a is not None and b is not None and abs(a - b) > tol.temperature:
            return f"simulated {b:.2f} K, {old.provenance} {a:.2f} K"
    elif name == "pressure":
        a = to_kpa_abs(old.value, old.unit or fs.units.pressure)
        b = to_kpa_abs(new.value, new.unit or fs.units.pressure)
        if a is not None and b is not None and abs(a - b) > tol.pressure_rel * max(a, b):
            return f"simulated {b:.4g} kPa(a), {old.provenance} {a:.4g} kPa(a)"
    elif name == "flow":
        a = stream_flows(process, stream, case).total
        b = new.value * FLOW_UNITS.get(new.unit or fs.units.flow, ("", 1.0))[1]
        if a is not None and abs(a - b) > fs.tolerance.abs + fs.tolerance.rel * max(a, b):
            return f"simulated {b:.6g} kg/h, {old.provenance} {a:.6g} kg/h"
    elif name == "composition":
        comps = process.components()
        a = _mole_fractions(old, comps)
        b = _mole_fractions(new, comps)
        if a is not None and b is not None:
            worst = max(a.keys() | b.keys(), key=lambda k: abs(a.get(k, 0.0) - b.get(k, 0.0)))
            if abs(a.get(worst, 0.0) - b.get(worst, 0.0)) > tol.composition:
                return (
                    f"simulated x({worst}) {b.get(worst, 0.0):.4g}, {old.provenance} "
                    f"{a.get(worst, 0.0):.4g} (mole fraction)"
                )
    elif name == "duty":
        factor = DUTY_UNITS.get(old.unit or fs.units.duty, 1.0)
        a, b = old.value * factor, new.value * DUTY_UNITS.get(new.unit or fs.units.duty, 1.0)
        if abs(a - b) > 0.01 * max(abs(a), abs(b)):
            return f"simulated {b:.6g} kW, {old.provenance} {a:.6g} kW"
    return ""
