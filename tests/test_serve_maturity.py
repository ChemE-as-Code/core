"""``GET /api/maturity``: the maturity report of the working tree, read-only."""

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from chemeascode.interfaces.api.export_static import export_static
from chemeascode.interfaces.api.serve import create_app
from chemeascode.project.maturity import MATURITY_FILE, maturity_payload
from tests.conftest import git

EXAMPLES = Path(__file__).parent.parent / "examples"


@pytest.fixture
def ammonia(tmp_path: Path) -> Path:
    """The process-ammonia example, committed in a fresh git repository."""
    root = tmp_path / "process-ammonia"
    shutil.copytree(EXAMPLES / "process-ammonia", root)
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "test@example.org")
    git(root, "config", "user.name", "Test")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "ammonia")
    return root


def client(root: Path) -> TestClient:
    return TestClient(create_app(root, allowed_hosts=["testserver"]))


def _files(root: Path) -> dict[Path, bytes]:
    return {p: p.read_bytes() for p in root.rglob("*") if p.is_file() and ".git" not in p.parts}


def test_maturity_is_the_report_and_writes_nothing(ammonia: Path):
    before = _files(ammonia)
    answer = client(ammonia).get("/api/maturity")
    assert answer.status_code == 200
    data = answer.json()
    assert _files(ammonia) == before
    assert not (ammonia / MATURITY_FILE).exists()
    assert git(ammonia, "status", "--porcelain") == ""
    # the same as the payload computed directly (as JSON), up to the evaluation time
    expected = json.loads(json.dumps(maturity_payload(ammonia)))
    assert data.pop("checked_at") and expected.pop("checked_at")
    assert data == expected
    assert data["schema"] == "cheme/maturity-report/v1"
    assert data["evaluated_through"] == "engineering"
    assert [lv["id"] for lv in data["levels"]] == [
        "sourced",
        "balanced",
        "predictive",
        "engineering",
    ]


def test_maturity_through_a_lower_level_skips_the_levels_above(ammonia: Path):
    data = client(ammonia).get("/api/maturity", params={"through": "balanced"}).json()
    assert data["evaluated_through"] == "balanced"
    levels = {lv["id"]: lv for lv in data["levels"]}
    for above in ("predictive", "engineering"):
        assert levels[above]["status"] == "not-evaluated"
        assert levels[above]["requirements"] == []


def test_maturity_refuses_an_unknown_level(ammonia: Path):
    answer = client(ammonia).get("/api/maturity", params={"through": "detail"})
    assert answer.status_code == 400
    assert "through: one of sourced, balanced, predictive, engineering" in answer.json()["error"]


def test_maturity_reads_the_working_tree(ammonia: Path):
    api = client(ammonia)
    first = api.get("/api/maturity", params={"through": "sourced"}).json()
    assert first["artifacts"]["files"]["line_list"] == []
    (ammonia / "piping").mkdir(exist_ok=True)
    (ammonia / "piping" / "line-list.yaml").write_text("lines: []\n", encoding="utf-8")
    # evaluated again on every request: an uncommitted file shows without a restart
    second = api.get("/api/maturity", params={"through": "sourced"}).json()
    assert second["artifacts"]["files"]["line_list"] == ["piping/line-list.yaml"]


def test_maturity_is_exported_without_excludes_only(ammonia: Path, tmp_path: Path):
    plain = export_static(ammonia, tmp_path / "plain")
    entry = plain["entries"]["maturity"]
    assert entry["status"] == 200 and entry["type"] == "application/json"
    data = json.loads((tmp_path / "plain" / "data" / entry["file"]).read_text())
    assert [lv["id"] for lv in data["levels"]][0] == "sourced"
    assert data["checked_at"] is None  # a snapshot is deterministic: no evaluation time
    assert not (ammonia / MATURITY_FILE).exists()
    # it quotes evidence from across the repository: not in a snapshot for publication
    published = export_static(ammonia, tmp_path / "published", exclude=["process/catalysts.yaml"])
    assert "maturity" not in published["entries"]
    # the working tree only: not in a revision snapshot
    head = git(ammonia, "rev-parse", "HEAD").strip()
    at_rev = export_static(ammonia, tmp_path / "at-rev", rev=head)
    assert "maturity" not in at_rev["entries"]
