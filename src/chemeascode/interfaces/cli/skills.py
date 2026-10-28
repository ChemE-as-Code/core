"""``cheme skills``: the bundled skills installed in ``.claude/skills/``, and safe updates."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Annotated

import typer

skills_app = typer.Typer(
    help="The bundled skills installed in .claude/skills/: status and safe updates.",
    no_args_is_help=True,
)


def _root():
    from chemeascode.interfaces.cli import _workspace

    return _workspace().root


@skills_app.command("status")
def status(
    names: Annotated[list[str] | None, typer.Argument(help="Skills (default: all).")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Machine-readable.")] = False,
) -> None:
    """Each bundled skill file as installed: current, outdated (an earlier bundled version),
    modified (changed locally) or missing."""
    from chemeascode.templates.install import skill_status

    found = skill_status(_root(), names or None)
    if as_json:
        typer.echo(json.dumps([asdict(f) for f in found], indent=2))
        return
    for item in found:
        if item.state != "current":
            typer.echo(f"{item.path}: {item.state}")
    counts = {s: sum(f.state == s for f in found) for s in ("current", "outdated", "modified")}
    missing = sum(f.state == "missing" for f in found)
    typer.echo(
        f"{len(found)} skill file(s): {counts['current']} current, {counts['outdated']} "
        f"outdated, {counts['modified']} modified, {missing} missing"
    )


@skills_app.command("update")
def update(
    names: Annotated[list[str] | None, typer.Argument(help="Skills (default: all).")] = None,
    force: Annotated[
        bool, typer.Option(help="Also replace files changed locally (they are still reported).")
    ] = False,
) -> None:
    """Install the bundled version of missing and outdated skill files. A file changed locally
    is kept and reported (exit 1) unless --force."""
    from chemeascode.templates.install import update_skills

    written, findings = update_skills(_root(), names or None, force=force)
    for item in written:
        typer.echo(f"{item.path}: {'installed' if item.state == 'missing' else 'updated'}")
    for finding in findings:
        typer.echo(finding.format())
    typer.echo(f"{len(written)} file(s) written")
    if findings and not force:
        raise typer.Exit(1)
