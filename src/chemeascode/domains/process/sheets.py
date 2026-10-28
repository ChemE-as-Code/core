"""The generated process sheets of a plant repository: build them, and check them.

A process sheet is a ``plant.yaml`` sheet with ``kind: bfd`` or ``kind: pfd`` (file default
``process/<id>.xml``). It is generated from ``process/*.yaml`` and never edited by hand.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lxml import etree

from chemeascode.domains.process import GENERATOR_VERSION, SCHEMA, provenance
from chemeascode.foundation.findings import Finding
from chemeascode.foundation.workspace import Workspace


def process_entries(workspace: Workspace) -> list[Any]:
    return [s for s in workspace.config().sheets if s.kind in ("bfd", "pfd")]


def _simulation_findings(
    workspace: Workspace, process: Any, targets: set[Path] | None, files: list[str]
) -> list[Finding]:
    """Schema findings of ``process/simulation.yaml``, and specs for steps the flowsheet lacks.
    Whether the specs suffice is ``cheme process simulate``'s question, not validate's."""
    from chemeascode.domains.process.simulation import SIMULATION_FILE
    from chemeascode.domains.process.simulation.translate import load
    from chemeascode.foundation.yamlsource import _yaml_line

    path = workspace.root / SIMULATION_FILE
    if not path.is_file() or (targets is not None and path.resolve() not in targets):
        return []
    files.append(SIMULATION_FILE)
    sim, doc, found = load(workspace.root)
    if sim is None or process is None:
        return found
    fs = process.flowsheet
    simulated = {n.id for n in [*fs.steps, *(b for b in fs.blocks if not process.inside(b.id))]}
    refined = {b.id for b in fs.blocks if process.inside(b.id)}
    return (
        found
        + origin_findings(SIMULATION_FILE, doc, sim)
        + [
            Finding(
                SIMULATION_FILE,
                "warning",
                "cheme.process-sim-unknown-step",
                f"specs.{node}: block {node} is refined into steps; the steps are simulated"
                if node in refined
                else f"specs.{node}: no step or block {node} in process/flowsheet.yaml",
                line=_yaml_line(doc, ["specs", node]),
                ids=[node],
                hint="give the specs to the steps inside it"
                if node in refined
                else "rename the spec to the step id, or remove it",
            )
            for node in sim.specs
            if node not in simulated
        ]
        + [
            Finding(
                SIMULATION_FILE,
                "warning",
                "cheme.process-sim-unknown-step",
                f"exclude: no step or block {node} in process/flowsheet.yaml",
                line=_yaml_line(doc, ["exclude", i]),
                ids=[node],
                hint="give the id of a step or block",
            )
            for i, node in enumerate(sim.exclude)
            if node not in simulated and node not in refined
        ]
        + [
            Finding(
                SIMULATION_FILE,
                "info",
                "cheme.process-sim-unknown-step",
                f"specs.{node}: {node} is excluded; its specs are not used",
                line=_yaml_line(doc, ["specs", node]),
                ids=[node],
                hint="remove it from exclude to simulate it",
            )
            for node in sim.specs
            if node in process.kinds and any(process.within(node, x) for x in sim.exclude)
        ]
    )


def _id_findings(process: Any) -> list[Finding]:
    """Ids other files refer to (components, reactions, catalysts, cases) that are no stable
    identifier: a warning, as the flowsheet's own ids are errors (``cheme.process-id``)."""
    from chemeascode.domains.chemistry.catalysts import CATALYSTS_FILE
    from chemeascode.domains.chemistry.reactions import REACTIONS_FILE
    from chemeascode.domains.process import FLOWSHEET_FILE, MATERIALS_FILE
    from chemeascode.foundation.schema_base import ID_PATTERN
    from chemeascode.foundation.yamlsource import _yaml_line

    groups = [
        (MATERIALS_FILE, process.materials_doc, "components", process.materials),
        (FLOWSHEET_FILE, process.flowsheet_doc, "cases", process.flowsheet),
        (REACTIONS_FILE, process.reactions_doc, "reactions", process.reactions),
        (CATALYSTS_FILE, process.catalysts_doc, "catalysts", process.catalysts),
    ]
    return [
        Finding(
            file,
            "warning",
            "cheme.contract-id",
            f"{key}[{i}]: id {item.id!r} is not a stable identifier",
            line=_yaml_line(doc, [key, i, "id"]),
            ids=[item.id],
            hint="letters, digits, _ and -, starting with a letter; put free text in name or "
            "title (docs/framework/contract.md)",
        )
        for file, doc, key, owner in groups
        if owner is not None
        for i, item in enumerate(getattr(owner, key, None) or [])
        if not ID_PATTERN.match(item.id)
    ]


def _component_identifier_findings(process: Any) -> list[Finding]:
    """The components' CAS numbers, SMILES and InChIKeys
    (:mod:`~chemeascode.domains.chemistry.identifiers`): warnings."""
    from chemeascode.domains.chemistry.identifiers import identifier_findings
    from chemeascode.domains.process import MATERIALS_FILE

    if process.materials is None:
        return []
    return identifier_findings(MATERIALS_FILE, process.materials_doc, process.materials.components)


def _run_stale_findings(
    workspace: Workspace, process: Any, targets: set[Path] | None
) -> list[Finding]:
    """``cheme.process-sim-run-stale`` for each case of ``process/simulation-run.json`` whose
    model the inputs no longer translate to, when any of the run's inputs is a target.
    Translating needs no simulator, so validate sees what ``simulate --check`` sees; a case
    that does not translate is simulate's to report."""
    from chemeascode.domains.process.simulation import record
    from chemeascode.domains.process.simulation.run import _record_check
    from chemeascode.domains.process.simulation.translate import load, translate

    root = workspace.root
    if process is None or not (root / record.RUN_FILE).is_file():
        return []
    if targets is not None and not any((root / f).resolve() in targets for f in record.RUN_INPUTS):
        return []
    sim, doc, found = load(root)
    if sim is None:
        return []
    cases = {c.id for c in process.flowsheet.cases}
    findings: list[Finding] = []
    for case in sorted(((record.read(workspace.root) or {}).get("cases") or {}).keys() & cases):
        try:
            model = translate(process, sim, doc, case)
        except Exception:  # noqa: BLE001 - a model that does not translate is simulate's to report
            continue
        if model.model is not None:
            findings += _record_check(workspace.root, case, model.fingerprint)
    return findings


def represented(content: bytes) -> dict[str, list[str]]:
    """The connections of generated sheet *content* by id and the streams each represents, as
    their descriptions say (``represents: S6 S7 S8``); empty for XML that does not parse."""
    try:
        root = etree.fromstring(content, etree.XMLParser(resolve_entities=False, no_network=True))
    except etree.XMLSyntaxError:
        return {}
    found: dict[str, list[str]] = {}
    for text in root.iter("String"):
        value = text.text or ""
        if not value.startswith("represents: "):
            continue
        owner = next(text.iterancestors("Object"), None)
        if owner is not None and owner.get("id"):
            found[owner.get("id")] = value.split(";", 1)[0].split()[1:]
    return found


def catalyst_reference_findings(process: Any) -> list[Finding]:
    """The catalysts the reactions, their rate laws and mechanisms name, against
    ``process/catalysts.yaml`` (:func:`chemistry.catalysts.reference_rules`); here and not
    in the generator module ``model.py``, so that built sheets stay current."""
    from chemeascode.domains.chemistry.catalysts import reference_rules

    reactions = process.reactions.reactions if process.reactions is not None else []
    return reference_rules(process.catalysts, reactions, process.reactions_doc)


def _with_origin(
    node: Any, loc: list[Any], ids: list[str]
) -> Iterator[tuple[list[Any], Any, list[str]]]:
    """(location, value, ids) of every value below the parsed *node* that gives an ``origin``,
    with the id of the nearest item holding it."""
    from pydantic import BaseModel

    if isinstance(node, BaseModel):
        if getattr(node, "origin", None) is not None and hasattr(node, "provenance"):
            yield loc, node, ids
            return
        own = getattr(node, "id", None)
        ids = [own] if isinstance(own, str) else ids
        for name, info in type(node).model_fields.items():
            yield from _with_origin(getattr(node, name), [*loc, info.alias or name], ids)
    elif isinstance(node, dict):
        for key, value in node.items():
            yield from _with_origin(value, [*loc, key], ids)
    elif isinstance(node, list | tuple):
        for index, value in enumerate(node):
            yield from _with_origin(value, [*loc, index], ids)


def origin_findings(file: str, doc: Any, parsed: Any) -> list[Finding]:
    """``cheme.provenance-origin`` (warning): a value whose ``origin`` does not refine its
    ``provenance`` (:data:`~chemeascode.foundation.schema_base.ORIGIN_CLASSES`), e.g. a
    calculated vendor figure. *parsed* is the flowsheet or the simulation spec, *doc* its YAML."""
    from chemeascode.foundation.schema_base import ORIGIN_CLASSES
    from chemeascode.foundation.yamlsource import _yaml_line

    return [
        Finding(
            file,
            "warning",
            "cheme.provenance-origin",
            f"{'.'.join(str(step) for step in loc)}: origin {value.origin} does not refine "
            f"provenance {value.provenance}",
            line=_yaml_line(doc, [*loc, "origin"]),
            ids=ids,
            hint=f"{value.origin} refines {' or '.join(ORIGIN_CLASSES[value.origin])}: correct "
            "the provenance or the origin (docs/framework/contract.md)",
        )
        for loc, value, ids in _with_origin(parsed, [], [])
        if value.provenance not in ORIGIN_CLASSES[value.origin]
    ]


def design_basis_reference_findings(
    workspace: Workspace, basis: Any, process: Any
) -> list[Finding]:
    """``cheme.contract-ref`` (warning): a ``terminal`` of a design-basis feed that is no feed
    of the flowsheet, or of a product that is no product of it. *basis* is the parsed design
    basis, *process* the loaded flowsheet; without either nothing is checked."""
    from chemeascode.foundation.yamlsource import _compose, _yaml_line

    path = workspace.list_file("design_basis")
    if basis is None or process is None or path is None:
        return []
    fs = process.flowsheet
    terminals = {"feeds": [f.id for f in fs.feeds], "products": [p.id for p in fs.products]}
    findings: list[Finding] = []
    document = None
    for key, ids in terminals.items():
        other = "products" if key == "feeds" else "feeds"
        for index, entry in enumerate(getattr(basis, key)):
            terminal = entry.get("terminal")
            if terminal is None or str(terminal) in ids:
                continue
            if document is None:
                document = _compose(path)
            what = key[:-1]
            name = f" ({entry['name']})" if entry.get("name") else ""
            hint = f"flowsheet {key}: {', '.join(ids) or 'none'}"
            if str(terminal) in terminals[other]:
                hint = f"{terminal} is a flowsheet {other[:-1]}; {hint}"
            findings.append(
                Finding(
                    workspace.relative(path),
                    "warning",
                    "cheme.contract-ref",
                    f"{key}[{index}]{name}: terminal {terminal!r} is no {what} of "
                    "process/flowsheet.yaml",
                    line=_yaml_line(document, [key, index, "terminal"]),
                    ids=[str(terminal)],
                    hint=hint,
                )
            )
    return findings


def workspace_findings(
    workspace: Workspace, parsed: dict[str, Any], targets: set[Path] | None
) -> tuple[list[Finding], list[str], list[str]]:
    """Findings of the process YAML and of each process sheet, the files read, and the process
    sheets pyDEXPI loaded."""
    from chemeascode.domains.chemistry.catalysts import CATALYSTS_FILE
    from chemeascode.domains.chemistry.reactions import REACTIONS_FILE
    from chemeascode.domains.process import FLOWSHEET_FILE, MATERIALS_FILE
    from chemeascode.domains.process.model import has_process, load, rules

    findings: list[Finding] = []
    files: list[str] = []
    loaded: list[str] = []
    entries = process_entries(workspace)
    yaml_paths = [
        workspace.root / MATERIALS_FILE,
        workspace.root / FLOWSHEET_FILE,
        workspace.root / REACTIONS_FILE,
        workspace.root / CATALYSTS_FILE,
    ]
    wanted = targets is None or any(p.resolve() in targets for p in yaml_paths)
    process = None
    if has_process(workspace.root):
        process, found = load(workspace.root)
        if wanted:
            files += [workspace.relative(p) for p in yaml_paths if p.is_file()]
            findings += found
            if process is not None:
                sheet_ids = [s.id for s in workspace.config().sheets]
                findings += rules(process, parsed, sheet_ids)
                findings += _id_findings(process)
                findings += _component_identifier_findings(process)
                findings += catalyst_reference_findings(process)
                findings += origin_findings(
                    FLOWSHEET_FILE, process.flowsheet_doc, process.flowsheet
                )
    findings += _simulation_findings(workspace, process, targets, files)
    findings += _run_stale_findings(workspace, process, targets)
    findings += design_basis_reference_findings(workspace, parsed.get("design_basis"), process)
    for entry in entries:
        path = workspace.sheet_path(entry.file)
        if path is None or (targets is not None and path.resolve() not in targets):
            continue
        name = workspace.relative(path)
        if not path.is_file():
            planned = entry.status == "planned"
            findings.append(
                Finding(
                    "plant.yaml",
                    "info" if planned else "error",
                    "cheme.sheet-planned" if planned else "cheme.missing-sheet",
                    f"{entry.kind} sheet {entry.id} ({name}) is not generated yet",
                    ids=[entry.id],
                    hint="run cheme process build",
                )
            )
            continue
        files.append(name)
        found, model = check_sheet(path, name)
        findings += found
        if model is not None:
            loaded.append(name)
        expected = None
        if process is not None:
            meta = meta_for(workspace, entry, process)
            expected = provenance.source_fingerprint(process, entry.kind, meta)
        findings += fingerprint_findings(name, path.read_bytes(), expected, entry)
    return findings, files, loaded


def meta_for(workspace: Workspace, entry: Any, process: Any) -> dict[str, str]:
    config = workspace.config()
    project = config.project
    return {
        "plant": config.name,
        "sheet_id": entry.id,
        "sheet_title": entry.title,
        "project_name": (project.name if project else "") or config.name,
        "project_number": project.number if project else "",
        "revision": project.revision if project else "",
        "case": process.flowsheet.default_case(),
    }


def produce(workspace: Workspace, entry: Any, process: Any) -> bytes:
    """The sheet *entry* as ``cheme process build`` writes it."""
    from pydexpi.loaders.xml_serializer import DexpiXmlSerializer

    from chemeascode.domains.process.build import build_model

    meta = meta_for(workspace, entry, process)
    source = provenance.source_fingerprint(process, entry.kind, meta)
    model, _ = build_model(process, entry.kind, {**meta, "source": source})
    content = DexpiXmlSerializer().export_to_bytes(model)
    return provenance.stamp(content, entry.kind, meta["case"], source)


@dataclass
class BuildResult:
    lines: list[str] = field(default_factory=list)
    failed: bool = False


def build(
    workspace: Workspace, keys: list[str] | None = None, *, force: bool = False
) -> BuildResult:
    """Write the process sheets (all, or those named by id or file); refuse when the flowsheet
    has errors, and over a sheet edited by hand unless *force*."""
    from chemeascode.domains.process.model import load, rules

    result = BuildResult()
    entries = process_entries(workspace)
    if keys:
        entries = [e for e in entries if e.id in keys or e.file in keys]
        unknown = set(keys) - {e.id for e in entries} - {e.file for e in entries}
        if unknown:
            result.lines.append(f"not a bfd/pfd sheet in plant.yaml: {', '.join(sorted(unknown))}")
            result.failed = True
            return result
    if not entries:
        result.lines.append(
            "plant.yaml declares no process sheet: add e.g. "
            "{id: BFD, kind: bfd, file: process/BFD.xml, generator: flowsheet} and "
            "{id: PFD, kind: pfd, file: process/PFD.xml, generator: flowsheet} to sheets:"
        )
        result.failed = True
        return result
    process, findings = load(workspace.root)
    if process is not None:
        findings += rules(process, sheet_ids=[s.id for s in workspace.config().sheets])
    errors = [f for f in findings if f.level == "error"]
    if process is None or errors:
        result.lines += [f.format() for f in errors] or ["process/flowsheet.yaml does not exist"]
        result.lines.append("refused: fix the errors above, then run cheme process build")
        result.failed = True
        return result
    for entry in entries:
        path = workspace.sheet_path(entry.file)
        if path is None:
            result.lines.append(f"{entry.file}: outside the repository; not written")
            result.failed = True
            continue
        current = path.read_bytes() if path.is_file() else None
        if current is not None and not force and edited(current):
            result.lines.append(
                f"{entry.file}: refused: edited by hand since it was generated; move the change "
                "into process/*.yaml (or layout overrides), then build with --force"
            )
            result.failed = True
            continue
        content = produce(workspace, entry, process)
        if content == current:
            result.lines.append(f"{entry.file}: up to date")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        result.lines.append(f"{entry.file}: written ({entry.kind}, {_counts(process, entry.kind)})")
    return result


def _counts(process: Any, view: str) -> str:
    fs = process.flowsheet
    shown = [s for s in fs.streams if view == "pfd" or process.crossing(s)]
    parts = [f"{len(fs.blocks)} block(s)"]
    if view == "pfd":
        parts.append(f"{len(fs.steps)} step(s)")
    parts.append(f"{len(shown)} stream(s)")
    return ", ".join(parts)


def edited(content: bytes) -> bool:
    """Whether *content* changed since it was generated (or carries no provenance)."""
    record = provenance.read(content)
    if record is None:
        return True
    try:
        return provenance.output_fingerprint(content) != record.get("output_sha256")
    except etree.XMLSyntaxError:
        return True


#: The one loader warning every valid DEXPI process model produces: the required references
#: between a Port and its ProcessConnection form a cycle, which the loader breaks.
CYCLE_CUT = re.compile(
    r"^Cyclic dependency detected involving object (\S+)\. Its unresolved required references "
    r"are deferred to the reference pass\.$"
)


def is_cycle_cut(entry: Any, model: Any) -> bool:
    """Whether loader report *entry* is the Port/ProcessConnection cycle cut: exactly that
    message, naming the entry's own object, which is a port taking part in a process
    connection of *model* (as its end or as a delegate of one)."""
    found = CYCLE_CUT.match(str(getattr(entry, "message", "")))
    wanted = getattr(entry, "object_id", None)
    if found is None or model is None or found.group(1) != wanted:
        return False
    from pydexpi.pydexpi_classes.pydexpi_classes import Port, ProcessConnection

    def steps(items: list[Any]) -> Any:
        for step in items or []:
            yield step
            yield from steps(step.__dict__.get("subProcessSteps") or [])

    conceptual = getattr(model, "conceptualModel", None)
    for connection in getattr(conceptual, "processConnections", None) or []:
        if connection.id == wanted:  # the cycle broken at the connection's side
            return isinstance(connection, ProcessConnection) and isinstance(
                connection.__dict__.get("source"), Port
            )
    for step in steps(getattr(conceptual, "processSteps", None) or []):
        for port in step.__dict__.get("ports") or []:
            if port.id == wanted and isinstance(port, Port):
                return isinstance(port.__dict__.get("connectorReference"), ProcessConnection)
    return False


def check_sheet(path: Path, name: str) -> tuple[list[Finding], Any]:
    """pyDEXPI's load and validation of one process sheet; the drawing lint and P&ID rules do
    not apply. Only the cycle-cut warning is demoted to info."""
    from pydexpi.loaders.compat import ConversionRefusedError
    from pydexpi.loaders.public import load_xml_with_report
    from pydexpi.validation import validate

    from chemeascode.integrations.pydexpi import _LOADER_LEVELS, _RULE_LEVELS

    content = path.read_bytes()
    try:
        etree.fromstring(content, etree.XMLParser(resolve_entities=False, no_network=True))
    except etree.XMLSyntaxError as failure:
        return [
            Finding(
                name,
                "error",
                "xml.syntax",
                f"not well-formed XML: {failure.msg}",
                line=failure.position[0],
            )
        ], None
    try:
        loaded = load_xml_with_report(content, strict=True)
    except (ConversionRefusedError, ValueError) as failure:
        return [Finding(name, "error", "dexpi.load", f"pyDEXPI could not load it: {failure}")], None
    findings: list[Finding] = []
    cuts: list[Any] = []
    for entry in loaded.errors:
        level = _LOADER_LEVELS.get(str(entry.level), "warning")
        if level == "info":
            continue
        if level == "warning" and is_cycle_cut(entry, loaded.model):
            cuts.append(entry)
            continue
        findings.append(
            Finding(
                name,
                level,
                "dexpi.load",
                entry.message,
                line=entry.line,
                ids=[entry.object_id] if entry.object_id else [],
            )
        )
    if cuts:  # one line per sheet: the cut is expected on every connected port
        findings.insert(
            0,
            Finding(
                name,
                "info",
                "dexpi.load",
                f"{len(cuts)} port/connection reference cycles cut by the loader (first one named)",
                line=cuts[0].line,
                ids=[cuts[0].object_id] if cuts[0].object_id else [],
                hint="the Port/ProcessConnection reference cycle every process model has",
            ),
        )
    for issue in validate(loaded.model):
        findings.append(
            Finding(
                name,
                _RULE_LEVELS.get(issue.level_of_recommendation.value, "warning"),
                issue.applied_rule_id,
                issue.short_description,
                ids=list(issue.affected_component_ids),
                hint=issue.long_description
                if issue.long_description != issue.short_description
                else "",
            )
        )
    return findings, loaded.model


def fingerprint_findings(
    name: str, content: bytes, expected_source: str | None, entry: Any
) -> list[Finding]:
    """``generated-edited``, ``generated-version`` and ``generated-outdated`` for one sheet."""
    record = provenance.read(content)
    build = f"cheme process build {entry.id}"
    if record is None and b"<!-- plantcode-process " in content:
        return [
            Finding(
                name,
                "error",
                "cheme.generated-edited",
                f"{name} carries the provenance record of plantcode, the package's name before "
                "0.7.0, not a cheme-as-code one",
                ids=[entry.id],
                hint=f"regenerate it under the new name: {build} --force",
            )
        ]
    if record is None:
        return [
            Finding(
                name,
                "error",
                "cheme.generated-edited",
                f"{name} is declared generated (kind {entry.kind}) but carries no cheme-as-code "
                "provenance record",
                ids=[entry.id],
                hint=f"never edit a generated sheet: change process/*.yaml, then {build} --force",
            )
        ]
    found = []
    if edited(content):
        found.append(
            Finding(
                name,
                "error",
                "cheme.generated-edited",
                f"{name} was edited by hand since it was generated (its XML no longer matches "
                "the recorded output fingerprint)",
                ids=[entry.id],
                hint="move the change into process/*.yaml or layout overrides, then "
                f"{build} --force",
            )
        )
    code = record.get("generator_sha256")
    if record.get("generator_version") != GENERATOR_VERSION or record.get("schema") != SCHEMA:
        found.append(
            Finding(
                name,
                "warning",
                "cheme.generated-version",
                f"{name} was generated by process generator {record.get('generator_version')} "
                f"({record.get('schema')}); this cheme-as-code writes {GENERATOR_VERSION} "
                f"({SCHEMA})",
                ids=[entry.id],
                hint=f"regeneration required: {build}",
            )
        )
    elif code is not None and code != provenance.generator_fingerprint():
        found.append(
            Finding(
                name,
                "warning",
                "cheme.generated-version",
                f"{name} was generated by other process generator code (generator "
                f"{GENERATOR_VERSION}, code {code[:12]}; this cheme-as-code has code "
                f"{provenance.generator_fingerprint()[:12]})",
                ids=[entry.id],
                hint=f"regeneration required: {build}",
            )
        )
    elif expected_source is not None and record.get("source_sha256") != expected_source:
        found.append(
            Finding(
                name,
                "warning",
                "cheme.generated-outdated",
                f"{name} is outdated: process/*.yaml changed since it was generated",
                ids=[entry.id],
                hint=f"run {build}",
            )
        )
    return found
