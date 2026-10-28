"""Draft datasheets for the equipment list (``cheme datasheets draft``).

Composes three domains: the equipment list (equipment, with the generated layout model read as
data for the main dimensions), the nozzles each P&ID draws for an item
(piping's loader and the nozzle reading of :mod:`chemeascode.domains.spatial.pid_nozzles`) and
the flowsheet streams linked to it (process: :func:`~chemeascode.domains.process.streams.
stream_report`). :func:`chemeascode.domains.equipment.datasheets.draft_datasheet` writes the text.
Only missing files are written; an existing datasheet is never touched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from chemeascode.foundation.findings import Finding
from chemeascode.foundation.workspace import LIST_FILES, Workspace


@dataclass
class DraftResult:
    """What a draft run wrote, kept and could not draft."""

    written: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)
    texts: dict[str, str] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)


def pid_nozzles(workspace: Workspace) -> tuple[dict[str, list[dict[str, Any]]], list[Finding]]:
    """The nozzles of each tag as the P&IDs draw them: ``{tag: [{name, dn, lines, sheet}]}``,
    and a finding for each sheet that could not be loaded. A sheet ``plant.yaml`` declares
    ``status: planned`` and that has no file yet is left out without a finding, as validate
    does: it draws nothing yet."""
    from chemeascode.domains.piping import dexpi_io

    models: list[tuple[str, Any]] = []
    findings: list[Finding] = []
    for path in workspace.pid_files():
        name = workspace.relative(path)
        if not path.is_file() and _planned(workspace, path):
            continue
        try:
            models.append((name, dexpi_io.load(path.read_bytes(), strict=True).model))
        except Exception as failure:  # noqa: BLE001 - reported, the others go on
            findings.append(_unloaded(name, failure))
    found, more = nozzles_of(models)
    return found, findings + more


def _planned(workspace: Workspace, path: Path) -> bool:
    """Whether ``plant.yaml`` declares the sheet file *path* ``status: planned``."""
    return any(
        entry.status == "planned"
        and (file := workspace.sheet_path(entry.file)) is not None
        and file.resolve() == path.resolve()
        for entry in workspace.config().sheets
    )


def _unloaded(name: str, failure: Exception) -> Finding:
    return Finding(
        name,
        "warning",
        "cheme.datasheet-draft-sheet",
        f"{name} could not be loaded, so its nozzles are left out: "
        f"{str(failure).splitlines()[0][:160]}",
        hint="run cheme validate for the reason",
    )


def nozzles_of(
    models: list[tuple[str, Any]],
) -> tuple[dict[str, list[dict[str, Any]]], list[Finding]]:
    """The nozzles of each tag drawn on the loaded P&ID *models* (``(file, model)``)."""
    from chemeascode.domains.spatial.pid_nozzles import sheet_equipment

    found: dict[str, list[dict[str, Any]]] = {}
    findings: list[Finding] = []
    for name, model in models:
        try:
            items = sheet_equipment(model, name)
        except Exception as failure:  # noqa: BLE001 - reported, the others go on
            findings.append(_unloaded(name, failure))
            continue
        for tag, item in items.items():
            entries = found.setdefault(tag, [])
            for nozzle in item.nozzles:
                entries.append(
                    {
                        "name": nozzle.name,
                        "dn": nozzle.dn,
                        "lines": sorted(set(nozzle.lines)),
                        "sheet": name,
                    }
                )
    return found, findings


def linked_streams(root: Path) -> tuple[dict[str, list[dict[str, Any]]], dict, str | None]:
    """The flowsheet streams into and out of the nodes linked to each tag, the units and the
    case (empty without a process that loads)."""
    from chemeascode.domains.process.streams import stream_report

    try:
        report = stream_report(root)
    except Exception:  # noqa: BLE001 - no process: drafts without streams
        return {}, {}, None
    if not report.loaded:
        return {}, {}, None
    owner: dict[str, list[str]] = {}
    for node in report.nodes:
        for link in node["links"]:
            if link.get("target") == "equipment":
                owner.setdefault(node["id"], []).append(link["ref"])
    found: dict[str, list[dict[str, Any]]] = {}
    for stream in report.streams:
        for end, direction in (("to", "in"), ("from", "out")):
            node = str(stream.get(end) or "").split(".", 1)[0]
            for tag in owner.get(node, []):
                found.setdefault(tag, []).append(
                    {
                        "id": stream["id"],
                        "title": stream.get("title") or "",
                        "direction": direction,
                        "state": stream.get("state") or {},
                    }
                )
    return found, report.units, report.case


def draft_missing(root: Path, tags: list[str] | None = None, write: bool = True) -> DraftResult:
    """Draft ``equipment/datasheets/<TAG>.yaml`` for every listed item (or *tags*) that has none;
    with *write*, write them."""
    from chemeascode.domains.equipment.datasheets import DATASHEET_DIR, draft_datasheet

    workspace = Workspace(Path(root))
    result = DraftResult()
    equipment = workspace.parsed_lists(("equipment",)).get("equipment")
    if equipment is None:
        result.findings.append(
            Finding(
                LIST_FILES["equipment"],
                "error",
                "cheme.datasheet-draft-list",
                "no valid equipment list: nothing to draft",
                hint="cheme validate names the problem",
            )
        )
        return result
    listed = {item.tag.strip(): item for item in equipment.equipment}
    for tag in tags or []:
        if tag not in listed:
            result.findings.append(
                Finding(
                    LIST_FILES["equipment"],
                    "error",
                    "cheme.datasheet-draft-list",
                    f"{tag} is not in the equipment list",
                    ids=[tag],
                    hint="draft only listed items",
                )
            )
    wanted = [t for t in listed if not tags or t in tags]
    nozzles, findings = pid_nozzles(workspace)
    result.findings += findings
    streams, units, case = linked_streams(workspace.root)
    model = None
    model_path = workspace.layout_model_file()
    if model_path is not None:
        import yaml

        try:
            loaded = yaml.safe_load(model_path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            loaded = None
        model = loaded if isinstance(loaded, dict) else None
    for tag in wanted:
        name = f"{DATASHEET_DIR}/{tag}.yaml"
        path = workspace.root / name
        if path.exists() or path.with_suffix(".yml").exists():
            result.kept.append(name)
            continue
        text = draft_datasheet(
            listed[tag],
            nozzles.get(tag, []),
            streams.get(tag, []),
            units,
            case,
            LIST_FILES["equipment"],
            model,
        )
        result.texts[name] = text
        if write:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        result.written.append(name)
    return result


# -- outline drawings (cheme datasheets drawing) ---------------------------------------------------


@dataclass
class DrawingResult:
    """The outline drawings of a run: each datasheet's state before it, what was written."""

    states: list[Any] = field(default_factory=list)
    written: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)


def title_meta(workspace: Workspace) -> dict[str, str]:
    """The title block fields of ``plant.yaml`` (none when it does not load)."""
    from chemeascode.domains.equipment.drawing import title_meta as meta

    try:
        return meta(workspace.config())
    except Exception:  # noqa: BLE001 - validate reports plant.yaml; the drawing goes without
        return {}


def drawings(root: Path, tags: list[str] | None = None, write: bool = False) -> DrawingResult:
    """The outline drawing ``equipment/datasheets/<TAG>.svg`` of every valid datasheet (or
    those of *tags*): its state (``current``, ``stale``, ``missing``) and, with *write*, the
    drawings that were not current written."""
    from chemeascode.domains.equipment.datasheets import DATASHEET_DIR, drawing_states

    workspace = Workspace(Path(root))
    result = DrawingResult()
    states = drawing_states(workspace, title_meta(workspace))
    known = {state.tag for state in states}
    for tag in tags or []:
        if tag not in known:
            result.findings.append(
                Finding(
                    DATASHEET_DIR,
                    "error",
                    "cheme.datasheet-drawing-tag",
                    f"no valid datasheet of {tag}",
                    ids=[tag],
                    hint="cheme validate names the problem; cheme datasheets draft --tag " + tag,
                )
            )
    result.states = [s for s in states if not tags or s.tag in tags]
    if write:
        for state in result.states:
            if state.state == "current":
                continue
            path = workspace.root / state.drawing
            path.write_text(state.text, encoding="utf-8")
            result.written.append(state.drawing)
    return result


# -- the datasheets of a plant, for the viewer --------------------------------------------------


@dataclass
class DatasheetEntry:
    """One datasheet file, parsed, with its findings."""

    tag: str
    file: str
    data: dict[str, Any] | None
    sheet: Any | None
    findings: list[Finding]
    drawing: str
    drawing_state: str  # current, stale, missing, none (no valid datasheet)
    drawing_text: str | None

    def summary(self) -> dict[str, Any]:
        from chemeascode.domains.equipment.datasheets import field_counts

        sheet = self.sheet
        levels = {"error": 0, "warning": 0, "info": 0}
        for finding in self.findings:
            levels[finding.level] = levels.get(finding.level, 0) + 1
        return {
            "tag": self.tag,
            "file": self.file,
            "valid": sheet is not None,
            "type": getattr(sheet, "type", None) if sheet else (self.data or {}).get("type"),
            "service": getattr(sheet, "service", "") if sheet else "",
            "draft": bool(getattr(sheet, "draft", False)) if sheet else None,
            "counts": field_counts(self.data or {}),
            "nozzles": len(sheet.nozzles) if sheet else 0,
            "has_dimensions": bool(sheet and sheet.dimensions is not None),
            "has_weights": bool(sheet and sheet.weights is not None),
            "drawing": self.drawing,
            "has_drawing": self.drawing_state in ("current", "stale"),
            "drawing_current": self.drawing_state == "current",
            "findings": levels,
        }


@dataclass
class DatasheetReport:
    """Every datasheet of the plant with the findings that name it (the checks of
    ``cheme validate`` on datasheets), and the listed items without one."""

    entries: list[DatasheetEntry] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    source: Any = None

    def index(self) -> dict[str, Any]:
        return {
            "directory": "equipment/datasheets",
            "datasheets": [entry.summary() for entry in self.entries],
            "missing": self.missing,
            "source": self.source.as_dict() if self.source is not None else None,
        }

    def entry(self, tag: str) -> DatasheetEntry | None:
        return next((e for e in self.entries if e.tag == tag), None)


def datasheet_report(root: Path) -> DatasheetReport:
    """The datasheets of the plant repository at *root* with their findings: schema, markers,
    against the equipment list, the main dimensions against the list and the layout model, the
    nozzle schedule against the P&IDs, the line list and the layout model, filled values whose
    streams have changed, the cases and streams the sheets name, and the outline drawing's
    state."""
    import yaml

    from chemeascode.domains.equipment.datasheets import (
        check_datasheets,
        datasheet_paths,
        dimension_findings,
        drawing_findings,
        drawing_path,
        drawing_states,
        load,
        missing_datasheets,
        nozzle_findings,
        nozzle_location_findings,
        reference_findings,
    )
    from chemeascode.domains.equipment.fill import stale_findings
    from chemeascode.foundation.provenance import source_revision
    from chemeascode.foundation.workspace import LAYOUT_MODEL_FILE

    workspace = Workspace(Path(root))
    report = DatasheetReport()
    parsed = workspace.parsed_lists(("equipment", "lines"))
    equipment = parsed.get("equipment")
    model = None
    model_path = workspace.layout_model_file()
    if model_path is not None:
        try:
            loaded_model = yaml.safe_load(model_path.read_text(encoding="utf-8"))
            model = loaded_model if isinstance(loaded_model, dict) else None
        except yaml.YAMLError:
            model = None
    paths = datasheet_paths(workspace)
    findings = check_datasheets(workspace, equipment)
    findings += stale_findings(workspace)
    findings += reference_findings(workspace)
    findings += dimension_findings(workspace, equipment, model)
    if paths:
        nozzles, unloaded = pid_nozzles(workspace)
        if not unloaded:  # a sheet that does not load could draw more nozzles
            findings += nozzle_findings(workspace, nozzles, parsed.get("lines"))
        else:
            findings += nozzle_findings(workspace, None, parsed.get("lines"))
    if model is not None:
        findings += nozzle_location_findings(workspace, model)
    meta = title_meta(workspace)
    findings += drawing_findings(workspace, meta)
    states = {s.tag: s for s in drawing_states(workspace, meta)}
    for path in paths:
        loaded = load(workspace, path)
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            data = None
        data = data if isinstance(data, dict) else None
        tag = loaded.sheet.tag.strip() if loaded.sheet else str((data or {}).get("tag") or "")
        tag = tag.strip() or path.stem
        state = states.get(tag)
        drawing = workspace.relative(drawing_path(workspace, tag))
        mine = [f for f in findings if f.file in (loaded.name, drawing)]
        report.entries.append(
            DatasheetEntry(
                tag=tag,
                file=loaded.name,
                data=data,
                sheet=loaded.sheet,
                findings=mine,
                drawing=drawing,
                drawing_state=state.state if state else "none",
                drawing_text=state.text if state else None,
            )
        )
    if equipment is not None:
        missing, _ = missing_datasheets(workspace, equipment)
        report.missing = missing
    report.source = source_revision(
        workspace.root,
        [
            "plant.yaml",
            "equipment/equipment-list.yaml",
            "piping/line-list.yaml",
            LAYOUT_MODEL_FILE,
            *(workspace.relative(p) for p in workspace.pid_files() if p.is_file()),
            *(workspace.relative(p) for p in paths),
            *(s.drawing for s in states.values() if s.state != "missing"),
        ],
    )
    return report
