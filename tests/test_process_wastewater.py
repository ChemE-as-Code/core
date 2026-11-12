"""Saved wastewater columns cannot replace molecular properties or fabricate missing data."""

import copy
import json
import shutil
from pathlib import Path

import pytest
import yaml

from chemeascode.domains.process.simulation import record
from chemeascode.domains.process.simulation.qsdsan import fingerprint
from chemeascode.domains.process.wastewater import COLUMNS, stream_table
from chemeascode.foundation.provenance import source_revision
from chemeascode.integrations import qsdsan


@pytest.fixture
def sample():
    table = {
        "case": "design",
        "units": {"flow": "kg/h"},
        "balances": [{"status": "not-evaluable"}],
        "streams": [
            {
                "id": "S1",
                "kind": "material",
                "properties": {"flow": {"value": 999, "unit": "kg/h"}},
                "stale": [],
            }
        ],
    }
    run = {
        "case": "design",
        "simulator": {"name": "QSDsan"},
        "status": "converged",
        "integration_completed": True,
        "streams": [
            {
                "id": "S1",
                "values": {k: {"value": i, "unit": u} for i, (k, _, u, _) in enumerate(COLUMNS)},
            }
        ],
        "units": [],
    }
    return table, {
        "case": "design",
        "spec": {"simulator": "qsdsan"},
        "run": run,
        "stale": False,
    }


def test_projection_preserves_units_zero_and_original_table(sample):
    table, sim = sample
    before = copy.deepcopy(table)
    result = stream_table(table, sim)
    assert table == before
    assert result["units"] == table["units"]
    assert result["balances"] == table["balances"]
    row = result["streams"][0]
    assert row["properties"] == table["streams"][0]["properties"]
    assert row["wastewater"]["flow"]["value"] == 0
    assert result["wastewater"]["status"] == "available"
    for key, _, unit, _ in COLUMNS:
        assert row["wastewater"][key]["unit"] == unit
        assert row["wastewater"][key]["provenance"] == "calculated"


@pytest.mark.parametrize("value", [None, True, "15", float("nan"), float("inf")])
def test_invalid_number_is_absent_not_zero(sample, value):
    table, sim = sample
    sim["run"]["streams"][0]["values"]["TN"]["value"] = value
    result = stream_table(table, sim)
    assert "TN" not in result["streams"][0]["wastewater"]
    assert result["wastewater"]["status"] == "partial"
    assert result["wastewater"]["findings"][0]["file"] == record.RUN_FILE


def test_wrong_basis_missing_cell_and_unknown_stream(sample):
    table, sim = sample
    sim["run"]["streams"][0]["values"]["TN"]["unit"] = "mg NH4/L"
    del sim["run"]["streams"][0]["values"]["TP"]
    sim["run"]["streams"].append({"id": "OLD", "values": {}})
    result = stream_table(table, sim)
    assert "TN" not in result["streams"][0]["wastewater"]
    assert "TP" not in result["streams"][0]["wastewater"]
    assert len(result["streams"]) == 1
    assert "OLD" in result["wastewater"]["findings"][-1]["message"]


@pytest.mark.parametrize("change", ["case", "solver", "failed", "duplicate", "missing", "invalid"])
def test_unusable_run_never_populates_cells(sample, change):
    table, sim = sample
    if change == "case":
        sim["run"]["case"] = "other"
    elif change == "solver":
        sim["run"]["simulator"]["name"] = "DWSIM"
    elif change == "failed":
        sim["run"]["status"] = "not-converged"
    elif change == "duplicate":
        sim["run"]["streams"] *= 2
    elif change == "missing":
        sim["run"] = None
    else:
        sim["problem"] = "invalid configuration"
    result = stream_table(table, sim)
    assert not result["streams"][0]["wastewater"]
    assert result["wastewater"]["status"] in {"invalid", "failed", "missing"}


def test_stale_values_are_flagged_and_other_simulators_unchanged(sample):
    table, sim = sample
    sim["stale"] = True
    sim["staleness"] = {"changed_files": ["inputs/baseline.json"]}
    result = stream_table(table, sim)
    assert result["streams"][0]["stale"] == ["wastewater"]
    assert result["streams"][0]["wastewater"]["TN"]["stale"]
    assert result["wastewater"]["changed_files"] == ["inputs/baseline.json"]
    sim["spec"]["simulator"] = "dwsim"
    assert stream_table(table, sim) is table


def test_api_is_read_only_and_refreshes_run_case_and_input_changes(tmp_path, sample, monkeypatch):
    from fastapi.testclient import TestClient

    from chemeascode.interfaces.api.serve import create_app

    root = tmp_path / "plant"
    shutil.copytree(Path(__file__).parent.parent / "examples/process-simulation", root)
    config = {
        "schema": "cheme/simulation/v1",
        "kind": "simulation",
        "simulator": "qsdsan",
        "qsdsan": {"model": "wwtp-a2o"},
    }
    (root / "process/simulation.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    (root / "inputs").mkdir()
    input_file = root / "inputs/baseline.json"
    input_file.write_text('{"case_id":"design"}', encoding="utf-8")
    hashes = source_revision(root, qsdsan.recipe_files(root, "inputs/baseline.json")).fingerprints
    entry = sample[1]["run"]
    entry.update(model_fingerprint=fingerprint(hashes), inputs={"fingerprints": hashes})
    record.write(root, entry)

    def forbidden(*args, **kwargs):
        pytest.fail("Reading the stream table must not execute a simulator")

    monkeypatch.setattr(qsdsan, "execute", forbidden)

    def files():
        return {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}

    before = files()
    with TestClient(create_app(root, allowed_hosts=["testserver"])) as client:
        response = client.get("/api/streams")
        assert response.status_code == 200, response.text
        view = response.json()
        s1 = next(s for s in view["streams"] if s["id"] == "S1")
        assert s1["wastewater"]["flow"]["value"] == 0
        assert view["wastewater"]["stale"] is False
        assert files() == before
        assert client.get("/api/streams?case=unknown").status_code == 422
        input_file.write_text("{}", encoding="utf-8")
        stale = client.get("/api/streams").json()
        assert stale["wastewater"]["stale"] is True
        assert "inputs/baseline.json" in stale["wastewater"]["changed_files"]
        record.write(root, {**entry, "status": "not-converged"})
        failed = client.get("/api/streams").json()
        assert failed["wastewater"]["status"] == "failed"
        assert all(not s["wastewater"] for s in failed["streams"])
        (root / record.RUN_FILE).write_text(json.dumps({"cases": {}}), encoding="utf-8")
        assert client.get("/api/streams").json()["wastewater"]["status"] == "missing"
