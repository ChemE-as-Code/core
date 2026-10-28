"""``cheme datasheets``: draft datasheets for the equipment list."""

from __future__ import annotations

from typing import Annotated

import typer

from chemeascode.foundation.workspace import NotAPlantRepository, Workspace

datasheets_app = typer.Typer(
    help="Equipment datasheets: drafts, calculated sizes and dimensions, outline drawings.",
    no_args_is_help=True,
)


@datasheets_app.command("draft")
def draft(
    tag: Annotated[
        list[str] | None, typer.Option("--tag", help="Only this item (repeatable).")
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Print the drafts, write nothing.")
    ] = False,
) -> None:
    """Write a draft equipment/datasheets/<TAG>.yaml for every listed item without one: type,
    service, design conditions and material from the equipment list, dimensions, nozzles from
    the P&IDs, inlet and outlet conditions from the flowsheet streams linked to it; every value
    with its source, unknowns TBD, `draft: true`. Existing datasheets are never touched."""
    from chemeascode.foundation.workspace import check_requirement
    from chemeascode.project.datasheets import draft_missing

    try:
        workspace = Workspace.find()
    except NotAPlantRepository as failure:
        typer.echo(f"{failure} Run `cheme init` to start one.", err=True)
        raise typer.Exit(2) from failure
    check_requirement(workspace.root)
    result = draft_missing(workspace.root, tag or None, write=not dry_run)
    for finding in result.findings:
        typer.echo(finding.format(), err=True)
    if dry_run:
        for name, text in result.texts.items():
            typer.echo(f"--- {name}")
            typer.echo(text, nl=False)
    else:
        for name in result.written:
            typer.echo(f"wrote {name}")
    for name in result.kept:
        typer.echo(f"kept {name} (exists)")
    if any(f.level == "error" for f in result.findings):
        raise typer.Exit(1)


@datasheets_app.command("fill")
def fill(
    tag: Annotated[
        list[str] | None, typer.Option("--tag", help="Only this item (repeatable).")
    ] = None,
    param: Annotated[
        list[str] | None,
        typer.Option(
            "--param",
            help="NAME=VALUE: an assumption for every item without its own (repeatable), "
            "e.g. pump_efficiency=0.7; written ASSUMED. --list names them.",
        ),
    ] = None,
    case: Annotated[str | None, typer.Option("--case", help="Flowsheet case.")] = None,
    dimensions: Annotated[
        bool,
        typer.Option(
            "--dimensions",
            help="Only the main dimensions and the empty weight the equipment list and the "
            "layout model state, into final datasheets too (never over a value written by "
            "hand).",
        ),
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Print the filled drafts, write nothing.")
    ] = False,
    list_: Annotated[
        bool,
        typer.Option(
            "--list",
            help="List the parameters, the typical overall coefficients (u_service) and the "
            "pipe roughness rows, and exit.",
        ),
    ] = False,
) -> None:
    """Fill the TBD sizes of the draft datasheets (draft: true) with calculated values and
    their basis: exchanger duty, LMTD and area; pump head, NPSH available and power; compressor
    and expander stages and power; column shortcut stages; vessel volume and residence time.
    A value the datasheet gives is never overwritten; what cannot be calculated stays TBD with
    the reason. The main dimensions and the empty weight come from the equipment list and the
    layout model (--dimensions: only those, final datasheets included)."""
    from chemeascode.domains.equipment.fill import PARAMETERS, fill_datasheets

    if list_:
        from chemeascode.domains.equipment.sizing import typical_u, u_rows
        from chemeascode.domains.process.hydraulics import roughness, roughness_materials

        typer.echo("parameters (type_specific.<name> in a datasheet, or --param name=value):")
        for name, (unit, what) in sorted(PARAMETERS.items()):
            typer.echo(f"  {name}{f' [{unit}]' if unit else ''}: {what}")
        typer.echo("u_service rows (W/(m2 K), design typical = middle of the range, ASSUMED):")
        for row in u_rows():
            u = typical_u(row)
            assert u is not None
            typer.echo(f"  {row}: {u.low:g}-{u.high:g}")
        typer.echo("pipe_roughness rows (mm):")
        for material in roughness_materials():
            r = roughness(material)
            assert r is not None
            typer.echo(f"  {material}: {r.value * 1000:g}")
        return
    parameters: dict[str, str] = {}
    for entry in param or []:
        name, sep, value = entry.partition("=")
        if not sep or not name.strip():
            typer.echo(f"--param {entry!r}: give NAME=VALUE", err=True)
            raise typer.Exit(2)
        parameters[name.strip()] = value.strip()
    try:
        workspace = Workspace.find()
    except NotAPlantRepository as failure:
        typer.echo(f"{failure} Run `cheme init` to start one.", err=True)
        raise typer.Exit(2) from failure
    from chemeascode.foundation.workspace import check_requirement

    check_requirement(workspace.root)
    result = fill_datasheets(
        workspace.root,
        tag or None,
        write=not dry_run,
        parameters=parameters,
        case=case,
        dimensions=dimensions,
    )
    for finding in result.findings:
        typer.echo(finding.format(), err=True)
    if dry_run:
        for name, text in result.texts.items():
            typer.echo(f"--- {name}")
            typer.echo(text, nl=False)
    for name in [*result.written, *result.unchanged]:
        filled, tbd = result.filled.get(name, []), result.tbd.get(name, [])
        verb = "would fill" if dry_run and name in result.written else "filled"
        if name in result.unchanged:
            verb = "unchanged"
        typer.echo(
            f"{verb} {name}: {', '.join(filled) or 'nothing'}"
            + (f"; TBD {', '.join(tbd)}" if tbd else "")
        )
    for name in result.skipped:
        typer.echo(f"kept {name} (not a draft)")
    if any(f.level == "error" for f in result.findings):
        raise typer.Exit(1)


@datasheets_app.command("drawing")
def drawing(
    tag: Annotated[
        list[str] | None, typer.Option("--tag", help="Only this item (repeatable).")
    ] = None,
    write: Annotated[
        bool,
        typer.Option("--write", help="Write equipment/datasheets/<TAG>.svg where not current."),
    ] = False,
    check: Annotated[
        bool, typer.Option("--check", help="Exit 1 when a drawing is missing or not current.")
    ] = False,
    show: Annotated[
        bool, typer.Option("--print", help="Print the drawing (one --tag) and write nothing.")
    ] = False,
) -> None:
    """The outline drawing of each datasheet, equipment/datasheets/<TAG>.svg: an elevation and
    a nozzle orientation view with the stated main dimensions, the nozzle schedule, weights,
    materials and a title block, generated from the datasheet (never edited by hand). Without
    an option, lists each drawing's state (current, stale, missing)."""
    from chemeascode.foundation.workspace import check_requirement
    from chemeascode.project.datasheets import drawings

    if write and (check or show):
        typer.echo("give --write, --check or --print, not several", err=True)
        raise typer.Exit(2)
    try:
        workspace = Workspace.find()
    except NotAPlantRepository as failure:
        typer.echo(f"{failure} Run `cheme init` to start one.", err=True)
        raise typer.Exit(2) from failure
    check_requirement(workspace.root)
    result = drawings(workspace.root, tag or None, write=write)
    for finding in result.findings:
        typer.echo(finding.format(), err=True)
    if any(f.level == "error" for f in result.findings):
        raise typer.Exit(1)
    if show:
        if len(result.states) != 1:
            typer.echo("--print draws one item: give --tag TAG", err=True)
            raise typer.Exit(2)
        typer.echo(result.states[0].text, nl=False)
        return
    if write:
        for name in result.written:
            typer.echo(f"wrote {name}")
        current = len(result.states) - len(result.written)
        if current:
            typer.echo(f"{current} drawing(s) already current")
        return
    for state in result.states:
        typer.echo(f"{state.drawing}: {state.state}")
    if check:
        stale = [s for s in result.states if s.state != "current"]
        if stale:
            typer.echo(
                f"{len(stale)} drawing(s) not current; run cheme datasheets drawing --write",
                err=True,
            )
            raise typer.Exit(1)
