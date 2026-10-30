"""``cheme safety hazop``: HAZOP studies (domains/safety/hazop.py, project/hazop.py)."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import typer

safety_app = typer.Typer(help="Safety: HAZOP studies and their risk matrix.", no_args_is_help=True)
hazop_app = typer.Typer(
    help="HAZOP studies in safety/hazop/<study-id>/study.yaml: start one, check it, look its "
    "bands up in the risk matrix, write its report, record its analysed inputs.",
    no_args_is_help=True,
)
safety_app.add_typer(hazop_app, name="hazop")

STUDY = Annotated[str, typer.Argument(help="The study id: its directory under safety/hazop/.")]


def _workspace():
    from chemeascode.interfaces.cli.process import _workspace

    return _workspace()


@hazop_app.command("init")
def init(
    study: STUDY,
    title: Annotated[str, typer.Option(help="The study's title.")] = "",
    input_: Annotated[
        list[str] | None,
        typer.Option(
            "--input",
            help="A file or directory the study analyses (pid/P-01.xml, control/; repeat). A "
            "directory is recorded at the HEAD commit and must be committed.",
        ),
    ] = None,
    matrix: Annotated[
        str | None,
        typer.Option(help="The risk matrix file (default safety/risk-matrix.yaml if it exists)."),
    ] = None,
) -> None:
    """Start a draft study: safety/hazop/STUDY/study.yaml with the analysed inputs at their
    current revision and an empty worksheet. Refuses an existing study."""
    from chemeascode.domains.safety.hazop import new_study, study_path
    from chemeascode.domains.safety.risk_matrix import MATRIX_FILE
    from chemeascode.foundation.schema_base import ID_PATTERN

    workspace = _workspace()
    if not ID_PATTERN.match(study):
        typer.echo(f"{study!r} is no stable id: letters, digits, _ and -, from a letter", err=True)
        raise typer.Exit(2)
    path = workspace.root / study_path(study)
    if path.exists():
        typer.echo(f"{study_path(study)} exists; edit it (skill hazop-study)", err=True)
        raise typer.Exit(2)
    from chemeascode.domains.safety.hazop import current_revision

    for name in input_ or []:
        try:
            current_revision(workspace, name)
        except ValueError as failure:
            typer.echo(f"--input {name}: {failure}", err=True)
            raise typer.Exit(2) from failure
    if matrix is None and (workspace.root / MATRIX_FILE).is_file():
        matrix = MATRIX_FILE
    elif matrix is not None and not (workspace.root / matrix).is_file():
        typer.echo(f"--matrix {matrix}: no such file (schema: cheme schema risk-matrix)", err=True)
        raise typer.Exit(2)
    text = new_study(workspace, study, title, input_ or [], matrix)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    typer.echo(workspace.relative(path))
    if matrix is None:
        typer.echo(
            "note: no risk matrix; write safety/risk-matrix.yaml (cheme schema risk-matrix) "
            "and name it under risk_matrix:",
            err=True,
        )


@hazop_app.command("check")
def check(
    study: Annotated[str | None, typer.Argument(help="The study id; none: every study.")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="As JSON.")] = False,
) -> None:
    """The findings of the studies (as in cheme validate) and the state of each: invalid,
    draft, assessed or reviewed. Read-only; exits 1 when a study has errors."""
    from chemeascode.project.hazop import study_summaries

    workspace = _workspace()
    try:
        summaries = study_summaries(workspace, study)
    except ValueError as failure:
        typer.echo(str(failure), err=True)
        raise typer.Exit(2) from failure
    if not summaries:
        typer.echo("no HAZOP study (cheme safety hazop init <id> starts one)")
        return
    if as_json:
        typer.echo(
            json.dumps(
                [
                    {
                        "study": s.id,
                        "path": s.path,
                        "state": s.state,
                        "review": asdict(s.review),
                        "findings": [{**asdict(f), "id": f.id} for f in s.findings],
                    }
                    for s in summaries
                ],
                indent=2,
            )
        )
    else:
        for summary in summaries:
            for finding in summary.findings:
                typer.echo(finding.format())
            counts = {
                level: sum(f.level == level for f in summary.findings)
                for level in ("error", "warning", "info")
            }
            typer.echo(
                f"{summary.path}: {summary.state} ({counts['error']} error(s), "
                f"{counts['warning']} warning(s), {counts['info']} info); review: "
                f"{summary.review.detail}"
            )
    if any(s.state == "invalid" for s in summaries):
        raise typer.Exit(1)


@hazop_app.command("rate")
def rate(
    study: STUDY,
    target: Annotated[
        str | None,
        typer.Option(help="Only this node, deviation or scenario id (default: the whole study)."),
    ] = None,
    write: Annotated[
        bool, typer.Option("--write", help="Record the bands (default: only check them).")
    ] = False,
    as_json: Annotated[bool, typer.Option("--json", help="As JSON.")] = False,
) -> None:
    """Look up the band of each rating (category, severity, likelihood) in the study's risk
    matrix. Without --write nothing is written and the command exits 1 when a band is missing,
    stale or edited, or a rating cannot be looked up. --write records the bands (with the
    matrix and input fingerprint) and changes nothing else in the file."""
    from chemeascode.domains.safety.hazop import rate as rate_study

    workspace = _workspace()
    try:
        result = rate_study(workspace, study, target, write=write)
    except ValueError as failure:
        typer.echo(str(failure), err=True)
        raise typer.Exit(2) from failure
    if as_json:
        typer.echo(
            json.dumps(
                {
                    "study": result.study,
                    "matrix": result.matrix,
                    "matrix_id": result.matrix_id,
                    "written": result.written,
                    "ratings": [
                        {
                            "node": r.node,
                            "scenario": r.scenario,
                            "which": r.which,
                            "category": r.rating.category,
                            "severity": r.rating.severity,
                            "likelihood": r.rating.likelihood,
                            "status": r.rating.status,
                            "band": r.band,
                            "recorded": r.recorded,
                            "state": r.state,
                            "problem": r.problem or None,
                        }
                        for r in result.rows
                    ],
                    "findings": [{**asdict(f), "id": f.id} for f in result.findings],
                },
                indent=2,
            )
        )
    else:
        typer.echo(f"matrix: {result.matrix or '(none)'} {result.matrix_id or ''}".rstrip())
        for r in result.rows:
            codes = f"{r.rating.category} {r.rating.severity or '?'}/{r.rating.likelihood or '?'}"
            band = r.band or f"unresolved ({r.message})"
            state = r.state if r.state != "current" else "current"
            if r in result.changes:
                state = ("written" if result.written else "would write") + f" ({r.state})"
            typer.echo(f"{r.node} {r.scenario} {r.which:<8} {codes:<20} -> {band:<10} {state}")
        for finding in result.findings:
            typer.echo(finding.format())
        if not result.rows:
            typer.echo("no ratings")
    failed = bool(result.findings) or (result.changes and not result.written)
    if failed or any(r.state == "unresolved" for r in result.rows):
        raise typer.Exit(1)


@hazop_app.command("propagate")
def propagate(
    study: STUDY,
    node: Annotated[str, typer.Option(help="The node id whose scenarios are walked.")],
    deviation: Annotated[
        str | None,
        typer.Option(
            help="Only this deviation: its id in the study (N1-NF) or '<guide word> "
            "<parameter>' (default: every deviation a cause brings to the node)."
        ),
    ] = None,
    library: Annotated[
        str, typer.Option(help="The failure-mode library (cheme schema failure-modes).")
    ] = "safety/failure-modes.yaml",
    paths: Annotated[
        bool, typer.Option("--paths", help="Print each path with its candidate safeguards.")
    ] = False,
    as_json: Annotated[bool, typer.Option("--json", help="As JSON.")] = False,
) -> None:
    """Candidate scenarios of a node: each failure mode of its objects (from the library) walked
    over the study's analysed P&IDs, object by object, to a top event, a study limit, a closed
    valve or an object that absorbs it, with the safeguards the plant has along the path and the
    questions the files leave open. One candidate per outcome, on its shortest path. Read-only:
    proposals for the study, never written into it."""
    from chemeascode.project.hazop import node_propagation

    workspace = _workspace()
    try:
        found = node_propagation(workspace, study, node, deviation, library)
    except ValueError as failure:
        typer.echo(str(failure), err=True)
        raise typer.Exit(2) from failure
    candidates = found.result.candidates
    if as_json:
        typer.echo(
            json.dumps(
                {
                    "study": found.study,
                    "node": found.node,
                    "library": found.library,
                    "sheets": found.sheets,
                    "candidates": [
                        {
                            "deviation": {
                                "guide_word": c.deviation.guide_word,
                                "parameter": c.deviation.parameter,
                            },
                            "at": c.at,
                            "cause": c.cause,
                            "mode": c.mode,
                            "mechanism": c.mechanism,
                            "kind": c.kind,
                            "end": c.end,
                            "top_event": c.top_event,
                            "fluid": c.fluid,
                            "path": [
                                {
                                    "sheet": s.sheet,
                                    "object": s.object,
                                    "tag": s.tag,
                                    "class": s.cls,
                                    "deviation": s.deviation.text(),
                                    "effect": s.effect,
                                }
                                for s in c.path
                            ],
                            "reached": c.reached,
                            "safeguards": [asdict(g) for g in c.safeguards],
                            "questions": c.questions,
                        }
                        for c in candidates
                    ],
                    "uncovered": found.result.uncovered,
                    "unresolved": found.result.unresolved,
                    "findings": [{**asdict(f), "id": f.id} for f in found.findings],
                },
                indent=2,
            )
        )
        return
    ends = Counter(c.end for c in candidates)
    typer.echo(
        f"{found.study} {found.node}: {len(candidates)} candidate(s) from {found.library} over "
        f"{', '.join(found.sheets)} (proposals: the team decides); "
        + ", ".join(f"{n} {end}" for end, n in ends.most_common())
    )
    questions: Counter[str] = Counter(q for c in candidates for q in c.questions)
    if paths:
        for c in candidates:
            typer.echo(
                f"{c.deviation.text()} at {c.at}: {c.cause} {c.mode} [{c.kind}] -> "
                f"{c.top_event or c.end} at {c.path[-1].label}"
                + (f" ({c.fluid})" if c.fluid else "")
            )
            typer.echo(f"  path: {c.path_text()}")
            for guard in c.safeguards:
                typer.echo(f"  safeguard? {guard.kind} {guard.ref}: {guard.detail}")
    else:
        # One line per outcome with its causes; ends that say nothing about a consequence
        # (a closed valve, an object already walked, no connection) are only counted.
        shown = ("top-event", "study-limit", "absorbed", "unknown", "depth")
        outcomes: dict[tuple[str, str, str, str | None], list[str]] = {}
        for c in sorted(candidates, key=lambda c: shown.index(c.end) if c.end in shown else 9):
            if c.end in shown:
                key = (c.deviation.text(), c.top_event or c.end, c.path[-1].label, c.fluid)
                causes = outcomes.setdefault(key, [])
                if c.cause not in causes:
                    causes.append(c.cause)
        for (deviation_text, ending, where, fluid), causes in outcomes.items():
            typer.echo(
                f"{deviation_text} -> {ending} at {where}"
                + (f" ({fluid})" if fluid else "")
                + f": {', '.join(causes)}"
            )
        hidden = sum(n for end, n in ends.items() if end not in shown)
        if hidden:
            typer.echo(
                f"{hidden} candidate(s) end at a closed valve, an object already walked or no "
                "connection: --paths lists every candidate with its path"
            )
    for question, n in questions.most_common():
        typer.echo(f"question ({n} candidate(s)): {question}")
    for finding in found.findings:
        typer.echo(finding.format())


@hazop_app.command("report")
def report(
    study: STUDY,
    output: Annotated[
        Path | None, typer.Option("-o", help="Directory (default build/; files in hazop/).")
    ] = None,
) -> None:
    """Write the study's report to build/hazop/STUDY.md and .html: state, analysed inputs,
    matrix, unresolved items, the worksheet with every rating and band, safeguards, actions,
    review status."""
    from chemeascode.domains.safety.hazop_report import write_report
    from chemeascode.project.hazop import study_summaries

    workspace = _workspace()
    try:
        (summary,) = study_summaries(workspace, study)
    except ValueError as failure:
        typer.echo(str(failure), err=True)
        raise typer.Exit(2) from failure
    written = write_report(
        workspace.root,
        output or workspace.build_dir(),
        summary.loaded,
        summary.findings,
        summary.review,
        summary.state,
        summary.rows,
    )
    for path in written:
        typer.echo(workspace.relative(path) if workspace.contains(path) else str(path))
    typer.echo(f"state: {summary.state}")


@hazop_app.command("stamp")
def stamp(
    study: STUDY,
    input_: Annotated[
        list[str] | None,
        typer.Option("--input", help="Add an analysed input (repeat)."),
    ] = None,
    write: Annotated[bool, typer.Option("--write", help="Record the revisions.")] = False,
) -> None:
    """Show the analysed inputs at their recorded and current revisions; --write records the
    current ones (sha256 of each file). Only once the team has reassessed what changed."""
    from chemeascode.domains.safety.hazop import stamp as stamp_study

    workspace = _workspace()
    try:
        stamps = stamp_study(workspace, study, input_ or [], write=write)
    except ValueError as failure:
        typer.echo(str(failure), err=True)
        raise typer.Exit(2) from failure
    for entry in stamps:
        if entry.new is None:
            state = "missing"
        elif entry.old == entry.new:
            state = "unchanged"
        else:
            state = ("recorded" if write else "would record") + (
                " (new)" if entry.old is None else " (changed)"
            )
        typer.echo(f"{entry.path}: {state} {entry.new or ''}".rstrip())
    if not stamps:
        typer.echo("no analysed inputs; add them with --input")


@hazop_app.command("review")
def review(
    study: STUDY,
    write: Annotated[
        bool,
        typer.Option("--write", help="Write reviews/<today>-hazop-STUDY.md (default: print it)."),
    ] = False,
) -> None:
    """Prepare a review record (skill review's format) for the study: scope, basis (analysed
    inputs and matrix) and the open items. The reviewer is left empty: the record does not
    validate until a person fills it in."""
    import datetime

    from chemeascode.project.hazop import review_draft, study_summaries

    workspace = _workspace()
    try:
        (summary,) = study_summaries(workspace, study)
        text = review_draft(workspace, summary)
    except ValueError as failure:
        typer.echo(str(failure), err=True)
        raise typer.Exit(2) from failure
    if not write:
        typer.echo(text, nl=False)
        return
    path = workspace.root / "reviews" / f"{datetime.date.today().isoformat()}-hazop-{study}.md"
    if path.exists():
        typer.echo(f"{workspace.relative(path)} exists", err=True)
        raise typer.Exit(2)
    path.parent.mkdir(exist_ok=True)
    path.write_text(text, encoding="utf-8")
    typer.echo(workspace.relative(path))
