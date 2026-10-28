"""The run record of ``cheme process simulate --fill`` (``process/simulation-run.json``),
``GET /api/simulation``, ``GET /api/reactions`` and their export by ``cheme export-static``.
DWSIM does not run: the simulate tests' stand-in solver gives the results."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from chemeascode.domains.process.model import load as load_process
from chemeascode.domains.process.reactors import reactor_report
from chemeascode.domains.process.simulation import record
from chemeascode.domains.process.simulation.run import run
from chemeascode.foundation.schemas.run import AdapterResult
from chemeascode.foundation.workspace import Workspace
from chemeascode.interfaces.api.export_static import export_static
from chemeascode.interfaces.api.serve import create_app
from tests.conftest import git
from tests.test_process_simulate import fake

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
SIM = "process/simulation.yaml"
RUN = "process/simulation-run.json"


def _commit(root: Path, message: str = "plant") -> None:
    git(root, "add", "-A")
    git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", message)


def _example(tmp_path: Path, name: str) -> Path:
    root = tmp_path / name
    shutil.copytree(EXAMPLES / name, root, ignore=shutil.ignore_patterns("build"))
    git(root, "init", "-q", "-b", "main")
    _commit(root)
    return root


@pytest.fixture
def simulated(tmp_path: Path) -> Path:
    return _example(tmp_path, "process-simulation")


@pytest.fixture
def ammonia(tmp_path: Path) -> Path:
    return _example(tmp_path, "process-ammonia")


def client(root: Path) -> TestClient:
    return TestClient(create_app(root, allowed_hosts=["testserver"]))


def _fill(root: Path, solver=fake):
    process, _ = load_process(root)
    return run(Workspace(root), process, "design", write=True, solver=solver)


def _check(root: Path):
    process, _ = load_process(root)
    return run(Workspace(root), process, "design", write=False, solver=fake)


def _edit_sim(root: Path, edit) -> None:
    data = yaml.safe_load((root / SIM).read_text())
    edit(data)
    (root / SIM).write_text(yaml.safe_dump(data, sort_keys=False))


# -- the run record -----------------------------------------------------------------------------


def test_fill_records_the_run(simulated: Path):
    result = _fill(simulated)
    assert f"{RUN}: run of case design recorded" in result.lines
    data = json.loads((simulated / RUN).read_text())
    assert data["schema"] == record.RUN_SCHEMA and data["kind"] == "simulation-run"
    entry = data["cases"]["design"]
    assert entry["simulator"] == {
        "name": "dwsim",
        "version": "9.0.5.0",
        "method": "Peng-Robinson (PR)",
    }
    assert entry["property_package"] == "Peng-Robinson (PR)"
    assert entry["converged"] is True and entry["messages"] == []
    assert entry["status"] == "converged" and entry["iterations"] == 1
    # an adapter result in the file's keys
    result = AdapterResult.model_validate(entry)
    assert result.solver.name == "dwsim" and result.solver.method == "Peng-Robinson (PR)"
    assert result.as_dict()["schema"] == "cheme/adapter-result/v1"
    assert entry["run_at"].endswith("Z") and entry["tool"].startswith("cheme-as-code ")
    inputs = entry["inputs"]
    assert inputs["commit"] == git(simulated, "rev-parse", "HEAD").strip()
    assert inputs["dirty"] == ["process/flowsheet.yaml"]  # filled, not committed
    assert sorted(inputs["fingerprints"]) == [
        "process/flowsheet.yaml",
        "process/materials.yaml",
        SIM,
    ]
    units = {u["id"]: u for u in entry["units"]}
    assert units["K1"] == {
        "id": "K1",
        "unit": "compressor",
        "status": "simulated",
        "basis": "predictive",
        "converged": True,
        "results": {"duty_kW": 84.2},
        "messages": [],
        "warnings": [],
        "coupling": "native",
    }
    assert units["E1"]["results"] == {"duty_kW": -81.0}
    streams = {s["id"]: s for s in entry["streams"]}
    s2 = streams["S2"]
    assert s2["values"]["temperature"] == {"value": 598.0, "unit": "K"}
    assert s2["values"]["composition"]["basis"] == "mole_fraction"
    assert s2["filled"] == ["temperature", "pressure", "flow", "composition"]
    assert streams["W1"]["values"]["duty"]["value"] == 84.2
    # the fingerprint every simulated value carries
    flowsheet = yaml.safe_load((simulated / "process/flowsheet.yaml").read_text())
    s2_state = next(s for s in flowsheet["streams"] if s["id"] == "S2")["state"]["design"]
    assert s2_state["temperature"]["fingerprint"] == entry["model_fingerprint"]

    # a second fill with the same inputs: values already current are "filled", not rewritten
    _fill(simulated)
    again = json.loads((simulated / RUN).read_text())["cases"]["design"]
    assert {s["id"]: s["filled"] for s in again["streams"]}["S2"] == s2["filled"]
    assert again["model_fingerprint"] == entry["model_fingerprint"]


def test_check_reports_a_missing_and_a_stale_record(simulated: Path):
    missing = [f for f in _check(simulated).findings if f.rule == "cheme.process-sim-run-missing"]
    assert missing and missing[0].level == "info" and missing[0].file == RUN
    _fill(simulated)
    assert not [f for f in _check(simulated).findings if "sim-run" in f.rule]
    before = (simulated / RUN).read_text()
    _edit_sim(simulated, lambda d: d["specs"]["K1"]["efficiency"].update(value=0.7))
    stale = [f for f in _check(simulated).findings if f.rule == "cheme.process-sim-run-stale"]
    assert stale and stale[0].level == "warning" and stale[0].hint
    assert (simulated / RUN).read_text() == before  # --check writes nothing


def test_no_convergence_is_recorded_without_stream_values(simulated: Path):
    before = (simulated / "process/flowsheet.yaml").read_text()
    result = _fill(simulated, solver=lambda m, s: fake(m, s, converged=False))
    assert result.refused == ["design"]
    assert (simulated / "process/flowsheet.yaml").read_text() == before
    entry = json.loads((simulated / RUN).read_text())["cases"]["design"]
    assert entry["converged"] is False and entry["messages"] == ["E1: not calculated"]
    assert entry["status"] == "not-converged"
    assert entry["streams"] == []
    units = {u["id"]: u for u in entry["units"]}
    assert units["E1"]["converged"] is False and units["E1"]["messages"] == ["E1: not calculated"]
    assert units["K1"]["converged"] is None  # not named: unknown
    assert any(f["rule"] == "cheme.process-sim-not-converged" for f in entry["findings"])


def test_excluded_units_carry_their_reason(simulated: Path):
    _fill(simulated)
    _edit_sim(simulated, lambda d: d.update(exclude=["K1"]))
    _fill(simulated)
    units = {
        u["id"]: u for u in json.loads((simulated / RUN).read_text())["cases"]["design"]["units"]
    }
    assert units["K1"] == {"id": "K1", "status": "excluded", "reason": f"exclude: in {SIM}"}
    assert units["E1"]["status"] == "simulated"


def test_a_record_keeps_the_other_cases(simulated: Path):
    (simulated / RUN).write_text(
        json.dumps({"schema": record.RUN_SCHEMA, "kind": "simulation-run", "cases": {"x": {}}})
    )
    _fill(simulated)
    assert list(json.loads((simulated / RUN).read_text())["cases"]) == ["design", "x"]
    assert record.parse("not json") is None
    assert record.parse(json.dumps({"schema": "other", "cases": {}})) is None


# -- GET /api/simulation ------------------------------------------------------------------------


def test_simulation_endpoint(simulated: Path):
    api = client(simulated)
    repo = api.get("/api/repo").json()
    assert repo["has_simulation"] is True and repo["has_reactions"] is False

    data = api.get("/api/simulation").json()
    assert data["file"] == SIM and data["run_file"] == RUN
    assert data["case"] == "design" and data["cases"] == ["design"]
    assert data["run"] is None and data["stale"] is None
    spec = data["spec"]
    assert spec["simulator"] == "dwsim" and spec["property_package"] == "Peng-Robinson (PR)"
    assert spec["specs"]["K1"]["efficiency"] == {
        "value": 0.78,
        "provenance": "assumed",
        "source": "typical single-stage centrifugal",
    }
    units = {u["id"]: u for u in data["units"]}
    assert [u["id"] for u in data["units"]][:3] == ["K1", "E1", "X1"]
    assert units["K1"]["status"] == "simulated" and units["K1"]["unit"] == "compressor"
    assert units["K1"]["run"] is None and units["X1"]["spec"] is None

    _fill(simulated)
    data = api.get("/api/simulation").json()
    assert data["stale"] is False and data["staleness"]["changed_files"] == []
    assert data["run"]["converged"] is True
    assert data["staleness"]["model_fingerprint"] == data["run"]["model_fingerprint"]
    units = {u["id"]: u for u in data["units"]}
    assert units["K1"]["run"]["results"] == {"duty_kW": 84.2}

    _edit_sim(simulated, lambda d: d["specs"]["K1"]["efficiency"].update(value=0.7))
    data = api.get("/api/simulation").json()
    assert data["stale"] is True and data["staleness"]["changed_files"] == [SIM]
    assert data["staleness"]["current_fingerprint"] != data["staleness"]["model_fingerprint"]

    _edit_sim(simulated, lambda d: d.update(exclude=["K1"]))
    units = {u["id"]: u for u in api.get("/api/simulation").json()["units"]}
    assert units["K1"]["status"] == "excluded" and SIM in units["K1"]["reason"]

    # the committed revision has no record yet
    assert api.get("/api/simulation", params={"rev": "HEAD"}).json()["run"] is None


#: An entry as ``simulate --fill`` wrote it before the adapter result: no ``status``, no
#: ``simulator.method``.
OLD_ENTRY = {
    "case": "design",
    "run_at": "2026-10-01T12:00:00Z",
    "tool": "cheme-as-code 0.9.0",
    "simulator": {"name": "dwsim", "version": "9.0.5.0"},
    "property_package": "Peng-Robinson (PR)",
    "model_fingerprint": "0123456789abcdef",
    "inputs": {"commit": None, "dirty": [], "fingerprints": {}},
    "converged": False,
    "iterations": None,
    "messages": ["E1: not calculated"],
    "units": [{"id": "K1", "unit": "compressor", "status": "simulated", "converged": None}],
    "streams": [],
    "findings": [],
}


def test_simulation_endpoint_serves_an_old_record_unchanged(simulated: Path):
    data = {"schema": record.RUN_SCHEMA, "kind": "simulation-run", "cases": {"design": OLD_ENTRY}}
    (simulated / RUN).write_text(json.dumps(data, indent=2) + "\n")
    served = client(simulated).get("/api/simulation").json()
    assert served["run"] == OLD_ENTRY and served["stale"] is True
    assert {u["id"]: u for u in served["units"]}["K1"]["run"] == OLD_ENTRY["units"][0]
    old = AdapterResult.model_validate(OLD_ENTRY)  # status from converged
    assert old.status == "not-converged" and old.solver.method is None


def test_simulation_endpoint_errors(simulated: Path, tmp_path: Path):
    api = client(simulated)
    assert api.get("/api/simulation", params={"case": "turndown"}).status_code == 422
    _fill(simulated)
    flowsheet = simulated / "process/flowsheet.yaml"
    flowsheet.write_text("schema: cheme/process/v1\nkind: flowsheet\nstreams: 3\n")
    data = api.get("/api/simulation").json()
    assert data["problem"] and data["stale"] is None and data["run"]["converged"] is True
    assert data["case"] == "design"  # the only recorded case
    (simulated / SIM).write_text("schema: cheme/simulation/v1\nkind: simulation\nspecs: 3\n")
    broken = api.get("/api/simulation")
    assert broken.status_code == 422 and SIM in broken.json()["error"]
    (simulated / SIM).unlink()
    assert api.get("/api/simulation").status_code == 404
    assert api.get("/api/repo").json()["has_simulation"] is False


# -- GET /api/reactions -------------------------------------------------------------------------


def test_reactions_endpoint(ammonia: Path):
    api = client(ammonia)
    repo = api.get("/api/repo").json()
    assert repo["has_reactions"] is True and repo["has_simulation"] is False
    assert api.get("/api/simulation").status_code == 404

    data = api.get("/api/reactions").json()
    assert data["file"] == "process/reactions.yaml" and data["case"] == "design"
    assert data["kinetics"]["file"] == "process/catalysts.yaml"
    assert [c["id"] for c in data["kinetics"]["catalysts"]] == ["FE_NH3"]
    (syn,) = data["reactions"]
    assert syn["rate"] is None and syn["rate_law"] is None
    assert syn["id"] == "NH3_SYN" and syn["equation"] == "N2 + 3 H2 <=> 2 NH3"
    assert syn["stoichiometry"] == {"N2": -1.0, "H2": -3.0, "NH3": 2.0}
    assert syn["heat_of_reaction"]["provenance"] == "given"
    assert syn["conversion"] is None and syn["equilibrium_constant"] is None
    assert syn["type"] == "equilibrium" and syn["key_component"] is None
    assert syn["units"] == [
        {
            "unit": "R1",
            "kind": "step",
            "model": "equilibrium",
            "approach_K": 20.0,
            "conversion": None,
        }
    ]
    assert syn["element_balance"] == {"evaluable": True, "balanced": True, "change": {}}
    # the rows of `cheme process reactors`
    report = json.loads(json.dumps(reactor_report(ammonia).reactors))
    assert data["reactors"] == report
    assert [b["node"] for b in data["balance"]["balances"]] == ["LOOP", "R1"]
    assert data["balance"]["balances"][1]["status"] == "ok"
    assert data["balance"]["findings"] == []


def test_reactions_findings_and_errors(ammonia: Path):
    api = client(ammonia)
    path = ammonia / "process/reactions.yaml"
    text = path.read_text()
    path.write_text(text.replace("{N2: -1, H2: -3, NH3: 2}", "{N2: -1, H2: -3, NH3: 3}"))
    data = api.get("/api/reactions").json()
    (syn,) = data["reactions"]
    assert syn["element_balance"]["balanced"] is False and syn["element_balance"]["change"]
    rules = {f["rule"] for f in data["balance"]["findings"]}
    assert "cheme.reaction-element-balance" in rules
    assert all(f["file"] and f["id"] for f in data["balance"]["findings"])
    # the committed revision is still balanced
    committed = api.get("/api/reactions", params={"rev": "HEAD"}).json()
    assert committed["reactions"][0]["element_balance"]["balanced"] is True

    assert api.get("/api/reactions", params={"case": "turndown"}).status_code == 422
    path.write_text("schema: cheme/reactions/v1\nkind: reactions\nreactions: 3\n")
    broken = api.get("/api/reactions")
    assert broken.status_code == 422 and "reactions" in broken.json()["error"]
    path.unlink()
    assert api.get("/api/reactions").status_code == 404
    assert api.get("/api/repo").json()["has_reactions"] is False


# -- export-static ------------------------------------------------------------------------------


def test_export_static_writes_simulation_and_reactions(simulated: Path, ammonia: Path, tmp_path):
    _fill(simulated)
    _commit(simulated, "simulated")
    manifest = export_static(simulated, tmp_path / "sim")
    entries = manifest["entries"]
    assert entries["simulation"]["status"] == 200
    assert "simulation?case=design" in entries and "reactions" not in entries
    stored = json.loads((tmp_path / "sim" / "data" / entries["simulation"]["file"]).read_text())
    assert stored["run"]["converged"] is True and stored["stale"] is False

    manifest = export_static(ammonia, tmp_path / "nh3")
    entries = manifest["entries"]
    assert entries["reactions"]["status"] == 200 and "reactions?case=design" in entries
    assert "simulation" not in entries
