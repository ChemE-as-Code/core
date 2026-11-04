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
    _Out,
    report_text,
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
    assert _body(placed, "E-101A") == pytest.approx([0.2, 0.18, 0.18])  # the built geometry
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
    shell = next(p for p in placed["T-101"]["parts"] if p["id"] == "T-101/shell")
    assert shell["radius"] == pytest.approx(d2 / 2, abs=1e-3)
    assert shell["end"][2] - shell["start"][2] == pytest.approx(h2, abs=1e-3)
    dd, dh = _cylinder(200 * 1.2, 1.2)
    assert (placed["T-102"]["dimensions"]["diameter"], placed["T-102"]["dimensions"]["height"]) == (
        dd,
        dh,
    )
    shell = next(p for p in placed["T-102"]["parts"] if p["id"] == "T-102/shell")
    assert shell["radius"] == pytest.approx(dd / 2, abs=1e-3)
    assert shell["end"][2] - shell["start"][2] == pytest.approx(dh, abs=1e-3)
    assert placed["E-101A"]["dimensions"] == {"length": 0.2, "width": 0.18, "height": 0.18}
    assert _body(placed, "E-101A") == pytest.approx([0.2, 0.18, 0.18])
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

    # a new envelope rewrites the stack dimensions this tool wrote, and the built stack bodies
    # carry them: 10 cells x 10 mm + 120 mm long, 100 mm + 2 x 50 mm across
    def envelope(data):
        env = data["stacks"][0]["envelope"]
        env["cell_pitch"]["value"], env["frame_margin"]["value"] = 10, 50

    _edit(root, "process/cells.yaml", envelope)
    fourth, listed, placed = run()
    assert fourth.number("cells_per_stack") == 10
    for tag in ("E-101A", "E-101B"):
        sizes = {k: listed[tag][k] for k in ("length", "width", "height")}
        assert sizes == {"length": 0.22, "width": 0.2, "height": 0.2}
        assert listed[tag]["source"].startswith(STACK_MARK)
        assert placed[tag]["dimensions"] == sizes
        assert _body(placed, tag) == pytest.approx([0.22, 0.2, 0.2])
    # a smaller product duty: fewer cells per stack, a shorter stack in the list and the model
    _edit(
        root, "process/cells.yaml", lambda c: c["stacks"][0]["product"]["rate"].update(value=0.08)
    )
    fifth, listed, placed = run()
    per_stack = fifth.number("cells_per_stack")
    assert per_stack < 10
    length = math.ceil((per_stack * 0.010 + 0.120) * 1000 - 1e-6) / 1000
    assert listed["E-101A"]["length"] == length
    assert _body(placed, "E-101A") == pytest.approx([length, 0.2, 0.2])


def _body(placed, tag):
    """The size of the built body of stack *tag* in the layout model (L, W, H)."""
    return next(p for p in placed[tag]["parts"] if p["id"] == f"{tag}/body")["size"]


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
    # inside the range but not the stack's current density: one operating point or nothing,
    # an error and no reservoir, dosing or bleed inputs (the duty is feasible on its own)
    _edit(
        root,
        "process/duties.yaml",
        lambda d: d["duties"][0]["schedule"]["current_density"].update(value=120),
    )
    report = stack_report(root)
    s = _stack(report)
    assert any(
        f.rule == "cheme.stack-duty" and f.level == "error" and "sized at 1500" in f.message
        for f in report.findings
    )
    assert s.duty["feasible"] and not s.duty["inputs_given"]
    for tag in ("T-101", "T-102"):
        assert _entry(s, tag).values["diameter"].provenance == "tbd"
    assert _entry(s, "P-102").values["mass_flow_kg_h"].provenance == "tbd"
    assert "reservoir_working_volume_l" not in s.values
    assert not {"T-101", "T-102"} & set(
        write_stack_inputs(root, report).written.get("equipment/equipment-list.yaml", [])
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


def test_values_out_of_range_are_schema_errors(tmp_path):
    """A rectifier current, an envelope, a flow, a density, a margin or an interval out of its
    range is a stack-schema error: never a crash, a negative size or a silently dropped value."""
    point = CellPoint("C-100", "specified", 20.0, 2000.0, 0.01, 3.5, 0.9, 2, 1, M_CO)
    for value in (0, -50):
        rectified = {
            **HAND,
            "electrical": {
                **HAND["electrical"],
                "rectifier_max_current": {"value": value, "unit": "A", "provenance": "given"},
            },
        }
        out = _Out(None)
        result = size_stack(Stack.model_validate(rectified), point, out)
        assert "rectifiers" not in result.values
        assert any(
            f.rule == "cheme.stack-schema" and "rectifier_max_current" in f.message
            for f in out.findings
        )
    for name, unit in (("max_stack_voltage", "V"), ("max_stack_current", "A")):
        bad = {
            **HAND,
            "electrical": {
                **HAND["electrical"],
                name: {"value": 0, "unit": unit, "provenance": "given"},
            },
        }
        out = _Out(None)
        assert size_stack(Stack.model_validate(bad), point, out).refused
        assert any(f.rule == "cheme.stack-schema" and name in f.message for f in out.findings)
    q = {"unit": "mm", "provenance": "given"}
    negative = {
        **HAND,
        "envelope": {k: {"value": -5, **q} for k in ("cell_pitch", "end_plates", "frame_margin")},
        "replacement": {"interval": {"value": 0, "unit": "h", "provenance": "given"}},
    }
    out = _Out(None)
    result = size_stack(Stack.model_validate(negative), point, out)
    assert {result.values[k].provenance for k in ("stack_length_m", "stack_width_m")} == {"tbd"}
    assert "no valid envelope" in result.values["stack_length_m"].source
    schema = [f.message for f in out.findings if f.rule == "cheme.stack-schema"]
    assert sum("is not above 0" in m or "is below 0" in m for m in schema) == 4, schema
    assert any("replacement interval" in m for m in schema)

    # through the plant: cheme validate and the skid inputs
    root = _plant(tmp_path)

    def wrong(data):
        stack = data["stacks"][0]
        stack["electrical"]["rectifier_max_current"] = {
            "value": 0,
            "unit": "A",
            "provenance": "assumed",
            "source": "placeholder",
        }
        skid = stack["equipment"]
        skid["recirculation_pump"]["density"]["value"] = -1050
        skid["dosing_pump"]["margin"]["value"] = -0.5
        skid["reservoir"]["margin"]["value"] = -0.1

    _edit(root, "process/cells.yaml", wrong)
    found = stack_findings(root)  # cheme validate's: no ZeroDivisionError
    assert any("rectifier_max_current" in f.message for f in found if f.level == "error")
    report = stack_report(root)
    s = _stack(report)
    assert _entry(s, "P-101").values["mass_flow_kg_h"].provenance == "tbd"
    assert _entry(s, "P-101").values["density_kg_m3"].provenance == "tbd"
    assert _entry(s, "P-101").values["density_kg_m3"].source == "no valid density"
    assert _entry(s, "P-102").values["mass_flow_kg_h"].provenance == "tbd"
    assert "no valid dosing_pump margin" in _entry(s, "P-102").values["mass_flow_kg_h"].source
    assert _entry(s, "T-101").values["diameter"].provenance == "tbd"
    assert _entry(s, "T-102").values["diameter"].provenance != "tbd"
    messages = [f.message for f in report.errors if f.rule == "cheme.stack-schema"]
    assert len(messages) == 4, messages
    written = write_stack_inputs(root, report)  # what is valid is still written
    assert "T-102" in written.written["equipment/equipment-list.yaml"]


def test_a_duty_of_another_cell_gives_no_skid_inputs(tmp_path):
    root = _plant(tmp_path)

    def other(data):
        cell = json.loads(json.dumps(data["cells"][0]))
        cell["id"] = "BPM-200"
        cell["active_area"]["value"] = 50
        cell["current"]["value"] = 7.5
        data["cells"].append(cell)

    _edit(root, "process/cells.yaml", other)
    _edit(root, "process/duties.yaml", lambda d: d["duties"][0].update(cell="BPM-200"))
    report = stack_report(root)
    s = _stack(report)
    assert any(
        f.rule == "cheme.stack-duty" and f.level == "error" and "runs cell BPM-200" in f.message
        for f in report.findings
    )
    for tag in ("T-101", "T-102"):
        assert _entry(s, tag).values["diameter"].provenance == "tbd"
        assert "runs cell BPM-200" in _entry(s, tag).values["diameter"].source
    assert _entry(s, "P-102").values["mass_flow_kg_h"].provenance == "tbd"
    assert s.duty is None  # the duty is not run for this stack
    listed = write_stack_inputs(root, report).written.get("equipment/equipment-list.yaml", [])
    assert listed == ["E-101A", "E-101B"]


def test_the_duty_command_runs_a_skid_duty_at_the_sized_arrangement(tmp_path, monkeypatch):
    """`cheme process duty` and `cheme process stack` run one duty id alike: the arrangement
    the stack is sized at (one design basis), with a cheme.duty-arrangement info finding."""
    from chemeascode.domains.equipment.electrolyser_stack import stack_arrangements
    from chemeascode.domains.process.electrolysis_duty import compare_duties, duty_report

    root = _plant(tmp_path)
    arrangements = stack_arrangements(root)
    assert set(arrangements) == {"SKID-150"}
    a = arrangements["SKID-150"]
    assert (a.cells_in_series, a.stacks, a.by) == (10, 2, "stack STK-1")
    reported = duty_report(root, ["SKID-150"], arrangements)
    alone = reported.duties[0]
    stacked = run_duty(root, "SKID-150", 10, 2).duties[0]
    assert (alone.cells_in_series, alone.stacks) == (10, 2)
    assert alone.totals == stacked.totals and alone.series == stacked.series
    assert any(f.rule == "cheme.duty-arrangement" for f in reported.findings)
    compared = compare_duties(root, ["SKID-150"], 0.1, arrangements=arrangements)
    assert (compared.duties[0].cells_in_series, compared.duties[0].stacks) == (10, 2)
    monkeypatch.chdir(root)
    result = runner.invoke(app, ["process", "duty", "SKID-150", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert (payload["duties"][0]["cells_in_series"], payload["duties"][0]["stacks"]) == (10, 2)
    assert payload["duties"][0]["totals"] == json.loads(json.dumps(stacked.totals))
    assert "cheme.duty-arrangement" in {f["rule"] for f in payload["findings"]}
    # without stacks the duty runs as it states
    _edit(root, "process/cells.yaml", lambda c: c.pop("stacks"))
    assert stack_arrangements(root) == {}
    payload = json.loads(runner.invoke(app, ["process", "duty", "SKID-150", "--json"]).stdout)
    assert (payload["duties"][0]["cells_in_series"], payload["duties"][0]["stacks"]) == (1, 1)


# -- review follow-ups: the pump fill, stale values, shared tags, the checks --------------------


def _list(root):
    data = yaml.safe_load((root / "equipment/equipment-list.yaml").read_text())
    return {i["tag"]: i for i in data["equipment"]}


def _specific(root, tag):
    return yaml.safe_load((root / f"equipment/datasheets/{tag}.yaml").read_text())["type_specific"]


def test_the_pump_inputs_reach_the_pump_fill(tmp_path, monkeypatch):
    """--write gives the recirculation pump its end points (the reservoir, the first stack) with
    the flow and pressures, so `cheme datasheets fill` sizes it as a declared pump: the flow
    from the mass flow and density, the head along the routed lines (none in this fixture: TBD
    with that reason, not 'no flowsheet node links')."""
    from chemeascode.domains.equipment.fill import fill_datasheets

    root = _plant(tmp_path)
    write_stack_inputs(root, stack_report(root))
    spec = _specific(root, "P-101")
    assert spec["suction_from"]["value"] == "T-101"
    assert spec["discharge_to"]["value"] == "E-101A"
    assert spec["suction_from"]["source"].startswith(STACK_MARK)
    assert _entry(_stack(stack_report(root)), "P-101").status == "current"
    monkeypatch.chdir(root)
    assert runner.invoke(app, ["layout", "build"]).exit_code == 0
    fill_datasheets(root, ["P-101"])
    spec = _specific(root, "P-101")
    assert spec["flow_m3_h"]["value"] == pytest.approx(63 / 1050)
    assert "Q = m / rho" in spec["flow_m3_h"]["source"]
    head = spec["differential_head_m"]
    assert head["value"] == "TBD" and "no flowsheet node links" not in head["source"]
    assert "T-101" in head["source"]
    # a hand-written end point at the item's nozzle is the same item: no stack-kept
    spec["suction_from"] = {"value": "T-101/N2", "source": "the P&ID"}
    _edit(root, "equipment/datasheets/P-101.yaml", lambda d: d.update(type_specific=spec))
    report = stack_report(root)
    assert "cheme.stack-kept" not in _rules(report.findings)


def test_a_missing_pump_input_is_tbd_and_its_old_value_cleared(tmp_path):
    root = _plant(tmp_path)
    write_stack_inputs(root, stack_report(root))
    assert _specific(root, "P-101")["discharge_pressure_kpa"]["value"] == pytest.approx(151.3)
    pump = "recirculation_pump"
    _edit(root, "process/cells.yaml", lambda c: c["stacks"][0]["equipment"][pump].pop("viscosity"))
    _edit(
        root,
        "process/cells.yaml",
        lambda c: c["stacks"][0]["equipment"][pump].pop("stack_pressure_drop"),
    )
    report = stack_report(root)
    entry = _entry(_stack(report), "P-101")
    assert entry.values["discharge_pressure_kpa"].provenance == "tbd"
    assert entry.values["discharge_pressure_kpa"].source == "no stack_pressure_drop"
    assert entry.values["viscosity_mpa_s"].provenance == "tbd"
    assert entry.status == "outdated"
    missing = [f for f in report.findings if f.rule == "cheme.stack-input-missing"]
    assert any("discharge_pressure_kpa" in f.message for f in missing)
    stale = [f for f in report.findings if f.rule == "cheme.stack-outdated"]
    assert any("viscosity_mpa_s, discharge_pressure_kpa" in f.message for f in stale), stale
    write_stack_inputs(root, report)
    spec = _specific(root, "P-101")
    for key in ("discharge_pressure_kpa", "viscosity_mpa_s"):
        assert spec[key]["value"] == "TBD" and spec[key]["source"].startswith(STACK_MARK)
    assert spec["suction_pressure_kpa"]["value"] == pytest.approx(101.3)  # still given
    after = stack_report(root)
    assert _entry(_stack(after), "P-101").status == "current"
    assert "cheme.stack-outdated" not in _rules(after.findings)


def test_sizes_written_before_are_flagged_and_removed_once_tbd(tmp_path):
    """An envelope or a tank input removed: the list sizes this tool wrote are outdated, and
    --write removes them (the layout falls back to the placement or the defaults); sizes it
    cannot remove alone (a weight beside them) are kept with a warning."""
    from chemeascode.domains.spatial.model import build_model
    from chemeascode.foundation.workspace import Workspace

    root = _plant(tmp_path)
    write_stack_inputs(root, stack_report(root))
    assert {"E-101A", "T-101"} <= {t for t, i in _list(root).items() if "dimensions" in i}

    def strip(data):
        del data["stacks"][0]["envelope"]
        del data["stacks"][0]["equipment"]["reservoir"]["aspect_ratio"]

    _edit(root, "process/cells.yaml", strip)
    report = stack_report(root)
    s = _stack(report)
    for tag in ("E-101A", "E-101B", "T-101"):
        assert _entry(s, tag).status == "outdated", tag
    outdated = {f.ids[1] for f in report.findings if f.rule == "cheme.stack-outdated"}
    assert {"E-101A", "E-101B", "T-101"} <= outdated
    assert "cheme.stack-outdated" in _rules(stack_findings(root))  # cheme validate too
    written = write_stack_inputs(root, report)
    assert {"E-101A", "E-101B", "T-101"} <= set(written.written["equipment/equipment-list.yaml"])
    listed = _list(root)
    assert "dimensions" not in listed["E-101A"] and "dimensions" not in listed["T-101"]
    assert listed["T-101"]["material"] == "PP" and "dimensions" in listed["T-102"]
    after = stack_report(root)
    assert {_entry(_stack(after), t).status for t in ("E-101A", "T-101")} == {"tbd"}
    assert not {"E-101A", "T-101"} & {
        f.ids[1] for f in after.findings if f.rule == "cheme.stack-outdated"
    }
    placed = {e["tag"]: e for e in build_model(Workspace(root)).document["equipment"]}
    assert placed["E-101A"]["size_from"] != "list"
    # a weight beside the calculated sizes: kept, with a warning to clear them by hand
    root = _plant(tmp_path / "weight")
    write_stack_inputs(root, stack_report(root))
    path = root / "equipment/equipment-list.yaml"
    path.write_text(
        path.read_text().replace("      head: flat\n", "      head: flat\n      weight: 0.1\n", 1)
    )
    _edit(root, "process/cells.yaml", strip)
    report = stack_report(root)
    tank = _entry(_stack(report), "T-101")
    assert tank.status == "kept"
    assert any(
        f.rule == "cheme.stack-kept" and "weight" in f.message and "T-101" in f.ids
        for f in report.findings
    )
    write_stack_inputs(root, report)
    assert _list(root)["T-101"]["dimensions"]["weight"] == 0.1


def test_a_stated_head_or_support_keeps_the_tank(tmp_path):
    root = _plant(tmp_path)
    write_stack_inputs(root, stack_report(root))
    listed = _list(root)
    assert (listed["T-101"]["dimensions"]["head"], listed["T-101"]["dimensions"]["support"]) == (
        "flat",
        "none",
    )

    def legs(data):
        for item in data["equipment"]:
            if item["tag"] == "T-101":
                item["dimensions"].update(head="ellipsoidal_2_1", support="legs")

    _edit(root, "equipment/equipment-list.yaml", legs)
    before = (root / "equipment/equipment-list.yaml").read_text()
    report = stack_report(root)
    tank = _entry(_stack(report), "T-101")
    assert tank.status == "kept"
    kept = [f for f in report.findings if f.rule == "cheme.stack-kept"]
    assert any("head ellipsoidal_2_1 and support legs" in f.message for f in kept), kept
    write_stack_inputs(root, report)
    assert (root / "equipment/equipment-list.yaml").read_text() == before


def test_two_stacks_naming_one_duty_or_tag(tmp_path):
    """The first stack naming a duty runs it, in both commands; a second gets no inputs from
    it, and a tag given twice is written by neither (cheme.stack-duty, cheme.stack-tags)."""
    from chemeascode.domains.equipment.electrolyser_stack import stack_arrangements

    root = _plant(tmp_path)

    def second(data):
        other = json.loads(json.dumps(data["stacks"][0]))
        other["id"], other["tags"] = "STK-2", ["E-201"]
        other["product"]["rate"]["value"] = 0.04
        other["equipment"]["recirculation_pump"]["tag"] = "P-201"
        other["equipment"]["dosing_pump"]["tag"] = "P-202"
        other["equipment"]["dosing_tank"]["tag"] = "T-202"
        data["stacks"].append(other)  # the same duty SKID-150 and the same reservoir T-101

    _edit(root, "process/cells.yaml", second)
    report = stack_report(root)
    one, two = _stack(report), _stack(report, "STK-2")
    assert (one.number("stacks"), one.number("cells_per_stack")) == (2, 10)
    assert (two.number("stacks"), two.number("cells_per_stack")) != (2, 10)
    assert one.duty is not None and two.duty is None
    assert any(
        f.rule == "cheme.stack-duty" and f.level == "error" and "STK-2" in f.ids
        for f in report.findings
    )
    assert _entry(two, "T-202").values["diameter"].provenance == "tbd"
    arrangement = stack_arrangements(root)["SKID-150"]
    assert (arrangement.cells_in_series, arrangement.stacks, arrangement.by) == (
        10,
        2,
        "stack STK-1",
    )
    tags = [f for f in report.findings if f.rule == "cheme.stack-tags" and f.level == "error"]
    assert len(tags) == 1 and "T-101" in tags[0].message
    assert {e.status for e in (one.equipment + two.equipment) if e.tag == "T-101"} == {"conflict"}
    written = write_stack_inputs(root, report)
    assert "T-101" not in written.written["equipment/equipment-list.yaml"]
    assert "dimensions" not in _list(root)["T-101"]
    assert "cheme.stack-duty" in _rules(stack_findings(root))  # cheme validate too


def test_a_rectifier_efficiency_out_of_range_drops_only_the_ac_power(tmp_path):
    point = CellPoint("C-100", "specified", 20.0, 2000.0, 0.01, 3.5, 0.9, 2, 1, M_CO)
    for value, unit in ((1.05, None), (95, "-"), (0, None)):
        bad = {
            **HAND,
            "electrical": {
                **HAND["electrical"],
                "rectifier_efficiency": {"value": value, "unit": unit, "provenance": "given"},
            },
        }
        out = _Out(None)
        result = size_stack(Stack.model_validate(bad), point, out)
        assert not result.refused
        assert "ac_power_kw" not in result.values
        assert result.number("dc_power_kw") == pytest.approx(7.56)
        assert any(
            f.rule == "cheme.stack-schema" and f.level == "error" and "rectifier" in f.message
            for f in out.findings
        )
    percent = {
        **HAND,
        "electrical": {
            **HAND["electrical"],
            "rectifier_efficiency": {"value": 95, "unit": "%", "provenance": "given"},
        },
    }
    result = size_stack(Stack.model_validate(percent), point)
    assert result.number("ac_power_kw") == pytest.approx(7.56 / 0.95)


def test_a_product_a_side_reaction_forms_too_is_refused(tmp_path):
    """O2 is a product of CO2R, but the WS side reaction forms it too: the cell's Faradaic
    efficiency (of CO2R) does not give its rate, and the stack is not sized on it."""
    root = _plant(tmp_path)
    _edit(root, "process/cells.yaml", lambda c: c["stacks"][0]["product"].update(component="O2"))
    report = stack_report(root)
    s = _stack(report)
    assert s.refused and "side reactions" in s.reasons[0]
    assert any(f.rule == "cheme.stack-cell" and f.level == "error" for f in report.findings)


def test_set_and_remove_dimensions_keep_the_rest_of_the_file():
    from chemeascode.domains.equipment.electrolyser_stack import remove_dimensions

    text = LIST
    for tag in ("T-2", "T-4", "T-1"):
        text = remove_dimensions(text, tag)
    data = yaml.safe_load(text)
    assert all("dimensions" not in i for i in data["equipment"])
    assert "    notes: after\n" in text and "    material: PP  # kept\n" in text
    assert "  - {tag: T-4, type: Tank}\n" in text
    assert text == LIST.replace(
        "    dimensions:\n      diameter: 1\n      height: 2\n      weight: 0.4\n", ""
    ).replace(
        "{tag: T-4, type: Tank, dimensions: {diameter: 1, height: 1}}", "{tag: T-4, type: Tank}"
    )


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
    # --write --json: the report as the files are then, and what was written
    fresh = _plant(tmp_path / "json")
    monkeypatch.chdir(fresh)
    result = runner.invoke(app, ["process", "stack", "--write", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["written"] == {
        "equipment/equipment-list.yaml": ["E-101A", "E-101B", "T-101", "T-102"],
        "equipment/datasheets/P-101.yaml": ["P-101"],
        "equipment/datasheets/P-102.yaml": ["P-102"],
    }
    assert {e["status"] for e in payload["stacks"][0]["equipment"]} == {"current"}
    payload = json.loads(runner.invoke(app, ["process", "stack", "--write", "--json"]).stdout)
    assert payload["written"] == {}


def test_cli_exit_codes(tmp_path, monkeypatch):
    root = _plant(tmp_path)
    monkeypatch.chdir(root)
    assert runner.invoke(app, ["process", "stack", "NOPE"]).exit_code == 2
    _edit(root, "process/cells.yaml", lambda c: c["stacks"][0].update(cell="NOPE"))
    result = runner.invoke(app, ["process", "stack"])
    assert result.exit_code == 1 and "refused" in result.stdout
    # a stacks: entry the schema refuses: its finding is printed, exit 1 (not "no stacks")
    _edit(root, "process/cells.yaml", lambda c: c["stacks"][0].update(cell="BPM-100", celll="x"))
    result = runner.invoke(app, ["process", "stack"])
    assert result.exit_code == 1
    assert "cheme.cell-schema" in result.stdout and "celll" in result.stdout
    _edit(root, "process/cells.yaml", lambda c: c.pop("stacks"))
    result = runner.invoke(app, ["process", "stack"])
    assert result.exit_code == 2 and "has no stacks: section" in result.output
    (root / "process/cells.yaml").unlink()
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


# -- skid inputs: refill and emptying intervals, recovery, a duty at the stack's arrangement,
# -- the reservoir volume to the horizon ---------------------------------------------------------


def _tank_volume(entry) -> float:
    """L held by a tank entry (its detail: 'N L (...)')."""
    return float(entry.detail.split(" L", 1)[0])


def test_dosing_and_bleed_tanks_over_their_interval(tmp_path):
    """SKID-150 doses 1 L/h and bleeds 0.8 L/h over 100 h: a dosing tank refilled every 24 h
    holds the 24 L of any 24 h (with its margin), filled ceil(100 / 24) = 5 times; a bleed tank
    emptied every 10 h holds 8 L, emptied 10 times; an interval past the campaign is the
    campaign (as without one); an interval out of range is a schema error, its tank TBD."""
    root = _plant(tmp_path)
    plain = _entry(_stack(stack_report(root)), "T-102")

    def intervals(dosing: dict, bleed: dict | None = None):
        def edit(data):
            skid = data["stacks"][0]["equipment"]
            skid["dosing_tank"]["refill_interval"] = dosing
            if bleed is not None:
                skid["bleed_tank"] = {
                    "tag": "T-103",
                    "margin": {"value": 0.1, "provenance": "assumed", "source": "test"},
                    "aspect_ratio": {"value": 1.0, "provenance": "assumed", "source": "test"},
                    "empty_interval": bleed,
                }

        return edit

    day = {"value": 24, "unit": "h", "provenance": "assumed", "source": "test: daily refill"}
    shift = {"value": 10, "unit": "h", "provenance": "assumed", "source": "test: per shift"}
    _edit(root, "process/cells.yaml", intervals(day, shift))
    report = stack_report(root)
    s = _stack(report)
    dosing, bleed = _entry(s, "T-102"), _entry(s, "T-103")
    assert _tank_volume(dosing) == pytest.approx(24 * 1.2)
    assert (dosing.values["diameter"].value, dosing.values["height"].value) == _cylinder(
        24 * 1.2, 1.2
    )
    assert "in any 24 h of the campaign" in dosing.values["diameter"].source
    assert s.number("dosing_tank_fills_per_campaign") == 5
    assert s.number("dosing_solution_per_fill_l") == pytest.approx(24)
    assert s.number("dosing_solution_l") == pytest.approx(100)  # the campaign's, unchanged
    assert _tank_volume(bleed) == pytest.approx(8 * 1.1)
    assert s.number("bleed_tank_empties_per_campaign") == 10
    assert s.number("bleed_per_empty_l") == pytest.approx(8)
    assert "dosing tank filled 5 ASSUMED time(s)" in report_text(report)
    # an interval past the campaign: the whole campaign, filled once
    _edit(root, "process/cells.yaml", intervals({**day, "value": 30, "unit": "d"}))
    s = _stack(stack_report(root))
    assert _entry(s, "T-102").values["diameter"].value == plain.values["diameter"].value
    assert s.number("dosing_tank_fills_per_campaign") == 1
    # out of range: a schema error, the tank TBD
    _edit(root, "process/cells.yaml", intervals({**day, "value": 0}))
    report = stack_report(root)
    assert "cheme.stack-schema" in _rules(report.findings, "error")
    assert _entry(_stack(report), "T-102").values["diameter"].provenance == "tbd"


def test_an_interval_belongs_to_its_tank():
    """refill_interval is the dosing tank's, empty_interval the bleed tank's (schema)."""
    from pydantic import ValidationError

    base = {**HAND, "equipment": {"duty": "D"}}
    interval = {"value": 24, "unit": "h", "provenance": "assumed"}
    for role, key in (
        ("reservoir", "refill_interval"),
        ("bleed_tank", "refill_interval"),
        ("dosing_tank", "empty_interval"),
    ):
        stack = json.loads(json.dumps(base))
        stack["equipment"][role] = {"tag": "T-1", key: interval}
        with pytest.raises(ValidationError):
            Stack.model_validate(stack)


def test_the_largest_window_of_a_piecewise_linear_total():
    from chemeascode.domains.equipment.electrolyser_stack import _largest_over

    times, total = [0, 1, 2, 3, 4], [0, 0, 2, 2, 3]
    assert _largest_over(times, total, 1) == pytest.approx(2)
    assert _largest_over(times, total, 0.5) == pytest.approx(1)
    assert _largest_over(times, total, 2.5) == pytest.approx(2.5)
    assert _largest_over(times, total, 10) == pytest.approx(3)


def test_product_recovery_sizes_for_the_product_formed():
    """The hand case at recovery 0.9: 1 kg/h delivered is 1.11111 kg/h formed, A = 1.18130 m2,
    119 cells (10 stacks of 12: 120 cells), output 1.12865 kg/h formed and 1.01579 kg/h
    delivered; kWh per kg delivered is that formed over the recovery. Without a recovery the
    stack and its fingerprint are as before; above 1 or not above 0 it is refused."""
    from chemeascode.domains.equipment.electrolyser_stack import _dump

    point = CellPoint("C-100", "specified", 20.0, 2000.0, 0.01, 3.5, 0.9, 2, 1, M_CO)
    plain = size_stack(Stack.model_validate(HAND), point)
    stack = json.loads(json.dumps(HAND))
    stack["product"]["recovery"] = {"value": 0.9, "provenance": "assumed", "source": "test: PSA"}
    result = size_stack(Stack.model_validate(stack), point)
    assert not result.refused
    n = result.number
    assert n("product_duty_kg_h") == 1 and n("product_recovery") == 0.9
    assert n("product_formed_duty_kg_h") == pytest.approx(1 / 0.9)
    assert n("total_active_area_m2") == pytest.approx(plain.number("total_active_area_m2") / 0.9)
    assert n("total_active_area_m2") == pytest.approx(1.181296, rel=1e-5)
    assert (n("cells_required"), n("stacks"), n("cells_per_stack")) == (119, 10, 12)
    assert n("product_output_kg_h") == pytest.approx(120 * 0.9 * 20 / (2 * FARADAY) * M_CO * 3.6)
    assert n("product_delivered_kg_h") == pytest.approx(0.9 * n("product_output_kg_h"))
    assert n("output_margin") == pytest.approx(n("product_delivered_kg_h") - 1)
    assert n("electricity_kwh_per_kg_delivered") == pytest.approx(n("electricity_kwh_per_kg") / 0.9)
    assert result.values["total_current_a"].assumed  # rests on the assumed recovery
    assert "product_recovery" not in plain.values and "product_delivered_kg_h" not in plain.values
    assert "recovery" not in _dump(Stack.model_validate(HAND), set())["product"]
    # a percentage is the same; out of range is refused
    stack["product"]["recovery"] = {"value": 90, "unit": "%", "provenance": "assumed"}
    assert size_stack(Stack.model_validate(stack), point).number("cells_required") == 119
    for bad in (1.2, 0):
        stack["product"]["recovery"] = {"value": bad, "provenance": "assumed", "source": "x"}
        out = _Out(None)
        refused = size_stack(Stack.model_validate(stack), point, out)
        assert refused.refused and "cheme.stack-schema" in _rules(out.findings, "error")


def _comparison_duties(root: Path, **onoff) -> None:
    """D-ONOFF (on and off at 150 mA/cm2) and D-PART (150 and 100 mA/cm2) on STK-1's skid
    hardware: the reservoir of SKID-150, no dosing; each names STK-1."""

    def edit(data):
        base = data["duties"][0]
        for did, schedule in (
            (
                "D-ONOFF",
                {
                    "kind": "on_off",
                    "period": {"value": 24, "unit": "h"},
                    "duty_fraction": 0.5,
                    "current_density": {"value": 150, "unit": "mA/cm2"},
                },
            ),
            (
                "D-PART",
                {"kind": "piecewise", "points": [[0, 150], [12, 100]], "unit": "mA/cm2"},
            ),
        ):
            duty = json.loads(json.dumps(base))
            duty.update(id=did, stack="STK-1", schedule=schedule)
            duty["dosing"] = {"kind": "none"}
            duty.pop("bleed")
            duty.update(onoff if did == "D-ONOFF" else {})
            data["duties"].append(duty)

    _edit(root, "process/duties.yaml", edit)


def test_a_duty_naming_the_stack_runs_at_its_arrangement(tmp_path, monkeypatch):
    """Comparison duties name the stack (stack: STK-1): `cheme process duty` and --compare run
    them at its 10 cells x 2 stacks; a duty that also states another arrangement, names a
    stack another stack's equipment runs it for, or a stack of another cell, is refused
    (cheme.duty-arrangement, error); one that states the same arrangement runs."""
    from chemeascode.domains.equipment.electrolyser_stack import stack_arrangements
    from chemeascode.domains.process.electrolysis_duty import compare_duties, duty_report

    root = _plant(tmp_path)
    _comparison_duties(root)
    arrangements = stack_arrangements(root)
    assert set(arrangements) == {"SKID-150", "D-ONOFF", "D-PART"}
    for did in ("D-ONOFF", "D-PART"):
        a = arrangements[did]
        assert (a.cells_in_series, a.stacks, a.stack) == (10, 2, "STK-1")
    report = duty_report(root, ["D-ONOFF", "D-PART"], arrangements)
    assert not report.errors, [f.format() for f in report.errors]
    for d in report.duties:
        assert (d.cells_in_series, d.stacks) == (10, 2)
    compared = compare_duties(root, ["D-ONOFF", "D-PART"], 0.5, arrangements=arrangements)
    assert {(d.cells_in_series, d.stacks) for d in compared.duties} == {(10, 2)}
    monkeypatch.chdir(root)
    result = runner.invoke(app, ["process", "duty", "--compare", "D-ONOFF,D-PART", "--co", "0.5"])
    assert "cheme.duty-arrangement" in result.stdout and "error" not in result.stdout.lower()
    # the stack's own skid inputs are those of its equipment.duty, as before
    assert _stack(stack_report(root)).duty["id"] == "SKID-150"
    from chemeascode.domains.process.electrolysis_duty import duty_findings

    assert not [f for f in duty_findings(root) if f.level == "error"]
    # the same arrangement stated: it runs; another: refused, not run at either
    _edit(root, "process/duties.yaml", lambda d: d["duties"][1].update(cells_in_series=10))
    assert not duty_report(root, ["D-ONOFF"], stack_arrangements(root)).errors
    _edit(root, "process/duties.yaml", lambda d: d["duties"][1].update(cells_in_series=7))
    report = duty_report(root, ["D-ONOFF"], stack_arrangements(root))
    d = report.duties[0]
    assert d.refused and "cells_in_series 7" in d.reasons[0]
    assert any(f.rule == "cheme.duty-arrangement" and f.level == "error" for f in report.findings)
    result = runner.invoke(app, ["process", "duty", "D-ONOFF"])
    assert result.exit_code == 1
    # the duty STK-1's equipment runs names another stack: refused there and in the stack
    _edit(root, "process/duties.yaml", lambda d: d["duties"][0].update(stack="STK-2"))
    report = duty_report(root, ["SKID-150"], stack_arrangements(root))
    assert report.duties[0].refused and "stack STK-1 runs it" in report.duties[0].reasons[0]
    stacks = stack_report(root)
    assert any(
        f.rule == "cheme.stack-duty" and "names stack STK-2" in f.message for f in stacks.findings
    )
    assert _entry(_stack(stacks), "T-101").values["diameter"].provenance == "tbd"


def _to_horizon(root: Path) -> None:
    """SKID-150 without dosing or bleed, its reservoir sized to the horizon (text edits: the
    file's comments stay) and without the dosing tank."""
    path = root / "process/duties.yaml"
    text = path.read_text(encoding="utf-8")
    start = text.index("    dosing:\n")
    end = text.index("    threshold:")
    text = text[:start] + "    dosing: {kind: none}\n" + text[end:]
    text = text.replace(
        "      model: well-mixed-carbonate\n",
        "      model: well-mixed-carbonate\n      size: to_horizon  # cheme process stack\n",
    )
    path.write_text(text, encoding="utf-8")
    _edit(root, "process/cells.yaml", lambda c: c["stacks"][0]["equipment"].pop("dosing_tank"))


def test_reservoir_size_to_horizon_is_written_into_the_duty(tmp_path, monkeypatch):
    """With reservoir.size: to_horizon the 20 L reservoir reaches the threshold before the
    horizon: the stack reports the exact volume V0 H / t_thr (stack-outdated on the duty) and no
    tanks; --write writes it, rounded up to 4 significant figures, into process/duties.yaml
    (comments kept), and in the same run the reservoir tank from the duty at that volume; then
    everything is current and the duty is feasible."""
    root = _plant(tmp_path)
    _to_horizon(root)
    run = run_duty(root, "SKID-150", 10, 2).duties[0]
    assert run.ended == "threshold"
    exact = 20 * 100 / run.time_to_threshold_h
    report = stack_report(root)
    s = _stack(report)
    assert s.number("reservoir_required_volume_l") == pytest.approx(exact, rel=1e-12)
    volume = _entry(s, "SKID-150")
    assert volume.target == "duty" and volume.status == "outdated"
    written = volume.values["volume"].value
    assert written == math.ceil(exact * (1 + 1e-6) * 100) / 100  # 4 figures: 0.01 L here
    assert written >= exact * (1 + 1e-6)
    assert _entry(s, "T-101").values["diameter"].provenance == "tbd"
    finding = next(f for f in report.findings if f.rule == "cheme.stack-duty")
    assert "--write` writes the reservoir volume" in finding.hint
    monkeypatch.chdir(root)
    result = runner.invoke(app, ["process", "stack", "--write"])
    assert result.exit_code == 0, result.output
    assert "wrote process/duties.yaml: SKID-150" in result.stdout
    assert "T-101" in result.stdout.split("wrote equipment/equipment-list.yaml: ", 1)[1]
    text = (root / "process/duties.yaml").read_text(encoding="utf-8")
    assert text.startswith("# The skid's duty (tests only)")  # the comments kept
    assert "size: to_horizon  # cheme process stack" in text
    duty = yaml.safe_load(text)["duties"][0]
    assert duty["reservoir"]["volume"]["value"] == written
    assert duty["reservoir"]["volume"]["source"].startswith(STACK_MARK)
    report = stack_report(root)
    s = _stack(report)
    assert s.duty["feasible"] and {e.status for e in s.equipment} == {"current", "tbd"}
    assert s.number("reservoir_working_volume_l") == pytest.approx(written)
    assert _entry(s, "T-101").values["diameter"].value == _cylinder(written * 1.25, 1.5)[0]
    assert s.number("reservoir_required_volume_l") == pytest.approx(exact, rel=1e-9)
    assert not report.errors
    assert runner.invoke(app, ["process", "stack", "--write"]).stdout.startswith("nothing to write")


def test_reservoir_size_to_horizon_with_dosing_writes_nothing(tmp_path):
    """The fixture's duty doses and bleeds: size: to_horizon is a cheme.duty-size error, the
    stack's reservoir volume TBD (nothing written into the duty), the tanks as without it."""
    root = _plant(tmp_path)
    plain = _stack(stack_report(root))
    _edit(
        root,
        "process/duties.yaml",
        lambda d: d["duties"][0]["reservoir"].update(size="to_horizon"),
    )
    report = stack_report(root)
    s = _stack(report)
    volume = _entry(s, "SKID-150")
    assert volume.status == "tbd" and "dosing" in volume.values["volume"].source
    assert _entry(s, "T-101").values == _entry(plain, "T-101").values
    assert "process/duties.yaml" not in write_stack_inputs(root, report).written
    run = run_duty(root, "SKID-150", 10, 2)
    assert any(f.rule == "cheme.duty-size" and f.level == "error" for f in run.findings)


def test_set_duty_volume_keeps_the_rest_of_the_file():
    """A block or flow reservoir volume is replaced by a flow mapping, the rest as it was; an
    edit that changes more is refused."""
    from chemeascode.domains.equipment.electrolyser_stack import _check_duties, set_duty_volume

    text = (
        "# duties\nschema: cheme/electrolysis-duties/v1\nkind: electrolysis_duties\nduties:\n"
        "- id: A  # the skid\n  cell: C\n"
        "  schedule: {kind: constant_current, current: {value: 1, unit: A}}\n"
        "  reservoir:\n    volume:\n      value: 20\n      unit: L\n"
        "    composition: {hydroxide: {value: 1, unit: mol/L}}  # fresh\n    model: m\n"
        "    size: to_horizon\n  threshold: {ph: 12}\n  horizon: {value: 100, unit: h}\n"
        "- id: B\n  cell: C\n"
        "  schedule: {kind: constant_current, current: {value: 1, unit: A}}\n"
        "  reservoir: {volume: {value: 2, unit: L}, composition: {}, model: m}\n"
        "  threshold: {ph: 12}\n  horizon: {value: 100, unit: h}\n"
    )
    a = {"value": 91.0, "unit": "L", "source": "cheme process stack: x"}
    b = {**a, "value": 3.5}
    new = set_duty_volume(set_duty_volume(text, "A", a), "B", b)
    _check_duties(text, new, {"A": a, "B": b})
    assert '    volume: {value: 91.0, unit: L, source: "cheme process stack: x"}\n' in new
    assert "# duties\n" in new and "- id: A  # the skid\n" in new and "  # fresh\n" in new
    assert "  reservoir: {volume: {value: 3.5, unit: L, source:" in new  # B in its flow mapping
    with pytest.raises(ValueError, match="changes more"):
        _check_duties(text, new.replace("ph: 12", "ph: 11", 1), {"A": a, "B": b})
    with pytest.raises(ValueError, match="no reservoir.volume"):
        set_duty_volume(text, "Z", a)


# -- review fixes: the skid duty's own stack, intervals, minimum inventory, reporting ----------


def test_a_skid_duty_naming_its_stack_with_another_arrangement_is_refused(tmp_path):
    """SKID-150 names its own stack (stack: STK-1): with the sized arrangement stated, or
    none, it gives the skid inputs; with cells_in_series 7 both commands refuse it
    (cheme.stack-duty and cheme.duty-arrangement, errors) and the tanks stay TBD."""
    from chemeascode.domains.equipment.electrolyser_stack import stack_arrangements
    from chemeascode.domains.process.electrolysis_duty import duty_report

    root = _plant(tmp_path)
    _edit(root, "process/duties.yaml", lambda d: d["duties"][0].update(stack="STK-1"))
    s = _stack(stack_report(root))
    assert s.duty["inputs_given"]
    _edit(root, "process/duties.yaml", lambda d: d["duties"][0].update(cells_in_series=10))
    assert _stack(stack_report(root)).duty["inputs_given"]
    _edit(root, "process/duties.yaml", lambda d: d["duties"][0].update(cells_in_series=7))
    report = stack_report(root)
    s = _stack(report)
    error = next(f for f in report.errors if f.rule == "cheme.stack-duty")
    assert "states cells_in_series 7" in error.message
    assert not s.duty or not s.duty.get("inputs_given")
    for tag in ("T-101", "T-102", "P-102"):
        assert not _entry(s, tag).complete
    duty = duty_report(root, ["SKID-150"], stack_arrangements(root))
    assert duty.duties[0].refused and "cells_in_series 7" in duty.duties[0].reasons[0]


def test_an_interval_of_a_tank_without_flow_is_still_checked(tmp_path):
    """A bleed tank's empty_interval out of range is a cheme.stack-schema error also when the
    duty bleeds nothing (the tank is TBD either way)."""
    root = _plant(tmp_path)
    _edit(root, "process/duties.yaml", lambda d: d["duties"][0].pop("bleed"))

    def tank(interval):
        def edit(data):
            data["stacks"][0]["equipment"]["bleed_tank"] = {
                "tag": "T-103",
                "margin": {"value": 0.1, "provenance": "assumed", "source": "test"},
                "aspect_ratio": {"value": 1.0, "provenance": "assumed", "source": "test"},
                "empty_interval": interval,
            }

        return edit

    good = {"value": 10, "unit": "h", "provenance": "assumed", "source": "test"}
    _edit(root, "process/cells.yaml", tank(good))
    report = stack_report(root)
    assert "cheme.stack-schema" not in _rules(report.findings)
    assert _entry(_stack(report), "T-103").values["diameter"].provenance == "tbd"
    for bad in ({**good, "value": 0}, {**good, "unit": "A"}):
        _edit(root, "process/cells.yaml", tank(bad))
        report = stack_report(root)
        schema = [f for f in report.errors if f.rule == "cheme.stack-schema"]
        assert any("bleed_tank empty_interval" in f.message for f in schema), bad
        assert _entry(_stack(report), "T-103").values["diameter"].provenance == "tbd"


def test_reservoir_size_to_horizon_with_a_minimum_inventory_writes_a_feasible_volume(
    tmp_path, monkeypatch
):
    """SKID-150 without dosing or bleed at 200 L, sized to the horizon with 74.2 mol of K+
    kept: the written volume keeps the minimum to the horizon, so after --write the duty is
    feasible, its tanks given and nothing is left to write."""
    root = _plant(tmp_path)
    _to_horizon(root)

    def edit(data):
        duty = data["duties"][0]
        duty["reservoir"]["volume"]["value"] = 200
        duty["minimum_inventory"] = {"cation": {"value": 74.2, "unit": "mol"}}

    _edit(root, "process/duties.yaml", edit)
    s = _stack(stack_report(root))
    assert s.duty["feasible"]
    exact = s.number("reservoir_required_volume_l")
    assert "the stated minimum cation inventory" in _entry(s, "SKID-150").detail
    monkeypatch.chdir(root)
    result = runner.invoke(app, ["process", "stack", "--write"])
    assert result.exit_code == 0, result.output
    report = stack_report(root)
    s = _stack(report)
    assert not report.errors, [f.format() for f in report.errors]
    assert s.duty["feasible"] and s.duty["ended"] == "horizon" and s.duty["inputs_given"]
    assert _entry(s, "T-101").complete
    assert s.number("reservoir_required_volume_l") == pytest.approx(exact, rel=1e-9)
    assert runner.invoke(app, ["process", "stack", "--write"]).stdout.startswith("nothing to write")


def test_a_duty_volume_with_no_target_is_reported():
    """The duty's reservoir volume compares against process/duties.yaml: a duty without a
    usable reservoir.volume there is no-target (info); a TBD volume is tbd."""
    from chemeascode.domains.equipment.electrolyser_stack import (
        EquipmentInput,
        Sized,
        _compare_duty,
    )

    root = DATA / "co2-skid"
    entry = EquipmentInput("NO-SUCH-DUTY", "reservoir_volume", "duty", "process/duties.yaml")
    entry.values = {"volume": Sized(12.5, "L", "calculated", "test")}
    out = _Out(None)
    _compare_duty(root, entry, out, "STK-1", [])
    assert entry.status == "no-target"
    assert [(f.level, f.rule) for f in out.findings] == [("info", "cheme.stack-target")]
    entry.values = {"volume": Sized("TBD", "L", "tbd", "test")}
    _compare_duty(root, entry, _Out(None), "STK-1", [])
    assert entry.status == "tbd"


def test_a_dosing_tank_over_its_interval_with_threshold_dosing(tmp_path):
    """Dosing on a pH trigger (2 L/h when on) over 20 h with a refill every 10 h: the tank
    holds the most dosed in any 10 h of the on and off periods the duty reports (its events),
    found here from those periods directly."""
    root = _plant(tmp_path)

    def duty(data):
        d = data["duties"][0]
        d["dosing"] = {
            "kind": "on_threshold",
            "trigger_ph": 13.8,
            "stop_ph": 13.9,
            "concentration": {"value": 2, "unit": "mol/L"},
            "rate": {"value": 2, "unit": "L/h"},
            "density": {"value": 1.1, "unit": "kg/L", "source": "test: about 2 M KOH"},
        }
        d["horizon"]["value"] = 20

    _edit(root, "process/duties.yaml", duty)
    refill = {"value": 10, "unit": "h", "provenance": "assumed", "source": "test"}
    _edit(
        root,
        "process/cells.yaml",
        lambda c: c["stacks"][0]["equipment"]["dosing_tank"].update(refill_interval=refill),
    )
    run = run_duty(root, "SKID-150", 10, 2).duties[0]
    assert run.feasible
    switches = [(e["kind"], e["t_h"]) for e in run.events if e["kind"].startswith("dosing-")]
    assert len(switches) >= 4  # on and off more than once
    periods, start = [], None
    for kind, t in switches:
        if kind == "dosing-on":
            start = t
        elif start is not None:
            periods.append((start, t))
            start = None
    if start is not None:
        periods.append((start, 20.0))

    def dosed(t):
        return 2 * sum(max(0.0, min(b, t) - a) for a, b in periods)

    starts = {0.0, 10.0} | {
        x for a, b in periods for t in (a, b) for x in (t, t - 10) if 0 <= x <= 10
    }
    largest = max(dosed(t + 10) - dosed(t) for t in starts)
    s = _stack(stack_report(root))
    assert s.number("dosing_solution_per_fill_l") == pytest.approx(largest, rel=1e-6)
    assert s.number("dosing_tank_fills_per_campaign") == 2
    assert _tank_volume(_entry(s, "T-102")) == pytest.approx(largest * 1.2, rel=1e-5)
    assert largest < s.number("dosing_solution_l")  # less than the whole campaign's


def test_the_report_text_gives_the_product_formed_and_delivered(tmp_path):
    """With product.recovery the report text names the duty delivered and the product formed
    at that recovery; without it, neither."""
    root = _plant(tmp_path)
    assert "delivered (formed" not in report_text(stack_report(root, duties=False))
    _edit(
        root,
        "process/cells.yaml",
        lambda c: c["stacks"][0]["product"].update(
            recovery={"value": 0.9, "provenance": "assumed", "source": "test: PSA"}
        ),
    )
    report = stack_report(root, duties=False)
    s = _stack(report)
    text = report_text(report)
    assert "delivered (formed" in text and "at recovery 0.9" in text
    assert f"{s.number('product_formed_duty_kg_h'):.6g}" in text
