"""The loop summary and the sequence report (``cheme control report``, ``GET /api/control``).

:func:`control_report` reads the loop register, the sequences, the narrative and the control
philosophy and returns them with their review status (``foundation.reviews.coverage``), the
``cheme.control-*`` findings and the source revision of the files, so a caller can tell later
whether the report still applies. :func:`write_report` writes ``build/control-loops.html`` and
``.csv`` and ``build/control-sequences.html``. A plant without control records gets an empty
report (``present`` False), never an empty page to fill.
"""

from __future__ import annotations

import csv
import html
import io
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from chemeascode.foundation.findings import Finding
from chemeascode.foundation.provenance import SourceRevision, source_revision
from chemeascode.foundation.workspace import LIST_FILES, Workspace

#: The control records a report rests on, by kind.
CONTROL_FILES = {
    "loops": LIST_FILES["loops"],
    "sequences": LIST_FILES["sequences"],
    "interlocks": LIST_FILES["interlocks"],
    "narrative": "process/narrative.md",
    "philosophy": "control/philosophy.md",
}


@dataclass
class ControlReport:
    """The control records of a plant, as the reports and the viewer show them."""

    root: Path
    #: Each control file that exists: its path, kind, review status and why.
    files: list[dict[str, Any]] = field(default_factory=list)
    loops: list[dict[str, Any]] = field(default_factory=list)
    sequences: list[dict[str, Any]] = field(default_factory=list)
    documents: list[dict[str, Any]] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    source: SourceRevision = field(default_factory=lambda: SourceRevision(None))

    @property
    def present(self) -> bool:
        """Whether the plant has any loop, sequence or control document."""
        return any(f["kind"] != "interlocks" for f in self.files)

    def as_dict(self) -> dict[str, Any]:
        return {
            "present": self.present,
            "files": self.files,
            "loops": self.loops,
            "sequences": self.sequences,
            "documents": self.documents,
            "findings": [{**asdict(f), "id": f.id} for f in self.findings],
            "source": self.source.as_dict(),
        }


# ---------------------------------------------------------------------------
# Text of the structured records
# ---------------------------------------------------------------------------


def _amount(amount: Any) -> str:
    return f"{amount.value:g} {amount.unit}"


def describe(condition: Any) -> str:
    """A condition in words: ``LT-102 > 30 % for 30 s``, ``2oo3(a, b, c)``, ``(a AND b)``."""
    if condition is None:
        return ""
    if condition.all_ is not None:
        text = "(" + " AND ".join(describe(c) for c in condition.all_) + ")"
    elif condition.any_ is not None:
        text = "(" + " OR ".join(describe(c) for c in condition.any_) + ")"
    elif condition.vote is not None:
        vote = condition.vote
        text = f"{vote.k}oo{len(vote.of)}(" + ", ".join(describe(c) for c in vote.of) + ")"
    elif condition.text is not None:
        text = f"[as text, not checked: {condition.text}]"
    elif condition.unresolved is not None:
        text = f"[unresolved: {condition.unresolved}]"
    else:
        what = next(
            f"{kind} {value}" if kind in ("interlock", "sequence", "step") else value
            for kind in ("tag", "loop", "interlock", "sequence", "step")
            if (value := getattr(condition, kind))
        )
        text = f"{what} {condition.state}".strip()
    if condition.delay is not None:
        text += f" for {_amount(condition.delay)}"
    if condition.deadband is not None:
        text += f" (dead band {_amount(condition.deadband)})"
    return text


def target_text(target: Any) -> str:
    """``setpoint 3600 kg/h (given: basis of design)``, or what is unresolved."""
    if target.value is None:
        return f"{target.kind} ? ({target.unresolved or 'not given'})"
    text = f"{target.kind} {target.value:g} {target.unit or ''}".rstrip()
    if target.provenance:
        text += f" ({target.provenance}" + (f": {target.source}" if target.source else "") + ")"
    scope = [*target.modes, *target.cases]
    return text + (f" [{', '.join(scope)}]" if scope else "")


def action_text(action: Any) -> str:
    who = f" ({action.by})" if action.by else ""
    if action.text is not None:
        return f"[as text: {action.text}]{who}"
    if action.loop is not None:
        if action.action == "setpoint":
            return f"{action.loop} {target_text(action.setpoint)}{who}"
        return f"{action.loop} to {action.action}{who}"
    if action.sequence is not None:
        return f"run {action.sequence}{who}"
    return f"{action.action} {action.tag}{who}"


def _link_text(link: Any) -> str:
    other = link.loop or link.tag
    if link.type == "cascade":
        return f"cascade from {other}"
    if link.type == "ratio":
        return f"ratio {link.ratio:g} to {other}" if link.ratio else f"ratio to {other}"
    if link.type == "override":
        return f"override with {other}" + (f" ({link.select} select)" if link.select else "")
    return f"feedforward from {other}"


def _element_text(element: Any) -> str:
    text = element.tag + (f" fail {element.fail}" if element.fail else " fail ?")
    if element.range is not None:
        text += f" at {element.range[0]:g}-{element.range[1]:g} %"
    if element.travel is not None:
        text += f" travel {element.travel[0]:g}-{element.travel[1]:g} %"
    return text


def _counts(findings: list[Finding], owner: str, steps: bool = False) -> dict[str, int]:
    """Findings about *owner* (``loop FIC-101``) by level; with *steps*, also about its steps
    (``sequence SEQ-1 step S2``)."""
    counts = {"error": 0, "warning": 0, "info": 0}
    for finding in findings:
        first = finding.ids[0] if finding.ids else ""
        bare = owner.split(" ", 1)[1]
        if first in (owner, bare) or steps and first.startswith(owner + " step "):
            counts[finding.level] += 1
    return counts


def loop_row(loop: Any, findings: list[Finding]) -> dict[str, Any]:
    owner = f"loop {loop.id}"
    return {
        "id": loop.id,
        "title": loop.title,
        "section": loop.section,
        "variable": loop.variable,
        "measurement": [m.tag for m in loop.measurement],
        "controller": loop.controller,
        "action": loop.action,
        "final_elements": [_element_text(e) for e in loop.final_elements],
        "targets": [target_text(t) for t in loop.targets],
        "modes": loop.modes,
        "normal_mode": loop.normal_mode,
        "links": [_link_text(link) for link in loop.links],
        "alarms": [f"{a.tag} {a.condition}: {a.response or '?'}" for a in loop.alarms],
        "interlocks": loop.interlocks,
        "unresolved": loop.unresolved,
        "findings": _counts(findings, owner),
        "record": loop.model_dump(by_alias=True, exclude_defaults=True),
    }


def sequence_row(sequence: Any, findings: list[Finding]) -> dict[str, Any]:
    owner = f"sequence {sequence.id}"
    abort = sequence.abort
    reset = sequence.reset
    return {
        "id": sequence.id,
        "title": sequence.title,
        "mode": sequence.mode,
        "section": sequence.section,
        "permissives": [describe(c) for c in sequence.permissives],
        "interlocks": sequence.interlocks,
        "steps": [
            {
                "id": step.id,
                "title": step.title,
                "entry": describe(step.entry),
                "actions": [action_text(a) for a in step.actions],
                "complete": describe(step.complete),
                "timeout": (
                    f"{_amount(step.timeout)} -> {step.on_timeout or '?'}" if step.timeout else ""
                ),
                "next": step.next or "",
                "operator": step.operator,
            }
            for step in sequence.steps
        ],
        "abort": None
        if abort is None
        else {
            "condition": describe(abort.condition),
            "actions": [action_text(a) for a in abort.actions],
            "then": abort.then,
            "notes": abort.notes,
        },
        "reset": None
        if reset is None
        else {
            "latching": reset.latching,
            "manual": reset.manual,
            "condition": describe(reset.condition),
            "restart": describe(reset.restart),
        },
        "unresolved": sequence.unresolved,
        "findings": _counts(findings, owner, steps=True),
        "record": sequence.model_dump(by_alias=True, exclude_defaults=True),
    }


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------


def has_control_texts(texts: dict[str, str | None]) -> bool:
    """Whether files with these texts (by path, None when absent) document control: a loop or
    a sequence (or a register that does not load), or a narrative or philosophy changed from
    its template; ``has_control`` of ``GET /api/repo``. The same rule as
    ``register.has_records``, on texts, so it works on any revision."""
    import yaml
    from pydantic import ValidationError

    from chemeascode.domains.control.documents import TEMPLATE_FINGERPRINTS
    from chemeascode.domains.control.schemas import LoopList, SequenceList
    from chemeascode.foundation.provenance import content_fingerprint

    for kind, model in (("loops", LoopList), ("sequences", SequenceList)):
        text = texts.get(CONTROL_FILES[kind])
        if text is None:
            continue
        try:
            if getattr(model.model_validate(yaml.safe_load(text) or {}), kind):
                return True
        except (ValidationError, yaml.YAMLError, AttributeError, TypeError):
            return True  # a register that does not load: the page shows why
    for kind in ("narrative", "philosophy"):
        path = CONTROL_FILES[kind]
        text = texts.get(path)
        if text is not None and content_fingerprint(text.encode()) != TEMPLATE_FINGERPRINTS[path]:
            return True
    return False


def _parsed(workspace: Workspace) -> dict[str, Any]:
    """The lists the control checks read; one that does not parse is left out."""
    kinds = ("equipment", "lines", "instruments", "piping_items", "interlocks", "loops")
    return workspace.parsed_lists((*kinds, "sequences"))


def control_report(root: Path) -> ControlReport:
    """The control records of the plant repository at *root*, with their review status and
    findings. Raises ``NotAPlantRepository`` without a ``plant.yaml``."""
    from chemeascode.domains.control.documents import load_documents
    from chemeascode.domains.control.register import (
        control_findings,
        has_records,
        interlock_time_findings,
    )
    from chemeascode.domains.piping.sheet_query import load_sheets
    from chemeascode.foundation.reviews import coverage, load_records

    workspace = Workspace(root) if (root / "plant.yaml").is_file() else Workspace.find(root)
    report = ControlReport(workspace.root)
    parsed = _parsed(workspace)
    documents = load_documents(workspace)
    present = {kind: path for kind, path in CONTROL_FILES.items() if (root / path).is_file()}
    report.source = source_revision(workspace.root, present.values())
    if not has_records(workspace, parsed, documents):
        return report  # nothing, or only the empty files of the template
    # The template's empty files are not shown: a register without entries, a document whose
    # front matter lists nothing.
    for kind in ("loops", "sequences"):
        if kind in present and kind in parsed and not getattr(parsed[kind], kind):
            del present[kind]
    for kind in ("narrative", "philosophy"):
        if kind in present and not documents[kind].started:
            del present[kind]
            del documents[kind]
    records = load_records(workspace)
    for kind, path in present.items():
        report.files.append({"path": path, "kind": kind, **coverage(workspace, path, records)})
    loaded = load_sheets(workspace)
    sheets = {s.name: (s.model, None) for s in loaded if s.model is not None}
    partial = any(s.model is None for s in loaded)
    report.findings = control_findings(workspace, sheets, parsed, partial, documents)
    report.findings += interlock_time_findings(workspace, parsed)
    for kind in ("loops", "sequences"):
        if kind in present and kind not in parsed:
            report.findings.append(
                Finding(
                    present[kind],
                    "error",
                    "yaml.schema",
                    f"{present[kind]} does not follow its schema; it is not reported",
                    line=1,
                    hint="run `cheme validate`",
                )
            )
    if "loops" in parsed:
        report.loops = [loop_row(loop, report.findings) for loop in parsed["loops"].loops]
    if "sequences" in parsed:
        report.sequences = [sequence_row(s, report.findings) for s in parsed["sequences"].sequences]
    for kind, document in documents.items():
        front = document.front
        entry: dict[str, Any] = {"path": document.name, "kind": kind, "valid": front is not None}
        if front is not None and kind == "narrative":
            entry["sections"] = [s.model_dump(exclude_defaults=True) for s in front.sections]
        elif front is not None:
            entry["objectives"] = [o.model_dump(exclude_defaults=True) for o in front.objectives]
            entry["failures"] = [f.model_dump(exclude_defaults=True) for f in front.failures]
        if front is not None:
            entry["unresolved"] = front.unresolved
        entry["headings"] = document.headings
        report.documents.append(entry)
    report.findings.sort(key=lambda f: (f.file, f.line or 0))
    return report


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

_STYLE = (
    "<style>body{font:13px system-ui,sans-serif;margin:16px;max-width:1400px}"
    "table{border-collapse:collapse;margin:8px 0}td,th{border:1px solid #bbb;padding:3px 6px;"
    "text-align:left;vertical-align:top}.drafted{background:#ffd}.reviewed{background:#def}"
    ".accepted{background:#dfd}.note{color:#555}.n{white-space:nowrap}</style>"
)
_LOOP_COLUMNS = (
    "id",
    "title",
    "section",
    "variable",
    "measurement",
    "controller",
    "action",
    "final_elements",
    "targets",
    "modes",
    "links",
    "interlocks",
    "alarms",
    "unresolved",
)


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "; ".join(str(v) for v in value)
    return str(value)


def loops_csv(report: ControlReport) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow([*_LOOP_COLUMNS, "errors", "warnings", "info"])
    for row in report.loops:
        counts = row["findings"]
        writer.writerow(
            [_cell(row[c]) for c in _LOOP_COLUMNS]
            + [counts["error"], counts["warning"], counts["info"]]
        )
    return out.getvalue()


def _header(report: ControlReport, title: str, kinds: tuple[str, ...]) -> str:
    esc = html.escape
    rows = "".join(
        f"<tr><td>{esc(f['path'])}</td><td class={f['status']}>{f['status']}</td>"
        f"<td>{esc(f.get('detail', ''))}</td></tr>"
        for f in report.files
        if f["kind"] in kinds
    )
    commit = report.source.commit or "not committed"
    dirty = f", uncommitted: {', '.join(report.source.dirty)}" if report.source.dirty else ""
    return (
        f"<!doctype html><meta charset=utf-8><title>{esc(title)}</title>{_STYLE}"
        f"<h1>{esc(title)}</h1><p class=note>PROPOSED control intent, not an implementation. "
        "Status from the review records: drafted, reviewed, accepted. Source: "
        f"{esc(commit[:12])}{esc(dirty)}.</p>"
        f"<table><tr><th>file</th><th>status</th><th>why</th></tr>{rows}</table>"
    )


def _findings_html(report: ControlReport, files: tuple[str, ...]) -> str:
    esc = html.escape
    shown = [f for f in report.findings if f.file in files]
    if not shown:
        return "<p>No findings.</p>"
    rows = "".join(
        f"<tr><td class=n>{esc(f.file)}:{f.line or ''}</td><td>{f.level}</td>"
        f"<td class=n>{esc(f.rule)}</td><td>{esc(f.message)}</td></tr>"
        for f in shown
    )
    return (
        "<h2>Findings</h2><table><tr><th>where</th><th>level</th><th>rule</th><th>message</th>"
        f"</tr>{rows}</table>"
    )


def loops_html(report: ControlReport, title: str) -> str:
    esc = html.escape
    head = "".join(f"<th>{c.replace('_', ' ')}</th>" for c in _LOOP_COLUMNS)
    body = []
    for row in report.loops:
        counts = row["findings"]
        flags = ", ".join(f"{n} {level}" for level, n in counts.items() if n) or ""
        cells = "".join(f"<td>{esc(_cell(row[c]))}</td>" for c in _LOOP_COLUMNS)
        body.append(f"<tr>{cells}<td class=n>{esc(flags)}</td></tr>")
    table = f"<table><tr>{head}<th>findings</th></tr>{''.join(body)}</table>"
    files = (CONTROL_FILES["loops"],)
    return (
        _header(report, title, ("loops", "narrative", "philosophy"))
        + "<p class=note>action: direct (output rises with the measurement) or reverse; fail: "
        "position on loss of signal, power or air; ? not known yet.</p>"
        + table
        + _findings_html(report, files)
    )


def sequences_html(report: ControlReport, title: str) -> str:
    esc = html.escape
    parts = [_header(report, title, ("sequences", "interlocks"))]
    for seq in report.sequences:
        parts.append(
            f"<h2>{esc(seq['id'])} {esc(seq['title'])}</h2><p>mode {esc(seq['mode'])}"
            + (f", section {esc(seq['section'])}" if seq["section"] else "")
            + (
                f"; trips (C&amp;E): {esc(', '.join(seq['interlocks']))}"
                if seq["interlocks"]
                else ""
            )
            + "</p>"
        )
        if seq["permissives"]:
            items = "".join(f"<li>{esc(p)}</li>" for p in seq["permissives"])
            parts.append(f"<p>Start permissives:</p><ul>{items}</ul>")
        rows = "".join(
            f"<tr><td>{esc(s['id'])}</td><td>{esc(s['title'])}</td><td>{esc(s['entry'])}</td>"
            f"<td>{esc('; '.join(s['actions']))}</td><td>{esc(s['complete'] or '?')}</td>"
            f"<td>{esc(s['timeout'])}</td><td>{esc(s['next'])}</td>"
            f"<td>{esc(s['operator'])}</td></tr>"
            for s in seq["steps"]
        )
        parts.append(
            "<table><tr><th>step</th><th>title</th><th>entry</th><th>actions</th>"
            "<th>complete when</th><th>timeout</th><th>next</th><th>operator</th></tr>"
            f"{rows}</table>"
        )
        abort, reset = seq["abort"], seq["reset"]
        if abort is None:
            parts.append("<p>Abort: not stated.</p>")
        else:
            text = abort["condition"] or "on a trip or by the operator"
            text += f"; {'; '.join(abort['actions'])}" if abort["actions"] else ""
            text += f"; then {abort['then']}" if abort["then"] else ""
            text += f" ({abort['notes']})" if abort["notes"] else ""
            parts.append(f"<p>Abort: {esc(text)}.</p>")
        if reset is not None:
            latching = {True: "latching", False: "not latching", None: "latching ?"}
            manual = {True: "manual reset", False: "automatic reset", None: "reset ?"}
            text = f"{latching[reset['latching']]}, {manual[reset['manual']]}"
            text += f", when {reset['condition']}" if reset["condition"] else ""
            text += f"; restart when {reset['restart']}" if reset["restart"] else ""
            parts.append(f"<p>Reset: {esc(text)}.</p>")
        for item in seq["unresolved"]:
            parts.append(f"<p class=note>Open: {esc(item)}</p>")
    parts.append(_findings_html(report, (CONTROL_FILES["sequences"],)))
    return "".join(parts)


def write_report(
    report: ControlReport, workspace: Workspace, out: Path | None = None
) -> list[Path]:
    """``control-loops.html``, ``control-loops.csv`` and ``control-sequences.html`` in *out*
    (default ``build/``); a file only for what the plant has."""
    folder = out or workspace.build_dir()
    folder.mkdir(parents=True, exist_ok=True)
    name = workspace.config().name
    written = []
    kinds = {f["kind"] for f in report.files}
    if "loops" in kinds:
        path = folder / "control-loops.html"
        path.write_text(loops_html(report, f"Control loops: {name}"), encoding="utf-8")
        csv_path = folder / "control-loops.csv"
        csv_path.write_text(loops_csv(report), encoding="utf-8")
        written += [path, csv_path]
    if "sequences" in kinds:
        path = folder / "control-sequences.html"
        path.write_text(sequences_html(report, f"Operating sequences: {name}"), encoding="utf-8")
        written.append(path)
    return written
