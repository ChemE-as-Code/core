"""cheme impact: review needed when a recorded source revision no longer matches."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from chemeascode.foundation.provenance import file_fingerprint
from chemeascode.foundation.reviews import load_records
from chemeascode.foundation.workspace import Workspace
from chemeascode.interfaces.cli import app
from chemeascode.project.impact import review_needed

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
runner = CliRunner()


def _git(root, *args):
    return subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=T", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture
def plant(tmp_path):
    root = tmp_path / "plant"
    shutil.copytree(EXAMPLES / "process-nested", root, ignore=shutil.ignore_patterns("build"))
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "start")
    return Workspace(root)


def _review(ws, name, topic, scope, basis=None):
    front = {
        "topic": topic,
        "reviewed_commit": _git(ws.root, "rev-parse", "HEAD"),
        "scope": scope,
        "reviewer": "R",
        "reviewer_kind": "human",
    }
    if basis is not None:
        front["basis"] = basis
    path = ws.root / "reviews" / name
    path.parent.mkdir(exist_ok=True)
    path.write_text("---\n" + yaml.safe_dump(front, sort_keys=False) + "---\n\n## Findings\n")
    _git(ws.root, "add", ".")
    _git(ws.root, "commit", "-q", "-m", f"review {name}")


def _retitle(ws, title):
    path = ws.root / "process/flowsheet.yaml"
    data = yaml.safe_load(path.read_text())
    data["streams"][0]["title"] = title
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def test_nothing_to_review_on_a_consistent_repository(plant):
    _review(plant, "2026-01-01-design.md", "design", ["process/"])
    assert review_needed(plant) == []


def test_editing_the_flowsheet_flags_the_generated_sheets(plant):
    _retitle(plant, "renamed feed")
    found = {(f.file, f.key) for f in review_needed(plant)}
    assert ("process/BFD.xml", "source") in found
    finding = next(f for f in review_needed(plant) if f.file == "process/BFD.xml")
    assert finding.level == "info" and finding.rule == "cheme.review-needed"
    assert "changed since it was generated" in finding.message and finding.hint
    # nothing was regenerated
    assert _git(plant.root, "status", "--porcelain") == "M process/flowsheet.yaml"


def test_editing_a_reviewed_file_flags_the_latest_record_of_its_topic(plant):
    _review(plant, "2026-01-01-design.md", "design", ["process/flowsheet.yaml"])
    _retitle(plant, "renamed feed")
    found = [f for f in review_needed(plant) if f.file.startswith("reviews/")]
    assert [(f.file, f.key) for f in found] == [("reviews/2026-01-01-design.md", "scope")]
    assert "process/flowsheet.yaml changed since the reviewed commit" in found[0].message
    _git(plant.root, "commit", "-qam", "edit")
    _review(plant, "2026-02-01-design.md", "design", ["process/flowsheet.yaml"])
    assert not [f for f in review_needed(plant) if f.file.startswith("reviews/")]


def test_records_of_one_topic_split_by_file_are_each_compared(plant):
    """Only the newest record of a topic was compared, missing the earlier one's files."""
    _review(plant, "2026-01-01-design.md", "design", ["process/flowsheet.yaml"])
    _review(plant, "2026-01-02-design.md", "design", ["process/materials.yaml"])
    _retitle(plant, "renamed feed")
    found = [f for f in review_needed(plant) if f.file.startswith("reviews/")]
    assert [f.file for f in found] == ["reviews/2026-01-01-design.md"]
    assert "process/flowsheet.yaml changed since" in found[0].message
    # a newer record of the topic that covers the file supersedes the earlier one for it
    _git(plant.root, "commit", "-qam", "edit")
    _review(plant, "2026-01-03-design.md", "design", ["process/"])
    _retitle(plant, "renamed again")
    found = [f for f in review_needed(plant) if f.file.startswith("reviews/")]
    assert [f.file for f in found] == ["reviews/2026-01-03-design.md"]


def test_a_scope_with_a_leading_slash_is_compared(plant):
    """Git failed on '/process/flowsheet.yaml' and impact stayed silent."""
    _review(plant, "2026-01-01-design.md", "design", ["/process/flowsheet.yaml"])
    _retitle(plant, "renamed feed")
    found = [f for f in review_needed(plant) if f.file.startswith("reviews/")]
    assert len(found) == 1 and "process/flowsheet.yaml changed since" in found[0].message


def test_a_git_failure_is_reported_not_silent(plant, monkeypatch):
    from chemeascode.foundation import gitinfo

    _review(plant, "2026-01-01-design.md", "design", ["process/flowsheet.yaml"])
    monkeypatch.setattr(gitinfo, "changed_since", lambda *args: None)
    found = [f for f in review_needed(plant) if f.file.startswith("reviews/")]
    assert len(found) == 1 and "cannot tell whether its scope changed" in found[0].message


def test_a_record_whose_commit_is_unknown_supersedes_nothing(plant):
    _review(plant, "2026-01-01-design.md", "design", ["process/flowsheet.yaml"])
    _review(plant, "2026-01-02-design.md", "design", ["process/flowsheet.yaml"])
    path = plant.root / "reviews" / "2026-01-02-design.md"
    head = _git(plant.root, "rev-parse", "HEAD~1")
    path.write_text(path.read_text().replace(head, "0" * 40))
    _git(plant.root, "commit", "-qam", "typo in the commit")
    _retitle(plant, "renamed feed")
    found = {f.file: f.message for f in review_needed(plant) if f.file.startswith("reviews/")}
    assert "process/flowsheet.yaml changed since" in found["reviews/2026-01-01-design.md"]
    assert "cannot be resolved here" in found["reviews/2026-01-02-design.md"]


def test_basis_entries_are_compared(plant):
    materials = "process/materials.yaml"
    basis = [
        {"path": materials, "revision": file_fingerprint(plant.root / materials)},
        {"path": "process/flowsheet.yaml", "revision": "0" * 40, "relation": "analyses"},
    ]
    _review(plant, "2026-01-01-hazop.md", "hazop", ["DESIGN.md"], basis)
    found = {f.key: f for f in review_needed(plant)}
    assert set(found) == {"basis[1]:process/flowsheet.yaml"}
    assert "cannot be resolved" in found["basis[1]:process/flowsheet.yaml"].message
    with (plant.root / materials).open("a") as handle:
        handle.write("\n# edited\n")
    found = {f.key: f for f in review_needed(plant)}
    assert "depends-on process/materials.yaml" in found[f"basis[0]:{materials}"].message


def test_records_without_basis_still_parse(plant):
    _review(plant, "2026-01-01-design.md", "design", ["process/"])
    (record,) = load_records(plant)
    assert record.front is not None and record.front.basis == []
    assert not record.front_errors


def test_cli_is_read_only_and_exits_zero(plant):
    _retitle(plant, "renamed feed")
    before = _git(plant.root, "status", "--porcelain")
    cwd = os.getcwd()
    os.chdir(plant.root)
    try:
        text = runner.invoke(app, ["impact"])
        data = runner.invoke(app, ["impact", "--json"])
    finally:
        os.chdir(cwd)
    assert text.exit_code == 0 and "cheme.review-needed" in text.stdout
    assert text.stdout.rstrip().endswith("artifact(s) to review")
    payload = json.loads(data.stdout)
    assert payload["commit"] == _git(plant.root, "rev-parse", "HEAD")
    assert {f["rule"] for f in payload["findings"]} == {"cheme.review-needed"}
    assert all(f["id"].startswith(f["file"] + "#review-needed:") for f in payload["findings"])
    assert _git(plant.root, "status", "--porcelain") == before


def test_api_impact_matches_the_cli(plant):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from chemeascode.interfaces.api.serve import create_app

    _retitle(plant, "renamed feed")
    before = _git(plant.root, "status", "--porcelain")
    client = TestClient(create_app(plant.root, None, allowed_hosts=["testserver"]))
    response = client.get("/api/impact")
    assert response.status_code == 200
    payload = response.json()
    assert payload["commit"] == _git(plant.root, "rev-parse", "HEAD")
    files = {f["file"] for f in payload["findings"]}
    assert {"process/BFD.xml", "process/PFD.xml"} <= files
    assert {f["level"] for f in payload["findings"]} == {"info"}
    cwd = os.getcwd()
    os.chdir(plant.root)
    try:
        cli = json.loads(runner.invoke(app, ["impact", "--json"]).stdout)
    finally:
        os.chdir(cwd)
    assert cli == payload
    assert _git(plant.root, "status", "--porcelain") == before
