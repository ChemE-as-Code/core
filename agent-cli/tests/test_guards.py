"""Guard patterns of agent.py: `uv run --with pytest pytest -q`."""

import asyncio
from pathlib import Path

import pytest

import agent

DESTRUCTIVE = [
    "rm -rf build",
    "git push -u origin case/x",
    "git reset --hard origin/main",
    "gh pr merge 12 --merge",
    "gh api repos/o/r/pulls/12/merge -X PUT",
    "gh api --method DELETE repos/o/r/git/refs/heads/x",
    "find . -name '*.tmp' | xargs rm",
    "find . -name '*.tmp' | xargs -0 rm -f",
    "git worktree remove ../wt/x",
    "ls && rm out.txt",
]
SAFE = [
    "git status",
    "git log --oneline origin/main..HEAD",
    "gh pr view 12",
    "gh api repos/o/r/pulls/12",
    "uv run pytest -q",
    "cheme validate",
    "grep -rn 'rm' src/",
]
SECRET = [
    "echo $ANTHROPIC_API_KEY",
    "printenv",
    "env",
    "env | grep KEY",
    "python -c 'import os; print(os.environ)'",
    "node -e 'console.log(process.env)'",
    "cat /proc/self/environ",
    "ps eww",
]
NOT_SECRET = ["export PATH=/x:$PATH; uv sync", "set -e; ls", "ps aux | grep agent.py"]


@pytest.mark.parametrize("cmd", DESTRUCTIVE)
def test_destructive_commands_are_caught(cmd):
    assert agent.DESTRUCTIVE.search(cmd)


@pytest.mark.parametrize("cmd", SAFE)
def test_ordinary_commands_pass(cmd):
    assert not agent.DESTRUCTIVE.search(cmd)


@pytest.mark.parametrize("cmd", SECRET)
def test_key_revealing_commands_are_refused(cmd):
    assert agent.SECRET.search(cmd)


@pytest.mark.parametrize("cmd", NOT_SECRET)
def test_ordinary_environment_use_passes(cmd):
    assert not agent.SECRET.search(cmd)


def _write(guard, path):
    return asyncio.run(guard({"tool_input": {"file_path": path}}, "t", None))


def test_write_guard_resolves_relative_paths_against_the_agent_cwd(tmp_path):
    guard = agent.make_write_guard(tmp_path.resolve(), lambda _: None)
    assert _write(guard, "notes.md") == {}  # relative: inside the agent's cwd
    assert _write(guard, str(tmp_path / "a" / "b.md")) == {}
    denied = _write(guard, str(Path(tmp_path).parent / "elsewhere.md"))
    assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert _write(guard, "../escape.md")["hookSpecificOutput"]["permissionDecision"] == "deny"


@pytest.mark.parametrize("text, done", [
    ("All set.\n\nSTATUS: DONE", True),
    ("STATUS: BLOCKED: no CI access", True),
    ("Findings ...\nVERDICT: fix", True),
    ("Waiting for the test suite; I'll continue when it finishes.", False),
])
def test_final_line_detection(text, done):
    assert bool(agent.DONE.search(text)) is done


def test_cost_estimate_from_transcript(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    d = tmp_path / ".claude" / "projects" / "-x"
    d.mkdir(parents=True)
    line = '{"message": {"id": "m1", "usage": {"input_tokens": 1000, "output_tokens": 100}}}\n'
    (d / "sid.jsonl").write_text(line + line, encoding="utf-8")  # the same message twice counts once
    assert agent.estimate_cost("sid", "claude-opus-5-5") == pytest.approx(1000 * 4e-6 + 100 * 20e-6)
    assert agent.estimate_cost("sid", "unknown-model") is None
    assert agent.estimate_cost(None, "claude-opus-5-5") is None


@pytest.mark.parametrize("cmd", [
    "git push --force origin case/x",
    "git push origin main",
    "git push origin HEAD:main",
    "gh repo delete o/r --yes",
    "gh api repos/o/r/git/refs/heads/x -X DELETE",
    "rm -rf ..",
    "rm -rf /",
    r"Remove-Item -Recurse -Force C:\ ",
])
def test_hard_deny(cmd):
    assert agent.HARD_DENY.search(cmd)


@pytest.mark.parametrize("cmd", [
    "git push -u origin claude/core-364",
    "git push --force-with-lease origin claude/core-364",
    "gh pr merge 12 --squash --delete-branch",
    "rm -rf build",
])
def test_not_hard_denied(cmd):
    assert not agent.HARD_DENY.search(cmd)


def _bash(guard, cmd):
    return asyncio.run(guard({"tool_input": {"command": cmd}}, "t", None))


def test_approve_modes():
    seen = []
    auto = agent.make_bash_guard("auto", lambda _: None, lambda d, c: seen.append(d))
    deny = agent.make_bash_guard("deny", lambda _: None)
    assert _bash(auto, "gh pr merge 12 --squash") == {}
    assert _bash(auto, "git push origin main")["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert _bash(deny, "gh pr merge 12 --squash")["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert _bash(auto, "git status") == {}
    assert seen == ["allow-auto", "deny-hard"]


@pytest.mark.parametrize("cmd", ["Remove-Item -Recurse build", "Stop-Process -Id 4", "Move-Item a b"])
def test_powershell_destructive(cmd):
    assert agent.DESTRUCTIVE.search(cmd)


@pytest.mark.parametrize("cmd", ["Get-ChildItem env:", "gci env:", "[Environment]::GetEnvironmentVariables()",
                                 "echo $env:ANTHROPIC_API_KEY"])
def test_powershell_secret(cmd):
    assert agent.SECRET.search(cmd)


def test_powershell_env_path_use_passes():
    assert not agent.SECRET.search(r'$env:PATH = "C:\x;$env:PATH"; uv sync')
