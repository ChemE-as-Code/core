"""``cheme serve`` on a folder of plants: every plant under ``/p/<id>/`` (ADR 0034)."""

import json
import shutil
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from chemeascode.interfaces.api.library import create_library_app, discover_plants, plant_entry
from chemeascode.interfaces.cli import app as cli_app
from chemeascode.templates.install import init
from tests.conftest import REFERENCE, git


@pytest.fixture
def library(tmp_path: Path) -> Path:
    """A process library in one git repository: processes/alpha and processes/beta (beta with
    a process.yaml and a recorded maturity), and a plant nested in tools/ that is not one."""
    root = tmp_path / "library"
    for name in ("alpha", "beta"):
        plant = root / "processes" / name
        init(plant, f"Plant {name}")
        shutil.copy(REFERENCE, plant / "pid" / "P-01.xml")
    beta = root / "processes" / "beta"
    (beta / "process.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "beta",
                "title": "Beta process",
                "summary": "  Makes beta.  ",
                "families": ["gases", 3],
                "keywords": ["not served"],
            }
        ),
        encoding="utf-8",
    )
    (beta / "checks" / "maturity.json").write_text(
        json.dumps({"level": "balanced", "checked_at": "2026-10-30T08:00:00Z"}), encoding="utf-8"
    )
    (root / "README.md").write_text("# Library\n", encoding="utf-8")
    (root / "node_modules" / "x").mkdir(parents=True)
    (root / "node_modules" / "x" / "plant.yaml").write_text("name: no\n", encoding="utf-8")
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "test@example.org")
    git(root, "config", "user.name", "Test")
    git(root, "config", "maintenance.auto", "false")
    git(root, "config", "gc.auto", "0")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "library")
    return root


def client(root: Path, ui: Path | None = None) -> TestClient:
    return TestClient(create_library_app(root, ui, allowed_hosts=["testserver"]))


def test_discovery_finds_plants_below_and_not_in_skipped_folders(library: Path):
    plants = discover_plants(library)
    assert [(p.id, p.path) for p in plants] == [
        ("alpha", "processes/alpha"),
        ("beta", "processes/beta"),
    ]


def test_discovery_disambiguates_equal_folder_names(tmp_path: Path):
    for parent in ("a", "b"):
        init(tmp_path / parent / "same", "Same")
    assert [(p.id, p.path) for p in discover_plants(tmp_path)] == [
        ("a-same", "a/same"),
        ("b-same", "b/same"),
    ]
    # a plant's own folders are not searched: a plant inside a plant is the outer one's
    init(tmp_path / "outer", "Outer")
    init(tmp_path / "outer" / "inner", "Inner")
    assert "inner" not in {p.id for p in discover_plants(tmp_path)}


def test_plants_endpoint(library: Path):
    body = client(library).get("/api/plants").json()
    assert body["root_name"] == "library"
    alpha, beta = body["plants"]
    assert alpha["id"] == "alpha" and alpha["path"] == "processes/alpha"
    assert alpha["name"] == "Plant alpha" and alpha["stage"] == "concept"
    assert alpha["maturity"] is None and alpha["title"] is None and alpha["families"] == []
    assert alpha["sheets"] >= 0 and alpha["error"] is None
    # the optional process.yaml fields, only those; strings only; the recorded maturity
    assert beta["title"] == "Beta process" and beta["summary"] == "Makes beta."
    assert beta["families"] == ["gases"] and "keywords" not in beta
    assert beta["maturity"] == "balanced" and beta["maturity_checked"] == "2026-10-30T08:00:00Z"


def test_a_plant_whose_plant_yaml_does_not_validate_is_still_listed(library: Path):
    bad = library / "processes" / "alpha" / "plant.yaml"
    bad.write_text("stage: 3\nsheets: nope\n", encoding="utf-8")
    entry = plant_entry(discover_plants(library)[0])
    assert entry["id"] == "alpha" and entry["name"] is None
    assert entry["error"].startswith("plant.yaml:")


def test_each_plant_is_served_under_its_prefix(library: Path):
    api = client(library)
    assert api.get("/p/alpha/api/repo").json()["name"] == "Plant alpha"
    assert api.get("/p/beta/api/repo").json()["name"] == "Plant beta"
    # paths are the plant's own: its tree, its files, its history in the shared repository
    tree = {e["path"] for e in api.get("/p/beta/api/tree").json()}
    assert "plant.yaml" in tree and "process.yaml" in tree
    assert not any(p.startswith(("processes", "node_modules")) for p in tree)
    assert api.get("/p/beta/api/file", params={"path": "process.yaml"}).status_code == 200
    log = api.get("/p/alpha/api/log").json()
    assert [c["subject"] for c in log] == ["library"]
    # a plant's app is made once and kept
    assert api.get("/p/alpha/api/branches").json()[0]["name"] == "main"


def test_unknown_plants_and_paths(library: Path):
    api = client(library)
    for url in ("/p/gamma/api/repo", "/p/gamma/", "/p/../api/repo"):
        response = api.get(url)
        assert response.status_code == 404, url
    assert api.get("/p/gamma/api/repo").json() == {"error": "no plant 'gamma' in this library"}
    # the library has no plant endpoints of its own
    assert api.get("/api/repo").status_code == 404
    # /p/<id> without its slash goes to the plant's page
    redirect = api.get("/p/alpha", follow_redirects=False)
    assert redirect.status_code == 307 and redirect.headers["location"] == "/p/alpha/"


def test_the_viewer_at_the_index_and_every_plant_page(library: Path, tmp_path: Path):
    ui = tmp_path / "dist"
    (ui / "assets").mkdir(parents=True)
    (ui / "index.html").write_text("<html>viewer</html>", encoding="utf-8")
    (ui / "assets" / "app.js").write_text("js", encoding="utf-8")
    api = client(library, ui)
    for url in ("/", "/p/alpha/", "/p/alpha/streams", "/p/beta/pid/pid/P-01.xml"):
        response = api.get(url)
        assert response.status_code == 200 and "viewer" in response.text, url
        assert response.headers["x-frame-options"] == "SAMEORIGIN"
    assert api.get("/assets/app.js").text == "js"
    assert api.get("/assets/gone.js").status_code == 404
    # no viewer: the pages say how to start one
    assert "--ui" in client(library).get("/").json()["error"]


def test_the_guards_hold_for_the_library_and_each_plant(library: Path):
    api = client(library)
    evil = TestClient(
        create_library_app(library, allowed_hosts=["testserver"]), base_url="http://evil.example"
    )
    assert evil.get("/api/plants").status_code == 400
    assert evil.get("/p/alpha/api/repo").status_code == 400
    cross = {"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"}
    assert api.get("/api/plants", headers=cross).status_code == 403
    assert api.get("/p/alpha/api/repo", headers=cross).status_code == 403
    # each plant has its own session token for running its checks
    a = api.get("/p/alpha/api/session").json()
    b = api.get("/p/beta/api/session").json()
    assert a != b


def test_a_folder_without_plants_is_refused(tmp_path: Path):
    with pytest.raises(ValueError, match="no plant.yaml below"):
        create_library_app(tmp_path)


def _serve(monkeypatch, *args: str):
    calls: dict = {}
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: calls.update(app=app, **kwargs))
    result = CliRunner().invoke(cli_app, ["serve", *args])
    calls["result"] = result
    return calls


def test_the_cli_serves_a_library_root_as_a_library(library: Path, monkeypatch):
    calls = _serve(monkeypatch, "--repo", str(library))
    assert calls["result"].exit_code == 0, calls["result"].output
    assert "(2 plants)" in calls["result"].output
    api = TestClient(calls["app"], base_url="http://127.0.0.1")
    assert [p["id"] for p in api.get("/api/plants").json()["plants"]] == ["alpha", "beta"]


def test_the_cli_serves_one_plant_as_before_and_a_library_on_request(library: Path, monkeypatch):
    plant = library / "processes" / "alpha"
    single = _serve(monkeypatch, "--repo", str(plant / "pid"))
    assert single["result"].exit_code == 0, single["result"].output
    api = TestClient(single["app"], base_url="http://127.0.0.1")
    assert api.get("/api/repo").json()["name"] == "Plant alpha"
    assert api.get("/api/plants").status_code == 404
    # --library: the plants below, even inside one
    forced = _serve(monkeypatch, "--repo", str(library / "processes"), "--library")
    assert forced["result"].exit_code == 0
    assert "(2 plants)" in forced["result"].output


def test_the_cli_refuses_a_folder_with_no_plant(tmp_path: Path, monkeypatch):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert _serve(monkeypatch, "--repo", str(empty))["result"].exit_code == 2
    assert _serve(monkeypatch, "--repo", str(empty), "--library")["result"].exit_code == 2
