"""Exercise the same subprocess boundary that a real project worker uses."""

import sys

import pytest

from chemeascode.domains.process.simulation.schema import QSDsanConfiguration
from chemeascode.integrations import qsdsan

WORKER = """
import json, os, sys, time
from pathlib import Path
req = json.loads(Path(sys.argv[1]).read_text())
mode = Path(req["input"]).read_text()
assert Path.cwd() != Path(req["evidence"])
assert "CHEME_WORKER_TEST_SECRET" not in os.environ
assert sys.flags.ignore_environment and sys.flags.no_user_site
Path(req["input"]).write_text("edited in staged copy")
if mode == "timeout": time.sleep(60)
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
    return qsdsan.execute(root, config, "design", output)


def test_stage_and_user_interpreter(project):
    result = execute(project, "ok")
    assert result.case == "design"
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
    with pytest.raises(ValueError, match=message):
        execute(project, mode, timeout_s=0.4 if mode == "timeout" else 15)
    assert (project / "input.txt").read_text() == mode


def test_missing_interpreter_and_module(project, monkeypatch):
    monkeypatch.delenv("CHEME_QSDSAN_PYTHON")
    with pytest.raises(ValueError, match="CHEME_QSDSAN_PYTHON"):
        execute(project, "ok")
    monkeypatch.setenv("CHEME_QSDSAN_PYTHON", sys.executable)
    with pytest.raises(ValueError, match="module"):
        execute(project, "ok", worker="not_declared")
