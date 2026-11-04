"""Electrolyser stacks and skid equipment inputs (domains/equipment/electrolyser_stack.py, the
``stacks:`` section of ``process/cells.yaml``, ``cheme process stack``): a hand-checked sizing,
the propagation of a changed duty into the equipment list, the datasheets and the generated
layout model, the invariance of the stack under a duty change, the measured range, the
refusals, the text editing of the equipment list, the command and the import boundary.

Fixture: tests/data/electrochemical/co2-skid, a 100 cm2 plant cell at 150 mA/cm2 with the
synthetic measured series of co2-bpm (50-200 mA/cm2), two stacks on a 48 V bus, a 20 L
reservoir dosed with 1 M KOH over a 100 h duty, and the skid's equipment list, pump datasheets
and layout files.
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from chemeascode.domains.equipment.electrolyser_stack import (
    MODEL,
    STACK_MARK,
    CellPoint,
    set_dimensions,
    size_stack,
    stack_findings,
    stack_report,
    write_stack_inputs,
)
from chemeascode.domains.process.electrochemical_cell import FARADAY, Stack
from chemeascode.domains.process.electrolysis_duty import run_duty
from chemeascode.interfaces.cli import app

DATA = Path(__file__).resolve().parent / "data" / "electrochemical"
runner = CliRunner()
#: g/mol, from the formula with the standard atomic weights of domains/chemistry/formulas.py
M_CO = 12.011 + 15.999


def _plant(tmp_path: Path) -> Path:
    root = tmp_path / "co2-skid"
    shutil.copytree(DATA / "co2-skid", root)
    return root


def _edit(root: Path, name: str, edit) -> None:
    path = root / name
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    edit(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _stack(report, sid="STK-1"):
    return next(s for s in report.stacks if s.id == sid)


def _entry(stack, tag):
    return next(e for e in stack.equipment if e.tag == tag)


def _rules(findings, level=None):
    return {f.rule for f in findings if level is None or f.level == level}


def _cylinder(volume_l: float, aspect: float) -> tuple[float, float]:
    """D and H (m, rounded up to the mm) of a vertical cylinder of *volume_l* at H/D *aspect*."""
    d = (4 * volume_l / 1000 / (math.pi * aspect)) ** (1 / 3)
    return math.ceil(d * 1000 - 1e-6) / 1000, math.ceil(aspect * d * 1000 - 1e-6) / 1000


# -- a hand-checked sizing ----------------------------------------------------------------------

HAND = {
    "id": "HAND",
    "cell": "C-100",
    "product": {"component": "CO", "rate": {"value": 1, "unit": "kg/h", "provenance": "given"}},
    "electrical": {"max_stack_voltage": {"value": 48, "unit": "V", "provenance": "given"}},
}


def test_hand_checked_sizing():
    """1 kg/h CO at FE 0.9, 200 mA/cm2 on 100 cm2 cells (20 A), U 3.5 V, a 48 V bus, by hand:
    Ndot = 1000 / 28.010 / 3600 = 9.91709e-3 mol/s; I = 2 F Ndot / 0.9 = 2126.33 A;
    A = I / 2000 A/m2 = 1.06317 m2, 106.3 cells -> 107; floor(48 / 3.5) = 13 per stack ->
    ceil(107 / 13) = 9 stacks of ceil(107 / 9) = 12 cells (108 cells, 42 V, 20 A, bus 180 A);
    P = 108 x 3.5 x 20 = 7.56 kW; output 108 x 0.9 x 20 / (2 F) x 28.010 x 3.6 = 1.01582 kg/h
    (margin 1.58 %), 7.4423 kWh/kg."""
    point = CellPoint("C-100", "specified", 20.0, 2000.0, 0.01, 3.5, 0.9, 2, 1, M_CO)
    result = size_stack(Stack.model_validate(HAND), point)
    assert not result.refused
    n = result.number
    assert n("product_duty_mol_s") == pytest.approx(9.91709e-3, rel=1e-5)
    assert n("total_current_a") == pytest.approx(2126.33, rel=1e-5)
    assert n("total_active_area_m2") == pytest.approx(1.063166, rel=1e-5)
    assert (n("cells_required"), n("max_cells_per_stack")) == (107, 13)
    assert (n("stacks"), n("cells_per_stack"), n("cells_total")) == (9, 12, 108)
    assert n("stack_voltage_v") == pytest.approx(42.0)
    assert (n("stack_current_a"), n("bus_current_a")) == (pytest.approx(20), pytest.approx(180))
    assert n("dc_power_kw") == pytest.approx(7.56)
    assert n("product_output_kg_h") == pytest.approx(1.01582, rel=1e-5)
    assert n("output_margin") == pytest.approx(0.01582, rel=1e-3)
    assert n("electricity_kwh_per_kg") == pytest.approx(7.4423, rel=1e-4)
    assert (
        "9 stack(s) in parallel" in result.arrangement
        and "12 cells in series" in result.arrangement
    )
    # the formula of the spec, A = n F Ndot / (FE j), with the numbers as they are
    assert n("total_active_area_m2") == pytest.approx(
        2 * FARADAY * n("product_duty_mol_s") / (0.9 * 2000)
    )
    # every value says where it comes from
    values = result.values
    assert values["dc_power_kw"].provenance == "calculated"
    assert values["product_duty_kg_h"].provenance == "given"
    assert "floor(U_max / U)" in values["max_cells_per_stack"].source
    # no envelope: its dimensions are TBD with the reason, never invented
    assert (
        values["stack_length_m"].provenance == "tbd"
        and "envelope" in values["stack_length_m"].source
    )


def test_hand_checked_case_through_the_plant(tmp_path):
    """The same case as a specified cell of process/cells.yaml gives the same numbers."""
    root = tmp_path / "hand"
    shutil.copytree(DATA / "co2-duty", root)
    (root / "process" / "duties.yaml").unlink()
    cell = {
        "id": "C-100",
        "reaction": "CO2R",
        "electrons": 2,
        "current": {"value": 20, "unit": "A", "provenance": "given", "source": "hand case"},
        "active_area": {"value": 100, "unit": "cm2", "provenance": "given", "source": "hand"},
        "faradaic_efficiency": {"value": 0.9, "provenance": "given", "source": "hand case"},
        "voltage": {"value": 3.5, "unit": "V", "provenance": "given", "source": "hand case"},
        "thermal": {
            "kind": "isothermal",
            "temperature": {"value": 25, "unit": "°C", "provenance": "given"},
        },
        "operating_range": {"current_density": [1000, 3000], "temperature": [290, 310]},
    }
    _edit(root, "process/cells.yaml", lambda d: d.update(cells=[cell], stacks=[HAND]))
    report = stack_report(root)
    s = _stack(report, "HAND")
    assert not s.refused, report.findings
    assert (s.number("stacks"), s.number("cells_per_stack")) == (9, 12)
    assert s.number("dc_power_kw") == pytest.approx(7.56)
    assert s.number("electricity_kwh_per_kg") == pytest.approx(7.4423, rel=1e-4)
    assert s.point.measurement["current_density_range_a_m2"] == [1000, 3000]
    # outside its declared range a specified cell is not sized on (cell-operating-range)
    _edit(root, "process/cells.yaml", lambda d: d["cells"][0]["current"].update(value=35))
    s = _stack(stack_report(root), "HAND")
    assert s.refused and "outside the declared range" in s.reasons[0]


def test_electrical_limits_refuse(tmp_path):
    point = CellPoint("C", "specified", 20.0, 2000.0, 0.01, 3.5, 0.9, 2, 1, M_CO)
    low = {
        **HAND,
        "electrical": {"max_stack_voltage": {"value": 3, "unit": "V", "provenance": "given"}},
    }
    result = size_stack(Stack.model_validate(low), point)
    assert result.refused and "above the stack voltage limit" in result.reasons[0]
    small = {
        **HAND,
        "electrical": {
            "max_stack_voltage": {"value": 48, "unit": "V", "provenance": "given"},
            "max_stack_current": {"value": 10, "unit": "A", "provenance": "given"},
        },
    }
    result = size_stack(Stack.model_validate(small), point)
    assert result.refused and "above the stack current limit" in result.reasons[0]
    bad = {
        **HAND,
        "product": {"component": "CO", "rate": {"value": 1, "unit": "lb/h", "provenance": "given"}},
    }
    result = size_stack(Stack.model_validate(bad), point)
    assert result.refused and "lb/h" in result.reasons[0]


# -- the fixture plant: sizing, the skid, and the files -----------------------------------------


def test_fixture_sizing_and_skid_inputs(tmp_path):
    root = _plant(tmp_path)
    report = stack_report(root)
    assert not report.errors, [f.format() for f in report.errors]
    s = _stack(report)
    p = s.point
    assert p.performance == "measured" and p.current_density_a_m2 == pytest.approx(1500)
    assert p.measurement["current_density_range_a_m2"] == [500.0, 2000.0]
    # FE(CO) at 1500 A/m2 from the measured series, 15 A per 100 cm2 cell, U 3.6 V
    cells = math.ceil(2 * FARADAY * (100 / M_CO / 3600) / (p.faradaic_efficiency * 1500) / 0.01)
    assert s.number("cells_required") == cells == 19
    assert (s.number("max_cells_per_stack"), s.number("stacks")) == (13, 2)
    assert (s.number("cells_per_stack"), s.number("cells_total")) == (10, 20)
    assert s.number("dc_power_kw") == pytest.approx(20 * 3.6 * 15 / 1000)
    assert s.number("output_margin") == pytest.approx(
        20 / (2 * FARADAY * (100 / M_CO / 3600) / (p.faradaic_efficiency * 15)) - 1
    )
    # the envelope: 10 cells x 8 mm + 120 mm; 100 mm + 2 x 40 mm
    assert (s.number("stack_length_m"), s.number("stack_width_m")) == (0.2, 0.18)
    assert s.values["stack_length_m"].assumed
    assert s.number("cells_replaced_per_year") == pytest.approx(20)
    # the duty run at the sized arrangement: 20 cells on the one reservoir, over 100 h
    assert s.duty["arrangement"] == "10 cells x 2 stacks" and s.duty["feasible"]
    assert s.duty["campaign_h"] == 100
    run = run_duty(root, "SKID-150", 10, 2).duties[0]
    assert run.cells_in_series == 10 and run.stacks == 2
    assert s.number("reservoir_working_volume_l") == pytest.approx(20 + (1.0 - 0.8) * 100)
    assert s.number("dosing_solution_l") == pytest.approx(100)
    tank = _entry(s, "T-101")
    assert (tank.values["diameter"].value, tank.values["height"].value) == _cylinder(40 * 1.25, 1.5)
    assert tank.source.startswith(f"{STACK_MARK}: stack STK-1, duty SKID-150")
    assert tank.fingerprint == s.duty["run_fingerprint"] and tank.assumed
    dosing = _entry(s, "T-102")
    assert (dosing.values["diameter"].value, dosing.values["height"].value) == _cylinder(
        100 * 1.2, 1.2
    )
    pump = _entry(s, "P-101")  # 0.5 mL/(min cm2) x 100 cm2 x 20 cells = 60 L/h
    assert pump.values["mass_flow_kg_h"].value == pytest.approx(60 * 1.05)
    assert pump.values["discharge_pressure_kpa"].value == pytest.approx(151.3)
    meter = _entry(s, "P-102")  # 1 L/h x 1.5 x 1.05 kg/L
    assert meter.values["mass_flow_kg_h"].value == pytest.approx(1.575)
    # nothing written yet: every target is outdated
    assert {e.status for e in s.equipment} == {"outdated"}
    assert _rules(report.findings, "warning") == {"cheme.stack-outdated"}


def test_propagation_into_the_list_datasheets_and_layout_model(tmp_path, monkeypatch):
    """A changed duty (its horizon, the campaign, and its reservoir) changes the reservoir and
    dosing tank as calculated, the equipment-list dimensions and the pump datasheet, and the
    generated layout model's geometry of those tags carries exactly those numbers; the stacks
    do not change."""
    from chemeascode.domains.spatial.model import build_model
    from chemeascode.foundation.workspace import Workspace

    root = _plant(tmp_path)

    def run():
        report = stack_report(root)
        write_stack_inputs(root, report)
        after = stack_report(root)
        assert {e.status for e in _stack(after).equipment} == {"current"}, after.findings
        listed = {
            i["tag"]: i.get("dimensions")
            for i in yaml.safe_load((root / "equipment/equipment-list.yaml").read_text())[
                "equipment"
            ]
        }
        model = build_model(Workspace(root)).document
        placed = {e["tag"]: e for e in model["equipment"]}
        return _stack(report), listed, placed

    first, listed, placed = run()
    from chemeascode.project.validate import validate_workspace

    checked = validate_workspace(Workspace(root))  # the written list and sheets are valid
    assert not [f.format() for f in checked.findings if f.level == "error"]
    assert "cheme.stack-outdated" not in {f.rule for f in checked.findings}
    d, h = _cylinder(40 * 1.25, 1.5)
    assert (listed["T-101"]["diameter"], listed["T-101"]["height"]) == (d, h)
    assert listed["T-101"]["head"] == "flat" and listed["T-101"]["assumed"] is True
    assert listed["T-101"]["source"].startswith(STACK_MARK)
    for tag in ("T-101", "T-102", "E-101A", "E-101B"):
        entry = _entry(first, tag)
        sizes = {k: v.value for k, v in entry.values.items()}
        assert {k: placed[tag]["dimensions"][k] for k in sizes} == sizes
        assert placed[tag]["size_from"] == "list"
    shell = next(p for p in placed["T-101"]["parts"] if p["id"] == "T-101/shell")
    assert shell["radius"] == pytest.approx(d / 2, abs=1e-3)
    assert shell["end"][2] - shell["start"][2] == pytest.approx(h, abs=1e-3)
    assert placed["E-101A"]["dimensions"] == {"length": 0.2, "width": 0.18, "height": 0.18}
    written = (root / "equipment/datasheets/P-101.yaml").read_text()
    assert written.startswith("# DRAFT datasheet")  # the header comment is kept
    sheet = yaml.safe_load(written)
    flow = sheet["type_specific"]["mass_flow_kg_h"]
    assert flow["value"] == pytest.approx(63) and flow["source"].startswith(STACK_MARK)
    # the datasheet draft takes the tank's sizes with their source and ASSUMED marking
    monkeypatch.chdir(root)
    assert runner.invoke(app, ["datasheets", "draft", "--tag", "T-101"]).exit_code == 0
    drafted = yaml.safe_load((root / "equipment/datasheets/T-101.yaml").read_text())
    diameter = drafted["dimensions"]["outside_diameter"]
    assert diameter["value"] == d and diameter["assumed"] is True
    assert "cheme process stack: stack STK-1, duty SKID-150" in diameter["source"]

    # a longer campaign: more dosed, the volume grows further; the stacks stay as they were
    def longer(data):
        data["duties"][0]["horizon"]["value"] = 200
        data["duties"][0]["reservoir"]["volume"]["value"] = 30

    _edit(root, "process/duties.yaml", longer)
    second, listed, placed = run()
    for key in ("stacks", "cells_per_stack", "electricity_kwh_per_kg", "dc_power_kw"):
        assert second.number(key) == first.number(key)
    assert second.number("reservoir_working_volume_l") == pytest.approx(30 + 0.2 * 200)
    assert second.number("dosing_solution_l") == pytest.approx(200)
    d2, h2 = _cylinder(70 * 1.25, 1.5)
    assert (listed["T-101"]["diameter"], listed["T-101"]["height"]) == (d2, h2) != (d, h)
    assert (placed["T-101"]["dimensions"]["diameter"], placed["T-101"]["dimensions"]["height"]) == (
        d2,
        h2,
    )
    dd, dh = _cylinder(200 * 1.2, 1.2)
    assert (placed["T-102"]["dimensions"]["diameter"], placed["T-102"]["dimensions"]["height"]) == (
        dd,
        dh,
    )
    assert placed["E-101A"]["dimensions"] == {"length": 0.2, "width": 0.18, "height": 0.18}
    # a changed anolyte flow reaches the pump datasheet; the stacks' list entries stay current
    _edit(
        root,
        "process/cells.yaml",
        lambda c: c["stacks"][0]["equipment"]["recirculation_pump"]["flow_per_area"].update(
            value=1
        ),
    )
    third, _, _ = run()
    sheet = yaml.safe_load((root / "equipment/datasheets/P-101.yaml").read_text())
    assert sheet["type_specific"]["mass_flow_kg_h"]["value"] == pytest.approx(126)
    assert sheet["type_specific"]["flow_m3_h"]["value"] == "TBD"  # the pump fill's, untouched


def test_duty_change_keeps_the_stack_and_a_range_exit_is_flagged(tmp_path):
    root = _plant(tmp_path)
    before = _stack(stack_report(root))
    _edit(
        root,
        "process/duties.yaml",
        lambda d: d["duties"][0]["reservoir"]["volume"].update(value=35),
    )
    after = _stack(stack_report(root))
    for key in ("cells_required", "stacks", "cells_per_stack", "electricity_kwh_per_kg"):
        assert after.number(key) == before.number(key)
    assert after.number("reservoir_working_volume_l") == pytest.approx(35 + 20)
    # the duty's schedule leaves the measured range: not feasible, no tank sizes from it
    _edit(
        root,
        "process/duties.yaml",
        lambda d: d["duties"][0]["schedule"]["current_density"].update(value=250),
    )
    report = stack_report(root)
    s = _stack(report)
    assert s.number("stacks") == before.number("stacks")  # the stack is sized on the cell
    assert not s.duty["feasible"] and "cheme.stack-duty" in _rules(report.findings, "error")
    assert _entry(s, "T-101").values["diameter"].provenance == "tbd"
    assert _entry(s, "P-101").complete  # from the arrangement, not the duty
    # inside the range but not the stack's current density: a warning
    _edit(
        root,
        "process/duties.yaml",
        lambda d: d["duties"][0]["schedule"]["current_density"].update(value=120),
    )
    report = stack_report(root)
    assert any(
        f.rule == "cheme.stack-duty" and f.level == "warning" and "sized at 1500" in f.message
        for f in report.findings
    )
    # the cell itself outside the measured range: the stack is refused, never extrapolated
    _edit(root, "process/cells.yaml", lambda c: c["cells"][0]["current"].update(value=25))
    report = stack_report(root)
    s = _stack(report)
    assert s.refused and not s.values
    assert any(
        f.rule == "cheme.stack-cell" and "never extrapolated" in f.message for f in report.findings
    )


def test_infeasible_duty_hint_gives_the_reservoir_that_lasts(tmp_path):
    root = _plant(tmp_path)

    def undosed(data):
        duty = data["duties"][0]
        duty["dosing"] = {"kind": "none"}
        del duty["bleed"]

    _edit(root, "process/duties.yaml", undosed)
    report = stack_report(root)
    finding = next(f for f in report.findings if f.rule == "cheme.stack-duty")
    run = run_duty(root, "SKID-150", 10, 2).duties[0]
    assert run.ended == "threshold"
    need = 20 * 100 / run.time_to_threshold_h
    assert f"{need:.4g} L" in finding.hint
    assert _entry(_stack(report), "T-102").values["diameter"].provenance == "tbd"


def test_missing_inputs_stay_tbd_and_tags_are_checked(tmp_path):
    root = _plant(tmp_path)

    def strip(data):
        stack = data["stacks"][0]
        del stack["envelope"]["cell_pitch"]
        del stack["equipment"]["reservoir"]["aspect_ratio"]
        stack["tags"] = ["E-101A"]

    _edit(root, "process/cells.yaml", strip)
    report = stack_report(root)
    s = _stack(report)
    assert s.values["stack_length_m"].provenance == "tbd"
    assert _entry(s, "T-101").values["height"].provenance == "tbd"
    assert {"cheme.stack-envelope", "cheme.stack-input-missing"} <= _rules(report.findings, "info")
    assert "cheme.stack-tags" in _rules(report.findings, "warning")
    write_stack_inputs(root, report)
    listed = yaml.safe_load((root / "equipment/equipment-list.yaml").read_text())["equipment"]
    by_tag = {i["tag"]: i for i in listed}
    assert "dimensions" not in by_tag["T-101"] and "dimensions" not in by_tag["E-101A"]
    assert "dimensions" in by_tag["T-102"]


def test_hand_written_values_are_kept(tmp_path):
    root = _plant(tmp_path)
    path = root / "equipment/equipment-list.yaml"
    text = path.read_text().replace(
        "    material: PP  # polypropylene for the KOH anolyte\n",
        "    material: PP  # polypropylene for the KOH anolyte\n"
        "    dimensions: {diameter: 0.5, height: 0.8}  # from the vendor\n",
    )
    path.write_text(text)
    _edit(
        root,
        "equipment/datasheets/P-101.yaml",
        lambda d: d["type_specific"].update(
            mass_flow_kg_h={"value": 80, "unit": "kg/h", "source": "vendor curve"}
        ),
    )
    report = stack_report(root)
    s = _stack(report)
    assert _entry(s, "T-101").status == "kept" and _entry(s, "P-101").status == "outdated"
    assert "cheme.stack-kept" in _rules(report.findings, "warning")
    write_stack_inputs(root, report)
    assert "{diameter: 0.5, height: 0.8}  # from the vendor" in path.read_text()
    sheet = yaml.safe_load((root / "equipment/datasheets/P-101.yaml").read_text())
    assert sheet["type_specific"]["mass_flow_kg_h"]["value"] == 80
    assert sheet["type_specific"]["density_kg_m3"]["source"].startswith(STACK_MARK)
    assert sheet["tag"] == "P-101" and sheet["draft"] is True


# -- editing the equipment list -----------------------------------------------------------------

LIST = """\
# a header comment
schema: cheme/equipment/v1
equipment:
  - tag: T-1
    type: Tank
    material: PP  # kept
  - tag: T-2
    type: Tank
    dimensions:
      diameter: 1
      height: 2
      weight: 0.4
    notes: after
  - {tag: T-3, type: Tank}
  - {tag: T-4, type: Tank, dimensions: {diameter: 1, height: 1}}
"""


def test_set_dimensions_keeps_the_rest_of_the_file():
    new = {"diameter": 0.5, "height": 0.75, "source": "cheme process stack: x: y", "assumed": True}
    text = LIST
    for tag in ("T-1", "T-2", "T-3", "T-4"):
        text = set_dimensions(text, tag, new)
    data = yaml.safe_load(text)
    assert [i["dimensions"] for i in data["equipment"]] == [new] * 4
    assert text.startswith("# a header comment\n")
    assert "    material: PP  # kept\n    dimensions:\n      diameter: 0.5\n" in text
    assert "    notes: after\n" in text and data["equipment"][1]["notes"] == "after"
    assert "{tag: T-3, type: Tank, dimensions: {diameter: 0.5, height: 0.75" in text
    with pytest.raises(ValueError):
        set_dimensions(LIST, "T-9", new)


# -- the command, validate and the boundary -----------------------------------------------------


def test_cli_json_is_the_report_and_write(tmp_path, monkeypatch):
    root = _plant(tmp_path)
    monkeypatch.chdir(root)
    result = runner.invoke(app, ["process", "stack", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload == json.loads(stack_report(root).to_json())
    assert payload["model"] == MODEL and payload["assumptions"] and payload["limitations"]
    assert set(payload["source"]["fingerprints"]) >= {
        "process/cells.yaml",
        "process/duties.yaml",
        "experiments/electrochemistry/synthetic-bpm.yaml",
        "equipment/equipment-list.yaml",
        "equipment/datasheets/P-101.yaml",
    }
    text = runner.invoke(app, ["process", "stack"])
    assert "2 stack(s) in parallel on the DC bus, 10 cells in series each" in text.stdout
    assert "[outdated]" in text.stdout
    result = runner.invoke(app, ["process", "stack", "--write"])
    assert result.exit_code == 0, result.output
    assert "wrote equipment/equipment-list.yaml: E-101A, E-101B, T-101, T-102" in result.stdout
    assert "[current]" in result.stdout and "cheme.stack-outdated" not in result.stdout
    assert runner.invoke(app, ["process", "stack", "--write"]).stdout.startswith("nothing to write")
    monkeypatch.chdir(tmp_path)  # the function from elsewhere
    assert not stack_report(root).findings


def test_cli_exit_codes(tmp_path, monkeypatch):
    root = _plant(tmp_path)
    monkeypatch.chdir(root)
    assert runner.invoke(app, ["process", "stack", "NOPE"]).exit_code == 2
    _edit(root, "process/cells.yaml", lambda c: c["stacks"][0].update(cell="NOPE"))
    result = runner.invoke(app, ["process", "stack"])
    assert result.exit_code == 1 and "refused" in result.stdout
    _edit(root, "process/cells.yaml", lambda c: c.pop("stacks"))
    assert runner.invoke(app, ["process", "stack"]).exit_code == 2


def test_validate_reports_stack_findings_without_the_duty(tmp_path):
    from chemeascode.foundation.workspace import Workspace
    from chemeascode.project.validate import validate_workspace

    root = _plant(tmp_path)
    found = stack_findings(root)
    assert {f.rule for f in found} == {"cheme.stack-outdated"}
    assert {f.ids[1] for f in found} == {"E-101A", "E-101B", "P-101"}  # no duty run
    report = validate_workspace(Workspace(root))
    assert {f.ids[1] for f in report.findings if f.rule == "cheme.stack-outdated"} == {
        "E-101A",
        "E-101B",
        "P-101",
    }
    _edit(
        root,
        "process/cells.yaml",
        lambda c: c["stacks"][0]["electrical"]["max_stack_voltage"].update(unit="volt"),
    )
    report = validate_workspace(Workspace(root))
    assert any(f.rule == "cheme.stack-schema" and "volt" in f.message for f in report.findings)
    # a stack the schema refuses refuses the file, as any part of it does
    _edit(root, "process/cells.yaml", lambda c: c["stacks"][0].update(colour="red"))
    report = validate_workspace(Workspace(root))
    assert any(f.rule == "cheme.cell-schema" and "colour" in f.message for f in report.findings)


def test_imports_without_typer():
    code = (
        "import sys; import chemeascode.domains.equipment.electrolyser_stack; "
        "assert 'typer' not in sys.modules and 'fastapi' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
