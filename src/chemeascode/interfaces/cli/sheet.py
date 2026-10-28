"""``cheme sheet new`` and ``cheme sheet meta``: start a sheet, set its title block."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from chemeascode.foundation.workspace import NotAPlantRepository, Workspace

sheet_app = typer.Typer(
    name="sheet",
    help="Start a P&ID sheet with a real title block, or change its title block.",
    no_args_is_help=True,
)


def _workspace() -> Workspace:
    """The repository, with a readable ``plant.yaml`` (else a one-line error and exit 2)."""
    import yaml
    from pydantic import ValidationError

    try:
        workspace = Workspace.find()
    except NotAPlantRepository as failure:
        typer.echo(f"{failure} Run `cheme init` to start one.", err=True)
        raise typer.Exit(2) from failure
    from chemeascode.foundation.workspace import check_requirement

    check_requirement(workspace.root)
    try:
        workspace.config()
    except (ValidationError, yaml.YAMLError, OSError) as failure:
        first = str(failure).strip().splitlines()[0] if str(failure).strip() else type(failure)
        typer.echo(f"plant.yaml: {first}; `cheme validate` shows where", err=True)
        raise typer.Exit(2) from failure
    return workspace


def _sheet_file(workspace: Workspace, key: str) -> Path:
    """The file of sheet *key*: a path, a sheet id of plant.yaml, or ``pid/<key>.xml``."""
    given = Path(key)
    if given.suffix == ".xml" and given.is_file():
        return given
    entry = next((s for s in workspace.config().sheets if s.id == key), None)
    path = workspace.sheet_path(entry.file) if entry else workspace.root / "pid" / f"{key}.xml"
    if path is None or not path.is_file():
        planned = entry is not None and entry.status == "planned"
        hint = f"; start it with `cheme sheet new {key}`" if planned or entry is None else ""
        typer.echo(f"sheet {key}: no file{hint}", err=True)
        raise typer.Exit(2)
    return path


@sheet_app.command("new")
def new(
    sheet_id: Annotated[str, typer.Argument(metavar="ID", help="Sheet id, e.g. P-05.")],
    title: Annotated[
        str, typer.Option(help="Sheet title (DrawingName); default: its plant.yaml title.")
    ] = "",
    file: Annotated[
        str | None, typer.Option(help="Path from the repository root (default pid/<ID>.xml).")
    ] = None,
    revision: Annotated[
        str | None, typer.Option(help="RevisionNumber (default: plant.yaml project.revision).")
    ] = None,
    force: Annotated[bool, typer.Option(help="Overwrite an existing file.")] = False,
) -> None:
    """Write a new sheet from the template, its title block filled from plant.yaml.

    Sets the Model name and uri, the diagram Name and the MetaData (drawing and sheet number,
    title, project, client, site, revision, dates, status "for review"; approver, approval date
    and checker stay empty) with their title-block texts, and adds the sheet to plant.yaml (or
    marks a planned one drafted).
    """
    from chemeascode.domains.piping.sheets import SheetError, new_sheet

    workspace = _workspace()
    try:
        _, notes = new_sheet(workspace, sheet_id, title, file, revision=revision, force=force)
    except SheetError as failure:
        typer.echo(f"sheet new: {failure}", err=True)
        raise typer.Exit(2) from failure
    for note in notes:
        typer.echo(note)


@sheet_app.command("meta")
def meta(
    sheet: Annotated[str, typer.Argument(metavar="SHEET", help="Sheet id or file.")],
    pairs: Annotated[
        list[str] | None,
        typer.Argument(
            metavar="KEY=VALUE...",
            help="MetaData property (RevisionNumber) or short name (Revision, Status, Title, "
            "Approver, Checker, Client, Site, Project, ...), or ModelName, ModelUri, "
            "DiagramName. An empty value empties it. None: print the title block.",
        ),
    ] = None,
) -> None:
    """Show or set title-block values: the MetaData and the title-block texts together."""
    from chemeascode.domains.piping.sheets import (
        SheetError,
        read_title_block,
        resolve_key,
        set_metadata,
    )

    workspace = _workspace()
    path = _sheet_file(workspace, sheet)
    name = workspace.relative(path)
    content = path.read_bytes()
    if not pairs:
        from lxml import etree

        root = etree.fromstring(
            content, etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=True)
        )
        block = read_title_block(root)
        typer.echo(f"ModelName: {block.model_name or ''}")
        typer.echo(f"ModelUri: {block.model_uri or ''}")
        typer.echo(f"DiagramName: {block.diagram_name or ''}")
        for prop, (values, _) in sorted(block.values.items()):
            typer.echo(f"{prop}: {' | '.join(values)}")
        return
    values: dict[str, str] = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key.strip():
            typer.echo(f"sheet meta: {pair!r} is not KEY=VALUE", err=True)
            raise typer.Exit(2)
        values[key.strip()] = value
    try:
        for key in values:
            resolve_key(key)
        written, changed = set_metadata(content, values)
    except SheetError as failure:
        typer.echo(f"sheet meta: {failure}", err=True)
        raise typer.Exit(2) from failure
    if written != content:
        from chemeascode.domains.piping.fmt import dropped_markup, dropped_note

        path.write_bytes(written)
        dropped = dropped_markup(content)
        if dropped:
            typer.echo(f"{name}: cheme fmt {dropped_note(dropped)}", err=True)
    for key, value in values.items():
        typer.echo(f"{name}: {resolve_key(key)} = {value!r}")
    for text_id, old, new in changed:
        typer.echo(f"{name}: title-block text {text_id}: {old!r} -> {new!r}")
