"""``cheme layout``: build, route, pin, render and report the generated 3D plant model."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer

from chemeascode.foundation.workspace import NotAPlantRepository, Workspace

layout_app = typer.Typer(
    help="3D layout: the plant model generated from layout/*.yaml, the lists and the P&IDs.",
    no_args_is_help=True,
)


def _workspace() -> Workspace:
    from chemeascode.foundation.workspace import check_requirement

    try:
        workspace = Workspace.find()
    except NotAPlantRepository as failure:
        typer.echo(f"{failure} Run `cheme init` to start one.", err=True)
        raise typer.Exit(2) from failure
    check_requirement(workspace.root)
    return workspace


def _committed(workspace: Workspace) -> dict[str, Any]:
    from chemeascode.domains.spatial.model import read
    from chemeascode.foundation.workspace import LAYOUT_MODEL_FILE

    path = workspace.layout_model_file()
    document = read(path.read_text(encoding="utf-8")) if path is not None else None
    if document is None:
        typer.echo(f"no {LAYOUT_MODEL_FILE}: run cheme layout build first", err=True)
        raise typer.Exit(1)
    return document


def _build(check: bool, force: bool, only: set[str] | None = None) -> None:
    from chemeascode.domains.spatial.model import (
        BuildError,
        build_model,
        model_findings,
        read,
        write_model,
    )
    from chemeascode.foundation.workspace import LAYOUT_MODEL_FILE

    workspace = _workspace()
    previous = None
    if only is not None:
        path = workspace.layout_model_file()
        previous = read(path.read_text(encoding="utf-8")) if path is not None else None
    try:
        model = build_model(workspace, only=only, previous=previous)
    except BuildError as failure:
        for finding in failure.findings:
            typer.echo(finding.format(), err=True)
        typer.echo(str(failure), err=True)
        raise typer.Exit(1) from failure
    for finding in model.findings:
        typer.echo(finding.format())
    s = model.stats
    summary = (
        f"{s['items']} items, {s['parts']} parts, "
        f"{s['pid'] + s['default'] + s['override']} nozzles ({s['pid']} placed from the P&ID "
        f"side, {s['default']} by default, {s['override']} overridden), "
        f"{s['envelopes']} envelopes"
    )
    if "segments" in s:
        summary += (
            f", {s['routed']} of {s['segments']} segments routed ({s['unrouted']} unrouted, "
            f"{s['route_seconds']:g} s)"
        )
    summary += f", {s.get('platforms', 0)} platforms"
    if check:
        path = workspace.root / LAYOUT_MODEL_FILE
        current = path.is_file() and path.read_text(encoding="utf-8") == model.text()
        typer.echo(f"{LAYOUT_MODEL_FILE} {'is up to date' if current else 'is not up to date'}")
        if not current:
            raise typer.Exit(1)
        return
    edited = [f for f in model_findings(workspace) if f.rule == "cheme.layout-model-edited"]
    if edited and not force:
        for finding in edited:
            typer.echo(finding.format(), err=True)
        typer.echo(f"not overwriting {LAYOUT_MODEL_FILE}; rebuild with --force", err=True)
        raise typer.Exit(1)
    _, changed = write_model(workspace, model)
    typer.echo(f"{'wrote' if changed else 'unchanged'} {LAYOUT_MODEL_FILE}: {summary}")
    if any(f.level == "error" for f in model.findings):
        raise typer.Exit(1)


@layout_app.command("build")
def build(
    check: Annotated[
        bool,
        typer.Option("--check", help="Write nothing; exit 1 when the model is not up to date."),
    ] = False,
    force: Annotated[
        bool, typer.Option(help="Overwrite a model edited by hand since it was built.")
    ] = False,
) -> None:
    """Derive layout/plant-model.yaml: equipment parts from type and dimensions, nozzles from
    the P&IDs (point, direction, DN, lines), maintenance envelopes, steel structures, platforms,
    zones, the site geometry and a pipe route for every P&ID segment.

    Prints the build's findings and the model rules (clashes, headroom, access, rack fill).
    Refuses while a layout file is invalid, and over a model edited by hand unless --force. A
    rebuild from the same inputs is byte-identical.
    """
    _build(check, force)


@layout_app.command("route")
def route(
    line: Annotated[
        list[str] | None,
        typer.Option("--line", help="Route only this line (repeatable); keep the other routes."),
    ] = None,
    force: Annotated[
        bool, typer.Option(help="Overwrite a model edited by hand since it was built.")
    ] = False,
) -> None:
    """Rebuild the model, routing only the given lines (the other pipes are kept from the
    committed model); without --line, the same as layout build."""
    _build(False, force, set(line) if line else None)


@layout_app.command("pin")
def pin(
    target: Annotated[
        str,
        typer.Argument(
            help="A line number, pipe id, TAG/platform-N, a proposed stair or ladder "
            "(S/stair-to-L, S/ladder-to-L, RACK/ladder-start|end), a wall penetration "
            "(OWNER/LINE), proposed support steel (PIPE/SP-<arc>) or a valve access platform "
            "(VP-<valve tag>)."
        ),
    ],
) -> None:
    """Copy a generated route (into piping/routing.yaml), a proposed platform (into the item's
    access: in layout/equipment-placement.yaml), a proposed stair or ladder (into its
    structure in layout/structures.yaml, or its rack in layout/site-plan.yaml) or the opening a
    wall penetration proposes (into its building's or enclosure's openings; a roof
    penetration is refused: route the line through a wall), proposed support
    steel (into pipe_supports) or a valve access platform (into structures, with the routes of
    its valves' pipes), so the next build keeps it."""
    from chemeascode.domains.spatial.pins import PinError
    from chemeascode.domains.spatial.pins import pin as pin_object

    workspace = _workspace()
    try:
        done = pin_object(workspace.root, _committed(workspace), target)
    except PinError as failure:
        typer.echo(str(failure), err=True)
        raise typer.Exit(1) from failure
    typer.echo(f"pinned into {done.file}: {', '.join(done.what)}")
    typer.echo("run cheme layout build to take the pins into the model")


def _numbers(text: str, count: int, name: str) -> tuple[float, ...]:
    try:
        values = tuple(float(v) for v in text.split(","))
    except ValueError:
        values = ()
    if len(values) != count:
        typer.echo(f"{name}: give {count} numbers separated by commas", err=True)
        raise typer.Exit(2)
    return values


@layout_app.command("render")
def render(
    plan: Annotated[bool, typer.Option("--plan", help="A plan (plot plan by default).")] = False,
    level: Annotated[
        str | None, typer.Option(help="Level plan of a structure or building level id.")
    ] = None,
    z: Annotated[str | None, typer.Option("--z", help="Level plan of the z range A,B (m).")] = None,
    section: Annotated[
        str | None, typer.Option(help="A section at x=VALUE or y=VALUE (m).")
    ] = None,
    depth: Annotated[float, typer.Option(help="Section depth (m).")] = 6.0,
    crop: Annotated[
        str | None, typer.Option(help="X0,Y0,X1,Y1: site m (a section: along, z).")
    ] = None,
    png: Annotated[bool, typer.Option("--png", help="PNG (extra png) instead of SVG.")] = False,
) -> None:
    """Draw the committed model as build/layout-*.svg (or .png): the plot plan, a level plan
    or a section, with grid, tags, line numbers, north arrow, scale bar and title block."""
    from chemeascode.domains.spatial.drawing2d import (
        level_range,
        plant_meta,
        render_plan,
        render_section,
        svg_to_png,
    )

    workspace = _workspace()
    model = _committed(workspace)
    meta = plant_meta(workspace)
    box = _numbers(crop, 4, "--crop") if crop else None
    if section is not None:
        axis, _, value = section.partition("=")
        if axis not in ("x", "y") or not value:
            typer.echo("--section: give x=VALUE or y=VALUE", err=True)
            raise typer.Exit(2)
        at = _numbers(value, 1, "--section")[0]
        svg = render_section(model, axis, at, depth, meta, box)  # type: ignore[arg-type]
        name = f"layout-section-{axis}{at:g}"
    else:
        cut = None
        name = "layout-plan"
        if level is not None:
            cut = level_range(model, level)
            if cut is None:
                typer.echo(f"--level: no structure or building level {level}", err=True)
                raise typer.Exit(2)
            name = f"layout-level-{level.replace('/', '-')}"
        elif z is not None:
            cut = _numbers(z, 2, "--z")
            name = f"layout-plan-z{cut[0]:g}-{cut[1]:g}"
        svg = render_plan(model, meta, cut, box)  # type: ignore[arg-type]
    if box is not None:
        name += "_crop-" + "-".join(f"{v:g}" for v in box)
    out = workspace.root / "build" / f"{name}.{'png' if png else 'svg'}"
    out.parent.mkdir(parents=True, exist_ok=True)
    if png:
        from chemeascode.domains.piping.render import PngUnavailable

        try:
            out.write_bytes(svg_to_png(svg, 4.0))
        except PngUnavailable as failure:
            typer.echo(str(failure), err=True)
            raise typer.Exit(1) from failure
    else:
        out.write_text(svg, encoding="utf-8")
    typer.echo(f"wrote {Path('build') / out.name}")


@layout_app.command("report")
def report(
    as_json: Annotated[bool, typer.Option("--json", help="The report as JSON.")] = False,
) -> None:
    """Routed and unrouted lines with the reasons, lengths per line, rack fill, the model rule
    findings, and the generated / pinned / declared counts of the committed model."""
    import json

    from chemeascode.domains.spatial.model_rules import workspace_model_rules
    from chemeascode.domains.spatial.report import format_report, layout_report

    workspace = _workspace()
    model = _committed(workspace)
    findings = workspace_model_rules(workspace, model)
    lines = workspace.parsed_lists(("lines",)).get("lines")
    numbers = [line.number.strip() for line in lines.lines] if lines is not None else []
    data = layout_report(model, findings, numbers)
    if as_json:
        typer.echo(json.dumps(data, indent=2))
        return
    for row in format_report(data):
        typer.echo(row)


@layout_app.command("cables")
def cables(
    as_csv: Annotated[bool, typer.Option("--csv", help="The schedule as CSV.")] = False,
    as_json: Annotated[bool, typer.Option("--json", help="The schedule as JSON.")] = False,
    write: Annotated[
        bool, typer.Option("--write", help="Write electrical/cable-schedule.csv and .md.")
    ] = False,
    check: Annotated[
        bool, typer.Option("--check", help="Exit 1 when the written schedule is not current.")
    ] = False,
) -> None:
    """The cable schedule of the committed model: every cable from, to, size, trays, length
    (Markdown by default)."""
    import json

    from chemeascode.domains.spatial.trays import (
        SCHEDULE_FILES,
        cable_schedule,
        schedule_csv,
        schedule_markdown,
    )

    workspace = _workspace()
    model = _committed(workspace)
    if model.get("cables") is None:
        typer.echo(
            "the model has no cables: add electrical/electrical-list.yaml, then cheme layout build",
            err=True,
        )
        raise typer.Exit(1)
    rows = cable_schedule(model)
    texts = dict(zip(SCHEDULE_FILES, (schedule_csv(rows), schedule_markdown(model)), strict=True))
    if write or check:
        stale = []
        for name, text in texts.items():
            path = workspace.root / name
            current = path.read_text(encoding="utf-8") if path.is_file() else None
            if current == text:
                continue
            stale.append(name)
            if write:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
        if check:
            for name in stale:
                typer.echo(f"{name} is not current: run cheme layout cables --write")
            raise typer.Exit(1 if stale else 0)
        for name in SCHEDULE_FILES:
            typer.echo(f"{'wrote' if name in stale else 'unchanged'} {name}")
        return
    if as_json:
        typer.echo(json.dumps({"cables": rows, "cabling": model.get("cabling")}, indent=2))
    elif as_csv:
        typer.echo(texts[SCHEDULE_FILES[0]], nl=False)
    else:
        typer.echo(texts[SCHEDULE_FILES[1]], nl=False)


@layout_app.command("lifting")
def lifting(
    as_csv: Annotated[bool, typer.Option("--csv", help="The study as CSV.")] = False,
    as_json: Annotated[bool, typer.Option("--json", help="The study as JSON.")] = False,
    write: Annotated[
        bool, typer.Option("--write", help="Write layout/lifting-study.csv and .md.")
    ] = False,
    check: Annotated[
        bool, typer.Option("--check", help="Exit 1 when the written study is not current.")
    ] = False,
) -> None:
    """The lifting study of the committed model: per heavy item its crane or pad, radius, load
    moment, capacity needed, lift and hook height, lane and laydown; checked against
    layout/crane-chart.yaml when there is one (Markdown by default)."""
    from chemeascode.domains.spatial.lifting import (
        STUDY_CSV,
        STUDY_MD,
        lifting_study,
        study_csv,
        study_markdown,
    )

    workspace = _workspace()
    _committed(workspace)
    result = lifting_study(workspace.root)
    texts = {STUDY_CSV: study_csv(result), STUDY_MD: study_markdown(result)}
    for finding in result.findings:
        typer.echo(finding.format(), err=True)
    if write or check:
        stale = []
        for name, text in texts.items():
            path = workspace.root / name
            current = path.read_text(encoding="utf-8") if path.is_file() else None
            if current == text:
                continue
            stale.append(name)
            if write:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")
        if check:
            for name in stale:
                typer.echo(f"{name} is not current: run cheme layout lifting --write")
            raise typer.Exit(1 if stale else 0)
        for name in texts:
            typer.echo(f"{'wrote' if name in stale else 'unchanged'} {name}")
        return
    if as_json:
        typer.echo(result.to_json())
    elif as_csv:
        typer.echo(texts[STUDY_CSV], nl=False)
    else:
        typer.echo(texts[STUDY_MD], nl=False)
