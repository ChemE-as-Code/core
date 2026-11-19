"""Second, test-only adapter proves that the worker path has no wastewater dependency."""

import json
import os
import shutil
import sys
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from chemeascode.domains.process.model import load
from chemeascode.domains.process.simulation import record, worker_model, worker_publication
from chemeascode.domains.process.simulation.backends import BACKENDS, ProjectWorkerBackend
from chemeascode.domains.process.simulation.run import run
from chemeascode.domains.process.simulation.schema import Simulation
from chemeascode.domains.process.simulation.worker_adapters import ProjectAdapter
from chemeascode.foundation.workspace import Workspace
from chemeascode.interfaces.api.serve import create_app

WORKER = r"""
import csv, hashlib, json, sys
from pathlib import Path
request = json.loads(Path(sys.argv[1]).read_bytes())
assert request['schema'] == 'cheme/worker-request/v1'
spec = json.loads(Path(request['input']).read_bytes())
assert Path('native-model.bin').read_bytes() == bytes([0, 255, 13, 10, 1])
evidence = Path(request['evidence'])
case = spec.get('mutation', '')
times = [0, 1, 2]
end = 2
if case == 'partial': times, end = [0, 1], 1
if case == 'decreasing': times = [0, 1, .5, 2]
if case in ('duplicate', 'events'): times = [0, 1, 1, 2]
path = evidence / 'trajectory.csv'
columns = ['time', 'concentration'] + (['side'] if case == 'events' else [])
with path.open('w', newline='') as handle:
    writer = csv.writer(handle)
    writer.writerow(columns)
    for i, time in enumerate(times):
        row = [time, time * 2]
        if case == 'events': row += [['sample','before','after','sample'][i]]
        writer.writerow(row)
native = 'outlet'
outcome = {'mode': request['mode'], 'convergence': 'not-applicable',
           'integration': {'start': 0, 'requested_end': 2, 'achieved_end': end,
                           'time_unit': 'h', 'completed': end == 2},
           'steady_state': {'state': 'not-evaluated'}}
variables = [{'name': 'concentration', 'unit': 'mg/L',
              'reference': {'kind': 'stream', 'id': native, 'quantity': 'tracer'}}]
trajectory = {'path': 'trajectory.csv', 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
              'time_variable': 'time', 'time_unit': 'h', 'start': 0, 'end': end,
              'variables': variables, 'final_snapshot': {'time': end}}
if case == 'events': trajectory['event_side_column'] = 'side'
result = {'schema': 'cheme/adapter-result/v2', 'case': request['case'],
          'solver': {'name':'Test simulator','version':'1'},
          'status':'completed' if end == 2 else 'not-converged', 'outcome':outcome,
          'streams':[{'id':native,'values':{'tracer': {'value':end * 2,'unit':'mg/L'}}}],
          'units':[{'id':'vessel','status':'simulated'}], 'trajectories':[trajectory]}
if request['mode'] == 'steady-state':
    result.update(status='converged', trajectories=[])
    outcome.update(convergence='converged', integration=None)
if spec.get('molecular'):
    result['streams'][0]['values']={'temperature':{'value':300,'unit':'K'},
                                   'flow':{'value':10,'unit':'kg/h'}}
if case == 'no-convergence':
    result['status']='not-converged'
    outcome['convergence']='not-converged'
if case == 'unknown-id': result['streams'][0]['id']='absent'
if case == 'duplicate-id': result['streams'] *= 2
if case == 'bad-unit': result['streams'][0]['values']['tracer']['unit']=''
if case == 'nan': result['streams'][0]['values']['tracer']['value']=float('nan')
if case == 'wrong-snapshot': result['streams'][0]['values']['tracer']['value']=42
if case == 'wrong-hash': trajectory['sha256']='0' * 64
if case == 'escape': trajectory['path']='../outside.csv'
if case == 'steady-claim': outcome['steady_state']={'state':'established'}
if case == 'malformed':
    path.write_text('time,concentration\n0,0,extra\n2,4\n')
    trajectory['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
if case == 'binary-native': (evidence / 'result.mat').write_bytes(bytes([255,0,13,10]))
if case == 'alter-archive': (evidence / 'cheme-inputs/native-model.bin').write_bytes(b'changed')
if case == 'proven-steady':
    (evidence / 'steady.json').write_text('{"max_residual":0,"tolerance":1e-8}')
    outcome['steady_state']={'state':'established','method':'fixture residual check',
                             'evidence':['steady.json']}
Path(sys.argv[2]).write_text(json.dumps(result))
"""


@pytest.fixture
def plant(tmp_path, monkeypatch):
    root = tmp_path / "plant"
    shutil.copytree(Path(__file__).resolve().parents[1] / "examples/process-qsdsan", root)
    (root / "test_worker.py").write_text(WORKER)
    (root / "native-model.bin").write_bytes(bytes([0, 255, 13, 10, 1]))
    (root / "settings.json").write_text("{}")
    (root / "process/simulation.yaml").write_text(
        yaml.safe_dump(
            {
                "schema": "cheme/simulation/v1",
                "kind": "simulation",
                "simulator": "test-only",
                "worker": {
                    "model": "native-case",
                    "worker": "test_worker",
                    "input": "settings.json",
                    "files": ["test_worker.py", "native-model.bin"],
                    "mappings": {"streams": {"outlet": "WATER"}, "units": {"vessel": "TANK"}},
                },
            }
        )
    )
    monkeypatch.setitem(
        BACKENDS, "test-only", ProjectWorkerBackend(ProjectAdapter("test-only", "Test simulator"))
    )
    monkeypatch.setenv("CHEME_WORKER_PYTHON", sys.executable)
    monkeypatch.delenv("CHEME_QSDSAN_PYTHON", raising=False)
    return root


def simulate(root, write=True):
    process, _ = load(root)
    return run(Workspace(root), process, "design", write=write)


def saved(root):
    return record.read(root)["cases"]["design"]


def setting(root, **value):
    (root / "settings.json").write_text(json.dumps(value))


def test_second_adapter_uses_shared_transport_publication_and_readers(plant, monkeypatch):
    before = {p.relative_to(plant): p.read_bytes() for p in plant.rglob("*") if p.is_file()}
    result = simulate(plant, False)
    assert not [f for f in result.findings if f.level == "error"], result.findings
    assert before == {p.relative_to(plant): p.read_bytes() for p in plant.rglob("*") if p.is_file()}
    assert not simulate(plant).findings
    entry = saved(plant)
    assert entry["status"] == "completed" and entry["converged"] is False
    assert entry["outcome"]["steady_state"]["state"] == "not-evaluated"
    assert entry["execution"]["state"] == "completed"
    assert entry["producer"]["adapter"] == "test-only"
    assert entry["trajectories"][0]["variables"][0]["reference"]["id"] == "WATER"
    assert (plant / entry["evidence"] / "cheme-inputs/native-model.bin").read_bytes() == bytes(
        [0, 255, 13, 10, 1]
    )
    assert not simulate(plant).findings
    assert saved(plant)["model_fingerprint"] == entry["model_fingerprint"]

    def forbidden(*args, **kwargs):
        pytest.fail("Read-only API launched the worker")

    monkeypatch.setattr("chemeascode.integrations.workers.LocalPythonTransport.execute", forbidden)
    with TestClient(create_app(plant, allowed_hosts=["testserver"])) as client:
        view = client.get("/api/simulation").json()
        assert view["stale"] is False, view
        table = client.get("/api/streams").json()
        assert table["calculated_columns"] == [
            {"key": "tracer", "label": "tracer", "unit": "mg/L", "basis": "mg/L"}
        ]
        assert table["streams"][1]["calculated"]["tracer"]["value"] == 4
        (plant / "native-model.bin").write_bytes(bytes([0, 255, 10, 1]))
        assert client.get("/api/simulation").json()["stale"] is True
        assert (
            client.get("/api/streams").json()["streams"][1]["calculated"]["tracer"]["stale"] is True
        )


@pytest.mark.parametrize(
    "mutation",
    [
        "partial",
        "decreasing",
        "duplicate",
        "unknown-id",
        "duplicate-id",
        "bad-unit",
        "nan",
        "wrong-snapshot",
        "wrong-hash",
        "escape",
        "steady-claim",
        "malformed",
        "alter-archive",
    ],
)
def test_invalid_results_keep_accepted_values_and_history(plant, mutation):
    assert not simulate(plant).findings
    accepted = (
        (plant / record.RUN_FILE).read_bytes(),
        (plant / "process/flowsheet.yaml").read_bytes(),
    )
    setting(plant, mutation=mutation)
    result = simulate(plant)
    assert any(f.level == "error" for f in result.findings), result
    assert accepted == (
        (plant / record.RUN_FILE).read_bytes(),
        (plant / "process/flowsheet.yaml").read_bytes(),
    )
    attempts = list((plant / "process/simulation-attempts").glob("*/cheme-attempt.json"))
    assert len(attempts) == 1 and json.loads(attempts[0].read_bytes())["accepted"] is False


@pytest.mark.parametrize("mutation", ["events", "binary-native"])
def test_dynamic_event_sides_and_opaque_native_results(plant, mutation):
    setting(plant, mutation=mutation)
    assert not simulate(plant).findings
    if mutation == "binary-native":
        assert (plant / saved(plant)["evidence"] / "result.mat").read_bytes() == bytes(
            [255, 0, 13, 10]
        )


@pytest.mark.parametrize(
    "protection", ["given", "assumed", "foreign-model", "foreign-adapter", "legacy-unknown"]
)
def test_owned_outputs_only(plant, protection):
    assert not simulate(plant).findings
    path = plant / "process/flowsheet.yaml"
    doc = yaml.safe_load(path.read_bytes())
    cell = doc["streams"][1]["state"]["design"]["calculated"]["tracer"]
    if protection in ("given", "assumed"):
        cell["provenance"] = protection
    elif protection == "legacy-unknown":
        cell.pop("producer")
        cell["source"] = "another calculator"
    else:
        cell["producer"]["model" if protection == "foreign-model" else "adapter"] = "foreign"
    path.write_text(yaml.safe_dump(doc))
    before = path.read_bytes()
    assert any(f.level == "error" for f in simulate(plant).findings)
    assert path.read_bytes() == before


def test_molecular_publication_and_numerical_convergence(plant, monkeypatch):
    monkeypatch.setitem(
        BACKENDS,
        "test-only",
        ProjectWorkerBackend(
            ProjectAdapter("test-only", "Test simulator", publication="molecular")
        ),
    )
    path = plant / "process/simulation.yaml"
    doc = yaml.safe_load(path.read_bytes())
    doc["worker"]["mode"] = "steady-state"
    path.write_text(yaml.safe_dump(doc))
    setting(plant, molecular=True)
    assert not simulate(plant).findings
    state = yaml.safe_load((plant / "process/flowsheet.yaml").read_bytes())["streams"][1]["state"][
        "design"
    ]
    assert state["flow"]["value"] == 10 and state["flow"]["unit"] == "kg/h"
    assert "calculated" not in state
    assert saved(plant)["converged"] is True
    assert saved(plant)["outcome"]["steady_state"]["state"] == "not-evaluated"
    assert not simulate(plant, False).findings
    accepted = (plant / record.RUN_FILE).read_bytes()
    setting(plant, molecular=True, mutation="no-convergence")
    assert any(f.level == "error" for f in simulate(plant).findings)
    assert (plant / record.RUN_FILE).read_bytes() == accepted


def test_lock_and_concurrent_input_change_refuse_publication(plant, monkeypatch):
    from chemeascode.integrations.workers import LocalPythonTransport

    assert not simulate(plant).findings
    old = (plant / record.RUN_FILE).read_bytes()
    lock = (plant / record.RUN_FILE).with_suffix(".lock")
    lock.write_text("other writer")
    # a publication still running holds the lock (a file alone is taken over, #320)
    fd = os.open(lock, os.O_RDWR)
    try:
        assert worker_publication._try_lock(fd)
        assert any(f.level == "error" for f in simulate(plant).findings)
        assert lock.read_text() == "other writer"
    finally:
        os.close(fd)
    lock.unlink()
    execute = LocalPythonTransport.execute

    def changed(self, root, request):
        result = execute(self, root, request)
        (root / "settings.json").write_text('{"changed":true}')
        return result

    monkeypatch.setattr(LocalPythonTransport, "execute", changed)
    assert any("inputs changed" in f.message for f in simulate(plant).findings)
    assert (plant / record.RUN_FILE).read_bytes() == old


def test_unregistered_commercial_names_and_host_settings_are_refused():
    for name in ["aspen-plus", "hysys", "dymola"]:
        with pytest.raises(ValueError, match="Unsupported simulator"):
            Simulation.model_validate(
                {"schema": "cheme/simulation/v1", "kind": "simulation", "simulator": name}
            )
    assert worker_model.raw_fingerprint(b"\xff\r\n") != worker_model.raw_fingerprint(b"\xff\n")


def test_legacy_dynamic_flag_is_not_numerical_convergence():
    assert record.numerically_converged({"converged": True})
    assert not record.numerically_converged({"converged": True, "integration_completed": True})


def test_explicit_outcome_does_not_accept_a_failed_execution():
    entry = {
        "schema": "cheme/adapter-result/v2",
        "status": "converged",
        "execution": {"state": "completed"},
        "outcome": {"mode": "steady-state", "convergence": "converged"},
    }
    assert record.numerically_converged(entry)
    entry["execution"]["state"] = "timed-out"
    assert not record.numerically_converged(entry)
    entry["execution"]["state"] = "completed"
    entry["status"] = "failed"
    assert not record.numerically_converged(entry)


def test_non_python_transport_seam(plant, monkeypatch):
    from chemeascode.foundation.schemas.run import AdapterResult
    from chemeascode.foundation.schemas.worker import ExecutionOutcome
    from chemeascode.integrations.workers import ExecutionResult

    class Session:
        def execute(self, root, request):
            # A deterministic session stand-in; no interpreter, subprocess or installed SDK.
            outcome = ExecutionOutcome(state="completed", transport="test-session")
            result = AdapterResult.model_validate(
                {
                    "schema": "cheme/adapter-result/v2",
                    "case": request.case,
                    "status": "converged",
                    "solver": {"name": "Test simulator", "version": "session"},
                    "outcome": {"mode": "steady-state", "convergence": "converged"},
                    "streams": [
                        {"id": "outlet", "values": {"tracer": {"value": 4, "unit": "mg/L"}}}
                    ],
                }
            )
            return ExecutionResult(outcome, result)

    class SessionAdapter(ProjectAdapter):
        def transport(self, config):
            return Session()

    monkeypatch.setitem(
        BACKENDS, "test-only", ProjectWorkerBackend(SessionAdapter("test-only", "Test simulator"))
    )
    monkeypatch.delenv("CHEME_WORKER_PYTHON")
    path = plant / "process/simulation.yaml"
    doc = yaml.safe_load(path.read_bytes())
    doc["worker"].pop("worker")
    doc["worker"]["mode"] = "steady-state"
    path.write_text(yaml.safe_dump(doc))
    assert not simulate(plant).findings
    assert saved(plant)["execution"]["transport"] == "test-session"


def test_independent_steady_assessment_requires_its_own_evidence(plant):
    setting(plant, mutation="proven-steady")
    assert not simulate(plant).findings
    entry = saved(plant)
    assert entry["converged"] is False  # Integration still makes no convergence claim.
    assert entry["outcome"]["steady_state"]["state"] == "established"
    assert (plant / entry["evidence"] / "steady.json").is_file()


@pytest.mark.parametrize("change", ["code", "mapping", "mode"])
def test_additional_authored_inputs_make_results_stale(plant, change):
    assert not simulate(plant).findings
    if change == "code":
        with (plant / "test_worker.py").open("a") as stream:
            stream.write("\n# changed model source\n")
    else:
        path = plant / "process/simulation.yaml"
        doc = yaml.safe_load(path.read_bytes())
        if change == "mapping":
            doc["worker"]["mappings"]["streams"] = {"outlet": "FEED"}
        else:
            doc["worker"]["mode"] = "steady-state"
        path.write_text(yaml.safe_dump(doc))
    with TestClient(create_app(plant, allowed_hosts=["testserver"])) as client:
        assert client.get("/api/simulation").json()["stale"] is True


def test_publication_failure_rolls_back_sheet_and_keeps_prior_evidence(plant, monkeypatch):
    from chemeascode.domains.process.simulation import worker_publication

    assert not simulate(plant).findings
    previous = (plant / record.RUN_FILE).read_bytes()
    sheet = (plant / "process/flowsheet.yaml").read_bytes()
    evidence = plant / saved(plant)["evidence"]
    files = {p.relative_to(evidence): p.read_bytes() for p in evidence.rglob("*") if p.is_file()}
    replace = worker_publication.os.replace

    def fail_record(source, target):
        if Path(target) == plant / record.RUN_FILE:
            raise OSError("record storage unavailable")
        return replace(source, target)

    monkeypatch.setattr(worker_publication.os, "replace", fail_record)
    result = simulate(plant)
    assert any("record storage unavailable" in f.message for f in result.findings)
    assert (plant / record.RUN_FILE).read_bytes() == previous
    assert (plant / "process/flowsheet.yaml").read_bytes() == sheet
    assert {
        p.relative_to(evidence): p.read_bytes() for p in evidence.rglob("*") if p.is_file()
    } == files
    assert list((plant / "process/simulation-runs").iterdir()) == [evidence]


def test_large_native_asset_is_hashed_without_serving_or_executing_it(plant):
    path = plant / "process/simulation.yaml"
    doc = yaml.safe_load(path.read_bytes())
    doc["worker"]["files"].append("large-native.bin")
    path.write_text(yaml.safe_dump(doc))
    asset = plant / "large-native.bin"
    asset.write_bytes(b"\xff\x00" * (3 * 1024 * 1024))
    assert not simulate(plant).findings
    with TestClient(create_app(plant, allowed_hosts=["testserver"])) as client:
        assert client.get("/api/simulation").json()["stale"] is False
        cell = client.get("/api/streams").json()["streams"][1]["calculated"]["tracer"]
        assert cell["stale"] is False and cell["value"] == 4
        assert client.get("/api/file?path=large-native.bin").status_code == 400
        with asset.open("ab") as stream:
            stream.write(b"changed")
        assert client.get("/api/simulation").json()["stale"] is True


def test_rollback_failure_keeps_manual_recovery_material(plant, monkeypatch):
    from chemeascode.domains.process.simulation import worker_publication

    assert not simulate(plant).findings
    previous = (plant / record.RUN_FILE).read_bytes()
    sheet = (plant / "process/flowsheet.yaml").read_bytes()
    replace = worker_publication.os.replace

    def fail_record_and_restore(source, target):
        if Path(target) == plant / record.RUN_FILE or Path(source).name == "previous-sheet":
            raise OSError("storage unavailable")
        return replace(source, target)

    monkeypatch.setattr(worker_publication.os, "replace", fail_record_and_restore)
    result = simulate(plant)
    assert any("rollback failed" in f.message for f in result.findings)
    assert (plant / record.RUN_FILE).read_bytes() == previous
    recovery = list((plant / "process/simulation-runs").glob("*-recovery/previous-sheet"))
    assert len(recovery) == 1 and recovery[0].read_bytes() == sheet
