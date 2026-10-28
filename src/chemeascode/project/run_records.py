"""Run records: one folder per design session in ``runs/<run-id>/`` (schema ``process-run/v1``).

:func:`start_session` remembers the start of a session (HEAD, branch, time, the state of the
working tree) in ``build/run-records/<session id>.start.json``; :func:`record_run` composes the
record from it, the session transcript (``integrations.claude_code``) and what the caller knows
(cost, budget, task), and writes ``run.yaml``, ``task.md``, ``report.md`` and
``session.jsonl.gz``. A record is never rewritten: a folder that exists is refused. A value
nobody knows stays null; ``complete`` is false and ``incomplete_notes`` says why (ADR 0029).
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import subprocess
from collections import Counter
from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from chemeascode.foundation import gitinfo
from chemeascode.foundation.findings import Finding
from chemeascode.foundation.schemas.run_record import RUN_SCHEMA, RunRecord
from chemeascode.foundation.workspace import Workspace
from chemeascode.integrations.claude_code import Transcript, find_transcript, read_transcript

#: The record folders, from the repository root.
RUNS_DIR = "runs"
#: Start files and session exports kept out of the repository (``build/`` is ignored).
STATE_DIR = "build/run-records"
EXPORT_FILE = "session.jsonl.gz"
#: ``CHEME_RUN_RECORD=off``: the hooks record nothing (a runner that records itself sets it).
SWITCH = "CHEME_RUN_RECORD"
_KEY_PREFIX = b"sk-ant-"


class RunRecordError(ValueError):
    """A record that may not be written (it exists, the session cannot be named, git refused)."""


def hooks_off() -> bool:
    return os.environ.get(SWITCH, "").strip().lower() == "off"


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _safe_id(session_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", session_id or ""):
        raise RunRecordError(f"{session_id!r} is not a session id")
    return session_id


def start_file(root: Path, session_id: str) -> Path:
    return root / STATE_DIR / f"{_safe_id(session_id)}.start.json"


def tree_state(root: Path) -> str | None:
    """A digest of the working tree against HEAD: ``git status --porcelain``, the diff of the
    tracked files and the content of the untracked ones. None when git cannot tell."""

    def output(*args: str) -> bytes | None:  # bytes: a diff need not be UTF-8
        try:
            done = subprocess.run(
                ["git", *args],
                cwd=root,
                check=False,
                capture_output=True,
                stdin=subprocess.DEVNULL,
            )
        except OSError:
            return None
        return done.stdout if done.returncode == 0 else None

    status = output("status", "--porcelain", "-z", "--untracked-files=all")
    others = output("ls-files", "--others", "--exclude-standard", "-z")
    if status is None or others is None:
        return None
    digest = hashlib.sha256(status)
    digest.update(output("diff", "--binary", "HEAD") or b"(no HEAD)")
    for name in sorted(n for n in others.split(b"\0") if n):
        path = root / os.fsdecode(name)
        digest.update(name + b"\0")
        if path.is_file():
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def start_session(
    root: Path,
    session_id: str,
    *,
    source: str | None = None,
    transcript: Path | None = None,
    now: datetime | None = None,
) -> tuple[Path, bool]:
    """Write the start file of *session_id*; ``(path, False)`` when it exists already (a
    compacted or resumed session keeps the start it had)."""
    path = start_file(root, session_id)
    if path.is_file():
        return path, False
    data = {
        "session_id": session_id,
        "start_commit": gitinfo.head(root),
        "branch": gitinfo.branch(root),
        "started": (now or _now()).isoformat(),
        "tree_state": tree_state(root),
        "source": source,
        "transcript_path": str(transcript) if transcript else None,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path, True


def read_start(root: Path, session_id: str) -> dict[str, Any] | None:
    try:
        data = json.loads(start_file(root, session_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def slugify(text: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def run_id(started: datetime, slug: str | None = None) -> str:
    stamp = started.astimezone(UTC).strftime("%Y%m%d-%H%M%S")
    return f"{stamp}-{slugify(slug)}" if slugify(slug) else stamp


def command_names(commands: list[str], groups: Collection[str] = ()) -> list[str]:
    """The distinct ``cheme`` commands of *commands*, without their arguments and options:
    ``cheme check``, ``cheme process build`` (a second word only after a group in *groups*)."""
    names: list[str] = []
    for command in commands:
        words = command.split()[1:]
        name = ["cheme"]
        if words and re.fullmatch(r"[a-z][a-z0-9-]*", words[0]):
            name.append(words[0])
            if words[0] in groups and len(words) > 1 and re.fullmatch(r"[a-z][a-z0-9-]*", words[1]):
                name.append(words[1])
        text = " ".join(name)
        if text not in names:
            names.append(text)
    return names


def holds_secret(data: bytes) -> bool:
    """Whether *data* holds an Anthropic API key: ``sk-ant-`` or the value of
    ``ANTHROPIC_API_KEY``. Compared in memory; the key is never printed."""
    if _KEY_PREFIX in data:
        return True
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    return len(key) >= 8 and key.encode() in data


def _parse_time(value: Any) -> datetime | None:
    try:
        stamp = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else None


def _iso(stamp: datetime | None) -> str | None:
    return stamp.astimezone(UTC).isoformat(timespec="seconds") if stamp else None


def _package_dir() -> Path:
    """The folder chemeascode is imported from (``src/chemeascode`` of an editable install)."""
    return Path(__file__).resolve().parents[1]


def source_checkout(folder: Path) -> tuple[str | None, bool | None]:
    """``(HEAD, uncommitted changes)`` of the git work tree that tracks *folder*'s
    ``__init__.py``; ``(None, None)`` when none does (a wheel in a virtual environment, even one
    inside a repository, is not tracked)."""
    if gitinfo.git(folder, "ls-files", "--error-unmatch", "--", "__init__.py").returncode != 0:
        return None, None
    commit = gitinfo.head(folder)
    status = gitinfo.git(folder, "status", "--porcelain")
    return commit, (bool(status.stdout.strip()) if status.returncode == 0 else None)


def _version(name: str) -> str | None:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version(name)
    except PackageNotFoundError:
        return None


def claude_code_version() -> str | None:
    """``claude --version`` (``2.1.3 (Claude Code)``): its first word, or None."""
    import shutil

    found = shutil.which("claude")
    if found is None:
        return None
    try:
        done = subprocess.run(
            [found, "--version"],
            check=False,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    words = done.stdout.split() if done.returncode == 0 else []
    return words[0] if words and re.fullmatch(r"\d+(\.\d+)+\S*", words[0]) else None


def _tools(
    session: Transcript | None = None,
    sdk_version: str | None = None,
    runner: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The software versions of a run. cheme-as-code's commit: ``direct_url.json`` of a git
    install first, else the HEAD of the checkout it is imported from (editable or local)."""
    from importlib.metadata import PackageNotFoundError, distribution

    commit, dirty = None, None
    try:
        dist = distribution("cheme-as-code")
    except PackageNotFoundError:
        dist = None
    if dist is not None:
        try:
            direct = json.loads(dist.read_text("direct_url.json") or "{}")
            commit = (direct.get("vcs_info") or {}).get("commit_id")
        except (ValueError, AttributeError):
            pass
        dirty = False if commit else None  # a git install is built from the commit as it is
    if commit is None:
        commit, dirty = source_checkout(_package_dir())
    return {
        "cheme": dist.version if dist is not None else None,
        "core_commit": commit,
        "core_dirty": dirty,
        "pydexpi": _version("pydexpi"),
        "claude_code": (session.claude_code if session else None) or claude_code_version(),
        "claude_agent_sdk": sdk_version,
        "runner": runner,
        "same_revision": same_revision(commit, dirty, runner),
    }


def same_revision(
    commit: str | None, dirty: bool | None, runner: dict[str, Any] | None
) -> bool | None:
    """Whether cheme-as-code and the runner ran from one clean commit. Each revision comes from
    its own source; they count as one only when both are known, identical and clean."""
    other = (runner or {}).get("commit")
    if commit is None or other is None:
        return None
    return commit == other and dirty is False and (runner or {}).get("dirty") is False


def checks_after_run(root: Path) -> list[dict[str, Any]]:
    """``cheme check`` and ``cheme maturity`` on the repository as it is, each with the exit
    the command would give and a short summary (counts, failing gates, levels)."""
    from chemeascode.project.checks import run_checks
    from chemeascode.project.maturity import maturity_report

    out: list[dict[str, Any]] = []
    try:
        results = run_checks(Workspace(root))
    except Exception as failure:  # noqa: BLE001 -- a broken checks.yaml is recorded, not raised
        out.append({"command": "cheme check", "exit": 2, "summary": {"error": str(failure)}})
    else:
        counts = Counter(r.status for r in results)
        failing = [r.id for r in results if r.status == "fail"]
        out.append(
            {
                "command": "cheme check",
                "exit": 1 if failing else 0,
                "summary": {
                    "ok": counts["pass"],
                    "FAIL": counts["fail"],
                    "n/a": counts["n/a"],
                    "failing": failing,
                },
            }
        )
    try:
        report = maturity_report(root)
    except Exception as failure:  # noqa: BLE001
        out.append({"command": "cheme maturity", "exit": 2, "summary": {"error": str(failure)}})
    else:
        out.append(
            {
                "command": "cheme maturity",
                "exit": 0,
                "summary": {
                    "level": report.level,
                    "levels": {lv["id"]: lv["status"] for lv in report.levels},
                },
            }
        )
    return out


@dataclass
class RecordResult:
    """What :func:`record_run` did: the folder written, or why nothing was."""

    folder: Path | None = None
    record: RunRecord | None = None
    skipped: str | None = None
    #: Where the session export went when it could not go into the run folder.
    outside_export: Path | None = None
    notes: list[str] = field(default_factory=list)


def _relative(root: Path, path: Path) -> str:
    """*path* from the root, or its name when it lies outside the repository."""
    name = Workspace(root).relative(path)
    return path.name if Path(name).is_absolute() else name


def record_run(
    root: Path,
    *,
    session_id: str | None = None,
    transcript: Path | None = None,
    cwd: Path | None = None,
    kind: str = "interactive",
    slug: str | None = None,
    task_file: Path | None = None,
    report_file: Path | None = None,
    cost: float | None = None,
    budget: float | None = None,
    effort: str | None = None,
    start_commit: str | None = None,
    result: str | None = None,
    checks: bool = False,
    hook: bool = False,
    command_groups: Collection[str] = (),
    sdk_version: str | None = None,
    runner: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> RecordResult:
    """Write ``runs/<run-id>/`` for one session of the plant repository at *root*.

    The start (commit, branch, time) comes from the session's start file, or *start_commit*;
    the rest from the transcript (*transcript*, else found by *session_id* for *cwd* or
    *root*). *hook*: the SessionEnd hook of an interactive session -- skipped when HEAD and the
    working tree are as they were at the start. Raises :class:`RunRecordError` when the folder
    exists or the session id is not one. *sdk_version* and *runner* (``name``, ``commit``,
    ``dirty``) are what an external runner says about itself; null, they leave the record
    complete.
    """
    notes: list[str] = []
    if session_id is not None:
        _safe_id(session_id)
    path = transcript
    if path is None and session_id:
        path = find_transcript(cwd or root, session_id) or find_transcript(root, session_id)
    if session_id is None and path is not None:
        session_id = path.stem
    start = read_start(root, session_id) if session_id else None
    if start and start_commit is None:
        start_commit = start.get("start_commit")
    end_commit = gitinfo.head(root)

    unchanged = start is not None and end_commit == start.get("start_commit")
    if hook and unchanged and tree_state(root) == start.get("tree_state"):
        start_file(root, session_id or "").unlink(missing_ok=True)
        return RecordResult(skipped="nothing changed in the session")

    since = _parse_time(start.get("started")) if start else None
    session: Transcript | None = None
    if path is not None and path.is_file():
        session = read_transcript(path, since=since)
        if session.skipped:
            notes.append(f"{session.skipped} unreadable transcript line(s) skipped")
    elif path is not None:
        notes.append(f"no session transcript at {path}")
    elif session_id:
        notes.append(f"no session transcript found for session {session_id}")
    else:
        notes.append("no session id or transcript given: nothing read from the session")
    if session is not None and session_id is None:
        session_id = session.session_id

    started = since or (session.started if session else None)
    finished = session.finished if session else None
    if started is None:
        notes.append("start time unknown: the run id is the time of recording")
    if session is not None and finished is None:
        notes.append("finish time unknown: the transcript has no timestamps")
    if start_commit is None:
        notes.append(
            "start commit unknown: no start file (SessionStart hook) and no --start-commit"
        )
    if end_commit is None:
        notes.append("end commit unknown: no commit in the repository")
    if session_id is None:
        notes.append("session id unknown")
    if session is not None and not session.num_turns:
        notes.append("the transcript holds no assistant message: model, turns, tokens unknown")

    rid = run_id(started or now or _now(), slug)
    folder = root / RUNS_DIR / rid
    if folder.exists():
        raise RunRecordError(f"{RUNS_DIR}/{rid} exists: a run record is never rewritten")

    task_text, task_name = None, None
    if task_file is not None:
        task_text = task_file.read_text(encoding="utf-8")
        task_name = _relative(root, task_file)
    elif session is not None and session.first_user_text:
        task_text = session.first_user_text + "\n"
    if task_text is not None and holds_secret(task_text.encode()):
        task_text = None
        notes.append("task.md withheld: the task holds what looks like an API key")
    elif task_text is None:
        notes.append("task unknown: no --task-file and no user message in the transcript")
    report_text = report_file.read_text(encoding="utf-8") if report_file else None
    if report_text is not None and holds_secret(report_text.encode()):
        report_text = None
        notes.append("report.md withheld: the report holds what looks like an API key")

    export, export_bytes, outside = None, None, None
    if session is not None and session.raw:
        if holds_secret(session.raw):
            notes.append("session export refused: the transcript holds what looks like an API key")
        else:
            export_bytes = gzip.compress(session.raw, mtime=0)
            if session.web:
                outside = root / STATE_DIR / f"{rid}.session.jsonl.gz"
                used = ", ".join(sorted(set(session.web)))
                notes.append(
                    f"session export kept out of the repository ({STATE_DIR}/{outside.name}): "
                    f"the session used web tools ({used}) and may hold third-party text"
                )
            else:
                export = {
                    "file": EXPORT_FILE,
                    "sha256": hashlib.sha256(export_bytes).hexdigest(),
                }
    elif session is not None:
        notes.append("the transcript is empty: no session export")

    record = RunRecord.model_validate(
        {
            "schema": RUN_SCHEMA,
            "run_id": rid,
            "process": root.resolve().name,
            "kind": kind,
            "complete": not notes,
            "incomplete_notes": notes,
            "task_file": task_name,
            "branch": (start or {}).get("branch") or gitinfo.branch(root),
            "start_commit": start_commit,
            "end_commit": end_commit,
            "started": _iso(started),
            "finished": _iso(finished),
            "wall_s": round((finished - started).total_seconds()) if started and finished else None,
            "cost_usd": cost,
            "cost_source": "api" if cost is not None else None,
            "budget_usd": budget,
            "model": session.model if session else None,
            "effort": effort,
            "num_turns": session.num_turns if session and session.num_turns else None,
            "tokens": session.tokens if session and session.tokens else None,
            "session_id": session_id,
            "session_export": export,
            "tools": _tools(session, sdk_version, runner),
            "checks_by_agent": command_names(session.cheme_commands, command_groups)
            if session
            else [],
            "checks_after_run": checks_after_run(root) if checks else [],
            "outcome": {"result": result, "report": "report.md" if report_text else None},
            "observed_later": {},
        }
    )
    folder.mkdir(parents=True)
    data = record.model_dump(by_alias=True, mode="json")
    (folder / "run.yaml").write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100), encoding="utf-8"
    )
    if task_text is not None:
        (folder / "task.md").write_text(task_text, encoding="utf-8")
    if report_text is not None:
        (folder / "report.md").write_text(report_text, encoding="utf-8")
    if export_bytes is not None:
        target = outside or folder / EXPORT_FILE
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(export_bytes)
    if session_id:
        start_file(root, session_id).unlink(missing_ok=True)
    return RecordResult(folder, record, outside_export=outside, notes=notes)


def commit_record(root: Path, folder: Path, record: RunRecord) -> str:
    """Commit the run folder alone (other staged changes stay staged); the new commit's sha.
    The pre-commit hook runs as for any commit; when it refuses, the folder stays uncommitted."""
    name = Workspace(root).relative(folder)
    added = gitinfo.git(root, "add", "--", name)
    if added.returncode != 0:
        raise RunRecordError(f"git add {name} failed: {added.stderr.strip()}")
    message = f"{record.process}: run record {record.run_id}"
    done = gitinfo.git(root, "commit", "-q", "-m", message, "--", name)
    if done.returncode != 0:
        tail = (done.stderr or done.stdout).strip().splitlines()[-1:] or [""]
        raise RunRecordError(f"git commit of {name} failed: {tail[0]}")
    return gitinfo.head(root) or ""


@dataclass
class RunList:
    records: list[RunRecord]
    findings: list[Finding]


def list_runs(root: Path) -> RunList:
    """The records under ``runs/``, oldest first, and a finding for each folder that holds no
    readable record. Read-only."""
    from chemeascode.foundation.yamlsource import _compose, _yaml_line

    records: list[RunRecord] = []
    findings: list[Finding] = []
    base = root / RUNS_DIR
    for folder in sorted(p for p in base.iterdir() if p.is_dir()) if base.is_dir() else []:
        name = f"{RUNS_DIR}/{folder.name}/run.yaml"
        path = folder / "run.yaml"
        if not path.is_file():
            findings.append(
                Finding(
                    name,
                    "warning",
                    "cheme.run-record-missing",
                    "a run folder without run.yaml",
                    hint="write records with `cheme runs record`; remove the stray folder",
                )
            )
            continue
        try:
            records.append(RunRecord.model_validate(yaml.safe_load(path.read_text("utf-8"))))
        except (yaml.YAMLError, UnicodeDecodeError) as failure:
            message = (str(failure).splitlines() or ["unreadable"])[0]
            findings.append(Finding(name, "error", "yaml.syntax", message))
        except ValidationError as failure:
            document = _compose(path)
            findings.extend(
                Finding(
                    name,
                    "error",
                    "cheme.run-record-invalid",
                    f"{'.'.join(str(p) for p in error['loc'])}: {error['msg']}",
                    line=_yaml_line(document, error["loc"]),
                    hint="see `cheme schema process-run`; a record is written by `cheme runs "
                    "record`, never edited",
                )
                for error in failure.errors()
            )
    return RunList(records, findings)
