"""The bundled-skills manifest, cheme skills status/update, and init never silently
replacing a skill changed locally."""

import hashlib
import os

import pytest
from typer.testing import CliRunner

from chemeascode.interfaces.cli import app
from chemeascode.templates import install
from chemeascode.templates.install import bundled_files, init, skill_status, skills_manifest

runner = CliRunner()
SKILL = ".claude/skills/review/SKILL.md"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _run(root, *args):
    cwd = os.getcwd()
    os.chdir(root)
    try:
        return runner.invoke(app, list(args))
    finally:
        os.chdir(cwd)


@pytest.fixture
def plant(tmp_path):
    root = tmp_path / "plant"
    init(root, "Test")
    return root


def test_manifest_lists_every_bundled_file_with_its_current_hash_first():
    manifest = skills_manifest()
    assert manifest["schema"] == install.MANIFEST_SCHEMA
    stale = [
        f"{skill}/{name}"
        for skill, found in bundled_files().items()
        for name, path in found.items()
        if manifest["skills"].get(skill, {}).get(name, [None])[0] != _sha(path.read_bytes())
    ]
    assert not stale, "run uv run python scripts/build_skill_manifest.py: " + ", ".join(stale)


def test_fresh_init_is_current(plant):
    states = {f.state for f in skill_status(plant)}
    assert states == {"current"}
    result = _run(plant, "skills", "status")
    assert result.exit_code == 0 and "0 outdated, 0 modified, 0 missing" in result.stdout


def test_update_installs_missing_and_outdated_and_keeps_modified(plant, monkeypatch):
    old = b"an earlier bundled version\n"
    manifest = skills_manifest()
    manifest["skills"]["pid-edit"]["SKILL.md"].append(_sha(old))
    monkeypatch.setattr(install, "skills_manifest", lambda: manifest)
    (plant / ".claude/skills/pid-edit/SKILL.md").write_bytes(old)
    (plant / ".claude/skills/layout-yaml/SKILL.md").unlink()
    (plant / SKILL).write_text("local instructions\n")
    states = {f.path: f.state for f in skill_status(plant)}
    assert states[".claude/skills/pid-edit/SKILL.md"] == "outdated"
    assert states[".claude/skills/layout-yaml/SKILL.md"] == "missing"
    assert states[SKILL] == "modified"

    result = _run(plant, "skills", "update")
    assert result.exit_code == 1
    assert ".claude/skills/pid-edit/SKILL.md: updated" in result.stdout
    assert ".claude/skills/layout-yaml/SKILL.md: installed" in result.stdout
    assert f"{SKILL}: warning cheme.skill-modified" in result.stdout
    assert (plant / SKILL).read_text() == "local instructions\n"
    assert {f.path: f.state for f in skill_status(plant)} == {
        **dict.fromkeys(states, "current"),
        SKILL: "modified",
    }

    result = _run(plant, "skills", "update", "review", "--force")
    assert result.exit_code == 0 and "cheme.skill-modified" in result.stdout
    assert {f.state for f in skill_status(plant)} == {"current"}


def test_update_of_named_skills_only(plant):
    (plant / SKILL).unlink()
    (plant / ".claude/skills/pid-edit/SKILL.md").unlink()
    result = _run(plant, "skills", "update", "review")
    assert result.exit_code == 0
    assert (plant / SKILL).is_file()
    assert not (plant / ".claude/skills/pid-edit/SKILL.md").exists()


def test_init_reports_a_modified_skill_and_replaces_it_only_with_force(tmp_path):
    root = tmp_path / "plant"
    init(root, "Test")
    (root / SKILL).write_text("local instructions\n")
    (root / "plant.yaml").unlink()
    result = runner.invoke(app, ["init", str(root), "--name", "Test"])
    assert result.exit_code == 0
    assert f"{SKILL}: warning cheme.skill-modified" in result.stdout
    assert "kept" in result.stdout
    assert (root / SKILL).read_text() == "local instructions\n"

    result = runner.invoke(app, ["init", str(root), "--name", "Test", "--force"])
    assert result.exit_code == 0
    assert "replaced by the bundled version (--force)" in result.stdout
    assert (root / SKILL).read_text() != "local instructions\n"


def test_init_output_is_unchanged_when_no_skill_was_modified(tmp_path):
    result = runner.invoke(app, ["init", str(tmp_path / "p"), "--name", "Test"])
    assert "skill-modified" not in result.stdout
