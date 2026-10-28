"""The Python + CLI pattern: ``stream_report`` is the implementation, ``process streams`` wraps it.

The capability is callable without the CLI, the server or an agent, from any working directory,
and the CLI prints exactly what the function returns.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from chemeascode.domains.process.streams import (
    REPORT_INPUTS,
    UnknownCase,
    stream_report,
)
from chemeascode.foundation.provenance import file_fingerprint
from chemeascode.foundation.workspace import NotAPlantRepository
from chemeascode.interfaces.cli import app

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
runner = CliRunner()


@pytest.fixture
def plant(tmp_path):
    root = tmp_path / "plant"
    shutil.copytree(EXAMPLES / "process-nested", root, ignore=shutil.ignore_patterns("build"))
    return root


def _cli_json(root: Path, *args: str) -> str:
    cwd = os.getcwd()
    os.chdir(root)
    try:
        result = runner.invoke(app, ["process", "streams", "--json", *args])
    finally:
        os.chdir(cwd)
    assert result.exit_code == 0, result.output
    return result.stdout


def test_cli_json_is_the_report(plant):
    report = stream_report(plant)
    assert report.loaded
    assert _cli_json(plant) == report.to_json() + "\n"
    assert json.loads(_cli_json(plant)) == report.payload()


def test_report_from_another_working_directory(plant, tmp_path, monkeypatch):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    report = stream_report(plant)
    monkeypatch.chdir(plant)
    assert stream_report(Path(".")).payload() == report.payload()
    # structured result: units, per-value provenance, balances, source revision
    assert report.units["flow"]
    states = [s["state"] for s in report.streams if s["state"]]
    assert any(
        q.get("provenance") in {"given", "assumed", "calculated"}
        for state in states
        for q in state.values()
        if isinstance(q, dict)
    )
    assert report.balances and {b.status for b in report.balances} <= {
        "ok",
        "imbalance",
        "not-evaluable",
        "unsupported",
        "no-streams",
    }
    assert report.source.commit is None  # a copy outside git
    assert report.source.fingerprints["process/flowsheet.yaml"] == file_fingerprint(
        plant / "process/flowsheet.yaml"
    )
    assert set(report.source.fingerprints) <= set(REPORT_INPUTS)
    assert json.dumps(report.as_dict())  # JSON-ready, findings and source included


def test_report_records_the_git_revision(plant):
    for args in (
        ["init", "-q", "-b", "main"],
        ["-c", "user.email=t@example.com", "-c", "user.name=T", "add", "."],
        ["-c", "user.email=t@example.com", "-c", "user.name=T", "commit", "-q", "-m", "x"],
    ):
        subprocess.run(["git", *args], cwd=plant, check=True, capture_output=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=plant, check=True, capture_output=True, text=True
    ).stdout.strip()
    report = stream_report(plant)
    assert report.source.commit == head and report.source.committed
    flowsheet = plant / "process/flowsheet.yaml"
    flowsheet.write_text(flowsheet.read_text() + "\n# edited\n")
    assert stream_report(plant).source.dirty == ("process/flowsheet.yaml",)


def test_case_and_errors_match_the_cli(plant, tmp_path):
    with pytest.raises(UnknownCase, match="unknown case 'nope'"):
        stream_report(plant, "nope")
    with pytest.raises(NotAPlantRepository):
        stream_report(tmp_path)
    (plant / "process/flowsheet.yaml").write_text("schema: cheme/process/v1\nstreams: 3\n")
    report = stream_report(plant)
    assert not report.loaded and report.streams == []
    assert any(f.level == "error" for f in report.findings)
    cwd = os.getcwd()
    os.chdir(plant)
    try:
        result = runner.invoke(app, ["process", "streams", "--json"])
    finally:
        os.chdir(cwd)
    assert result.exit_code == 1


def test_report_needs_no_cli_server_or_agent(plant):
    code = (
        "import sys\n"
        "from pathlib import Path\n"
        "from chemeascode.domains.process.streams import stream_report\n"
        f"report = stream_report(Path({str(plant)!r}))\n"
        "assert report.loaded and report.streams\n"
        "print(sorted(m for m in ('typer', 'fastapi', 'uvicorn', 'thermo', 'chemicals') "
        "if m in sys.modules))\n"
    )
    result = subprocess.run(
        [sys.executable, "-W", "error", "-c", code],
        capture_output=True,
        text=True,
        check=True,
        cwd=plant.parent,
    )
    assert result.stdout.strip() == "[]", result.stdout + result.stderr
