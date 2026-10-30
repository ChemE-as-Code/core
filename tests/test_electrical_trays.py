"""Cable trays and electrical: the electrical list and motor list (control), the cable sizes,
the trays, junction boxes and cable schedule of the 3D model (spatial), their rules, the
drawings, ``cheme layout cables`` and the gate requirements ``cables`` and ``trays``."""

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from chemeascode.domains.control.electrical import (
    actuated_valve,
    cross_check_electrical,
    field_cable,
    full_load_current,
    is_driven,
    motor_list,
    multipair_cable,
    power_cable,
)
from chemeascode.domains.control.schemas import ElectricalList
from chemeascode.domains.equipment.schemas.equipment import EquipmentList
from chemeascode.domains.spatial.drawing2d import render_plan, render_section
from chemeascode.domains.spatial.gates import layout_gate
from chemeascode.domains.spatial.lifting import study
from chemeascode.domains.spatial.model import build_model, model_findings, read, write_model
from chemeascode.domains.spatial.schemas import LayoutModelFile, TrayRuleSet
from chemeascode.domains.spatial.trays import (
    _width,
    cable_schedule,
    schedule_csv,
    tray_findings,
)
from chemeascode.foundation.workspace import Workspace
from chemeascode.interfaces.cli import app
from chemeascode.project.validate import validate_workspace
from tests.conftest import DATA

runner = CliRunner()
SHEET = DATA / "layout_cabling.xml"

EQUIPMENT = """\
equipment:
  - {tag: V-101, type: PressureVessel, sheet: P-01, dimensions: {diameter: 2, height: 8}}
  - {tag: P-101, type: CentrifugalPump, sheet: P-01,
     dimensions: {length: 1.6, width: 0.7, height: 1.0}}
"""
LINES = """\
lines:
  - {number: 80-P-101, from: V-101, to: P-101, nominal_diameter: DN80, fluid: Water}
  - {number: 50-P-102, from: P-101, to: BL, nominal_diameter: DN50, fluid: Water}
"""
INSTRUMENTS = """\
instruments:
  - {tag: PT-101, service: discharge pressure, sheet: P-01}
  - {tag: LT-102, service: level, sheet: P-01}
  - {tag: PI-103, service: local gauge, sheet: P-01}
  - {tag: FIC-104, service: discharge flow, sheet: P-01}
"""
SITE = """\
site: {name: Test, width: 40, depth: 30}
areas:
  - {id: A1, box: [2, 2, 38, 28]}
racks:
  - {id: PR-1, points: [[5, 15], [35, 15]], width: 3, levels: [5]}
"""
PLACEMENT = """\
equipment:
  - {tag: V-101, position: [10, 10, 0]}
  - {tag: P-101, position: [14, 10, 0], rotation_deg: 90}
"""
BUILDING = """\
buildings:
  - {id: SUB-1, origin: [30, 20], width: 6, depth: 5,
     levels: [{id: GF, elevation: 0, height: 4}], walls: all}
"""
ELECTRICAL = """\
rooms:
  - {id: MCC-1, kind: mcc, building: SUB-1}
  - {id: CR-1, kind: control, building: SUB-1}
motors:
  - {driven: P-101, power_kw: 15, source: vendor data}
"""


@pytest.fixture
def cabled(plant: Path) -> Path:
    shutil.copy(SHEET, plant / "pid" / "P-01.xml")
    (plant / "equipment" / "equipment-list.yaml").write_text(EQUIPMENT)
    (plant / "piping" / "line-list.yaml").write_text(LINES)
    (plant / "control" / "instrument-list.yaml").write_text(INSTRUMENTS)
    (plant / "layout" / "site-plan.yaml").write_text(SITE)
    (plant / "layout" / "equipment-placement.yaml").write_text(PLACEMENT)
    (plant / "layout" / "building.yaml").write_text(BUILDING)
    (plant / "electrical").mkdir(exist_ok=True)
    (plant / "electrical" / "electrical-list.yaml").write_text(ELECTRICAL)
    return plant


def _by_id(entries):
    return {e["id"]: e for e in entries}


# -- control: motors, cable sizes, valves -----------------------------------------------------


def test_driven_equipment_and_the_cable_table():
    items = EquipmentList.model_validate(
        yaml.safe_load(
            """
equipment:
  - {tag: P-1, type: CentrifugalPump}
  - {tag: K-1, type: CentrifugalCompressor}
  - {tag: KT-1, type: CentrifugalCompressor, dimensions: {length: 3, width: 2, height: 2,
     variant: compander}}
  - {tag: T-1, type: SteamTurbine}
  - {tag: E-1, type: AirCooledHeatExchanger}
  - {tag: V-1, type: PressureVessel}
"""
        )
    ).equipment
    assert [i.tag for i in items if is_driven(i)] == ["P-1", "K-1", "E-1"]
    # 15 kW at 400 V: about 28 A; with the 0.8 derating the 4 mm2 cable (39 A) carries it
    assert full_load_current(15, 400) == pytest.approx(27.7, abs=0.1)
    small = power_cable(15, 400)
    assert small.size == "4C x 4 mm2" and small.od_mm == 16.6 and small.count == 1
    # an MV motor takes the 3-core MV table; a large one parallel cables of the largest size
    assert power_cable(800, 6600).size.startswith("3C x ")
    big = power_cable(500, 400)
    assert big.count >= 2 and big.size.startswith(f"{big.count} x 4C x 300")
    unknown = power_cable(None, 400)
    assert unknown.size == "4C x 2.5 mm2" and "power unknown" in unknown.basis
    assert field_cable("on_off_valve").pairs == 3 and field_cable("transmitter").pairs == 1
    assert multipair_cable(4, 0.2).pairs == 5  # 4 pairs + 20 % spare -> 5
    assert multipair_cable(100, 0.2).count == 3
    assert actuated_valve("FV-104", "GlobeValve") == "control_valve"
    assert actuated_valve("XV-201", "BallValve") == "on_off_valve"
    assert actuated_valve("SDV-3", "BallValve") == "on_off_valve"
    for manual in ("HV-1", "PSV-2", "PCV-3", "V-12"):
        assert actuated_valve(manual, "GlobeValve") is None, manual
    assert actuated_valve(None, "MotorOperatedValve") == "on_off_valve"


def test_motor_list_powers_from_the_list_and_the_datasheets(cabled: Path):
    workspace = Workspace(cabled)
    (cabled / "equipment" / "equipment-list.yaml").write_text(
        EQUIPMENT + "  - {tag: P-102, type: CentrifugalPump}\n  - {tag: K-1, type: Compressor}\n"
    )
    (cabled / "equipment" / "datasheets").mkdir(exist_ok=True)
    (cabled / "equipment" / "datasheets" / "P-102.yaml").write_text(
        "tag: P-102\ntype_specific:\n  driver_kw: {value: 7.5, assumed: true, source: D-1}\n"
    )
    parsed = workspace.parsed_lists(("equipment", "electrical"))
    electrical = parsed["electrical"]
    motors, _ = motor_list(workspace, parsed["equipment"], electrical)
    by = {m.driven: m for m in motors}
    assert by["P-101"].power_kw == 15 and by["P-101"].basis == "list"
    assert by["P-101"].tag == "M-P-101" and by["P-101"].room == "MCC-1"
    assert by["P-102"].power_kw == 7.5 and by["P-102"].basis == "datasheet"
    assert by["P-102"].assumed and "P-102.yaml driver_kw" in by["P-102"].source
    assert by["K-1"].power_kw is None and by["K-1"].basis == "missing"
    findings = cross_check_electrical(workspace, parsed)
    rules = {(f.rule, tuple(f.ids)) for f in findings}
    assert ("cheme.electrical-motor-power", ("K-1",)) in rules
    # an MV motor goes to the switchgear room when there is one
    electrical = ElectricalList.model_validate(
        yaml.safe_load(
            ELECTRICAL.replace(
                "motors:", "  - {id: SWG-1, kind: switchgear, building: SUB-1}\nmotors:"
            ).replace("power_kw: 15", "power_kw: 900")
        )
    )
    (motor,) = [
        m for m in motor_list(workspace, parsed["equipment"], electrical)[0] if m.driven == "P-101"
    ]
    assert motor.voltage_v == 6600 and motor.room == "SWG-1"


def test_validate_checks_the_electrical_list(cabled: Path):
    (cabled / "electrical" / "electrical-list.yaml").write_text(
        ELECTRICAL
        + "  - {driven: X-9, power_kw: 1, room: MCC-9}\n"
        + "instruments:\n  - {tag: PT-101, jb: JB-9}\n"
    )
    report = validate_workspace(Workspace(cabled))
    found = {f.rule for f in report.findings if f.file == "electrical/electrical-list.yaml"}
    assert {
        "cheme.electrical-unknown-tag",
        "cheme.electrical-unknown-room",
        "cheme.electrical-unknown-jb",
    } <= found
    line = next(f for f in report.findings if f.rule == "cheme.electrical-unknown-tag").line
    assert line == 6
    bad = ElectricalList.model_json_schema()
    assert "rooms" in bad["properties"]
    with pytest.raises(ValueError):
        ElectricalList.model_validate({"rooms": [{"id": "R", "kind": "mcc"}]})


# -- the build ----------------------------------------------------------------------------------


def test_the_build_routes_trays_cables_and_junction_boxes(cabled: Path):
    model = build_model(Workspace(cabled))
    document = model.document
    LayoutModelFile.model_validate(document)
    trays = _by_id(document["trays"])
    cables = _by_id(document["cables"])
    # own tray tier on steel of its own, 1.5 m above the top pipe tier
    (tier,) = document["tray_tiers"]
    assert tier["rack"] == "PR-1" and tier["elevation"] == 6.5
    assert all(p["kind"] == "member" for p in tier["parts"])
    power, instrument = trays["PT-PR-1-1"], trays["IT-PR-1-1"]
    assert {p[2] for p in power["points"]} == {6.5} == {p[2] for p in instrument["points"]}
    # power left of the rack's direction (north of an eastward rack), instrument right
    assert {p[1] for p in power["points"]} == {15.75}
    assert {p[1] for p in instrument["points"]} == {14.25}
    assert power["kind"] == "trunk" and power["width"] == 0.1 and 0 < power["fill"] < 0.3
    # the motor cable: room, trunk, branch, in that order; length with allowances
    motor = cables["C-M-P-101"]
    assert motor["trays"] == ["PT-MCC-1", "PT-PR-1-1", "PT-M-P-101"]
    assert motor["from"] == "MCC-1" and motor["to"] == "M-P-101" and motor["size"] == "4C x 4 mm2"
    run = sum(trays[t]["length"] for t in motor["trays"])
    assert motor["route_length"] >= run
    assert motor["length"] >= motor["route_length"] * 1.05 + 3.0 - 1e-6
    branch = trays["PT-M-P-101"]
    assert branch["kind"] == "branch" and branch["refs"]["tag"] == "P-101"
    assert branch["points"][-1][2] < 3.0 <= max(p[2] for p in branch["points"][1:-1])
    # instruments: the local gauge has none; the flow loop's valve and sensor have one each
    assert "IC-PI-103" not in cables
    assert {"IC-PT-101", "IC-LT-102", "IC-FIC-104", "IC-FV-104"} <= set(cables)
    (jb,) = document["junction_boxes"]
    assert jb["source"] == "generated" and jb["review_needed"] and jb["area"] == "A1"
    assert jb["instruments"] == ["FIC-104", "FV-104", "LT-102", "PT-101"]
    home = cables[f"MC-{jb['tag']}"]
    assert home["from"] == "CR-1" and home["trays"][0] == "IT-CR-1"
    assert home["pairs"] == 5  # 4 pairs in use + 20 % spare
    assert cables["IC-PT-101"]["trays"] == [] and cables["IC-PT-101"]["kind"] == "field"
    assert document["cabling"]["missing"] == []
    # inputs recorded, rebuild byte-identical, findings clean
    sources = document["provenance"]["sources"]
    assert {"electrical/electrical-list.yaml", "control/instrument-list.yaml"} <= set(sources)
    assert build_model(Workspace(cabled)).text() == model.text()
    rules = {f.rule for f in model.findings}
    assert not rules & {
        "cheme.layout-tray-separation",
        "cheme.layout-tray-fill",
        "cheme.layout-clash-tray",
        "cheme.layout-cable-missing",
    }


def test_a_feeder_cable_carries_the_load_current_without_motor_efficiency(cabled: Path):
    # 50 kW at 400 V: a motor draws 92.3 A (pf 0.85, efficiency 0.92) and takes 25 mm2; a
    # resistive heater draws 72.2 A, which 16 mm2 carries (94 A x 0.8 derating = 75.2 A).
    motor = power_cable(50, 400)
    assert motor.current_a == 92.3 and motor.size == "4C x 25 mm2"
    heater = power_cable(50, 400, power_factor=1.0)
    assert heater.current_a == 72.2 and heater.size == "4C x 16 mm2"
    assert power_cable(50, 400, power_factor=0.9).current_a == 80.2
    (cabled / "electrical" / "electrical-list.yaml").write_text(
        ELECTRICAL
        + "feeders:\n"
        + "  - {tag: EH-1, item: P-101, power_kw: 50}\n"
        + "  - {tag: PK-1, item: P-101, power_kw: 50, power_factor: 0.9}\n"
    )
    workspace = Workspace(cabled)
    parsed = workspace.parsed_lists(("equipment", "electrical"))
    by = {m.tag: m for m in motor_list(workspace, parsed["equipment"], parsed["electrical"])[0]}
    assert by["EH-1"].power_factor == 1.0 and by["PK-1"].power_factor == 0.9
    assert by["M-P-101"].power_factor is None  # a motor: the table's pf and efficiency
    cables = _by_id(build_model(workspace).document["cables"])
    assert cables["C-EH-1"]["size"] == "4C x 16 mm2"
    assert "power factor 1 ASSUMED (resistive load)" in cables["C-EH-1"]["basis"]
    assert "power factor 0.9" in cables["C-PK-1"]["basis"]
    assert "ASSUMED" not in cables["C-PK-1"]["basis"]
    assert "power factor" not in cables["C-M-P-101"]["basis"]
    assert cables["C-M-P-101"]["size"] == "4C x 4 mm2"  # the 15 kW motor, as before


def test_no_electrical_list_no_cabling(cabled: Path):
    (cabled / "electrical" / "electrical-list.yaml").unlink()
    document = build_model(Workspace(cabled)).document
    assert not {"trays", "cables", "junction_boxes", "tray_tiers", "cabling"} & set(document)
    assert "control/instrument-list.yaml" not in document["provenance"]["sources"]


def test_a_new_or_changed_electrical_input_outdates_the_model(cabled: Path):
    workspace = Workspace(cabled)
    write_model(workspace, build_model(workspace))
    assert model_findings(workspace) == []
    (cabled / "electrical" / "tray-rules.yaml").write_text("rules: {tier_gap_m: 2.0}\n")
    assert [f.rule for f in model_findings(workspace)] == ["cheme.layout-model-outdated"]
    document = build_model(workspace).document
    assert document["tray_tiers"][0]["elevation"] == 7.0


def test_missing_cables_and_declared_junction_boxes(cabled: Path):
    (cabled / "equipment" / "equipment-list.yaml").write_text(
        EQUIPMENT + "  - {tag: P-102, type: CentrifugalPump}\n"
    )
    (cabled / "electrical" / "electrical-list.yaml").write_text(
        ELECTRICAL
        + "junction_boxes:\n  - {tag: JB-1, point: [20, 8, 1.2], instruments: ['P*']}\n"
        + "instruments:\n  - {tag: LT-102, skip: wireless}\n  - {tag: AT-9, point: [12, 6, 1]}\n"
    )
    model = build_model(Workspace(cabled))
    document = model.document
    missing = {m["tag"]: m["reason"] for m in document["cabling"]["missing"]}
    assert "not placed" in missing["M-P-102"]
    boxes = _by_id(document["junction_boxes"])
    # PT-101 by its pattern, the others as the declared box within reach: none proposed
    assert list(boxes) == ["JB-1"] and boxes["JB-1"]["source"] == "declared"
    assert boxes["JB-1"]["instruments"] == ["AT-9", "FIC-104", "FV-104", "PT-101"]
    assert not boxes["JB-1"].get("review_needed")  # LT-102 skipped, AT-9 placed by the list
    findings = [f for f in model.findings if f.rule == "cheme.layout-cable-missing"]
    assert [f.ids for f in findings] == [["M-P-102"]]


def _lifted(plant: Path, entry: str = "") -> tuple[dict, Any]:
    """The model and the lift of P-101 made heavy (8 t) with a crane pad south of it: its lane
    runs north over the pump from the pad, the motor's tray comes south from the rack."""
    (plant / "equipment" / "equipment-list.yaml").write_text(
        EQUIPMENT.replace("height: 1.0}", "height: 1.0, weight: 8}")
    )
    (plant / "layout" / "zones.yaml").write_text(
        "zones:\n  - {id: CP-1, kind: crane_pad, reach_m: 20, shape: box,\n"
        "     box: [12, 1, 0, 16, 5, 1]}\n"
    )
    (plant / "electrical" / "electrical-list.yaml").write_text(
        ELECTRICAL.replace("source: vendor data}", f"source: vendor data{entry}}}")
    )
    model = build_model(Workspace(plant))
    (lift,) = [x for x in study(model.document).lifts if x.tag == "P-101"]
    return model, lift


def test_a_cable_entry_ends_the_motor_tray_beside_the_machine(cabled: Path):
    # before: the branch runs over the pump to above its terminal box and blocks the lane
    model, lift = _lifted(cabled)
    branch = _by_id(model.document["trays"])["PT-M-P-101"]
    assert "drop_to" not in branch
    assert lift.pad == "CP-1" and lift.blockers == ["PT-M-P-101"]
    item = _by_id([{**e, "id": e["tag"]} for e in model.document["equipment"]])["P-101"]
    x0, y0, _, x1, y1, _ = item["bbox"]
    # after: the tray ends east of the pump, across the lane (margin 1 m + half the 0.1 m tray
    # + spacing), and the cable drops from there to the terminal box
    model, lift = _lifted(cabled, ", cable_entry: {side: east}")
    document = model.document
    branch = _by_id(document["trays"])["PT-M-P-101"]
    end, terminal = branch["points"][-1], branch["drop_to"]
    spacing = TrayRuleSet().spacing_m
    assert end[0] == pytest.approx(x1 + 1.0 + 0.05 + spacing, abs=1e-3)
    assert end[1] == pytest.approx((y0 + y1) / 2, abs=1e-3)
    assert all(p[0] > x1 + 1.0 for p in branch["points"])  # no run over the pump
    assert lift.blockers == [] and lift.status.startswith("lane clear")
    # the schedule's length takes the drop (orthogonal, tray end to terminal box)
    cable = _by_id(document["cables"])["C-M-P-101"]
    trays = _by_id(document["trays"])
    run = sum(trays[t]["length"] for t in cable["trays"])
    drop = sum(abs(a - b) for a, b in zip(end, terminal, strict=True))
    assert cable["to_point"] == terminal
    assert cable["route_length"] == pytest.approx(run + drop, abs=2e-3)
    assert not {f.rule for f in model.findings} & {
        "cheme.layout-clash-tray",
        "cheme.layout-cable-missing",
        "cheme.electrical-cable-entry",
    }
    LayoutModelFile.model_validate(document)
    # an elevation and an absolute point: the tray ends there
    model, lift = _lifted(cabled, ", cable_entry: {point: [17, 10], elevation_m: 3.5}")
    branch = _by_id(model.document["trays"])["PT-M-P-101"]
    assert branch["points"][-1] == [17.0, 10.0, 3.5] and lift.blockers == []
    # a tray still inside the lane counts: an entry on the pad's side, between pad and pump
    model, lift = _lifted(cabled, ", cable_entry: {side: south}")
    assert lift.blockers == ["PT-M-P-101"]


def test_an_impossible_cable_entry_is_an_error_on_its_line(cabled: Path):
    _lifted(cabled, ", cable_entry: {side: north, offset_m: 3}")
    workspace = Workspace(cabled)
    model = build_model(workspace)
    missing = {m["tag"]: m["reason"] for m in model.document["cabling"]["missing"]}
    assert "offset_m 3 is beyond the north side" in missing["M-P-101"]
    assert "PT-M-P-101" not in _by_id(model.document["trays"])
    (finding,) = [f for f in model.findings if f.rule == "cheme.electrical-cable-entry"]
    assert finding.file == "electrical/electrical-list.yaml" and finding.line == 5
    assert finding.hint and finding.ids == ["P-101"]
    write_model(workspace, model)
    report = validate_workspace(workspace)
    (finding,) = [f for f in report.findings if f.rule == "cheme.electrical-cable-entry"]
    assert finding.line == 5 and finding.level == "error"
    model, _ = _lifted(cabled, ", cable_entry: {point: [14, 10]}")
    (finding,) = [f for f in model.findings if f.rule == "cheme.electrical-cable-entry"]
    assert "inside the item's footprint" in finding.message
    # the schema refuses an entry that says neither or both where it is
    for bad in ({}, {"side": "east", "point": [1, 2]}, {"point": [1, 2], "offset_m": 1}):
        with pytest.raises(ValueError, match="cable_entry"):
            ElectricalList.model_validate({"motors": [{"driven": "P-1", "cable_entry": bad}]})
    (cabled / "electrical" / "electrical-list.yaml").write_text(
        ELECTRICAL.replace("vendor data}", "vendor data,\n     cable_entry: {side: up}}")
    )
    report = validate_workspace(Workspace(cabled))
    (finding,) = [f for f in report.findings if f.file == "electrical/electrical-list.yaml"]
    assert finding.level == "error" and finding.line == 6 and finding.hint
    assert "cable_entry" in finding.message


def test_fill_and_separation_rules():
    rules = TrayRuleSet()
    from chemeascode.domains.control.electrical import CableType

    cable = CableType("power", "x", 40.0)
    widths = [_width([cable] * n, rules.fill_max_power, rules) for n in (1, 5, 20, 80)]
    assert [w for w, _ in widths] == [0.1, 0.3, 0.9, 0.9]
    assert widths[-1][1] > rules.fill_max_power  # over the largest width
    model = {
        "trays": [
            {
                "id": "PT-1",
                "refs": {},
                "system": "power",
                "points": [[0, 0, 5], [10, 0, 5]],
                "rack": "PR",
                "width": 0.3,
                "cables": ["C-1"],
                "fill": 0.5,
                "fill_max": 0.3,
            },
            {
                "id": "IT-1",
                "refs": {},
                "system": "instrument",
                "points": [[0, 0.4, 5], [10, 0.4, 5]],
                "rack": "PR",
                "width": 0.2,
                "cables": ["C-2"],
                "fill": 0.1,
                "fill_max": 0.4,
            },
        ],
        "cabling": {"rules": {"separation_m": 0.3}, "missing": []},
    }
    rules_found = sorted(f.rule for f in tray_findings(model))
    assert rules_found == ["cheme.layout-tray-fill", "cheme.layout-tray-separation"]
    model["trays"][1]["points"] = [[0, 1.0, 5], [10, 1.0, 5]]
    model["trays"][0]["fill"] = 0.2
    assert tray_findings(model) == []
    assert tray_findings({"pipes": []}) == []


def test_a_tray_through_an_item_is_a_clash():
    model = {
        "equipment": [
            {
                "tag": "X",
                "parts": [
                    {
                        "id": "X/body",
                        "kind": "box",
                        "material": "shell",
                        "centre": [5, 0, 5],
                        "size": [2, 2, 2],
                        "rotation_deg": 0,
                    }
                ],
            }
        ],
        "trays": [
            {
                "id": "PT-1",
                "refs": {},
                "system": "power",
                "points": [[0, 0, 5], [10, 0, 5]],
                "rack": "PR",
                "width": 0.3,
                "cables": [],
                "fill": 0.1,
                "fill_max": 0.3,
            }
        ],
        "cabling": {"missing": []},
    }
    (finding,) = tray_findings(model)
    assert finding.rule == "cheme.layout-clash-tray" and finding.ids == ["PT-1", "X"]


# -- schedule, drawings, CLI, gates ---------------------------------------------------------------


def test_schedule_drawings_and_command(cabled: Path, monkeypatch):
    monkeypatch.chdir(cabled)
    assert runner.invoke(app, ["layout", "build"]).exit_code == 0
    model = read((cabled / "layout" / "plant-model.yaml").read_text())
    rows = cable_schedule(model)
    assert [r["tag"] for r in rows] == sorted(r["tag"] for r in rows)
    result = runner.invoke(app, ["layout", "cables", "--csv"])
    assert result.exit_code == 0 and result.output == schedule_csv(rows)
    data = json.loads(runner.invoke(app, ["layout", "cables", "--json"]).output)
    assert data["cables"] == rows and data["cabling"]["cables"] == len(rows)
    text = runner.invoke(app, ["layout", "cables"]).output
    assert text.startswith("# Cable schedule") and "| C-M-P-101 | MCC-1 | M-P-101 |" in text
    assert runner.invoke(app, ["layout", "cables", "--check"]).exit_code == 1
    assert runner.invoke(app, ["layout", "cables", "--write"]).exit_code == 0
    assert (cabled / "electrical" / "cable-schedule.csv").read_text() == schedule_csv(rows)
    assert runner.invoke(app, ["layout", "cables", "--check"]).exit_code == 0
    plan = render_plan(model)
    assert 'id="tray-PT-PR-1-1"' in plan and 'id="jb-JB-A1-1"' in plan
    section = render_section(model, "x", 20.0)
    assert 'id="tray-PT-PR-1-1"' in section and 'id="tray-IT-PR-1-1"' in section


def test_cables_and_trays_gate(cabled: Path):
    workspace = Workspace(cabled)
    findings = validate_workspace(workspace).findings
    assert any(
        "no layout/plant-model.yaml" in p for p in layout_gate(workspace, ["cables"], findings)
    )
    write_model(workspace, build_model(workspace))
    findings = validate_workspace(workspace).findings
    assert layout_gate(workspace, ["cables", "trays"], findings) == []
    # an unplaced motor: the gate names it until its finding is accepted
    (cabled / "equipment" / "equipment-list.yaml").write_text(
        EQUIPMENT + "  - {tag: P-102, type: CentrifugalPump}\n"
    )
    write_model(workspace, build_model(workspace))
    findings = validate_workspace(workspace).findings
    (problem,) = layout_gate(workspace, ["cables"], findings)
    assert "M-P-102" in problem
    accept = [{"id": "layout/plant-model.yaml#layout-cable-missing:M-P-102", "reason": "spare"}]
    from chemeascode.foundation.schemas.checks import Accept

    accepted = [Accept.model_validate(a) for a in accept]
    assert layout_gate(workspace, ["cables"], findings, accept=accepted) == []
    (cabled / "electrical" / "electrical-list.yaml").unlink()
    problems = layout_gate(workspace, ["cables"], validate_workspace(workspace).findings)
    assert any("no electrical/electrical-list.yaml" in p for p in problems)


def test_the_template_gate_and_skill():
    from chemeascode.templates.install import bundled_skills

    template = Path(__file__).parents[1] / "src/chemeascode/templates/project"
    checks = yaml.safe_load((template / "checks/checks.yaml").read_text())
    (gate,) = [c for c in checks["checks"] if c["id"] == "electrical"]
    assert gate["stage"] == "detail" and set(gate["require"]) == {
        "model-current",
        "cables",
        "trays",
    }
    assert (template / "electrical/README.md").is_file()
    skill = Path(str(bundled_skills()["electrical-cabling"])) / "SKILL.md"
    assert skill.parent.parent.parent.name == "control"


def test_cabling_needs_neither_typer_nor_fastapi(cabled: Path):
    code = (
        "import sys; from pathlib import Path; "
        "from chemeascode.domains.spatial.model import build_model; "
        "from chemeascode.foundation.workspace import Workspace; "
        f"d = build_model(Workspace(Path({str(cabled)!r}))).document; "
        "assert d['cables']; "
        "assert 'typer' not in sys.modules and 'fastapi' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], check=True, cwd="/")


def test_the_point_along_a_rack_skips_repeated_points_and_needs_a_length():
    from chemeascode.domains.spatial.trays import _along

    assert _along([(0, 0), (0, 0), (10, 0), (10, 10)], 15.0) == (10.0, 5.0, 0.0, 1.0)
    assert _along([(0, 0), (10, 0)], 10.000001) == (10.0, 0.0, 1.0, 0.0)  # its end
    assert _along([(5, 5), (5, 5)], 0.0) is None  # no length: no direction (pre-release issue 236)


# -- several power trays per rack (power_trays) ---------------------------------------------

HEAVY = """\
rooms:
  - {id: MCC-1, kind: mcc, building: SUB-1}
  - {id: SWG-1, kind: switchgear, building: SUB-1}
  - {id: CR-1, kind: control, building: SUB-1}
motors:
  - {driven: P-101, power_kw: 15, source: vendor data}
feeders:
  - {tag: HV-1, item: P-101, power_kw: 3000, voltage_v: 6600, room: SWG-1}
  - {tag: HV-2, item: P-101, power_kw: 3000, voltage_v: 6600, room: SWG-1}
  - {tag: LV-1, item: P-101, power_kw: 250, voltage_v: 400, room: MCC-1}
  - {tag: LV-2, item: P-101, power_kw: 250, voltage_v: 400, room: MCC-1}
"""
NARROW = "rules:\n  widths_mm: [100, 150, 200, 300]\n"


def _power(document):
    return {t["id"]: t for t in document["trays"] if t["system"] == "power"}


def test_one_power_tray_overfills_and_the_hint_names_power_trays(cabled: Path):
    (cabled / "electrical" / "electrical-list.yaml").write_text(HEAVY)
    (cabled / "electrical" / "tray-rules.yaml").write_text(NARROW)
    model = build_model(Workspace(cabled))
    trays = _power(model.document)
    assert trays["PT-PR-1-1"]["fill"] > 0.3 and "voltage" not in trays["PT-PR-1-1"]
    assert "power_trays" not in model.document["cabling"]["rules"]
    (fill,) = [f for f in model.findings if f.rule == "cheme.layout-tray-fill"]
    assert fill.key == "PT-PR-1-1"
    assert "declare 2 power trays on rack PR-1" in fill.hint
    assert "power_trays: [{rack: PR-1, trays: 2}]" in fill.hint


def test_several_power_trays_per_rack_by_voltage_class(cabled: Path):
    (cabled / "electrical" / "electrical-list.yaml").write_text(HEAVY)
    (cabled / "electrical" / "tray-rules.yaml").write_text(
        NARROW + "  power_trays:\n    - {rack: PR-1, trays: [hv, lv]}\n"
    )
    workspace = Workspace(cabled)
    model = build_model(workspace)
    document = model.document
    LayoutModelFile.model_validate(document)
    trays = _power(document)
    hv, lv = trays["PT-PR-1-A-1"], trays["PT-PR-1-B-1"]
    assert "PT-PR-1-1" not in trays
    assert (hv["voltage"], lv["voltage"]) == ("hv", "lv")
    assert hv["cables"] == ["C-HV-1", "C-HV-2"]
    assert lv["cables"] == ["C-LV-1", "C-LV-2", "C-M-P-101"]
    # side by side, centred on the power lane (0.75 m left of the rack at y 15), the largest
    # width (300 mm) and spacing_m (0.15 m) apart; both on the rack's tray tier
    assert {p[1] for p in hv["points"]} == {15.525} and {p[1] for p in lv["points"]} == {15.975}
    assert {p[2] for p in hv["points"]} == {6.5} == {p[2] for p in lv["points"]}
    # the room legs follow the trays; the schedule names each cable's trays
    cables = _by_id(document["cables"])
    assert cables["C-HV-1"]["trays"] == ["PT-SWG-1-A", "PT-PR-1-A-1", "PT-HV-1"]
    assert cables["C-M-P-101"]["trays"] == ["PT-MCC-1-B", "PT-PR-1-B-1", "PT-M-P-101"]
    assert trays["PT-SWG-1-A"]["voltage"] == "hv" and "voltage" not in trays["PT-HV-1"]
    rows = {r["tag"]: r for r in cable_schedule(document)}
    assert rows["C-LV-1"]["trays"] == "PT-MCC-1-B PT-PR-1-B-1 PT-LV-1"
    assert document["cabling"]["rules"]["power_trays"] == {"PR-1": ["hv", "lv"]}
    rules = {f.rule for f in model.findings}
    assert not rules & {
        "cheme.layout-tray-fill",
        "cheme.layout-tray-separation",
        "cheme.layout-tray-voltage",
        "cheme.layout-clash-tray",
    }
    assert build_model(workspace).text() == model.text()
    write_model(workspace, model)
    findings = validate_workspace(workspace).findings
    assert layout_gate(workspace, ["cables", "trays"], findings) == []


def test_power_trays_by_count_share_the_cables_out_by_fill(cabled: Path):
    (cabled / "electrical" / "electrical-list.yaml").write_text(HEAVY)
    (cabled / "electrical" / "tray-rules.yaml").write_text(
        NARROW + "  power_trays:\n    - {rack: PR-1, trays: 2}\n"
    )
    trays = _power(build_model(Workspace(cabled)).document)
    a, b = trays["PT-PR-1-A-1"], trays["PT-PR-1-B-1"]
    # the larger first, each into the emptier tray: one HV cable in each, the LV ones after
    assert "voltage" not in a and "voltage" not in b
    assert {"C-HV-1", "C-HV-2"} & set(a["cables"]) and {"C-HV-1", "C-HV-2"} & set(b["cables"])
    assert max(a["fill"], b["fill"]) <= 0.3


def test_a_cable_without_a_tray_of_its_class_is_a_voltage_finding(cabled: Path):
    (cabled / "electrical" / "electrical-list.yaml").write_text(HEAVY)
    (cabled / "electrical" / "tray-rules.yaml").write_text(
        NARROW + "  power_trays:\n    - {rack: PR-1, trays: [hv, hv]}\n"
    )
    model = build_model(Workspace(cabled))
    voltage = [f for f in model.findings if f.rule == "cheme.layout-tray-voltage"]
    assert voltage and all(f.hint and f.level == "warning" for f in voltage)
    assert any("C-M-P-101" in f.message for f in voltage)


def test_power_trays_are_validated_against_the_site_plan(cabled: Path):
    (cabled / "electrical" / "tray-rules.yaml").write_text(
        "rules:\n"
        "  power_trays:\n"
        "    - {rack: PR-9, trays: 2}\n"
        "    - {rack: PR-1, trays: 3}\n"
        "    - {rack: PR-1, trays: [hv]}\n"
    )
    found = {
        (f.message, f.level, f.line)
        for f in validate_workspace(Workspace(cabled)).findings
        if f.rule == "cheme.layout-tray-rack"
    }
    messages = sorted(found)
    assert any("rack PR-9, which the site plan" in m and lv == "error" for m, lv, _ in messages)
    assert any("listed twice" in m and line == 5 for m, _, line in messages)
    # three 900 mm trays do not fit on the power half of the 3 m rack
    assert any("3 power trays on rack PR-1" in m and lv == "warning" for m, lv, _ in messages)
    with pytest.raises(ValueError):
        TrayRuleSet.model_validate({"power_trays": [{"rack": "PR-1", "trays": 0}]})
    with pytest.raises(ValueError):
        TrayRuleSet.model_validate({"power_trays": [{"rack": "PR-1", "trays": ["mv"]}]})
