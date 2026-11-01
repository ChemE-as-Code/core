"""process/adsorption.yaml: the equilibrium TSA cycle, external performance records, the
refusals, and the model basis an adsorber gets from them."""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from chemeascode.domains.process.model import load as load_process
from chemeascode.domains.process.model_basis import model_bases
from chemeascode.domains.process.separations.adsorption import (
    UnknownCase,
    adsorption_report,
    single_loading,
)
from chemeascode.domains.process.separations.schema import Isotherm
from chemeascode.interfaces.cli import app

R = 8.314462618  # J/(mol K)

PLANT = {
    "plant.yaml": "name: tsa\nstage: concept\nsheets: []\n",
    "process/materials.yaml": """\
schema: cheme/process/v1
kind: materials
components:
  - {id: N2, name: Nitrogen, cas: 7727-37-9, molar_mass: 28.014}
  - {id: O2, name: Oxygen, cas: 7782-44-7, molar_mass: 31.998}
  - {id: AR, name: Argon, cas: 7440-37-1, molar_mass: 39.948}
  - {id: CO2, name: Carbon dioxide, cas: 124-38-9, molar_mass: 44.009}
templates:
  - {id: air, components: [N2, O2, AR, CO2]}
""",
    "process/flowsheet.yaml": """\
schema: cheme/process/v1
kind: flowsheet
units: {pressure: kPa(a), temperature: K, flow: kmol/h, duty: kW, enthalpy: kJ/kmol}
feeds:
  - {id: AIR, ports: [{id: out, direction: out}]}
products:
  - id: P
    ports: [{id: dry, direction: in}, {id: waste, direction: in}]
blocks:
  - id: A1
    class: Adsorbing
    ports: [{id: in, direction: in}, {id: dry, direction: out}, {id: waste, direction: out}]
streams:
  - id: S1
    from: AIR.out
    to: A1.in
    template: air
    state:
      design:
        pressure: {value: 790, provenance: given, source: fixture}
        temperature: {value: 298.15, provenance: given, source: fixture}
        flow: {value: 100, provenance: given, source: fixture}
        composition:
          basis: mole_fraction
          values: {N2: 0.7807, O2: 0.2095, AR: 0.0094, CO2: 0.0004}
          provenance: given
          source: fixture
  - {id: S2, from: A1.dry, to: P.dry, template: air}
  - {id: S3, from: A1.waste, to: P.waste, template: air}
""",
    "process/simulation.yaml": """\
schema: cheme/simulation/v1
kind: simulation
specs:
  A1:
    recoveries: {CO2: 1.0, N2: 0.00206, O2: 0.000407, AR: 0.000407}
    recovery_outlet: waste
    basis_source: process/adsorption.yaml (cheme process adsorption)
    operating_basis: TSA at the design feed
""",
}

#: Test fixture parameters (round numbers, not data): every number below is checked by the
#: hand calculation in test_tsa_matches_the_hand_calculation.
ADSORPTION = {
    "schema": "cheme/adsorption/v1",
    "kind": "adsorption",
    "units": [
        {
            "id": "A1",
            "technique": "tsa",
            "performance": "calculated",
            "product_outlet": "dry",
            "specification": {"CO2": {"value": 0.1, "unit": "ppm", "source": "fixture spec"}},
            "layers": [
                {
                    "adsorbent": "fixture 13X",
                    "length": {"value": 1.0, "unit": "m", "source": "fixture"},
                    "bulk_density": {"value": 650, "unit": "kg/m3", "source": "fixture"},
                    "heat_capacity": {"value": 0.92, "unit": "kJ/(kg K)", "source": "fixture"},
                    "void_fraction": {"value": 0.65, "unit": "-", "source": "fixture"},
                    "removes": ["CO2"],
                    "mass_transfer_zone": {"value": 200, "unit": "mm", "source": "fixture"},
                    "life": {"value": 5, "unit": "a", "source": "fixture"},
                    "isotherms": [
                        {
                            "component": "CO2",
                            "model": "langmuir",
                            "parameters": {"q_s": 3.0, "b0": 5.0e-7, "E": 36.0},
                            "heat_of_adsorption": {
                                "value": 36,
                                "unit": "kJ/mol",
                                "source": "fixture",
                            },
                            "valid": {"temperature": [273, 523], "partial_pressure": [0.01, 100]},
                            "source": "fixture isotherm",
                        },
                        {
                            "component": "N2",
                            "model": "langmuir",
                            "parameters": {"q_s": 4.0, "b0": 1.0e-6, "E": 18.0},
                            "heat_of_adsorption": {
                                "value": 18,
                                "unit": "kJ/mol",
                                "source": "fixture",
                            },
                            "valid": {"temperature": [273, 523], "partial_pressure": [1, 1000]},
                            "source": "fixture isotherm",
                        },
                    ],
                }
            ],
            "cycle": {
                "beds": 2,
                "diameter": {"value": 0.5, "unit": "m", "source": "fixture"},
                "adsorption_time": {"value": 1.0, "unit": "h", "source": "fixture"},
                "heating_time": {"value": 24, "unit": "min", "source": "fixture"},
                "cooling_time": {"value": 24, "unit": "min", "source": "fixture"},
                "switch_time": {"value": 6, "unit": "min", "source": "fixture"},
                "regeneration_temperature": {"value": 200, "unit": "°C", "source": "fixture"},
                "regeneration_pressure": {"value": 110, "unit": "kPa(a)", "source": "fixture"},
                "purge": {
                    "flow": {"value": 15, "unit": "kmol/h", "source": "fixture"},
                    "composition": {"N2": 1.0},
                    "supply_temperature": {"value": 298.15, "unit": "K", "source": "fixture"},
                    "heat_capacity": {"value": 29.1, "unit": "kJ/(kmol K)", "source": "fixture"},
                },
            },
        }
    ],
}


def _write(root: Path, files: dict[str, str], adsorption: dict | None) -> None:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    if adsorption is not None:
        (root / "process/adsorption.yaml").write_text(
            yaml.safe_dump(adsorption, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )


@pytest.fixture
def plant(tmp_path):
    root = tmp_path / "tsa"
    _write(root, PLANT, json.loads(json.dumps(ADSORPTION)))
    return root


def _edit(root: Path, change) -> None:
    path = root / "process/adsorption.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    change(data["units"][0])
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _rules(report) -> list[str]:
    return [f.rule for f in report.findings]


def test_tsa_matches_the_hand_calculation(plant):
    """The positive reference: every result against the equilibrium relations written out."""
    report = adsorption_report(plant)
    assert _rules(report) == []
    unit = report.units[0]
    assert unit.status == "qualified" and unit.consistent
    row = unit.cases[0]

    # feed state and the extended Langmuir loadings
    t, p_ads, flow = 298.15, 790.0, 100.0
    y = {"N2": 0.7807, "O2": 0.2095, "AR": 0.0094, "CO2": 0.0004}
    b_co2 = 5.0e-7 * math.exp(36000 / (R * t))
    b_n2 = 1.0e-6 * math.exp(18000 / (R * t))
    bp_co2, bp_n2 = b_co2 * y["CO2"] * p_ads, b_n2 * y["N2"] * p_ads
    q_co2 = 3.0 * bp_co2 / (1 + bp_co2 + bp_n2)
    q_n2 = 4.0 * bp_n2 / (1 + bp_co2 + bp_n2)
    layer = row.layers[0]
    assert layer["keys"]["CO2"]["loading_feed_mol_kg"] == pytest.approx(q_co2, rel=1e-9)

    # stoichiometric and breakthrough times (length of unused bed = MTZ/2 = 0.1 m)
    volume = math.pi / 4 * 0.5**2 * 1.0
    mass = 650 * volume
    void_gas = 0.65 * volume / (R * t)  # kmol per kPa of partial pressure
    capacity = mass * q_co2 / 1000 + void_gas * y["CO2"] * p_ads
    t_st = capacity / (flow * y["CO2"])
    assert layer["mass_kg"] == pytest.approx(mass, rel=1e-12)
    assert layer["keys"]["CO2"]["stoichiometric_time_h"] == pytest.approx(t_st, rel=1e-9)
    assert layer["keys"]["CO2"]["breakthrough_time_h"] == pytest.approx(t_st * 0.9, rel=1e-9)

    # recoveries: the void gas and co-adsorbed N2 the bed takes up from the regenerated state
    # (pure N2 purge at 110 kPa, cooled to the feed temperature) to the loaded state
    bp_n2_cold = b_n2 * 110.0
    q_n2_cold = 4.0 * bp_n2_cold / (1 + bp_n2_cold)
    lost_n2 = mass * (q_n2 - q_n2_cold) / 1000 + void_gas * (y["N2"] * p_ads - 110.0)
    lost_o2 = void_gas * y["O2"] * p_ads
    assert row.recoveries["N2"] == pytest.approx(1 - lost_n2 / (flow * y["N2"]), rel=1e-9)
    assert row.recoveries["O2"] == pytest.approx(1 - lost_o2 / (flow * y["O2"]), rel=1e-9)
    assert row.recoveries["AR"] == pytest.approx(row.recoveries["O2"], rel=1e-9)
    assert row.recoveries["CO2"] == 0.0
    assert row.specification["CO2"] == {"limit": pytest.approx(1e-7), "predicted": 0.0, "met": True}
    # the waste is the balance remainder: the closure is bookkeeping, not independent evidence
    assert row.closure["relative_residual"] < 1e-12 and "by construction" in row.closure["basis"]

    # regeneration: sensible heat plus the heat of desorption, carried by the hot purge
    t_reg = 473.15
    b_n2_hot = 1.0e-6 * math.exp(18000 / (R * t_reg))
    q_n2_hot = 4.0 * b_n2_hot * 110 / (1 + b_n2_hot * 110)
    sensible = mass * 0.92 * (t_reg - t)
    desorption = (flow * y["CO2"] * 1.0) * 1000 * 36 + mass * (q_n2 - q_n2_hot) * 18
    reg = row.regeneration
    assert reg["sensible_heat_kJ"] == pytest.approx(sensible, rel=1e-9)
    assert reg["bed_heat_kJ"] == pytest.approx(sensible + desorption, rel=1e-9)
    assert reg["min_purge_thermal_kmol"] == pytest.approx(
        (sensible + desorption) / (29.1 * (t_reg - t)), rel=1e-9
    )
    assert reg["hot_purge_kmol"] == pytest.approx(15 * 0.4)
    assert reg["heater_duty_kW"] == pytest.approx(15 / 3600 * 29.1 * (t_reg - t), rel=1e-12)
    # the desorbed CO2 leaves at the pressure in equilibrium with the feed loading at T_reg
    b_hot = 5.0e-7 * math.exp(36000 / (R * t_reg))
    p_star = q_co2 / (b_hot * (3.0 - q_co2))
    assert layer["keys"]["CO2"]["desorption_partial_pressure_kPa"] == pytest.approx(p_star, 1e-6)
    assert reg["min_purge_desorption_kmol"] == pytest.approx(0.04 / (p_star / 110), rel=1e-6)

    # adsorbent replacement: inventory of both beds over its life
    replacement = unit.replacement["layers"][0]
    assert replacement["inventory_kg"] == pytest.approx(2 * mass)
    assert replacement["replacement_kg_per_a"] == pytest.approx(2 * mass / 5)
    assert unit.split["status"] == "consistent" and unit.fingerprint


def test_the_basis_is_calculated_not_simulated(plant):
    process, _ = load_process(plant)
    from chemeascode.domains.process.simulation.translate import load as load_sim

    sim, _, _ = load_sim(plant)
    units = adsorption_report(plant).by_id()
    basis = model_bases(process, sim, adsorption=units)[0]
    assert (basis.basis, basis.predictive, basis.simulated, basis.sourced) == (
        "adsorption-equilibrium",
        True,
        False,
        True,
    )
    assert basis.file == "process/adsorption.yaml" and "fixture isotherm" in basis.sources
    # without the record, the same separator is a specified split
    assert model_bases(process, sim)[0].basis == "component-split"


def test_maturity_keeps_a_calculated_split_out_of_the_simulation(plant):
    from chemeascode.project.maturity import maturity_report

    report = maturity_report(plant, through="predictive")
    units = {u["id"]: u for u in report.model_basis}
    assert units["A1"]["basis"] == "adsorption-equilibrium"
    req = next(r for r in report.requirements if r.id == "predictive.model-basis")
    assert req.status == "fail" and "not in the simulation: A1 (adsorption-equilibrium)" in (
        req.detail
    )
    assert "process/adsorption.yaml" in report.source["fingerprints"]


def test_a_simulated_split_that_does_not_follow_stays_specified(plant):
    _edit(plant, lambda u: u.update(split_tolerance=1e-7))
    report = adsorption_report(plant)
    assert _rules(report) == ["cheme.adsorption-split"]
    unit = report.units[0]
    assert unit.status == "qualified" and not unit.consistent
    process, _ = load_process(plant)
    from chemeascode.domains.process.simulation.translate import load as load_sim

    basis = model_bases(process, load_sim(plant)[0], adsorption=report.by_id())[0]
    assert basis.basis == "component-split"
    assert any("simulated split differs" in x for x in basis.limitations)


def test_an_isotherm_is_not_extrapolated(plant):
    def narrow(u):
        u["layers"][0]["isotherms"][0]["valid"]["partial_pressure"] = [1, 100]

    _edit(plant, narrow)
    report = adsorption_report(plant)
    finding = next(f for f in report.findings if f.rule == "cheme.adsorption-isotherm-range")
    assert finding.level == "error" and "p = 0.316 kPa outside 1-100 kPa" in finding.message
    assert finding.line is not None and finding.hint
    assert report.units[0].status == "refused" and report.units[0].cases == []

    def cold(u):
        u["layers"][0]["isotherms"][1]["valid"]["temperature"] = [273, 400]

    _write(plant, {}, json.loads(json.dumps(ADSORPTION)))
    _edit(plant, cold)
    report = adsorption_report(plant)
    assert "at the regeneration temperature" in report.findings[0].message


def test_breakthrough_before_the_end_of_the_step_fails_the_specification(plant):
    _edit(plant, lambda u: u["cycle"]["adsorption_time"].update(value=1.4))
    report = adsorption_report(plant)
    unit = report.units[0]
    assert unit.status == "fail" and "cheme.adsorption-spec" in _rules(report)
    assert unit.cases[0].specification["CO2"]["met"] is False


def test_too_little_purge_fails_the_regeneration(plant):
    _edit(plant, lambda u: u["cycle"]["purge"]["flow"].update(value=10))
    report = adsorption_report(plant)
    assert report.units[0].status == "fail"
    message = next(f.message for f in report.findings if f.rule == "cheme.adsorption-regeneration")
    assert "carries less heat than the bed needs" in message


def test_regeneration_has_to_fit_in_the_adsorption_step(plant):
    _edit(plant, lambda u: u["cycle"]["cooling_time"].update(value=40))
    message = adsorption_report(plant).findings[0].message
    assert "more than the 1 h the other bed(s) adsorb" in message


def test_a_calculated_psa_is_unsupported(plant):
    _edit(plant, lambda u: u.update(technique="psa"))
    report = adsorption_report(plant)
    assert report.units[0].status == "unsupported"
    finding = report.findings[0]
    assert finding.rule == "cheme.adsorption-unsupported" and "no PSA cycle model" in (
        finding.message
    )


def test_refusals_name_the_input(plant):
    _edit(plant, lambda u: u["layers"][0]["isotherms"].pop(0))
    assert "removes CO2 but has no isotherm" in adsorption_report(plant).findings[0].message
    _write(plant, {}, json.loads(json.dumps(ADSORPTION)))
    _edit(plant, lambda u: u["layers"][0]["bulk_density"].update(unit="g/cm3"))
    finding = adsorption_report(plant).findings[0]
    assert finding.rule == "cheme.adsorption-input" and "give layers.0.bulk_density in kg/m3" in (
        finding.hint
    )
    _write(plant, {}, json.loads(json.dumps(ADSORPTION)))
    _edit(plant, lambda u: u.update(id="A9"))
    assert adsorption_report(plant).findings[0].rule == "cheme.adsorption-unknown-node"
    _write(plant, {}, json.loads(json.dumps(ADSORPTION)))
    _edit(plant, lambda u: u["layers"][0]["isotherms"][0]["parameters"].pop("E"))
    assert "parameters E missing or unknown" in adsorption_report(plant).findings[0].message


def test_a_feed_without_flow_is_refused(plant):
    path = plant / "process/flowsheet.yaml"
    text = path.read_text(encoding="utf-8").replace("flow: {value: 100,", "flow: {value: 0,")
    path.write_text(text, encoding="utf-8")
    report = adsorption_report(plant)
    assert report.units[0].status == "refused"
    assert _rules(report) == ["cheme.adsorption-feed"] and "S1 flow (zero)" in (
        report.findings[0].message
    )


def test_assumed_inputs_are_reported_and_keep_the_split_specified(plant):
    _edit(plant, lambda u: u["layers"][0]["void_fraction"].update(provenance="assumed"))
    report = adsorption_report(plant)
    assert _rules(report) == ["cheme.adsorption-unsourced"]
    process, _ = load_process(plant)
    basis = model_bases(process, None, adsorption=report.by_id())[0]
    assert basis.basis != "adsorption-equilibrium"
    assert any("inputs without a source" in x for x in basis.limitations)


def _external(u):
    u.clear()
    u.update(
        id="A1",
        technique="psa",
        performance="external",
        product_outlet="dry",
        specification={"CO2": {"value": 1, "unit": "ppm", "source": "fixture"}},
        external={
            "model": "fixture PSA model",
            "version": "1.0",
            "source": "fixture report",
            "recoveries": {"CO2": 0.0, "N2": 0.9, "O2": 0.9, "AR": 0.9},
            "utilities": [{"name": "electric power", "value": 5, "unit": "kW"}],
            "operating_range": {
                "temperature": [283, 313],
                "pressure": [500, 1000],
                "mole_fractions": {"CO2": [0.0002, 0.0006]},
            },
        },
    )


def test_an_external_model_is_checked_not_trusted(plant):
    _edit(plant, _external)
    report = adsorption_report(plant)
    unit = report.units[0]
    assert unit.status == "qualified" and unit.model == "fixture PSA model 1.0"
    assert unit.cases[0].recoveries["N2"] == 0.9
    assert unit.cases[0].product["flow_kmol_h"] == pytest.approx(0.9 * 99.96)
    assert unit.cases[0].utilities[0]["name"] == "electric power"
    # the simulation sends 0.2 % of N2 to waste, the external model 10 %
    assert unit.split["status"] == "differs" and _rules(report) == ["cheme.adsorption-split"]

    def hot(u):
        u["external"]["operating_range"]["temperature"] = [283, 290]

    _edit(plant, hot)
    finding = adsorption_report(plant).findings[0]
    assert finding.rule == "cheme.adsorption-external-range"
    assert "feed T = 298.1 K outside 283-290 K" in finding.message

    def unclosed(u):
        u["external"]["operating_range"]["temperature"] = [283, 313]
        u["external"]["recoveries"].pop("AR")

    _edit(plant, unclosed)
    assert adsorption_report(plant).findings[0].rule == "cheme.adsorption-external-closure"


def test_an_external_basis_is_specified(plant):
    def matching(u):
        _external(u)
        u["external"]["recoveries"] = {"CO2": 0.0, "N2": 0.99794, "O2": 0.99959, "AR": 0.99959}

    _edit(plant, matching)
    report = adsorption_report(plant)
    assert report.units[0].consistent
    process, _ = load_process(plant)
    from chemeascode.domains.process.simulation.translate import load as load_sim

    basis = model_bases(process, load_sim(plant)[0], adsorption=report.by_id())[0]
    assert (basis.basis, basis.predictive, basis.sourced) == ("external-performance", False, True)


def test_isotherm_models_against_their_closed_forms():
    def iso(model, parameters, unit="kPa"):
        return Isotherm.model_validate(
            {
                "component": "X",
                "model": model,
                "parameters": parameters,
                "pressure_unit": unit,
                "heat_of_adsorption": {"value": 30, "unit": "kJ/mol"},
                "valid": {"temperature": [200, 600], "partial_pressure": [0, 1e4]},
                "source": "closed form",
            }
        )

    t = 320.0
    b = 2e-5 * math.exp(25000 / (R * t))
    dsl = iso(
        "dual-site-langmuir", {"q_s1": 2, "b01": 2e-5, "E1": 25, "q_s2": 1, "b02": 1e-6, "E2": 30}
    )
    b2 = 1e-6 * math.exp(30000 / (R * t))
    assert single_loading(dsl, 10, t) == pytest.approx(
        2 * b * 10 / (1 + b * 10) + b2 * 10 / (1 + b2 * 10)
    )
    # Sips in bar with the temperature dependence of Hefti et al. (2015)
    sips = iso(
        "sips",
        {
            "q_s_ref": 7.0,
            "chi": -0.6,
            "b0": 1e-4,
            "E": 28,
            "n_ref": 0.42,
            "alpha": 0.7,
            "T_ref": 298.15,
        },
        "bar",
    )
    ratio = t / 298.15
    q_s, n = 7.0 * math.exp(-0.6 * (ratio - 1)), 0.42 + 0.7 * (ratio - 1)
    term = (1e-4 * math.exp(28000 / (R * t)) * 0.15) ** n
    assert single_loading(sips, 15, t) == pytest.approx(q_s * term / (1 + term), rel=1e-12)
    # Toth with the temperature dependence of Do (1998): q_s falls with T for chi > 0
    toth = iso(
        "toth",
        {"q_s_ref": 5, "chi": 0.5, "b0": 2e-5, "E": 25, "t_ref": 0.5, "alpha": 0.2, "T_ref": 300},
    )
    tt = 0.5 + 0.2 * (1 - 300 / t)
    q_s_toth = 5 * math.exp(0.5 * (1 - t / 300))
    assert single_loading(toth, 10, t) == pytest.approx(
        q_s_toth * b * 10 / (1 + (b * 10) ** tt) ** (1 / tt), rel=1e-12
    )
    assert q_s_toth < 5


def test_cli_prints_the_function_result(plant, monkeypatch):
    monkeypatch.chdir(plant)
    runner = CliRunner()
    result = runner.invoke(app, ["process", "adsorption", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    expected = adsorption_report(plant).as_dict()
    assert data["units"] == json.loads(json.dumps(expected["units"]))
    text = runner.invoke(app, ["process", "adsorption"])
    assert "A1: TSA calculated (equilibrium-tsa/1) qualified; split consistent" in text.stdout
    assert runner.invoke(app, ["process", "adsorption", "--case", "nope"]).exit_code == 2
    with pytest.raises(UnknownCase):
        adsorption_report(plant, "nope")


def test_the_module_needs_neither_typer_nor_fastapi(plant):
    code = (
        "import sys\n"
        "from chemeascode.domains.process.separations.adsorption import adsorption_report\n"
        f"r = adsorption_report(__import__('pathlib').Path({str(plant)!r}))\n"
        "assert r.units[0].status == 'qualified'\n"
        "assert 'typer' not in sys.modules and 'fastapi' not in sys.modules\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
