"""``cheme run`` and ``cheme regen``: generator scripts and generated sheets."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from chemeascode.foundation.workspace import NotAPlantRepository, Workspace


def _root() -> Path:
    """The repository root, or the working directory outside a plant repository."""
    try:
        return Workspace.find().root
    except NotAPlantRepository:
        return Path.cwd()


def run(
    ctx: typer.Context,
    script: Annotated[
        Path, typer.Argument(help="The Python file to run, e.g. scripts/draft_P-02.py.")
    ],
    fmt_sheets: Annotated[
        list[Path] | None,
        typer.Option(
            "--fmt",
            metavar="SHEET",
            help="After a successful run, run cheme fmt on this sheet (repeatable).",
        ),
    ] = None,
) -> None:
    """Run a Python script in cheme-as-code's interpreter, where pyDEXPI and chemeascode import.

    Usage: cheme run [--fmt SHEET] SCRIPT [ARGS...]. Options go before SCRIPT: everything
    after it goes to the script (sys.argv[1:]); its exit code is cheme-as-code's. The
    working directory is the repository root, so relative paths mean the same wherever you start
    it. Use this instead of python3 or uv run python: neither has pyDEXPI in a plant repository.
    """
    from chemeascode.interfaces.cli.run import ScriptNotFound, resolve_script, run_script

    root = _root()
    try:
        path = resolve_script(script, root)
    except ScriptNotFound as missing:
        typer.echo(str(missing), err=True)
        raise typer.Exit(2) from missing
    args = list(ctx.args)
    if any(a == "--fmt" or a.startswith("--fmt=") for a in args):
        typer.echo(
            "warning: --fmt after SCRIPT goes to the script, cheme does not format anything; "
            "write cheme run --fmt SHEET SCRIPT [ARGS...]",
            err=True,
        )
    code = run_script(path, args, root)
    if code == 0 and fmt_sheets:
        from chemeascode.domains.piping.fmt import FormatRefused, dropped_note, format_file

        for sheet in fmt_sheets:
            target = sheet if sheet.is_absolute() else root / sheet
            try:
                result = format_file(target)
            except (FormatRefused, OSError) as refusal:
                typer.echo(f"{sheet}: fmt refused: {refusal}", err=True)
                code = 1
                continue
            if result.changed:
                typer.echo(f"{sheet}: reformatted", err=True)
            if result.dropped:
                typer.echo(f"{sheet}: fmt {dropped_note(result.dropped)}", err=True)
    if code:
        raise typer.Exit(code)


def regen(
    sheets: Annotated[
        list[str] | None,
        typer.Argument(help="Sheet ids or files (default: every sheet with a generator)."),
    ] = None,
    force: Annotated[
        bool, typer.Option(help="Overwrite a sheet edited by hand since its last generation.")
    ] = False,
    detach: Annotated[
        bool,
        typer.Option("--detach", help="Make the sheets hand-maintained: remove their generator."),
    ] = False,
    list_only: Annotated[
        bool, typer.Option("--list", help="Print which sheets are generated; change nothing.")
    ] = False,
) -> None:
    """Rebuild generated sheets: frame -> cheme run SCRIPT FILE -> fmt.

    A sheet is generated when plant.yaml gives it generator: {script, frame}; it is then not
    edited by hand. regen refuses a sheet that differs from what its generator (as committed)
    makes, naming the items edited by hand, unless --force. --detach removes the generator: the
    XML becomes the source and the script provenance only.
    """
    from chemeascode.domains.piping.generators import (
        GeneratorError,
        describe,
        find_entry,
        generated_entries,
        regenerate,
        sheet_entries,
    )
    from chemeascode.domains.piping.generators import detach as do_detach

    try:
        workspace = Workspace.find()
    except NotAPlantRepository as failure:
        typer.echo(f"{failure} Run `cheme init` to start one.", err=True)
        raise typer.Exit(2) from failure
    try:
        if list_only:
            for entry in sheet_entries(workspace):
                typer.echo(describe(entry))
            return
        if sheets:
            entries = [find_entry(workspace, key) for key in sheets]
        elif detach:
            typer.echo("--detach needs the sheets to detach.", err=True)
            raise typer.Exit(2)
        else:
            entries = generated_entries(workspace)
            if not entries:
                typer.echo("No sheet declares a generator in plant.yaml.")
                return
    except GeneratorError as failure:
        typer.echo(str(failure), err=True)
        raise typer.Exit(2) from failure
    failed = False
    for entry in entries:
        try:
            lines = (
                do_detach(workspace, entry)
                if detach
                else regenerate(workspace, entry, force=force).lines
            )
        except GeneratorError as failure:
            typer.echo(f"{entry.id}: refused: {failure}" if not detach else str(failure), err=True)
            failed = True
            continue
        for line in lines:
            typer.echo(line)
    if failed:
        raise typer.Exit(1)


def register(app: typer.Typer) -> None:
    """Add ``run`` and ``regen`` to the ``cheme`` command line."""
    app.command(
        "run",
        context_settings={
            "allow_extra_args": True,
            "ignore_unknown_options": True,
            "allow_interspersed_args": False,
        },
    )(run)
    app.command("regen")(regen)
