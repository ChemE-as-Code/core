import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from chemeascode.domains.piping.fmt import format_file
from chemeascode.domains.piping.render import load_model
from chemeascode.integrations.git import cheme_command, readable_projection, setup
from tests.conftest import REFERENCE, git

HASH_TOKEN = re.compile(r"@[0-9a-f]{12}\b")


def test_projection_uses_the_ids_of_the_file(tmp_path: Path):
    sheet = tmp_path / "P-01.xml"
    shutil.copy(REFERENCE, sheet)
    format_file(sheet)
    text = readable_projection(load_model(sheet))
    assert not HASH_TOKEN.search(text)
    assert "PipeTee@PipeTee1  C3" in text
    assert "valve -> GlobeValve@GlobeValve2" in text
    # Stable: the same file gives the same text.
    assert readable_projection(load_model(sheet)) == text


def test_git_diff_works_without_cheme_on_path(plant: Path):
    format_file(plant / "pid" / "P-01.xml")
    git(plant, "add", "-A")
    git(plant, "commit", "-q", "-m", "P-01")
    lines = setup(plant, hook=True)
    assert any(line.startswith("pre-commit hook:") for line in lines)
    hook = Path(git(plant, "rev-parse", "--git-path", "hooks").strip())
    hook = (hook if hook.is_absolute() else plant / hook) / "pre-commit"
    assert "cheme() {" in hook.read_text()
    sheet = plant / "pid" / "P-01.xml"
    sheet.write_text(sheet.read_text().replace("<String>T4750</String>", "<String>T4751</String>"))
    env = {k: v for k, v in os.environ.items() if k not in ("PATH", "VIRTUAL_ENV")}
    env["PATH"] = os.path.dirname(shutil.which("git") or "/usr/bin/git") + ":/usr/bin:/bin"
    result = subprocess.run(
        ["git", "diff", "--", "pid/P-01.xml"],
        cwd=plant,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "-Tank@Tank1  T4750" in result.stdout
    assert "+Tank@Tank1  T4751" in result.stdout
    assert "could not load" not in result.stdout


def _fake_cheme(directory: Path) -> Path:
    directory.mkdir(parents=True)
    script = directory / "cheme"
    script.write_text("#!/bin/sh\nexit 0\n")
    script.chmod(0o755)
    return script


def test_setup_wires_the_running_cheme_not_the_one_on_path(plant: Path, monkeypatch):
    decoy = _fake_cheme(plant.parent / "decoy")
    running = _fake_cheme(plant.parent / "env" / "bin")
    (plant.parent / "env" / "other").mkdir()
    monkeypatch.setenv("PATH", f"{decoy.parent}:{os.environ['PATH']}")
    monkeypatch.setattr(sys, "argv", [str(plant.parent / "env" / "other" / ".." / "bin" / "cheme")])
    assert cheme_command() == str(running)
    setup(plant, hook=True)
    assert git(plant, "config", "diff.dexpi.textconv").strip() == f"{running} textconv"
    hook = (plant / ".git" / "hooks" / "pre-commit").read_text()
    assert str(running) in hook and str(decoy) not in hook
    # Not started as cheme (pytest, python -m): the one on PATH.
    monkeypatch.setattr(sys, "argv", ["pytest"])
    assert cheme_command() == str(decoy)


def test_hook_works_for_a_plant_in_a_subdirectory(plant: Path, tmp_path: Path):
    outer = tmp_path / "outer"
    outer.mkdir()
    shutil.rmtree(plant / ".git")
    shutil.move(str(plant), outer / "plant")
    sub = outer / "plant"
    git(outer, "init", "-q", "-b", "main")
    git(outer, "config", "user.email", "test@example.org")
    git(outer, "config", "user.name", "Test")
    format_file(sub / "pid" / "P-01.xml")
    setup(sub, hook=True)
    hook = (outer / ".git" / "hooks" / "pre-commit").read_text()
    assert '"$(git rev-parse --show-toplevel)"/plant' in hook
    git(sub, "add", "-A")
    result = subprocess.run(
        ["git", "commit", "-q", "-m", "plant"], cwd=sub, check=False, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
    # The hook sees the plant's staged sheets: an unformatted one is refused.
    sheet = sub / "pid" / "P-01.xml"
    sheet.write_text(sheet.read_text().replace("<", "\n  <", 3))
    git(sub, "add", "-A")
    result = subprocess.run(
        ["git", "commit", "-q", "-m", "unformatted"],
        cwd=sub,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "Run: cheme fmt pid/P-01.xml" in result.stderr
