"""cheme status: one summary of sheets, findings by sheet, gates, sign-offs and reviews."""

import json
import shutil
from pathlib import Path

from typer.testing import CliRunner

from chemeascode.interfaces.cli import app
from tests.conftest import git, without_layout_gates

runner = CliRunner()


def status(*args: str) -> dict:
    result = runner.invoke(app, ["status", "--json", *args])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def setup_sheets(plant: Path) -> None:
    empty = plant / ".claude" / "skills" / "dexpi-xml" / "snippets" / "empty-sheet.xml"
    shutil.copy(empty, plant / "pid" / "P-02.xml")
    (plant / "plant.yaml").write_text(
        (plant / "plant.yaml")
        .read_text()
        .replace(
            "sheets: []",
            "sheets:\n  - {id: P-01, file: pid/P-01.xml}\n  - {id: P-02, file: pid/P-02.xml}\n"
            "  - {id: P-03, file: pid/P-03.xml}",
        )
    )
    (plant / "equipment" / "equipment-list.yaml").write_text(
        "equipment:\n"
        "  - {tag: T4750, type: Tank, sheet: P-01}\n"
        "  - {tag: P-201, type: CentrifugalPump, sheet: P-02}\n"
        "  - {tag: P-202, type: CentrifugalPump, sheet: P-02}\n"
        "  - {tag: X-1, type: Tank}\n"
    )


def test_status_of_sheets_and_findings(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    setup_sheets(plant)
    data = status("--no-gates")
    sheets = {s["id"]: s for s in data["sheets"]}
    assert sheets["P-01"]["state"] == "drawn" and sheets["P-01"]["drawn"]["equipment"] == 5
    assert sheets["P-02"]["state"] == "empty"
    assert sheets["P-02"]["missing"]["equipment"] == ["P-201", "P-202"]
    assert sheets["P-03"]["state"] == "missing"
    assert data["next_sheet"] == "P-02"
    assert data["validation"]["not_on_pid"] == {"P-02": 2, "unassigned": 1}
    assert data["signoffs"] == {} and data["legacy_status"] is None
    assert data["gates"] == {"concept": [], "basic": [], "detail": []}
    assert data["plant"]["stage"] == "concept"
    assert not (plant / "checks" / "status.json").exists()


def test_not_on_pid_counts_every_item_held_for_a_planned_sheet(plant: Path, monkeypatch):
    """validate folds the items of a planned sheet into one info finding; status counts each
    of them under its own sheet."""
    monkeypatch.chdir(plant)
    (plant / "plant.yaml").write_text(
        (plant / "plant.yaml")
        .read_text()
        .replace(
            "sheets: []",
            "sheets:\n  - {id: P-01, file: pid/P-01.xml}\n"
            "  - {id: P-02, file: pid/P-02.xml, status: planned}\n"
            "  - {id: P-03, file: pid/P-03.xml, status: planned}",
        )
    )
    (plant / "equipment" / "equipment-list.yaml").write_text(
        "equipment:\n"
        + "".join(f"  - {{tag: P-20{n}, type: CentrifugalPump, sheet: P-02}}\n" for n in range(4))
        + "  - {tag: P-301, type: CentrifugalPump, sheet: P-03}\n"
        "  - {tag: X-1, type: Tank, sheet: P-01}\n"
    )
    data = status("--no-gates")
    assert data["validation"]["by_rule"]["cheme.equipment-not-on-pid"] == 3
    assert data["validation"]["not_on_pid"] == {"P-02": 4, "P-03": 1, "P-01": 1}
    sheets = {s["id"]: s for s in data["sheets"]}
    assert len(sheets["P-02"]["missing"]["equipment"]) == 4


def test_status_text_gates_git_and_signoff(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    without_layout_gates(plant)
    git(plant, "add", "-A")
    git(plant, "commit", "-qm", "plant")
    before = sorted(p.name for p in plant.iterdir())
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0, result.output
    assert "next sheet to draw: none" in result.output
    # drawing-clean fails on the reference sheet's crossings, design-review without a record,
    # process-basic without a PFD; issues-basic is n/a without plant.yaml
    # issues:.
    assert "basic: 3 ok, 3 fail, 5 n/a (process-basic, drawing-clean, design-review)" in (
        result.output
    )
    assert "sign-offs: none" in result.output
    assert sorted(p.name for p in plant.iterdir()) == before  # nothing written (no build/ either)
    data = status()
    gates = {g["id"]: g["status"] for g in data["gates"]["basic"]}
    assert gates["pids-valid"] == "pass" and gates["design-review"] == "fail"
    assert data["git"]["branch"] == "main" and data["git"]["dirty"] == []
    # A sign-off on an unmerged branch is flagged.
    git(plant, "checkout", "-qb", "stage/concept")
    basis = plant / "process" / "design-basis.yaml"
    basis.write_text(basis.read_text() + "# ASSUMED\n")
    git(plant, "commit", "-qam", "assumed")
    assert runner.invoke(app, ["check", "--stage", "concept", "--write"]).exit_code == 0
    git(plant, "add", "checks/status.json")
    git(plant, "commit", "-qm", "sign off concept")
    data = status("--no-gates")
    assert data["signoffs"]["concept"]["on_default_branch"] is False
    assert data["git"]["ahead"] == 2 and data["git"]["behind"] == 0
    text = runner.invoke(app, ["status", "--no-gates"]).output
    assert "NOT on the default branch" in text
    git(plant, "checkout", "-q", "main")
    git(plant, "merge", "-q", "--ff-only", "stage/concept")
    assert status("--no-gates")["signoffs"]["concept"]["on_default_branch"] is True


def test_status_at_a_revision(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    git(plant, "add", "-A")
    git(plant, "commit", "-qm", "plant")
    first = git(plant, "rev-parse", "HEAD").strip()
    setup_sheets(plant)
    git(plant, "add", "-A")
    git(plant, "commit", "-qm", "sheets")
    data = status("--rev", first, "--no-gates")
    assert data["rev"] == first and [s["id"] for s in data["sheets"]] == ["P-01"]
    assert all(s["file"] == "pid/P-01.xml" for s in data["sheets"])
    assert "worktree" not in git(plant, "worktree", "list")
    assert len(git(plant, "worktree", "list").splitlines()) == 1


def test_api_status(plant: Path):
    import pytest

    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from chemeascode.interfaces.api.serve import create_app

    git(plant, "add", "-A")
    git(plant, "commit", "-qm", "plant")
    data = TestClient(create_app(plant, None, allowed_hosts=["testserver"])).get("/api/status")
    assert data.status_code == 200
    assert set(data.json()) >= {"plant", "sheets", "next_sheet", "validation", "gates", "git"}
