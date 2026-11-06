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
from pathlib import PurePosixPath
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
from chemeascode.domains.safety.propagation import (
    Context,
    Coverage,
    Deviation,
    Propagation,
    coverage,
    propagate,
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


#: The project's failure-mode library ``cheme safety hazop propagate`` walks with.
LIBRARY_FILE = "safety/failure-modes.yaml"


@dataclass
class NodePropagation:
    """``cheme safety hazop propagate`` for one node: its candidates and what limits them."""

    study: str
    node: str
    library: str
    sheets: list[str]
    deviation: Deviation | None
    result: Propagation
    findings: list[Finding]
    #: The node's scenarios against its candidates (all deviations only).
    coverage: Coverage | None = None


def _deviation(node: Any, wanted: str) -> Deviation:
    """A deviation of *node* by its id (``N1-NF``), or one given as ``<guide word> <parameter>``."""
    for deviation in node.deviations:
        if deviation.id == wanted:
            return Deviation(deviation.parameter, deviation.guide_word)
    guide_word, _, parameter = wanted.strip().partition(" ")
    if not parameter.strip():
        raise ValueError(
            f"--deviation {wanted!r}: no deviation of {node.id} has that id; give its id or "
            "'<guide word> <parameter>' (no flow, more pressure)"
        )
    return Deviation(parameter.strip(), guide_word)


def node_propagation(
    workspace: Workspace,
    study_id: str,
    node_id: str,
    deviation: str | None = None,
    library_file: str = LIBRARY_FILE,
) -> NodePropagation:
    """Walk the study's analysed P&IDs from the members of node *node_id* with the failure-mode
    library. Reads only; raises ValueError for a missing study, node, library or P&ID."""
    inputs = _propagation_inputs(workspace, study_id, library_file)
    node = next((n for n in inputs.study.nodes if n.id == node_id), None)
    if node is None:
        raise ValueError(f"{inputs.path}: no node {node_id}")
    return _walk_node(inputs, node, _deviation(node, deviation) if deviation else None)


def study_propagation(
    workspace: Workspace, study_id: str, library_file: str = LIBRARY_FILE
) -> list[NodePropagation]:
    """:func:`node_propagation` for every node of the study, the inputs read once."""
    inputs = _propagation_inputs(workspace, study_id, library_file)
    return [_walk_node(inputs, node, None) for node in inputs.study.nodes if node.members]


#: The triage of the walk's outcomes, beside the study (``cheme/hazop-coverage/v1``).
COVERAGE_FILE = "coverage.yaml"
#: Who writes the open outcomes.
COVERAGE_WRITER = "cheme safety hazop propagate --coverage --write"


#: A project's own deviation matrix (``cheme/hazop-deviation-matrix/v1``), replacing the default.
DEVIATION_MATRIX_FILE = "safety/deviation-matrix.yaml"


@dataclass
class StudyCoverage:
    """``propagate --coverage``: each node's walk coverage and completeness, and the state of
    the triage file."""

    path: str
    found: list[NodePropagation]
    #: The library or an analysed sheet changed since the triage file was written.
    stale: bool
    written: bool
    study: str = ""
    #: The failure-mode library walked, or None: there is none and the walk was skipped.
    library: str | None = None
    #: Node id -> its deviation and cause checks, every node with members (or the one asked).
    complete: list[tuple[str, Any]] = field(default_factory=list)
    #: The deviation matrix used: the project's file, or cheme-as-code's default.
    matrix: str = "default"

    def open_gaps(self) -> int:
        walk = sum(len(f.coverage.gaps) for f in self.found if f.coverage is not None)
        return walk + sum(len(c.deviations) + len(c.causes) for _, c in self.complete)


def study_coverage(
    workspace: Workspace,
    study_id: str,
    node_id: str | None = None,
    library_file: str = LIBRARY_FILE,
    write: bool = False,
    walk_too: bool = True,
) -> StudyCoverage:
    """Every node's (or one node's) scenarios against the walk (when the project has a
    failure-mode library), the deviations its equipment calls for and the cause families it
    has to consider, the triage file's decisions applied; *write* brings the triage file up to
    date (open outcomes only, decisions kept)."""
    from chemeascode.domains.safety.completeness import (
        check_decisions,
        completeness,
        wanted,
    )
    from chemeascode.domains.safety.propagation import _index, triage
    from chemeascode.domains.safety.schemas import COVERAGE_SCHEMA, HazopCoverage, Walk
    from chemeascode.foundation import provenance

    inputs = _propagation_inputs(workspace, study_id, library_file, need_library=False)
    if not walk_too:  # --no-walk: the deviation and cause checks only, as if there were no library
        inputs.library = None
    # The study's node without members takes the study-wide prompts (utilities, site hazards).
    study_wide = next((n.id for n in inputs.study.nodes if not n.members), None)
    nodes = [
        n
        for n in inputs.study.nodes
        if (n.members or n.id == study_wide) and node_id in (None, n.id)
    ]
    if node_id is not None and not nodes:
        raise ValueError(f"{inputs.path}: no node {node_id} with members")
    recorded = inputs.triage
    outcomes_before = recorded.outcomes if recorded else []
    problems = check_decisions(inputs.study.nodes, outcomes_before)
    if problems:
        raise ValueError(f"{COVERAGE_FILE} of {study_id}: " + "; ".join(problems))
    found = [_walk_node(inputs, n, None) for n in nodes if n.members] if inputs.library else []
    index = _index(inputs.models)
    complete = [
        (
            node.id,
            completeness(
                index, node, inputs.plant, outcomes_before, inputs.matrix, study_wide=study_wide
            ),
        )
        for node in nodes
    ]
    root = workspace.root
    walk = Walk(
        library=provenance.file_fingerprint(root / library_file) if inputs.library else "",
        sheets={p: provenance.file_fingerprint(root / p) for p in inputs.sheet_files},
        inputs={p: provenance.file_fingerprint(root / p) for p in inputs.other_files},
    )
    before = recorded.walk if recorded is not None else None
    # A triage file written before the other checks existed records no inputs: only the walk's.
    stale = before is not None and (
        (before.library, before.sheets) != (walk.library, walk.sheets)
        or (bool(before.inputs) and before.inputs != walk.inputs)
    )
    path = str(PurePosixPath(inputs.path).parent / COVERAGE_FILE)
    if write:
        outcomes = triage(
            [(f.node, f.coverage) for f in found if f.coverage is not None],
            outcomes_before,
            COVERAGE_WRITER,
            [
                (node_id_, wanted(node_id_, result, COVERAGE_WRITER))
                for node_id_, result in complete
            ],
        )
        data = HazopCoverage.model_validate(
            {
                "schema": COVERAGE_SCHEMA,
                "kind": "hazop-coverage",
                "study": inputs.study.id,
                "walk": walk.model_dump(),
                "outcomes": [o.model_dump(mode="json") for o in outcomes],
            }
        )
        dumped = data.model_dump(mode="json", by_alias=True)
        # Empty fields (reason, by, causes, those of another kind) are left out: the file is
        # edited by hand.
        dumped["outcomes"] = [
            {k: v for k, v in o.items() if v not in ("", [], None)} for o in dumped["outcomes"]
        ]
        text = yaml.safe_dump(dumped, sort_keys=False)
        with (root / path).open("w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        inputs.triage = data
        stale = False
    return StudyCoverage(
        path,
        found,
        stale,
        write,
        inputs.study.id,
        library_file if inputs.library else None,
        complete,
        DEVIATION_MATRIX_FILE if inputs.matrix_file else "default",
    )


@dataclass
class _PropagationInputs:
    path: str
    study: Any
    library_file: str
    #: None: no library (only under --coverage, where the walk is then skipped).
    library: Any
    models: list[tuple[str, Any]]
    context: Context
    sheet_files: list[str] = field(default_factory=list)
    #: The study's coverage.yaml, if it has one.
    triage: Any = None
    #: What the deviation and cause checks read besides the sheets.
    plant: Any = None
    matrix: Any = None
    matrix_file: bool = False
    other_files: list[str] = field(default_factory=list)


def _load(workspace: Workspace, name: str, model: Any) -> Any:
    """*name* (a YAML file from the repository root) parsed into *model*; ValueError if not."""
    from pydantic import ValidationError

    try:
        return model.model_validate(
            yaml.safe_load((workspace.root / name).read_text(encoding="utf-8")) or {}
        )
    except (yaml.YAMLError, ValidationError) as failure:
        raise ValueError(f"{name} does not load: {failure}") from failure


def _propagation_inputs(
    workspace: Workspace, study_id: str, library_file: str, need_library: bool = True
) -> _PropagationInputs:
    from chemeascode.domains.piping.sheet_query import load_sheets, sheet_id_of
    from chemeascode.domains.safety.completeness import DEFAULT_MATRIX, Plant
    from chemeascode.domains.safety.hazop import load_study
    from chemeascode.domains.safety.schemas import DeviationMatrix, FailureModeLibrary

    path = study_path(study_id)
    if not (workspace.root / path).is_file():
        raise ValueError(f"no study {path}")
    loaded = load_study(workspace.root, path)
    if loaded.model is None:
        raise ValueError(f"{path} does not load: cheme safety hazop check {study_id}")

    library = None
    if (workspace.root / library_file).is_file():
        library = _load(workspace, library_file, FailureModeLibrary)
    elif need_library:
        raise ValueError(
            f"no failure-mode library {library_file}: the team writes it "
            "(cheme schema failure-modes; skill hazop-scenario-propagation)"
        )

    analysed = {basis.path for basis in loaded.model.analysed}
    models = []
    sheet_files = []
    for sheet in load_sheets(workspace):
        if sheet.name not in analysed:
            continue
        if sheet.model is None:
            raise ValueError(f"{sheet.name} does not load: {sheet.error}")
        models.append((sheet_id_of(workspace, sheet.name), sheet.model))
        sheet_files.append(sheet.name)
    if not models:
        raise ValueError(
            f"{path} analyses no P&ID: cheme safety hazop stamp {study_id} --input pid/<sheet>.xml"
        )

    context = Context()
    plant = Plant()
    parsed = workspace.parsed_lists(("interlocks", "loops", "design_basis"))
    if "interlocks" in parsed:
        for interlock in parsed["interlocks"].interlocks:
            context.interlocks.setdefault(str(interlock.cause.tag), []).append(str(interlock.id))
            plant.interlocks[str(interlock.id)] = _tags(interlock.model_dump())
    if "loops" in parsed:
        for loop in parsed["loops"].loops:
            for element in loop.final_elements:
                if element.fail:
                    context.fail[str(element.tag)] = element.fail
    if "design_basis" in parsed:
        plant.utilities = parsed["design_basis"].utilities
        plant.site = parsed["design_basis"].site
    other_files = [
        name
        for name in (
            "process/design-basis.yaml",
            "control/cause-effect.yaml",
            DEVIATION_MATRIX_FILE,
        )
        if (workspace.root / name).is_file()
    ]
    matrix_file = (workspace.root / DEVIATION_MATRIX_FILE).is_file()
    matrix = (
        _load(workspace, DEVIATION_MATRIX_FILE, DeviationMatrix) if matrix_file else DEFAULT_MATRIX
    )

    from chemeascode.domains.safety.schemas import HazopCoverage

    triage_file = PurePosixPath(path).parent / COVERAGE_FILE
    recorded = None
    if (workspace.root / triage_file).is_file():
        recorded = _load(workspace, str(triage_file), HazopCoverage)
    return _PropagationInputs(
        path,
        loaded.model,
        library_file,
        library,
        models,
        context,
        sheet_files,
        recorded,
        plant,
        matrix,
        matrix_file,
        other_files,
    )


def _tags(data: Any) -> set[str]:
    """Every ``tag`` value in *data* (an interlock dumped: cause, logic, effects)."""
    if isinstance(data, dict):
        found = {str(data["tag"])} if data.get("tag") is not None else set()
        return found.union(*(_tags(v) for v in data.values()))
    if isinstance(data, list):
        return set().union(*(_tags(v) for v in data))
    return set()


def _walk_node(inputs: _PropagationInputs, node: Any, wanted: Deviation | None) -> NodePropagation:
    path, node_id, library_file = inputs.path, node.id, inputs.library_file
    others = {n.id: n.members for n in inputs.study.nodes if n.id != node_id}
    result = propagate(inputs.models, inputs.library, node.members, inputs.context, wanted, others)
    findings = []
    if result.unresolved:
        findings.append(
            Finding(
                path,
                "warning",
                "cheme.hazop-propagation-member",
                f"{node_id}: not on the analysed P&IDs: {', '.join(result.unresolved)}",
                key=node_id,
                hint="fix the member, or stamp the sheet it is on (cheme safety hazop stamp)",
            )
        )
    if result.uncovered:
        findings.append(
            Finding(
                library_file,
                "info",
                "cheme.hazop-class-uncovered",
                f"{node_id}: no library entry for {', '.join(result.uncovered)}: no cause or "
                "response of theirs is walked",
                key=node_id,
                hint="add the class (or a superclass) to the library under classes:",
            )
        )
    return NodePropagation(
        inputs.study.id,
        node_id,
        library_file,
        [sheet for sheet, _ in inputs.models],
        wanted,
        result,
        findings,
        None
        if wanted
        else coverage(node, result.candidates, inputs.triage.outcomes if inputs.triage else ()),
    )
