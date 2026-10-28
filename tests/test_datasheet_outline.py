"""Datasheet main dimensions, weights, nozzle schedule and the generated outline drawing
(pre-release issue 62): the schema stays compatible with existing datasheets, the drawing is
deterministic and drift-checked, the checks against the equipment list, the layout model, the
P&IDs and the line list, the ``kind: datasheets`` gate options, ``draft``/``fill`` and the
``cheme datasheets drawing`` command."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from chemeascode.domains.equipment.datasheets import (
    datasheet_gate,
    dimension_findings,
    draft_datasheet,
    drawing_states,
    field_counts,
    main_dimensions_missing,
    nozzle_findings,
    weights_missing,
)
from chemeascode.domains.equipment.drawing import render_outline
from chemeascode.domains.equipment.outline import derived_dimensions, outline
from chemeascode.domains.equipment.schemas.datasheet import Datasheet, Material, Quantity
from chemeascode.domains.equipment.schemas.equipment import EquipmentItem, EquipmentList
from chemeascode.foundation.schemas.checks import Check
from chemeascode.foundation.workspace import Workspace
from chemeascode.interfaces.cli import app
from chemeascode.project.checks import run_checks
from chemeascode.project.datasheets import datasheet_report, drawings, pid_nozzles, title_meta
from chemeascode.project.validate import validate_workspace

runner = CliRunner()
DATA = Path(__file__).parent / "data"
ASU_FIXTURES = DATA / "datasheets-asu"
LIBRARY = Path(os.environ.get("CHEME_PROCESS_LIBRARY", "~/Developer/repos/plantcode-asu"))

COLUMN = {
    "tag": "C-1",
    "type": "ProcessColumn",
    "service": "Stripper",
    "design_pressure_barg": 5,
    "dimensions": {"diameter": 2.0, "height": 20.0, "head": "ellipsoidal_2_1", "support": "skirt"},
}
VESSEL = {
    "tag": "V-1",
    "type": "PressureVessel",
    "dimensions": {
        "diameter": 2.0,
        "length": 8.0,
        "height": 3.0,
        "head": "ellipsoidal_2_1",
        "support": "saddles",
        "weight": 6.0,
    },
}
SHEET = {
    "tag": "C-1",
    "type": "ProcessColumn",
    "service": "Stripper",
    "dimensions": {
        "orientation": "vertical",
        "outside_diameter": {"value": 2.0, "unit": "m", "source": "DESIGN.md D-1"},
        "inside_diameter": {"value": 1960, "unit": "mm", "source": "D-1", "assumed": True},
        "tangent_length": {"value": 16.5, "unit": "m", "source": "D-1"},
        "head": {"value": "ellipsoidal_2_1", "source": "D-1"},
        "support": {"type": "skirt", "height": {"value": 3.0, "unit": "m", "source": "D-1"}},
        "overall_height": {"value": 20.0, "unit": "m", "source": "list"},
        "sections": [
            {
                "id": "stripping",
                "internals": "valve trays",
                "bottom": 1.5,
                "height": 6.0,
                "count": 12,
                "spacing": 0.5,
            }
        ],
    },
    "weights": {
        "empty": {"value": 18.0, "unit": "t", "source": "vendor"},
        "operating": {"value": "supplier", "unit": "t", "source": "enquiry E-12"},
        "test": {"value": "TBD", "unit": "t", "source": "TBD: vessel design"},
    },
    "materials": {
        "shell": {"value": "SA-516-70", "material_class": "carbon_steel", "standard": "ASME II A"},
        "trays": "SS 304",
    },
    "nozzles": [
        {
            "name": "N1",
            "dn": 200,
            "rating": "PN25",
            "facing": "RF",
            "service": "Feed",
            "face": "side",
            "orientation_deg": 90,
            "elevation_m": 12.0,
            "projection_m": 1.4,
            "lines": ["L-1"],
        },
        {"name": "N2", "dn": 150, "face": "top", "lines": ["L-2"]},
        {"name": "N3", "dn": 100, "face": "bottom", "elevation_m": 2.5},
        {"name": "N4", "dn": 50},
    ],
}


def write(root: Path, rel: str, data: object) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


# -- schema compatibility -------------------------------------------------------------------------


def _asu_sheets() -> list[Path]:
    folder = LIBRARY.expanduser() / "processes" / "asu-1" / "equipment" / "datasheets"
    return sorted(folder.glob("*.yaml")) if folder.is_dir() else []


@pytest.mark.parametrize("path", sorted(ASU_FIXTURES.glob("*.yaml")), ids=lambda p: p.stem)
def test_existing_datasheets_validate_unchanged(path: Path):
    """Datasheets written before the typed dimensions validate as they are, and draw."""
    sheet = Datasheet.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    assert sheet.dimensions is None and sheet.weights is None
    svg = render_outline(sheet, {"plant": "ASU"}, "sha256:0")
    assert svg == render_outline(sheet, {"plant": "ASU"}, "sha256:0")
    assert svg.startswith("<?xml") and sheet.tag in svg


@pytest.mark.skipif(not _asu_sheets(), reason="no local process-library checkout")
def test_every_datasheet_of_the_library_checkout_validates():
    paths = _asu_sheets()
    assert len(paths) >= 39
    for path in paths:
        sheet = Datasheet.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        render_outline(sheet)


def test_the_new_sections_parse_and_a_plain_material_still_does():
    sheet = Datasheet.model_validate(SHEET)
    assert isinstance(sheet.materials["shell"], Material)
    assert sheet.materials["shell"].material_class == "carbon_steel"
    assert sheet.materials["trays"] == "SS 304"
    plain = Datasheet.model_validate({"tag": "X", "materials": {"a": {"value": "CS"}}})
    assert isinstance(plain.materials["a"], Quantity)  # as before: a value, not a Material
    with pytest.raises(ValueError):
        Datasheet.model_validate(
            {"tag": "X", "materials": {"a": {"value": "CS", "material_class": "unobtainium"}}}
        )
    shape = outline(sheet)
    assert shape.family == "vertical" and shape.kind == "column"
    assert shape.id is not None and shape.id.value == pytest.approx(1.96) and shape.id.assumed
    assert shape.sections[0][0] == "stripping"
    counts = field_counts(yaml.safe_load(yaml.safe_dump(SHEET)))
    assert counts == {"assumed": 1, "tbd": 1, "supplier": 1, "not_applicable": 0}


# -- the drawing ----------------------------------------------------------------------------------


def test_the_drawing_is_deterministic_and_shows_what_is_stated():
    sheet = Datasheet.model_validate(SHEET)
    svg = render_outline(sheet, {"plant": "P", "revision": "B"}, "sha256:abc")
    assert svg == render_outline(
        Datasheet.model_validate(SHEET), {"plant": "P", "revision": "B"}, "sha256:abc"
    )
    for text in ("C-1", "Stripper", "16.5 T-T", "20 overall", "3 skirt", "OD 2", "NOZZLE"):
        assert text in svg, text
    assert "sha256:abc" in svg and ">B<" in svg
    assert "N4 †" in svg  # in the schedule, not placed: no location
    assert "stripping" in svg and "valve trays" in svg
    assert "SA-516-70 (carbon_steel)" in svg
    assert ">DRAFT<" not in svg
    draft = Datasheet.model_validate({**SHEET, "draft": True})
    assert ">DRAFT<" in render_outline(draft)
    # a horizontal vessel and a machine draw too; with nothing to draw, a note says so
    vessel = Datasheet.model_validate(
        {
            "tag": "V-1",
            "type": "PressureVessel",
            "dimensions": {
                "outside_diameter": 2.0,
                "overall_length": 8.0,
                "head": "hemispherical",
                "axis_deg": 90,
            },
            "nozzles": [{"name": "N1", "dn": 100, "face": "top", "axial_m": 2.0}],
        }
    )
    assert outline(vessel).family == "horizontal"
    assert "8 overall" in render_outline(vessel) and "N1 †" not in render_outline(vessel)
    pump = Datasheet.model_validate(
        {
            "tag": "P-1",
            "type": "CentrifugalPump",
            "dimensions": {
                "overall_length": 1.2,
                "overall_width": 0.5,
                "overall_height": 0.8,
                "baseplate": {"length": 1.1, "width": 0.45},
                "shaft_height": 0.4,
            },
        }
    )
    assert "0.4 shaft" in render_outline(pump) and "1.1 baseplate" in render_outline(pump)
    # nozzles at one angle, or at one place on the roof, share a label
    stacked = Datasheet.model_validate(
        {
            **SHEET,
            "nozzles": [
                {"name": "N1", "dn": 100, "face": "side", "orientation_deg": 270, "elevation_m": 4},
                {"name": "N2", "dn": 100, "face": "side", "orientation_deg": 270, "elevation_m": 9},
                {"name": "N3", "dn": 80, "face": "top"},
                {"name": "N4", "dn": 80, "face": "bottom"},
            ],
        }
    )
    svg = render_outline(stacked)
    assert ">N1, N2 270°<" in svg and ">N3, N4<" in svg
    assert ">N1 270°<" not in svg
    empty = render_outline(Datasheet.model_validate({"tag": "X-1", "type": "Tank"}))
    assert "no main dimensions given" in empty


def test_drawing_command_writes_and_checks(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    write(plant, "equipment/datasheets/C-1.yaml", SHEET)
    result = runner.invoke(app, ["datasheets", "drawing", "--check"])
    assert result.exit_code == 1 and "C-1.svg: missing" in result.output
    result = runner.invoke(app, ["datasheets", "drawing", "--write"])
    assert result.exit_code == 0 and "wrote equipment/datasheets/C-1.svg" in result.output
    svg = (plant / "equipment/datasheets/C-1.svg").read_text(encoding="utf-8")
    assert runner.invoke(app, ["datasheets", "drawing", "--check"]).exit_code == 0
    printed = runner.invoke(app, ["datasheets", "drawing", "--tag", "C-1", "--print"])
    assert printed.output == svg
    # validate reports a drawing that no longer follows its datasheet
    assert not [f for f in validate_workspace(Workspace(plant)).findings if "drawing" in f.rule]
    write(plant, "equipment/datasheets/C-1.yaml", {**SHEET, "service": "Stripper (rev)"})
    (stale,) = [
        f
        for f in validate_workspace(Workspace(plant)).findings
        if f.rule == "cheme.datasheet-drawing-stale"
    ]
    assert stale.file == "equipment/datasheets/C-1.svg" and "--write" in stale.hint
    result = runner.invoke(app, ["datasheets", "drawing", "--check"])
    assert result.exit_code == 1 and "C-1.svg: stale" in result.output
    assert drawings(plant, write=True).written == ["equipment/datasheets/C-1.svg"]
    assert runner.invoke(app, ["datasheets", "drawing", "--tag", "NOPE"]).exit_code == 1


# -- checks ---------------------------------------------------------------------------------------


def test_dimensions_are_checked_against_the_equipment_list_and_the_layout_model(plant: Path):
    workspace = Workspace(plant)
    write(plant, "equipment/datasheets/C-1.yaml", SHEET)
    equipment = EquipmentList.model_validate({"equipment": [COLUMN]})
    assert dimension_findings(workspace, equipment, None) == []
    wrong = {
        **COLUMN,
        "dimensions": {**COLUMN["dimensions"], "diameter": 2.6, "head": "hemispherical"},
    }
    found = dimension_findings(
        workspace, EquipmentList.model_validate({"equipment": [wrong]}), None
    )
    messages = " | ".join(f.message for f in found)
    assert {f.rule for f in found} == {"cheme.datasheet-dimension-mismatch"}
    assert "outside_diameter 2 m here, diameter 2.6 m in the equipment list" in messages
    assert "head ellipsoidal_2_1 here, hemispherical in the equipment list" in messages
    # a tangent length longer than the overall height
    longer = {**SHEET["dimensions"], "tangent_length": {"value": 22.0, "unit": "m"}}
    write(plant, "equipment/datasheets/C-1.yaml", {**SHEET, "dimensions": longer})
    (f,) = dimension_findings(workspace, equipment, None)
    assert "tangent_length 22 m is longer than the overall 20 m" in f.message
    write(plant, "equipment/datasheets/C-1.yaml", SHEET)
    # the layout model: the shell's diameter and the overall height of its box
    item = {
        "tag": "C-1",
        "shape": "vertical_cylinder",
        "bbox": [0, 0, 0, 2.0, 2.0, 24.0],
        "parts": [{"id": "C-1/shell", "kind": "cylinder", "radius": 1.0}],
    }
    found = dimension_findings(workspace, None, {"equipment": [item]})
    assert [f.rule for f in found] == ["cheme.datasheet-dimension-layout"]
    assert "overall_height 20 m, the model's 24 m" in found[0].message
    # a horizontal item's tangent length is compared with its length, not its height
    horizontal = {
        "tag": "V-1",
        "type": "PressureVessel",
        "dimensions": {"outside_diameter": 2.0, "tangent_length": 7.0, "overall_length": 8.0},
    }
    write(plant, "equipment/datasheets/V-1.yaml", horizontal)
    vessels = EquipmentList.model_validate({"equipment": [VESSEL]})
    assert dimension_findings(workspace, vessels, None) == []
    # weights against the list's empty weight
    write(plant, "equipment/datasheets/V-1.yaml", {"tag": "V-1", "weights": {"empty": 9.0}})
    found = dimension_findings(
        workspace, EquipmentList.model_validate({"equipment": [VESSEL]}), None
    )
    assert any("empty weight 9 t here, 6 t" in f.message for f in found)


def test_nozzles_are_checked_against_the_pid_and_the_line_list(plant: Path):
    workspace = Workspace(plant)
    nozzles, _ = pid_nozzles(workspace)  # the reference P&ID: P4711 N1 and N2, DN80
    sheet = {
        "tag": "P4711",
        "nozzles": [
            {"name": "N1", "dn": 80, "lines": ["47121"]},
            {"name": "N2", "dn": 100, "lines": ["47199"]},
            {"name": "N9", "dn": 25},
        ],
    }
    write(plant, "equipment/datasheets/P4711.yaml", sheet)
    found = nozzle_findings(workspace, nozzles, None)
    messages = {f.key: f.message for f in found}
    assert set(messages) == {"P4711/N2/dn", "P4711/N2/lines", "P4711/N9/missing-on-pid"}
    assert "DN 100 here, DN 80 on pid/P-01.xml" in messages["P4711/N2/dn"]
    sheet["nozzles"] = sheet["nozzles"][:1]
    write(plant, "equipment/datasheets/P4711.yaml", sheet)
    (f,) = nozzle_findings(workspace, nozzles, None)
    assert f.key == "P4711/missing" and "1 of the 2 nozzles" in f.message
    # the line list: a line it does not have, unless the P&ID draws it there
    from chemeascode.schemas import LineList

    lines = LineList.model_validate({"lines": [{"number": "47122", "from": "P4711", "to": "X"}]})
    sheet["nozzles"] = [{"name": "N1", "dn": 80, "lines": ["47121", "99999"]}]
    write(plant, "equipment/datasheets/P4711.yaml", sheet)
    found = nozzle_findings(workspace, None, lines)
    assert sorted(f.key for f in found) == ["P4711/N1/47121", "P4711/N1/99999"]
    found = [f for f in nozzle_findings(workspace, nozzles, lines) if "line" in f.rule]
    assert [f.key for f in found] == ["P4711/N1/99999"]
    # validate runs it with the loaded sheets
    report = validate_workspace(workspace)
    assert any(f.rule == "cheme.datasheet-nozzle-pid" for f in report.findings)


def test_duplicate_nozzles_and_unknown_units_are_reported(plant: Path):
    data = {
        "tag": "C-1",
        "nozzles": [{"name": "N1"}, {"name": "N1"}],
        "dimensions": {"outside_diameter": {"value": 2, "unit": "ft"}},
        "weights": {"empty": {"value": 3, "unit": "lb"}},
    }
    write(plant, "equipment/datasheets/C-1.yaml", data)
    rules = sorted(
        f.rule
        for f in validate_workspace(Workspace(plant)).findings
        if "datasheet" in f.rule and f.rule != "cheme.datasheet-not-listed"
    )
    assert rules == [
        "cheme.datasheet-nozzle-duplicate",
        "cheme.datasheet-unit",
        "cheme.datasheet-unit",
    ]


def test_the_gate_can_require_dimensions_weights_schedule_and_drawing(plant: Path):
    workspace = Workspace(plant)
    write(plant, "equipment/datasheets/C-1.yaml", SHEET)
    sheet = Datasheet.model_validate(SHEET)
    assert main_dimensions_missing(sheet) == []
    assert weights_missing(sheet) == ["test"]  # TBD; supplier counts as given
    every = ["dimensions", "weights", "nozzle-schedule", "drawing-current"]
    problems = datasheet_gate(workspace, every, {})
    text = "; ".join(problems)
    assert "weights missing: C-1 (test)" in text
    assert "nozzles without DN or location: C-1 (N4)" in text
    assert "outline drawings not current: C-1 (missing)" in text
    assert "main dimensions missing" not in text
    pump = Datasheet.model_validate({"tag": "P-1", "type": "CentrifugalPump"})
    assert main_dimensions_missing(pump) == ["dimensions"]
    pump = Datasheet.model_validate(
        {"tag": "P-1", "type": "CentrifugalPump", "dimensions": {"shaft_height": 0.4}}
    )
    assert main_dimensions_missing(pump) == ["baseplate.length", "baseplate.width"]
    # the schema keeps the requirements to their kind
    Check.model_validate(
        {"id": "d", "title": "t", "stage": "basic", "kind": "datasheets", "require": every}
    )
    with pytest.raises(ValueError, match="belong to a kind: datasheets"):
        Check.model_validate(
            {"id": "m", "title": "t", "stage": "b", "kind": "layout-model", "require": ["weights"]}
        )
    with pytest.raises(ValueError, match="a datasheets check requires only"):
        Check.model_validate(
            {"id": "d", "title": "t", "stage": "b", "kind": "datasheets", "require": ["rates"]}
        )
    # in checks.yaml: the gate fails with the reason, and passes once the sheet meets it
    write(plant, "equipment/equipment-list.yaml", {"equipment": [COLUMN]})
    checks = yaml.safe_load((plant / "checks/checks.yaml").read_text(encoding="utf-8"))
    for check in checks["checks"]:
        if check["kind"] == "datasheets":
            check["require"] = ["weights", "drawing-current"]
    write(plant, "checks/checks.yaml", checks)
    gate = {c.id: c for c in run_checks(workspace)}["datasheets"]
    assert gate.status == "fail" and "weights missing: C-1 (test)" in gate.detail
    weights = {**SHEET["weights"], "test": {"value": 48.0, "unit": "t", "source": "D-1"}}
    write(plant, "equipment/datasheets/C-1.yaml", {**SHEET, "weights": weights})
    drawings(plant, write=True)
    gate = {c.id: c for c in run_checks(workspace)}["datasheets"]
    assert gate.status == "pass", gate.detail


# -- draft and fill -------------------------------------------------------------------------------


def test_derived_dimensions_come_from_the_list_and_the_model_only():
    item = EquipmentItem.model_validate(COLUMN)
    dims, weights = derived_dimensions(item, None)
    assert dims["outside_diameter"]["value"] == 2.0 and "assumed" not in dims["outside_diameter"]
    assert dims["support"] == {
        "type": {"value": "skirt", "source": dims["support"]["type"]["source"]}
    }
    assert "tangent_length" not in dims and weights == {}  # nothing invented
    model = {
        "equipment": [
            {
                "tag": "C-1",
                "shape": "vertical_cylinder",
                "position": [0, 0, 0],
                "parts": [
                    {"id": "C-1/skirt", "start": [0, 0, 0], "end": [0, 0, 2.4]},
                    {"id": "C-1/shell", "start": [0, 0, 2.9], "end": [0, 0, 19.5], "radius": 1},
                ],
            }
        ]
    }
    dims, _ = derived_dimensions(item, model)
    assert dims["tangent_length"]["value"] == pytest.approx(16.6)
    assert dims["tangent_length"]["assumed"] is True
    assert dims["support"]["height"]["value"] == pytest.approx(2.9)  # to the bottom tangent
    vessel = EquipmentItem.model_validate(VESSEL)
    dims, weights = derived_dimensions(vessel, None)
    assert dims["orientation"] == "horizontal" and dims["overall_length"]["value"] == 8.0
    assert weights["empty"]["value"] == 6.0


def test_a_draft_carries_dimensions_and_the_listed_weight():
    item = EquipmentItem.model_validate(VESSEL)
    data = yaml.safe_load(draft_datasheet(item, [], []))
    Datasheet.model_validate(data)
    assert data["dimensions"]["outside_diameter"]["value"] == 2.0
    assert data["weights"]["empty"]["value"] == 6.0
    assert set(data["weights"]) == {"empty"}  # nothing invented, no TBD added
    assert "weights" not in yaml.safe_load(
        draft_datasheet(EquipmentItem.model_validate(COLUMN), [], [])
    )
    keys = list(data)
    assert keys.index("dimensions") == keys.index("materials") + 1


def test_fill_adds_dimensions_and_never_overwrites_a_hand_value(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    write(plant, "equipment/equipment-list.yaml", {"equipment": [COLUMN, VESSEL]})
    final = {
        "tag": "C-1",
        "type": "ProcessColumn",
        "materials": {"main": "CS"},
        "dimensions": {"outside_diameter": {"value": 2.0, "unit": "m", "source": "vendor"}},
        "notes": "",
    }
    write(plant, "equipment/datasheets/C-1.yaml", final)
    # a plain fill keeps final sheets as they are
    result = runner.invoke(app, ["datasheets", "fill"])
    assert "kept equipment/datasheets/C-1.yaml (not a draft)" in result.output
    result = runner.invoke(app, ["datasheets", "fill", "--dimensions"])
    assert result.exit_code == 0, result.output
    data = yaml.safe_load((plant / "equipment/datasheets/C-1.yaml").read_text(encoding="utf-8"))
    assert data["dimensions"]["outside_diameter"]["source"] == "vendor"  # kept
    assert data["dimensions"]["overall_height"]["source"].startswith("cheme datasheets fill")
    assert "weights" not in data  # the list gives no weight: no TBD in a final sheet
    Datasheet.model_validate(data)
    again = runner.invoke(app, ["datasheets", "fill", "--dimensions"])
    assert "unchanged equipment/datasheets/C-1.yaml" in again.output
    # validate has nothing to say about it
    report = validate_workspace(Workspace(plant))
    assert not [f for f in report.findings if f.file.startswith("equipment/datasheets/C-1")]


# -- the viewer API ------------------------------------------------------------------------------


def test_datasheet_report_index_and_entry(plant: Path):
    write(plant, "equipment/equipment-list.yaml", {"equipment": [COLUMN, VESSEL]})
    write(plant, "equipment/datasheets/C-1.yaml", SHEET)
    report = datasheet_report(plant)
    index = report.index()
    assert index["missing"] == ["V-1"]
    (entry,) = index["datasheets"]
    assert entry["tag"] == "C-1" and entry["has_dimensions"] and entry["has_weights"]
    assert entry["has_drawing"] is False and entry["drawing_current"] is False
    assert entry["counts"]["tbd"] == 1
    states = drawing_states(Workspace(plant), title_meta(Workspace(plant)))
    assert report.entry("C-1").drawing_text == states[0].text


def test_drawing_of_a_copied_plant_matches(plant: Path, tmp_path: Path):
    """The drawing depends on the datasheet (and plant.yaml) only, not on where it is."""
    write(plant, "equipment/datasheets/C-1.yaml", SHEET)
    drawings(plant, write=True)
    copy = tmp_path / "copy"
    shutil.copytree(plant, copy)
    assert [s.state for s in drawings(copy).states] == ["current"]


# -- pre-release issue 96: stacked and housed items, schedule service, saddles clear of bottom
#    nozzles ---------------------------------------------------------------------------------------


def test_a_stacked_item_gets_its_base_elevation_and_what_it_stands_on():
    upper = EquipmentItem.model_validate(
        {**COLUMN, "tag": "C-2", "dimensions": {**COLUMN["dimensions"], "support": "none"}}
    )
    model = {
        "equipment": [
            {"tag": "C-1", "position": [5, 5, 0], "bbox": [4, 4, 0, 6, 6, 20.0]},
            {"tag": "C-2", "position": [5, 5, 20.0], "bbox": [4, 4, 20, 6, 6, 40.0]},
        ]
    }
    dims, _ = derived_dimensions(upper, model)
    assert dims["support"]["elevation"]["value"] == 20.0
    assert dims["support"]["stands_on"]["value"] == "C-1"
    lower, _ = derived_dimensions(EquipmentItem.model_validate(COLUMN), model)
    assert "elevation" not in lower["support"] and "stands_on" not in lower["support"]
    # the key is not YAML 1.1's boolean `on`: written and read back as itself
    sheet = Datasheet.model_validate(
        yaml.safe_load(yaml.safe_dump({"tag": "C-2", "type": "ProcessColumn", "dimensions": dims}))
    )
    assert sheet.dimensions is not None and sheet.dimensions.support is not None
    svg = render_outline(sheet)
    assert ">base on C-1 (+20 m)<" in svg and "base / grade" not in svg
    assert ">base / grade<" in render_outline(Datasheet.model_validate(SHEET))
    alone = {**dims, "support": {"elevation": 7.5}}
    assert ">base +7.5 m<" in render_outline(
        Datasheet.model_validate({"tag": "C-2", "type": "ProcessColumn", "dimensions": alone})
    )


def test_an_item_without_dimensions_says_what_is_missing_or_what_houses_it():
    bare = {"tag": "E-3", "type": "PlateHeatExchanger", "nozzles": [{"name": "N1", "dn": 300}]}
    svg = render_outline(Datasheet.model_validate(bare))
    assert "give dimensions:" not in svg and "type_specific" not in svg
    assert "no dimensions.overall_length or overall_height: no elevation drawn" in svg
    housed = render_outline(Datasheet.model_validate({**bare, "dimensions": {"housed_in": "C-2"}}))
    assert "housed in C-2: no main dimensions of its own, not drawn" in housed
    assert "no elevation drawn" not in housed and ">C-2<" in housed  # the table row
    # an older draft's type_specific sizes still say where to move them
    older = render_outline(
        Datasheet.model_validate({**bare, "type_specific": {"length_m": 3.0, "height_m": 4.5}})
    )
    assert "move them into dimensions: (cheme datasheets fill --dimensions)" in older


def test_the_schedule_shows_the_lines_as_service_when_none_is_given():
    sheet = Datasheet.model_validate(
        {
            "tag": "V-9",
            "nozzles": [
                {"name": "N1", "dn": 100, "lines": ["AIR-1004"]},
                {"name": "N2", "dn": 100, "service": "Drain", "lines": ["DR-1"]},
            ],
        }
    )
    svg = render_outline(sheet)
    assert svg.count(">AIR-1004<") == 2 and ">Drain<" in svg and svg.count(">DR-1<") == 1


def _saddles(svg: str) -> list[tuple[float, float]]:
    """The x extents of the outline rectangles below the shell (the saddles), sheet mm."""
    import re

    found = []
    for x, w, _h in re.findall(
        r'<rect x="([\d.]+)" y="[\d.]+" width="([\d.]+)" height="([\d.]+)" class="outline"/>', svg
    ):
        if float(w) < 20:  # not the shell
            found.append((float(x), float(x) + float(w)))
    return found


def _bottom_stubs(svg: str) -> list[tuple[float, float]]:
    import re

    return [
        (float(x), float(x) + float(w))
        for x, w in re.findall(
            r'<rect x="([\d.]+)" y="[\d.]+" width="([\d.]+)" height="[\d.]+" class="nozzle"/>',
            svg,
        )
    ]


def test_saddles_are_drawn_clear_of_the_bottom_nozzles():
    vessel = {
        "tag": "V-2",
        "type": "PressureVessel",
        "dimensions": {
            "orientation": "horizontal",
            "outside_diameter": 4.5,
            "overall_length": 18.0,
            "tangent_length": 15.75,
            "head": "ellipsoidal_2_1",
            "support": {"type": "saddles", "height": 2.0},
            "axis_deg": 0,
        },
        "nozzles": [
            {"name": "N1", "dn": 600, "face": "bottom", "orientation_deg": 180, "offset_m": 6.0},
            {"name": "N4", "dn": 600, "face": "bottom", "orientation_deg": 0, "offset_m": 6.0},
        ],
    }
    svg = render_outline(Datasheet.model_validate(vessel))
    elevation = svg.split("NOZZLE ORIENTATION")[0] if "NOZZLE ORIENTATION" in svg else svg
    saddles = [s for s in _saddles(elevation) if s[1] < 215]
    stubs = [s for s in _bottom_stubs(elevation) if s[1] < 215]
    assert len(saddles) == 2 and len(stubs) >= 2
    for a0, a1 in saddles:
        for b0, b1 in stubs:
            # clear of the stub and its flange (0.8 DN each side), not just touching
            assert a1 + 2.0 <= b0 or b1 + 2.0 <= a0, (saddles, stubs)
    assert svg == render_outline(Datasheet.model_validate(vessel))  # deterministic
    # with no bottom nozzle in the way the saddles stay at 0.3 L each side
    plain = render_outline(Datasheet.model_validate({**vessel, "nozzles": []}))
    (left, right) = sorted(s for s in _saddles(plain) if s[1] < 215)
    assert (left[0] + left[1]) / 2 + (right[0] + right[1]) / 2 == pytest.approx(230.0, abs=0.5)


def test_an_unknown_field_hints_at_a_newer_release(plant: Path):
    from chemeascode.domains.equipment.datasheets import load

    path = write(plant, "equipment/datasheets/C-1.yaml", {**SHEET, "future_field": 1})
    (finding,) = load(Workspace(plant), path).findings
    assert finding.rule == "yaml.schema" and "future_field" in finding.message
    assert "newer cheme-as-code" in finding.hint and "cheme schema datasheet" in finding.hint
    path = write(plant, "equipment/datasheets/C-1.yaml", {**SHEET, "service": ["not", "text"]})
    assert all("newer" not in f.hint for f in load(Workspace(plant), path).findings)
