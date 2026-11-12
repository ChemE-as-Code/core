"""The opt-in A2/O dispatcher, evidence contract, and read-only check/viewer behavior."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from chemeascode.domains.process.model import load as load_process
from chemeascode.domains.process.simulation import record
from chemeascode.domains.process.simulation.qsdsan import fingerprint
from chemeascode.domains.process.simulation.run import run
from chemeascode.domains.process.simulation.schema import Simulation
from chemeascode.domains.process.simulation.translate import load, translate
from chemeascode.foundation.provenance import source_revision
from chemeascode.foundation.workspace import Workspace
from chemeascode.integrations import qsdsan

CONFIG = {
    "schema": "cheme/simulation/v1",
    "kind": "simulation",
    "simulator": "qsdsan",
    "qsdsan": {"model": "wwtp-a2o"},
}


@pytest.fixture
def plant(tmp_path):
    root = tmp_path / "plant"
    shutil.copytree(Path(__file__).parent.parent / "examples/process-simulation", root)
    (root / "process/simulation.yaml").write_text(yaml.safe_dump(CONFIG), encoding="utf-8")
    (root / "inputs").mkdir()
    (root / "inputs/baseline.json").write_text('{"case_id":"design"}', encoding="utf-8")
    worker = root / "wwtp_a2o/interfaces/cli/cheme.py"
    worker.parent.mkdir(parents=True)
    worker.write_text("# worker fixture\n", encoding="utf-8")
    return Workspace(root)


def payload(root, status="converged"):
    evidence = root / "runs/fresh"
    evidence.mkdir(parents=True, exist_ok=True)
    return {
        "status": "completed",
        "run": str(evidence),
        "adapter": {
            "case": "design",
            "status": status,
            "solver": {"name": "QSDsan", "version": "test"},
            "units": [{"id": "A1", "status": "simulated"}],
            "streams": [
                {
                    "id": "EFFLUENT",
                    "filled": [],
                    "values": {"TN": {"value": 15.67, "unit": "mg N/L"}},
                }
            ],
        },
    }


def calculate(ws, write, **kwargs):
    process, _ = load_process(ws.root)
    return run(ws, process, "design", write=write, **kwargs)


def test_schema_preserves_dwsim_default_and_rejects_mixed_fields():
    assert (
        Simulation.model_validate({"schema": "cheme/simulation/v1", "kind": "simulation"}).simulator
        == "dwsim"
    )
    for fields in ({"property_package": "Peng-Robinson (PR)"}, {"specs": {}}, {"qsdsan": None}):
        with pytest.raises(ValidationError):
            Simulation.model_validate({**CONFIG, **fields})
    for value in (0, float("nan"), float("inf")):
        with pytest.raises(ValidationError):
            Simulation.model_validate(
                {**CONFIG, "qsdsan": {"model": "wwtp-a2o", "timeout_s": value}}
            )


def test_fill_dispatch_preserves_units_and_prior_evidence(plant, monkeypatch):
    from chemeascode.domains.process.simulation import qsdsan as domain

    old = plant.root / "runs/old/result.json"
    old.parent.mkdir(parents=True)
    old.write_text("original", encoding="utf-8")
    before = (plant.root / "process/flowsheet.yaml").read_bytes()
    response = payload(plant.root)
    monkeypatch.setattr(domain, "execute", lambda *a, **k: qsdsan.WorkerResult(response, "", "", 0))

    def no_molecular_audit(*args, **kwargs):
        pytest.fail("The dynamic A2/O worker must not enter the molecular energy audit")

    monkeypatch.setattr("chemeascode.domains.process.simulation.energy.audit", no_molecular_audit)
    result = calculate(plant, True)
    assert not result.findings
    saved = record.entry_of(record.read(plant.root), "design")
    assert saved["streams"][0]["values"]["TN"]["unit"] == "mg N/L"
    assert saved["streams"][0]["filled"] == []
    assert saved["integration_completed"] is True
    assert old.read_text() == "original"
    assert (plant.root / "process/flowsheet.yaml").read_bytes() == before
    assert (plant.root / "runs/fresh/cheme-simulation-entry.json").is_file()
    assert json.loads((plant.root / "runs/latest.json").read_text())["run_id"] == "fresh"


@pytest.mark.parametrize("failure", ["exit", "status", "case", "filled"])
def test_failed_or_mismatched_result_does_not_replace_last_run(plant, monkeypatch, failure):
    from chemeascode.domains.process.simulation import qsdsan as domain

    record.write(plant.root, {"case": "design", "marker": "old"})
    before = (plant.root / record.RUN_FILE).read_bytes()
    response = payload(plant.root)
    if failure == "status":
        response["adapter"]["status"] = "not-converged"
    elif failure == "case":
        response["adapter"]["case"] = "another"
    elif failure == "filled":
        response["adapter"]["streams"][0]["filled"] = ["composition"]
    monkeypatch.setattr(
        domain,
        "execute",
        lambda *a, **k: qsdsan.WorkerResult(response, "", "", int(failure == "exit")),
    )
    result = calculate(plant, True)
    assert any(f.level == "error" for f in result.findings)
    assert (plant.root / record.RUN_FILE).read_bytes() == before
    assert not (plant.root / "runs/latest.json").exists()


def test_check_stages_files_and_does_not_write_project(plant, monkeypatch):
    python = (
        plant.root / ".venv" / ("Scripts/python.exe" if qsdsan.os.name == "nt" else "bin/python")
    )
    python.parent.mkdir(parents=True)
    python.write_bytes(b"interpreter fixture")
    before = {
        p.relative_to(plant.root): p.read_bytes() for p in plant.root.rglob("*") if p.is_file()
    }

    def fake(command, **kwargs):
        target = Path(kwargs["cwd"])
        assert target != plant.root
        assert kwargs["check"] is False
        assert kwargs["env"]["PYTHONDONTWRITEBYTECODE"] == "1"
        assert not (target / ".venv").exists()
        (target / "process/flowsheet.yaml").write_text(
            "changed in temporary copy", encoding="utf-8"
        )
        response = Path(command[command.index("--response") + 1])
        response.write_text(json.dumps({"status": "completed"}), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "output", "")

    monkeypatch.setattr(qsdsan.subprocess, "run", fake)
    qsdsan.execute(
        plant.root,
        environment=".venv",
        input_path="inputs/baseline.json",
        case="design",
        timeout=300,
        write=False,
    )
    after = {
        p.relative_to(plant.root): p.read_bytes() for p in plant.root.rglob("*") if p.is_file()
    }
    assert before == after


def test_viewer_reports_changed_inputs_without_dwsim(plant):
    process, _ = load_process(plant.root)
    sim, doc, _ = load(plant.root)
    assert translate(process, sim, doc, "design").model is None
    paths = qsdsan.recipe_files(plant.root, sim.qsdsan.input)
    hashes = source_revision(plant.root, paths).fingerprints
    entry = payload(plant.root)["adapter"]
    entry.update(model_fingerprint=fingerprint(hashes), inputs={"fingerprints": hashes})
    data = {"cases": {"design": entry}}
    current = record.view(process, sim, doc, data, "design", hashes)
    assert current["stale"] is False
    assert current["spec"]["property_package"] is None
    hashes = {**hashes, "inputs/baseline.json": "changed"}
    assert record.view(process, sim, doc, data, "design", hashes)["stale"] is True


def test_save_rejected_without_running(plant, monkeypatch):
    from chemeascode.domains.process.simulation import qsdsan as domain

    def forbidden(*args, **kwargs):
        pytest.fail("Worker must not run for unsupported --save")

    monkeypatch.setattr(domain, "execute", forbidden)
    assert calculate(plant, True, save=Path("out.dwxmz")).findings[0].level == "error"


def test_inputs_changed_during_run_are_not_accepted(plant, monkeypatch):
    from chemeascode.domains.process.simulation import qsdsan as domain

    def changed(*args, **kwargs):
        (plant.root / "inputs/baseline.json").write_text("{}", encoding="utf-8")
        return qsdsan.WorkerResult(payload(plant.root), "", "", 0)

    monkeypatch.setattr(domain, "execute", changed)
    assert calculate(plant, True).findings[0].level == "error"
    assert not (plant.root / record.RUN_FILE).exists()


def test_native_api_reads_recipe_without_running_worker(plant, monkeypatch):
    from fastapi.testclient import TestClient

    from chemeascode.interfaces.api.serve import create_app

    def forbidden(*args, **kwargs):
        pytest.fail("Serving must never execute QSDsan")

    monkeypatch.setattr(qsdsan, "execute", forbidden)
    paths = qsdsan.recipe_files(plant.root, "inputs/baseline.json")
    hashes = source_revision(plant.root, paths).fingerprints
    entry = payload(plant.root)["adapter"]
    entry.update(model_fingerprint=fingerprint(hashes), inputs={"fingerprints": hashes})
    record.write(plant.root, entry)
    with TestClient(create_app(plant.root, allowed_hosts=["testserver"])) as client:
        response = client.get("/api/simulation")
        assert response.status_code == 200, response.text
        view = response.json()
        assert view["stale"] is False
        assert view["spec"]["tolerance"] == {}
        assert view["spec"]["components"] == {}
        (plant.root / "inputs/baseline.json").write_text("{}", encoding="utf-8")
        assert client.get("/api/simulation").json()["stale"] is True


@pytest.mark.parametrize("name", ["../other", "C:/outside", ".git/config"])
def test_project_path_refusal(plant, name):
    with pytest.raises(ValueError):
        qsdsan.local_path(plant.root, name)
