"""``GET /api/estimate/equipment``: the equipment estimate of a revision, as ``cheme assess
equipment --json``, and ``has_equipment_estimate`` of ``/api/repo``."""

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from chemeascode.domains.assessment.equipment_cost import equipment_estimate
from chemeascode.interfaces.api.serve import create_app
from tests.conftest import git

LIST = "equipment/equipment-list.yaml"
ITEMS = [
    {
        "tag": "V-1",
        "type": "PressureVessel",
        "design_pressure_barg": 10,
        "material": "CS",
        "dimensions": {"diameter": 2.0, "height": 3.1830989},
    },
    {"tag": "C-1", "type": "ProcessColumn", "design_pressure_barg": 1, "material": "CS"},
]
SHEET = {"tag": "C-1", "type_specific": {"volume_m3": {"value": 30.0, "source": "SN-1"}}}


def client(root: Path) -> TestClient:
    return TestClient(create_app(root, allowed_hosts=["testserver"]))


def head(root: Path) -> str:
    return git(root, "rev-parse", "HEAD").strip()


def commit(root: Path, message: str) -> None:
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", message)


def write_estimate_inputs(root: Path) -> None:
    (root / LIST).write_text(yaml.safe_dump({"equipment": ITEMS}), encoding="utf-8")
    (root / "equipment" / "datasheets" / "C-1.yaml").write_text(
        yaml.safe_dump(SHEET), encoding="utf-8"
    )
    (root / "estimate" / "cost-basis.yaml").write_text(
        "cost_index: {value: 794, year: 2030, source: test}\n", encoding="utf-8"
    )


@pytest.fixture
def committed(plant: Path) -> Path:
    """The template plant (an empty equipment list), committed."""
    commit(plant, "initial plant")
    return plant


def test_an_empty_equipment_list_has_nothing_to_estimate(committed: Path):
    api = client(committed)
    assert api.get("/api/repo").json()["has_equipment_estimate"] is False
    answer = api.get("/api/estimate/equipment")
    assert answer.status_code == 404
    assert answer.json() == {"error": f"nothing to estimate: no items in {LIST}"}


def test_no_equipment_list_is_404(committed: Path):
    (committed / LIST).unlink()
    api = client(committed)
    assert api.get("/api/repo").json()["has_equipment_estimate"] is False
    answer = api.get("/api/estimate/equipment")
    assert answer.status_code == 404
    assert answer.json() == {"error": f"no {LIST} at working tree"}


def test_the_estimate_at_a_revision_is_the_command_s(committed: Path):
    first = head(committed)
    write_estimate_inputs(committed)
    commit(committed, "equipment")
    api = client(committed)
    assert api.get("/api/repo").json()["has_equipment_estimate"] is True
    assert api.get("/api/repo", params={"rev": first}).json()["has_equipment_estimate"] is False

    data = api.get("/api/estimate/equipment", params={"rev": "HEAD"}).json()
    expected = equipment_estimate(committed).payload()
    assert data["rev"] == head(committed)
    assert {k: v for k, v in data.items() if k not in ("rev", "source")} == {
        k: v for k, v in expected.items() if k != "source"
    }
    assert data["source"] == expected["source"]
    assert data["source"]["commit"] == head(committed) and data["source"]["dirty"] == []
    assert data["totals"]["items"] == 2 and data["index"]["value"] == 794
    (column,) = [line for line in data["lines"] if line["tag"] == "C-1"]
    assert column["size_source"] == "datasheet type_specific.volume_m3 (SN-1)"
    assert {"currency", "base", "estimate_class", "accuracy", "own_costs", "findings"} <= set(data)

    # the revision before the list had items: nothing to estimate
    older = api.get("/api/estimate/equipment", params={"rev": first})
    assert older.status_code == 404

    # the working tree, with an uncommitted change: rev null, the changed file dirty
    (committed / "estimate" / "cost-basis.yaml").write_text(
        "cost_index: {value: 397, year: 2001, source: test}\n", encoding="utf-8"
    )
    now = api.get("/api/estimate/equipment").json()
    assert now["rev"] is None and now["index"]["value"] == 397
    assert now["source"]["dirty"] == ["estimate/cost-basis.yaml"]
    assert now["source"] == equipment_estimate(committed).payload()["source"]
    # the committed revision still answers as committed (the cache keys on the inputs)
    again = api.get("/api/estimate/equipment", params={"rev": "HEAD"}).json()
    assert again["index"]["value"] == 794


def test_a_list_that_does_not_load_is_422(committed: Path):
    (committed / LIST).write_text("equipment:\n  - {tag: V-1, unknown_field: 1}\n")
    api = client(committed)
    assert api.get("/api/repo").json()["has_equipment_estimate"] is True
    answer = api.get("/api/estimate/equipment")
    assert answer.status_code == 422
    assert answer.json()["error"].startswith(f"{LIST}: ")


def test_a_cost_basis_that_does_not_load_is_a_finding(committed: Path):
    (committed / LIST).write_text(yaml.safe_dump({"equipment": ITEMS[:1]}), encoding="utf-8")
    (committed / "estimate" / "cost-basis.yaml").write_text("cost_index: [", encoding="utf-8")
    data = client(committed).get("/api/estimate/equipment").json()
    assert data["findings"][0]["rule"] == "cheme.estimate-cost-basis"
    assert data["totals"]["items"] == 1


def test_inputs_count_as_uncommitted_when_git_cannot_tell(committed: Path, monkeypatch):
    from chemeascode.foundation import gitinfo

    write_estimate_inputs(committed)
    commit(committed, "equipment")
    monkeypatch.setattr(gitinfo, "dirty_paths", lambda root: None)
    api = client(committed)
    source = api.get("/api/estimate/equipment").json()["source"]
    assert source["dirty"] and set(source["dirty"]) >= {LIST, "estimate/cost-basis.yaml"}
    # a commit identifies its inputs without asking the working tree
    assert (
        api.get("/api/estimate/equipment", params={"rev": "HEAD"}).json()["source"]["dirty"] == []
    )
