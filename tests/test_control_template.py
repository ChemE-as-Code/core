"""The control files ``cheme init`` writes: templates that cost a plant
nothing until it changes them, the detail-stage gate on them, and the bundled control skills."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from chemeascode.interfaces.cli import app
from tests.conftest import git

runner = CliRunner()


def validate(plant: Path) -> list[dict]:
    return json.loads(runner.invoke(app, ["validate", "--json"]).output)["findings"]


def test_init_writes_the_control_templates_and_skills(plant: Path):
    for path in (
        "control/loops.yaml",
        "control/sequences.yaml",
        "control/philosophy.md",
        "process/narrative.md",
    ):
        assert (plant / path).is_file(), path
    for skill in ("control-loops", "control-sequences", "control-narrative"):
        text = (plant / ".claude" / "skills" / skill / "SKILL.md").read_text()
        assert text.startswith(f"---\nname: {skill}\n")
    assert "PROPOSED" in (plant / "control/philosophy.md").read_text()


def test_the_empty_templates_give_no_findings_and_no_page(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    assert [f for f in validate(plant) if f["rule"].startswith("cheme.control")] == []
    result = runner.invoke(app, ["control", "report"])
    assert result.exit_code == 2
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from chemeascode.interfaces.api.serve import create_app

    api = TestClient(create_app(plant, None, allowed_hosts=["testserver"]))
    assert api.get("/api/control").status_code == 404


def test_a_started_narrative_is_checked(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    path = plant / "process/narrative.md"
    text = path.read_text().replace("sections: []", "sections:\n  - {id: FEED, title: Feed}")
    path.write_text(text)
    found = [f for f in validate(plant) if f["rule"].startswith("cheme.control")]
    assert [f["message"] for f in found] == ["section FEED: has no heading in the text"]
    report = json.loads(runner.invoke(app, ["control", "report", "--json"]).output)
    assert [f["path"] for f in report["files"]] == [
        "control/cause-effect.yaml",
        "process/narrative.md",
    ]


def test_the_detail_gate_requires_complete_control_records(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    git(plant, "add", "-A")
    git(plant, "commit", "-qm", "init")

    from chemeascode.foundation.workspace import Workspace
    from chemeascode.project.checks import run_checks

    def gate() -> str:
        return {c.id: c for c in run_checks(Workspace(plant))}["control-complete"].status

    assert gate() == "pass"
    (plant / "control/loops.yaml").write_text("loops:\n  - {id: FIC-1, title: draft}\n")
    assert gate() == "fail"


def test_the_template_fingerprints_are_the_templates():
    from chemeascode.domains.control.documents import TEMPLATE_FINGERPRINTS
    from chemeascode.foundation.provenance import file_fingerprint

    templates = Path(__file__).resolve().parents[1] / "src/chemeascode/templates/project"
    for path, fingerprint in TEMPLATE_FINGERPRINTS.items():
        assert file_fingerprint(templates / path) == fingerprint, (
            f"{path} changed: update TEMPLATE_FINGERPRINTS in domains/control/documents.py"
        )


def test_prose_without_front_matter_is_checked(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    (plant / "process/narrative.md").write_text("# Narrative\n\n## FEED Feed\n\nThe feed ...\n")
    found = [f for f in validate(plant) if f["rule"].startswith("cheme.control")]
    assert [f["message"] for f in found] == [
        "the narrative names no process sections in its front matter"
    ]
    report = json.loads(runner.invoke(app, ["control", "report", "--json"]).output)
    assert report["present"] and "process/narrative.md" in [f["path"] for f in report["files"]]


def test_report_and_validate_agree_beside_a_template_narrative(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    (plant / "control/loops.yaml").write_text("loops:\n  - {id: FIC-1, section: FEED}\n")
    validated = {f["id"] for f in validate(plant) if f["rule"].startswith("cheme.control")}
    report = json.loads(runner.invoke(app, ["control", "report", "--json"]).output)
    assert {f["id"] for f in report["findings"]} == validated
    assert not any("section FEED" in f for f in validated)  # no narrative: sections unchecked


def test_has_control_in_the_repo_info(plant: Path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from chemeascode.interfaces.api.serve import create_app

    git(plant, "add", "-A")
    git(plant, "commit", "-qm", "init")
    first = git(plant, "rev-parse", "HEAD").strip()
    api = TestClient(create_app(plant, None, allowed_hosts=["testserver"]))
    assert api.get("/api/repo").json()["has_control"] is False
    (plant / "control/philosophy.md").write_text("# Control philosophy\n\nProse.\n")
    assert api.get("/api/repo").json()["has_control"] is True
    git(plant, "commit", "-qam", "philosophy")
    assert api.get("/api/repo", params={"rev": first}).json()["has_control"] is False
