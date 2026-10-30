"""The ``cheme`` command line."""

from __future__ import annotations

import json
import re
import sys
import warnings
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any, Literal

import typer

from chemeascode.foundation.workspace import NotAPlantRepository, Workspace

app = typer.Typer(
    name="cheme",
    help="Plant design as code: validate, format, render and diff a plant repository.",
    add_completion=False,
    no_args_is_help=True,
)


def _version_line() -> str:
    """``cheme <version> (pyDEXPI <version>)``."""
    from importlib.metadata import PackageNotFoundError, version

    def of(package: str) -> str:
        try:
            return version(package)
        except PackageNotFoundError:
            return "unknown"

    return f"cheme {of('cheme-as-code')} (pyDEXPI {of('pydexpi')})"


def _print_version(value: bool) -> None:
    if value:
        from chemeascode.interfaces.cli.run import interpreter_line

        typer.echo(_version_line())
        typer.echo(interpreter_line())
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_print_version,
            is_eager=True,
            help="Print the cheme-as-code and pyDEXPI versions and the interpreter, and exit.",
        ),
    ] = False,
) -> None:
    """Plant design as code: validate, format, render and diff a plant repository."""


def _workspace() -> Workspace:
    from chemeascode.foundation.workspace import check_requirement

    try:
        workspace = Workspace.find()
    except NotAPlantRepository as failure:
        typer.echo(f"{failure} Run `cheme init` to start one.", err=True)
        raise typer.Exit(2) from failure
    check_requirement(workspace.root)
    return workspace


def _require_config(workspace: Workspace) -> None:
    """Stop with a one-line message when ``plant.yaml`` does not load (commands that read it
    as a whole; ``cheme validate`` reports it as a finding instead)."""
    import yaml
    from pydantic import ValidationError

    try:
        workspace.config()
    except (ValidationError, yaml.YAMLError, UnicodeDecodeError) as failure:
        first = (str(failure).splitlines() or [type(failure).__name__])[0]
        typer.echo(f"plant.yaml does not load ({first}); run `cheme validate`", err=True)
        raise typer.Exit(2) from failure


@app.command()
def init(
    directory: Annotated[Path, typer.Argument(help="Where to create the repository.")] = Path("."),
    name: Annotated[str, typer.Option(help="Plant name for plant.yaml.")] = "",
    force: Annotated[bool, typer.Option(help="Overwrite existing files.")] = False,
) -> None:
    """Create a plant repository from the template (folders, schemas, skills, CI)."""
    from chemeascode.templates.install import init as do_init
    from chemeascode.templates.install import modified_finding, skill_status

    modified = [s for s in skill_status(directory) if s.state == "modified"]
    written = do_init(directory, name or directory.resolve().name, force=force)
    typer.echo(f"Wrote {len(written)} file(s) to {directory}.")
    for item in modified:
        typer.echo(modified_finding(item, replaced=force).format())
    typer.echo("Next: git init && cheme git-setup")
    typer.echo(
        "Note: the drawing-clean gate (checks/checks.yaml) fails on a sheet kept from the DEXPI "
        "reference P&ID, whose crossings and labels on lines are by design; accept them there "
        'with `accept: [{id: "pid/P-01.xml#*", reason: "DEXPI reference sheet"}]` '
        "(the sheet's file)."
    )
    typer.echo(
        "Note: Claude Code applies .claude/settings.json (the agents' allowlist) only once the "
        "folder is trusted: open it interactively once and accept the trust dialog, or run "
        "headless with --settings .claude/settings.json (cheme-as-code README, 'Running agents "
        "headless')."
    )


@app.command()
def validate(
    paths: Annotated[list[Path] | None, typer.Argument(help="Only these files.")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Machine-readable report.")] = False,
    fail_on: Annotated[
        Literal["error", "warning", "info"],
        typer.Option(help="Lowest level that fails: error, warning or info."),
    ] = "error",
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Print only failures.")] = False,
    skip_generators: Annotated[
        bool,
        typer.Option(
            "--skip-generators", help="Do not run generators to check generated sheets for drift."
        ),
    ] = False,
    ignore: Annotated[
        list[str] | None,
        typer.Option(
            "--ignore",
            metavar="RULE[,RULE]",
            help="Leave out these rules (ids or globs); also for --json and --fail-on.",
        ),
    ] = None,
    only: Annotated[
        list[str] | None,
        typer.Option(
            "--only", metavar="RULE[,RULE]", help="Report only these rules (ids or globs)."
        ),
    ] = None,
) -> None:
    """Validate every P&ID and list, and the lists against the P&IDs.

    A sheet declared generated in plant.yaml is rebuilt from its generator in a scratch file and
    compared (cheme.generated-sheet-drift); --skip-generators leaves that out.
    """
    from chemeascode.project.validate import validate_workspace

    workspace = _workspace()
    for path in paths or []:
        problem = (
            "no such file"
            if not path.exists()
            else None
            if workspace.contains(path)
            else f"not in this plant ({workspace.root}); run validate from its own plant"
        )
        if problem:
            typer.echo(f"{path}: {problem}", err=True)
            raise typer.Exit(2)
    report = validate_workspace(workspace, paths or None, generators=not skip_generators)
    report.filter_rules(ignore or (), only or ())
    if as_json:
        typer.echo(report.to_json())
    else:
        from chemeascode.foundation.findings import _SEVERITY

        shown = [
            f for f in report.findings if not quiet or _SEVERITY[f.level] >= _SEVERITY[fail_on]
        ]
        for finding in shown:
            typer.echo(finding.format())
        errors = sum(f.level == "error" for f in report.findings)
        warnings = sum(f.level == "warning" for f in report.findings)
        if not quiet or report.failed(fail_on):
            for line in report.drawing_lines():
                typer.echo(line)
            typer.echo(f"{len(report.files)} file(s): {errors} error(s), {warnings} warning(s)")
            typer.echo(report.compared_line())
    if report.failed(fail_on):
        raise typer.Exit(1)


@app.command()
def fmt(
    paths: Annotated[list[Path] | None, typer.Argument(help="P&ID files (default: all).")] = None,
    check: Annotated[bool, typer.Option(help="Only report files that would change.")] = False,
) -> None:
    """Write P&IDs in canonical form: readable ids on every object, DEXPI 2.0.1, stable order."""
    from chemeascode.domains.piping.fmt import FormatRefused, format_file

    # A planned sheet has no file yet: nothing to format.
    targets = paths or [p for p in _workspace().pid_files() if p.is_file()]
    failed = False
    for path in targets:
        try:
            result = format_file(path, check=check)
        except FormatRefused as refusal:
            typer.echo(f"{path}: refused: {refusal}", err=True)
            failed = True
            continue
        if result.changed:
            verb = "would reformat" if check else "reformatted"
            extra = f" ({result.ids_assigned} id(s) assigned)" if result.ids_assigned else ""
            typer.echo(f"{path}: {verb}{extra}")
            failed = failed or check
        if result.dropped:
            verb = "would drop" if check else "dropped"
            typer.echo(
                f"{path}: {verb} {len(result.dropped)} XML comment(s) / processing "
                "instruction(s); the DEXPI model has no place for them:",
                err=True,
            )
            for line in result.dropped:
                typer.echo(f"  {line}", err=True)
    if failed:
        raise typer.Exit(1)


def _safe_rev(rev: str) -> str:
    """*rev* for a file name: ``feature/x`` -> ``feature-x``."""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", rev).strip("-") or "rev"


@app.command()
def render(
    paths: Annotated[list[Path] | None, typer.Argument(help="P&ID files (default: all).")] = None,
    png: Annotated[bool, typer.Option("--png", help="Write PNG (needs the png extra).")] = False,
    scale: Annotated[
        float | None,
        typer.Option(
            help="PNG pixels per sheet millimetre (default 4; 8 with --tiles).", min=0.1, max=50
        ),
    ] = None,
    crop: Annotated[
        str | None,
        typer.Option(
            help="Only this sheet region: X0,Y0,X1,Y1 in sheet mm, origin top left, Y down."
        ),
    ] = None,
    rev: Annotated[
        str | None, typer.Option(help="Render the sheets as of this git revision.")
    ] = None,
    output: Annotated[Path | None, typer.Option("-o", help="Output file (one input).")] = None,
    tiles: Annotated[
        str | None,
        typer.Option(
            metavar="CxR",
            help="Overlapping tiles covering the sheet's whole viewBox (which can include content "
            "left of or above the frame), C columns by R rows (e.g. 4x3), or auto: "
            "build/<sheet>_tile-<row letter><column>.svg|png and build/<sheet>_tiles.json.",
        ),
    ] = None,
    findings: Annotated[
        bool, typer.Option("--findings", help="Mark the drawing-geometry findings on it.")
    ] = False,
    emphasise_inline: Annotated[
        bool,
        typer.Option(
            "--emphasise-inline",
            help="Draw valves, inline fittings and actuators 1.5 times larger with bolder lines, "
            "for reading a full-sheet render (a review aid; the XML is unchanged): "
            "build/<sheet>..._inline.svg|png.",
        ),
    ] = False,
) -> None:
    """Render P&IDs to SVG or PNG: build/<sheet>(@<rev>)(_crop-X0-Y0-X1-Y1)(_inline).svg|png."""
    from chemeascode.domains.piping.diffview import git_show
    from chemeascode.domains.piping.render import Crop, PngUnavailable, TooLarge, render_file

    if tiles is not None and (crop or output):
        typer.echo("--tiles covers the whole sheet: it does not go with --crop or -o.", err=True)
        raise typer.Exit(2)
    if tiles is not None:
        from chemeascode.domains.piping.render import parse_grid

        try:
            parse_grid(tiles, 420.0, 297.0, scale or 8.0)
        except ValueError as failure:
            typer.echo(f"--tiles: {failure}", err=True)
            raise typer.Exit(2) from failure
    scale = scale or (8.0 if tiles is not None else 4.0)
    box = None
    if crop:
        try:
            box = Crop.parse(crop)
        except ValueError as failure:
            typer.echo(f"--crop: {failure}", err=True)
            raise typer.Exit(2) from failure
    if rev is not None and (not rev or rev.startswith("-")):
        typer.echo(f"--rev: not a revision: {rev!r}", err=True)
        raise typer.Exit(2)
    workspace = _workspace() if rev is not None or not paths else None
    commit = _resolve(workspace.root, rev) if rev is not None else None  # type: ignore[union-attr]
    targets = paths or [
        p
        for p in workspace.pid_files()  # type: ignore[union-attr]
        if rev is not None or p.is_file()  # a planned sheet has no file yet
    ]
    # Sheets planned in plant.yaml: without explicit paths, one absent at --rev is skipped.
    planned = (
        set()
        if paths or workspace is None
        else {
            path.resolve()
            for entry in workspace.config().sheets
            if entry.status == "planned" and (path := workspace.sheet_path(entry.file)) is not None
        }
    )
    if output and len(targets) != 1:
        typer.echo("-o needs exactly one input file.", err=True)
        raise typer.Exit(2)
    suffix = ".png" if png else ".svg"
    failed = False
    for path in targets:
        source: Path | bytes = path
        stem = path.stem
        if rev is not None:
            sheet = workspace.relative(path)  # type: ignore[union-attr]
            content = git_show(workspace.root, commit, sheet)  # type: ignore[union-attr,arg-type]
            if content is None and path.resolve() in planned:
                continue
            if content is None:
                typer.echo(f"{sheet}: not in revision {rev}", err=True)
                failed = True
                continue
            source = content
            stem = f"{path.stem}@{_safe_rev(rev)}"
        if box is not None:
            stem += crop_suffix(box)
        if emphasise_inline:
            stem += "_inline"
        home = workspace or Workspace.find(path.parent)
        out = output or home.build_dir() / f"{stem}{suffix}"
        marks: dict[str, Any] = {}
        if findings:
            from chemeascode.foundation.acceptance import accepted_entries

            marks = {"sheet": home.relative(path), "accept": accepted_entries(home)[0]}
        try:
            if tiles is not None:
                _render_tiles(
                    source, out.parent, stem, tiles, png, scale, findings, marks, emphasise_inline
                )
                continue
            made = render_file(
                source,
                out,
                png=png,
                scale=scale,
                crop=box,
                findings=findings,
                emphasise=emphasise_inline,
                **marks,
            )
            typer.echo(f"{made}")
        except PngUnavailable as missing:
            typer.echo(str(missing), err=True)
            raise typer.Exit(2) from missing
        except TooLarge as large:
            typer.echo(f"{path}: {large}", err=True)
            raise typer.Exit(2) from large
        except Exception as failure:  # noqa: BLE001 - a sheet that does not load or draw: report, go on
            reason = f"{type(failure).__name__}: {failure}".splitlines()[0]
            typer.echo(f"{path}: cannot render: {reason}", err=True)
            failed = True
    if failed:
        raise typer.Exit(1)


def _render_tiles(
    source: Path | bytes,
    build: Path,
    stem: str,
    grid: str,
    png: bool,
    scale: float,
    findings: bool,
    marks: dict[str, Any],
    emphasise: bool = False,
) -> None:
    """``render --tiles``: write the tiles and their index, and print the index.

    Each line carries the ``--crop`` and ``--scale`` that reproduce its tile.
    """
    from chemeascode.domains.piping.render import render_tiles

    made = render_tiles(
        source,
        build,
        stem,
        grid,
        png=png,
        scale=scale,
        findings=findings,
        emphasise=emphasise,
        **marks,
    )
    index = build / f"{stem}_tiles.json"
    entries = []
    for tile in made:
        crop = ",".join(f"{v:g}" for v in (tile.crop.x0, tile.crop.y0, tile.crop.x1, tile.crop.y1))
        entry: dict[str, Any] = {"tile": tile.name, "crop": crop, "file": tile.file.name}
        if findings:
            entry["findings"] = [m.entry() for m in tile.marks]
        entries.append(entry)
        shown = f"  findings: {', '.join(tile.findings)}" if tile.findings else ""
        typer.echo(f"{tile.file}  tile {tile.name}  --crop {crop} --scale {scale:g}{shown}")
    payload = {"sheet": stem, "scale": scale, "overlap": 0.1, "tiles": entries}
    index.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="")
    typer.echo(f"{index}")


def crop_suffix(box: Any) -> str:
    """``_crop-150-50-300-180``: the part of an output name that names its crop."""
    return "_crop-" + "-".join(f"{v:g}" for v in (box.x0, box.y0, box.x1, box.y1))


def _resolve(root: Path, rev: str) -> str:
    """The commit *rev* names; exit 2 with ``unknown revision`` when it names none."""
    from chemeascode.domains.piping.diffview import resolve_rev

    commit = resolve_rev(root, rev)
    if commit is None:
        typer.echo(f"unknown revision {rev!r}", err=True)
        raise typer.Exit(2)
    return commit


def _change_line(change: Any, sheet: Any) -> str:
    """One change of ``cheme diff --list``."""
    owners = sheet.old_owner if change.kind == "removed" else sheet.new_owner
    owner = owners.get(change.object_id)
    if owner is None and change.kind == "modified":
        owner = sheet.old_owner.get(change.object_id)
    parts = [change.kind, change.object_type, change.object_id]
    if change.tag:
        parts.append(f"[{change.tag}]")
    parts.append(f"({change.domain})")
    if change.detail:
        parts.append(change.detail)
    return " ".join(parts) + f" -> drawn as {owner or 'not drawn'}"


_KINDS = ("added", "removed", "modified", "moved")


def _grouped_lines(result: Any, verbose: bool) -> list[str]:
    """``cheme diff --list``: one line per plant item with its counts (and, verbose, each
    change under it)."""
    groups: dict[str, list[Any]] = {}
    for change in result.changes:
        groups.setdefault(change.item, []).append(change)
    order = {"removed": 0, "added": 1, "modified": 2, "moved": 3, "changed": 4}
    rows = []
    for item, changes in groups.items():
        own = next((c.kind for c in changes if c.object_id == item and item), "changed")
        rows.append((order[own], item == "", item, own, changes))
    lines = []
    for _, _, item, own, changes in sorted(rows):
        counts = {k: sum(c.kind == k for c in changes) for k in _KINDS}
        summary = ", ".join(f"{counts[k]} {k}" for k in _KINDS[:3])
        if counts["moved"]:
            summary += f", {counts['moved']} moved"
        if item:
            info = result.items.get(item, {})
            tag = f" [{info['tag']}]" if info.get("tag") else ""
            lines.append(f"{own} {info.get('class', '?')} {item}{tag}: {summary}")
        else:
            lines.append(f"changed (no plant item): {summary}")
        if verbose:
            lines += ["  " + _change_line(change, result) for change in changes]
    return lines


@app.command()
def diff(
    old_rev: Annotated[str, typer.Argument(help="Old revision, e.g. main.")] = "HEAD",
    new_rev: Annotated[
        str | None, typer.Argument(help="New revision (default: the working tree).")
    ] = None,
    paths: Annotated[list[Path] | None, typer.Option("--path", help="Only these sheets.")] = None,
    html_out: Annotated[
        Path | None, typer.Option("--html", help="HTML report (default: build/diff.html).")
    ] = None,
    as_json: Annotated[
        bool, typer.Option("--json", help="Print every sheet's changes as JSON.")
    ] = False,
    as_list: Annotated[
        bool, typer.Option("--list", help="Print one line per changed plant item.")
    ] = False,
    flat: Annotated[
        bool, typer.Option("--flat", help="With --list: one line per changed object (0.2).")
    ] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="With --list: each change under its item.")
    ] = False,
) -> None:
    """Compare P&IDs between two git revisions; write an HTML report with changes highlighted.

    --json or --list print the result instead; the HTML report is then written only with --html.
    --list groups the changes by the plant item they belong to; --flat lists every object.
    A sheet that does not load or draw is named with the reason; the others are still compared,
    and the exit code is 1.
    """
    from chemeascode.domains.piping.diffview import diff_sheet, git_show, render_html, sheets_at

    if (flat or verbose) and not as_list:
        typer.echo("--flat and --verbose go with --list.", err=True)
        raise typer.Exit(2)
    for rev in (old_rev, new_rev):
        if rev is not None and (not rev or rev.startswith("-")):
            typer.echo(f"not a revision: {rev!r}", err=True)
            raise typer.Exit(2)
    workspace = _workspace()
    old_commit = _resolve(workspace.root, old_rev)
    new_commit = _resolve(workspace.root, new_rev) if new_rev is not None else None
    if paths:
        sheets = [workspace.relative(p) for p in paths]
    else:
        # Every sheet on either side: one deleted from (or only in) a side is compared too.
        found = set(sheets_at(workspace.root, old_commit))
        if new_commit is None:
            found.update(workspace.relative(p) for p in workspace.sheet_files())
        else:
            found.update(sheets_at(workspace.root, new_commit))
        sheets = sorted(found)
    results = []
    failed = False
    for sheet in sheets:
        old = git_show(workspace.root, old_commit, sheet)
        if new_commit is None:
            path = workspace.root / sheet
            new = path.read_bytes() if path.exists() else None
        else:
            new = git_show(workspace.root, new_commit, sheet)
        if old == new:
            continue
        result = diff_sheet(old, new, sheet, old_rev, new_rev or "working tree")
        results.append(result)
        if result.error:
            typer.echo(f"{sheet}: {result.error}", err=True)
            failed = True
        if as_json or (result.error and not result.changes):
            continue
        if as_list:
            typer.echo(f"{sheet}:" + (f" (sheet {result.status})" if result.status else ""))
            if flat:
                for change in result.changes:
                    typer.echo(_change_line(change, result))
            else:
                for line in _grouped_lines(result, verbose):
                    typer.echo(line)
            continue
        counts = {
            k: sum(c.kind == k for c in result.changes)
            for k in ("added", "removed", "modified", "moved")
        }
        typer.echo(f"{sheet}: " + ", ".join(f"{v} {k}" for k, v in counts.items()))
    if as_json:
        payload = []
        for result in results:
            item = asdict(result)
            del item["old_svg"], item["new_svg"]
            payload.append(item)
        typer.echo(json.dumps(payload, indent=2))
    if not results:
        if not as_json:
            typer.echo("No P&ID changed.")
        return
    if not (as_json or as_list) or html_out is not None:
        out = html_out or workspace.build_dir() / "diff.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render_html(results), encoding="utf-8")
        if not as_json:
            typer.echo(f"Report: {out}")
    if failed:
        raise typer.Exit(1)


@app.command()
def show(
    key: Annotated[str, typer.Argument(metavar="ID_OR_TAG", help="An XML id or a tag.")],
    sheet: Annotated[
        Path | None, typer.Option("--sheet", help="Only this sheet (default: every sheet).")
    ] = None,
    layout: Annotated[
        bool,
        typer.Option(
            "--layout",
            help="Measured plot-plan distances to the nearest items, buildings, "
            "roads, racks and the site boundary.",
        ),
    ] = False,
) -> None:
    """Where an object is: its block, owner, drawing, references and what references it."""
    from chemeascode.domains.piping.show import show as do_show

    if layout:  # plot-plan distances (pre-release issue 22)
        from chemeascode.domains.spatial.layout_distances import show_layout

        lines, found = show_layout(_workspace(), key)
        for line in lines:
            typer.echo(line)
        raise typer.Exit(0 if found else 1)

    if sheet is not None:
        if not sheet.is_file():
            typer.echo(f"{sheet}: no such file", err=True)
            raise typer.Exit(2)
        try:
            name = Workspace.find(sheet.parent).relative(sheet)
        except NotAPlantRepository:
            name = str(sheet)
        sheets = [(sheet, name)]
    else:
        workspace = _workspace()
        sheets = [(p, workspace.relative(p)) for p in workspace.sheet_files() if p.is_file()]
    lines, found = do_show(key, sheets)
    if sheet is None:  # a block, step or stream of process/flowsheet.yaml (by its id)
        from chemeascode.domains.process.summary import show_lines

        extra = show_lines(workspace, key)
        lines, found = extra + lines, found or bool(extra)
    for line in lines:
        typer.echo(line)
    if not found:
        raise typer.Exit(1)


@app.command()
def check(
    stage: Annotated[
        str | None,
        typer.Option(help="Gates of every stage up to this one (plant.yaml order)."),
    ] = None,
    only_stage: Annotated[
        bool, typer.Option("--only-stage", help="With --stage: only that stage's gates.")
    ] = False,
    write: Annotated[
        bool,
        typer.Option(
            help="Sign off the stage: record it in checks/status.json (refused unless "
            "the tree is clean and every gate passes)."
        ),
    ] = False,
    review: Annotated[
        Path | None,
        typer.Option(help="With --write: the review record the sign-off rests on."),
    ] = None,
    by: Annotated[
        str | None, typer.Option(help="With --write: who signs off (default: git user.name).")
    ] = None,
) -> None:
    """Run the engineering-step gates in checks/checks.yaml (--write signs off a stage)."""
    from chemeascode.project.checks import run_checks, stages_up_to

    workspace = _workspace()
    if (review or by) and not write:
        typer.echo("--review and --by go with --write.", err=True)
        raise typer.Exit(2)
    if only_stage and stage is None:
        typer.echo("--only-stage needs --stage.", err=True)
        raise typer.Exit(2)
    if write and stage is None:
        stage = workspace.config().stage
        typer.echo(f"Signing off stage {stage} (plant.yaml stage); name it with --stage.")
    if write and only_stage:
        typer.echo("--write signs off every stage up to --stage; drop --only-stage.", err=True)
        raise typer.Exit(2)
    stages = None
    if stage is not None and not only_stage:
        try:
            stages = stages_up_to(workspace, stage)
        except ValueError as failure:
            typer.echo(str(failure), err=True)
            raise typer.Exit(2) from failure
    results = run_checks(workspace, stage if only_stage else None, stages=stages)
    marks = {"pass": "ok  ", "fail": "FAIL", "n/a": "n/a "}
    for result in results:
        line = f"{marks[result.status]} [{result.stage}] {result.id}: {result.title}"
        typer.echo(line + (f" -- {result.detail}" if result.detail else ""))
    if write:
        from chemeascode.project.signoff import SignOffRefused, sign_off

        assert stage is not None and stages is not None
        try:
            done = sign_off(workspace, stage, stages, results, review=review, by=by)
        except SignOffRefused as refused:
            typer.echo(f"Sign-off of stage {stage} refused; nothing written:", err=True)
            for reason in refused.reasons:
                typer.echo(f"  - {reason}", err=True)
            raise typer.Exit(1) from refused
        entry = done.entry
        typer.echo(
            f"Wrote checks/status.json: stage {stage} signed off by {entry['signed_by']} at "
            f"{entry['commit'][:12]} on {entry['branch'] or 'a detached HEAD'}"
            + (f", review {entry['review']}" if entry.get("review") else "")
        )
        for note in done.notes:
            typer.echo(note)
        typer.echo("Commit checks/status.json now, as the last commit of the stage.")
    if any(r.status == "fail" for r in results):
        raise typer.Exit(1)


@app.command("status")
def status_command(
    as_json: Annotated[bool, typer.Option("--json", help="Machine-readable summary.")] = False,
    rev: Annotated[
        str | None,
        typer.Option(help="The repository as committed at this revision (a temporary worktree)."),
    ] = None,
    gates: Annotated[bool, typer.Option(help="Evaluate the gates (they may run commands).")] = True,
) -> None:
    """Where the repository stands: sheets, findings by sheet, gates, sign-offs, review findings."""
    from chemeascode.project.status import plant_status, status_lines, to_json

    workspace = _workspace()
    if rev is None:
        _require_config(workspace)
        data = plant_status(workspace, run_gates=gates)
    else:
        import tempfile

        from chemeascode.foundation import gitinfo

        commit = _resolve(workspace.root, rev)
        top = gitinfo.git(workspace.root, "rev-parse", "--show-toplevel").stdout.strip()
        inner = workspace.root.resolve().relative_to(Path(top).resolve())
        with tempfile.TemporaryDirectory(prefix="cheme-status-") as scratch:
            tree = Path(scratch) / "tree"
            added = gitinfo.git(workspace.root, "worktree", "add", "--detach", str(tree), commit)
            if added.returncode != 0:
                typer.echo(f"cannot check out {rev}: {added.stderr.strip()}", err=True)
                raise typer.Exit(2)
            try:
                at_rev = Workspace((tree / inner).resolve())
                _require_config(at_rev)
                data = plant_status(at_rev, run_gates=gates)
            finally:
                gitinfo.git(workspace.root, "worktree", "remove", "--force", str(tree))
        data["rev"] = commit
    if as_json:
        typer.echo(to_json(data))
        return
    for line in status_lines(data):
        typer.echo(line)


@app.command()
def impact(
    as_json: Annotated[bool, typer.Option("--json", help="Machine-readable findings.")] = False,
) -> None:
    """Artifacts whose sources changed since they were reviewed or generated: review needed.

    Review records whose scope or basis changed since, generated sheets whose process YAML
    changed, stale calculated values. Read-only, info only, exit 0: nothing is regenerated."""
    from chemeascode.project.impact import impact_report, review_needed

    workspace = _workspace()
    _require_config(workspace)
    if as_json:
        typer.echo(json.dumps(impact_report(workspace), indent=2))
        return
    findings = review_needed(workspace)
    for finding in findings:
        typer.echo(finding.format())
    typer.echo(f"{len(findings)} artifact(s) to review" if findings else "nothing to review")


@app.command()
def maturity(
    as_json: Annotated[bool, typer.Option("--json", help="The machine-readable report.")] = False,
    write: Annotated[
        bool, typer.Option(help="Also write the report to checks/maturity.json.")
    ] = False,
    require: Annotated[
        str | None,
        typer.Option(
            help="Exit 1 unless this calculation maturity level is reached: sourced, balanced, "
            "predictive, engineering."
        ),
    ] = None,
) -> None:
    """Which calculation maturity level the evidence supports, requirement by requirement.

    Levels: sourced process description, balanced conceptual PFD, converged predictive
    simulation, preliminary/basic engineering package. The design maturity a process.yaml
    claims, artifact completeness and review status are reported beside them and never raise a
    level; no command sets the review status (docs/concepts/glossary.md)."""
    from chemeascode.project.maturity import LEVELS, maturity_report, report_lines, write_report

    ids = [level[0] for level in LEVELS]
    if require is not None and require not in ids:
        typer.echo(f"--require: one of {', '.join(ids)}", err=True)
        raise typer.Exit(2)
    workspace = _workspace()
    _require_config(workspace)
    report = maturity_report(workspace.root)
    if as_json:
        typer.echo(report.to_json())
    else:
        for line in report_lines(report):
            typer.echo(line)
    if write:
        path = write_report(workspace.root, report)
        typer.echo(f"Wrote {workspace.relative(path)}", err=as_json)
    if require is not None and (
        report.level is None or ids.index(report.level) < ids.index(require)
    ):
        raise typer.Exit(1)


@app.command("issues")
def issues(
    all_: Annotated[bool, typer.Option("--all", help="Closed issues too.")] = False,
    as_json: Annotated[bool, typer.Option("--json", help="As JSON.")] = False,
) -> None:
    """The plant's issues (plant.yaml issues:) as engineering items: actions, holds, technical
    queries and design changes, by the gate they must close before. Exits 2 when they cannot be
    read (no GitHub token or network)."""
    from chemeascode.project.issues import IssuesUnavailable, issues_report

    workspace = _workspace()
    if workspace.config().issues is None:
        typer.echo("plant.yaml declares no issues: (repository, label)", err=True)
        raise typer.Exit(2)
    try:
        report = issues_report(workspace)
    except IssuesUnavailable as failure:
        typer.echo(f"issues not read: {failure}", err=True)
        raise typer.Exit(2) from failure
    if as_json:
        typer.echo(json.dumps(report, indent=2))
        return
    shown = [i for i in report["issues"] if all_ or i["state"] == "open"]
    order = {s: n for n, s in enumerate(report["stages"])}
    shown.sort(key=lambda i: (order.get(i["gate"], 99), i["type"] or "", -i["number"]))
    for issue in shown:
        gate = f"before {issue['gate']}" if issue["gate"] else "no gate"
        flags = " ".join(
            x for x in (issue["status"], issue["waiting"] and f"waiting:{issue['waiting']}") if x
        )
        kind = issue["type"] or "-"
        typer.echo(f"#{issue['number']:<5} {kind:<7} {gate:<15} {flags:<28} {issue['title']}")
    stage = report["stage"]
    blocking = report["blocking"].get(stage, [])
    typer.echo(
        f"{len(shown)} issue(s); {len(blocking)} open item(s) of any type to close before {stage}"
    )
    for kind, url in report["new"].items():
        typer.echo(f"new {kind}: {url}")


@app.command("cause-effect")
def cause_effect(
    output: Annotated[
        Path | None, typer.Option("-o", help="HTML file (default: build/cause-effect.html).")
    ] = None,
) -> None:
    """Write the cause-and-effect matrix of control/cause-effect.yaml (HTML and CSV)."""
    import yaml as _yaml
    from pydantic import ValidationError

    from chemeascode.domains.control.interlocks import write_matrix
    from chemeascode.domains.control.schemas import InterlockList

    workspace = _workspace()
    path = workspace.list_file("interlocks")
    if path is None:
        typer.echo("no control/cause-effect.yaml (schema: cheme schema interlocks)", err=True)
        raise typer.Exit(2)
    try:
        model = InterlockList.model_validate(_yaml.safe_load(path.read_text("utf-8")) or {})
    except (ValidationError, _yaml.YAMLError) as failure:
        typer.echo(f"{workspace.relative(path)} is invalid; run `cheme validate`", err=True)
        raise typer.Exit(2) from failure
    for written in write_matrix(workspace, model, output):
        typer.echo(workspace.relative(written))


@app.command()
def serve(
    repo: Annotated[
        Path | None,
        typer.Option(
            help="Plant repository (default: the one around the cwd), or a folder of plants "
            "(a process library): then every plant is served under /p/<id>/."
        ),
    ] = None,
    library: Annotated[
        bool,
        typer.Option(
            "--library",
            help="Serve every plant below the folder (at most 3 levels down), also when it "
            "lies inside a plant. Without it, a folder with no plant.yaml above it but plants "
            "below it is served as a library.",
        ),
    ] = False,
    host: Annotated[
        str,
        typer.Option(
            help="Address to bind. A non-local address (e.g. 0.0.0.0) serves the repository to "
            "the network; requests must still name a local host or an --allow-host name."
        ),
    ] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port to listen on.")] = 8765,
    ui: Annotated[
        Path | None,
        typer.Option(envvar="CHEME_UI", help="Built viewer to serve at / (a dist directory)."),
    ] = None,
    allow_host: Annotated[
        list[str] | None,
        typer.Option(
            help="Also accept requests for this host name or address in the Host header "
            "(repeatable), e.g. the machine's LAN address with --host 0.0.0.0. Only "
            "127.0.0.1, localhost, ::1 and a non-wildcard --host are accepted otherwise "
            "(against DNS rebinding); no wildcard."
        ),
    ] = None,
    allow_remote_checks: Annotated[
        bool,
        typer.Option(
            help="Let the viewer run the checks (POST /api/checks/run, which runs the "
            "command checks of checks/checks.yaml) although --host is not a local address."
        ),
    ] = False,
) -> None:
    """Serve the repository read-only as a JSON API (and the viewer, with --ui).

    In a folder of plants (process-library's root, or a folder of plant repositories) it serves
    each plant under /p/<id>/ and lists them at /api/plants (ADR 0034)."""
    try:
        from chemeascode.interfaces.api.serve import accepted_hosts, is_local_bind
        from chemeascode.interfaces.api.serve import serve as run_server
    except ImportError as missing:
        typer.echo(f"{missing}. Install the extra: cheme-as-code[serve]", err=True)
        raise typer.Exit(2) from missing

    from chemeascode.foundation.workspace import PLANT_FILE
    from chemeascode.interfaces.api.library import MAX_DEPTH, discover_plants

    root = (repo or Path.cwd()).resolve()
    plants = []
    if library:
        plants = discover_plants(root)
        if not plants:
            typer.echo(f"No {PLANT_FILE} below {root} ({MAX_DEPTH} levels).", err=True)
            raise typer.Exit(2)
    else:
        try:
            found = Workspace.find(root)
        except NotAPlantRepository as failure:
            plants = discover_plants(root)
            if not plants:
                typer.echo(f"{failure} No plant below it either ({MAX_DEPTH} levels).", err=True)
                raise typer.Exit(2) from failure
            library = True
        else:
            if repo is None:
                root = found.root
    try:
        hosts = accepted_hosts(host, allow_host or ())
    except ValueError as failure:
        typer.echo(str(failure), err=True)
        raise typer.Exit(2) from failure
    if not is_local_bind(host):
        typer.echo(
            f"warning: serving {root} to the network on {host}: every file of the repository "
            f"is readable by whoever reaches port {port} as {', '.join(hosts)}",
            err=True,
        )
        if allow_remote_checks:
            typer.echo(
                "warning: --allow-remote-checks: they can also run the command checks "
                "of checks/checks.yaml",
                err=True,
            )
        else:
            typer.echo("  the viewer cannot run the checks (--allow-remote-checks)", err=True)
    if library:
        typer.echo(
            f"Serving the library {root} ({len(plants)} plants) on http://{host}:{port}/: "
            "/api/plants, each plant under /p/<id>/"
        )
    else:
        typer.echo(f"Serving {root} on http://{host}:{port}/api/repo")
    try:
        run_server(
            root,
            host=host,
            port=port,
            ui_dir=ui,
            allow_hosts=allow_host or (),
            allow_remote_checks=allow_remote_checks,
            library=library,
        )
    except FileNotFoundError as failure:  # --ui without index.html
        typer.echo(str(failure), err=True)
        raise typer.Exit(2) from failure


@app.command("export-static")
def export_static(
    out: Annotated[
        Path,
        typer.Argument(
            help="Output directory: new, empty, or a previous snapshot (replaced). Not the "
            "plant repository, a directory containing it, or one inside it other than below "
            "build/ (e.g. build/snapshot)."
        ),
    ],
    repo: Annotated[
        Path | None, typer.Option(help="Plant repository (default: the one around the cwd).")
    ] = None,
    rev: Annotated[
        str | None, typer.Option(help="Export this git revision (default: the working tree).")
    ] = None,
    max_file_mb: Annotated[
        float, typer.Option(help="Leave out files larger than this (MB).", min=0.1)
    ] = 2.0,
    exclude: Annotated[
        list[str] | None,
        typer.Option(
            help="Leave out paths matching this glob (repeatable; ** spans directories, "
            "e.g. reviews/** or PROGRESS.md)."
        ),
    ] = None,
) -> None:
    """Write the viewer's API as static files: a read-only snapshot the viewer opens without a
    server (manifest.json + data/)."""
    try:
        from chemeascode.interfaces.api.export_static import ExportError, ExportWarning
        from chemeascode.interfaces.api.export_static import export_static as run_export
    except ImportError as missing:
        typer.echo(f"{missing}. Install the extra: cheme-as-code[serve]", err=True)
        raise typer.Exit(2) from missing

    root = repo.resolve() if repo else _workspace().root
    try:
        Workspace.find(root)
    except NotAPlantRepository as failure:
        typer.echo(str(failure), err=True)
        raise typer.Exit(2) from failure
    limit = int(max_file_mb * 1024 * 1024)
    try:
        with warnings.catch_warnings(
            record=True, action="always", category=ExportWarning
        ) as warned:
            manifest = run_export(
                root, out.resolve(), rev=rev, max_file_bytes=limit, exclude=exclude or ()
            )
    except ExportError as failure:
        typer.echo(str(failure), err=True)
        raise typer.Exit(2) from failure
    for warning in warned:
        if issubclass(warning.category, ExportWarning):
            typer.echo(f"warning: {warning.message}", err=True)
        else:  # not ours: shown as it would have been
            warnings.showwarning(
                warning.message, warning.category, warning.filename, warning.lineno
            )
    entries = manifest["entries"]
    failed = sorted(key for key, entry in entries.items() if entry["status"] != 200)
    typer.echo(f"{len(entries)} responses written to {out} ({len(failed)} not 200)")
    for key in failed:
        typer.echo(f"  {entries[key]['status']} {key}", err=True)
    for skipped in manifest["skipped"]:
        typer.echo(f"  left out (too large): {skipped['path']}", err=True)
    if manifest["excluded"]:
        typer.echo(f"  excluded: {', '.join(manifest['excluded'])}", err=True)
    for withheld in manifest["withheld"]:
        what = withheld["endpoint"] or ", ".join(withheld["files"])
        typer.echo(f"  withheld: {what} ({withheld['reason']})", err=True)


@app.command("git-setup")
def git_setup(
    hook: Annotated[bool, typer.Option(help="Install the pre-commit hook.")] = True,
) -> None:
    """Show P&IDs as review text in git diffs, and check them before each commit."""
    from chemeascode.integrations.git import setup

    for line in setup(_workspace().root, hook=hook):
        typer.echo(line)


@app.command(hidden=True)
def textconv(path: Path) -> None:
    """Git textconv driver: print the review text of a P&ID. Never fails."""
    from chemeascode.integrations.git import textconv as convert

    sys.stdout.write(convert(path))
    sys.stdout.flush()


@app.command()
def schema(
    kind: Annotated[
        str | None,
        typer.Argument(help="plant, equipment, lines, site_plan, ... (none: list the kinds)"),
    ] = None,
) -> None:
    """Print the JSON Schema of a YAML file kind, or list the kinds."""
    from chemeascode.foundation.workspace import LAYOUT_FILES, LIST_FILES, PLANT_FILE
    from chemeascode.schemas import LAYOUT_SCHEMAS, LIST_SCHEMAS, OTHER_SCHEMAS, PlantConfig

    schemas = {"plant": PlantConfig, **LIST_SCHEMAS, **LAYOUT_SCHEMAS}
    schemas.update({name: model for name, (model, _) in OTHER_SCHEMAS.items()})
    if kind is not None and kind not in schemas:
        kind = kind.replace("-", "_")  # site-plan is site_plan
    if kind is None:
        files = {"plant": PLANT_FILE, **LIST_FILES, **LAYOUT_FILES}
        files.update({name: where for name, (_, where) in OTHER_SCHEMAS.items()})
        width = max(len(name) for name in schemas)
        for name, model in schemas.items():
            title = (model.__doc__ or "").strip().splitlines()[0]
            typer.echo(f"{name:<{width}} {files[name]:<32} {title}")
        return
    if kind not in schemas:
        typer.echo(f"Unknown kind {kind!r}; one of {', '.join(schemas)}", err=True)
        raise typer.Exit(2)
    typer.echo(json.dumps(schemas[kind].model_json_schema(by_alias=True), indent=2))


@app.command()
def migrate(
    check: Annotated[
        bool, typer.Option("--check", help="Only list the files that would change (default).")
    ] = False,
    write: Annotated[bool, typer.Option("--write", help="Rewrite the files.")] = False,
) -> None:
    """Bring the YAML inputs to the schema versions this cheme-as-code reads: a file without
    `schema:` gets `schema: cheme/<kind>/v1` as its first key, its comments kept, and a v1 LCI
    dataset in lca/datasets/ (`schema: cheme/lca/v1`) gets `schema: cheme/lci_dataset/v2`.
    Exits 1 when --check finds a file to change or a file cannot be migrated."""
    from chemeascode.domains.equipment.datasheets import datasheet_paths
    from chemeascode.foundation.migrate import migrate as run_migrations

    if check and write:
        typer.echo("--check and --write do not go together.", err=True)
        raise typer.Exit(2)
    workspace = _workspace()
    migrations = run_migrations(workspace, datasheet_paths(workspace), write=write)
    changed = [m for m in migrations if m.text is not None]
    for migration in migrations:
        name = workspace.relative(migration.path)
        if migration.text is None:
            typer.echo(f"{name}: refused: {migration.problem}", err=True)
            continue
        verb = "migrated" if write else "would migrate"
        typer.echo(f"{name}: {verb} {migration.kind} {migration.found} -> {migration.target}")
    if not migrations:
        typer.echo("Nothing to migrate: every input is at the version this cheme-as-code reads.")
    elif changed:
        typer.echo(f"{len(changed)} file(s) {'migrated' if write else 'would change'}.")
    if len(changed) < len(migrations) or (changed and not write):
        raise typer.Exit(1)


def _sheet_for(key: str, sheet: Path | None) -> tuple[Path, str]:
    """The sheet to work on: *sheet*, or the one sheet of the workspace that has *key*."""
    if sheet is not None:
        if not sheet.is_file():
            typer.echo(f"{sheet}: no such file", err=True)
            raise typer.Exit(2)
        try:
            return sheet, Workspace.find(sheet.parent).relative(sheet)
        except NotAPlantRepository:
            return sheet, str(sheet)
    from chemeascode.domains.piping.show import Sheet, ShowError

    workspace = _workspace()
    found = []
    for path in workspace.pid_files():
        if not path.is_file():
            continue
        try:
            if Sheet.load(path).find(key):
                found.append(path)
        except ShowError:
            continue
    if len(found) != 1:
        where = ", ".join(workspace.relative(p) for p in found) or "no sheet"
        typer.echo(f"{key!r} is in {where}: name the sheet with --sheet", err=True)
        raise typer.Exit(2)
    return found[0], workspace.relative(found[0])


@app.command("copy")
def copy_command(
    key: Annotated[str, typer.Argument(metavar="ID", help="The object to copy (id or tag).")],
    prefix: Annotated[
        str, typer.Option(help="Id of the copy; every id inside it is derived from it.")
    ],
    tag: Annotated[str | None, typer.Option(help="Tag of the copy (TagName, ...).")] = None,
    offset: Annotated[
        str, typer.Option(help="Move the drawing by DX,DY (sheet mm, Y down).")
    ] = "0,0",
    sheet: Annotated[
        Path | None, typer.Option("--sheet", help="The sheet (default: the one holding ID).")
    ] = None,
    into: Annotated[
        str | None,
        typer.Option("--into", metavar="PARENT_ID", help="Put the copy into this object."),
    ] = None,
    print_only: Annotated[
        bool, typer.Option("--print", help="Print the copied XML; change no file.")
    ] = False,
    rename: Annotated[
        list[str] | None,
        typer.Option(
            "--rename", metavar="OLD=NEW", help="An inner tag of the copy (data, labels, ids)."
        ),
    ] = None,
    renumber: Annotated[
        list[str] | None,
        typer.Option(metavar="OLD:NEW", help="A number in the copy's inner tags, labels, ids."),
    ] = None,
    set_: Annotated[
        list[str] | None,
        typer.Option("--set", metavar="PROP=VALUE", help="On every copied object having PROP."),
    ] = None,
    sense_at: Annotated[
        str | None,
        typer.Option(metavar="ID[:X,Y]", help="Instrument: sensing location (and its node)."),
    ] = None,
    connect: Annotated[
        list[str] | None,
        typer.Option(metavar="PIPE[.END]=ITEM:NODE", help="Connect a copied pipe's open end."),
    ] = None,
) -> None:
    """Duplicate an object with its parts and drawing, renaming every id (e.g. a spare pump)."""
    from chemeascode.domains.piping.authoring._xml import parse_pair
    from chemeascode.domains.piping.authoring.copy import CopyError, copy_object

    def pairs(values: list[str] | None, sep: str, what: str) -> list[tuple[str, str]]:
        out = []
        for value in values or []:
            left, found, right = value.partition(sep)
            if not found or not left.strip():
                typer.echo(f"{what} {value}: expected A{sep}B", err=True)
                raise typer.Exit(2)
            out.append((left.strip(), right.strip()))
        return out

    try:
        delta = parse_pair(offset, "--offset")
    except ValueError as failure:
        typer.echo(str(failure), err=True)
        raise typer.Exit(2) from failure
    path, name = _sheet_for(key, sheet)
    try:
        result = copy_object(
            path,
            key,
            prefix,
            tag=tag,
            offset=delta,
            into=into,
            write=not print_only,
            name=name,
            renames=pairs(rename, "=", "--rename"),
            renumbers=pairs(renumber, ":", "--renumber"),
            sets=pairs(set_, "=", "--set"),
            sense_at=sense_at,
            connects=pairs(connect, "=", "--connect"),
        )
    except (CopyError, ValueError) as failure:
        typer.echo(str(failure), err=True)
        raise typer.Exit(2) from failure
    if print_only:
        typer.echo(f"<!-- CONCEPTUAL: {result.new_id}, next to {result.source_id} -->")
        typer.echo(result.xml_conceptual)
        for old, xml in zip(result.drawing_ids, result.xml_drawings, strict=True):
            where = f"{result.renamed[old]}, next to {old}" if old else "next to the original's"
            typer.echo(f"<!-- DRAWING: {where} -->")
            typer.echo(xml)
        typer.echo("<!-- END -->")
        for line in result.report(name):
            typer.echo(line, err=True)
        return
    for line in result.report(name):
        typer.echo(line)


def _fragment_sheet(
    kind: str,
    source: str | None,
    target: str | None,
    for_id: str | None,
    like: str | None,
    others: list[str] | None = None,
) -> Path | None:
    """Without --sheet: the one sheet of the workspace holding the ids a fragment refers to.

    Pipe ends at existing nodes need the sheet's real PipingNodePosition ids, ``--like`` and
    labels need its data. None when not in a plant repository or when no sheet (or more than
    one) holds them; fragment ids that are not pasted yet are in no sheet.
    """
    from chemeascode.domains.piping.show import Sheet, ShowError

    wanted = [for_id, like]
    if kind in ("pipe", "segment"):
        for end in (source, target):
            if end and ":" in end:
                wanted += end.split(":", 1)
    if kind == "signal":
        wanted += [source, *(target or "").split(",")]
    wanted += others or []
    wanted = [w.strip() for w in wanted if w and w.strip()]
    if kind not in ("pipe", "segment", "label", "signal", "nozzle", "instrument") or not wanted:
        return None
    try:
        workspace = Workspace.find()
    except NotAPlantRepository:
        return None
    found: list[tuple[Path, list[str]]] = []
    for path in workspace.pid_files():
        try:
            ids = Sheet.load(path).by_id if path.is_file() else {}
        except ShowError:
            continue
        held = [w for w in wanted if w in ids]
        if held:
            found.append((path, held))
    if len(found) == 1:
        path, held = found[0]
        typer.echo(
            f"note: using --sheet {workspace.relative(path)} (it holds {', '.join(held)})", err=True
        )
        return path
    if len(found) > 1:
        names = ", ".join(workspace.relative(p) for p, _ in found)
        typer.echo(
            f"note: {', '.join(wanted)} are in {names}: name the sheet with --sheet", err=True
        )
    return None


def _drafting_options(kind: str, **given) -> dict:
    """The options of the drafting kinds (equipment, ..., shape) that were given."""
    from chemeascode.domains.piping.authoring.fragment import DRAFTING_KINDS

    if kind in DRAFTING_KINDS:
        return given
    unused = [k for k, v in given.items() if v not in (None, False, [])]
    if unused:
        names = ", ".join(
            "a NAME argument"
            if k == "name"
            else "--" + k.replace("_", "-").replace("text-value", "text")
            for k in unused
        )
        typer.echo(f"{kind} takes no {names}", err=True)
        raise typer.Exit(2)
    return {}


@app.command()
def fragment(
    kind: Annotated[
        str,
        typer.Argument(
            help="node, pipe, valve, tee, segment, label, equipment, nozzle, instrument, "
            "signal, offpage, line, note or shape."
        ),
    ],
    name: Annotated[
        str | None, typer.Argument(help="shape: the catalogue name, e.g. COLUMN_SHAPE.")
    ] = None,
    object_id: Annotated[
        str | None,
        typer.Option("--id", help="Id of the new object; its parts' ids derive from it."),
    ] = None,
    dn: Annotated[str | None, typer.Option(help="Nominal diameter, e.g. 80.")] = None,
    standard: Annotated[
        str, typer.Option(help="DN standard: Din2448, Iso6708 or none.")
    ] = "Din2448",
    source: Annotated[
        str | None,
        typer.Option(
            "--from",
            metavar="ITEM:NODE|INST",
            help="pipe/segment: where it starts (ITEM:NODE); signal: the source instrument.",
        ),
    ] = None,
    target: Annotated[
        str | None,
        typer.Option(
            "--to",
            metavar="ITEM:NODE|TARGET[,...]",
            help="pipe/segment: where it ends (ITEM:NODE); signal: the operated valve(s) or "
            "instrument(s) it goes to, comma-separated for a trip.",
        ),
    ] = None,
    points: Annotated[
        str | None,
        typer.Option(
            help="pipe/signal/instrument (measuring line): the bends between the two node "
            "positions, x,y;x,y (default: routed)."
        ),
    ] = None,
    valve_class: Annotated[
        str | None,
        typer.Option(
            "--class",
            help="valve: GlobeValve (default), BallValve, GateValve, Silencer, ...; "
            "equipment: the DEXPI class, e.g. CentrifugalCompressor.",
        ),
    ] = None,
    at: Annotated[str | None, typer.Option(help="Position X,Y (sheet mm, Y down).")] = None,
    rotation: Annotated[
        float,
        typer.Option(
            help="valve/tee: flow direction, degrees (0: left to right); equipment/offpage: "
            "symbol rotation, degrees."
        ),
    ] = 0.0,
    branch_dn: Annotated[str | None, typer.Option(help="tee: DN of the branch node.")] = None,
    branch: Annotated[
        str | None,
        typer.Option(
            help="tee: side the branch leaves (absolute): up, down, left or right "
            "(default: left of the flow, up for --rotation 0)."
        ),
    ] = None,
    for_id: Annotated[
        str | None, typer.Option("--for", metavar="ID", help="label: the object it shows.")
    ] = None,
    attribute: Annotated[
        str | None, typer.Option(help="label: the attribute shown, e.g. TagName.")
    ] = None,
    tag: Annotated[
        str | None,
        typer.Option(
            help="valve: PipingComponentNumber; tee: its tag; equipment: K-1101; instrument: "
            "PIC-4101; nozzle: SubTagName."
        ),
    ] = None,
    number: Annotated[
        str | None,
        typer.Option(
            help="segment: SegmentNumber (S2); line: LineNumber; signal: ActuatingSystemNumber."
        ),
    ] = None,
    like: Annotated[
        str | None,
        typer.Option(help="segment: copy fluid, class and DN data from this segment (--sheet)."),
    ] = None,
    sheet: Annotated[
        Path | None,
        typer.Option("--sheet", help="Take shape ids, node positions and values from it."),
    ] = None,
    shape: Annotated[
        str | None, typer.Option(help="equipment: symbol name (default: by --class).")
    ] = None,
    scale: Annotated[
        str | None, typer.Option(help="equipment: symbol scale S or SX,SY; valve: S.")
    ] = None,
    nozzle: Annotated[
        list[str] | None,
        typer.Option(
            "--nozzle",
            metavar="NAME:dx,dy[:DN[:DIR]]",
            help="equipment: a nozzle, offset from the symbol centre; no DN: an instrument "
            "connection. The stub points away from the nearer side of the symbol, or DIR "
            "(left, right, up, down; N1:-10,40::left without DN). Repeat it.",
        ),
    ] = None,
    marker: Annotated[
        list[str] | None,
        typer.Option(
            "--marker",
            metavar="NAME:dy[:SY][:m]",
            help="equipment: a marker symbol inside it (COLUMN_PACKED_BED_SHAPE, "
            "COLUMN_TRAY_SHAPE), dy from the symbol centre, ScaleY SY (ScaleX: the "
            "equipment's), m: mirrored. Repeat it.",
        ),
    ] = None,
    label_at: Annotated[str | None, typer.Option(help="equipment: tag label position X,Y.")] = None,
    on: Annotated[
        str | None, typer.Option(metavar="EQUIPMENT", help="nozzle: the equipment's id.")
    ] = None,
    sense: Annotated[
        str | None,
        typer.Option(
            metavar="ITEM[:x,y]",
            help="instrument: what it measures (nozzle, segment, inline item), and where the "
            "measuring line starts.",
        ),
    ] = None,
    field: Annotated[
        bool, typer.Option("--field/--central", help="instrument: field or central bubble.")
    ] = False,
    fail_action: Annotated[
        str | None, typer.Option(help="signal to a valve: FC, FO or FL.")
    ] = None,
    inflow: Annotated[
        bool, typer.Option("--in", help="offpage: flow comes in from another sheet.")
    ] = False,
    outflow: Annotated[
        bool, typer.Option("--out", help="offpage: flow goes out to another sheet.")
    ] = False,
    note: Annotated[str | None, typer.Option(help="offpage: text beside the arrow.")] = None,
    note_at: Annotated[str | None, typer.Option(help="offpage: position of --note.")] = None,
    text: Annotated[str | None, typer.Option(help="note: the text.")] = None,
    fluid: Annotated[str | None, typer.Option(help="line: FluidCode.")] = None,
) -> None:
    """Print a ready-to-paste XML fragment (conceptual part and drawing part)."""
    from chemeascode.domains.piping.authoring.fragment import FragmentError, make_fragment

    if inflow and outflow:
        typer.echo("offpage: give --in or --out, not both", err=True)
        raise typer.Exit(2)
    if name is not None and kind != "shape":
        hint = f": give the new object's id as --id {name}" if object_id is None else ""
        typer.echo(f"{kind} takes no NAME argument{hint}", err=True)
        raise typer.Exit(2)
    if sheet is not None and not sheet.is_file():
        typer.echo(f"{sheet}: no such file", err=True)
        raise typer.Exit(2)
    if sheet is None:
        sheet = _fragment_sheet(
            kind, source, target, for_id, like, [on or "", (sense or "").split(":")[0]]
        )
    try:
        made = make_fragment(
            kind,
            object_id,
            dn=dn,
            standard=standard,
            source=source,
            target=target,
            points=points,
            valve_class=valve_class,
            at=at,
            rotation=rotation,
            branch_dn=branch_dn,
            branch=branch,
            for_id=for_id,
            attribute=attribute,
            tag=tag,
            number=number,
            like=like,
            sheet=sheet,
            scale=scale,
            **_drafting_options(
                kind,
                name=name,
                shape=shape,
                nozzles=nozzle,
                markers=marker,
                label_at=label_at,
                on=on,
                sense=sense,
                field=field,
                fail_action=fail_action,
                direction="in" if inflow else "out" if outflow else None,
                note=note,
                note_at=note_at,
                text_value=text,
                fluid=fluid,
            ),
        )
    except (FragmentError, ValueError) as failure:
        typer.echo(str(failure), err=True)
        raise typer.Exit(2) from failure
    typer.echo(made.text())
    for note in made.notes:
        typer.echo(f"note: {note}", err=True)


# -- generator scripts: cheme run, cheme regen (cli_scripts.py) ---------------------------
from chemeascode.interfaces.cli.scripts import register as _register_scripts  # noqa: E402

_register_scripts(app)
# cheme move / rename / set (pre-release issue 14): their own module, registered here.
from chemeascode.interfaces.cli.edit import register as _register_edit_commands  # noqa: E402

_register_edit_commands(app)
# cheme sheet new / sheet meta (sheet_cli.py)
from chemeascode.interfaces.cli.sheet import sheet_app  # noqa: E402

app.add_typer(sheet_app, name="sheet")
# cheme process build / streams / layout (process/cli.py)
from chemeascode.interfaces.cli.process import process_app  # noqa: E402

app.add_typer(process_app, name="process")
# cheme layout build
from chemeascode.interfaces.cli.layout import layout_app  # noqa: E402

app.add_typer(layout_app, name="layout")
# cheme assess mto / estimate
from chemeascode.interfaces.cli.assess import assess_app  # noqa: E402

app.add_typer(assess_app, name="assess")

from chemeascode.interfaces.cli.datasheets import datasheets_app  # noqa: E402

app.add_typer(datasheets_app, name="datasheets")
# cheme skills status / update
from chemeascode.interfaces.cli.skills import skills_app  # noqa: E402

app.add_typer(skills_app, name="skills")
# cheme chemistry props
from chemeascode.interfaces.cli.chemistry import chemistry_app  # noqa: E402

app.add_typer(chemistry_app, name="chemistry")

# cheme control report
from chemeascode.interfaces.cli.control import control_app  # noqa: E402

app.add_typer(control_app, name="control")

from chemeascode.interfaces.cli.experiments import experiments_app  # noqa: E402
from chemeascode.interfaces.cli.safety import safety_app  # noqa: E402

app.add_typer(safety_app, name="safety")

app.add_typer(experiments_app, name="experiments")
# cheme data fetch / status: optional datasets in the user data directory
from chemeascode.interfaces.cli.data import data_app  # noqa: E402

app.add_typer(data_app, name="data")

from chemeascode.interfaces.cli.runs import runs_app  # noqa: E402

app.add_typer(runs_app, name="runs")
