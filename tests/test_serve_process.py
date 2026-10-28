import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from chemeascode.interfaces.api.serve import create_app
from tests.conftest import git

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
FLOWSHEET = "process/flowsheet.yaml"


@pytest.fixture
def recycle(tmp_path: Path) -> Path:
    """The recycle example, committed on main."""
    root = tmp_path / "plant"
    shutil.copytree(EXAMPLES / "process-recycle", root, ignore=shutil.ignore_patterns("build"))
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "recycle")
    return root


def client(root: Path) -> TestClient:
    return TestClient(create_app(root, allowed_hosts=["testserver"]))


def test_repo_sheets_carry_their_kind(recycle: Path):
    sheets = client(recycle).get("/api/repo").json()["sheets"]
    assert [(s["id"], s["kind"], s["file"]) for s in sheets] == [
        ("BFD", "bfd", "process/BFD.xml"),
        ("PFD", "pfd", "process/PFD.xml"),
    ]


def test_streams(recycle: Path):
    data = client(recycle).get("/api/streams").json()
    assert data["case"] == "design" == data["default_case"]
    assert data["units"]["flow"] == "kg/h"
    streams = {s["id"]: s for s in data["streams"]}
    s1 = streams["S1"]
    assert s1["on_bfd"] is True and s1["from_block"] == "FEED" and s1["to_block"] == "MIX"
    flow = s1["properties"]["flow"]
    assert flow["value"] == 1000 and flow["unit"] == "kg/h" and flow["stale"] is False
    assert flow["provenance"] in ("given", "assumed")
    assert streams["S6"]["on_bfd"] is False  # internal to SEP
    assert streams["S5"]["properties"]["duty"] is None
    # BFD connections: one per boundary stream, internal streams have none.
    assert data["bfd_connections"]["S1"] == ["S1"]
    assert "S6" not in data["bfd_connections"]
    balances = {b["node"]: b for b in data["balances"]}
    assert balances["MIX"]["status"] == "ok" and balances["MIX"]["in_kg_h"] == 1500
    assert balances["SEP"]["title"]
    # Links with their status: no equipment list, so step links do not resolve.
    c1 = next(n for n in data["nodes"] if n["id"] == "C1")
    assert c1["kind"] == "step" and c1["block"] == "SEP"
    assert c1["links"][0]["ref"] == "C-101" and c1["links"][0]["resolved"] is False
    assert "equipment" in c1["links"][0]["problem"]


def test_streams_flag_an_imbalance_on_its_streams(recycle: Path):
    path = recycle / FLOWSHEET
    text = path.read_text(encoding="utf-8")
    assert "flow: {value: 600, provenance: assumed}" in text
    path.write_text(text.replace("flow: {value: 600,", "flow: {value: 700,", 1), encoding="utf-8")
    api = client(recycle)
    data = api.get("/api/streams").json()
    sep = next(b for b in data["balances"] if b["node"] == "SEP")
    assert sep["status"] == "imbalance" and sep["failing"]
    s5 = next(s for s in data["streams"] if s["id"] == "S5")
    assert "SEP" in s5["imbalance"]
    # The committed revision still balances.
    committed = api.get("/api/streams", params={"rev": "HEAD"}).json()
    assert next(b for b in committed["balances"] if b["node"] == "SEP")["status"] == "ok"


def test_streams_errors(recycle: Path, tmp_path: Path):
    api = client(recycle)
    unknown = api.get("/api/streams", params={"case": "turndown"})
    assert unknown.status_code == 422 and "design" in unknown.json()["error"]
    (recycle / FLOWSHEET).write_text("schema: cheme/process/v1\nkind: flowsheet\nunits: 3\n")
    broken = api.get("/api/streams")
    assert broken.status_code == 422 and FLOWSHEET in broken.json()["error"]
    (recycle / FLOWSHEET).unlink()
    assert api.get("/api/streams").status_code == 404


def test_yaml_kinds_of_the_process_files(recycle: Path):
    api = client(recycle)
    materials = api.get("/api/yaml", params={"path": "process/materials.yaml"}).json()
    assert materials["kind"] == "materials" and "components" in materials["schema"]["properties"]
    flowsheet = api.get("/api/yaml", params={"path": FLOWSHEET}).json()
    assert flowsheet["kind"] == "flowsheet" and "streams" in flowsheet["schema"]["properties"]
    assert flowsheet["data"]["streams"][0]["id"] == "S1"


def test_an_error_in_reactions_yaml_does_not_block_the_process_endpoints(recycle: Path):
    (recycle / "process/reactions.yaml").write_text("schema: cheme/reactions/v2\nkind: reactions\n")
    response = client(recycle).get("/api/streams")
    assert response.status_code == 200, response.text
    broken = (recycle / FLOWSHEET).read_text().replace("from: FEED.out", "from: NOWHERE.out")
    (recycle / FLOWSHEET).write_text(broken.replace("kind: flowsheet", "kind: nonsense"))
    assert client(recycle).get("/api/streams").status_code == 422


def test_a_bfd_sheet_over_the_size_cap_is_skipped(recycle: Path, monkeypatch):
    """pre-release issue 257: the drawn BFD is read through the size cap like every other file."""
    import chemeascode.interfaces.api.serve as serve_module

    assert client(recycle).get("/api/streams").json()["bfd_connections_from"] == "sheet"
    monkeypatch.setattr(serve_module, "MAX_FILE_BYTES", 100_000)  # BFD.xml is ~145 kB
    response = client(recycle).get("/api/streams")
    assert response.status_code == 200
    assert response.json()["bfd_connections_from"] == "flowsheet"
