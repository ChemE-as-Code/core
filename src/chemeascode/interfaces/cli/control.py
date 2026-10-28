"""``cheme control``: the loop summary and the sequence report (domains/control/report.py)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

control_app = typer.Typer(
    help="Control: the loop register, operating sequences, narrative and control philosophy.",
    no_args_is_help=True,
)


@control_app.command("report")
def report(
    output: Annotated[
        Path | None, typer.Option("-o", help="Folder to write to (default: build/).")
    ] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print the report as JSON.")] = False,
) -> None:
    """Write the loop summary (control-loops.html, .csv) and the sequence report
    (control-sequences.html), with each file's review status and the control findings."""
    from chemeascode.domains.control.report import control_report, write_report
    from chemeascode.interfaces.cli.process import _workspace

    workspace = _workspace()
    result = control_report(workspace.root)
    if as_json:
        typer.echo(json.dumps(result.as_dict(), indent=2, default=str))
        return
    if not result.present:
        typer.echo(
            "no control records yet: control/loops.yaml and control/sequences.yaml list nothing, "
            "process/narrative.md and control/philosophy.md are absent or still the templates "
            "(skills control-loops, control-sequences, control-narrative)",
            err=True,
        )
        raise typer.Exit(2)
    for written in write_report(result, workspace, output):
        typer.echo(workspace.relative(written))
    for entry in result.files:
        typer.echo(f"{entry['path']}: {entry['status']} ({entry['detail']})")
    counts = {
        level: sum(f.level == level for f in result.findings)
        for level in ("error", "warning", "info")
    }
    typer.echo(
        ", ".join(f"{n} {level}" for level, n in counts.items()) + " (cheme validate lists them)"
    )
