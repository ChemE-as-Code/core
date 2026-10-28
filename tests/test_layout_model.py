"""The generated 3D model ``layout/plant-model.yaml``: nozzles from the P&ID, the build, its
provenance findings, ``cheme layout build`` and ``/api/layout``."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from lxml import etree
from typer.testing import CliRunner

from chemeascode.domains.piping import dexpi_io
from chemeascode.domains.spatial.model import (
    BuildError,
    build_model,
    model_findings,
    output_fingerprint,
    read,
    write_model,
)
from chemeascode.domains.spatial.pid_nozzles import sheet_equipment, side_of
from chemeascode.domains.spatial.schemas import LayoutModelFile
from chemeascode.foundation.workspace import Workspace
from chemeascode.interfaces.cli import app
from chemeascode.project.impact import review_needed
from chemeascode.project.validate import validate_workspace
from tests.conftest import DATA, git

SHEET = DATA / "layout_nozzles.xml"
FIXTURE = DATA / "api-layout-asu.json"
runner = CliRunner()

EQUIPMENT = """\
equipment:
  - {tag: V-101, type: PressureVessel, sheet: P-01, dimensions: {diameter: 2, height: 8}}
  - {tag: P-101, type: CentrifugalPump, sheet: P-01,
     dimensions: {length: 1.6, width: 0.7, height: 1.0}}
"""
SITE = """\
site: {name: Test, width: 40, depth: 30}
areas:
  - {id: A1, box: [2, 2, 38, 28]}
racks:
  - {id: PR-1, points: [[5, 15], [35, 15]], width: 3, levels: [5]}
separations:
  - {from: V-101, to: P-101, min_m: 2, basis: test}
"""
PLACEMENT = """\
equipment:
  - {tag: V-101, position: [10, 10, 0]}
  - {tag: P-101, position: [14, 10, 0], rotation_deg: 90}
"""


@pytest.fixture
def layout_plant(plant: Path) -> Path:
    shutil.copy(SHEET, plant / "pid" / "P-01.xml")
    (plant / "equipment" / "equipment-list.yaml").write_text(EQUIPMENT)
    (plant / "layout" / "site-plan.yaml").write_text(SITE)
    (plant / "layout" / "equipment-placement.yaml").write_text(PLACEMENT)
    return plant


def nozzles(model, tag):
    item = next(e for e in model.document["equipment"] if e["tag"] == tag)
    return {n["name"]: n for n in item["nozzles"]}


# -- nozzles from the P&ID -----------------------------------------------------------------


def test_nozzles_and_their_sides_from_the_sheet():
    model = dexpi_io.load(SHEET.read_bytes()).model
    found = sheet_equipment(model, "pid/P-01.xml")
    assert set(found) == {"V-101", "P-101"}
    vessel = found["V-101"]
    assert vessel.cls == "PressureVessel" and vessel.dexpi_id == "V101" and vessel.drawn_tall
    sides = {n.name: n.side for n in vessel.nozzles}
    assert sides == {
        "N1": "top",
        "N2": "bottom",
        "N3": "left",
        "N4": "left",
        "N5": "right",
        "N6": "right",
    }
    by_name = {n.name: n for n in vessel.nozzles}
    assert by_name["N1"].dn == 100 and by_name["N3"].dn == 150
    assert by_name["N2"].lines == ("80-P-101",) and by_name["N2"].segments == ("Line_80P101_S1",)
    assert by_name["N5"].offset[1] < 0 < by_name["N6"].offset[1]  # N5 drawn higher (y down)
    assert {"N1", "V101_N1"} <= vessel.names
    pump = {n.name: n for n in found["P-101"].nozzles}
    assert pump["N1"].side == "left" and pump["N2"].side == "top"
    assert side_of(0.01, -0.02) is None and side_of(0.9, 0.2) == "right"


# -- the build -------------------------------------------------------------------------------


def test_build_places_nozzles_from_the_pid_sides(layout_plant: Path):
    model = build_model(Workspace(layout_plant))
    counts = ("items", "pid", "default", "override", "envelopes")
    assert {k: model.stats[k] for k in counts} == {
        "items": 2,
        "pid": 8,
        "default": 0,
        "override": 0,
        "envelopes": 2,
    }
    every = [p for item in model.document["equipment"] for p in item["parts"]]
    assert model.stats["parts"] == len(every)
    assert len([p for p in every if p.get("lod") != 2]) == 11  # the envelope: 4 + 7
    LayoutModelFile.model_validate(model.document)  # the contract
    vessel = nozzles(model, "V-101")
    top, bottom = vessel["N1"], vessel["N2"]
    assert top["direction"] == [0.0, 0.0, 1.0] and top["base"][2] == pytest.approx(8, abs=0.01)
    assert top["point"][2] == pytest.approx(8 + 0.15 + 0.114 / 2, abs=0.01)  # the flange face
    assert bottom["direction"] == [0.0, 0.0, -1.0] and bottom["point"][2] > 0
    assert vessel["N3"]["direction"][0] == pytest.approx(-1)  # drawn left: own -x
    assert vessel["N3"]["point"] != vessel["N4"]["point"]  # same spot on the P&ID: spread
    assert vessel["N5"]["point"][2] > vessel["N6"]["point"][2]  # drawn higher, sits higher
    assert top["dn"] == 100 and top["basis"] == "pid" and top["side"] == "top"
    assert bottom["refs"] == {
        "tag": "V-101",
        "dexpi": "V101_N2",
        "sheet": "pid/P-01.xml",
        "lines": ["80-P-101"],
        "segments": ["Line_80P101_S1"],
    }
    pump = nozzles(model, "P-101")  # turned 90 degrees: its suction end (own -x) faces south
    assert pump["N1"]["direction"] == pytest.approx([0, -1, 0], abs=1e-3)
    assert pump["N2"]["direction"] == [0.0, 0.0, 1.0]
    item = model.document["equipment"][1]
    assert item["family"] == "pump" and item["size_from"] == "list"
    assert [e["kind"] for e in item["envelopes"]] == ["motor_removal", "access"]
    assert {p["id"] for p in item["parts"]} >= {"P-101/casing", "P-101/motor"}
    assert model.document["site"]["source"] == "declared"
    (pipe,) = [p for p in model.document["pipes"] if p["line"] == "80-P-101"]
    assert pipe["refs"]["sheet"] == "pid/P-01.xml" and model.document["zones"] == []
    sources = model.document["provenance"]["sources"]
    assert set(sources) == {
        "equipment/equipment-list.yaml",
        "layout/equipment-placement.yaml",
        "layout/site-plan.yaml",
        "pid/P-01.xml",
        "piping/line-list.yaml",  # the template's
    }
    assert all(v.startswith("sha256:") for v in sources.values())


def test_every_object_has_id_refs_and_source(layout_plant: Path):
    document = build_model(Workspace(layout_plant)).document
    objects = [document["site"], *document["areas"], *document["racks"]]
    for item in document["equipment"]:
        objects += [item, *item["parts"], *item["nozzles"], *item["envelopes"]]
    for obj in objects:
        assert obj["id"] and isinstance(obj["refs"], dict), obj
        assert obj["source"] in ("generated", "declared", "pinned"), obj


def test_overrides_win_and_unknown_nozzles_are_errors(layout_plant: Path):
    (layout_plant / "layout" / "equipment-placement.yaml").write_text(
        "equipment:\n"
        "  - tag: V-101\n"
        "    position: [10, 10, 0]\n"
        "    nozzles:\n"
        "      - {id: N3, angle_deg: 90, elevation: 4}\n"
        "      - {id: V101_N5, face: top, offset: [0.5, 0]}\n"
        "      - {id: N9, face: bottom}\n"
        "  - {tag: P-101, position: [14, 10, 0]}\n"
    )
    model = build_model(Workspace(layout_plant))
    vessel = nozzles(model, "V-101")
    assert vessel["N3"]["basis"] == "override" and vessel["N3"]["source"] == "declared"
    assert vessel["N3"]["base"] == [10.0, 11.0, 4.0] and "side" not in vessel["N3"]
    assert vessel["N5"]["basis"] == "override" and vessel["N5"]["direction"] == [0.0, 0.0, 1.0]
    (unknown,) = [f for f in model.findings if f.rule == "cheme.layout-nozzle-unknown"]
    assert unknown.level == "error" and unknown.line == 7 and "N9" in unknown.message
    assert model.stats["override"] == 2
    report = validate_workspace(Workspace(layout_plant))
    found = [f for f in report.findings if f.rule == "cheme.layout-nozzle-unknown"]
    assert len(found) == 1 and found[0].line == 7


def test_a_nozzle_without_a_drawn_position_is_placed_by_default(layout_plant: Path):
    sheet = layout_plant / "pid" / "P-01.xml"
    tree = etree.parse(str(sheet))
    (group,) = tree.xpath("//Object[@id='V101_N6_Drawing']")
    group.getparent().remove(group)
    tree.write(str(sheet), xml_declaration=True, encoding="utf-8")
    model = build_model(Workspace(layout_plant))
    n6 = nozzles(model, "V-101")["N6"]
    assert n6["basis"] == "default" and "side" not in n6
    (note,) = [f for f in model.findings if f.rule == "cheme.layout-nozzle-defaulted"]
    assert note.level == "info" and "1 of 6 nozzles" in note.message and note.ids == ["V-101"]


def test_an_item_on_no_pid_has_no_nozzles(layout_plant: Path):
    (layout_plant / "equipment" / "equipment-list.yaml").write_text(
        EQUIPMENT + "  - {tag: T-1, type: Tank, dimensions: {diameter: 4, height: 6}}\n"
    )
    (layout_plant / "layout" / "equipment-placement.yaml").write_text(
        PLACEMENT + "  - {tag: T-1, position: [25, 20, 0]}\n"
    )
    model = build_model(Workspace(layout_plant))
    assert nozzles(model, "T-1") == {}
    assert any("T-1 is drawn on no P&ID" in f.message for f in model.findings)


def test_the_build_refuses_without_or_with_invalid_layout_files(plant: Path):
    with pytest.raises(BuildError, match="no layout files"):
        build_model(Workspace(plant))
    (plant / "layout" / "site-plan.yaml").write_text("site: {width: -1, depth: 3}\n")
    with pytest.raises(BuildError) as failure:
        build_model(Workspace(plant))
    assert failure.value.findings[0].rule == "yaml.schema"


def test_rebuild_is_byte_identical(layout_plant: Path):
    workspace = Workspace(layout_plant)
    first = build_model(workspace).text()
    second = build_model(workspace).text()
    assert first == second
    path, changed = write_model(workspace, build_model(workspace))
    assert changed and path.read_text() == first
    assert write_model(workspace, build_model(workspace)) == (path, False)
    assert first.startswith("# Generated by `cheme layout build`")
    document = read(first)
    assert document["schema"] == "cheme/layout_model/v1"
    assert document["provenance"]["output_sha256"] == output_fingerprint(document)
    # numbers are rounded to the millimetre
    numbers = [
        v
        for item in document["equipment"]
        for nozzle in item["nozzles"]
        for v in nozzle["point"] + nozzle["direction"]
    ]
    assert all(round(v, 3) == v for v in numbers)


# -- provenance findings and impact ------------------------------------------------------------


def rules(workspace):
    return [f.rule for f in model_findings(workspace)]


def test_missing_current_outdated_edited_and_version(layout_plant: Path):
    workspace = Workspace(layout_plant)
    assert rules(workspace) == ["cheme.layout-model-missing"]
    write_model(workspace, build_model(workspace))
    assert rules(workspace) == []
    assert review_needed(workspace) == []
    # an input changes: outdated (validate) and review needed (impact)
    placement = layout_plant / "layout" / "equipment-placement.yaml"
    placement.write_text(PLACEMENT.replace("[10, 10, 0]", "[11, 10, 0]"))
    (outdated,) = model_findings(workspace)
    assert outdated.rule == "cheme.layout-model-outdated" and outdated.level == "warning"
    assert "layout/equipment-placement.yaml changed" in outdated.message
    (impact,) = review_needed(workspace)
    assert impact.file == "layout/plant-model.yaml" and impact.rule == "cheme.review-needed"
    write_model(workspace, build_model(workspace))
    # a new input file counts as a change
    (layout_plant / "layout" / "building.yaml").write_text("buildings: []\n")
    assert rules(workspace) == ["cheme.layout-model-outdated"]
    write_model(workspace, build_model(workspace))
    # an edit of the model itself
    path = layout_plant / "layout" / "plant-model.yaml"
    text = path.read_text()
    path.write_text(text.replace("width: 40.0", "width: 41.0", 1))
    (edited,) = model_findings(workspace)
    assert edited.rule == "cheme.layout-model-edited" and edited.level == "error"
    # comments and formatting are not an edit
    path.write_text(text + "# a comment\n")
    assert rules(workspace) == []
    # another generator version
    path.write_text(text.replace("generator_version: '2'", "generator_version: '0'"))
    assert rules(workspace) == ["cheme.layout-model-version"]
    path.write_text(text.replace(text.split("generator_sha256: ")[1][:12], "000000000000", 1))
    assert rules(workspace) == ["cheme.layout-model-version"]
    path.write_text("equipment: []\n")
    assert rules(workspace) == ["cheme.layout-model-edited"]


def test_validate_reports_the_model_findings(layout_plant: Path):
    workspace = Workspace(layout_plant)
    report = validate_workspace(workspace)
    assert "cheme.layout-model-missing" in [f.rule for f in report.findings]
    write_model(workspace, build_model(workspace))
    report = validate_workspace(workspace)
    assert not [f for f in report.findings if f.rule.startswith("cheme.layout-model")]
    assert "layout/plant-model.yaml" in report.files


def test_validate_and_the_gate_report_an_outdated_lifting_study(layout_plant: Path, monkeypatch):
    from chemeascode.domains.spatial.gates import layout_gate

    def outdated() -> list[str]:
        report = validate_workspace(workspace)
        return sorted(
            f.file for f in report.findings if f.rule == "cheme.layout-lifting-study-outdated"
        )

    monkeypatch.chdir(layout_plant)
    workspace = Workspace(layout_plant)
    write_model(workspace, build_model(workspace))
    assert outdated() == []  # no study written
    git(layout_plant, "add", "-A")
    git(layout_plant, "commit", "-qm", "model")
    assert runner.invoke(app, ["layout", "lifting", "--write"]).exit_code == 0
    assert outdated() == [] and not layout_gate(workspace, ["lifting-current"], [])
    # the model is rebuilt: the study names the old model, lifting --check fails, and so
    # validate and the gate say so
    placement = layout_plant / "layout" / "equipment-placement.yaml"
    placement.write_text(PLACEMENT.replace("[10, 10, 0]", "[11, 10, 0]"))
    write_model(workspace, build_model(workspace))
    assert runner.invoke(app, ["layout", "lifting", "--check"]).exit_code == 1
    (finding,) = [
        f
        for f in validate_workspace(workspace).findings
        if f.rule == "cheme.layout-lifting-study-outdated"
    ]
    assert finding.file == "layout/lifting-study.md" and finding.level == "warning"
    assert "cheme layout lifting --write" in (finding.hint or "")
    (problem,) = layout_gate(workspace, ["lifting-current"], [])
    assert problem.startswith("layout/lifting-study.md is not current")
    assert runner.invoke(app, ["layout", "lifting", "--write"]).exit_code == 0
    assert outdated() == []
    (layout_plant / "layout" / "lifting-study.csv").write_text("tag\n", encoding="utf-8")
    assert outdated() == ["layout/lifting-study.csv"]


# -- the command -----------------------------------------------------------------------------


def test_layout_build_command(layout_plant: Path, monkeypatch):
    monkeypatch.chdir(layout_plant)
    result = runner.invoke(app, ["layout", "build", "--check"])
    assert result.exit_code == 1 and "is not up to date" in result.output
    result = runner.invoke(app, ["layout", "build"])
    assert result.exit_code == 0, result.output
    last = result.output.strip().splitlines()[-1]
    parts = build_model(Workspace(layout_plant)).stats["parts"]
    assert last.startswith(
        f"wrote layout/plant-model.yaml: 2 items, {parts} parts, 8 nozzles (8 placed from the P&ID "
        "side, 0 by default, 0 overridden), 2 envelopes, 1 of 1 segments routed (0 unrouted, "
    ) and last.endswith("3 platforms")
    function = build_model(Workspace(layout_plant)).text()
    assert (layout_plant / "layout" / "plant-model.yaml").read_text() == function
    assert runner.invoke(app, ["layout", "build", "--check"]).exit_code == 0
    assert "unchanged" in runner.invoke(app, ["layout", "build"]).output
    path = layout_plant / "layout" / "plant-model.yaml"
    path.write_text(path.read_text().replace("width: 40.0", "width: 41.0", 1))
    refused = runner.invoke(app, ["layout", "build"])
    assert refused.exit_code == 1 and "--force" in refused.output
    assert runner.invoke(app, ["layout", "build", "--force"]).exit_code == 0
    assert path.read_text() == function
    (layout_plant / "layout" / "site-plan.yaml").write_text("site: {width: 0}\n")
    failed = runner.invoke(app, ["layout", "build"])
    assert failed.exit_code == 1 and "yaml.schema" in failed.output


def test_layout_model_schema_is_listed(layout_plant: Path, monkeypatch):
    monkeypatch.chdir(layout_plant)
    schema = json.loads(runner.invoke(app, ["schema", "layout_model"]).stdout)
    assert {"ModelNozzle", "ModelPart", "ModelEquipment"} <= set(schema["$defs"])
    assert "direction" in schema["$defs"]["ModelNozzle"]["properties"]


def test_build_model_needs_neither_typer_nor_fastapi(layout_plant: Path, tmp_path: Path):
    code = (
        "import sys; from pathlib import Path\n"
        "from chemeascode.foundation.workspace import Workspace\n"
        "from chemeascode.domains.spatial.model import build_model\n"
        f"build_model(Workspace(Path({str(layout_plant)!r})))\n"
        "assert 'typer' not in sys.modules and 'fastapi' not in sys.modules\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True, cwd=tmp_path)


# -- the API ---------------------------------------------------------------------------------


def client(root: Path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from chemeascode.interfaces.api.serve import create_app

    return TestClient(create_app(root, None, allowed_hosts=["testserver"]))


def test_api_layout_returns_the_model_and_separations(layout_plant: Path):
    workspace = Workspace(layout_plant)
    git(layout_plant, "add", "-A")
    git(layout_plant, "commit", "-q", "-m", "layout")
    api = client(layout_plant)
    data = api.get("/api/layout").json()
    assert data["model"] is None
    (separation,) = data["separations"]
    assert separation["from"] == "V-101" and separation["min_m"] == 2.0
    write_model(workspace, build_model(workspace))
    data = api.get("/api/layout").json()
    assert data["model"] == read((layout_plant / "layout" / "plant-model.yaml").read_text())
    pump = next(e for e in data["equipment"] if e["tag"] == "P-101")
    assert pump["family"] == "pump" and pump["size_from"] == "list" and pump["mount"] is None
    assert api.get("/api/layout", params={"rev": "HEAD"}).json()["model"] is None
    described = api.get("/api/yaml", params={"path": "layout/plant-model.yaml"}).json()
    assert described["kind"] == "layout_model" and "ModelNozzle" in described["schema"]["$defs"]
    # an override naming an unknown nozzle is reported by the API too
    (layout_plant / "layout" / "equipment-placement.yaml").write_text(
        PLACEMENT.replace("[10, 10, 0]}", "[10, 10, 0], nozzles: [{id: N9, face: top}]}")
    )
    found = api.get("/api/layout").json()["findings"]
    assert any(f["rule"] == "cheme.layout-nozzle-unknown" for f in found)


def test_the_frozen_api_fixture_follows_the_contract():
    data = json.loads(FIXTURE.read_text())
    assert set(data) >= {
        "site",
        "areas",
        "roads",
        "racks",
        "buildings",
        "equipment",
        "lines",
        "separations",
        "model",
        "findings",
    }
    model = LayoutModelFile.model_validate(data["model"])
    assert model.schema_ == "cheme/layout_model/v1" and model.kind == "layout_model"
    assert [e.tag for e in model.equipment] == [e["tag"] for e in data["equipment"]]
    count = sum(len(e.nozzles) for e in model.equipment)
    assert count == 162
    assert all(n.dn is None or n.dn > 0 for e in model.equipment for n in e.nozzles)
    assert {n.basis for e in model.equipment for n in e.nozzles} == {"pid", "default", "override"}
    directions = [n.direction for e in model.equipment for n in e.nozzles]
    assert all(abs(sum(c * c for c in d) - 1) < 1e-2 for d in directions)
    assert output_fingerprint(data["model"]) == model.provenance.output_sha256


def test_the_model_file_parses_as_yaml_1_1(layout_plant: Path):
    """``on`` is a key of the model's equipment; PyYAML must read it back as text."""
    (layout_plant / "layout" / "building.yaml").write_text(
        "buildings:\n  - {id: B-1, origin: [20, 5], width: 10, depth: 8,"
        " levels: [{id: GF, elevation: 0, height: 5}]}\n"
    )
    (layout_plant / "layout" / "equipment-placement.yaml").write_text(
        PLACEMENT + "  - {tag: V-102, position: [25, 9, 0], mount: {building: B-1, level: GF},"
        " size: [1, 1, 1]}\n"
    )
    text = build_model(Workspace(layout_plant)).text()
    item = yaml.safe_load(text)["equipment"][2]
    assert item["mount"] == {"building": "B-1", "level": "GF"}
