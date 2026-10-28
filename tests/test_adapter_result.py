"""The adapter result (``cheme/adapter-result/v1``, foundation/schemas/run.py) of ``cheme process
propagate --json`` and ``cheme process props --json``; the DWSIM record's entries are tested
with the run record (test_serve_simulation_reactions.py)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from chemeascode.foundation.schemas.run import ADAPTER_SCHEMA, AdapterResult
from chemeascode.interfaces.cli import app

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def _copy(tmp_path: Path, name: str) -> Path:
    root = tmp_path / name
    shutil.copytree(EXAMPLES / name, root, ignore=shutil.ignore_patterns("build"))
    return root


def _json(root: Path, monkeypatch, *args: str) -> tuple[int, dict]:
    monkeypatch.chdir(root)
    done = CliRunner().invoke(app, ["process", *args, "--json"])
    return done.exit_code, json.loads(done.stdout)


def test_propagate_json_is_an_adapter_result(tmp_path, monkeypatch):
    root = _copy(tmp_path, "process-simulation")
    before = sorted(p.name for p in (root / "process").iterdir())
    code, data = _json(root, monkeypatch, "propagate", "--fill")
    assert code == 0 and len(data["results"]) == 1
    result = data["results"][0]
    AdapterResult.model_validate(result)
    assert result["schema"] == ADAPTER_SCHEMA and result["case"] == "design"
    assert result["status"] == "converged" and result["messages"] == []
    assert result["solver"]["name"] == "cheme process propagate" and result["solver"]["version"]
    assert result["iterations"] == 2  # the sweep that derived, the sweep that found no more
    streams = {s["id"]: s for s in result["streams"]}
    assert streams["S4"]["filled"] == ["composition", "flow"]
    assert streams["S4"]["values"]["flow"] == {"value": pytest.approx(700.0), "unit": "kg/h"}
    assert "process/flowsheet.yaml" in result["inputs"]["fingerprints"]
    # a second run writes nothing, and no run writes a file of its own
    _, again = _json(root, monkeypatch, "propagate", "--check")
    assert all(s["filled"] == [] for s in again["results"][0]["streams"])
    assert sorted(p.name for p in (root / "process").iterdir()) == before


def test_propagate_json_names_what_is_unsolved(tmp_path, monkeypatch):
    root = _copy(tmp_path, "process-separation")
    _, data = _json(root, monkeypatch, "propagate", "--check")
    result = data["results"][0]
    assert result["status"] == "not-converged"
    assert len(result["messages"]) == len(result["units"]) == 3
    unit = result["units"][0]
    assert unit["status"] == "not-solved" and unit["converged"] is False and unit["lacking"]
    assert unit["id"] in result["messages"][0]
    assert any(f["rule"] == "cheme.process-propagate-not-solved" for f in result["findings"])


def test_props_json_is_an_adapter_result(tmp_path, monkeypatch):
    pytest.importorskip("thermo")
    from tests.test_process_props import FLOWSHEET, MATERIALS

    root = tmp_path / "plant"
    (root / "process").mkdir(parents=True)
    (root / "plant.yaml").write_text("name: props-test\nstage: concept\n")
    (root / "process/materials.yaml").write_text(MATERIALS)
    (root / "process/flowsheet.yaml").write_text(FLOWSHEET)
    code, data = _json(root, monkeypatch, "props", "--fill")
    result = data["results"][0]
    AdapterResult.model_validate(result)
    assert code == 0 and result["status"] == "converged" and result["messages"] == []
    assert result["solver"]["name"] == "thermo" and result["solver"]["version"] == "0.6.1"
    assert result["solver"]["method"].startswith("Peng-Robinson")
    assert result["iterations"] is None  # one flash per stream
    s1 = {s["id"]: s for s in result["streams"]}["S1"]
    assert s1["values"]["phase"] == "vapor"
    assert s1["values"]["density"]["unit"] == "kg/m3"
    assert "phase" in s1["filled"] and "density" in s1["filled"]
    _, again = _json(root, monkeypatch, "props", "--check")
    assert all(s["filled"] == [] for s in again["results"][0]["streams"])

    path = root / "process/flowsheet.yaml"
    path.write_text(path.read_text().replace("value: 293.15", "value: 500.0", 1))
    code, data = _json(root, monkeypatch, "props", "--check")
    result = data["results"][0]
    assert code == 1 and result["status"] == "not-converged"
    assert result["messages"] and result["messages"][0].startswith("S1:")


def test_an_old_dwsim_entry_reads_as_an_adapter_result():
    entry = {
        "case": "design",
        "simulator": {"name": "dwsim", "version": "9.0.5.0"},
        "converged": True,
        "iterations": None,
    }
    result = AdapterResult.model_validate(entry)
    assert result.status == "converged" and result.solver.version == "9.0.5.0"
    assert result.as_dict()["solver"] == {"name": "dwsim", "version": "9.0.5.0", "method": None}
    with pytest.raises(ValueError):
        AdapterResult.model_validate({**entry, "status": "maybe"})
