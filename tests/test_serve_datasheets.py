"""``GET /api/datasheets``, ``/api/datasheets/{tag}`` and ``/api/datasheets/{tag}.svg`` of a
revision, ``has_datasheets`` of ``/api/repo``, and their export by ``cheme export-static``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from chemeascode.interfaces.api.export_static import export_static
from chemeascode.interfaces.api.serve import create_app
from chemeascode.project.datasheets import datasheet_report, drawings
from tests.conftest import git

LIST = "equipment/equipment-list.yaml"
ITEMS = [
    {
        "tag": "V-1",
        "type": "PressureVessel",
        "service": "Buffer",
        "dimensions": {"diameter": 2.0, "height": 4.0, "head": "ellipsoidal_2_1"},
    },
    {"tag": "P4711", "type": "CentrifugalPump"},
]
SHEET = {
    "tag": "V-1",
    "type": "PressureVessel",
    "service": "Buffer",
    "dimensions": {
        "outside_diameter": {"value": 2.0, "unit": "m", "source": "list"},
        "overall_height": {"value": 4.0, "unit": "m", "source": "list"},
        "head": "ellipsoidal_2_1",
    },
    "weights": {"empty": {"value": "TBD", "unit": "t", "source": "TBD: vendor"}},
    "nozzles": [{"name": "N1", "dn": 50, "face": "top"}],
    "draft": True,
}


def client(root: Path) -> TestClient:
    return TestClient(create_app(root, allowed_hosts=["testserver"]))


def commit(root: Path, message: str) -> str:
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", message)
    return git(root, "rev-parse", "HEAD").strip()


def write(root: Path, rel: str, data: object) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


@pytest.fixture
def committed(plant: Path) -> Path:
    """The template plant (no datasheets), committed."""
    commit(plant, "initial plant")
    return plant


def test_no_datasheets_is_404(committed: Path):
    api = client(committed)
    assert api.get("/api/repo").json()["has_datasheets"] is False
    answer = api.get("/api/datasheets")
    assert answer.status_code == 404
    assert answer.json() == {"error": "no datasheets in equipment/datasheets at working tree"}


def test_index_entry_and_drawing_at_a_revision(committed: Path):
    first = git(committed, "rev-parse", "HEAD").strip()
    write(committed, LIST, {"equipment": ITEMS})
    write(committed, "equipment/datasheets/V-1.yaml", SHEET)
    second = commit(committed, "datasheet")
    api = client(committed)
    assert api.get("/api/repo").json()["has_datasheets"] is True
    assert api.get("/api/repo", params={"rev": first}).json()["has_datasheets"] is False
    assert api.get("/api/datasheets", params={"rev": first}).status_code == 404

    index = api.get("/api/datasheets", params={"rev": "HEAD"}).json()
    assert index["rev"] == second
    assert index["missing"] == ["P4711"]
    assert index["source"]["commit"] == second and index["source"]["dirty"] == []
    (entry,) = index["datasheets"]
    assert entry == {
        "tag": "V-1",
        "file": "equipment/datasheets/V-1.yaml",
        "valid": True,
        "type": "PressureVessel",
        "service": "Buffer",
        "draft": True,
        "counts": {"assumed": 0, "tbd": 1, "supplier": 0, "not_applicable": 0},
        "nozzles": 1,
        "has_dimensions": True,
        "has_weights": True,
        "drawing": "equipment/datasheets/V-1.svg",
        "has_drawing": False,
        "drawing_current": False,
        "findings": {"error": 0, "warning": 0, "info": 0},
    }
    # the same as the function on the working tree
    expected = datasheet_report(committed).index()
    assert index["datasheets"] == expected["datasheets"]

    detail = api.get("/api/datasheets/V-1", params={"rev": second}).json()
    assert detail["tag"] == "V-1" and detail["summary"] == entry
    assert detail["datasheet"]["dimensions"]["outside_diameter"]["value"] == 2.0
    assert detail["data"]["draft"] is True
    assert detail["drawing"] == {
        "file": "equipment/datasheets/V-1.svg",
        "state": "missing",
        "current": False,
    }
    assert detail["findings"] == []

    # no committed drawing: generated on the fly, and flagged
    svg = api.get("/api/datasheets/V-1.svg", params={"rev": second})
    assert svg.status_code == 200 and svg.headers["content-type"].startswith("image/svg+xml")
    assert svg.headers["x-cheme-drawing"] == "generated"
    assert "default-src 'none'" in svg.headers["content-security-policy"]
    text = svg.text
    assert "V-1" in text and ">DRAFT<" in text

    # committed drawing: served as committed, with whether it is current
    drawings(committed, write=True)
    third = commit(committed, "drawing")
    svg = api.get("/api/datasheets/V-1.svg", params={"rev": third})
    assert svg.headers["x-cheme-drawing"] == "committed"
    assert svg.headers["x-cheme-drawing-current"] == "true"
    assert svg.text == (committed / "equipment/datasheets/V-1.svg").read_text(encoding="utf-8")
    write(committed, "equipment/datasheets/V-1.yaml", {**SHEET, "service": "Buffer drum"})
    fourth = commit(committed, "service")
    svg = api.get("/api/datasheets/V-1.svg", params={"rev": fourth})
    assert svg.headers["x-cheme-drawing-current"] == "false"
    fresh = api.get("/api/datasheets/V-1.svg", params={"rev": fourth, "generated": "true"})
    assert fresh.headers["x-cheme-drawing"] == "generated" and "Buffer drum" in fresh.text
    detail = api.get("/api/datasheets/V-1", params={"rev": fourth}).json()
    assert detail["drawing"]["state"] == "stale"
    assert [f["rule"] for f in detail["findings"]] == ["cheme.datasheet-drawing-stale"]


def test_unknown_or_invalid_datasheets(committed: Path):
    write(committed, "equipment/datasheets/V-1.yaml", SHEET)
    write(committed, "equipment/datasheets/X-1.yaml", {"tag": "X-1", "bogus": 1})
    api = client(committed)
    assert api.get("/api/datasheets/NOPE").status_code == 404
    assert api.get("/api/datasheets/NOPE.svg").status_code == 404
    bad = api.get("/api/datasheets/X-1").json()
    assert bad["datasheet"] is None and bad["summary"]["valid"] is False
    assert bad["findings"][0]["rule"] == "yaml.schema"
    assert api.get("/api/datasheets/X-1.svg").status_code == 422
    assert api.get("/api/datasheets/V-1", params={"rev": "-x"}).status_code == 400


def test_datasheets_are_exported(committed: Path, tmp_path: Path):
    write(committed, "equipment/datasheets/V-1.yaml", SHEET)
    commit(committed, "datasheet")
    out = tmp_path / "snap"
    manifest = export_static(committed, out)
    entries = manifest["entries"]
    for key in ("datasheets", "datasheets/V-1", "datasheets/V-1.svg"):
        assert entries[key]["status"] == 200, key
    assert entries["datasheets/V-1.svg"]["type"] == "image/svg+xml"
    server = client(committed)
    for key in ("datasheets", "datasheets/V-1", "datasheets/V-1.svg"):
        stored = (out / "data" / entries[key]["file"]).read_bytes()
        assert stored == server.get(f"/api/{key}").content, key
    assert json.loads((out / "data" / entries["datasheets"]["file"]).read_bytes())["datasheets"]


def test_an_excluded_datasheet_is_not_exported(committed: Path, tmp_path: Path):
    write(committed, "equipment/datasheets/V-1.yaml", SHEET)
    write(committed, "equipment/datasheets/V-2.yaml", {**SHEET, "tag": "V-2"})
    commit(committed, "datasheets")
    out = tmp_path / "snap"
    manifest = export_static(committed, out, exclude=["equipment/datasheets/V-2.*"])
    entries = manifest["entries"]
    assert "datasheets/V-1" in entries and "datasheets/V-2" not in entries
    assert "datasheets/V-2.svg" not in entries
    index = json.loads((out / "data" / entries["datasheets"]["file"]).read_bytes())
    assert [s["tag"] for s in index["datasheets"]] == ["V-1"]


def test_an_excluded_datasheet_is_not_named_in_the_kept_answers(committed: Path, tmp_path: Path):
    write(committed, "equipment/datasheets/V-1.yaml", SHEET)
    write(committed, "equipment/datasheets/V-2.yaml", {**SHEET, "tag": "V-2"})
    commit(committed, "datasheets")
    out = tmp_path / "snap"
    manifest = export_static(committed, out, exclude=["equipment/datasheets/V-2.*"])
    entries = manifest["entries"]
    for key in ("datasheets", "datasheets/V-1"):
        answer = json.loads((out / "data" / entries[key]["file"]).read_bytes())
        fingerprints = answer["source"]["fingerprints"]
        assert "equipment/datasheets/V-1.yaml" in fingerprints, key  # the kept sheet stays
        assert not [p for p in fingerprints if "V-2" in p], key
        assert not [p for p in answer["source"]["dirty"] if "V-2" in p], key
    for stored in (out / "data").iterdir():
        assert b"datasheets/V-2" not in stored.read_bytes(), stored.name


def test_an_uncommitted_excluded_datasheet_is_not_named_as_dirty(committed: Path, tmp_path: Path):
    """``source.dirty`` lists uncommitted datasheets: an excluded one is left out of it, a kept
    one stays."""
    write(committed, "equipment/datasheets/V-1.yaml", SHEET)
    commit(committed, "datasheet")
    write(committed, "equipment/datasheets/V-1.yaml", {**SHEET, "service": "Buffer drum"})
    write(committed, "equipment/datasheets/V-2.yaml", {**SHEET, "tag": "V-2"})  # never committed
    served = client(committed).get("/api/datasheets").json()["source"]["dirty"]
    assert "equipment/datasheets/V-2.yaml" in served  # the filter has something to remove
    out = tmp_path / "snap"
    manifest = export_static(committed, out, exclude=["equipment/datasheets/V-2.*"])
    entries = manifest["entries"]
    assert manifest["source"]["dirty"] is True
    for key in ("datasheets", "datasheets/V-1"):
        answer = json.loads((out / "data" / entries[key]["file"]).read_bytes())
        assert answer["source"]["dirty"] == ["equipment/datasheets/V-1.yaml"], key
    for stored in (out / "data").iterdir():
        assert b"datasheets/V-2" not in stored.read_bytes(), stored.name
