"""``cheme process props --fill/--check``: calculated stream properties into the flowsheet.

``--fill`` writes, per stream and case with temperature, absolute pressure and composition, the
calculated ``phase`` and ``calculated: {molar_mass, density, enthalpy, exergy}``, each with
provenance ``calculated`` (the values also ``origin: correlation``), its source and an input
fingerprint, and records the method (adapter, EOS, interaction parameters, application range,
package versions) in materials.yaml. Exergy (:mod:`.exergy`) is written only where every
component has a tabulated chemical exergy and the dead state (298.15 K, 101.325 kPa) is inside
the claimed range. It never overwrites a given or assumed value. A state the method does not
support or claim is refused and nothing is written for it; values calculated earlier stay and
show as stale.

A stream whose phase is given or assumed as vapour or liquid while the flash gives the other
phase (or two-phase) is calculated on that phase's EOS root at T and P (``Adapter.flash`` with
``phase``): its sources name the constraint (``phase-constrained <phase> root``), its
fingerprint includes the phase, and an info finding ``property-phase-constrained`` says so. A
root that does not exist (``property-phase``) or is metastable beyond
``props.METASTABLE_TOLERANCE`` (``property-metastable``) is refused.

``--check`` writes nothing: it recalculates and reports what differs, is stale or is missing.
``--coverage`` (:func:`coverage`) writes nothing and needs no thermo: it lists the property
package of the process, why it was chosen, and per stream whether the package covers its
components and state or why not (the nearest other package and what it lacks).

The method recorded is the process's property package (:mod:`.property_packages`), with its id
(``package``) and its benchmark (test file, reference, tolerances).
The YAML is edited in place (only the ``phase:`` and ``calculated:`` entries of a state and the
``property_method:`` block change); comments elsewhere are kept.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import yaml

from chemeascode.domains.process import FLOWSHEET_FILE, MATERIALS_FILE
from chemeascode.domains.process import property_packages as packages
from chemeascode.domains.process.exergy import stream_exergy
from chemeascode.domains.process.model import Process
from chemeascode.domains.process.props import (
    EOS,
    Adapter,
    Unsupported,
    choose_package,
    constraining_phase,
    fingerprint,
    gather,
    method_config,
    range_problems,
    stale,
    versions,
)
from chemeascode.domains.process.schema import (
    CALCULATED_UNITS,
    PhaseValue,
    PropertyMethod,
    Quantity,
)
from chemeascode.foundation.findings import Finding
from chemeascode.foundation.schemas.run import AdapterResult, Solver, finding_dict
from chemeascode.foundation.yamlsource import _yaml_line

#: Where an exergy comes from: the dead state and the chemical exergy table (with the method).
EXERGY_SOURCE = (
    "cheme process props: chemical (Szargut 1988, model II) + physical, dead state "
    "298.15 K, 101.325 kPa"
)
UNITS = CALCULATED_UNITS
#: Relative difference --check reports as a mismatch.
CHECK_REL = 1e-4


@dataclass
class PropsResult:
    findings: list[Finding] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    written: int = 0
    #: Streams the method refused (out of range, unsupported, failed, phase contradicted).
    refused: list[str] = field(default_factory=list)
    #: The run as an adapter result (``--json``); propagate and props set it.
    adapter: AdapterResult | None = None
    #: ``--coverage``: the package and the per-stream coverage (``--json``).
    coverage: dict[str, Any] | None = None


def _sig(value: float) -> float:
    return float(f"{value:.6g}")


def configured_method(process: Process) -> PropertyMethod:
    """The method --fill records: the process's property package, a range configured for that
    package kept."""
    package = choose_package(process).package
    assert package is not None  # Adapter(process) refused an unknown package
    current = method_config(process)
    own = current.application_range if current.status == "configured" else None
    if (current.package or packages.LEGACY.id) != package.id:
        own = None
    return PropertyMethod(
        adapter=package.adapter,
        status="configured",
        package=package.id,
        phase_models=dict(package.phase_models),
        eos=package.eos,
        binary_interaction=package.binary_interaction,
        application_range=own or package.validated,
        versions=versions(),
        benchmark=package.benchmark,
    )


def _enthalpy_ok(process: Process) -> str | None:
    """None when the flowsheet's enthalpy reference is thermo's, else why not."""
    ref = process.flowsheet.units.enthalpy_reference
    if ref is None:
        return "units.enthalpy_reference is not given"
    if ref.state != "ideal_gas" or abs(ref.temperature - 298.15) > 1e-6:
        return f"units.enthalpy_reference is {ref.state} at {ref.temperature:g} K"
    if ref.pressure is not None and abs(ref.pressure - 101.325) > 1e-3:
        return f"units.enthalpy_reference pressure is {ref.pressure:g} kPa(a)"
    return None


def run(workspace: Any, process: Process, case: str, *, write: bool) -> PropsResult:
    """Fill (*write*) or check the calculated properties of every stream in *case*."""
    result = PropsResult()
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

    if process.materials is None:
        add("error", "property-unsupported", f"{MATERIALS_FILE} is missing", [], [])
        result.adapter = _adapter_result(workspace.root, case, result, "refused")
        return result
    try:
        adapter = Adapter(process)
    except Unsupported as failure:
        hint = (
            "pip install 'cheme-as-code[props]'"
            if "not installed" in str(failure)
            else "name a package cheme process props --coverage lists, or remove "
            "property_method.package"
        )
        add("error", failure.rule, str(failure), [], [], hint)
        result.adapter = _adapter_result(workspace.root, case, result, "refused")
        return result
    recorded = method_config(process)
    method = configured_method(process) if write else recorded
    if not write and recorded.status != "configured":
        result.lines.append(
            f"{MATERIALS_FILE}: property_method is a placeholder; run cheme process props --fill"
        )
    if not write and recorded.versions and recorded.versions != versions():
        result.lines.append(
            f"recorded versions {recorded.versions}, installed {versions()}: values are "
            "recalculated with the installed ones"
        )
    process.materials.property_method = method
    no_enthalpy = _enthalpy_ok(process)
    if no_enthalpy:
        result.lines.append(
            f"enthalpy not calculated: {no_enthalpy} (thermo's reference: ideal_gas, 298.15 K, "
            "101.325 kPa)"
        )
    edits: dict[int, dict[str, Any]] = {}
    #: what the adapter result reports: the streams left uncalculated, the values calculated
    unsolved: list[str] = []
    calculated: list[dict[str, Any]] = []
    for i, stream in enumerate(process.flowsheet.streams):
        if stream.kind != "material":
            continue
        loc = ["streams", i, "state", case]
        state = stream.state.get(case)
        constrain = constraining_phase(state)
        old_stale = stale(process, stream, case)
        gathered = gather(process, stream, case)
        problems = gathered.problems
        if gathered.inputs is not None:
            problems = problems or range_problems(process, gathered.inputs)
        outcome = None
        if problems:
            rule, message = problems[0]
            result.refused.append(stream.id)
            unsolved.append(f"{stream.id}: {message}")
            add(
                "warning",
                rule,
                f"stream {stream.id} ({case}): {message}; not calculated, nothing written",
                loc,
                [stream.id],
                "the method's claimed range is in process/materials.yaml property_method",
            )
        elif gathered.inputs is None:
            if state is not None and (state.temperature or state.pressure):
                unsolved.append(f"{stream.id}: missing {', '.join(gathered.missing)}")
                add(
                    "info",
                    "property-not-calculable",
                    f"stream {stream.id} ({case}): missing {', '.join(gathered.missing)}",
                    loc,
                    [stream.id],
                    "give the missing inputs (provenance given or assumed)",
                )
        else:
            try:
                outcome = adapter.flash(gathered.inputs, constrain)
            except Unsupported as failure:
                result.refused.append(stream.id)
                unsolved.append(f"{stream.id}: {failure}")
                add(
                    "warning",
                    failure.rule,
                    f"stream {stream.id} ({case}): {failure}; nothing written",
                    loc,
                    [stream.id],
                    "the method's claimed range is in process/materials.yaml property_method",
                )
        given_phase = state.phase if state and state.phase else None
        if (
            outcome is not None
            and given_phase is not None
            and given_phase.provenance != "calculated"
            and given_phase.value != outcome.phase
        ):
            # the inputs contradict the stated phase: values for the other phase would mislead
            result.refused.append(stream.id)
            unsolved.append(
                f"{stream.id}: phase {given_phase.value} given, {outcome.phase} calculated"
            )
            add(
                "warning",
                "property-phase",
                f"stream {stream.id} ({case}): phase {given_phase.value} "
                f"({given_phase.provenance}), but {outcome.phase} at the given temperature, "
                f"pressure and composition (vapour fraction {outcome.vapor_fraction:.3g}); "
                "nothing written",
                loc + ["phase"],
                [stream.id],
                "correct the temperature or pressure (or the phase) so they agree",
            )
            outcome = None
        if outcome is None:
            if old_stale:
                add(
                    "warning",
                    "calculated-stale",
                    f"stream {stream.id} ({case}): calculated {', '.join(old_stale)} kept but "
                    "stale: they could not be recalculated",
                    loc,
                    [stream.id],
                    "fix the inputs, or remove the stale values",
                )
            continue
        assert state is not None
        fp = fingerprint(
            process, stream, case, constrained=constrain if outcome.constrained else None
        )
        source = f"cheme process props: thermo {versions()['thermo']}, PR"
        if adapter.package is not packages.LEGACY:
            source += f", package {adapter.package.id}"
        exergy_source = EXERGY_SOURCE
        if outcome.constrained:
            assert state.phase is not None
            note = (
                f"phase-constrained {outcome.phase} root ({state.phase.provenance} phase; "
                f"flash {outcome.stable_phase}, dG/RT {outcome.metastability:.2g})"
            )
            source += f", {note}"
            exergy_source += f"; {note}"
            add(
                "info",
                "property-phase-constrained",
                f"stream {stream.id} ({case}): {outcome.phase} ({state.phase.provenance}), but "
                f"{outcome.stable_phase} at the given temperature, pressure and composition; "
                f"calculated on the EOS {outcome.phase} root, metastable by "
                f"{outcome.metastability:.2g} RT",
                loc + ["phase"],
                [stream.id],
                "the stream is close to saturation; the values are marked phase-constrained",
            )
        values = {"molar_mass": outcome.molar_mass, "density": outcome.density}
        if not no_enthalpy:
            values["enthalpy"] = outcome.enthalpy
        # exergy (chemical + physical, dead state 298.15 K, 101.325 kPa): only where every
        # component has a tabulated chemical exergy and the dead state is inside the range
        try:
            values["exergy"], _ = stream_exergy(adapter, gathered.inputs, constrain)
        except Unsupported:
            values["exergy"] = None
        new_calc = dict(state.calculated)
        changed = False
        for name, value in values.items():
            old = state.calculated.get(name)
            if value is None:
                if old is not None and old.provenance == "calculated":
                    add(
                        "warning",
                        "calculated-stale",
                        f"stream {stream.id} ({case}): {name} not calculated for a "
                        f"{outcome.phase} state; the old value is kept and stale",
                        loc,
                        [stream.id],
                    )
                continue
            if old is not None and old.provenance != "calculated":
                result.lines.append(
                    f"{stream.id} {name}: {old.provenance} value kept ({old.value:g}); "
                    f"calculated {value:.6g}"
                )
                continue
            if not write:
                if old is None:
                    add("info", "property-not-filled", f"{stream.id} {name} not filled", loc, [])
                elif abs(old.value - value) > CHECK_REL * max(abs(value), 1.0):
                    add(
                        "warning",
                        "calculated-stale",
                        f"stream {stream.id} ({case}): {name} {old.value:g}, recalculated "
                        f"{value:.6g}",
                        loc,
                        [stream.id],
                        "run cheme process props --fill",
                    )
                continue
            new = Quantity(
                value=_sig(value),
                unit=UNITS[name],
                provenance="calculated",
                origin="correlation",
                source=exergy_source if name == "exergy" else source,
                fingerprint=fp,
            )
            if old != new:
                new_calc[name] = new
                changed = True
        phase = PhaseValue(
            value=outcome.phase,  # type: ignore[arg-type]
            vapor_fraction=round(outcome.vapor_fraction, 4),
            provenance="calculated",
            source=source,
            fingerprint=fp,
        )
        new_phase = state.phase
        # a given or assumed phase stays (it agrees with the flash: checked above)
        own = state.phase is None or state.phase.provenance == "calculated"
        if own and write and state.phase != phase:
            new_phase = phase
            changed = True
        elif own and not write and state.phase is not None and state.phase.value != outcome.phase:
            add(
                "warning",
                "calculated-stale",
                f"stream {stream.id} ({case}): phase {state.phase.value}, recalculated "
                f"{outcome.phase}",
                loc,
                [stream.id],
            )
        result.lines.append(
            f"{stream.id}: {outcome.phase}"
            + (f" vf {outcome.vapor_fraction:.3f}" if outcome.phase == "two-phase" else "")
            + f", M {outcome.molar_mass:.4g} kg/kmol"
            + (f", rho {outcome.density:.4g} kg/m3" if outcome.density is not None else "")
            + ("" if no_enthalpy else f", h {outcome.enthalpy:.6g} kJ/kmol")
            + (
                f" (phase-constrained; flash {outcome.stable_phase}, dG/RT "
                f"{outcome.metastability:.2g})"
                if outcome.constrained
                else ""
            )
        )
        if write and changed:
            # an unchanged phase line is left as written (its quoting and comments)
            edits[i] = {
                "phase": None if new_phase is state.phase else new_phase,
                "calculated": new_calc,
            }
        shown: dict[str, Any] = {
            "phase": outcome.phase,
            "vapor_fraction": round(outcome.vapor_fraction, 4),
        }
        shown |= {
            n: {"value": _sig(v), "unit": UNITS[n]} for n, v in values.items() if v is not None
        }
        written = edits.get(i, {})
        calculated.append(
            {
                "id": stream.id,
                "values": shown,
                "filled": [
                    *(["phase"] if written.get("phase") is not None else []),
                    *(
                        n
                        for n, v in written.get("calculated", {}).items()
                        if v != state.calculated.get(n)
                    ),
                ],
            }
        )
    if write:
        if edits:
            _write_states(workspace.root / FLOWSHEET_FILE, doc, case, edits)
            result.written = len(edits)
        _write_method(workspace.root / MATERIALS_FILE, method)
        result.lines.append(
            f"{FLOWSHEET_FILE}: calculated values written for {len(edits)} stream(s); "
            f"{MATERIALS_FILE}: property_method recorded"
            + (
                f"; {len(result.refused)} stream(s) refused, nothing written for them: "
                + ", ".join(result.refused)
                if result.refused
                else ""
            )
        )
    result.adapter = _adapter_result(
        workspace.root,
        case,
        result,
        "not-converged" if unsolved else "converged",
        unsolved,
        calculated,
    )
    return result


def _adapter_result(
    root: Any,
    case: str,
    result: PropsResult,
    status: str,
    messages: list[str] | None = None,
    streams: list[dict[str, Any]] | None = None,
) -> AdapterResult:
    """The run as an adapter result: one flash per stream, so no iterations; *messages* the
    streams left uncalculated."""
    from importlib.metadata import PackageNotFoundError

    from chemeascode.foundation.provenance import source_revision

    try:
        version = versions()["thermo"]
    except PackageNotFoundError:  # not installed: the run was refused
        version = None
    return AdapterResult(
        case=case,
        status=status,  # type: ignore[arg-type]
        solver=Solver(name="thermo", version=version, method=EOS),
        inputs=source_revision(root, (MATERIALS_FILE, FLOWSHEET_FILE)).as_dict(),
        messages=messages or [],
        streams=streams or [],
        findings=[finding_dict(f) for f in result.findings],
    )


# -- writing ------------------------------------------------------------------------------------


def _flow(data: dict[str, Any]) -> str:
    return yaml.safe_dump(data, default_flow_style=True, sort_keys=False, width=10000).strip()


def _dump(value: Any) -> dict[str, Any]:
    return value.model_dump(mode="json", exclude_none=True, exclude_defaults=False)


def _child(node: Any, key: str) -> tuple[Any, Any] | None:
    for k, v in node.value:
        if getattr(k, "value", None) == key:
            return k, v
    return None


def _last_line(node: Any) -> int:
    """The last line (0-based) of *node*'s text."""
    if isinstance(node, yaml.MappingNode) and not node.flow_style and node.value:
        return _last_line(node.value[-1][1])
    if isinstance(node, yaml.SequenceNode) and not node.flow_style and node.value:
        return _last_line(node.value[-1])
    end = node.end_mark
    return end.line - 1 if end.column == 0 else end.line


def _write_states(path: Any, doc: Any, case: str, edits: dict[int, dict[str, Any]]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    streams = _child(doc, "streams")
    assert streams is not None
    changes: list[tuple[int, int, list[str]]] = []  # (start, end exclusive, new lines)
    for index, new in edits.items():
        stream = streams[1].value[index]
        state = _child(stream, "state")
        target = _child(state[1], case) if state else None
        if target is None or target[1].flow_style or not isinstance(target[1], yaml.MappingNode):
            raise ValueError(
                f"{FLOWSHEET_FILE}: stream {index + 1} has no block-style state.{case}; write "
                "the state as a block mapping"
            )
        mapping = target[1]
        indent = " " * mapping.value[0][0].start_mark.column
        texts = {}
        if new["phase"] is not None:
            texts["phase"] = [f"{indent}phase: {_flow(_dump(new['phase']))}\n"]
        if new["calculated"]:
            texts["calculated"] = [f"{indent}calculated:\n"] + [
                f"{indent}  {name}: {_flow(_dump(q))}\n" for name, q in new["calculated"].items()
            ]
        insert_at = _last_line(mapping) + 1
        for key, text in texts.items():
            found = _child(mapping, key)
            if found is None:
                changes.append((insert_at, insert_at, text))
            else:
                start = found[0].start_mark.line
                changes.append((start, _last_line(found[1]) + 1, text))
    for start, end, text in sorted(changes, key=lambda c: (c[0], c[1]), reverse=True):
        lines[start:end] = text
    path.write_text("".join(lines), encoding="utf-8")


def _write_method(path: Any, method: PropertyMethod) -> None:
    text = path.read_text(encoding="utf-8")
    if not text.endswith("\n"):  # the block's pattern ends every line, the file's last one too
        text += "\n"
    data = method.model_dump(mode="json", exclude_none=True)
    block = yaml.safe_dump(
        {"property_method": data},
        sort_keys=False,
        default_flow_style=False,
        width=100,
        allow_unicode=True,
    )
    found = re.search(r"(?m)^property_method:.*\n(?:(?:[ \t]+.*|[ \t]*)\n)*", text)
    if found:
        text = text[: found.start()] + block + text[found.end() :]
    else:
        text = text.rstrip("\n") + "\n" + block
    path.write_text(text, encoding="utf-8")


# -- coverage -----------------------------------------------------------------------------------


def coverage(process: Process, case: str) -> PropsResult:
    """Which property package the process uses and, per material stream in *case*, whether it
    covers the stream's components (and pairs) and its temperature and pressure, or why not.
    Writes nothing and runs no flash: the phase is decided by ``--fill``/``--check``."""
    result = PropsResult()
    doc = process.flowsheet_doc
    choice = choose_package(process)
    rows: list[dict[str, Any]] = []
    if choice.package is None:
        result.findings.append(
            Finding(
                MATERIALS_FILE,
                "error",
                "cheme.process-property-unsupported",
                choice.reason,
                ids=[],
                hint="name a package listed below, or remove property_method.package",
            )
        )
        result.lines.append(f"property package: none ({choice.reason})")
    else:
        package = choice.package
        claim = package.validated
        result.lines.append(f"property package: {package.id} ({choice.reason})")
        result.lines.append(f"  {package.title}")
        result.lines.append(
            f"  claims phases {', '.join(claim.phases)}; benchmark {package.benchmark.test}"
        )
    result.lines.append(
        "packages: "
        + "; ".join(
            f"{p.id} ({', '.join(sorted(p.components.values()))})" for p in packages.PACKAGES
        )
    )
    for i, stream in enumerate(process.flowsheet.streams):
        if stream.kind != "material":
            continue
        row: dict[str, Any] = {"id": stream.id, "package": None}
        gathered = gather(process, stream, case)
        if gathered.inputs is None:
            why = (
                gathered.problems[0][1]
                if gathered.problems
                else ("missing " + ", ".join(gathered.missing))
            )
            row["status"] = "not-calculable"
            row["reason"] = why
        elif choice.package is None:
            row["status"] = "not-covered"
            row["reason"] = choice.reason
        else:
            problems = range_problems(process, gathered.inputs)
            if problems:
                row["status"] = "not-covered"
                row["rule"] = f"cheme.process-{problems[0][0]}"
                row["reason"] = problems[0][1]
            else:
                row["status"] = "covered"
                row["package"] = choice.package.id
                row["reason"] = "components and state inside the claim (phase: by the flash)"
        if row["status"] == "not-covered" and "rule" not in row:
            row["rule"] = "cheme.process-property-unsupported"
        rows.append(row)
        if row["status"] == "covered":
            result.lines.append(f"  {stream.id}: {row['package']}")
        else:
            result.lines.append(f"  {stream.id}: {row['status']}: {row['reason']}")
            if row["status"] == "not-covered" and choice.package is not None:
                result.findings.append(
                    Finding(
                        FLOWSHEET_FILE,
                        "info",
                        row["rule"],
                        f"stream {stream.id} ({case}): {row['reason']}",
                        line=_yaml_line(doc, ["streams", i, "state", case]),
                        ids=[stream.id],
                        hint="cheme process props --fill refuses it; property packages and "
                        "their benchmarks: the process-design skill",
                    )
                )
    result.coverage = {
        "case": case,
        "package": choice.package.id if choice.package else None,
        "reason": choice.reason,
        "recorded": choice.recorded,
        "streams": rows,
    }
    return result
