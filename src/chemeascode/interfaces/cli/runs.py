"""``cheme runs``: the record of each design session in ``runs/<run-id>/``
(project/run_records.py, ADR 0029)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated, Any

import typer

runs_app = typer.Typer(
    help="Run records: one folder per design session in runs/ (start, record, list).",
    no_args_is_help=True,
)


def _hook_input() -> dict[str, Any]:
    """The JSON object Claude Code writes to a hook's stdin."""
    data = json.loads(sys.stdin.read() or "{}")
    if not isinstance(data, dict):
        raise ValueError("the hook input is not a JSON object")
    return data


def _plant_root(start: Path | None = None) -> Path:
    from chemeascode.foundation.workspace import Workspace

    return Workspace.find(start).root


def _quiet(what: str, failure: BaseException) -> None:
    """A hook never fails the session: one line on stderr, exit 0."""
    message = (str(failure).splitlines() or [type(failure).__name__])[0]
    typer.echo(f"cheme runs {what}: {message}", err=True)


@runs_app.command("start")
def start(
    hook: Annotated[
        bool,
        typer.Option(
            "--hook", help="Claude Code SessionStart hook: read its JSON from stdin, never fail."
        ),
    ] = False,
    session_id: Annotated[
        str | None, typer.Option(help="The session id (without --hook; required then).")
    ] = None,
) -> None:
    """Remember the start of a session (HEAD, branch, time, working tree) in
    build/run-records/<session_id>.start.json, for `cheme runs record`."""
    from chemeascode.project.run_records import RunRecordError, hooks_off, start_session

    if not hook:
        if not session_id:
            typer.echo("give --session-id (or --hook in a Claude Code hook)", err=True)
            raise typer.Exit(2)
        from chemeascode.interfaces.cli.process import _workspace

        root = _workspace().root
        try:
            path, written = start_session(root, session_id)
        except RunRecordError as failure:
            typer.echo(str(failure), err=True)
            raise typer.Exit(2) from failure
        typer.echo(f"{path.relative_to(root)}{'' if written else ' (kept: exists)'}")
        return
    if hooks_off():
        return
    try:
        data = _hook_input()
        cwd = Path(data["cwd"]) if isinstance(data.get("cwd"), str) else None
        root = _plant_root(cwd)
        transcript = data.get("transcript_path")
        start_session(
            root,
            str(data.get("session_id") or ""),
            source=data.get("source") if isinstance(data.get("source"), str) else None,
            transcript=Path(transcript) if isinstance(transcript, str) else None,
        )
    except Exception as failure:  # noqa: BLE001 -- a hook never fails the session
        _quiet("start", failure)


@runs_app.command("record")
def record(
    hook: Annotated[
        bool,
        typer.Option(
            "--hook",
            help="Claude Code SessionEnd hook: JSON from stdin, kind interactive, no checks, no "
            "commit, skipped when nothing changed, never fails.",
        ),
    ] = False,
    session_id: Annotated[str | None, typer.Option(help="The Claude Code session id.")] = None,
    transcript: Annotated[
        Path | None, typer.Option(help="The session transcript (.jsonl) instead of --session-id.")
    ] = None,
    kind: Annotated[str, typer.Option(help="agent, interactive or manual.")] = "interactive",
    slug: Annotated[
        str | None, typer.Option(help="Appended to the run id (e.g. the stage id).")
    ] = None,
    task_file: Annotated[Path | None, typer.Option(help="The task, copied to task.md.")] = None,
    report_file: Annotated[
        Path | None, typer.Option(help="The session's report, copied to report.md.")
    ] = None,
    cost: Annotated[
        float | None, typer.Option(help="USD as reported by the API (never an estimate).")
    ] = None,
    budget: Annotated[float | None, typer.Option(help="The session's USD cap.")] = None,
    effort: Annotated[str | None, typer.Option(help="The reasoning effort it ran with.")] = None,
    result: Annotated[
        str | None, typer.Option(help="How it ended (Claude Code's result subtype: success, ...).")
    ] = None,
    start_commit: Annotated[
        str | None, typer.Option(help="HEAD at the start, when no start file was written.")
    ] = None,
    checks: Annotated[
        bool, typer.Option("--checks", help="Run cheme check and cheme maturity and record them.")
    ] = False,
    commit: Annotated[
        bool, typer.Option("--commit", help="Commit the run folder alone (git commit -- runs/ID).")
    ] = False,
    sdk_version: Annotated[
        str | None, typer.Option(help="Claude Agent SDK version, from a runner that uses it.")
    ] = None,
    runner_name: Annotated[
        str | None, typer.Option(help="The external runner that ran the session.")
    ] = None,
    runner_commit: Annotated[
        str | None, typer.Option(help="The runner's commit, when it knows one.")
    ] = None,
    runner_dirty: Annotated[
        bool | None,
        typer.Option(
            "--runner-dirty/--runner-clean", help="Whether the runner's checkout had changes."
        ),
    ] = None,
) -> None:
    """Write runs/<run-id>/ for one session: run.yaml (process-run/v1), task.md, report.md and
    session.jsonl.gz. Prints the run folder. A record that exists is never rewritten."""
    from chemeascode.interfaces.cli import app
    from chemeascode.project.run_records import (
        RunRecordError,
        commit_record,
        hooks_off,
        record_run,
    )

    if kind not in ("agent", "interactive", "manual"):
        typer.echo("--kind: agent, interactive or manual", err=True)
        raise typer.Exit(2)
    groups = {group.name for group in app.registered_groups if group.name}
    if hook:
        if hooks_off():
            return
        try:
            data = _hook_input()
            if not data.get("session_id"):
                raise ValueError("the hook input names no session_id")
            cwd = Path(data["cwd"]) if isinstance(data.get("cwd"), str) else None
            root = _plant_root(cwd)
            path = data.get("transcript_path")
            done = record_run(
                root,
                session_id=str(data["session_id"]),
                transcript=Path(path) if isinstance(path, str) else None,
                cwd=cwd,
                kind="interactive",
                hook=True,
                command_groups=groups,
            )
        except Exception as failure:  # noqa: BLE001 -- a hook never fails the session
            _quiet("record", failure)
            return
        if done.folder is not None:
            typer.echo(done.folder.relative_to(root).as_posix())
        return

    from chemeascode.interfaces.cli.process import _workspace

    if session_id and transcript:
        typer.echo("give --session-id or --transcript, not both", err=True)
        raise typer.Exit(2)
    given_runner = (runner_name, runner_commit, runner_dirty)
    runner = (
        None
        if all(v is None for v in given_runner)
        else dict(zip(("name", "commit", "dirty"), given_runner, strict=True))
    )
    root = _workspace().root
    for given in (task_file, report_file, transcript):
        if given is not None and not given.is_file():
            typer.echo(f"{given}: no such file", err=True)
            raise typer.Exit(2)
    try:
        done = record_run(
            root,
            session_id=session_id,
            transcript=transcript,
            cwd=Path.cwd(),
            kind=kind,
            slug=slug,
            task_file=task_file,
            report_file=report_file,
            cost=cost,
            budget=budget,
            effort=effort,
            start_commit=start_commit,
            result=result,
            checks=checks,
            command_groups=groups,
            sdk_version=sdk_version,
            runner=runner,
        )
    except RunRecordError as failure:
        typer.echo(str(failure), err=True)
        raise typer.Exit(1) from failure
    assert done.folder is not None and done.record is not None
    typer.echo(done.folder.relative_to(root).as_posix())
    for note in done.notes:
        typer.echo(f"incomplete: {note}", err=True)
    if commit:
        try:
            sha = commit_record(root, done.folder, done.record)
        except RunRecordError as failure:
            typer.echo(str(failure), err=True)
            raise typer.Exit(1) from failure
        typer.echo(f"committed {sha[:12]}: {done.record.process}: run record {done.record.run_id}")


def _wall(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes // 60}h{minutes % 60:02d}m" if minutes >= 60 else f"{minutes}m{secs:02d}s"


@runs_app.command("list")
def list_command(
    as_json: Annotated[bool, typer.Option("--json", help="Machine-readable.")] = False,
) -> None:
    """One line per run record in runs/: run id, kind, cost, wall time, complete, turns.
    Read-only."""
    from chemeascode.interfaces.cli.process import _workspace
    from chemeascode.project.run_records import list_runs

    listing = list_runs(_workspace().root)
    for finding in listing.findings:
        typer.echo(finding.format(), err=True)
    if as_json:
        rows = [
            {
                "run_id": r.run_id,
                "kind": r.kind,
                "cost_usd": r.cost_usd,
                "wall_s": r.wall_s,
                "complete": r.complete,
                "num_turns": r.num_turns,
            }
            for r in listing.records
        ]
        typer.echo(json.dumps(rows, indent=2))
    else:
        for r in listing.records:
            cost = f"USD {r.cost_usd:.2f}" if r.cost_usd is not None else "USD -"
            turns = f"{r.num_turns} turns" if r.num_turns is not None else "- turns"
            state = "complete" if r.complete else "incomplete"
            typer.echo(
                f"{r.run_id}  {r.kind:<11} {cost:<10} {_wall(r.wall_s):<7} {state:<10} {turns}"
            )
        if not listing.records:
            typer.echo("no run records in runs/")
    if any(f.level == "error" for f in listing.findings):
        raise typer.Exit(1)
