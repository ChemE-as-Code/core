"""Exercise the same subprocess boundary that a real project worker uses."""

import json
import sys

import pytest

from chemeascode.domains.process.simulation.schema import QSDsanConfiguration
from chemeascode.foundation.schemas.worker import WorkerRequest
from chemeascode.integrations.workers import LocalPythonTransport, interpreter


def test_legacy_a2o_requires_matching_declared_interval(tmp_path):
    from chemeascode.domains.process.simulation.qsdsan import QSDsanAdapter
    from chemeascode.foundation.schemas.run import AdapterResult

    evidence = tmp_path / "evidence"
    (evidence / "cheme-inputs").mkdir(parents=True)
    declared = {"case_id": "baseline", "solver": {"days": 2}}
    (evidence / "cheme-inputs/input.json").write_text(json.dumps(declared))
    saved = {
        **declared,
        "status": "completed",
        "metric_units": {"COD": "mg COD/L"},
        "basic_checks": {"integration_reached_requested_day": True},
    }
    (evidence / "result.json").write_text(json.dumps(saved))
    (evidence / "trajectory.csv").write_text("day,COD\n0,5\n2,4\n", encoding="utf-8-sig")
    request = WorkerRequest(
        run_id="test",
        case="baseline",
        mode="dynamic",
        model="a2o",
        input="input.json",
        files=["input.json"],
        timeout_s=5,
        evidence=str(evidence),
    )
    result = AdapterResult(case="baseline", status="converged", solver={"name": "QSDsan"})
    adapter = QSDsanAdapter()
    outcome = adapter.normalize(result, request, evidence)
    assert outcome.status == "completed" and outcome.outcome.convergence == "not-applicable"
    assert outcome.outcome.steady_state.state == "not-evaluated"
    declared["solver"]["days"] = 4
    (evidence / "cheme-inputs/input.json").write_text(json.dumps(declared))
    with pytest.raises(ValueError, match="completion is not established"):
        adapter.normalize(result, request, evidence)
    (evidence / "result.json").write_text("[]")
    with pytest.raises(ValueError, match="malformed"):
        adapter.normalize(result, request, evidence)


WORKER = """
import json, os, sys, time
import subprocess
from pathlib import Path
req = json.loads(Path(sys.argv[1]).read_text())
mode = Path(req["input"]).read_text()
assert Path.cwd() != Path(req["evidence"])
assert "CHEME_WORKER_TEST_SECRET" not in os.environ
assert sys.flags.ignore_environment and sys.flags.no_user_site
Path(req["input"]).write_text("edited in staged copy")
if mode in ("timeout", "child-timeout"):
    if mode == "child-timeout":
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
        Path(req['evidence'], 'child.pid').write_text(str(child.pid))
    time.sleep(60)
if mode == "missing": sys.exit(0)
if mode == "failed": sys.exit(7)
response = Path(sys.argv[2])
if mode == "invalid": response.write_text("{")
else:
    data = {"schema":"cheme/adapter-result/v1","case":req["case"],"status":"converged",
            "solver":{"name":"QSDsan","version":"fixture"}}
    if mode == "escape": data["evidence"] = "../outside"
    response.write_text(json.dumps(data))
"""


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("CHEME_QSDSAN_PYTHON", sys.executable)
    monkeypatch.setenv("CHEME_WORKER_TEST_SECRET", "must not be inherited")
    root = tmp_path / "plant"
    root.mkdir()
    (root / "demo.py").write_text(WORKER)
    return root


def execute(root, mode, **overrides):
    (root / "input.txt").write_text(mode)
    settings = {
        "model": "fixture",
        "worker": "demo",
        "files": ["demo.py"],
        "input": "input.txt",
        "timeout_s": 15,
        **overrides,
    }
    config = QSDsanConfiguration.model_validate(settings)
    output = root.parent / "evidence"
    output.mkdir(exist_ok=True)
    request = WorkerRequest(
        run_id="test",
        case="design",
        mode="dynamic",
        model=config.model,
        input=config.input,
        files=config.inputs,
        timeout_s=config.timeout_s,
        evidence=str(output),
    )
    return LocalPythonTransport(interpreter("CHEME_QSDSAN_PYTHON"), config.worker).execute(
        root, request
    )


def test_stage_and_user_interpreter(project):
    result = execute(project, "ok")
    assert result.result.case == "design"
    assert result.execution.state == "completed"
    assert (project / "input.txt").read_text() == "ok"


@pytest.mark.parametrize(
    ("mode", "message"),
    [
        ("invalid", "JSON"),
        ("failed", "exit"),
        ("missing", "response"),
        ("escape", "evidence"),
        ("timeout", "timed out"),
    ],
)
def test_failed_worker(project, mode, message):
    result = execute(project, mode, timeout_s=0.4 if mode == "timeout" else 15)
    assert message in result.execution.message
    assert result.result is None
    assert result.execution.state == ("timed-out" if mode == "timeout" else "failed")
    assert (project / "input.txt").read_text() == mode


def test_missing_interpreter_and_module(project, monkeypatch):
    monkeypatch.delenv("CHEME_QSDSAN_PYTHON")
    with pytest.raises(ValueError, match="CHEME_QSDSAN_PYTHON"):
        execute(project, "ok")
    monkeypatch.setenv("CHEME_QSDSAN_PYTHON", sys.executable)
    assert "module" in execute(project, "ok", worker="not_declared").execution.message


def test_interpreter_precedence_and_missing_declared_asset(project, monkeypatch):
    from pathlib import Path

    monkeypatch.setenv("CHEME_WORKER_PYTHON", sys.executable)
    monkeypatch.setenv("CHEME_QSDSAN_PYTHON", "invalid")
    with pytest.raises(ValueError, match="CHEME_QSDSAN_PYTHON"):
        interpreter("CHEME_QSDSAN_PYTHON")
    monkeypatch.delenv("CHEME_QSDSAN_PYTHON")
    assert interpreter("CHEME_QSDSAN_PYTHON") == Path(sys.executable)
    result = execute(project, "ok", files=["demo.py", "missing.bin"])
    assert result.execution.state == "refused" and "missing.bin" in result.execution.message


def test_timeout_terminates_worker_descendants(project):
    import os
    import subprocess
    import time

    result = execute(project, "child-timeout", timeout_s=2)
    assert result.execution.state == "timed-out"
    pid = int((project.parent / "evidence/child.pid").read_text())
    if os.name == "nt":
        listing = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True,
            check=True,
        )
        assert f'"{pid}"'.encode() not in listing.stdout
    else:
        # A reparented child may briefly be a zombie until the system reaps it.
        from pathlib import Path

        for _ in range(50):
            status = Path(f"/proc/{pid}/stat")
            if not status.exists() or status.read_text().split()[2] == "Z":
                break
            time.sleep(0.02)
        else:
            pytest.fail("worker descendant survived timeout")
