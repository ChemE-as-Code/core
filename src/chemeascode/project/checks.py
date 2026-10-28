"""Engineering-step gates: ``checks/checks.yaml`` evaluated into ``checks/status.json``."""

from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import PurePosixPath
from typing import Any

import yaml

from chemeascode.foundation.acceptance import acceptance
from chemeascode.foundation.findings import _SEVERITY, Finding, rule_matches
from chemeascode.foundation.schemas.checks import Check, CheckList
from chemeascode.foundation.workspace import Workspace
from chemeascode.project.validate import validate_workspace


@dataclass
class CheckStatus:
    id: str
    title: str
    stage: str
    status: str  # pass, fail, n/a
    detail: str = ""
    #: What a passing gate rests on; a review gate: path, reviewed_commit, reviewer(_kind).
    evidence: dict[str, Any] = field(default_factory=dict)


def _glob_inside(workspace: Workspace, pattern: str) -> bool | None:
    """Whether *pattern* matches a file inside the repository; ``None`` when it may not be used."""
    parts = PurePosixPath(pattern.replace("\\", "/")).parts
    if not pattern or PurePosixPath(pattern).is_absolute() or ".." in parts:
        return None
    return any(workspace.contains(match) for match in workspace.root.glob(pattern))


def _run_command(
    command: str, workspace: Workspace, timeout: float | None
) -> subprocess.CompletedProcess[str]:
    """Run *command* in a shell; on timeout kill its whole process group, then re-raise."""
    with subprocess.Popen(
        command,
        shell=True,
        cwd=workspace.root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,  # its own process group, so children die with it
    ) as process:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError):
                if hasattr(os, "killpg"):
                    os.killpg(process.pid, signal.SIGKILL)
                else:  # Windows: no process groups here
                    process.kill()
            process.communicate()
            raise
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


class _Context:
    """What several gates of one run share: the validation report and the loaded sheets."""

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace
        self._validation: dict[bool, Any] = {}
        self._sheets: list[Any] | None = None
        self._items: dict[str, list[Any]] = {}
        self._records: list[Any] | None = None

    def validation(self, generators: bool = False) -> Any:
        """The ``validate`` report; with *generators*, also running the P&ID generators, as
        ``cheme validate`` does (``cheme.generated-sheet-drift``)."""
        if generators not in self._validation:
            self._validation[generators] = (
                validate_workspace(self.workspace, generators=True)
                if generators
                else validate_workspace(self.workspace)
            )
        return self._validation[generators]

    def sheets(self) -> list[Any]:
        """Every sheet, loaded with pyDEXPI (see :mod:`chemeascode.domains.piping.sheet_query`)."""
        from chemeascode.domains.piping.sheet_query import load_sheets, sheet_items

        if self._sheets is None:
            self._sheets = load_sheets(self.workspace)
            for sheet in self._sheets:
                if sheet.model is not None:
                    self._items[sheet.name] = sheet_items(sheet.model, sheet.name)
        return self._sheets

    def items(self, sheet: Any) -> list[Any]:
        return self._items.get(sheet.name, [])

    def records(self) -> list[Any]:
        """The review records (see :mod:`chemeascode.foundation.reviews`)."""
        from chemeascode.foundation.reviews import load_records

        if self._records is None:
            self._records = load_records(self.workspace)
        return self._records


def _on_sheet(check: Check, context: _Context) -> tuple[str, str]:
    """``kind: on-sheet``: the tags and classes, by printed tag in the loaded model."""
    from chemeascode.domains.piping.sheet_query import class_matches, matches_sheet

    sheets = context.sheets()
    wanted = [check.sheet] if check.sheet else list(check.sheets)
    problems: list[str] = []
    if wanted:
        groups = []
        for name in wanted:
            found = [s for s in sheets if matches_sheet(s, name)]
            if not found:
                known = ", ".join(s.sheet_id for s in sheets) or "none"
                problems.append(f"{name}: no such sheet (sheets: {known})")
                continue
            groups.append((name, found))
    else:
        groups = [("any sheet", sheets)]
    for label, group in groups:
        unloaded = [s for s in group if s.model is None]
        for sheet in unloaded:
            problems.append(f"{sheet.sheet_id}: not loaded ({sheet.error})")
        items = [
            item for sheet in group if sheet.model is not None for item in context.items(sheet)
        ]
        missing = []
        loose = []
        for tag in check.tags:
            drawn = [item for item in items if item.tag == tag.strip()]
            if not drawn:
                missing.append(tag)
            elif check.connected and not any(item.connected for item in drawn):
                loose.append(tag)
        if missing:
            problems.append(f"{label}: {', '.join(missing)} not drawn")
        if loose:
            problems.append(f"{label}: {', '.join(loose)} drawn but not connected")
        for name in check.classes:
            of_class = [item for item in items if class_matches(item, name)]
            counted = [item for item in of_class if item.connected or not check.connected]
            if len(counted) >= check.min_count:
                continue
            need = f"{check.min_count} " if check.min_count > 1 else ""
            if check.connected and of_class:
                unconnected = ", ".join(i.tag for i in of_class if not i.connected)
                problems.append(
                    f"{label}: {len(counted)} connected {name} of {need or '1 '}needed"
                    f" ({unconnected} not connected)"
                )
            else:
                problems.append(f"{label}: {len(counted)} {name} drawn, {need or '1 '}needed")
    if problems:
        return "fail", "; ".join(problems)
    return "pass", ""


def _datasheets(workspace: Workspace, require: list[str] | None = None) -> tuple[str, str]:
    """``kind: datasheets``: one valid datasheet per equipment-list item, and what *require*
    asks of each (:func:`~chemeascode.domains.equipment.datasheets.datasheet_gate`)."""
    from chemeascode.domains.equipment.datasheets import DATASHEET_DIR, missing_datasheets
    from chemeascode.domains.equipment.schemas.equipment import EquipmentList

    path = workspace.list_file("equipment")
    if path is None:
        return "fail", "no equipment/equipment-list.yaml"
    try:
        equipment = EquipmentList.model_validate(
            yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        )
    except (ValueError, yaml.YAMLError):
        return "fail", "equipment/equipment-list.yaml is invalid; run `cheme validate`"
    if not equipment.equipment:
        return "fail", "the equipment list is empty"
    missing, invalid = missing_datasheets(workspace, equipment)
    from chemeascode.domains.equipment.datasheets import draft_datasheets

    drafts = draft_datasheets(workspace)
    problems = []
    if drafts:
        shown = ", ".join(drafts[:10]) + (
            f" and {len(drafts) - 10} more" if len(drafts) > 10 else ""
        )
        problems.append(f"draft datasheets (draft: true) for {shown}: complete them")
    if missing:
        shown = ", ".join(missing[:10]) + (
            f" and {len(missing) - 10} more" if len(missing) > 10 else ""
        )
        problems.append(f"no datasheet in {DATASHEET_DIR}/ for {shown}")
    if invalid:
        problems.append("invalid datasheet for " + ", ".join(invalid) + "; run `cheme validate`")
    from chemeascode.domains.equipment.datasheets import open_tbd

    still = open_tbd(workspace)
    if still:
        tags = sorted(still)
        shown = ", ".join(tags[:10]) + (f" and {len(tags) - 10} more" if len(tags) > 10 else "")
        problems.append(
            f"final datasheets with TBD fields for {shown}: give the values, or mark them "
            "supplier / not_applicable with a reason"
        )
    if require:
        from chemeascode.domains.equipment.datasheets import datasheet_gate
        from chemeascode.project.datasheets import title_meta

        problems += datasheet_gate(workspace, list(require), title_meta(workspace))
    return ("fail", "; ".join(problems)) if problems else ("pass", "")


def _process_links(check: Check, context: _Context) -> tuple[str, str]:
    """``kind: process-links``: no ``cheme.process-link-unresolved`` left (see
    :func:`chemeascode.domains.process.model.link_problem`); at ``level: warning`` the gate only
    reports."""
    from chemeascode.domains.process.model import has_process

    if not has_process(context.workspace.root):
        return "pass", "no process/flowsheet.yaml: no links to resolve"
    unresolved = [
        f
        for f in context.validation().findings
        if f.rule == "cheme.process-link-unresolved"
        and f.accepted is None
        and acceptance(check.accept, f) is None
    ]
    if not unresolved:
        return "pass", ""
    shown = "; ".join(f.message for f in unresolved[:3])
    more = f" and {len(unresolved) - 3} more" if len(unresolved) > 3 else ""
    detail = (
        f"{len(unresolved)} unresolved link(s): {shown}{more}; run `cheme validate` and "
        "resolve them in process/flowsheet.yaml or the lists"
    )
    if check.level == "warning":
        return "pass", "warning: " + detail
    return "fail", detail


def _mto(check: Check, context: _Context) -> tuple[str, str]:
    """``kind: mto``: see :mod:`chemeascode.domains.assessment.gates`."""
    from chemeascode.domains.assessment.gates import mto_gate

    problems = mto_gate(context.workspace.root, list(check.require))
    return ("fail", "; ".join(problems)) if problems else ("pass", "")


def _lca(check: Check, context: _Context) -> tuple[str, str]:
    """``kind: lca``: see :mod:`chemeascode.domains.assessment.lca.gates`."""
    from chemeascode.domains.assessment.lca.gates import lca_gate

    problems = lca_gate(context.workspace.root, list(check.require))
    return ("fail", "; ".join(problems)) if problems else ("pass", "")


def _tea(check: Check, context: _Context) -> tuple[str, str]:
    """``kind: tea``: see :mod:`chemeascode.domains.assessment.tea.gates`."""
    from chemeascode.domains.assessment.tea.gates import tea_gate

    problems = tea_gate(context.workspace.root, list(check.require))
    return ("fail", "; ".join(problems)) if problems else ("pass", "")


def _layout_model(check: Check, context: _Context) -> tuple[str, str]:
    """``kind: layout-model``: see :mod:`chemeascode.domains.spatial.gates`."""
    from chemeascode.domains.spatial.gates import layout_gate

    problems = layout_gate(
        context.workspace,
        list(check.require),
        context.validation().findings,
        min_dn=check.min_dn,
        exclude_lines=check.exclude_lines,
        exclude_fluids=check.exclude_fluids,
        rules=check.rules,
        accept=check.accept,
        sections=check.sections,
        topic=check.topic or "layout",
        records=context.records() if "drawings" in check.require else None,
    )
    return ("fail", "; ".join(problems)) if problems else ("pass", "")


def _unbuilt(workspace: Workspace, kinds: list[str]) -> list[str]:
    """What is missing of the generated sheet *kinds* (``generated:`` of a validate gate): no
    sheet of that kind declared in plant.yaml, or its file not built."""
    problems = []
    sheets = workspace.config().sheets
    for kind in kinds:
        declared = [s for s in sheets if s.kind == kind]
        if not declared:
            problems.append(
                f"no kind: {kind} sheet declared in plant.yaml; add {{id: {kind.upper()}, kind: "
                f"{kind}, file: process/{kind.upper()}.xml}} and run `cheme process build`"
            )
            continue
        for sheet in declared:
            path = workspace.sheet_path(sheet.file)
            if path is None or not path.is_file():
                problems.append(f"{sheet.file} not built; run `cheme process build {sheet.id}`")
    return problems


def stages_up_to(workspace: Workspace, stage: str) -> list[str]:
    """The stage ids of ``plant.yaml`` from the first up to *stage*; ValueError when unknown."""
    ids = [s.id for s in workspace.config().stages]
    if stage not in ids:
        raise ValueError(f"unknown stage {stage!r}; plant.yaml has {', '.join(ids) or 'none'}")
    return ids[: ids.index(stage) + 1]


def run_checks(
    workspace: Workspace,
    stage: str | None = None,
    timeout: float | None = None,
    stages: list[str] | None = None,
) -> list[CheckStatus]:
    """Evaluate every check (of *stage* only, or of the *stages*, when given).

    *timeout*: seconds each ``kind: command`` check may run before it fails (default: no limit).
    """
    path = workspace.list_file("checks")
    if path is None:
        return []
    checks = CheckList.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
    known = _stage_ids(workspace)
    results: list[CheckStatus] = []
    context = _Context(workspace)
    for check in checks.checks:
        unknown = known is not None and check.stage not in known
        if not unknown and stage and check.stage != stage:
            continue
        if not unknown and stages is not None and check.stage not in stages:
            continue
        status, detail, evidence = "pass", "", {}
        if unknown:  # a typo must not drop the gate from --stage and the sign-off
            status, detail = "fail", _unknown_stage(check.stage, known or [])
        elif not check.applies:
            status = "n/a"
        elif check.kind == "validate":
            # the gate's own accept: is not consulted: an entry that would accept the drift of
            # one sheet must not spare the generators for the others
            generators = bool(gate_findings(_GENERATED, check, accepted=False))
            failing = gate_findings(context.validation(generators).findings, check)
            unbuilt = _unbuilt(workspace, check.generated)
            if failing or unbuilt:
                parts = unbuilt + ([_validate_detail(failing, check)] if failing else [])
                status, detail = "fail", "; ".join(parts)
        elif check.kind == "files":
            found = {g: _glob_inside(workspace, g) for g in check.files}
            outside = [g for g, ok in found.items() if ok is None]
            missing = [g for g, ok in found.items() if ok is False]
            if outside:
                status, detail = "fail", "pattern leaves the repository: " + ", ".join(outside)
            elif missing:
                status, detail = "fail", "nothing matches " + ", ".join(missing)
        elif check.kind == "on-sheet":
            status, detail = _on_sheet(check, context)
        elif check.kind == "review":
            from chemeascode.foundation.reviews import evaluate_review_gate

            gate = evaluate_review_gate(workspace, check, context.records())
            status, detail, evidence = gate.status, gate.detail, gate.evidence
        elif check.kind == "datasheets":
            status, detail = _datasheets(workspace, list(check.require))
        elif check.kind == "process-links":
            status, detail = _process_links(check, context)
        elif check.kind == "layout-model":
            status, detail = _layout_model(check, context)
        elif check.kind == "mto":
            status, detail = _mto(check, context)
        elif check.kind == "lca":
            status, detail = _lca(check, context)
        elif check.kind == "tea":
            status, detail = _tea(check, context)
        elif check.kind == "hazop":
            from chemeascode.project.hazop import hazop_gate

            problems = hazop_gate(workspace, check, context.validation().findings)
            if problems:
                status, detail = "fail", "; ".join(problems)
        elif check.kind == "maturity":
            from chemeascode.project.maturity import maturity_gate

            problems, evidence = maturity_gate(
                workspace.root,
                check.require[0] if check.require else None,
                max_claim=check.max_claim,
                validation=context.validation,
            )
            if problems:
                status, detail = "fail", "; ".join(problems)
        elif check.kind == "issues":
            from chemeascode.project.issues import issues_gate

            status, detail = issues_gate(workspace, check)
        elif check.kind == "command":
            try:
                run = _run_command(check.command or "false", workspace, timeout)
            except subprocess.TimeoutExpired:
                status, detail = "fail", f"timed out after {timeout:g} s"
            else:
                if run.returncode != 0:
                    tail = (run.stderr or run.stdout).strip().splitlines()[-1:] or [""]
                    status, detail = "fail", f"exit {run.returncode}: {tail[0]}"
        results.append(CheckStatus(check.id, check.title, check.stage, status, detail, evidence))
    return results


def gate_findings(findings: list[Finding], check: Check, accepted: bool = True) -> list[Finding]:
    """The findings that fail a ``kind: validate`` gate.

    Those of its ``rules`` (all when none are given), at its ``fail_on`` level or above, that
    neither checks.yaml's ``accept:`` nor the gate's own ``accept:`` names. Errors are never
    accepted. *accepted* False skips the gate's ``accept:``. A rule that matches
    ``cheme.generated-sheet-drift`` also matches ``cheme.generator-failed`` (see
    :func:`~chemeascode.foundation.findings.rule_matches`).
    """
    lowest = _SEVERITY[check.fail_on]
    return [
        f
        for f in findings
        if f.accepted is None
        and _SEVERITY[f.level] >= lowest
        and (not check.rules or any(rule_matches(f.rule, r) for r in check.rules))
        and (not accepted or acceptance(check.accept, f) is None)
    ]


#: What running the P&ID generators can report, as a gate sees it: a validate gate that would
#: fail on either runs the generators (as ``cheme validate`` does), so it never passes over a
#: hand-edited sheet or a generator that cannot run.
_GENERATED = [
    Finding("", "warning", "cheme.generated-sheet-drift", ""),
    Finding("", "warning", "cheme.generator-failed", ""),
]


def _stage_ids(workspace: Workspace) -> list[str] | None:
    """The stage ids of plant.yaml; None when plant.yaml cannot be read (validate says why)."""
    try:
        return [s.id for s in workspace.config().stages]
    except (OSError, ValueError, yaml.YAMLError):
        return None


def _unknown_stage(stage: str, known: list[str]) -> str:
    return (
        f"stage {stage!r} is not a stage of plant.yaml ({', '.join(known) or 'none'}): the gate "
        "is not evaluated and counts as failing until its stage: names one"
    )


def checklist_findings(workspace: Workspace, checks: CheckList, name: str) -> list[Finding]:
    """``cheme validate`` on checks/checks.yaml *name*: a check whose stage plant.yaml does not
    declare (``cheme.check-stage-unknown``), and a check id listed twice
    (``cheme.check-duplicate-id``); both errors."""
    from chemeascode.foundation.yamlsource import _compose, _yaml_line

    known = _stage_ids(workspace)
    document = _compose(workspace.root / name)
    findings = []
    first: dict[str, int] = {}
    for position, check in enumerate(checks.checks):
        if known is not None and check.stage not in known:
            findings.append(
                Finding(
                    name,
                    "error",
                    "cheme.check-stage-unknown",
                    f"check {check.id}: {_unknown_stage(check.stage, known)}",
                    line=_yaml_line(document, ["checks", position, "stage"]),
                    ids=[check.id],
                    hint="use a stage id of plant.yaml stages: (case matters); `cheme check "
                    "--write` refuses the sign-off while a gate names an unknown stage",
                )
            )
        if check.id in first:
            findings.append(
                Finding(
                    name,
                    "error",
                    "cheme.check-duplicate-id",
                    f"check id {check.id} is listed twice (first as check {first[check.id] + 1})",
                    line=_yaml_line(document, ["checks", position, "id"]),
                    ids=[check.id],
                    hint="give every check its own id: status.json and the sign-off name gates "
                    "by id",
                )
            )
        first.setdefault(check.id, position)
    return findings


def _validate_detail(failing: list[Finding], check: Check) -> str:
    counts: dict[str, int] = {}
    for finding in failing:
        counts[finding.rule] = counts.get(finding.rule, 0) + 1
    if check.rules or check.fail_on != "error":
        levels = [lv for lv in ("error", "warning", "info") if any(f.level == lv for f in failing)]
        per_level = ", ".join(f"{sum(f.level == lv for f in failing)} {lv}(s)" for lv in levels)
        what = ", ".join(f"{n} {rule}" for rule, n in sorted(counts.items()))
        first = failing[0]
        option = "" if check.fail_on == "error" else f" --fail-on {check.fail_on}"
        return (
            f"{what} not accepted; first: {first.id}; {per_level}; run `cheme validate"
            f"{option}` (fix, or accept with a reason under accept:)"
        )
    return f"{len(failing)} error(s); run `cheme validate`"


def write_status(workspace: Workspace, results: list[CheckStatus]) -> None:
    """Write ``checks/status.json`` with *results* only (no sign-off entry); see
    :func:`chemeascode.project.signoff.sign_off` for a stage sign-off."""
    path = workspace.root / "checks" / "status.json"
    path.parent.mkdir(exist_ok=True)
    payload = {"checks": [result_dict(r) for r in results]}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="")


def result_dict(result: CheckStatus) -> dict[str, Any]:
    """*result* for ``status.json``: without an empty ``evidence``."""
    data = asdict(result)
    if not data["evidence"]:
        del data["evidence"]
    return data
