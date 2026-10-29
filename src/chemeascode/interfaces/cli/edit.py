"""``cheme move``, ``rename`` and ``set``: the edit commands, registered on the main app."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

_SHEET = typer.Option("--sheet", help="The sheet (default: the one holding ID).")
_PRINT = typer.Option("--print", help="Dry run: print the change as a diff; write nothing.")
_NO_FMT = typer.Option("--no-fmt", help="Do not run cheme fmt after writing.")


def _find_sheet(key: str, sheet: Path | None) -> tuple[Path, str]:
    """*sheet*, or the one sheet of the workspace that has *key*; exit 2 with why otherwise."""
    from chemeascode.domains.piping.show import Sheet, ShowError
    from chemeascode.interfaces.cli import _sheet_for, _workspace

    if sheet is not None:
        return _sheet_for(key, sheet)
    workspace = _workspace()
    found = []
    for path in workspace.pid_files():
        try:
            if path.is_file() and Sheet.load(path).find(key):
                found.append(path)
        except ShowError:
            continue
    if not found:
        typer.echo(f"no sheet has an object with id or tag {key!r}", err=True)
        raise typer.Exit(2)
    if len(found) > 1:
        names = ", ".join(workspace.relative(p) for p in found)
        typer.echo(f"{key!r} is in {names}: name the sheet with --sheet", err=True)
        raise typer.Exit(2)
    return found[0], workspace.relative(found[0])


def _run(edit, key: str, sheet: Path | None, print_only: bool) -> None:
    """Find the sheet, run *edit(path, name)*, print its report (and diff), exit 2 on refusal."""
    from chemeascode.domains.piping.authoring.edit import EditError

    path, name = _find_sheet(key, sheet)
    try:
        result = edit(path, name)
    except (EditError, ValueError) as failure:
        typer.echo(str(failure), err=True)
        raise typer.Exit(2) from failure
    if print_only:
        typer.echo(result.diff, nl=False)
        for line in result.report():
            typer.echo(line, err=True)
        return
    for line in result.report():
        typer.echo(line)


def move(
    key: Annotated[str, typer.Argument(metavar="ID", help="The object to move (id or tag).")],
    offset: Annotated[str, typer.Option(help="DX,DY in sheet mm (Y down), e.g. -8,12.")],
    sheet: Annotated[Path | None, _SHEET] = None,
    print_only: Annotated[bool, _PRINT] = False,
    no_fmt: Annotated[bool, _NO_FMT] = False,
) -> None:
    """Move an object's drawing: symbol, node positions, labels; attached lines follow."""
    from chemeascode.domains.piping.authoring._xml import parse_pair
    from chemeascode.domains.piping.authoring.edit import move_object

    try:
        delta = parse_pair(offset, "--offset")
    except ValueError as failure:
        typer.echo(str(failure), err=True)
        raise typer.Exit(2) from failure
    _run(
        lambda path, name: move_object(
            path, key, delta, write=not print_only, name=name, fmt=not no_fmt
        ),
        key,
        sheet,
        print_only,
    )


def rename(
    old: Annotated[str, typer.Argument(help="The id (or a tag) to rename.")],
    new: Annotated[str, typer.Argument(help="The new id (or tag).")],
    children: Annotated[
        bool, typer.Option(help="Also rename the ids derived from it: OLD_* -> NEW_*.")
    ] = False,
    ids: Annotated[
        bool,
        typer.Option(help="Renaming a tag: also rename the ids that spell it (HV4146 -> HV4147)."),
    ] = False,
    tag: Annotated[
        bool,
        typer.Option(
            "--tag",
            help="NEW is the new tag of the object OLD names (by id): retags one of two "
            "objects sharing a tag (an instrument's sensor and actuator follow).",
        ),
    ] = False,
    sheet: Annotated[Path | None, _SHEET] = None,
    print_only: Annotated[bool, _PRINT] = False,
    no_fmt: Annotated[bool, _NO_FMT] = False,
) -> None:
    """Rename an id and every reference to it, or a tag and the labels that show it."""
    from chemeascode.domains.piping.authoring.edit import rename as do_rename

    _run(
        lambda path, name: do_rename(
            path,
            old,
            new,
            children=children,
            ids=ids,
            tag=tag,
            write=not print_only,
            name=name,
            fmt=not no_fmt,
        ),
        old,
        sheet,
        print_only,
    )


def set_command(
    key: Annotated[str, typer.Argument(metavar="ID", help="The object (id or tag).")],
    assignments: Annotated[
        list[str],
        typer.Argument(
            metavar="PROPERTY=VALUE...",
            help="DEXPI attribute names and values (FluidCode=Nitrogen, "
            "NominalCapacityVolume='26 MetreCubed', Stroke.Width=0.5); PROPERTY= removes it.",
        ),
    ],
    sheet: Annotated[Path | None, _SHEET] = None,
    print_only: Annotated[bool, _PRINT] = False,
    no_fmt: Annotated[bool, _NO_FMT] = False,
) -> None:
    """Set data values of an object (typed as DEXPI defines them) and the labels showing them."""
    from chemeascode.domains.piping.authoring.edit import EditError, parse_assignment, set_values

    try:
        pairs = [parse_assignment(a) for a in assignments]
    except EditError as failure:
        typer.echo(str(failure), err=True)
        raise typer.Exit(2) from failure
    _run(
        lambda path, name: set_values(
            path, key, pairs, write=not print_only, name=name, fmt=not no_fmt
        ),
        key,
        sheet,
        print_only,
    )


def crossings(
    sheets: Annotated[
        list[Path] | None,
        typer.Argument(metavar="[SHEET...]", help="P&ID files (default: every P&ID)."),
    ] = None,
    gap: Annotated[float, typer.Option(help="Gap length in sheet mm.")] = 3.0,
    check: Annotated[
        bool, typer.Option("--check", help="Write nothing; exit 1 if a crossing is not shown.")
    ] = False,
    print_only: Annotated[bool, _PRINT] = False,
    no_fmt: Annotated[bool, _NO_FMT] = False,
) -> None:
    """Show every crossing of two lines by a gap: pipes run through instrument lines, the
    horizontal through the vertical of two lines of one kind; gaps drawn in the line that
    should run through are joined."""
    from chemeascode.domains.piping.authoring.crossings import apply_crossings
    from chemeascode.domains.piping.authoring.edit import EditError
    from chemeascode.interfaces.cli import _sheet_for, _workspace

    if sheets:
        targets = [_sheet_for("", s) for s in sheets]
    else:
        workspace = _workspace()
        targets = [(p, workspace.relative(p)) for p in workspace.pid_files() if p.is_file()]
    pending = False
    for path, name in targets:
        try:
            result = apply_crossings(
                path, gap=gap, write=not (print_only or check), name=name, fmt=not no_fmt
            )
        except (EditError, ValueError) as failure:
            typer.echo(str(failure), err=True)
            raise typer.Exit(2) from failure
        pending = pending or bool(result.diff)
        if print_only:
            typer.echo(result.diff, nl=False)
        for line in result.report():
            typer.echo(line, err=print_only)
    if check and pending:
        raise typer.Exit(1)


def register(app: typer.Typer) -> None:
    app.command()(move)
    app.command()(rename)
    app.command("set")(set_command)
    app.command()(crossings)
