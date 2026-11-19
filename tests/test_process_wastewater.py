"""Exercise the unmocked fill, CLI, read-only snapshot, validation and maturity paths."""

import shutil
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from chemeascode.domains.process.model import load
from chemeascode.domains.process.sheets import _run_stale_findings
from chemeascode.foundation.workspace import Workspace
from chemeascode.interfaces.api.serve import create_app
from chemeascode.project.maturity import maturity_report


def test_readers_see_current_and_changed_worker_inputs(tmp_path, monkeypatch):
    from chemeascode.interfaces.cli import app

    root = tmp_path / "plant"
    shutil.copytree(Path(__file__).resolve().parents[1] / "examples/process-qsdsan", root)
    monkeypatch.chdir(root)
    monkeypatch.setenv("CHEME_QSDSAN_PYTHON", sys.executable)
    runner = CliRunner()
    output = runner.invoke(app, ["process", "simulate", "--fill"])
    assert output.exit_code == 0, output.output
    assert "mg N/L" in runner.invoke(app, ["process", "streams", "--json"]).output

    def forbid(*args, **kwargs):
        pytest.fail("reading or validating launched the worker")

    monkeypatch.setattr("chemeascode.integrations.qsdsan.execute", forbid)
    with TestClient(create_app(root, allowed_hosts=["testserver"])) as client:
        for changed in (False, True):
            if changed:
                with (root / "demo_worker.py").open("a") as f:
                    f.write("\n# modified\n")
            view = client.get("/api/simulation").json()
            assert view["stale"] is changed, view
            assert view["spec"]["property_package"] is None
            assert view["spec"]["qsdsan"]["worker"] == "demo_worker"
            streams = client.get("/api/streams").json()["streams"]
            assert streams[0]["properties"]["pressure"]["provenance"] == "given"
            assert streams[0]["calculated"]["TN"]["stale"] is changed
            assert "NH4" not in streams[0]["calculated"]
            assert streams[1]["calculated"]["NH4"]["value"] == 0
            plant, _ = load(root)
            findings = _run_stale_findings(
                Workspace(root), plant, {(root / "demo_worker.py").resolve()}
            )
            assert any(f.rule == "cheme.process-sim-run-stale" for f in findings) is changed
            report = maturity_report(root)
            reqs = {r.id: r for r in report.requirements}
            assert reqs["predictive.current"].status == ("fail" if changed else "pass")
            assert reqs["predictive.simulation-spec"].status == "pass"


def test_oversized_worker_input_does_not_blank_the_stream_table(tmp_path):
    root = tmp_path / "plant"
    shutil.copytree(Path(__file__).resolve().parents[1] / "examples/process-qsdsan", root)
    (root / "results.json").write_bytes(b" " * (6 * 1024 * 1024))
    with TestClient(create_app(root, allowed_hosts=["testserver"])) as client:
        assert client.get("/api/simulation").status_code == 200
        response = client.get("/api/streams")
        assert response.status_code == 200
        assert len(response.json()["streams"]) == 2


def test_serve_fingerprints_a_worker_input_over_the_display_cap(tmp_path, monkeypatch):
    # serve hashes a declared input over 5 MB as the CLI does, not as missing (#318)
    from chemeascode.interfaces.cli import app

    root = tmp_path / "plant"
    shutil.copytree(Path(__file__).resolve().parents[1] / "examples/process-qsdsan", root)
    data = root / "results.json"
    data.write_bytes(data.read_bytes() + b" " * (6 * 1024 * 1024))
    monkeypatch.chdir(root)
    monkeypatch.setenv("CHEME_QSDSAN_PYTHON", sys.executable)
    runner = CliRunner()
    assert runner.invoke(app, ["process", "simulate", "--fill"]).exit_code == 0
    assert runner.invoke(app, ["process", "simulate", "--check"]).exit_code == 0
    with TestClient(create_app(root, allowed_hosts=["testserver"])) as client:
        view = client.get("/api/simulation").json()
        assert view["stale"] is False, view
        streams = client.get("/api/streams").json()["streams"]
        assert streams[0]["calculated"]["TN"]["stale"] is False
        assert streams[0]["stale"] == []
