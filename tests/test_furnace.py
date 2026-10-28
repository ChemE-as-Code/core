"""The furnace energy basis (domains/process/furnace.py, ``cheme process furnace``,
pre-release issue 370).

Reference data, all independent of the NASA polynomials the model uses:

- the published kiln balance of tests/data/furnaces-lime-kiln.yaml: kiln No. 1 of Sagastume
  Gutiérrez, Cogollos Martínez and Vandecasteele, Applied Thermal Engineering 51 (2013) 273-280,
  doi:10.1016/j.applthermaleng.2012.07.013 (Tables 1, 2 and 4);
- the formation enthalpies and entropies of the CRC Handbook as ``chemicals`` 1.5.2 holds them
  (calcite, lime) and Active Thermochemical Tables (CO2, CH4, H2O), extra ``props``;
- the lime BREF (Schorcht et al., EUR 26129 EN, 2013): heat of dissociation 3.2 GJ/t of lime
  (section 2.3.2.1, p. 222) and the typical heat use by kiln type (Table 2.23, p. 223).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from chemeascode.domains.process import furnace as fm

pytest.importorskip("cantera")

DATA = Path(__file__).parent / "data" / "furnaces-lime-kiln.yaml"
runner = CliRunner()

# Sagastume Gutiérrez et al. 2013, kiln No. 1 (kg/h, kW)
PAPER = {
    "limestone": 3277.0,  # Table 1
    "air": 3707.0,
    "fuel": 230.0,
    "quicklime": 1965.0,
    "gases": 5249.0,
    "fuel_heat": 2555.0,  # Table 2
    "quicklime_heat": 124.0,
    "gases_heat": 763.0,
    "reaction_heat": 1478.0,
    "wall_loss": 292.0,
    "total": 2603.0,
}
# Table 4, combustion products per kg of fuel
PAPER_PRODUCTS = {"CO2": 3.117, "H2O": 0.693, "SO2": 0.060}


def _kiln() -> fm.Furnace:
    return fm.FurnacesFile.model_validate(yaml.safe_load(DATA.read_text("utf-8"))).furnaces[0]


def _with(**changes) -> fm.Furnace:
    data = _kiln().model_dump(by_alias=True, exclude_none=True)
    for path, value in changes.items():
        node = data
        keys = path.split("__")
        for key in keys[:-1]:
            node = node.setdefault(key, {})
        if value is None:
            node.pop(keys[-1], None)
        else:
            node[keys[-1]] = value
    return fm.Furnace.model_validate(data)


def _rules(result: fm.FurnaceResult, level: str = "error") -> list[str]:
    return [f.rule for f in result.findings if f.level == level]


# -- thermochemistry against independent data ---------------------------------------------------


def test_reaction_enthalpy_and_gibbs_energy_agree_with_the_crc_and_atct_data():
    """NASA (calcite: Barin 1989; lime: JANAF 1973; CO2: 1988) against the CRC Handbook
    (chemicals): within 1 % of the reaction enthalpy, the spread between compilations of the
    calcite and lime formation enthalpies (CRC -1207.6 and -634.9 kJ/mol)."""
    reaction = pytest.importorskip("chemicals.reaction")
    hf = {
        "CaCO3": reaction.Hfs("471-34-1"),
        "CaO": reaction.Hfs("1305-78-8"),
        "CO2": reaction.Hfg("124-38-9"),
    }
    s0 = {
        "CaCO3": reaction.S0s("471-34-1"),
        "CaO": reaction.S0s("1305-78-8"),
        "CO2": reaction.S0g("124-38-9"),
    }
    dh_crc = (hf["CaO"] + hf["CO2"] - hf["CaCO3"]) / 1000  # kJ/mol
    dg_crc = dh_crc - 298.15 * (s0["CaO"] + s0["CO2"] - s0["CaCO3"]) / 1000
    data = fm._Data()
    dh = fm.calcination_enthalpy(data) / 1000
    g_over_rt = (
        data.g_over_rt("CaO", 298.15)
        + data.g_over_rt("CO2", 298.15)
        - data.g_over_rt("CaCO3", 298.15)
    )
    dg = g_over_rt * 8.314462618 * 298.15 / 1000
    assert dh == pytest.approx(dh_crc, rel=0.01)  # 178.3 against 179.2 kJ/mol
    assert dg == pytest.approx(dg_crc, rel=0.01)  # 130.9 against 131.5 kJ/mol
    # the endothermic reaction weakens with temperature (Kirchhoff): 167.5 kJ/mol at 1173 K
    assert 160 < fm.calcination_enthalpy(data, 1173.15) / 1000 < dh


def test_heat_of_dissociation_is_the_brefs_3_2_gj_per_tonne_of_lime():
    """BREF section 2.3.2.1: 3.2 GJ/t of lime, two significant figures."""
    per_tonne = fm.calcination_enthalpy() / fm._molar_mass({"Ca": 1, "O": 1}) / 1000  # GJ/t
    assert per_tonne == pytest.approx(3.2, abs=0.05)


def test_equilibrium_co2_pressure_and_decomposition_temperature():
    """1 atm of CO2 over calcite and lime at 1167 K (894 °C), from the same data, on their
    standard pressure of 1 bar (TM-4513, p. 2; Cantera's converted files declare 1 atm); the data
    end at 1200 K, where no decomposition temperature above is extrapolated."""
    data = fm._Data()
    assert fm.P_STANDARD == 100.0
    t = fm.decomposition_temperature(101.325, data)
    assert t == pytest.approx(1167.2, abs=0.5)
    assert fm.co2_equilibrium_pressure(t, data) == pytest.approx(101.325, rel=1e-6)
    assert fm.co2_equilibrium_pressure(1000.0, data) < 10.0
    assert fm.decomposition_temperature(500.0, data) is None  # above 1200 K: not claimed
    assert fm.decomposition_temperature(1e-12, data) == pytest.approx(418, abs=1)
    assert fm.decomposition_temperature(1e-40, data) is None  # below 300 K: not claimed


def test_methane_lower_heating_value_agrees_with_atct():
    """A gas fuel's LHV comes from the data: methane against chemicals' combustion data on the
    ATcT formation enthalpy, within 0.2 %."""
    combustion = pytest.importorskip("chemicals.combustion")
    reaction = pytest.importorskip("chemicals.reaction")
    ref = combustion.combustion_data(formula="CH4", Hf=reaction.Hfg("74-82-8"))
    lhv_ref = -combustion.LHV_from_HHV(ref.HHV, 2) / ref.MW  # kJ/kg
    fuel = fm.Fuel.model_validate({"gas": {"fractions": {"CH4": 1.0}, "source": "x"}})
    _, _, o2, lhv, _, _ = fm._fuel_basis(fuel, fm._Data())
    assert lhv == pytest.approx(lhv_ref, rel=0.002)  # 50.0 MJ/kg
    assert o2 == pytest.approx(2 / 16.043, rel=1e-4)


# -- the published kiln --------------------------------------------------------------------------


def test_reference_kiln_elements_off_gas_reaction_energy_and_closure():
    result = fm.evaluate(_kiln())
    assert _rules(result) == [] and _rules(result, "warning") == []
    assert result.basis == "calculated" and result.mode == "closure"

    # elements: every element in equals out (an implementation check)
    for element, (n_in, n_out) in result.elements.items():
        assert n_in == pytest.approx(n_out, rel=1e-9), element
    assert set(result.elements) == {"Ar", "C", "Ca", "H", "N", "O", "S"}

    # mass: product and off-gas against Table 1 (conservation: limestone + air + fuel - lime)
    assert result.product_total_kg_h == pytest.approx(PAPER["quicklime"], abs=0.5)
    assert sum(result.off_gas_kg_h.values()) == pytest.approx(PAPER["gases"], abs=1.0)

    # off-gas against Table 4 x 230 kg/h plus the calcination CO2 (1312 kg/h): within 1 %,
    # the difference between the paper's 0.693 kg H2O/kg and the 0.688 its own ultimate
    # analysis gives. O2 and N2 are not compared: the paper splits its air with N2/O2 = 3.76
    # by mass (Table 4), the molar ratio, where dry air holds 3.29.
    calcination = PAPER["limestone"] - PAPER["quicklime"]
    assert result.co2_kg_h["calcination"] == pytest.approx(calcination, rel=1e-6)
    for gas, per_kg in PAPER_PRODUCTS.items():
        expected = per_kg * PAPER["fuel"] + (calcination if gas == "CO2" else 0.0)
        assert result.off_gas_kg_h[gas] == pytest.approx(expected, rel=0.01), gas
    assert result.air_excess == pytest.approx(1.30, abs=0.01)  # the paper states 1.15

    terms = {t.name: t.kW for t in result.terms}
    # reaction energy: Table 2 (1784 kJ/kg CaCO3), within 1 %, the compilation spread above
    assert terms["reaction enthalpy of calcination (298.15 K)"] == pytest.approx(
        PAPER["reaction_heat"], rel=0.01
    )
    # sensible heats: the paper's rows are on 273.15 K (its limestone and air at 298 K carry
    # 21 and 27 kW) with constant heat capacities (CaO 46, CaCO3 92 kJ/(kmol K), Table 5; the
    # gas about 1.15 kJ/(kg K)); shifted to 298.15 K by those, within 10 %: the gas's mean heat
    # capacity from the NASA data is 1.06 kJ/(kg K), 8 % below the paper's constant
    lime_298 = PAPER["quicklime_heat"] * (550 - 298.15) / (550 - 273.15)
    gas_298 = PAPER["gases_heat"] * (728 - 298.15) / (728 - 273.15)
    assert terms["sensible heat of the product solids"] == pytest.approx(lime_298, rel=0.10)
    assert terms["sensible heat of the off-gas"] == pytest.approx(gas_298, rel=0.10)

    # closure: the measured fuel heat against the outputs and the paper's wall loss, within the
    # paper's own imbalance (output rows 2657 kW against inputs 2603 kW: 54 kW)
    assert result.tolerance_kW == 54.0
    assert abs(result.residual_kW) <= 54.0
    assert abs(result.residual_kW) < 0.005 * PAPER["fuel_heat"]  # 3 kW today
    assert result.closed

    # specific heat use: 4.68 GJ/t, inside the BREF's 3.5-7.0 for "other kilns"
    assert result.specific_energy_GJ_t == pytest.approx(4.68, abs=0.01)
    assert result.bref_range_GJ_t == (3.5, 7.0)
    assert "cheme.furnace-specific-energy" in _rules(result, "info")

    # 900 °C: calcination proceeds against the off-gas's 28.8 kPa CO2
    eq = result.equilibrium
    assert eq["co2_equilibrium_pressure_kPa"] > eq["off_gas_co2_partial_pressure_kPa"]
    assert eq["off_gas_co2_partial_pressure_kPa"] == pytest.approx(28.8, abs=0.1)

    # provenance: data, versions, phases and ranges are recorded
    by_component = {d.component: d for d in result.data}
    assert by_component["CaCO3"].nasa == ["CaCO3(caL)"]
    assert by_component["CaCO3"].temperature_range == (298.15, 1200.0)
    assert by_component["CaO"].notes == ["J 6/73"]
    assert "NASA TM-4513" in result.provenance["thermochemistry"]
    assert "Cantera" in result.provenance["thermochemistry"]
    assert result.contract == fm.CONTRACT


def test_reference_kiln_solved_fuel_flow_matches_the_measured_one():
    """Without the fuel flow the balance is solved for it: 229.7 kg/h against 230 measured."""
    result = fm.evaluate(_with(fuel__mass_flow=None))
    assert result.mode == "solved"
    assert result.fuel_kg_h == pytest.approx(PAPER["fuel"], rel=0.01)
    assert result.residual_kW == pytest.approx(0.0, abs=1e-6)


def test_a_phase_change_on_the_way_is_in_the_sensible_heat():
    """Quartz in the feed: alpha below 847 K, beta above; the lime at 1000 K passes the
    transition, the data of both phases are recorded."""
    result = fm.evaluate(
        _with(
            feed__composition__fractions={"CaCO3": 0.95, "SiO2": 0.05},
            product_temperature={"value": 1000, "unit": "K"},
            conversion={"value": 1, "unit": "1", "source": "x"},
        )
    )
    assert _rules(result) == []
    quartz = next(d for d in result.data if d.component == "SiO2")
    assert quartz.nasa == ["SiO2(Lqz)", "SiO2(hqz)"]
    assert quartz.phases == ["alpha quartz", "beta quartz"]


# -- methods, modes, fallback --------------------------------------------------------------------


def test_methane_fired_kiln_solved_with_excess_air_closes_and_balances():
    result = fm.evaluate(
        _with(
            fuel={
                "gas": {"fractions": {"CH4": 0.95, "C2H6": 0.03, "N2": 0.02}, "source": "x"},
            },
            air={"excess": {"value": 1.2, "unit": "1", "source": "x"}},
            off_gas_temperature={"value": 150, "unit": "°C"},
            product_temperature={"value": 80, "unit": "°C"},
            losses={"fraction": {"value": 5, "unit": "%", "source": "x"}},
            kiln_type="parallel-flow-regenerative",
        )
    )
    assert _rules(result) == []
    assert result.mode == "solved" and result.residual_kW == pytest.approx(0, abs=1e-6)
    assert result.air_excess == pytest.approx(1.2, rel=1e-9)
    for n_in, n_out in result.elements.values():
        assert n_in == pytest.approx(n_out, rel=1e-9)
    # losses are 5 % of the heat input
    terms = {t.name: t.kW for t in result.terms}
    assert terms["losses"] == pytest.approx(0.05 * result.heat_input_kW)
    assert result.fuel_lhv_kJ_kg == pytest.approx(47_000, rel=0.05)
    assert result.off_gas_dry_mole_fractions["CO2"] > result.off_gas_mole_fractions["CO2"]


def test_electric_calciner_solved_and_closed():
    solved = fm.evaluate(_with(fuel=None, air=None, electric={}))
    assert solved.mode == "solved" and _rules(solved) == []
    assert set(solved.off_gas_kmol_h) == {"CO2"}  # pure calcination CO2
    power = solved.heat_input_kW
    closed = fm.evaluate(
        _with(
            fuel=None, air=None, electric={"power": {"value": power, "unit": "kW", "source": "x"}}
        )
    )
    assert closed.mode == "closure" and closed.residual_kW == pytest.approx(0, abs=1e-6)
    off = fm.evaluate(
        _with(
            fuel=None,
            air=None,
            electric={"power": {"value": 1.2 * power, "unit": "kW", "source": "x"}},
        )
    )
    assert "cheme.furnace-closure" in _rules(off, "warning")
    swept = fm.evaluate(
        _with(fuel=None, electric={}, air={"mass_flow": {"value": 500, "unit": "kg/h"}})
    )
    assert _rules(swept) == [] and swept.heat_input_kW > power  # the sweep air leaves hot
    assert {"CO2", "N2", "O2", "Ar"} <= set(swept.off_gas_kmol_h)
    for n_in, n_out in swept.elements.values():
        assert n_in == pytest.approx(n_out, rel=1e-9)


def test_specific_energy_fallback_is_labelled_conceptual():
    by_type = fm.evaluate(_with(method="specific-energy", kiln_type="parallel-flow-regenerative"))
    assert by_type.basis.startswith("conceptual fallback") and by_type.mode == "fallback"
    tonnes = PAPER["quicklime"] / 1000
    low, high = by_type.heat_input_range_kW
    assert low == pytest.approx(3.2 * tonnes * 1e6 / 3600)
    assert high == pytest.approx(4.2 * tonnes * 1e6 / 3600)
    assert by_type.heat_input_kW is None and by_type.terms == []
    # no combustion gas: no off-gas composition or CO2 partial pressure is claimed
    assert by_type.off_gas_mole_fractions == {} and by_type.co2_partial_pressure_kPa is None
    assert by_type.co2_kg_h["calcination"] == pytest.approx(1312, rel=1e-6)
    assert "cheme.furnace-specific-energy" in _rules(by_type, "info")
    assert fm.BREF_SOURCE in by_type.provenance["specific energy"]
    given = fm.evaluate(
        _with(method="specific-energy", specific_energy={"value": 4.0, "unit": "GJ/t"})
    )
    assert given.heat_input_kW == pytest.approx(4.0 * tonnes * 1e6 / 3600)
    assert "cheme.furnace-provenance" in _rules(given, "warning")  # no source
    neither = fm.evaluate(_with(method="specific-energy", kiln_type=None))
    assert _rules(neither) == ["cheme.furnace-input"]


# -- refusals ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("changes", "rule", "words"),
    [
        ({"reaction": "carbothermal-sic"}, "furnace-unsupported", "carbothermal"),
        (
            {"feed__composition__fractions": {"CaCO3": 0.6, "MgCO3": 0.4}},
            "furnace-unsupported",
            "MgCO3",
        ),
        ({"product_temperature": {"value": 1300, "unit": "K"}}, "furnace-data-range", "1200"),
        (
            {
                "conversion": {"value": 1, "unit": "1", "source": "x"},
                "product_temperature": {"value": 3300, "unit": "K"},
            },
            "furnace-data-range",
            "melts",
        ),
        ({"feed__temperature": {"value": 10, "unit": "°C"}}, "furnace-data-range", "298.15"),
        ({"losses": None}, "furnace-input", "losses"),
        ({"electric": {}}, "furnace-input", "one heat source"),
        (
            {"fuel": None, "electric": {}, "air": {"excess": {"value": 1.2, "unit": "1"}}},
            "furnace-input",
            "needs a fuel",
        ),
        ({"fuel__lhv": None}, "furnace-input", "lower heating value"),
        ({"feed__composition__fractions": {"CaCO3": 0.9}}, "furnace-input", "sum to"),
        ({"feed__mass_flow": {"value": 3.277, "unit": "Mg/h"}}, "furnace-input", "unit"),
        ({"air": {"mass_flow": {"value": 1000, "unit": "kg/h"}}}, "furnace-infeasible", "oxygen"),
        (
            {"air": {"excess": {"value": 0.9, "unit": "1"}}, "fuel__mass_flow": None},
            "furnace-infeasible",
            "below 1",
        ),
        (
            {
                "air": {"excess": {"value": 6, "unit": "1"}},
                "fuel__mass_flow": None,
                "off_gas_temperature": {"value": 2400, "unit": "K"},
            },
            "furnace-infeasible",
            "carries away more",
        ),
        (
            {"calcining_temperature": {"value": 1000, "unit": "K"}},
            "furnace-infeasible",
            "cannot proceed",
        ),
    ],
)
def test_refusals(changes, rule, words):
    result = fm.evaluate(_with(**changes))
    errors = [f for f in result.findings if f.level == "error"]
    assert [f.rule for f in errors] == [f"cheme.{rule}"], [f.format() for f in result.findings]
    assert words in errors[0].message
    assert errors[0].hint
    if rule != "furnace-infeasible" or "cannot proceed" not in words:
        assert result.heat_input_kW is None and result.terms == []  # no numbers on a refusal


def test_measured_fuel_flow_that_does_not_close_is_a_warning():
    result = fm.evaluate(_with(fuel__mass_flow={"value": 250, "unit": "kg/h", "source": "x"}))
    assert _rules(result, "warning") == ["cheme.furnace-closure"]
    assert result.residual_kW > 54 and result.closed is False


def test_given_inputs_without_source_are_flagged():
    result = fm.evaluate(
        _with(
            conversion={"value": 0.91, "unit": "1"}, losses={"heat": {"value": 292, "unit": "kW"}}
        )
    )
    messages = [f.message for f in result.findings if f.rule == "cheme.furnace-provenance"]
    assert any("degree of calcination" in m for m in messages)
    assert any("losses" in m for m in messages)


def test_without_cantera_the_energy_basis_names_the_extra(monkeypatch):
    monkeypatch.setitem(sys.modules, "cantera", None)
    result = fm.evaluate(_kiln())
    assert _rules(result) == ["cheme.furnace-extra"]
    assert "cheme-as-code[cantera]" in result.findings[0].hint
    # the fallback needs no thermochemical data
    fallback = fm.evaluate(_with(method="specific-energy"))
    assert _rules(fallback) == [] and fallback.heat_input_range_kW is not None


def test_no_fluid_flash_is_used():
    """The furnace duty never comes from a fluid-only flash: evaluating the reference kiln
    loads neither thermo nor the phase or props modules."""
    code = (
        "import sys, yaml\n"
        "from chemeascode.domains.process import furnace as fm\n"
        f"data = yaml.safe_load(open({str(DATA)!r}, encoding='utf-8'))\n"
        "r = fm.evaluate(fm.FurnacesFile.model_validate(data).furnaces[0])\n"
        "assert r.heat_input_kW, r.findings\n"
        "bad = ['thermo', 'chemeascode.domains.process.props',\n"
        "       'chemeascode.domains.process.thermodynamics.phase']\n"
        "print(sorted(m for m in bad if m in sys.modules))\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"


# -- the plant's file and the CLI ---------------------------------------------------------------


def test_schema_errors_name_the_line(tmp_path):
    (tmp_path / "process").mkdir()
    text = DATA.read_text("utf-8").replace("reaction: calcination-caco3", "reacton: x")
    (tmp_path / "process" / "furnaces.yaml").write_text(text, encoding="utf-8")
    report = fm.furnace_report(tmp_path)
    assert report.results == []
    rules = {f.rule for f in report.findings}
    assert rules == {"cheme.furnace-schema"}
    assert all(f.line for f in report.findings)
    other = DATA.read_text("utf-8").replace("cheme/furnaces/v1", "cheme/furnaces/v9")
    (tmp_path / "process" / "furnaces.yaml").write_text(other, encoding="utf-8")
    assert "not supported" in fm.furnace_report(tmp_path).findings[0].message


def test_finding_lines_point_into_the_file(tmp_path):
    (tmp_path / "process").mkdir()
    text = (
        DATA.read_text("utf-8")
        .replace("value: 1300", "value: 1300")
        .replace("product_temperature: {value: 550", "product_temperature: {value: 1300")
    )
    (tmp_path / "process" / "furnaces.yaml").write_text(text, encoding="utf-8")
    report = fm.furnace_report(tmp_path)
    finding = next(f for f in report.findings if f.rule == "cheme.furnace-data-range")
    line = text.splitlines()[finding.line - 1]
    assert line.lstrip().startswith("product_temperature")
    assert finding.id == "process/furnaces.yaml#furnace-data-range:K-1:product_temperature"
    with pytest.raises(KeyError):
        fm.furnace_report(tmp_path, "K-9")


def test_cli_text_json_and_exit_codes(plant, monkeypatch):
    from chemeascode.interfaces.cli import app

    monkeypatch.chdir(plant)
    missing = runner.invoke(app, ["process", "furnace"])
    assert missing.exit_code == 1 and "does not exist" in missing.output
    shutil.copy(DATA, plant / "process" / "furnaces.yaml")
    shown = runner.invoke(app, ["process", "furnace"])
    assert shown.exit_code == 0, shown.output
    assert "furnace K-1: CaCO3(calcite) -> CaO(s) + CO2(g)" in shown.output
    assert "reaction enthalpy of calcination" in shown.output
    as_json = runner.invoke(app, ["process", "furnace", "K-1", "--json"])
    payload = json.loads(as_json.output)
    entry = payload["results"][0]
    function = fm.furnace_report(plant).results[0]
    assert entry["residual_kW"] == pytest.approx(function.residual_kW)
    assert entry["closed"] is True and payload["contract"] == fm.CONTRACT
    assert payload["source"]["fingerprints"]["process/furnaces.yaml"].startswith("sha256:")
    unknown = runner.invoke(app, ["process", "furnace", "K-9"])
    assert unknown.exit_code == 2
    schema = runner.invoke(app, ["schema", "furnaces"])
    assert schema.exit_code == 0 and "calcination-caco3" in schema.output


# -- cheme maturity ------------------------------------------------------------------------------


def _furnace_requirement(root: Path):
    from chemeascode.project.maturity import maturity_report

    report = maturity_report(root)
    found = [r for r in report.requirements if r.id == "balanced.furnace-energy"]
    return (found[0] if found else None), report


def test_maturity_reports_the_furnace_energy_basis_without_requiring_it(plant):
    assert _furnace_requirement(plant)[0] is None  # no process/furnaces.yaml: not listed
    shutil.copy(DATA, plant / "process" / "furnaces.yaml")
    req, report = _furnace_requirement(plant)
    assert req.status == "pass" and not req.required
    assert req.evidence["furnaces"][0]["closed"] is True
    assert any(
        "not claimed: conversion" in item["limitation"]
        for item in report.limitations
        if item["subject"] == "balanced.furnace-energy"
    )
    assert "process/furnaces.yaml" in report.source["fingerprints"]


@pytest.mark.parametrize(
    ("old", "new", "status"),
    [
        ("mass_flow: {value: 230,", "mass_flow: {value: 250,", "fail"),  # does not close
        ("reaction: calcination-caco3", "reaction: carbothermal-sic", "unsupported"),
        (
            "reaction: calcination-caco3",
            "reaction: calcination-caco3\n    method: specific-energy",
            "missing",
        ),
    ],
)
def test_maturity_furnace_requirement_statuses(plant, old, new, status):
    text = DATA.read_text("utf-8").replace(old, new)
    (plant / "process" / "furnaces.yaml").write_text(text, encoding="utf-8")
    req, _ = _furnace_requirement(plant)
    assert req.status == status, req.detail
    assert req.hint
