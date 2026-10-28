"""Run records (``cheme runs``, ``project/run_records.py``): one folder per session in runs/."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
from importlib.metadata import version
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from chemeascode.foundation.schemas.run_record import RunRecord
from chemeascode.integrations.claude_code import find_transcript, project_dir, read_transcript
from chemeascode.interfaces.cli import app
from chemeascode.project import run_records
from chemeascode.project.run_records import (
    STATE_DIR,
    claude_code_version,
    command_names,
    record_run,
    same_revision,
    source_checkout,
    start_file,
)
from tests.conftest import git

runner = CliRunner()
SESSION = "0b6f7c1e-1111-4222-8333-444455556666"


def _assistant(mid: str, ts: str, usage: dict, content=(), model="claude-opus-5-5") -> dict:
    return {
        "type": "assistant",
        "sessionId": SESSION,
        "version": "2.1.3",
        "timestamp": ts,
        "message": {
            "id": mid,
            "model": model,
            "role": "assistant",
            "content": list(content),
            "usage": usage,
        },
    }


def _user(text, ts: str) -> dict:
    return {
        "type": "user",
        "sessionId": SESSION,
        "version": "2.1.2",
        "timestamp": ts,
        "message": {"role": "user", "content": text},
    }


def _bash(command: str) -> dict:
    return {"type": "tool_use", "id": "t", "name": "Bash", "input": {"command": command}}


def _write(path: Path, entries: list, extra: list[str] = ()) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(e) for e in entries] + list(extra)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _session(tools=()) -> list[dict]:
    return [
        {"type": "summary", "summary": "no timestamp here"},
        _user("<command-name>/clear</command-name>", "2026-10-27T20:22:40.000Z"),
        _user(
            [{"type": "text", "text": "Draw the PFD of the methanol loop."}],
            "2026-10-27T20:22:41.500Z",
        ),
        # one API message over two lines: the last line's usage counts, once
        _assistant(
            "msg_1",
            "2026-10-27T20:22:50.000Z",
            {"input_tokens": 3, "output_tokens": 10, "cache_read_input_tokens": 100},
            [{"type": "thinking", "thinking": "..."}],
        ),
        _assistant(
            "msg_1",
            "2026-10-27T20:22:52.000Z",
            {
                "input_tokens": 3,
                "output_tokens": 40,
                "cache_read_input_tokens": 100,
                "cache_creation_input_tokens": 7,
                "output_tokens_details": {"thinking_tokens": 12},
            },
            [_bash("cd process && cheme check --stage concept; cheme process build PFD")],
        ),
        _user(
            [{"type": "tool_result", "tool_use_id": "t", "content": "ok"}], "2026-10-27T20:23:00Z"
        ),
        _assistant(
            "msg_2",
            "2026-10-27T20:38:02.000Z",
            {"input_tokens": 2, "output_tokens": 5, "cache_read_input_tokens": 200},
            [_bash("cheme check"), _bash("cheme validate pid/P-01.xml"), *tools],
            model="claude-sonnet-5-5",
        ),
        _assistant("msg_3", "2026-10-27T20:38:02.000Z", {"output_tokens": 0}, model="<synthetic>"),
    ]


def test_transcript_counts_each_message_once(tmp_path: Path):
    path = _write(tmp_path / "s.jsonl", _session(), ["not json {", "[1, 2]"])
    t = read_transcript(path)
    assert t.session_id == SESSION
    assert t.num_turns == 2
    assert t.tokens == {
        "input": 5,
        "output": 45,
        "thinking": 12,
        "cache_read": 300,
        "cache_write": 7,
    }
    assert t.skipped == 2
    assert t.model == "claude-opus-5-5"  # two lines of msg_1 against one of msg_2
    assert t.claude_code == "2.1.3"  # the last line's: a resumed session may have upgraded
    assert t.started.isoformat() == "2026-10-27T20:22:40+00:00"
    assert t.finished.isoformat() == "2026-10-27T20:38:02+00:00"
    assert t.first_user_text == "Draw the PFD of the methanol loop."
    assert t.cheme_commands == [
        "cheme check --stage concept",
        "cheme process build PFD",
        "cheme check",
        "cheme validate pid/P-01.xml",
    ]
    assert command_names(t.cheme_commands, {"process"}) == [
        "cheme check",
        "cheme process build",
        "cheme validate",
    ]
    assert t.web == []


def test_transcript_since_leaves_out_what_came_before(tmp_path: Path):
    from datetime import datetime

    path = _write(tmp_path / "s.jsonl", _session())
    t = read_transcript(path, since=datetime.fromisoformat("2026-10-27T20:30:00+00:00"))
    assert t.num_turns == 1 and t.tokens["output"] == 5 and t.first_user_text is None
    assert b"msg_1" not in t.raw and b"no timestamp here" in t.raw


def test_project_dir_replaces_every_non_alphanumeric(tmp_path: Path):
    folder = project_dir(Path("/Users/a.b/my plant_1"), tmp_path)
    assert folder == tmp_path / "projects" / "-Users-a-b-my-plant-1"
    _write(folder / f"{SESSION}.jsonl", _session())
    assert find_transcript(Path("/Users/a.b/my plant_1"), SESSION, tmp_path) is not None
    assert find_transcript(Path("/Users/a.b/my plant_1"), "../x", tmp_path) is None


@pytest.fixture
def committed(plant: Path) -> Path:
    git(plant, "add", "-A")
    git(plant, "commit", "-qm", "plant")
    return plant


def test_clean_session_is_exported_into_the_run_folder(committed: Path, tmp_path: Path):
    path = _write(tmp_path / f"{SESSION}.jsonl", _session())
    done = record_run(committed, transcript=path, kind="agent", slug="Concept to PFD", cost=5.0828)
    folder = done.folder
    assert folder.name == "20261027-202240-concept-to-pfd"
    data = yaml.safe_load((folder / "run.yaml").read_text())
    record = RunRecord.model_validate(data)
    assert record.session_export.file == "session.jsonl.gz"
    gz = (folder / "session.jsonl.gz").read_bytes()
    assert hashlib.sha256(gz).hexdigest() == record.session_export.sha256
    assert gzip.decompress(gz) == path.read_bytes()
    assert gz[4:8] == b"\0\0\0\0"  # mtime 0: the same transcript gives the same bytes
    assert record.cost_usd == 5.0828 and record.cost_source == "api"
    assert record.process == committed.name and record.kind == "agent"
    assert record.end_commit == git(committed, "rev-parse", "HEAD").strip()
    assert record.wall_s == 922 and record.num_turns == 2
    assert record.checks_by_agent[0] == "cheme check"
    assert (folder / "task.md").read_text() == "Draw the PFD of the methanol loop.\n"
    # no start file and no --start-commit: the start commit is not guessed
    assert record.start_commit is None and not record.complete
    assert any("start commit unknown" in n for n in record.incomplete_notes)
    assert list(data)[:3] == ["schema", "run_id", "process"]
    assert data["schema"] == "process-run/v1"


def test_a_record_is_never_rewritten(committed: Path, tmp_path: Path):
    from chemeascode.project.run_records import RunRecordError

    path = _write(tmp_path / f"{SESSION}.jsonl", _session())
    record_run(committed, transcript=path)
    with pytest.raises(RunRecordError, match="never rewritten"):
        record_run(committed, transcript=path)


@pytest.mark.parametrize(
    "tool",
    [
        {"type": "tool_use", "name": "WebFetch", "input": {"url": "https://example.org"}},
        {"type": "tool_use", "name": "WebSearch", "input": {"query": "methanol"}},
        _bash("curl -s https://example.org/data.csv"),
    ],
)
def test_web_use_keeps_the_export_out_of_the_repository(committed: Path, tmp_path: Path, tool):
    path = _write(tmp_path / f"{SESSION}.jsonl", _session([tool]))
    done = record_run(committed, transcript=path)
    assert not (done.folder / "session.jsonl.gz").exists()
    assert done.record.session_export is None and not done.record.complete
    outside = committed / STATE_DIR / f"{done.record.run_id}.session.jsonl.gz"
    assert done.outside_export == outside and outside.is_file()
    assert any("web tools" in note for note in done.record.incomplete_notes)
    assert "build/" in (committed / ".gitignore").read_text()


@pytest.mark.parametrize("secret", ["sk-ant-x", "the-users-own-key-1234"])
def test_a_transcript_with_a_key_is_not_exported(committed, tmp_path, monkeypatch, secret):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "the-users-own-key-1234")
    entries = _session()
    entries.append(_user(f"my key is {secret}", "2026-10-27T20:38:03Z"))
    path = _write(tmp_path / f"{SESSION}.jsonl", entries)
    done = record_run(committed, transcript=path)
    assert done.record.session_export is None and not done.record.complete
    assert not list((committed / "runs").rglob("*.gz"))
    assert not (committed / STATE_DIR).exists() or not list((committed / STATE_DIR).glob("*.gz"))
    text = (done.folder / "run.yaml").read_text()
    assert secret not in text and "API key" in text


def _records(plant: Path) -> list[Path]:
    """The run folders (the template's runs/README.md is not one)."""
    return [p for p in (plant / "runs").iterdir() if p.is_dir()]


def _hook(event: str, plant: Path, transcript: Path | None = None, **extra) -> str:
    data = {"session_id": SESSION, "cwd": str(plant), "hook_event_name": event, **extra}
    if transcript is not None:
        data["transcript_path"] = str(transcript)
    return json.dumps(data)


@pytest.fixture
def claude_home(tmp_path: Path, monkeypatch) -> Path:
    home = tmp_path / "claude-home"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
    monkeypatch.delenv("CHEME_RUN_RECORD", raising=False)
    return home


def test_hooks_record_an_interactive_session(committed: Path, claude_home: Path):
    start = runner.invoke(
        app, ["runs", "start", "--hook"], input=_hook("SessionStart", committed, source="startup")
    )
    assert start.exit_code == 0, start.output
    state = start_file(committed, SESSION)
    assert (
        json.loads(state.read_text())["start_commit"] == git(committed, "rev-parse", "HEAD").strip()
    )
    first = git(committed, "rev-parse", "HEAD").strip()
    # the session changes a file and commits
    (committed / "DESIGN.md").write_text("# Design\n\nD-001: methanol loop.\n")
    git(committed, "commit", "-qam", "design")
    # transcript found by session id under CLAUDE_CONFIG_DIR, not ~/.claude
    entries = [_user("Write D-001.", "2099-01-01T10:00:00Z")] + [
        e for e in _session() if e.get("type") == "assistant"
    ]
    for e in entries[1:]:
        e["timestamp"] = "2099-01-01T10:05:00Z"
    _write(project_dir(committed, claude_home) / f"{SESSION}.jsonl", entries)
    end = runner.invoke(app, ["runs", "record", "--hook"], input=_hook("SessionEnd", committed))
    assert end.exit_code == 0, end.output
    folders = _records(committed)
    assert len(folders) == 1 and end.output.strip() == f"runs/{folders[0].name}"
    record = RunRecord.model_validate(yaml.safe_load((folders[0] / "run.yaml").read_text()))
    assert record.kind == "interactive" and record.start_commit == first
    assert record.end_commit == git(committed, "rev-parse", "HEAD").strip()
    assert record.branch == "main" and record.checks_after_run == []
    assert record.complete, record.incomplete_notes
    assert (folders[0] / "task.md").read_text() == "Write D-001.\n"
    assert not state.exists()  # consumed
    assert git(committed, "status", "--porcelain").startswith("?? runs/")  # never committed


def test_hook_skips_a_session_that_changed_nothing(committed: Path, claude_home: Path, tmp_path):
    (committed / "DESIGN.md").write_text("an edit made before the session\n")
    transcript = _write(tmp_path / "t.jsonl", _session())
    runner.invoke(app, ["runs", "start", "--hook"], input=_hook("SessionStart", committed))
    end = runner.invoke(
        app, ["runs", "record", "--hook"], input=_hook("SessionEnd", committed, transcript)
    )
    assert end.exit_code == 0 and end.output == ""
    assert not _records(committed)
    # the same file edited further in the session is a change
    runner.invoke(app, ["runs", "start", "--hook"], input=_hook("SessionStart", committed))
    (committed / "DESIGN.md").write_text("an edit made before the session, and one in it\n")
    end = runner.invoke(
        app, ["runs", "record", "--hook"], input=_hook("SessionEnd", committed, transcript)
    )
    assert end.exit_code == 0 and len(_records(committed)) == 1


def test_hooks_are_off_for_a_runner_that_records_itself(committed, claude_home, tmp_path):
    transcript = _write(tmp_path / "t.jsonl", _session())
    env = {"CHEME_RUN_RECORD": "off"}
    start = runner.invoke(
        app, ["runs", "start", "--hook"], input=_hook("SessionStart", committed), env=env
    )
    assert start.exit_code == 0 and not (committed / STATE_DIR).exists()
    (committed / "DESIGN.md").write_text("changed\n")
    end = runner.invoke(
        app,
        ["runs", "record", "--hook"],
        input=_hook("SessionEnd", committed, transcript),
        env=env,
    )
    assert end.exit_code == 0 and not _records(committed)


@pytest.mark.parametrize("stdin", ["", "garbage {", "[1]", '{"session_id": "../../etc"}'])
def test_hooks_never_fail_the_session(committed: Path, monkeypatch, stdin: str):
    monkeypatch.chdir(committed)
    monkeypatch.delenv("CHEME_RUN_RECORD", raising=False)
    for command in ("start", "record"):
        result = runner.invoke(app, ["runs", command, "--hook"], input=stdin)
        assert result.exit_code == 0, (command, result.output)
    assert not _records(committed)


def test_hook_outside_a_plant_repository_exits_0(tmp_path: Path):
    data = json.dumps({"session_id": SESSION, "cwd": str(tmp_path)})
    for command in ("start", "record"):
        result = runner.invoke(app, ["runs", command, "--hook"], input=data)
        assert result.exit_code == 0


def test_record_commit_touches_only_the_run_folder(committed, claude_home, monkeypatch):
    monkeypatch.chdir(committed)
    start = git(committed, "rev-parse", "HEAD").strip()
    (committed / "DESIGN.md").write_text("staged, not part of the record\n")
    git(committed, "add", "DESIGN.md")
    _write(project_dir(committed, claude_home) / f"{SESSION}.jsonl", _session())
    prompt = committed / "build" / "agent-run" / "S1" / "prompt.txt"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("Stage S1: draw the PFD.\n")
    result = runner.invoke(
        app,
        [
            "runs",
            "record",
            "--session-id",
            SESSION,
            "--kind",
            "agent",
            "--slug",
            "S1",
            "--task-file",
            str(prompt),
            "--cost",
            "5.08",
            "--budget",
            "7",
            "--start-commit",
            start,
            "--result",
            "success",
            "--checks",
            "--commit",
        ],
    )
    assert result.exit_code == 0, result.output
    run_id = "20261027-202240-s1"
    assert result.output.splitlines()[0] == f"runs/{run_id}"
    assert git(committed, "rev-list", "--count", f"{start}..HEAD").strip() == "1"
    assert git(committed, "log", "-1", "--format=%s").strip() == f"plant: run record {run_id}"
    touched = git(committed, "show", "--name-only", "--format=", "HEAD").split()
    assert touched and all(t.startswith(f"runs/{run_id}/") for t in touched)
    assert git(committed, "diff", "--cached", "--name-only").split() == ["DESIGN.md"]
    record = RunRecord.model_validate(
        yaml.safe_load((committed / "runs" / run_id / "run.yaml").read_text())
    )
    assert record.task_file == "build/agent-run/S1/prompt.txt"
    assert (committed / "runs" / run_id / "task.md").read_text() == "Stage S1: draw the PFD.\n"
    assert record.budget_usd == 7 and record.outcome.result == "success"
    assert [c.command for c in record.checks_after_run] == ["cheme check", "cheme maturity"]
    check = record.checks_after_run[0]
    assert check.exit == (1 if check.summary["FAIL"] else 0)
    assert set(check.summary) == {"ok", "FAIL", "n/a", "failing"}
    assert "levels" in record.checks_after_run[1].summary
    assert record.start_commit == start and record.complete, record.incomplete_notes
    # no runner, no SDK: null, and the record is still complete
    assert record.tools.runner is None and record.tools.claude_agent_sdk is None
    # recording the same session again is refused, nothing changes
    again = runner.invoke(app, ["runs", "record", "--session-id", SESSION, "--slug", "S1"])
    assert again.exit_code == 1 and "never rewritten" in again.output


def _fake_claude(tmp_path: Path, monkeypatch, output: str) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "claude"
    fake.write_text(f"#!/bin/sh\necho '{output}'\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")


def test_tools_pin_the_claude_code_version_of_the_transcript(committed, tmp_path, monkeypatch):
    _fake_claude(tmp_path, monkeypatch, "9.9.9 (Claude Code)")
    path = _write(tmp_path / f"{SESSION}.jsonl", _session())
    tools = record_run(committed, transcript=path).record.tools
    assert tools.claude_code == "2.1.3"  # the transcript's, not the claude on PATH
    assert tools.pydexpi == version("pydexpi")
    assert tools.cheme == version("cheme-as-code")
    # a transcript without versions: `claude --version`
    entries = [{k: v for k, v in e.items() if k != "version"} for e in _session()]
    path = _write(tmp_path / "old" / f"{SESSION}.jsonl", entries)
    tools = record_run(committed, transcript=path, slug="again").record.tools
    assert tools.claude_code == "9.9.9"


def test_claude_version_is_null_when_unknown(tmp_path: Path, monkeypatch):
    _fake_claude(tmp_path, monkeypatch, "not a version")
    assert claude_code_version() is None
    monkeypatch.setenv("PATH", str(tmp_path / "nowhere"))
    assert claude_code_version() is None


def test_core_commit_of_an_editable_checkout(tmp_path: Path, monkeypatch):
    checkout = tmp_path / "core"
    package = checkout / "src" / "chemeascode"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    git(checkout, "init", "-q")
    git(checkout, "add", "-A")
    git(checkout, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "core")
    head = git(checkout, "rev-parse", "HEAD").strip()
    assert source_checkout(package) == (head, False)
    monkeypatch.setattr(run_records, "_package_dir", lambda: package)
    tools = run_records._tools()  # this checkout is an editable install: no vcs_info
    assert (tools["core_commit"], tools["core_dirty"]) == (head, False)
    (checkout / "scratch.py").write_text("x = 1\n")  # untracked counts
    assert source_checkout(package) == (head, True)
    # a package folder no work tree tracks (a wheel in .venv inside a repository): unknown
    venv = checkout / ".venv" / "chemeascode"
    venv.mkdir(parents=True)
    (venv / "__init__.py").write_text("")
    (checkout / ".gitignore").write_text(".venv/\n")
    assert source_checkout(venv) == (None, None)
    assert source_checkout(tmp_path) == (None, None)


def test_record_runner_options(committed, claude_home, monkeypatch):
    monkeypatch.chdir(committed)
    start = git(committed, "rev-parse", "HEAD").strip()
    _write(project_dir(committed, claude_home) / f"{SESSION}.jsonl", _session())
    base = ["runs", "record", "--session-id", SESSION, "--start-commit", start]
    result = runner.invoke(
        app,
        [
            *base,
            "--slug",
            "sdk",
            "--sdk-version",
            "0.4.1",
            "--runner-name",
            "agent-cli",
            "--runner-commit",
            "0123abc",
            "--runner-dirty",
        ],
    )
    assert result.exit_code == 0, result.output
    data = yaml.safe_load((committed / result.output.splitlines()[0] / "run.yaml").read_text())
    assert data["tools"]["claude_agent_sdk"] == "0.4.1"
    assert data["tools"]["runner"] == {"name": "agent-cli", "commit": "0123abc", "dirty": True}
    assert data["complete"], data["incomplete_notes"]
    clean = runner.invoke(app, [*base, "--slug", "named", "--runner-name", "r", "--runner-clean"])
    assert clean.exit_code == 0, clean.output
    data = yaml.safe_load((committed / clean.output.splitlines()[0] / "run.yaml").read_text())
    assert data["tools"]["runner"] == {"name": "r", "commit": None, "dirty": False}
    assert data["tools"]["claude_agent_sdk"] is None and data["complete"]
    assert data["tools"]["same_revision"] is None  # the runner knows no commit


def test_same_revision_only_for_one_clean_commit():
    clean = {"commit": "abc1234", "dirty": False}
    assert same_revision("abc1234", False, clean) is True
    assert same_revision("abc1234", False, {**clean, "commit": "def5678"}) is False
    assert same_revision("abc1234", True, clean) is False  # cheme-as-code checkout had changes
    assert same_revision("abc1234", False, {**clean, "dirty": True}) is False
    assert same_revision("abc1234", None, clean) is False  # unknown state is never "clean"
    # a revision nobody knows (no git, a wheel, no runner): unknown, not invented
    assert same_revision(None, None, clean) is None
    assert same_revision("abc1234", False, None) is None
    assert same_revision("abc1234", False, {"commit": None, "dirty": None}) is None


def test_versions_without_git(tmp_path: Path, monkeypatch):
    # an exported snapshot (no .git) or a machine without git: no commit, no crash
    package = tmp_path / "src" / "chemeascode"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    monkeypatch.setattr(run_records, "_package_dir", lambda: package)
    assert source_checkout(package) == (None, None)
    monkeypatch.setenv("PATH", str(tmp_path / "nowhere"))  # git not found at all
    assert source_checkout(package) == (None, None)
    tools = run_records._tools(runner={"name": "agent-cli", "commit": None, "dirty": None})
    assert (tools["core_commit"], tools["core_dirty"], tools["same_revision"]) == (None, None, None)


def test_a_record_without_the_version_fields_still_validates():
    old = {
        "schema": "process-run/v1",
        "run_id": "20261027-202240-s1",
        "process": "plant",
        "kind": "agent",
        "complete": True,
        "tools": {"cheme": "0.9.0", "core_commit": None},
    }
    tools = RunRecord.model_validate(old).tools
    assert tools.cheme == "0.9.0" and tools.runner is None and tools.core_dirty is None
    assert tools.pydexpi is None and tools.claude_code is None


def test_runs_list(committed: Path, tmp_path: Path, monkeypatch):
    monkeypatch.chdir(committed)
    empty = runner.invoke(app, ["runs", "list"])
    assert empty.exit_code == 0 and "no run records" in empty.output
    path = _write(tmp_path / f"{SESSION}.jsonl", _session())
    record_run(committed, transcript=path, kind="agent", slug="s1", cost=5.0828)
    listed = runner.invoke(app, ["runs", "list"])
    assert listed.exit_code == 0
    assert listed.output.split() == [
        "20261027-202240-s1",
        "agent",
        "USD",
        "5.08",
        "15m22s",
        "incomplete",
        "2",
        "turns",
    ]
    rows = json.loads(runner.invoke(app, ["runs", "list", "--json"]).output)
    assert rows == [
        {
            "run_id": "20261027-202240-s1",
            "kind": "agent",
            "cost_usd": 5.0828,
            "wall_s": 922,
            "complete": False,
            "num_turns": 2,
        }
    ]
    bad = committed / "runs" / "20261027-210000" / "run.yaml"
    bad.parent.mkdir()
    bad.write_text("schema: process-run/v1\nrun_id: 20261027-210000\nkind: robot\n")
    broken = runner.invoke(app, ["runs", "list"])
    assert broken.exit_code == 1
    assert "runs/20261027-210000/run.yaml:3: error cheme.run-record-invalid" in broken.output


def test_schema_command_prints_the_run_record_schema():
    result = runner.invoke(app, ["schema", "process-run"])
    assert result.exit_code == 0
    schema = json.loads(result.output)
    assert schema["properties"]["schema"]["const"] == "process-run/v1"
    assert "process-run" in runner.invoke(app, ["schema"]).output


def test_record_modules_load_without_typer():
    import subprocess
    import sys

    code = (
        "import sys, chemeascode.project.run_records\n"
        "print(sorted(m for m in ('typer', 'fastapi') if m in sys.modules))\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"
