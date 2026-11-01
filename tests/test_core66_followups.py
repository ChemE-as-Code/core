"""Follow-ups: the independent checks of the cited tables, the public pump
sizing, the datasheet markers ``supplier`` / ``not_applicable`` and what ``fill`` adds or keeps.

The expected pump numbers are the hand calculation of ``test_datasheet_fill`` (same layout)."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from chemeascode.domains.equipment import pumps
from chemeascode.domains.equipment.datasheets import (
    check_datasheets,
    field_path,
    field_state,
    marker_problem,
    open_fields,
    open_tbd,
)
from chemeascode.domains.equipment.fill import fill_datasheets
from chemeascode.domains.equipment.sizing import U_TABLE
from chemeascode.domains.process.hydraulics import DATA as HYDRAULICS
from chemeascode.foundation.workspace import Workspace
from tests.test_datasheet_fill import LAYOUT, _declare, _specific, sized  # noqa: F401

# -- 1. cited tables: every row says which independent source agrees ---------------------------


def test_every_cited_row_names_its_independent_check_and_no_print_check_is_claimed():
    u = yaml.safe_load(U_TABLE.read_text(encoding="utf-8"))
    assert u["print_checked"] is False
    for row, entry in u["rows"].items():
        check = entry.get("check")
        assert check, row
        named = [k for k in u["checks"] if k in check]
        assert named or "unverified" in check, row
    hyd = yaml.safe_load(HYDRAULICS.read_text(encoding="utf-8"))
    assert hyd["print_checked"] is False
    for table in ("roughness", "fittings"):
        for row, entry in hyd[table]["rows"].items():
            assert any(k in str(entry.get("check")) for k in hyd["checks"]), (table, row)
    assert "wikipedia_nps" in hyd["walls"]["check"]
    # the rows the reproductions confirm keep their values
    assert u["rows"]["cooler/light-oils-water"]["range"] == [350, 900]
    assert hyd["fittings"]["rows"]["GlobeValve"]["k"] == 6.0


# -- 2. public pump sizing -----------------------------------------------------------------------


def battery_limit_layout() -> dict:
    """The fill test's layout with the tank taken away: L1 starts at a free end (a battery
    limit) at [0, 0, 2.0]."""
    model = copy.deepcopy(LAYOUT)
    model["equipment"] = [e for e in model["equipment"] if e["tag"] != "T-1"]
    model["pipes"][0]["ends"] = [{}, {"kind": "nozzle", "ref": "P-1/N1"}]
    return model


def test_size_pump_from_a_battery_limit_by_hand():
    duty = pumps.size_pump(
        battery_limit_layout(),
        "P-1",
        suction_from="pipe:L1:start",
        discharge_to="V-2",
        mass_flow_kg_s=10.0,
        density_kg_m3=1000.0,
        viscosity_pa_s=1e-3,
        suction_pressure_kpa=150.0,
        discharge_pressure_kpa=400.0,
        vapour_pressure_kpa=3.17,
        efficiency=0.7,
    )
    assert duty.flow_m3_h == pytest.approx(36.0)
    # (400 - 150) / (rho g) 25.4929 + static 10 - 2 = 8 + suction 0.12173 + discharge 2.27555
    assert duty.differential_head_m == pytest.approx(35.89, abs=0.01)
    assert duty.suction.end == "pipe:L1:start" and duty.suction.pump_nozzle == "P-1/N1"
    assert duty.discharge.end == "V-2/N1" and duty.discharge.pump_nozzle == "P-1/N2"
    # NPSHa = (150 - 3.17) / (rho g) + (2.0 - 0.5) - 0.12173
    assert duty.npsh_available_m == pytest.approx(16.351, abs=0.002)
    assert duty.shaft_power_kw == pytest.approx(5.028, abs=0.002)
    assert duty.assumed  # schedule 40 and roughness by default, ASSUMED
    assert "Table 6-4" in duty.basis["differential_head_m"]
    # a control valve allowance adds its head; no vapour pressure, no efficiency: None
    more = pumps.size_pump(
        battery_limit_layout(),
        "P-1",
        suction_from="pipe:L1:start",
        discharge_to="V-2/N1",
        mass_flow_kg_s=10.0,
        density_kg_m3=1000.0,
        viscosity_pa_s=1e-3,
        suction_pressure_kpa=150.0,
        discharge_pressure_kpa=400.0,
        allowance_kpa=98.0665,
    )
    assert more.differential_head_m == pytest.approx(duty.differential_head_m + 10.0, abs=1e-6)
    assert more.npsh_available_m is None and more.shaft_power_kw is None


def test_size_pump_refuses_an_unknown_end_point():
    with pytest.raises(pumps.SizingError, match="no routed pipe"):
        pumps.size_pump(
            battery_limit_layout(),
            "P-1",
            suction_from="pipe:NOPE:start",
            discharge_to="V-2",
            mass_flow_kg_s=10.0,
            density_kg_m3=1000.0,
            viscosity_pa_s=1e-3,
            suction_pressure_kpa=150.0,
            discharge_pressure_kpa=400.0,
        )
    with pytest.raises(pumps.SizingError, match="no routed path"):
        pumps.route_line(
            battery_limit_layout(),
            "P-1",
            "T-9",
            mass_flow_kg_s=1.0,
            density_kg_m3=1000.0,
            viscosity_pa_s=1e-3,
        )


def unlink_pump(plant: Path) -> None:
    """P-1 out of the flowsheet (its block links no equipment), the tank out of the layout."""
    path = plant / "process" / "flowsheet.yaml"
    flowsheet = yaml.safe_load(path.read_text(encoding="utf-8"))
    for block in flowsheet["blocks"]:
        if block["id"] == "PU":
            block["links"] = []
    path.write_text(yaml.safe_dump(flowsheet, sort_keys=False), encoding="utf-8")
    (plant / "layout" / "plant-model.yaml").write_text(
        yaml.safe_dump(battery_limit_layout()), encoding="utf-8"
    )


def test_fill_sizes_an_unlinked_pump_from_its_declared_end_points(sized: Path):  # noqa: F811
    unlink_pump(sized)

    def q(value, unit, source="D-7"):
        return {"value": value, "unit": unit, "source": source}

    _declare(
        sized,
        "P-1",
        suction_from={"value": "pipe:L1:start", "source": "battery limit CW-1 (D-7)"},
        discharge_to={"value": "V-2", "source": "D-7"},
        mass_flow_kg_h=q(36000, "kg/h"),
        density_kg_m3=q(1000, "kg/m3"),
        viscosity_mpa_s=q(1.0, "mPa s"),
        suction_pressure_kpa=q(150, "kPa(a)"),
        discharge_pressure_kpa=q(400, "kPa(a)"),
        vapour_pressure_kpa=q(3.17, "kPa(a)"),
    )
    result = fill_datasheets(sized, ["P-1"], parameters={"pump_efficiency": "0.7"})
    assert result.written == ["equipment/datasheets/P-1.yaml"], result.findings
    spec = _specific(sized, "P-1")
    assert spec["flow_m3_h"]["value"] == 36.0
    assert spec["differential_head_m"]["value"] == pytest.approx(35.89, abs=0.01)
    assert spec["npsh_available_m"]["value"] == pytest.approx(16.351, abs=0.002)
    assert spec["shaft_power_kw"]["value"] == pytest.approx(5.028, abs=0.002)
    head = spec["differential_head_m"]["source"]
    assert "pipe:L1:start" in head and "pumps.size_pump" in head and "D-7" in head
    # without a declared end point its sizes go back to TBD with the flowsheet's reason
    _declare(sized, "P-1", suction_from={"value": "TBD", "source": "TBD: which battery limit"})
    fill_datasheets(sized, ["P-1"], parameters={"pump_efficiency": "0.7"})
    head = _specific(sized, "P-1")["differential_head_m"]
    assert head["value"] == "TBD" and "no flowsheet node links P-1" in head["source"]


def test_declared_end_points_replace_the_flowsheet_ends_of_a_linked_pump(sized: Path):  # noqa: F811
    _declare(
        sized,
        "P-1",
        density_kg_m3={"value": 1000, "unit": "kg/m3", "source": "D-2"},
        viscosity_mpa_s={"value": 1.0, "unit": "mPa s", "source": "D-2"},
        discharge_to={"value": "V-2/N1", "source": "D-2"},
    )
    fill_datasheets(sized, ["P-1"])
    head = _specific(sized, "P-1")["differential_head_m"]
    assert head["value"] == pytest.approx(35.89, abs=0.01)
    assert "V-2/N1" in head["source"]


def joint_layout() -> dict:
    """T-1/N1 -> L0 -> a plain joint at [5, 0, 1] -> L1 -> P-1/N1."""
    return {
        "equipment": [{"tag": "T-1"}, {"tag": "P-1"}],
        "pipes": [
            {
                "id": "L0",
                "dn": 50,
                "class": {"material": "CS"},
                "points": [[0, 0, 1], [5, 0, 1]],
                "ends": [{"kind": "nozzle", "ref": "T-1/N1"}, {}],
            },
            {
                "id": "L1",
                "dn": 50,
                "class": {"material": "CS"},
                "points": [[5, 0, 1], [10, 0, 1]],
                "ends": [{}, {"kind": "nozzle", "ref": "P-1/N1"}],
            },
        ],
    }


def test_a_pipe_end_point_does_not_block_later_routes_through_it():
    line = {"mass_flow_kg_s": 1.0, "density_kg_m3": 1000.0, "viscosity_pa_s": 1e-3}
    net = pumps.network(joint_layout())
    first = pumps.route_line(net, "P-1", "pipe:L1:start", **line)
    assert first.end == "pipe:L1:start" and first.pump_nozzle == "P-1/N1"
    # the same network still routes through the joint, in either order
    through = pumps.route_line(net, "P-1", "T-1", nozzle="N1", **line)
    fresh = pumps.route_line(pumps.network(joint_layout()), "P-1", "T-1", nozzle="N1", **line)
    assert through.end == fresh.end == "T-1/N1"
    assert through.head_loss_m == pytest.approx(fresh.head_loss_m)
    assert pumps.route_line(net, "P-1", "pipe:L1:start", **line) == first
    # the open end is a target only where it is asked for
    assert pumps.route_line(net, "P-1", "pipe:L0:end", **line).end == "pipe:L0:end"
    # an end on an item nozzle is that nozzle
    assert pumps.network(joint_layout()).endpoint("pipe:L0:start") == "T-1/N1"


# -- 3. datasheet markers --------------------------------------------------------------------------


def test_field_states_and_marker_problems():
    assert field_state({"value": "TBD", "source": "TBD: x"}) == "tbd"
    assert field_state({"value": "supplier", "source": "RFQ-12"}) == "supplier"
    assert field_state({"value": "not_applicable", "reason": "packed"}) == "not_applicable"
    assert field_state({"value": 3.0}) == "value"
    assert marker_problem("not_applicable", {"value": "not_applicable"})
    assert marker_problem("supplier", {"value": "supplier"})
    assert marker_problem("supplier", {"value": "supplier", "source": "the pump curve"}) is None


def test_open_fields_counts_every_value_at_any_depth():
    sheet = {
        "operating": {"flow": {"value": 3.0, "source": "TBD: never read, a source text"}},
        "nozzles": [{"name": "N1", "dn": "TBD", "source": "TBD: P&ID"}, {"name": "N2", "dn": 50}],
        "sizing_basis": [
            {"parameter": "head", "value": "TBD"},
            {"parameter": "flow", "value": 12.0},
        ],
        "type_specific": {
            "stages": {"value": "TBD per stage"},
            "curve": {"impeller_mm": {"value": "TBD"}, "points": [{"value": "supplier"}]},
            "seal": "TBD",
            "speed": {"value": "not_applicable", "reason": "a fixed speed drive"},
        },
    }
    found = {field_path(where): state for where, state, _ in open_fields(sheet)}
    assert found == {
        "nozzles[0].dn": "tbd",
        "sizing_basis[0]": "tbd",
        "type_specific.stages": "tbd",
        "type_specific.curve.impeller_mm": "tbd",
        "type_specific.curve.points[0]": "supplier",
        "type_specific.seal": "tbd",
        "type_specific.speed": "not_applicable",
    }


def test_a_final_sheet_with_a_nested_tbd_fails_the_gate(sized: Path):  # noqa: F811
    from chemeascode.project.checks import _datasheets

    workspace = Workspace(sized)
    for path in sorted((sized / "equipment" / "datasheets").glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        for where, state, _ in open_fields(data):
            if state == "tbd" and len(where) == 2 and isinstance(where[1], str):
                data[where[0]][where[1]] = {"value": "supplier", "source": "RFQ-1"}
        data.pop("draft", None)
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    assert open_tbd(workspace) == {}
    path = sized / "equipment" / "datasheets" / "P-1.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["nozzles"] = [{"name": "N1", "dn": "TBD"}]
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    assert open_tbd(workspace) == {"P-1": ["nozzles[0].dn"]}
    assert _datasheets(workspace)[0] == "fail"
    found = [f for f in check_datasheets(workspace, None) if f.rule == "cheme.datasheet-open"]
    assert len(found) == 1 and "nozzles[0].dn" in found[0].message and found[0].line


def _final(plant: Path, tag: str, **values) -> None:
    _declare(plant, tag, **values)
    path = plant / "equipment" / "datasheets" / f"{tag}.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace("draft: true\n", ""), "utf-8")


def test_a_sheet_whose_open_fields_are_markers_can_be_final(sized: Path):  # noqa: F811
    from chemeascode.project.checks import _datasheets

    workspace = Workspace(sized)
    for path in sorted((sized / "equipment" / "datasheets").glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        for section in ("operating", "design", "materials", "type_specific"):
            for key, entry in (data.get(section) or {}).items():
                if field_state(entry) == "tbd":
                    unit = entry.get("unit", "") if isinstance(entry, dict) else ""
                    data[section][key] = {"value": "supplier", "unit": unit, "source": "RFQ-1"}
        data.pop("draft", None)
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    assert open_tbd(workspace) == {}
    status, detail = _datasheets(workspace)
    assert status == "pass", detail
    # one TBD left on a final sheet: a warning, and the gate fails naming it
    _final(sized, "P-1", npsh_required_m={"value": "TBD", "unit": "m", "source": "TBD: x"})
    assert open_tbd(workspace) == {"P-1": ["type_specific.npsh_required_m"]}
    status, detail = _datasheets(workspace)
    assert status == "fail" and "P-1" in detail and "supplier / not_applicable" in detail
    rules = [f.rule for f in check_datasheets(workspace, None)]
    assert "cheme.datasheet-open" in rules
    # not_applicable without a reason is an error
    _final(
        sized,
        "P-1",
        npsh_required_m={"value": "not_applicable", "unit": "m"},
    )
    found = [f for f in check_datasheets(workspace, None) if f.rule == "cheme.datasheet-marker"]
    assert len(found) == 1 and "needs a reason" in found[0].message and found[0].line
    _final(
        sized,
        "P-1",
        npsh_required_m={"value": "not_applicable", "reason": "a test stand pump, no suction"},
    )
    assert not [f for f in check_datasheets(workspace, None) if f.level == "error"]
    assert _datasheets(workspace)[0] == "pass"


def test_fill_keeps_markers_and_hand_written_tbd_reasons_and_adds_no_foreign_fields(
    sized: Path,  # noqa: F811
):
    _declare(
        sized,
        "E-1",
        area_m2={"value": "TBD", "unit": "m2", "source": "TBD: the vendor's thermal rating (D-9)"},
        duty_kw={"value": "supplier", "unit": "kW", "source": "vendor rating, RFQ-4"},
    )
    _declare(
        sized,
        "C-1",
        number_of_stages={"value": "not_applicable", "reason": "a spray tower, no stages"},
    )
    result = fill_datasheets(sized, ["E-1", "C-1"], parameters={"light_key": "N9"})
    e1, c1 = _specific(sized, "E-1"), _specific(sized, "C-1")
    assert e1["area_m2"]["source"] == "TBD: the vendor's thermal rating (D-9)"
    assert e1["duty_kw"] == {"value": "supplier", "unit": "kW", "source": "vendor rating, RFQ-4"}
    # the LMTD and correction fields an exchanger only gets when they are calculated
    assert "lmtd_k" not in e1 and "correction_factor" not in e1
    assert c1["number_of_stages"]["value"] == "not_applicable"
    # the shortcut's own fields are not added as TBD where it does not run
    for key in ("minimum_stages", "minimum_reflux_ratio", "theoretical_stages"):
        assert key not in c1 or c1[key]["value"] != "TBD", key
    assert "area_m2" in result.tbd["equipment/datasheets/E-1.yaml"]
