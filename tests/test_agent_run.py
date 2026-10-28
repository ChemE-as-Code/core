"""The packaged agent design run: the runner builds its prompt from the repository."""

import importlib.util
import json
import shutil
import sys
from pathlib import Path

from tests.conftest import git

RUNNER = (
    Path(__file__).parents[1] / "src/chemeascode/templates/project/scripts/agent-run/run_stage.py"
)


def runner_module(path: Path = RUNNER):
    spec = importlib.util.spec_from_file_location("run_stage", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_template_ships_the_runner(plant: Path):
    folder = plant / "scripts" / "agent-run"
    for name in (
        "run_stage.py",
        "stage-prompt.md",
        "reviewer-prompt.md",
        "allowed-tools.txt",
        "stages.json",
        "spec.md",
        "README.md",
    ):
        assert (folder / name).is_file(), name
    text = "".join(p.read_text() for p in folder.iterdir() if p.is_file())
    assert "/Users/" not in text and "/home/" not in text
    tools = (folder / "allowed-tools.txt").read_text()
    assert "Bash(sed -i" not in tools
    assert "Bash(sed -n:*)" in tools and "Bash(awk" not in tools and "Bash(cp" not in tools
    json.loads((folder / "stages.json").read_text())


def test_dry_run_derives_this_stage_from_the_repository(plant: Path, monkeypatch, capsys):
    monkeypatch.chdir(plant)
    monkeypatch.setenv("CHEME", str(Path(sys.executable).parent / "cheme"))
    monkeypatch.setenv("CLAUDE_BIN", "/bin/false")
    empty = plant / ".claude" / "skills" / "dexpi-xml" / "snippets" / "empty-sheet.xml"
    shutil.copy(empty, plant / "pid" / "P-02.xml")
    config = plant / "plant.yaml"
    config.write_text(
        config.read_text().replace(
            "sheets: []",
            "sheets:\n  - {id: P-01, file: pid/P-01.xml}\n  - {id: P-02, file: pid/P-02.xml}",
        )
    )
    (plant / "scripts" / "agent-run" / "spec.md").write_text("A small test plant.\n")
    git(plant, "add", "-A")
    git(plant, "commit", "-qm", "plant")
    out = plant / "build" / "agent-run"
    (out / "S1").mkdir(parents=True)
    (out / "S1" / "review.json").write_text(json.dumps({"carry_over": ["split the vent header"]}))
    copy = plant / "scripts" / "agent-run" / "run_stage.py"
    assert copy.read_text() == RUNNER.read_text()
    code = runner_module(copy).main(["stage", "S2", "--dry-run"])
    assert code == 0
    prompt = (out / "S2" / "prompt.txt").read_text()
    assert "A small test plant." in prompt
    assert "Already drawn (edit them only to fix findings, never draw them again): P-01" in prompt
    assert "Next sheet to draw: P-02" in prompt
    assert "1) split the vent header" in prompt
    assert "USD 7" in prompt and "${" not in prompt
    printed = capsys.readouterr().out
    assert "--max-budget-usd 7" in printed and "--settings .claude/settings.json" in printed
    review = runner_module(copy).main(["review", "S2", "--dry-run"])
    assert review == 0
    reviewer = (out / "S2" / "review" / "prompt.txt").read_text()
    assert "reviewer_kind agent" in reviewer and "carry_over" in reviewer


def test_runner_runs_on_python_3_9():
    """macOS ships python3 3.9: `python3 scripts/agent-run/run_stage.py` must work there."""
    import ast

    text = RUNNER.read_text()
    ast.parse(text, feature_version=(3, 9))
    for newer in ("datetime.UTC", "tomllib", "typing.Self", "ExceptionGroup", "zip(strict"):
        assert newer not in text, newer


def test_runner_dry_run_with_an_older_system_python(plant: Path, tmp_path: Path):
    import os
    import subprocess

    import pytest

    old = next(
        (
            p
            for p in ("/usr/bin/python3", shutil.which("python3.9"), shutil.which("python3.10"))
            if p and Path(p).is_file()
        ),
        None,
    )
    if old is None:
        pytest.skip("no system python3 to try")
    version = subprocess.run(
        [old, "-c", "import sys; print(sys.version_info[:2] < (3, 11))"],
        check=False,
        capture_output=True,
        text=True,
    )
    if version.returncode != 0 or version.stdout.strip() != "True":
        pytest.skip(f"{old} is 3.11 or later")
    (plant / "scripts" / "agent-run" / "spec.md").write_text("A small test plant.\n")
    git(plant, "add", "-A")
    git(plant, "commit", "-qm", "plant")
    env = {
        **os.environ,
        "CHEME": str(Path(sys.executable).parent / "cheme"),
        "PATH": "/usr/bin:/bin",  # no claude: a dry run does not need it
    }
    env.pop("CLAUDE_BIN", None)
    result = subprocess.run(
        [old, "-I", "scripts/agent-run/run_stage.py", "stage", "S1", "--dry-run"],
        cwd=plant,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert (plant / "build" / "agent-run" / "S1" / "prompt.txt").is_file()


def test_headless_allowlist_matches_the_settings(plant: Path):
    """A Bash command allowed headless is allowed interactively too, and vice versa."""
    tools = [
        line.strip()
        for line in (plant / "scripts" / "agent-run" / "allowed-tools.txt").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    settings = json.loads((plant / ".claude" / "settings.json").read_text())["permissions"]
    allow = set(settings["allow"])
    bash = {t for t in tools if t.startswith("Bash(")}
    assert bash == {t for t in allow if t.startswith("Bash(")}
    assert "Bash(python3 scripts/:*)" not in bash


def _fake_claude(tmp_path: Path, cost: float) -> Path:
    """A ``claude`` that records its arguments and prints a result with *cost*."""
    fake = tmp_path / "claude"
    fake.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$@" > "{tmp_path}/args.txt"\n'
        f'echo \'{{"total_cost_usd": {cost}, "num_turns": 1, '
        '"permission_denials": [{"tool_name": "Bash"}]}\'\n'
    )
    fake.chmod(0o755)
    return fake


def test_runner_keeps_a_chain_inside_the_total_cap(plant: Path, tmp_path: Path, monkeypatch):
    monkeypatch.chdir(plant)
    monkeypatch.setenv("CHEME", str(Path(sys.executable).parent / "cheme"))
    monkeypatch.setenv("CLAUDE_BIN", str(_fake_claude(tmp_path, 5.23)))
    (plant / "scripts" / "agent-run" / "spec.md").write_text("A small test plant.\n")
    plan = plant / "scripts" / "agent-run" / "stages.json"
    data = json.loads(plan.read_text())
    data["stages"][1]["extra_tools"] = ["Bash(npm:*)"]
    plan.write_text(json.dumps(data))
    git(plant, "add", "-A")
    git(plant, "commit", "-qm", "plant")
    runner = runner_module(plant / "scripts" / "agent-run" / "run_stage.py")
    out = plant / "build" / "agent-run"

    assert runner.main(["stage", "S1", "--total-cap", "8"]) == 0
    launch = json.loads((out / "S1" / "launch.json").read_text())
    assert launch["total_cost_usd"] == 5.23 and launch["num_turns_last_segment"] == 1
    assert launch["permission_denials"] == 1
    assert (out / "S1" / "done").read_text() == "exit 0\n"

    # S2's own cap (7) is lowered to what the total leaves (8 - 5.23), in the prompt too.
    assert runner.main(["stage", "S2", "--total-cap", "8", "--extra-tool", "Bash(npx:*)"]) == 0
    args = (tmp_path / "args.txt").read_text().splitlines()
    assert args[args.index("--max-budget-usd") + 1] == "2.77"
    assert "Bash(npm:*)" in args and "Bash(npx:*)" in args
    assert "USD 2.77" in (out / "S2" / "prompt.txt").read_text()
    assert "--no-verify" in (out / "S2" / "prompt.txt").read_text()

    # The fake result names no session: no run record, and the runner says so.
    assert launch["run_record"] is None and not [
        p for p in (plant / "runs").iterdir() if p.is_dir()
    ]

    # Nothing left: the review is skipped and claude is not started.
    (tmp_path / "args.txt").unlink()
    assert runner.main(["review", "S2", "--total-cap", "8"]) == 3
    assert not (tmp_path / "args.txt").exists()


def test_runner_records_the_session_and_switches_its_hooks_off(
    plant: Path, tmp_path: Path, monkeypatch, capsys
):
    """After the session the runner writes and commits runs/<run-id>/ with `cheme runs
    record`; the session itself runs with CHEME_RUN_RECORD=off, so its hooks record nothing."""
    from chemeascode.integrations.claude_code import project_dir

    session = "5e55e55e-0000-4000-8000-000000000001"
    home = tmp_path / "claude-home"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
    monkeypatch.delenv("CHEME_RUN_RECORD", raising=False)
    monkeypatch.chdir(plant)
    transcript = project_dir(plant.resolve(), home) / f"{session}.jsonl"
    transcript.parent.mkdir(parents=True)
    line = {
        "type": "assistant",
        "sessionId": session,
        "timestamp": "2026-10-27T20:22:41Z",
        "message": {
            "id": "msg_1",
            "model": "claude-opus-5-5",
            "content": [{"type": "tool_use", "name": "Bash", "input": {"command": "cheme check"}}],
            "usage": {"input_tokens": 1, "output_tokens": 2},
        },
    }
    transcript.write_text(json.dumps(line) + "\n")
    fake = tmp_path / "claude"
    fake.write_text(
        "#!/bin/sh\n"
        f'echo "$CHEME_RUN_RECORD" > "{tmp_path}/switch.txt"\n'
        f'echo \'{{"total_cost_usd": 1.5, "num_turns": 3, "session_id": "{session}", '
        '"subtype": "success", "result": "Drew the PFD."}\'\n'
    )
    fake.chmod(0o755)
    monkeypatch.setenv("CHEME", str(Path(sys.executable).parent / "cheme"))
    monkeypatch.setenv("CLAUDE_BIN", str(fake))
    (plant / "scripts" / "agent-run" / "spec.md").write_text("A small test plant.\n")
    git(plant, "add", "-A")
    git(plant, "commit", "-qm", "plant")
    head = git(plant, "rev-parse", "HEAD").strip()
    runner = runner_module(plant / "scripts" / "agent-run" / "run_stage.py")
    assert runner.main(["stage", "S1", "--budget", "3"]) == 0
    assert (tmp_path / "switch.txt").read_text().strip() == "off"
    run_id = "20261027-202241-s1"
    launch = json.loads((plant / "build" / "agent-run" / "S1" / "launch.json").read_text())
    assert launch["run_record"] == f"runs/{run_id}"
    assert f"run record runs/{run_id}" in capsys.readouterr().out
    assert git(plant, "log", "-1", "--format=%s").strip() == f"plant: run record {run_id}"
    assert git(plant, "rev-list", "--count", f"{head}..HEAD").strip() == "1"
    import yaml

    folder = plant / "runs" / run_id
    record = yaml.safe_load((folder / "run.yaml").read_text())
    assert record["kind"] == "agent" and record["start_commit"] == head
    assert record["cost_usd"] == 1.5 and record["budget_usd"] == 3.0
    assert record["task_file"] == "build/agent-run/S1/prompt.txt"
    assert record["outcome"] == {"result": "success", "report": "report.md"}
    assert (folder / "report.md").read_text() == "Drew the PFD.\n"
    assert [c["command"] for c in record["checks_after_run"]] == ["cheme check", "cheme maturity"]
    assert record["checks_by_agent"] == ["cheme check"]
    assert record["tools"]["runner"] == {"name": "run_stage.py", "commit": None, "dirty": None}
    assert (folder / "task.md").read_text() == (
        plant / "build" / "agent-run" / "S1" / "prompt.txt"
    ).read_text()
