"""Portable configuration, read-only serving and publication on a real worker boundary."""

import json
import shutil
import sys
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from chemeascode.domains.process.model import load
from chemeascode.domains.process.simulation import record
from chemeascode.domains.process.simulation.run import run
from chemeascode.domains.process.simulation.schema import QSDsanConfiguration
from chemeascode.foundation.project_paths import local_path
from chemeascode.foundation.workspace import Workspace

EXAMPLE = Path(__file__).resolve().parents[1] / "examples/process-qsdsan"


@pytest.fixture
def plant(tmp_path, monkeypatch):
    monkeypatch.setenv("CHEME_QSDSAN_PYTHON", sys.executable)
    root = tmp_path / "case"
    shutil.copytree(EXAMPLE, root)
    return root


def simulate(root, fill=True):
    process, _ = load(root)
    return run(Workspace(root), process, "design", write=fill)


@pytest.mark.parametrize(
    "name",
    [
        "../other",
        r"..\other",
        r"inputs\file",
        ".git/config",
        "/outside",
        r"\absolute",
        "C:/outside",
        "C:outside",
        r"\\host\share",
        "nested/.Git/object",
    ],
)
def test_project_path_refusal(tmp_path, name):
    with pytest.raises(ValueError):
        local_path(tmp_path, name)
    config = {"model": "example", "worker": "demo", "input": "data", "files": ["demo.py"]}
    for fields in ({"input": name}, {"files": [name]}, {"environment": name}):
        with pytest.raises(ValidationError):
            QSDsanConfiguration.model_validate({**config, **fields})


def test_fill_and_check(plant):
    def snapshot():
        return {p.relative_to(plant): p.read_bytes() for p in plant.rglob("*") if p.is_file()}

    before = snapshot()
    result = simulate(plant, False)
    assert not [f for f in result.findings if f.level == "error"]
    assert snapshot() == before
    assert not simulate(plant).findings
    data = record.read(plant)["cases"]["design"]
    assert (plant / data["evidence"] / "cheme-simulation-entry.json").is_file()
    assert not (plant / "runs").exists()
    assert not simulate(plant, False).findings
    assert not simulate(plant).findings
    assert len(list((plant / "process/simulation-runs").iterdir())) == 2
    assert record.read(plant)["cases"]["design"]["model_fingerprint"] == data["model_fingerprint"]


@pytest.mark.parametrize(
    "mutation",
    [
        "solver",
        "case",
        "wrong_id",
        "duplicate",
        "status",
        "filled",
        "given",
        "assumed",
        "invalid_unit",
    ],
)
def test_refuse_invalid_or_protected(plant, mutation):
    assert not simulate(plant).findings
    sheet = plant / "process/flowsheet.yaml"
    worker = plant / "demo_worker.py"
    if mutation in ("given", "assumed"):
        doc = yaml.safe_load(sheet.read_bytes())
        doc["streams"][0]["state"]["design"]["calculated"]["TN"]["provenance"] = mutation
        sheet.write_text(yaml.safe_dump(doc))
    else:
        action = {
            "solver": "result['solver']['name']='wrong'",
            "case": "result['case']='wrong'",
            "wrong_id": "result['streams'][0]['id']='unknown'",
            "duplicate": "result['streams'] *= 2",
            "status": "result['status']='failed'",
            "filled": "result['streams'][0]['filled']=['composition']",
            "invalid_unit": "result['streams'][0]['values']['TN']['unit']='mg O2/L'",
        }[mutation]
        worker.write_text(
            worker.read_text().replace(
                "    Path(sys.argv[2])", "    " + action + "\n    Path(sys.argv[2])"
            )
        )
    old = (sheet.read_bytes(), (plant / record.RUN_FILE).read_bytes())
    assert any(f.level == "error" for f in simulate(plant).findings)
    assert old == (sheet.read_bytes(), (plant / record.RUN_FILE).read_bytes())
    assert len(list((plant / "process/simulation-runs").iterdir())) == 1


def test_failed_publication_restores_previous_sheet_and_evidence(plant, monkeypatch):
    import os

    assert not simulate(plant).findings
    sheet = plant / "process/flowsheet.yaml"
    path = plant / record.RUN_FILE
    folder = plant / "process/simulation-runs"
    before = sheet.read_bytes(), path.read_bytes(), set(folder.iterdir())
    replace = os.replace

    def fail_record(src, dest):
        if dest == path:
            raise PermissionError("simulated write failure")
        replace(src, dest)

    monkeypatch.setattr(os, "replace", fail_record)
    assert any("simulated write failure" in f.message for f in simulate(plant).findings)
    assert before == (sheet.read_bytes(), path.read_bytes(), set(folder.iterdir()))


def test_keeps_authored_yaml_comment_and_accepts_volume_unit_alias(plant):
    data = plant / "results.json"
    data.write_bytes(data.read_bytes().replace(b"m3/day", b"m3/d"))
    sheet = plant / "process/flowsheet.yaml"
    with sheet.open("a", encoding="utf-8") as out:
        out.write("\n# commissioning assumption retained for review\n")
    assert not simulate(plant).findings
    assert "commissioning assumption retained for review" in sheet.read_text()
    assert (
        yaml.safe_load(sheet.read_bytes())["streams"][0]["state"]["design"]["calculated"]["flow"][
            "unit"
        ]
        == "m3/d"
    )


def _worker_action(root, action):
    worker = root / "demo_worker.py"
    worker.write_text(
        worker.read_text().replace(
            "    Path(sys.argv[2])", "    " + action + "\n    Path(sys.argv[2])"
        )
    )


@pytest.mark.parametrize("values", [(1e-05, 2e16), (5e-05, 1.5e-07)])
def test_fill_writes_floats_json_writes_in_exponent_form(plant, values):
    # json.dumps writes 1e-05 and 2e+16, which YAML 1.1 reads back as strings (#316)
    data = plant / "results.json"
    cells = yaml.safe_load(data.read_bytes())
    for small, large in (values, (values[1], values[0])):
        cells["WATER"]["NH4"]["value"] = small
        cells["WATER"]["flow"]["value"] = large
        data.write_text(json.dumps(cells))
        assert not simulate(plant).findings
        doc = yaml.safe_load((plant / "process/flowsheet.yaml").read_bytes())
        written = doc["streams"][1]["state"]["design"]["calculated"]
        assert (written["NH4"]["value"], written["flow"]["value"]) == (small, large)
        assert all(type(written[k]["value"]) is float for k in ("NH4", "flow"))


def test_stale_wastewater_flow_is_not_the_stream_flow(plant):
    # the calculated "flow" (m3/day) and the state's "flow" are different values (#317)
    from chemeascode.domains.process.pfd_sheet import stream_table as pfd_table
    from chemeascode.domains.process.props import stale
    from chemeascode.domains.process.streams import stream_table

    assert not simulate(plant).findings
    sheet = plant / "process/flowsheet.yaml"
    sheet.write_text(
        sheet.read_text().replace(
            "        pressure: {value: 101.325, unit: kPa(a), provenance: given, "
            "source: design basis}\n",
            "        pressure: {value: 101.325, unit: kPa(a), provenance: given, "
            "source: design basis}\n"
            "        flow: {value: 1000, unit: kg/h, provenance: given, source: design basis}\n",
        )
    )
    process, _ = load(plant)  # the model changed: the QSDsan cells are stale
    feed = process.flowsheet.streams[0]
    assert sorted(stale(process, feed, "design")) == ["TN", "calculated.flow"]
    row = stream_table(process, "design", {}, set())["streams"][0]
    assert row["properties"]["flow"]["stale"] is False
    assert row["calculated"]["flow"]["stale"] is True
    assert row["calculated"]["TN"]["stale"] is True
    assert pfd_table(process, ["FEED"], [], "design").columns[0][1][3] == "1 000"


def test_worker_findings_are_reported(plant, monkeypatch):
    # a worker warning reaches the findings and makes --check exit 1 (#319)
    from typer.testing import CliRunner

    from chemeascode.interfaces.cli import app

    _worker_action(
        plant,
        "result['findings']=[{'level': 'warning', 'rule': 'n-balance', "
        "'message': 'N balance off by 8%', 'ids': ['TANK']}]",
    )
    found = [f for f in simulate(plant, False).findings if f.ids != ["design"]]  # not the record's
    assert [(f.level, f.ids) for f in found] == [("warning", ["TANK"])]
    assert "N balance off by 8%" in found[0].message
    monkeypatch.chdir(plant)
    result = CliRunner().invoke(app, ["process", "simulate", "--check"])
    assert result.exit_code == 1, result.output
    assert "N balance off by 8%" in result.output


def test_lock_left_by_a_killed_run_is_taken_over(plant):
    # a SIGKILL during publication leaves the lock file; it must not refuse every later fill
    (plant / "process/simulation-run.lock").write_bytes(b"")
    assert not simulate(plant).findings
    assert record.read(plant)["cases"]["design"]
    assert not (plant / "process/simulation-run.lock").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="flock")
def test_live_publication_lock_refuses(plant):
    import fcntl
    import os

    lock = plant / "process/simulation-run.lock"
    fd = os.open(lock, os.O_RDWR | os.O_CREAT)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        sheet = (plant / "process/flowsheet.yaml").read_bytes()
        found = simulate(plant).findings
        assert any("Another simulate --fill is publishing" in f.message for f in found)
        assert (plant / "process/flowsheet.yaml").read_bytes() == sheet
        assert lock.exists()
    finally:
        os.close(fd)
