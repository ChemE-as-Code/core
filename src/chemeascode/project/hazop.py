"""HAZOP studies over the workspace: each study's findings (from ``validate_workspace``), its
review and its state, and the stage gate ``kind: hazop``.

The gate's ``require`` (each item one test, over every study, or the studies its ``files``
globs name):

- ``assessed``: nothing unresolved and no error (state ``assessed`` or ``reviewed``);
- ``reviewed``: a current human review record covers the study and its analysed inputs;
- ``inputs-current``: no analysed input changed since its recorded revision;
- ``actions-closed``: every action is closed or rejected (with its response);
- ``no-example``: neither the study nor its matrix is example data.

A gate passes or fails on structure and currency. That a study is complete is not that the
plant is safe: the judgement is the team's, recorded in the study and the review record.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from typing import Any

import yaml

from chemeascode.domains.safety.hazop import (
    LoadedStudy,
    RatingRow,
    ReviewStatus,
    State,
    rating_rows,
    review_status,
    study_path,
    study_state,
    workspace_studies,
)
from chemeascode.foundation.findings import Finding
from chemeascode.foundation.workspace import Workspace

REQUIREMENTS = ("assessed", "reviewed", "inputs-current", "actions-closed", "no-example")


@dataclass
class StudySummary:
    """One study as ``cheme safety hazop check`` and the report show it."""

    loaded: LoadedStudy
    findings: list[Finding]
    review: ReviewStatus
    state: State
    rows: list[RatingRow] = field(default_factory=list)

    @property
    def path(self) -> str:
        return self.loaded.path

    @property
    def id(self) -> str:
        return self.loaded.model.id if self.loaded.model is not None else self.path


def study_summaries(
    workspace: Workspace, study_id: str | None = None, findings: list[Finding] | None = None
) -> list[StudySummary]:
    """Every study (or the one *study_id*) with its findings, review and state. *findings*:
    those of a ``validate_workspace`` run already made; None runs it.

    Raises ValueError for a *study_id* without a study file."""
    if study_id is not None and not (workspace.root / study_path(study_id)).is_file():
        raise ValueError(f"no study {study_path(study_id)}")
    if findings is None:
        from chemeascode.project.validate import validate_workspace

        findings = validate_workspace(workspace).findings
    out = []
    for loaded in workspace_studies(workspace):
        if study_id is not None and loaded.path != study_path(study_id):
            continue
        files = {loaded.path}
        if loaded.matrix is not None:
            files.add(loaded.matrix.path)
        mine = [f for f in findings if f.file in files]
        review = review_status(workspace, loaded)
        out.append(
            StudySummary(loaded, mine, review, study_state(mine, review), rating_rows(loaded))
        )
    return out


def hazop_gate(workspace: Workspace, check: Any, findings: list[Finding]) -> list[str]:
    """What fails of the ``kind: hazop`` *check*; empty when it passes."""
    summaries = study_summaries(workspace, findings=findings)
    if check.files:
        summaries = [s for s in summaries if any(fnmatch.fnmatch(s.path, g) for g in check.files)]
    if not summaries:
        return ["no HAZOP study (safety/hazop/<id>/study.yaml)"]
    problems: list[str] = []
    for summary in summaries:
        study, name = summary.loaded.model, summary.id
        if study is None or summary.state == "invalid":
            errors = [f for f in summary.findings if f.level == "error"]
            first = errors[0].format() if errors else "it does not load"
            problems.append(f"{name}: has errors (first: {first})")
            continue
        require = set(check.require)
        if "assessed" in require and summary.state not in ("assessed", "reviewed"):
            open_rules = sorted({f.rule for f in summary.findings if f.level != "error"})
            problems.append(
                f"{name}: {summary.state}, not assessed ({', '.join(open_rules[:4])}); "
                f"cheme safety hazop check {name}"
            )
        if "reviewed" in require and not (summary.review.human and summary.review.current):
            problems.append(f"{name}: no current human review ({summary.review.detail})")
        if "inputs-current" in require:
            changed = [f.ids[0] for f in summary.findings if f.rule == "cheme.hazop-input-changed"]
            if changed:
                problems.append(f"{name}: analysed inputs changed since: {', '.join(changed)}")
        if "actions-closed" in require:
            pending = [a.id for a in study.actions if a.status in ("proposed", "open")]
            if pending:
                problems.append(f"{name}: actions not closed or rejected: {', '.join(pending)}")
        if "no-example" in require:
            matrix = summary.loaded.matrix
            if study.example:
                problems.append(f"{name}: the study is an example (example: true)")
            if matrix is not None and matrix.model is not None and matrix.model.example:
                problems.append(f"{name}: its matrix {matrix.path} is example data")
    return problems


def review_draft(workspace: Workspace, summary: StudySummary) -> str:
    """A review record for the study in the format of ``reviews/`` (skill ``review``), to be
    completed by the reviewer: the scope is the study's directory, ``basis`` its analysed
    inputs and matrix at the revisions the study records, and the front matter leaves the
    reviewer empty, so the record does not validate until a person fills it in."""
    from chemeascode.foundation import gitinfo, provenance

    study = summary.loaded.model
    if study is None:
        raise ValueError(f"{summary.path} does not load; run cheme safety hazop check")
    directory = summary.path.rsplit("/", 1)[0] + "/"

    def entry(path: str, revision: str, relation: str) -> str:
        data = {"path": path, "revision": revision, "relation": relation}
        return "  - " + yaml.safe_dump(data, default_flow_style=True, sort_keys=False).strip()

    basis = [entry(b.path, b.revision, "analyses") for b in study.analysed]
    matrix = summary.loaded.matrix
    if matrix is not None and (workspace.root / matrix.path).is_file():
        revision = provenance.file_fingerprint(workspace.root / matrix.path)
        basis.append(entry(matrix.path, revision, "depends-on"))
    open_items = [
        f.format() for f in summary.findings if f.level != "info" or "unresolved" in f.rule
    ]
    lines = [
        "---",
        "schema: cheme/review/v1",
        "topic: hazop",
        f"reviewed_commit: {gitinfo.head(workspace.root) or '<commit the study is at>'}",
        f"scope: [{directory}]",
        "reviewer: ''            # fill in: the person (or independent agent) who reviewed",
        "reviewer_kind: human    # human | agent | self (a self review needs approved_by)",
        *(["basis:", *basis] if basis else []),
        "---",
        "",
        f"# HAZOP study {study.id} review",
        "",
        f"State when prepared: {summary.state} (cheme safety hazop check {study.id}). The",
        "reviewer checks the judgements in the study (nodes, scenarios, ratings and their",
        "basis, safeguards, actions), not only its structure.",
        "",
        "## Findings",
        "",
        "| id | item | finding | severity | status | proposed action |",
        "|---|---|---|---|---|---|",
        "",
        "## Previous findings",
        "",
        "| id | finding | severity | status | evidence |",
        "|---|---|---|---|---|",
        "",
        "## Open items when prepared",
        "",
        *([f"- {item}" for item in open_items] or ["- none"]),
        "",
    ]
    return "\n".join(lines)
