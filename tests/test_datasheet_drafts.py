"""Draft datasheets from the lists, the P&IDs and the flowsheet (``cheme datasheets draft``):
every value with its source, unknowns TBD, only missing files written, drafts not counted by
the datasheets gate."""

from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from chemeascode.domains.equipment.datasheets import draft_datasheet
from chemeascode.domains.equipment.schemas.datasheet import Datasheet
from chemeascode.domains.equipment.schemas.equipment import EquipmentItem
from chemeascode.foundation.workspace import Workspace
from chemeascode.interfaces.cli import app
from chemeascode.project.checks import run_checks
from chemeascode.project.datasheets import draft_missing
from chemeascode.project.validate import validate_workspace

runner = CliRunner()

PUMP = {
    "tag": "P4711",
    "type": "CentrifugalPump",
    "service": "Feed pump",
    "design_pressure_barg": 10,
    "material": "1.4408",
    "dimensions": {"length": 1.2, "width": 0.5, "height": 0.8, "weight": 0.4},
}
TANK = {
    "tag": "T4750",
    "type": "Tank",
    "design_pressure_barg": 0.05,
    "dimensions": {"diameter": 4.0, "height": 6.0},
}


def test_a_draft_carries_its_sources_and_tbd_values():
    item = EquipmentItem.model_validate(PUMP)
    nozzles = [{"name": "N1", "dn": 80, "lines": ["L-1"], "sheet": "pid/P-01.xml"}]
    streams = [
        {
            "id": "S1",
            "title": "Feed",
            "direction": "in",
            "state": {"temperature": {"value": 25.0, "provenance": "given", "source": "basis"}},
        },
        {
            "id": "S2",
            "title": "Out",
            "direction": "out",
            "state": {"pressure": {"value": 6.0, "provenance": "assumed", "source": "D-4"}},
        },
    ]
    text = draft_datasheet(
        item, nozzles, streams, {"temperature": "degC", "pressure": "bar(a)"}, "design"
    )
    assert text.startswith("# DRAFT datasheet")
    data = yaml.safe_load(text)
    sheet = Datasheet.model_validate(data)  # the schema takes a draft as it is
    assert sheet.draft and sheet.tag == "P4711"
    assert data["design"]["pressure_barg"] == {
        "value": 10.0,
        "unit": "barg",
        "source": "equipment/equipment-list.yaml",
    }
    assert data["design"]["temperature_degc"]["value"] == "TBD"
    assert data["operating"]["inlet_temperature"]["value"] == 25.0
    assert "stream S1 (case design)" in data["operating"]["inlet_temperature"]["source"]
    assert data["operating"]["outlet_pressure"]["assumed"] is True
    assert data["nozzles"] == [{"name": "N1", "dn": 80, "lines": ["L-1"], "source": "pid/P-01.xml"}]
    specific = data["type_specific"]
    assert specific["shaft_power_kw"]["value"] == "TBD"
    assert specific["weight_t"]["value"] == 0.4
    # every value names where it comes from
    for part in ("operating", "design", "materials"):
        for value in data[part].values():
            assert value["source"], (part, value)


def test_a_vessel_volume_from_dimensions_is_marked_assumed():
    data = yaml.safe_load(draft_datasheet(EquipmentItem.model_validate(TANK), [], []))
    volume = data["type_specific"]["volume_m3"]
    assert volume["value"] == 75.398 and volume["assumed"] is True  # pi/4 x 16 x 6
    assert data["operating"]["conditions"]["value"] == "TBD"
    assert data["materials"]["main"]["value"] == "TBD"


def test_a_horizontal_vessel_volume_runs_along_its_length():
    drum = {
        **TANK,
        "tag": "V4751",
        "type": "PressureVessel",
        "dimensions": {"diameter": 2.0, "length": 8.0, "height": 3.0, "support": "saddles"},
    }
    data = yaml.safe_load(draft_datasheet(EquipmentItem.model_validate(drum), [], []))
    volume = data["type_specific"]["volume_m3"]
    assert volume["value"] == 25.133 and "x length" in volume["source"]  # pi/4 x 4 x 8


def test_the_command_writes_only_missing_drafts(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    (plant / "equipment" / "equipment-list.yaml").write_text(
        yaml.safe_dump({"equipment": [PUMP, TANK]}), encoding="utf-8"
    )
    folder = plant / "equipment" / "datasheets"
    (folder / "T4750.yaml").write_text("tag: T4750\ntype: Tank\n", encoding="utf-8")
    result = runner.invoke(app, ["datasheets", "draft"])
    assert result.exit_code == 0, result.output
    assert "wrote equipment/datasheets/P4711.yaml" in result.output
    assert "kept equipment/datasheets/T4750.yaml" in result.output
    assert (folder / "T4750.yaml").read_text(encoding="utf-8") == "tag: T4750\ntype: Tank\n"
    data = yaml.safe_load((folder / "P4711.yaml").read_text(encoding="utf-8"))
    names = [n["name"] for n in data["nozzles"]]
    assert names == ["N1", "N2"] and data["nozzles"][0]["source"] == "pid/P-01.xml"
    # validate accepts the draft; the datasheets gate does not count it
    report = validate_workspace(Workspace(plant))
    assert not [f for f in report.findings if f.file.startswith("equipment/datasheets/P4711")]
    gates = {c.id: c for c in run_checks(Workspace(plant))}
    assert gates["datasheets"].status == "fail"
    assert "draft datasheets (draft: true) for P4711" in gates["datasheets"].detail
    # a second run writes nothing; an unknown tag is an error
    again = draft_missing(plant)
    assert not again.written and len(again.kept) == 2
    result = runner.invoke(app, ["datasheets", "draft", "--tag", "X-9"])
    assert result.exit_code == 1 and "X-9 is not in the equipment list" in result.output


def test_datasheet_nozzle_locations_are_checked_against_the_layout_model(plant: Path):
    from chemeascode.domains.equipment.datasheets import (
        declares_nozzle_locations,
        nozzle_location_findings,
    )

    folder = plant / "equipment" / "datasheets"
    folder.mkdir(parents=True, exist_ok=True)
    sheet = {
        "tag": "C-1",
        "nozzles": [
            {"name": "N1", "orientation_deg": 270, "face": "side", "elevation_m": 12.5},
            {"name": "N2", "face": "top", "orientation_deg": 90, "offset_m": 2.5},
            {"name": "N3"},
        ],
    }
    (folder / "C-1.yaml").write_text(yaml.safe_dump(sheet), encoding="utf-8")
    workspace = Workspace(plant)
    assert declares_nozzle_locations(workspace)
    nozzle = {"name": "N1", "direction": [0.0, -1.0, 0.0], "base": [72.0, 50.0, 13.5]}
    top = {"name": "N2", "direction": [0.0, 0.0, 1.0], "base": [72.0, 54.5, 26.0]}
    model = {"equipment": [{"tag": "C-1", "position": [72, 52, 1.0], "nozzles": [nozzle, top]}]}
    assert nozzle_location_findings(workspace, model) == []  # 270 deg, 12.5 m above the base
    nozzle["direction"] = [1.0, 0.0, 0.0]
    nozzle["base"] = [74.0, 52.0, 10.0]
    (f,) = nozzle_location_findings(workspace, model)
    assert f.rule == "cheme.datasheet-nozzle-layout" and f.key == "C-1/N1"
    assert "orientation 270 deg here, 0.0 deg in the layout" in f.message
    assert "elevation 12.5 m here, 9.000 m in the layout" in f.message
    top["base"] = [70.0, 52.0, 26.0]  # 2 m west of the centre: bearing and offset differ
    messages = " ".join(f.message for f in nozzle_location_findings(workspace, model))
    assert "orientation 90 deg here, 180.0 deg in the layout" in messages
    assert "offset 2.5 m here, 2.000 m in the layout" in messages
    top["direction"] = [0.0, 1.0, 0.0]
    messages = " ".join(f.message for f in nozzle_location_findings(workspace, model))
    assert "face top here, side in the layout" in messages
    # a nozzle the placement overrides needs a location on the datasheet too
    top["direction"] = [0.0, 0.0, 1.0]
    top["base"] = [72.0, 54.5, 26.0]
    nozzle.update(direction=[0.0, -1.0, 0.0], base=[72.0, 50.0, 13.5])
    model["equipment"][0]["nozzles"].append({"name": "N3", "basis": "override", "base": [0, 0, 0]})
    (f,) = nozzle_location_findings(workspace, model)
    assert f.key == "C-1/N3/missing" and "gives no location" in f.message
    # validate reads the model only when a datasheet declares a location, and reports it
    (plant / "layout").mkdir(exist_ok=True)
    (plant / "layout" / "plant-model.yaml").write_text(yaml.safe_dump(model), "utf-8")
    report = validate_workspace(Workspace(plant))
    assert any(f.rule == "cheme.datasheet-nozzle-layout" for f in report.findings)
    sheet["nozzles"] = [{"name": "N3"}]
    (folder / "C-1.yaml").write_text(yaml.safe_dump(sheet), encoding="utf-8")
    assert not declares_nozzle_locations(workspace)


def test_a_planned_sheet_does_not_hold_back_the_nozzle_checks(plant: Path):
    # a sheet plant.yaml plans (no file yet) draws nothing; the drafts and
    # the viewer's datasheet report still compare the nozzles with the sheets that are drawn
    from chemeascode.project.datasheets import datasheet_report

    path = plant / "plant.yaml"
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    config["sheets"] = [
        {"id": "P-01", "file": "pid/P-01.xml"},
        {"id": "P-02", "file": "pid/P-02.xml", "status": "planned"},
    ]
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    (plant / "equipment" / "equipment-list.yaml").write_text(
        yaml.safe_dump({"equipment": [PUMP]}), encoding="utf-8"
    )
    result = draft_missing(plant)
    assert not [f for f in result.findings if f.rule == "cheme.datasheet-draft-sheet"]
    sheet = plant / "equipment" / "datasheets" / "P4711.yaml"
    data = yaml.safe_load(sheet.read_text(encoding="utf-8"))
    assert [n["dn"] for n in data["nozzles"]] == [80, 80]
    data["nozzles"][1]["dn"] = 100  # P-01 draws N2 DN 80
    sheet.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    report = datasheet_report(plant)
    found = [f for f in report.entry("P4711").findings if f.rule == "cheme.datasheet-nozzle-pid"]
    assert any("DN 100 here, DN 80 on pid/P-01.xml" in f.message for f in found)
    validated = validate_workspace(Workspace(plant)).findings
    assert any(f.rule == "cheme.datasheet-nozzle-pid" for f in validated)
    # a missing sheet that is not planned still holds them back, with the finding
    config["sheets"][1].pop("status")
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    sheet.unlink()
    result = draft_missing(plant)
    assert [f.rule for f in result.findings] == ["cheme.datasheet-draft-sheet"]
