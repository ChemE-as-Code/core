"""``GET /api/lca``: the LCA of a revision, as ``cheme assess lca --json`` without the
source."""

import json
import shutil
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from chemeascode.domains.assessment.lca.report import lca_report
from chemeascode.interfaces.api.serve import create_app
from tests.conftest import git

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "process-blocks"
SCOPE = {
    "schema": "cheme/lca/v1",
    "kind": "lca",
    "functional_unit": {"product": "PROD", "amount": 1, "unit": "t"},
    "allocation": {"method": "none"},
    "flows": [
        {"key": "feed:FEED", "factor": "feed", "source": "test"},
        {"key": "feed:STEAM", "factor": "steam", "source": "test"},
    ],
    "scenarios": [{"id": "2050", "factors": {"steam": "steam-2050"}, "source": "test"}],
}
FACTORS = {
    "schema": "cheme/lca/v1",
    "kind": "lca_factors",
    "example": True,
    "categories": [{"id": "gwp", "unit": "kg CO2-eq"}],
    "factors": [
        {
            "id": i,
            "unit": u,
            "values": {"gwp": v},
            "status": "ASSUMED",
            "source": "test",
            "year": 2025,
        }
        for i, u, v in (("feed", "kg", 0.5), ("steam", "MJ", 0.07), ("steam-2050", "MJ", 0.01))
    ],
}


def _commit(root: Path, message: str) -> None:
    git(root, "add", "-A")
    git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", message)


@pytest.fixture
def plant(tmp_path: Path) -> Path:
    root = tmp_path / "plant"
    shutil.copytree(EXAMPLE, root)
    git(root, "init", "-q", "-b", "main")
    _commit(root, "process")
    return root


def _write(root: Path, scope: dict) -> None:
    (root / "lca").mkdir(exist_ok=True)
    (root / "lca" / "lca.yaml").write_text(yaml.safe_dump(scope, sort_keys=False))
    (root / "lca" / "factors.yaml").write_text(yaml.safe_dump(FACTORS, sort_keys=False))


def client(root: Path) -> TestClient:
    return TestClient(create_app(root, allowed_hosts=["testserver"]))


def test_lca_matches_the_report(plant: Path) -> None:
    api = client(plant)
    assert api.get("/api/lca").status_code == 404
    assert api.get("/api/repo").json()["has_lca"] is False
    _write(plant, SCOPE)
    _commit(plant, "lca")
    assert api.get("/api/repo").json()["has_lca"] is True
    data = api.get("/api/lca").json()
    expected = json.loads(json.dumps(lca_report(plant).payload()))
    assert {k: v for k, v in data.items() if k not in ("rev", "findings")} == expected
    assert data["rev"] is None
    assert data["totals"]["gwp"] == pytest.approx(1250 + 220.5)
    assert data["scenarios"]["2050"]["gwp"] == pytest.approx(1250 + 31.5)
    assert data["scenario_ids"] == ["baseline", "2050"]
    rules = {f["rule"] for f in data["findings"]}
    assert {"cheme.lca-unmapped", "cheme.lca-example-factors"} <= rules
    # the boundary check, as in /api/tea: the blocks' products have no category
    assert data["boundary_check"]["complete"] is False
    assert "cheme.boundary-unclassified" in rules


def test_lca_at_a_revision_and_errors(plant: Path) -> None:
    _write(plant, SCOPE)
    _commit(plant, "lca")
    head = git(plant, "rev-parse", "HEAD").strip()
    _write(plant, {**SCOPE, "functional_unit": {"product": "BOGUS"}})
    api = client(plant)
    broken = api.get("/api/lca")
    assert broken.status_code == 422
    assert "BOGUS" in broken.json()["error"]
    at_head = api.get("/api/lca", params={"rev": head}).json()
    assert at_head["rev"] == head and at_head["functional_unit"] == "1 t PROD"


def test_lca_bad_inputs_are_422_or_404(plant: Path) -> None:
    api = client(plant)
    _write(plant, SCOPE)
    (plant / "lca" / "lca.yaml").write_bytes(b"schema: \xff\xfe\n")
    bad = api.get("/api/lca")
    assert bad.status_code == 422 and "cannot be read" in bad.json()["error"]
    _write(
        plant,
        {
            **SCOPE,
            "operation": {"hours_per_year": 8000, "life_years": 20},
            "construction": [
                {
                    "id": "steel",
                    "takeoff": "mto",
                    "category": "steel",
                    "factor": "feed",
                    "source": "test",
                }
            ],
        },
    )
    (plant / "estimate").mkdir()
    (plant / "estimate" / "mto.csv").write_text("foo,bar\n1,2\n")
    bad = api.get("/api/lca")
    assert bad.status_code == 422
    # the file is named once, not as a prefix of its own message
    assert bad.json()["error"].startswith("estimate/mto.csv cannot be read as a take-off")
    factors = {**FACTORS, "factors": [{**FACTORS["factors"][0], "values": {"gwp": float("inf")}}]}
    _write(plant, SCOPE)
    (plant / "lca" / "factors.yaml").write_text(yaml.safe_dump(factors))
    bad = api.get("/api/lca")
    assert bad.status_code == 422 and bad.json()["error"].startswith("lca/factors.yaml")
    # a revision without plant.yaml
    _write(plant, SCOPE)
    git(plant, "rm", "-q", "plant.yaml")
    _commit(plant, "no plant.yaml")
    head = git(plant, "rev-parse", "HEAD").strip()
    assert api.get("/api/lca", params={"rev": head}).status_code == 404


def test_lca_brightway_is_not_cached(plant: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from chemeascode.domains.assessment.lca import report as module

    calls = []
    real = module.lca_report

    def counted(root):
        calls.append(root)
        return real(root)

    monkeypatch.setattr(module, "lca_report", counted)
    _write(plant, SCOPE)
    api = client(plant)
    api.get("/api/lca")
    api.get("/api/lca")
    assert len(calls) == 1  # factors: cached by the files' blob ids
    bw = {
        **SCOPE,
        "backend": "brightway",
        "brightway": {"project": "nope", "categories": [{"id": "gwp", "method": ["m"]}]},
        "flows": [
            {**f, "activity": {"database": "d", "name": f["factor"]}} for f in SCOPE["flows"]
        ],
    }
    _write(plant, bw)
    first = api.get("/api/lca")
    api.get("/api/lca")
    assert first.status_code == 422
    assert len(calls) == 3  # brightway: computed every time


def test_lca_resolves_referenced_datasets(plant: Path) -> None:
    dataset = {
        "schema": "cheme/lca/v1",
        "kind": "lci_dataset",
        "id": "feedstock",
        "exchanges": [
            {"key": "product:FEEDSTOCK", "type": "product", "amount": 1.0, "unit": "kg"},
            {
                "key": "feed:X",
                "type": "input",
                "amount": 2.0,
                "unit": "kg",
                "link": {"factor": "feed", "source": "test"},
            },
        ],
    }
    (plant / "lca" / "datasets").mkdir(parents=True)
    (plant / "lca" / "datasets" / "feedstock.yaml").write_text(yaml.safe_dump(dataset))
    scope = {**SCOPE, "scenarios": []}
    scope["flows"] = [
        {
            "key": "feed:FEED",
            "dataset": {"path": "lca/datasets/feedstock.yaml", "product": "FEEDSTOCK"},
            "source": "test",
        },
        SCOPE["flows"][1],
    ]
    _write(plant, scope)
    _commit(plant, "dataset")
    data = client(plant).get("/api/lca").json()
    # 2500 kg feed x 2 kg x 0.5, plus the steam
    assert data["totals"]["gwp"] == pytest.approx(2500 + 220.5)
    assert data["allocation"]["comparison"] == []  # one product: nothing to compare
