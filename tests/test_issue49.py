"""Parallel boundary streams between the same BFD nodes drawn as one connection
(``bfd.aggregate``), listing the streams it represents; balances unchanged."""

import shutil
from pathlib import Path

import pytest
import yaml

from chemeascode.domains.process.build import connection_streams
from chemeascode.domains.process.model import balances, load, rules
from chemeascode.domains.process.provenance import source_fingerprint
from chemeascode.domains.process.sheets import build, represented
from chemeascode.foundation.workspace import Workspace
from chemeascode.project.validate import validate_workspace
from tests.conftest import git

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
AGGREGATED = {
    "S1": ["S1"],
    "Q1": ["Q1"],
    "S2": ["S2", "S3"],
    "Q2": ["Q2"],
    "S4": ["S4"],
    "S5": ["S5"],
    "S6": ["S6", "S7", "S8"],
    "S9": ["S9"],
    "S10": ["S10"],
    "S11": ["S11"],
}


@pytest.fixture
def aggregate(tmp_path):
    shutil.copytree(
        EXAMPLES / "process-aggregate", tmp_path / "plant", ignore=shutil.ignore_patterns("build")
    )
    return Workspace(tmp_path / "plant")


def _edit(ws, change):
    path = ws.root / "process/flowsheet.yaml"
    data = yaml.safe_load(path.read_text())
    change(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def _process(ws):
    process, found = load(ws.root)
    assert process is not None, [f.format() for f in found]
    return process


def _bfd(ws):
    from pydexpi.loaders.public import load_xml_with_report

    model = load_xml_with_report((ws.root / "process/BFD.xml").read_bytes()).model
    return {c.id: c for c in model.conceptualModel.processConnections}


def test_parallel_streams_drawn_as_one_connection_kinds_and_directions_apart(aggregate):
    assert connection_streams(_process(aggregate)) == AGGREGATED
    assert not build(aggregate, force=True).failed
    conns = _bfd(aggregate)
    assert set(conns) == set(AGGREGATED)
    text = {cid: c.description.singleLanguageStrings[0].value for cid, c in conns.items()}
    assert text["S2"] == "represents: S2 S3"
    assert text["S6"] == "represents: S6 S7 S8"
    assert text["S1"] == "represents: S1"
    # one connection between COMP and COLD per kind and direction
    assert conns["S2"].source.id == "COMP_main" and conns["Q2"].source.id == "COMP_shaft"
    assert conns["S4"].source.id == "COLD_waste"
    # the aggregated connection carries no values (the streams' states differ)
    assert conns["S2"].label == "S2 S3" and not conns["S2"].massFlow
    assert conns["S1"].massFlow[0].value.value == 1000.0
    report = validate_workspace(aggregate)
    assert not [f.format() for f in report.findings if f.level != "info"]


def test_aggregated_bfd_builds_deterministically(aggregate):
    build(aggregate, force=True)
    first = (aggregate.root / "process/BFD.xml").read_bytes()
    (aggregate.root / "process/BFD.xml").unlink()
    build(aggregate)
    assert (aggregate.root / "process/BFD.xml").read_bytes() == first


def test_committed_aggregate_example_is_current():
    report = validate_workspace(Workspace(EXAMPLES / "process-aggregate"))
    bad = [f for f in report.findings if f.rule.startswith("cheme.generated-")]
    assert not bad, [f.format() for f in bad]


def test_balances_unchanged_and_off_by_default(aggregate):
    on = [b.entry() for b in balances(_process(aggregate))]
    _edit(aggregate, lambda d: d.pop("bfd"))
    process = _process(aggregate)
    assert [b.entry() for b in balances(process)] == on
    assert all(len(streams) == 1 for streams in connection_streams(process).values())


def test_aggregate_per_pair_either_order(aggregate):
    _edit(aggregate, lambda d: d.update(bfd={"aggregate": [["STORE", "COLD"]]}))
    conns = connection_streams(_process(aggregate))
    assert conns["S6"] == ["S6", "S7", "S8"]
    assert conns["S2"] == ["S2"] and conns["S3"] == ["S3"]


def test_aggregate_pair_off_the_bfd_is_an_error(aggregate):
    _edit(aggregate, lambda d: d.update(bfd={"aggregate": [["COLD", "NOPE"]]}))
    found = [f for f in rules(_process(aggregate)) if f.rule == "cheme.process-aggregate"]
    assert len(found) == 1 and found[0].level == "error" and found[0].line
    assert "NOPE is not a feed, product or block" in found[0].message and found[0].hint


def test_bfd_option_does_not_touch_the_pfd_fingerprint(aggregate):
    process = _process(aggregate)
    with_option = source_fingerprint(process, "pfd", {})
    bfd_with = source_fingerprint(process, "bfd", {})
    _edit(aggregate, lambda d: d.pop("bfd"))
    process = _process(aggregate)
    assert source_fingerprint(process, "pfd", {}) == with_option
    assert source_fingerprint(process, "bfd", {}) != bfd_with


def test_represented_reads_the_sheet():
    content = (EXAMPLES / "process-aggregate/process/BFD.xml").read_bytes()
    assert represented(content) == AGGREGATED
    assert represented(b"<not xml") == {}


def _streams_api(root):
    from fastapi.testclient import TestClient

    from chemeascode.interfaces.api.serve import create_app

    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "aggregate")
    return TestClient(create_app(root, allowed_hosts=["testserver"])).get("/api/streams").json()


def test_api_streams_lists_what_each_bfd_connection_represents(aggregate):
    data = _streams_api(aggregate.root)
    assert data["bfd_connections"] == AGGREGATED and data["bfd_connections_from"] == "sheet"
    assert {s["id"] for s in data["streams"] if s["on_bfd"]} >= {"S3", "S7", "S8"}


def test_api_streams_follows_the_drawn_sheet_else_the_flowsheet(aggregate):
    # the YAML no longer aggregates, the sheet is not rebuilt: the drill-down follows the drawing
    _edit(aggregate, lambda d: d.pop("bfd"))
    assert _streams_api(aggregate.root)["bfd_connections"] == AGGREGATED


def test_api_streams_without_a_built_bfd_uses_the_flowsheet(aggregate):
    (aggregate.root / "process/BFD.xml").unlink()
    data = _streams_api(aggregate.root)
    assert data["bfd_connections"] == AGGREGATED and data["bfd_connections_from"] == "flowsheet"
