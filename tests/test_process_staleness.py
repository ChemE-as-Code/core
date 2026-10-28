"""Stale and derived stream values are reported and exported honestly: the stream table and the
generated sheets mark or leave out stale propagated and simulated values
(pre-release issues 187, 188), molar and normal-volume flows reach the sheets
(pre-release issue 217), propagated values carry no copied origin or uncertainty
(pre-release issue 218) and go stale with the molar masses they were converted with
(pre-release issue 219), and ``props --fill`` rewrites a property_method block at the end of the
file (pre-release issue 253)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from chemeascode.domains.process.model import load, rules
from chemeascode.domains.process.props import stale
from chemeascode.domains.process.sheets import build
from chemeascode.domains.process.streams import rows, stream_csv, stream_markdown
from chemeascode.foundation.workspace import Workspace
from chemeascode.project.validate import validate_workspace
from tests.test_process_simulate import fake

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def _copy(tmp_path: Path, name: str) -> Workspace:
    shutil.copytree(EXAMPLES / name, tmp_path / name, ignore=shutil.ignore_patterns("build"))
    return Workspace(tmp_path / name)


def _replace(ws: Workspace, path: str, old: str, new: str) -> None:
    file = ws.root / path
    text = file.read_text()
    assert old in text, old
    file.write_text(text.replace(old, new, 1))


def _process(ws: Workspace):
    process, found = load(ws.root)
    assert process is not None, [f.format() for f in found]
    return process


def _stale_ids(ws: Workspace) -> set[str]:
    found = validate_workspace(ws).findings
    return {f.ids[0] for f in found if f.rule == "cheme.process-calculated-stale"}


def _state(ws: Workspace, sid: str) -> dict:
    data = yaml.safe_load((ws.root / "process/flowsheet.yaml").read_text())
    return next(s for s in data["streams"] if s["id"] == sid).get("state", {}).get("design", {})


# -- pre-release issue 187: stale propagated values in the stream table and the sheets -------------


@pytest.fixture
def ammonia_stale(tmp_path):
    """process-ammonia with the reactor's approach changed: S3's propagated composition (and
    what follows from it) no longer matches its inputs."""
    ws = _copy(tmp_path, "process-ammonia")
    assert not _stale_ids(ws)
    _replace(ws, "process/flowsheet.yaml", "approach: 20", "approach: 60")
    return ws


def test_stream_table_marks_stale_propagated_values(ammonia_stale):
    process = _process(ammonia_stale)
    s3 = next(s for s in process.flowsheet.streams if s.id == "S3")
    assert "composition" in stale(process, s3, "design")
    row = next(r for r in rows(process, "design") if r["stream"] == "S3")
    assert row["composition"].endswith("[C STALE]")
    s3_md = next(
        line for line in stream_markdown(process, "design").splitlines() if "| S3 |" in line
    )
    assert "[C STALE]" in s3_md
    s3_csv = next(line for line in stream_csv(process, "design").splitlines() if line[:3] == "S3,")
    assert "[C STALE]" in s3_csv


def test_sheet_leaves_out_what_it_lists_as_stale(ammonia_stale):
    from pydexpi.loaders.public import load_xml_with_report

    process = _process(ammonia_stale)
    s3 = next(s for s in process.flowsheet.streams if s.id == "S3")
    old = stale(process, s3, "design")
    assert "composition" in old
    assert not build(ammonia_stale, force=True).failed
    sheet = ammonia_stale.root / "process/PFD.xml"
    model = load_xml_with_report(sheet.read_bytes()).model
    conn = next(c for c in model.conceptualModel.processConnections if c.identifier == "S3")
    state = conn.materialStateReference.state
    lines = [str(t) for t in state.description] if state.description else []
    assert any(f"stale, not exported (design): {', '.join(sorted(old))}" in t for t in lines)
    # every value it lists as stale is left out
    comp = state.composition
    assert comp is None or not (comp.moleFractions or comp.massFractions or comp.moleFlow)
    for name, prop in (
        ("flow", "massFlow"),
        ("pressure", "pressure"),
        ("temperature", "temperature"),
    ):
        if name in old:
            assert not getattr(conn, prop)


# -- pre-release issue 188: values written by cheme process simulate -------------------------------


def test_simulated_values_go_stale_when_the_model_changes(tmp_path):
    from chemeascode.domains.process.simulation.run import run as simulate

    ws = _copy(tmp_path, "process-simulation")
    result = simulate(ws, _process(ws), "design", write=True, solver=fake)
    assert not [f for f in result.findings if f.level == "error"], result.findings
    simulated = ("S2", "S3", "S4", "S5", "W1")
    process = _process(ws)
    assert all(not stale(process, s, "design") for s in process.flowsheet.streams)
    assert not _stale_ids(ws)

    sim = ws.root / "process/simulation.yaml"
    data = yaml.safe_load(sim.read_text())
    data["specs"]["K1"]["efficiency"]["value"] = 0.5
    sim.write_text(yaml.safe_dump(data, sort_keys=False))

    process = _process(ws)
    by_id = {s.id: s for s in process.flowsheet.streams}
    assert stale(process, by_id["S2"], "design") == [
        "temperature",
        "pressure",
        "flow",
        "composition",
    ]
    assert stale(process, by_id["W1"], "design") == ["duty"]
    assert not stale(process, by_id["S1"], "design")  # the feed is given
    assert _stale_ids(ws) == set(simulated)
    row = next(r for r in rows(process, "design") if r["stream"] == "S2")
    assert "STALE" in row["temperature"] and "STALE" in row["composition"]
    assert "STALE" in next(r for r in rows(process, "design") if r["stream"] == "W1")["duty"]


def test_simulated_values_go_stale_with_a_feed_and_api_streams_list_them(tmp_path):
    from chemeascode.domains.process.simulation.run import run as simulate
    from chemeascode.domains.process.streams import stream_report, stream_table

    ws = _copy(tmp_path, "process-simulation")
    simulate(ws, _process(ws), "design", write=True, solver=fake)
    flowsheet = ws.root / "process/flowsheet.yaml"
    data = yaml.safe_load(flowsheet.read_text())
    s1 = next(s for s in data["streams"] if s["id"] == "S1")
    s1["state"]["design"]["temperature"]["value"] += 40
    flowsheet.write_text(yaml.safe_dump(data, sort_keys=False))
    assert _stale_ids(ws) == {"S2", "S3", "S4", "S5", "W1"}
    expected = ["temperature", "pressure", "flow", "composition"]
    report = stream_report(ws.root)  # process streams --json
    assert next(s for s in report.streams if s["id"] == "S3")["stale"] == expected
    table = stream_table(report.process, "design", {}, set())  # /api/streams
    s3 = next(s for s in table["streams"] if s["id"] == "S3")
    assert s3["stale"] == sorted(expected)
    assert s3["properties"]["temperature"]["stale"] and s3["properties"]["flow"]["stale"]


def test_simulated_values_no_longer_simulated_are_stale(tmp_path):
    from chemeascode.domains.process.simulation.run import run as simulate

    ws = _copy(tmp_path, "process-simulation")
    simulate(ws, _process(ws), "design", write=True, solver=fake)
    (ws.root / "process/simulation.yaml").unlink()
    assert _stale_ids(ws) == {"S2", "S3", "S4", "S5", "W1"}


def test_api_streams_sees_simulated_values_as_current_and_stale(tmp_path):
    """``cheme serve`` loads a revision from a temporary copy: the simulation file goes with it,
    so /api/streams judges simulated values as the CLI does."""
    from fastapi.testclient import TestClient

    from chemeascode.domains.process.simulation.run import run as simulate
    from chemeascode.interfaces.api.serve import create_app
    from tests.conftest import git

    ws = _copy(tmp_path, "process-simulation")
    simulate(ws, _process(ws), "design", write=True, solver=fake)
    root = ws.root
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "simulated")
    client = TestClient(create_app(root, allowed_hosts=["testserver"]))

    def stale_by_stream() -> dict[str, list[str]]:
        response = client.get("/api/streams")
        assert response.status_code == 200, response.text
        return {s["id"]: s["stale"] for s in response.json()["streams"]}

    assert stale_by_stream() == {sid: [] for sid in ("S1", "S2", "S3", "S4", "S5", "W1")}
    sim = root / "process/simulation.yaml"
    data = yaml.safe_load(sim.read_text())
    data["specs"]["K1"]["efficiency"]["value"] = 0.5
    sim.write_text(yaml.safe_dump(data, sort_keys=False))
    git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "efficiency")
    found = stale_by_stream()
    assert found["S2"] == ["composition", "flow", "pressure", "temperature"]
    assert found["W1"] == ["duty"] and found["S1"] == []
    s2 = next(s for s in client.get("/api/streams").json()["streams"] if s["id"] == "S2")
    assert s2["composition"]["stale"] and s2["properties"]["temperature"]["stale"]


# -- pre-release issue 217: molar and normal-volume flows in the sheets ----------------------------


def _sheet_flows(ws: Workspace, sheet: str, sid: str) -> dict[str, list]:
    from pydexpi.loaders.public import load_xml_with_report

    assert not build(ws, force=True).failed
    model = load_xml_with_report((ws.root / f"process/{sheet}.xml").read_bytes()).model
    conn = next(c for c in model.conceptualModel.processConnections if c.identifier == sid)
    state = conn.materialStateReference
    mole = state.state.composition.moleFlow if state and state.state.composition else []
    return {"massFlow": conn.massFlow, "volumeFlow": conn.volumeFlow, "moleFlow": mole}


def test_molar_flow_with_mass_fractions_reaches_the_sheet(tmp_path):
    from chemeascode.domains.process.model import stream_flows

    ws = _copy(tmp_path, "process-blocks")
    process = _process(ws)
    s1 = next(s for s in process.flowsheet.streams if s.id == "S1")
    assert s1.state["design"].composition.basis == "mass_fraction"
    kg_h = stream_flows(process, s1, "design").total
    data = yaml.safe_load((ws.root / "process/flowsheet.yaml").read_text())
    stream = next(s for s in data["streams"] if s["id"] == "S1")
    mw = 1 / sum(
        x / next(c["molar_mass"] for c in _components(ws) if c["id"] == n)
        for n, x in stream["state"]["design"]["composition"]["values"].items()
    )
    stream["state"]["design"]["flow"] = {
        "value": round(kg_h / mw, 4),
        "unit": "kmol/h",
        "provenance": "given",
    }
    (ws.root / "process/flowsheet.yaml").write_text(yaml.safe_dump(data, sort_keys=False))
    flows = _sheet_flows(ws, "BFD", "S1")
    assert len(flows["massFlow"]) == 1
    assert flows["massFlow"][0].value.value == pytest.approx(kg_h, rel=1e-4)
    assert "kmol/h" in flows["massFlow"][0].displayText


def _components(ws: Workspace) -> list[dict]:
    return yaml.safe_load((ws.root / "process/materials.yaml").read_text())["components"]


def test_normal_volume_flow_is_not_exported_as_actual_volume(tmp_path):
    ws = _copy(tmp_path, "process-ammonia")
    data = yaml.safe_load((ws.root / "process/flowsheet.yaml").read_text())
    data["units"]["normal_conditions"] = {"temperature": 273.15, "pressure": 101.325}
    s1 = next(s for s in data["streams"] if s["id"] == "S1")
    kmol_h = s1["state"]["design"]["flow"]["value"]
    assert s1["state"]["design"]["flow"].get("unit", data["units"].get("flow")) == "kmol/h"
    nm3_h = kmol_h * 8.314462618 * 273.15 / 101.325
    s1["state"]["design"]["flow"] = {"value": nm3_h, "unit": "Nm3/h", "provenance": "given"}
    (ws.root / "process/flowsheet.yaml").write_text(yaml.safe_dump(data, sort_keys=False))
    flows = _sheet_flows(ws, "PFD", "S1")
    assert not flows["volumeFlow"]
    total = sum(q.value.value for q in flows["moleFlow"]) * 3600.0
    assert total == pytest.approx(kmol_h, rel=1e-9)
    assert "Nm3/h" not in flows["moleFlow"][0].displayText  # it shows the kmol/h


# -- pre-release issue 218: propagated values carry no origin or uncertainty -----------------------


def test_propagate_drops_the_origin_and_uncertainty_of_copied_values(tmp_path):
    from tests.test_issue50 import FLOWSHEET, _plant, _run

    text = FLOWSHEET.replace(
        "        flow: {value: 1000, provenance: assumed}\n",
        "        flow: {value: 1000, provenance: given, source: flow meter FT-101, "
        "origin: measured, uncertainty: {gsd2: 1.05}}\n",
        1,
    )
    assert text != FLOWSHEET
    ws = _plant(tmp_path, text)
    _run(ws)
    s2, s5, s6 = _state(ws, "S2"), _state(ws, "S5"), _state(ws, "S6")
    for flow in (s2["flow"], s5["flow"], s6["flow"]):  # pass-through, split, remainder
        assert flow["provenance"] == "calculated"
        assert "origin" not in flow and "uncertainty" not in flow
    findings = validate_workspace(ws).findings
    assert not [f.format() for f in findings if f.rule == "cheme.provenance-origin"]


# -- pre-release issue 219: propagated fingerprints include the molar masses they were converted
#    with ------------------------------------------------------------------------------------------


def test_molar_mass_change_makes_mixer_outlet_stale(tmp_path):
    ws = _copy(tmp_path, "process-ammonia")
    assert not _stale_ids(ws)
    _replace(ws, "process/materials.yaml", "molar_mass: 2.016", "molar_mass: 4.032")
    process = _process(ws)
    s2 = next(s for s in process.flowsheet.streams if s.id == "S2")
    assert "flow" in stale(process, s2, "design")
    assert "S2" in {f.ids[0] for f in rules(process) if f.rule == "cheme.process-calculated-stale"}


def test_values_converted_without_molar_masses_keep_their_fingerprints(tmp_path):
    """Pass-through values, split fractions and flows summed from mass flows keep the
    fingerprints they had before (taken from the code before pre-release issue 219): no stale wave
    for them."""
    from tests.test_issue50 import _plant, _run

    ws = _plant(tmp_path)
    _run(ws)
    s2, s4, s5, s6 = (_state(ws, s) for s in ("S2", "S4", "S5", "S6"))
    assert s2["flow"]["fingerprint"] == s2["composition"]["fingerprint"] == "386e008765212069"
    assert s4["flow"]["fingerprint"] == "676f15e184bbf3ca"  # mixer of kg/h flows
    assert s5["flow"]["fingerprint"] == "c056e7af20ac29b6"  # split fraction
    assert s6["flow"]["fingerprint"] == "4e1c46cc627daab7"  # remainder of kg/h flows
    assert s5["composition"]["fingerprint"] == "47451c9503f40f47"
    # the mixed composition is converted with the molar masses (mole fractions): it now
    # depends on them
    assert s4["composition"]["fingerprint"] != "676f15e184bbf3ca"


# -- pre-release issue 253: property_method at the end of materials.yaml without a newline ---------


def test_write_method_without_trailing_newline(tmp_path):
    from chemeascode.domains.process.fill import _write_method
    from chemeascode.domains.process.schema import PropertyMethod

    path = tmp_path / "materials.yaml"
    path.write_text("schema: x\nproperty_method:\n  adapter: thermo\n  status: placeholder")
    _write_method(path, PropertyMethod(adapter="thermo", status="configured", eos="PR"))
    text = path.read_text()
    assert text.count("status:") == 1 and "placeholder" not in text
    assert yaml.safe_load(text)["property_method"]["status"] == "configured"
