import json
import os
import shutil
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from chemeascode.domains.piping.fmt import format_file
from chemeascode.interfaces.api.serve import create_app
from chemeascode.interfaces.cli import app as cli_app
from chemeascode.templates.install import init
from tests.conftest import REFERENCE, git

SHEET = "pid/P-01.xml"


def client(root: Path, ui: Path | None = None) -> TestClient:
    return TestClient(create_app(root, ui, allowed_hosts=["testserver"]))


@pytest.fixture
def committed(plant: Path) -> Path:
    """The plant fixture, formatted (stable ids) and committed on main."""
    format_file(plant / SHEET)
    git(plant, "add", "-A")
    git(plant, "commit", "-q", "-m", "initial plant")
    return plant


def head(root: Path) -> str:
    return git(root, "rev-parse", "HEAD").strip()


def renumber_valve(root: Path) -> None:
    sheet = root / SHEET
    text = sheet.read_text(encoding="utf-8")
    assert "<String>C1</String>" in text
    sheet.write_text(text.replace("<String>C1</String>", "<String>C1A</String>", 1))


# -- repository -----------------------------------------------------------------


def test_repo(committed: Path):
    api = client(committed)
    data = api.get("/api/repo").json()
    assert data["name"] == "Test plant"
    assert data["root_name"] == "plant"
    assert data["branch"] == "main"
    assert data["head"] == head(committed)
    assert data["stage"] == "concept"
    assert [s["id"] for s in data["stages"]] == ["concept", "basic", "detail"]
    assert data["sheets"] == [{"id": "P-01", "file": SHEET, "title": "", "kind": "pid"}]
    assert data["dirty"] is False
    renumber_valve(committed)
    assert api.get("/api/repo").json()["dirty"] is True


def test_repo_at_a_revision_reads_plant_yaml_there(committed: Path):
    first = head(committed)
    plant_yaml = committed / "plant.yaml"
    plant_yaml.write_text(plant_yaml.read_text().replace("Test plant", "Renamed"))
    git(committed, "commit", "-qam", "rename")
    api = client(committed)
    assert api.get("/api/repo").json()["name"] == "Renamed"
    old = api.get("/api/repo", params={"rev": first}).json()
    assert old["name"] == "Test plant" and old["head"] == first


def test_repo_without_commits(plant: Path):
    api = client(plant)
    assert api.get("/api/repo").json()["head"] is None
    assert api.get("/api/branches").json() == []
    assert api.get("/api/log").json() == []


def test_branches(committed: Path):
    git(committed, "branch", "feat/x")
    branches = client(committed).get("/api/branches").json()
    assert {b["name"]: b["current"] for b in branches} == {"feat/x": False, "main": True}
    assert all(b["head"] == head(committed) for b in branches)


def test_log(committed: Path):
    first = head(committed)
    (committed / "DESIGN.md").write_text("# Design\n\nchanged\n")
    git(committed, "commit", "-qam", "design note")
    api = client(committed)
    log = api.get("/api/log").json()
    assert [e["subject"] for e in log] == ["design note", "initial plant"]
    assert log[1]["sha"] == first and first.startswith(log[1]["short"])
    assert log[0]["author"] == "Test" and "T" in log[0]["date"]
    assert len(api.get("/api/log", params={"limit": 1}).json()) == 1
    assert [e["subject"] for e in api.get("/api/log", params={"path": SHEET}).json()] == [
        "initial plant"
    ]
    assert [e["sha"] for e in api.get("/api/log", params={"rev": first}).json()] == [first]
    assert api.get("/api/log", params={"limit": 0}).status_code == 400


# -- tree and files ------------------------------------------------------------------


def test_tree(committed: Path):
    (committed / "build").mkdir(exist_ok=True)
    (committed / "build" / "P-01.svg").write_text("<svg/>")
    (committed / "notes.txt").write_text("new\n")
    api = client(committed)
    tree = {e["path"]: e for e in api.get("/api/tree").json()}
    assert tree[SHEET]["kind"] == "pid" and tree[SHEET]["type"] == "file"
    assert tree["pid"]["type"] == "dir"
    assert tree["plant.yaml"]["kind"] == "yaml"
    assert tree["AGENTS.md"]["kind"] == "markdown"
    assert tree["notes.txt"]["kind"] == "other"
    assert ".claude/settings.json" in tree and tree[".claude/settings.json"]["kind"] == "json"
    assert not any(p.startswith((".git/", "build")) or p == ".git" for p in tree)
    at_head = {e["path"] for e in api.get("/api/tree", params={"rev": "HEAD"}).json()}
    assert SHEET in at_head and "pid" in at_head and "notes.txt" not in at_head
    assert not any(p.startswith(".git/") for p in at_head)


def test_file(committed: Path):
    api = client(committed)
    response = api.get("/api/file", params={"path": "plant.yaml"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert 'name: "Test plant"' in response.text
    (committed / "plant.yaml").write_text("name: changed\n")
    assert api.get("/api/file", params={"path": "plant.yaml"}).text == "name: changed\n"
    at_head = api.get("/api/file", params={"path": "plant.yaml", "rev": "HEAD"}).text
    assert 'name: "Test plant"' in at_head


def test_file_errors(committed: Path):
    api = client(committed)
    (committed / "new.md").write_text("only in the working tree\n")
    assert api.get("/api/file", params={"path": "nope.txt"}).status_code == 404
    missing_at_rev = api.get("/api/file", params={"path": "new.md", "rev": "HEAD"})
    assert missing_at_rev.status_code == 404 and "error" in missing_at_rev.json()
    assert api.get("/api/file", params={"path": "pid"}).status_code == 400
    assert api.get("/api/file", params={"path": "pid", "rev": "HEAD"}).status_code == 400
    assert api.get("/api/file").status_code == 400  # path missing
    (committed / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR")
    binary = api.get("/api/file", params={"path": "logo.png"})
    assert binary.status_code == 400 and "binary" in binary.json()["error"]
    (committed / "latin1.txt").write_bytes("Gr\xfc\xdfe".encode("latin-1"))
    assert api.get("/api/file", params={"path": "latin1.txt"}).status_code == 400
    (committed / "big.txt").write_bytes(b"x" * (5 * 1024 * 1024 + 1))
    big = api.get("/api/file", params={"path": "big.txt"})
    assert big.status_code == 400 and "larger" in big.json()["error"]
    git(committed, "add", "logo.png", "big.txt")
    git(committed, "commit", "-qm", "binaries")
    assert api.get("/api/file", params={"path": "logo.png", "rev": "HEAD"}).status_code == 400
    assert api.get("/api/file", params={"path": "big.txt", "rev": "HEAD"}).status_code == 400


# -- P&IDs ----------------------------------------------------------------------------


def test_pid_svg_and_cache(committed: Path):
    fastapi_app = create_app(committed, allowed_hosts=["testserver"])
    api = TestClient(fastapi_app)
    response = api.get("/api/pid.svg", params={"path": SHEET})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert "default-src 'none'" in response.headers["content-security-policy"]
    assert 'id="Tank1"' in response.text
    # Same blob in the working tree and at HEAD: one cache entry.
    assert api.get("/api/pid.svg", params={"path": SHEET, "rev": "HEAD"}).text == response.text
    assert len(fastapi_app.state.svg_cache) == 1
    assert api.get("/api/pid.svg", params={"path": "pid/P-99.xml"}).status_code == 404


def test_pid_svg_unloadable_sheet(committed: Path):
    (committed / "pid" / "P-02.xml").write_text("<not-dexpi/>")
    response = client(committed).get("/api/pid.svg", params={"path": "pid/P-02.xml"})
    assert response.status_code == 422 and "pid/P-02.xml" in response.json()["error"]


def test_diff(committed: Path):
    fastapi_app = create_app(committed, allowed_hosts=["testserver"])
    api = TestClient(fastapi_app)
    renumber_valve(committed)
    data = api.get("/api/diff", params={"path": SHEET, "old": "HEAD"}).json()
    assert data["path"] == SHEET and data["old_rev"] == "HEAD"
    assert data["new_rev"] == "working tree"
    modified = [c for c in data["changes"] if c["kind"] == "modified"]
    assert [c["object_id"] for c in modified] == ["GlobeValve2"]
    assert set(modified[0]) == {
        "kind",
        "object_type",
        "object_id",
        "tag",
        "domain",
        "detail",
        "item",
    }
    assert modified[0]["item"] == "GlobeValve2"
    assert data["items"]["GlobeValve2"] == {"class": "GlobeValve", "tag": "C1A"}
    assert data["new_highlight"] == {"GlobeValve2": "modified"}
    assert "<svg" in data["old_svg"] and "<svg" in data["new_svg"]
    assert "C1A" in data["projection_diff"]
    api.get("/api/diff", params={"path": SHEET, "old": "HEAD"})
    assert len(fastapi_app.state.diff_cache) == 1
    same = api.get("/api/diff", params={"path": SHEET, "old": "HEAD", "new": "HEAD"}).json()
    assert same["changes"] == [] and same["projection_diff"] == ""


def test_diff_added_sheet_and_missing(committed: Path):
    shutil.copy(committed / SHEET, committed / "pid" / "P-02.xml")
    api = client(committed)
    added = api.get("/api/diff", params={"path": "pid/P-02.xml"}).json()
    assert added["old_svg"] == "" and "<svg" in added["new_svg"]
    assert added["status"] == "added"
    assert added["changes"] and {c["kind"] for c in added["changes"]} == {"added"}
    assert added["new_highlight"] and added["new_owner"]
    assert api.get("/api/diff", params={"path": "pid/P-99.xml"}).status_code == 404


def test_diff_of_a_sheet_that_does_not_load_or_draw_stays_422(committed: Path):
    from tests.test_diffview import _dangling_shape

    content = (committed / SHEET).read_bytes()
    api = client(committed)
    for name, broken in (("P-02.xml", content[:5000]), ("P-03.xml", _dangling_shape(content))):
        (committed / "pid" / name).write_bytes(broken)
        response = api.get("/api/diff", params={"path": f"pid/{name}"})
        assert response.status_code == 422, response.text
        assert response.json()["error"].startswith(f"pid/{name}: cannot ")


# -- YAML, validation, checks ---------------------------------------------------------


def test_yaml(committed: Path):
    api = client(committed)
    plant = api.get("/api/yaml", params={"path": "plant.yaml"}).json()
    assert plant["kind"] == "plant" and plant["data"]["name"] == "Test plant"
    assert plant["schema"]["title"] == "PlantConfig"
    equipment = api.get("/api/yaml", params={"path": "equipment/equipment-list.yaml"}).json()
    assert equipment["kind"] == "equipment"
    assert equipment["schema"]["title"] == "EquipmentList"
    (committed / "other.yaml").write_text("a: [1, 2]\nwhen: 2026-10-17\n")
    other = api.get("/api/yaml", params={"path": "other.yaml"}).json()
    assert other == {"data": {"a": [1, 2], "when": "2026-10-17"}, "kind": None, "schema": None}
    (committed / "broken.yaml").write_text("a: [1, 2\n")
    assert api.get("/api/yaml", params={"path": "broken.yaml"}).status_code == 422
    at_head = api.get("/api/yaml", params={"path": "plant.yaml", "rev": "HEAD"}).json()
    assert at_head["data"]["name"] == "Test plant"


def test_validate(committed: Path):
    data = client(committed).get("/api/validate").json()
    assert SHEET in data["files"]
    assert data["findings"], "the reference P&ID has warnings"
    assert {"file", "level", "rule", "message", "line", "ids", "hint", "id"} <= set(
        data["findings"][0]
    )


def run_checks_now(api: TestClient):
    session = api.get("/api/session").json()
    return api.post("/api/checks/run", headers={session["header"]: session["token"]})


def add_command_check(root: Path, command: str, check_id: str = "cmd") -> None:
    checks = root / "checks" / "checks.yaml"
    data = yaml.safe_load(checks.read_text())
    data["checks"].append(
        {
            "id": check_id,
            "title": "Command",
            "stage": "concept",
            "kind": "command",
            "command": command,
        }
    )
    checks.write_text(yaml.safe_dump(data))


def test_checks(committed: Path):
    api = client(committed)
    assert api.get("/api/checks").json() == {"checks": []}
    run = run_checks_now(api).json()
    assert {c["id"]: c["status"] for c in run["checks"]}["pids-valid"] == "pass"
    assert not (committed / "checks" / "status.json").exists()
    # A plain GET never runs commands.
    assert api.get("/api/checks", params={"run": 1}).status_code == 405
    status = {"checks": [{"id": "x", "title": "X", "stage": "concept", "status": "pass"}]}
    (committed / "checks" / "status.json").write_text(json.dumps(status))
    git(committed, "add", "checks/status.json")
    git(committed, "commit", "-qm", "status")
    (committed / "checks" / "status.json").write_text('{"checks": []}')
    assert api.get("/api/checks", params={"rev": "HEAD"}).json() == status
    assert api.get("/api/checks").json() == {"checks": []}


def test_running_checks_needs_the_session_token(committed: Path):
    add_command_check(committed, "touch PWNED")
    api = client(committed)
    assert api.post("/api/checks/run").status_code == 403
    assert api.post("/api/checks/run", headers={"X-Cheme-Token": "guess"}).status_code == 403
    assert not (committed / "PWNED").exists()
    assert run_checks_now(api).status_code == 200
    assert (committed / "PWNED").exists()
    # Every launch has its own token.
    assert client(committed).get("/api/session").json() != api.get("/api/session").json()


def test_command_checks_time_out(committed: Path, monkeypatch):
    import time

    import chemeascode.interfaces.api.serve as serve_module

    monkeypatch.setattr(serve_module, "CHECK_TIMEOUT", 0.5)
    add_command_check(committed, "sleep 30; touch LATE")
    started = time.monotonic()
    result = {c["id"]: c for c in run_checks_now(client(committed)).json()["checks"]}
    assert time.monotonic() - started < 10
    assert result["cmd"]["status"] == "fail" and "timed out" in result["cmd"]["detail"]


def test_only_one_check_run_at_a_time(committed: Path):
    import threading

    add_command_check(committed, "sleep 1")
    api = client(committed)
    statuses: list[int] = []
    threads = [
        threading.Thread(target=lambda: statuses.append(run_checks_now(api).status_code))
        for _ in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(statuses) == [200, 409]


def test_malformed_checks_yaml_is_a_json_422(committed: Path):
    (committed / "checks" / "checks.yaml").write_text("checks: [{id: 1, bogus: true}]\n")
    response = run_checks_now(client(committed))
    assert response.status_code == 422
    assert "checks/checks.yaml" in response.json()["error"]


def test_unexpected_errors_are_json(committed: Path, monkeypatch):
    import chemeascode.interfaces.api.serve as serve_module

    def boom(*_: object) -> None:
        raise RuntimeError("/secret/internal/path")

    monkeypatch.setattr(serve_module, "validate_workspace", boom)
    api = TestClient(
        create_app(committed, allowed_hosts=["testserver"]), raise_server_exceptions=False
    )
    response = api.get("/api/validate")
    assert response.status_code == 500
    assert response.json() == {"error": "internal error"}


def test_yaml_alias_bombs_and_non_json_values_are_refused(committed: Path):
    levels = ['a0: &a0 ["x","x","x","x","x","x","x","x","x","x"]']
    for i in range(1, 8):
        refs = ",".join([f"*a{i - 1}"] * 10)
        levels.append(f"a{i}: &a{i} [{refs}]")
    (committed / "bomb.yaml").write_text("\n".join(levels) + "\n")
    (committed / "rec.yaml").write_text("&a [*a]\n")
    (committed / "bin.yaml").write_text("x: !!binary /w==\n")
    (committed / "scalar.yaml").write_text("just a string\n")
    (committed / "alias.yaml").write_text("base: &b {x: 1}\nuse: *b\n")
    api = client(committed)
    for name in ("bomb.yaml", "rec.yaml", "bin.yaml", "scalar.yaml"):
        response = api.get("/api/yaml", params={"path": name})
        assert response.status_code == 422, (name, response.text)
        assert response.json()["error"].startswith(name)
    assert api.get("/api/yaml", params={"path": "alias.yaml"}).json()["data"] == {
        "base": {"x": 1},
        "use": {"x": 1},
    }
    # Only YAML files: an XML sheet is not returned as one big string.
    assert api.get("/api/yaml", params={"path": SHEET}).status_code == 422


def test_large_files_are_not_parsed(committed: Path, monkeypatch):
    import chemeascode.interfaces.api.serve as serve_module

    monkeypatch.setattr(serve_module, "MAX_FILE_BYTES", 100)
    api = client(committed)
    for endpoint in ("/api/yaml", "/api/pid.svg", "/api/diff"):
        path = "plant.yaml" if endpoint == "/api/yaml" else SHEET
        response = api.get(endpoint, params={"path": path})
        assert response.status_code == 400, endpoint
        assert "larger than" in response.json()["error"]
    # the recorded check results too (pre-release issue 257)
    (committed / "checks" / "status.json").write_text(json.dumps({"checks": [], "pad": "x" * 200}))
    response = api.get("/api/checks")
    assert response.status_code == 400 and "larger than" in response.json()["error"]


def test_sheets_outside_the_repository_are_not_read(committed: Path):
    (committed.parent / "outside").mkdir()
    (committed.parent / "outside" / "s.xml").write_text("<Model/>")
    plant_yaml = committed / "plant.yaml"
    data = yaml.safe_load(plant_yaml.read_text())
    data["sheets"] = [
        {"id": "P-01", "file": SHEET},
        {"id": "X", "file": "../outside/s.xml"},
        {"id": "H", "file": "/etc/hosts"},
    ]
    plant_yaml.write_text(yaml.safe_dump(data))
    report = client(committed).get("/api/validate").json()
    assert SHEET in report["files"]
    assert not any("outside" in f or "hosts" in f for f in report["files"])
    outside = [f for f in report["findings"] if f["rule"] == "cheme.sheet-outside-repo"]
    assert len(outside) == 2
    assert not any(str(committed) in f["message"] for f in report["findings"])
    assert {f["file"] for f in report["findings"]} <= set(report["files"]) | {"plant.yaml"}


def test_files_check_patterns_stay_inside(committed: Path):
    from chemeascode.foundation.workspace import Workspace
    from chemeascode.project.checks import run_checks

    checks = committed / "checks" / "checks.yaml"
    data = yaml.safe_load(checks.read_text())
    data["checks"] = [
        {"id": "up", "title": "Up", "stage": "concept", "kind": "files", "files": ["../*"]},
        {"id": "ok", "title": "Ok", "stage": "concept", "kind": "files", "files": ["pid/*.xml"]},
    ]
    checks.write_text(yaml.safe_dump(data))
    result = {r.id: r for r in run_checks(Workspace(committed))}
    assert result["up"].status == "fail" and "leaves the repository" in result["up"].detail
    assert result["ok"].status == "pass"


def test_diff_with_empty_old_means_head(committed: Path):
    renumber_valve(committed)
    data = client(committed).get("/api/diff", params={"path": SHEET, "old": ""}).json()
    assert data["old_rev"] == "HEAD" and data["changes"]


# -- security ---------------------------------------------------------------------------

TRAVERSALS = [
    "../outside.txt",
    "pid/../../outside.txt",
    "/etc/passwd",
    ".git/config",
    ".GIT/config",
    "pid/.git/x",
    "pid/./P-01.xml",
    "pid//P-01.xml",
    "pid\\P-01.xml",
]


@pytest.mark.parametrize("path", TRAVERSALS)
@pytest.mark.parametrize("rev", [None, "HEAD"])
def test_path_traversal_is_refused(committed: Path, path: str, rev: str | None):
    (committed.parent / "outside.txt").write_text("secret\n")
    api = client(committed)
    params = {"path": path, **({"rev": rev} if rev else {})}
    for endpoint in ("/api/file", "/api/pid.svg", "/api/yaml"):
        response = api.get(endpoint, params=params)
        assert response.status_code == 400, (endpoint, path, response.text)
        assert "error" in response.json()
    assert api.get("/api/diff", params={"path": path}).status_code == 400
    assert api.get("/api/log", params={"path": path}).status_code == 400


def test_symlinks_escaping_the_root_are_refused(committed: Path):
    outside = committed.parent / "outside.txt"
    outside.write_text("secret\n")
    os.symlink(outside, committed / "leak.txt")
    os.symlink(committed / ".git" / "config", committed / "gitconfig")
    os.symlink(committed.parent, committed / "up")
    os.symlink(committed / "plant.yaml", committed / "alias.yaml")
    api = client(committed)
    for path in ("leak.txt", "gitconfig", "up/outside.txt"):
        response = api.get("/api/file", params={"path": path})
        assert response.status_code == 400, (path, response.text)
        assert "secret" not in response.text
    assert api.get("/api/file", params={"path": "alias.yaml"}).status_code == 200
    tree = {e["path"] for e in api.get("/api/tree").json()}
    assert "alias.yaml" in tree
    assert not tree & {"leak.txt", "gitconfig", "up"}
    # Committed, a symlink is a blob holding the target path: not served as a file.
    git(committed, "add", "leak.txt")
    git(committed, "commit", "-qm", "symlink")
    assert api.get("/api/file", params={"path": "leak.txt", "rev": "HEAD"}).status_code == 400


@pytest.mark.parametrize("rev", ["--output=x", "-h", "-", "--all", "HEAD\nmain", "a" * 300])
def test_rev_injection_is_refused(committed: Path, rev: str):
    api = client(committed)
    for endpoint, params in (
        ("/api/file", {"path": "plant.yaml", "rev": rev}),
        ("/api/repo", {"rev": rev}),
        ("/api/log", {"rev": rev}),
        ("/api/tree", {"rev": rev}),
        ("/api/diff", {"path": SHEET, "old": rev}),
        ("/api/diff", {"path": SHEET, "new": rev}),
    ):
        response = api.get(endpoint, params=params)
        assert response.status_code == 400, (endpoint, rev, response.text)
    assert not (committed / "x").exists()


def test_unknown_revision_is_404(committed: Path):
    api = client(committed)
    response = api.get("/api/file", params={"path": "plant.yaml", "rev": "no-such-branch"})
    assert response.status_code == 404 and "unknown revision" in response.json()["error"]
    tree_sha = git(committed, "rev-parse", "HEAD^{tree}").strip()
    assert api.get("/api/tree", params={"rev": tree_sha}).status_code == 404  # not a commit


def test_foreign_host_header_is_refused(committed: Path):
    api = client(committed)
    refused = api.get("/api/repo", headers={"host": "evil.example"})
    assert refused.status_code == 400
    assert refused.json() == {"error": "invalid Host header"}


def test_local_host_headers_are_accepted(committed: Path):
    api = TestClient(create_app(committed))
    for host in ("127.0.0.1:8765", "localhost", "[::1]:8765"):
        assert api.get("/api/repo", headers={"host": host}).status_code == 200, host
    assert api.get("/api/repo", headers={"host": "127.0.0.1.evil.example"}).status_code == 400
    local = TestClient(create_app(committed), base_url="http://127.0.0.1:8765")
    assert local.get("/api/repo").status_code == 200


@pytest.mark.parametrize(
    "headers",
    [
        {"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"},
        {"Origin": "https://evil.example"},
        {"Origin": "null"},
        {"Sec-Fetch-Site": "cross-site"},
        {"Sec-Fetch-Site": "same-site"},
    ],
)
def test_cross_site_requests_are_refused(committed: Path, headers: dict[str, str]):
    add_command_check(committed, "touch PWNED")
    api = client(committed)
    for method, url in (("GET", "/api/checks?run=1"), ("POST", "/api/checks/run")):
        response = api.request(method, url, headers=headers)
        assert response.status_code == 403, (url, response.text)
        assert "error" in response.json()
    assert api.get("/api/session", headers=headers).status_code == 403
    assert api.get("/api/repo", headers=headers).status_code == 403
    assert not (committed / "PWNED").exists()


def test_same_origin_requests_are_accepted(committed: Path):
    api = client(committed)
    same = {"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"}
    assert api.get("/api/repo", headers=same).status_code == 200
    assert api.get("/api/repo", headers={"Sec-Fetch-Site": "none"}).status_code == 200


# -- the viewer ---------------------------------------------------------------------------


def test_spa_fallback(committed: Path, tmp_path: Path):
    ui = tmp_path / "dist"
    (ui / "assets").mkdir(parents=True)
    (ui / "index.html").write_text("<!doctype html><title>viewer</title>")
    (ui / "assets" / "app.js").write_text("console.log('viewer')")
    (tmp_path / "secret.txt").write_text("secret")
    api = client(committed, ui)
    assert "viewer" in api.get("/").text
    script = api.get("/assets/app.js")
    assert script.status_code == 200 and "javascript" in script.headers["content-type"]
    assert "<title>viewer" in api.get("/sheets/P-01").text
    assert "<title>viewer" in api.get("/pid/pid/P-01.xml").text
    assert api.get("/assets/missing.js").status_code == 404
    assert "secret" not in api.get("/%2e%2e/secret.txt").text
    unknown = api.get("/api/nope")
    assert unknown.status_code == 404 and "error" in unknown.json()
    assert api.get("/api/repo").json()["name"] == "Test plant"


def test_the_viewer_may_be_framed_only_by_itself(committed: Path, tmp_path: Path):
    """pre-release issue 258: another site cannot frame the viewer and trick a click on "Run
    now"."""
    ui = tmp_path / "dist"
    (ui / "assets").mkdir(parents=True)
    (ui / "index.html").write_text("<!doctype html><title>viewer</title>")
    (ui / "assets" / "app.js").write_text("console.log('viewer')")
    api = client(committed, ui)
    for url in ("/", "/checks", "/checks?embed=1", "/assets/app.js"):
        response = api.get(url)
        assert response.status_code == 200, url
        assert response.headers["content-security-policy"] == "frame-ancestors 'self'", url
        assert response.headers["x-frame-options"] == "SAMEORIGIN", url


def test_no_ui(committed: Path):
    response = client(committed).get("/")
    assert response.status_code == 404 and "--ui" in response.json()["error"]


# -- layout and CLI -------------------------------------------------------------------------


def test_plant_in_a_subdirectory_of_the_git_repository(tmp_path: Path):
    outer = tmp_path / "outer"
    root = outer / "plants" / "one"
    init(root, "Nested")
    shutil.copy(REFERENCE, root / "pid" / "P-01.xml")
    (outer / "OUTER.md").write_text("outer\n")
    git(outer, "init", "-q", "-b", "main")
    git(outer, "config", "user.email", "test@example.org")
    git(outer, "config", "user.name", "Test")
    git(outer, "add", "-A")
    git(outer, "commit", "-qm", "nested")
    api = client(root)
    tree = {e["path"] for e in api.get("/api/tree", params={"rev": "HEAD"}).json()}
    assert (
        "plant.yaml" in tree and SHEET in tree and "OUTER.md" not in tree and "plants" not in tree
    )
    assert "Nested" in api.get("/api/file", params={"path": "plant.yaml", "rev": "HEAD"}).text
    assert api.get("/api/repo", params={"rev": "HEAD"}).json()["sheets"][0]["file"] == SHEET
    # The log without a path lists only commits that touch the plant.
    (outer / "OUTER.md").write_text("changed\n")
    git(outer, "commit", "-qam", "outer only")
    assert [e["subject"] for e in api.get("/api/log").json()] == ["nested"]


# -- binding to the network (pre-release issue 191) ------------------------------------------------


def test_accepted_hosts():
    from chemeascode.interfaces.api.serve import accepted_hosts

    local = ["127.0.0.1", "::1", "localhost"]
    assert accepted_hosts("127.0.0.1") == local
    # a wildcard bind names no host: only the local names and the allowed ones, never "*"
    assert accepted_hosts("0.0.0.0") == local
    assert accepted_hosts("::", ["Box.lan", "192.168.1.5"]) == sorted(
        [*local, "box.lan", "192.168.1.5"]
    )
    assert accepted_hosts("192.168.1.5") == sorted([*local, "192.168.1.5"])
    for bad in ("*", "*.lan", ""):
        with pytest.raises(ValueError, match="wildcard"):
            accepted_hosts("0.0.0.0", [bad])
    # every spelling of the unspecified address is a wildcard
    assert accepted_hosts("0:0:0:0:0:0:0:0") == local
    # an IPv6 address may be given in brackets; a port can never match a Host name
    assert "fe80::1" in accepted_hosts("::", ["[fe80::1]"])
    for bad in ("box.lan:8765", "[fe80::1]:8765", "box.lan/x"):
        with pytest.raises(ValueError, match="no port"):
            accepted_hosts("0.0.0.0", [bad])


def _served(committed: Path, monkeypatch, *args: str) -> dict:
    calls: dict = {}
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: calls.update(app=app, **kwargs))
    result = CliRunner().invoke(cli_app, ["serve", "--repo", str(committed), *args])
    assert result.exit_code == 0, result.output
    calls["output"] = result.output
    return calls


def test_a_wildcard_bind_refuses_other_host_names(committed: Path, monkeypatch):
    add_command_check(committed, f"touch {committed / 'RAN'}")
    app = _served(committed, monkeypatch, "--host", "0.0.0.0")["app"]
    # a page whose name was rebound to this machine (DNS rebinding)
    evil = TestClient(app, base_url="http://evil.example:8765")
    same_origin = {"Origin": "http://evil.example:8765", "Sec-Fetch-Site": "same-origin"}
    for method, url in (("get", "/api/session"), ("get", "/api/file"), ("post", "/api/checks/run")):
        response = getattr(evil, method)(url, params={"path": "plant.yaml"}, headers=same_origin)
        assert response.status_code == 400, url
        assert response.json() == {"error": "invalid Host header"}
    assert not (committed / "RAN").exists()
    # the machine itself still works
    assert TestClient(app, base_url="http://127.0.0.1").get("/api/repo").status_code == 200


def test_allowed_host_names_are_served(committed: Path, monkeypatch):
    calls = _served(committed, monkeypatch, "--host", "0.0.0.0", "--allow-host", "box.lan")
    assert "every file of the repository" in calls["output"]
    lan = TestClient(calls["app"], base_url="http://box.lan:8765")
    assert lan.get("/api/repo").status_code == 200
    # host names are case-insensitive
    assert lan.get("/api/repo", headers={"Host": "BOX.LAN:8765"}).status_code == 200
    assert lan.get("/api/repo", headers={"Host": "LOCALHOST:8765"}).status_code == 200
    assert lan.get("/api/repo", headers={"Host": "evil.example:8765"}).status_code == 400
    bad = CliRunner().invoke(
        cli_app, ["serve", "--repo", str(committed), "--host", "0.0.0.0", "--allow-host", "*"]
    )
    assert bad.exit_code == 2 and "wildcard" in bad.output


def test_a_network_bind_runs_no_checks_unless_allowed(committed: Path, monkeypatch):
    add_command_check(committed, f"touch {committed / 'RAN'}")
    app = _served(committed, monkeypatch, "--host", "0.0.0.0", "--allow-host", "box.lan")["app"]
    api = TestClient(app, base_url="http://box.lan:8765")
    session = api.get("/api/session")
    assert session.status_code == 403 and "--allow-remote-checks" in session.json()["error"]
    response = api.post("/api/checks/run", headers={"X-Cheme-Token": "guess"})
    assert response.status_code == 403 and "--allow-remote-checks" in response.json()["error"]
    assert not (committed / "RAN").exists()

    calls = _served(
        committed,
        monkeypatch,
        "--host",
        "0.0.0.0",
        "--allow-host",
        "box.lan",
        "--allow-remote-checks",
    )
    assert "run the command checks" in calls["output"]
    api = TestClient(calls["app"], base_url="http://box.lan:8765")
    assert run_checks_now(api).status_code == 200
    assert (committed / "RAN").exists()


def test_a_local_bind_runs_the_checks(committed: Path, monkeypatch):
    add_command_check(committed, f"touch {committed / 'RAN'}")
    app = _served(committed, monkeypatch)["app"]
    assert run_checks_now(TestClient(app, base_url="http://127.0.0.1:8765")).status_code == 200
    assert (committed / "RAN").exists()


def test_serve_command(committed: Path, monkeypatch):
    calls = {}
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: calls.update(app=app, **kwargs))
    result = CliRunner().invoke(cli_app, ["serve", "--repo", str(committed), "--port", "9999"])
    assert result.exit_code == 0, result.output
    assert calls["host"] == "127.0.0.1" and calls["port"] == 9999
    assert TestClient(calls["app"], base_url="http://127.0.0.1").get("/api/repo").status_code == 200
    missing_ui = CliRunner().invoke(
        cli_app, ["serve", "--repo", str(committed), "--ui", str(committed / "nope")]
    )
    assert missing_ui.exit_code == 2


def test_every_route_is_in_the_readme_table(plant: Path):
    """README's serve table is the endpoint contract the viewer relies on."""
    from fastapi.routing import APIRoute

    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    rows = {
        line.split("`")[1].split("?")[0] for line in readme.splitlines() if line.startswith("| `")
    }
    routes = {
        f"{method} {route.path}"
        for route in create_app(plant).routes
        if isinstance(route, APIRoute) and route.path.startswith("/api/")
        for method in route.methods
    }
    assert routes - rows == set()
