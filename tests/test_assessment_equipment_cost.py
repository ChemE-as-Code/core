"""The equipment estimate from published correlations (Turton et al., CAPCOST): hand-calculated
purchased and bare module costs, pressure and material factors, escalation by the project's
index, range and coverage findings, and the gate requirements."""

from __future__ import annotations

import math
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from chemeascode.domains.assessment.equipment_cost import (
    capcost,
    choose,
    equipment_estimate,
    estimate_equipment,
    material_of,
    pressure_factor,
    purchased_cost,
    vessel_pressure_factor,
)
from chemeascode.domains.assessment.gates import mto_gate
from chemeascode.domains.assessment.schemas import CostBasis
from chemeascode.domains.equipment.schemas.equipment import EquipmentList
from chemeascode.interfaces.cli import app

runner = CliRunner()


def listed(*items):
    return EquipmentList.model_validate({"equipment": list(items)})


def test_every_package_row_names_its_table_and_cross_check():
    data = capcost()
    assert data["base_cepci"]["value"] == 397 and data["base_cepci"]["year"] == 2001
    for name, row in data["correlations"].items():
        assert row["table"] == "A.1" and row["check"], name
        assert row["min"] < row["max"] and len(row["K"]) == 3
    for section in ("pressure", "material", "bare_module"):
        for name, row in data[section].items():
            assert name in data["correlations"] and row["check"], (section, name)


def test_hand_calculated_vertical_vessel():
    # A = 10 m3: log10 Cp0 = 3.4974 + 0.4485 + 0.1074 = 4.0533 -> 11 308 USD (CEPCI 397)
    assert purchased_cost("vessel_vertical", 10.0) == pytest.approx(10**4.0533, rel=1e-9)
    # Fp at 10 barg, D 2 m: (11 x 2 / (2 (850 - 6.6)) + 0.00315) / 0.0063 = 2.5703
    fp = vessel_pressure_factor(10.0, 2.0)
    assert fp == pytest.approx((22 / 1686.8 + 0.00315) / 0.0063, rel=1e-9)
    assert fp == pytest.approx(2.5703, abs=1e-4)
    assert vessel_pressure_factor(0.0, 1.0) == 1.0  # at least 1
    item = {
        "tag": "V-1",
        "type": "PressureVessel",
        "design_pressure_barg": 10,
        "material": "SS 316L",
        "dimensions": {"diameter": 2.0, "height": 3.1830989},  # pi/4 x 4 x h = 10 m3
    }
    basis = CostBasis.model_validate(
        {"cost_index": {"value": 794.0, "year": 2030, "source": "test value"}}
    )
    result = estimate_equipment(listed(item), {}, basis)
    (line,) = result.lines
    cp0 = 10**4.0533
    fbm = 2.25 + 1.82 * 3.1 * fp  # B1 + B2 Fm Fp, SS vessel
    assert line.status == "bare module" and line.fm == 3.1
    assert line.size == pytest.approx(10.0, abs=1e-3)
    assert line.cbm_base == pytest.approx(cp0 * fbm, rel=1e-4)
    assert line.bare_module == pytest.approx(cp0 * fbm * 2.0, rel=1e-4)  # 794 / 397
    assert not [f for f in result.findings if f.level != "info"]


def test_hand_calculated_exchanger_pump_and_compressor():
    # floating head, 100 m2: log10 Cp0 = 4.8306 - 0.8509 x 2 + 0.3187 x 4 = 4.4036
    assert purchased_cost("hx_floating_head", 100.0) == pytest.approx(10**4.4036, rel=1e-9)
    # shell and tube Fp at 41 barg (Table A.2): log10 Fp = 0.03881 - 0.11272 x + 0.08183 x^2
    x = math.log10(41.0)
    expected = 10 ** (0.03881 - 0.11272 * x + 0.08183 * x * x)
    assert pressure_factor([0.03881, -0.11272, 0.08183], 41.0) == pytest.approx(expected)
    pump = {
        "tag": "P-1",
        "type": "CentrifugalPump",
        "design_pressure_barg": 5,
        "material": "CS",
    }
    compressor = {"tag": "K-1", "type": "CentrifugalCompressor", "material": "carbon steel"}
    sheets = {
        "P-1": _sheet("P-1", {"shaft_power_kw": 10}),
        "K-1": _sheet("K-1", {"fluid_power_kw": {"value": 1000, "unit": "kW", "source": "x"}}),
    }
    result = estimate_equipment(listed(pump, compressor), sheets, None)
    p, k = result.lines
    # pump: 10 kW -> log10 Cp0 = 3.3892 + 0.0536 + 0.1538; Fp 1 below 10 barg; Fm CS 1.6
    assert p.cp0_base == pytest.approx(10 ** (3.3892 + 0.0536 + 0.1538), rel=1e-9)
    assert p.fp == 1.0 and p.fbm == pytest.approx(1.89 + 1.35 * 1.6)
    # compressor: 1000 kW -> log10 Cp0 = 2.2897 + 1.3604 x 3 - 0.1027 x 9; FBM CS 2.7 directly
    assert k.cp0_base == pytest.approx(10 ** (2.2897 + 1.3604 * 3 - 0.1027 * 9), rel=1e-9)
    assert k.fbm == 2.7 and k.size_source == "datasheet type_specific.fluid_power_kw (x)"
    assert "FBM CS centrifugal (Figure A.19)" in k.notes
    # no index: the base year stays, and says so
    assert any(f.rule == "cheme.estimate-no-index" for f in result.findings)
    assert p.index_ratio is None and p.bare_module == pytest.approx(p.cbm_base)


def _sheet(tag, specific, **extra):
    from chemeascode.domains.equipment.schemas.datasheet import Datasheet

    return Datasheet.model_validate({"tag": tag, "type_specific": specific, **extra})


def test_the_centrifugal_compressor_factor_is_not_applied_to_other_kinds():
    sheet = {"fluid_power_kw": 1000}
    kinds = {
        "K-1": "CentrifugalCompressor",
        "K-2": "ReciprocatingCompressor",
        "K-3": "AxialCompressor",
        "K-4": "Compressor",
    }
    items = [{"tag": t, "type": c, "material": "CS"} for t, c in kinds.items()]
    result = estimate_equipment(listed(*items), {t: _sheet(t, sheet) for t in kinds}, None)
    centrifugal, recip, axial, plain = result.lines
    assert centrifugal.fbm == 2.7 and centrifugal.status == "bare module"
    # the purchased cost row is shared; the bare module factor is not: purchased cost only
    for line, kind in ((recip, "reciprocating"), (axial, "axial")):
        assert line.status == "purchased only" and line.fbm is None
        assert line.purchased == pytest.approx(centrifugal.purchased)
        assert f"centrifugal machine only, not {kind}" in line.notes
    partial = {f.key for f in result.findings if f.rule == "cheme.estimate-equipment-partial"}
    assert partial == {"K-2", "K-3"}
    # a class naming no kind: the centrifugal factor, marked ASSUMED
    assert plain.fbm == 2.7 and "ASSUMED centrifugal: the class names no kind" in plain.notes


def test_a_datasheet_size_keeps_its_source_its_assumption_and_its_draft_state():
    item = {
        "tag": "C-1",
        "type": "ProcessColumn",
        "design_pressure_barg": 1,
        "material": "CS",
        "dimensions": {"diameter": 2.0, "height": 10.0},
    }
    volume = {"value": 31.416, "unit": "m3", "source": "pi/4 D^2 x height", "assumed": True}
    sheet = _sheet("C-1", {"volume_m3": volume}, draft=True)
    result = estimate_equipment(listed(item), {"C-1": sheet}, None)
    (line,) = result.lines
    assert line.size_source == (
        "draft datasheet type_specific.volume_m3 (ASSUMED: pi/4 D^2 x height)"
    )
    (draft,) = [f for f in result.findings if f.rule == "cheme.estimate-draft-size"]
    assert draft.level == "info" and draft.ids == ["C-1"]
    # the CSV row carries it too: the same marking as the list-dimension path
    from chemeascode.domains.assessment.equipment_cost import cost_csv

    assert "ASSUMED: pi/4 D^2 x height" in cost_csv(result)
    # a completed datasheet, a value it knows: its source, no ASSUMED, no draft finding
    known = {"value": 30.0, "unit": "m3", "source": "sizing note SN-1"}
    result = estimate_equipment(listed(item), {"C-1": _sheet("C-1", {"volume_m3": known})}, None)
    (line,) = result.lines
    assert line.size_source == "datasheet type_specific.volume_m3 (sizing note SN-1)"
    assert not [f for f in result.findings if f.rule == "cheme.estimate-draft-size"]
    # an assumed Quantity in design: marked as well
    sheet = _sheet("C-1", {}, design={"volume_m3": {"value": 25.0, "assumed": True}})
    (line,) = estimate_equipment(listed(item), {"C-1": sheet}, None).lines
    assert line.size_source == "datasheet design.volume_m3 (ASSUMED: no basis given)"


def test_out_of_range_unknown_and_partial_items_are_findings_not_guesses():
    big_pump = {"tag": "P-2", "type": "CentrifugalPump", "material": "CS"}
    filt = {"tag": "F-1", "type": "GasFilter"}
    alu = {
        "tag": "C-1",
        "type": "ProcessColumn",
        "design_pressure_barg": 3,
        "material": "Aluminium 5083",
        "dimensions": {"diameter": 3.0, "height": 30.0},
    }
    sheets = {"P-2": _sheet("P-2", {"shaft_power_kw": 500})}
    result = estimate_equipment(listed(big_pump, filt, alu), sheets, None)
    rules = {f.ids[0]: f.rule for f in result.findings if f.ids}
    assert rules == {
        "P-2": "cheme.estimate-equipment-range",
        "F-1": "cheme.estimate-equipment-uncovered",
        "C-1": "cheme.estimate-equipment-partial",
    }
    p, f, c = result.lines
    assert p.status == "not covered" and p.cp0_base is None  # 500 kW > 300 kW: not extrapolated
    assert c.status == "purchased only" and c.purchased and c.bare_module is None
    assert "ASSUMED upper bound" in c.size_source
    # the project closes the gaps with sourced factors, an own cost or an exclusion
    basis = CostBasis.model_validate(
        {
            "items": [
                {"tag": "C-1", "fm": 1.5, "fp": 1.0, "factor_source": "test basis"},
                {
                    "tag": "F-1",
                    "cost": 12000,
                    "currency": "EUR",
                    "year": 2026,
                    "status": "QUOTED",
                    "source": "quotation Q-1",
                },
                {"tag": "P-2", "exclude": "two pumps of 250 kW costed as P-2A/B"},
            ]
        }
    )
    result = estimate_equipment(listed(big_pump, filt, alu), sheets, basis)
    p, f, c = result.lines
    assert c.status == "bare module" and c.fbm == pytest.approx(2.25 + 1.82 * 1.5)
    assert f.status == "project cost" and p.status.startswith("excluded")
    assert not result.uncovered()


def test_choices_and_materials():
    assert choose("TubularHeatExchanger", None)[0] == "hx_fixed_tube"
    assert choose("UTubeHeatExchanger", None)[0] == "hx_u_tube"
    assert choose("ReciprocatingPump", None)[0] == "pump_reciprocating"
    assert choose("Turbine", None)[0] == "expander_radial"
    assert choose("ElectricHeater", None)[0] is None
    # a diameter with a length is a horizontal shell, also where the list gives its height
    # over the saddles (as the 3D model reads it; the ASU's adsorbers)
    from chemeascode.domains.equipment.schemas.equipment import Dimensions

    saddled = Dimensions(diameter=4.5, length=18, height=6.5, support="saddles")
    assert choose("PressureVessel", saddled)[0] == "vessel_horizontal"
    assert choose("PressureVessel", Dimensions(diameter=2, height=6))[0] == "vessel_vertical"
    assert material_of("CS") == "CS" and material_of("SS 316L") == "SS"
    assert material_of("1.4404") == "SS" and material_of("CS shell / SS tubes") is None
    assert material_of("Aluminium 3003") is None
    # another alloy beside the stainless steel: no single material factor (a LOX pump's
    # 'SS / bronze', as 'SS / Monel / copper alloys' and 'CS / SS packing' already are)
    assert material_of("SS / bronze") is None and material_of("Hastelloy C-276") is None
    assert material_of("SS / Monel / copper alloys") is None


@pytest.mark.parametrize("cls", ["StirredTankReactor", "TubularReactor", "Reactor", "Converter"])
def test_a_reactor_is_costed_as_its_vessel_whatever_else_its_class_names(cls):
    # 'tank' and 'tubular' do not make a reactor an API storage tank or an exchanger
    # (pre-release issue 195)
    corr, why = choose(cls, None)
    assert corr == "vessel_vertical" and "a reactor costed as its pressure vessel" in why


#: The datasheet fill's class word for each correlation the estimate chooses.
FILL_KIND = {"tower": "column", "tank_fixed_roof": "vessel", "tank_floating_roof": "vessel"}


@pytest.mark.parametrize(
    "cls",
    [
        "StirredTankReactor",
        "TubularReactor",
        "AgitatedReactor",
        "PressureVessel",
        "Drum",
        "StorageTank",
        "FloatingRoofTank",
        "TrayColumn",
        "PackedColumn",
        "TubularHeatExchanger",
        "ShellAndTubeHeatExchanger",
        "UTubeHeatExchanger",
        "PlateHeatExchanger",
        "AirCooledHeatExchanger",
        "KettleReboiler",
    ],
)
def test_the_estimate_and_the_datasheet_fill_classify_alike(cls):
    from chemeascode.domains.equipment.fill import _kind

    corr, why = choose(cls, None)
    if corr.startswith("vessel_"):
        kind = "reactor" if "a reactor" in why else "vessel"
    elif corr.startswith("hx_"):
        kind = "exchanger"
    else:
        kind = FILL_KIND[corr]
    assert kind == _kind(cls)


def test_command_and_gate(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    (plant / "equipment" / "equipment-list.yaml").write_text(
        yaml.safe_dump(
            {
                "equipment": [
                    {
                        "tag": "V-1",
                        "type": "PressureVessel",
                        "design_pressure_barg": 10,
                        "material": "CS",
                        "dimensions": {"diameter": 2.0, "height": 3.1830989},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    problems = mto_gate(plant, ["equipment-covered", "equipment-current"])
    assert any("no cost_index" in p for p in problems)
    assert any("no estimate/equipment-cost.csv" in p for p in problems)
    (plant / "estimate" / "cost-basis.yaml").write_text(
        "cost_index: {value: 397, year: 2001, source: test}\n", encoding="utf-8"
    )
    result = runner.invoke(app, ["assess", "equipment", "--write"])
    assert result.exit_code == 0, result.output
    assert not mto_gate(plant, ["equipment-covered", "equipment-current"])
    text = (plant / "estimate" / "equipment-cost.md").read_text(encoding="utf-8")
    assert "Estimate class 5" in text and "18R-97" in text and "-20 % to -50 %" in text
    report = equipment_estimate(plant)
    assert report.totals()["bare_module_items"] == 1


def test_a_catalyst_fill_in_another_currency_is_reported_not_dropped():
    # a fill priced in EUR/kg is not converted: it is in no USD total, and says so
    # (pre-release issue 194)
    from types import SimpleNamespace as NS

    from chemeascode.domains.assessment.equipment_cost import (
        EquipmentEstimate,
        catalyst_fills_of,
    )

    price = NS(value=20.0, unit="EUR/kg", year=2024, provenance="assumed", source="quote")
    process = NS(
        catalysts=NS(by_id=lambda: {"cu": NS(price=price)}),
        nodes={"R1": NS(catalyst="cu", links=[NS(target="equipment", ref="R-101")])},
    )
    sheet = NS(type_specific={"catalyst_mass_kg": 5000.0}, operating={}, design={}, draft=False)
    lines, findings = catalyst_fills_of(process, {"R-101": sheet}, {"value": 800, "year": 2024})
    (line,) = lines
    assert line.purchased is None and line.bare_module is None
    assert line.own_cost == pytest.approx(100000) and line.currency == "EUR"
    assert line.price_year == 2024 and line.status == "own currency EUR"
    (finding,) = findings
    assert finding.rule == "cheme.estimate-catalyst-currency" and finding.level == "warning"
    assert finding.ids == ["R-101"] and "100000 EUR" in finding.message
    totals = EquipmentEstimate(lines=lines).totals()
    assert totals["own_currency"] == 1 and totals["bare_module"] == 0
